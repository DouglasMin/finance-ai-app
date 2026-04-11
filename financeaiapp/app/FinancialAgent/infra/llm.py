"""LLM provider factory — OpenAI <-> Bedrock switchable via env var.

Reads LLM_PROVIDER ("openai" | "bedrock") and {PURPOSE}_MODEL to return the
appropriate chat model. Keeps agent code provider-agnostic.

Defaults:
    LLM_PROVIDER=openai
    ORCHESTRATOR_MODEL=gpt-5.4-mini
    ANALYZE_MODEL=gpt-5.4

Bedrock override example:
    LLM_PROVIDER=bedrock
    ORCHESTRATOR_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
    ANALYZE_MODEL=us.anthropic.claude-sonnet-4-5-20250929-v1:0
"""
import os
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel

from infra.secrets import get_secret

Purpose = Literal["orchestrator", "analyze"]

_DEFAULTS: dict[tuple[str, str], str] = {
    ("openai", "orchestrator"): "gpt-5.4-mini",
    ("openai", "analyze"): "gpt-5.4",
    ("bedrock", "orchestrator"): "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    ("bedrock", "analyze"): "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
}


def get_llm(purpose: Purpose) -> BaseChatModel:
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()
    env_var = f"{purpose.upper()}_MODEL"
    model = os.environ.get(env_var) or _DEFAULTS[(provider, purpose)]

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=get_secret("OPENAI_API_KEY"),
            max_retries=2,
        )
    elif provider == "bedrock":
        from langchain_aws import ChatBedrockConverse

        region = os.environ.get("BEDROCK_REGION", "us-east-1")
        return ChatBedrockConverse(
            model=model,
            region_name=region,
            max_retries=2,
        )
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
