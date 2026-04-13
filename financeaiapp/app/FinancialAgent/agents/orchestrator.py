"""Orchestrator — LangChain create_agent with all Phase 1 tools.

Top-level agent that handles conversation, tool routing, and memory.
Detects LLM provider changes at runtime and recreates the agent
without server restart. Checkpointer uses AgentCore Memory for
persistent conversation history across container restarts.
"""
import os
import threading
from pathlib import Path

from langchain.agents import create_agent
from langgraph_checkpoint_aws import AgentCoreMemorySaver

from agents.research_tool import research
from infra.llm import get_llm, get_provider
from tools.briefing import get_briefing, get_briefings
from tools.compare_analysis import compare_analysis, watchlist_changes
from tools.compare_tickers import compare_tickers
from tools.news_previews import fetch_news_previews
from tools.preferences import get_preferences, set_preference
from tools.sessions import list_sessions
from tools.watchlist import add_watchlist, list_watchlist, remove_watchlist
from tools.watchlist_report import watchlist_report

_orchestrator = None
_current_provider: str | None = None
_orchestrator_lock = threading.Lock()

_prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "orchestrator.md"
_orchestrator_prompt: str | None = None

MEMORY_ID = os.environ.get(
    "AGENTCORE_MEMORY_ID", "FinancialAgentMemory-zkfgNCGggq"
)
REGION = os.environ.get("AWS_REGION", "ap-northeast-2")

# Persistent checkpointer — survives container restarts
_checkpointer: AgentCoreMemorySaver | None = None


def _load_prompt() -> str:
    global _orchestrator_prompt
    if _orchestrator_prompt is None:
        _orchestrator_prompt = _prompt_path.read_text(encoding="utf-8")
    return _orchestrator_prompt


def _get_checkpointer() -> AgentCoreMemorySaver:
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = AgentCoreMemorySaver(MEMORY_ID, region_name=REGION)
    return _checkpointer


_TOOLS = [
    research,
    compare_tickers,
    fetch_news_previews,
    watchlist_report,
    compare_analysis,
    watchlist_changes,
    list_watchlist,
    add_watchlist,
    remove_watchlist,
    get_briefings,
    get_briefing,
    get_preferences,
    set_preference,
    list_sessions,
]


def get_orchestrator():
    """Return cached orchestrator, recreating if LLM provider changed."""
    global _orchestrator, _current_provider

    provider = get_provider()
    if _orchestrator is not None and _current_provider == provider:
        return _orchestrator

    with _orchestrator_lock:
        if _orchestrator is not None and _current_provider == provider:
            return _orchestrator
        llm = get_llm("orchestrator")
        _orchestrator = create_agent(
            model=llm,
            tools=_TOOLS,
            system_prompt=_load_prompt(),
            checkpointer=_get_checkpointer(),
        )
        _current_provider = provider
    return _orchestrator
