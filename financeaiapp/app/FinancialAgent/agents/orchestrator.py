"""Orchestrator — LangChain create_agent with all Phase 1 tools.

Top-level agent that handles conversation, tool routing, and memory.
The research subgraph (fetch_market ∥ fetch_news → analyze) is exposed as
a single `research` tool; watchlist/briefing/preferences/sessions are
direct DDB tools.
"""
import os

from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver

from agents.research_tool import research
from infra.llm import get_llm
from tools.briefing import get_briefing, get_briefings
from tools.preferences import get_preferences, set_preference
from tools.sessions import list_sessions
from tools.watchlist import add_watchlist, list_watchlist, remove_watchlist

_orchestrator = None
_checkpointer = None


def _load_prompt() -> str:
    prompt_path = os.path.join(
        os.path.dirname(__file__), "..", "prompts", "orchestrator.md"
    )
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def get_orchestrator():
    """Return a module-level cached orchestrator instance.

    Uses an in-memory checkpointer for session persistence within the
    lifetime of the agent process. Each session_id becomes a thread_id.
    """
    global _orchestrator, _checkpointer
    if _orchestrator is None:
        llm = get_llm("orchestrator")
        _checkpointer = InMemorySaver()

        tools = [
            research,
            list_watchlist,
            add_watchlist,
            remove_watchlist,
            get_briefings,
            get_briefing,
            get_preferences,
            set_preference,
            list_sessions,
        ]

        _orchestrator = create_agent(
            model=llm,
            tools=tools,
            system_prompt=_load_prompt(),
            checkpointer=_checkpointer,
        )
    return _orchestrator
