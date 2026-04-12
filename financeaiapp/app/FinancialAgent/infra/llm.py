"""LLM provider factory — OpenAI <-> Bedrock switchable at runtime.

Provider can be changed via DDB preference (PREF#llm_provider) without
server restart. Falls back to LLM_PROVIDER env var if no preference set.
Callers should use get_provider() to check the current provider and
invalidate cached instances when it changes.
"""
import os
import threading
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel

from infra.secrets import get_secret
from storage.ddb import get_item

Purpose = Literal["orchestrator", "analyze"]

_DEFAULTS: dict[tuple[str, str], str] = {
    ("openai", "orchestrator"): "gpt-5.4-mini",
    ("openai", "analyze"): "gpt-5.4",
    ("bedrock", "orchestrator"): "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    ("bedrock", "analyze"): "global.anthropic.claude-opus-4-6-v1",
}

_provider_lock = threading.Lock()


def get_provider() -> str:
    """Return current LLM provider — checks DDB preference first, then env var."""
    try:
        pref = get_item("PREF#llm_provider")
        if pref and pref.get("value") in ("openai", "bedrock"):
            return pref["value"]
    except Exception:
        pass
    return os.environ.get("LLM_PROVIDER", "openai").lower()


def get_llm(purpose: Purpose) -> BaseChatModel:
    provider = get_provider()
    env_var = f"{purpose.upper()}_MODEL"
    model = os.environ.get(env_var) or _DEFAULTS.get(
        (provider, purpose), _DEFAULTS[("openai", purpose)]
    )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=get_secret("OPENAI_API_KEY"),
            max_retries=2,
        )
    elif provider == "bedrock":
        from langchain_aws import ChatBedrockConverse

        region = os.environ.get("BEDROCK_REGION", "ap-northeast-2")
        return ChatBedrockConverse(
            model=model,
            region_name=region,
            max_retries=2,
        )
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
