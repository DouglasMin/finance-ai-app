"""Secrets loader — env vars locally, Secrets Manager in cloud."""
import json
import os
from functools import lru_cache

import boto3

_ENV_KEYS = (
    "OPENAI_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
    "FINNHUB_API_KEY",
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
    "LANGSMITH_API_KEY",
)


@lru_cache(maxsize=1)
def load_secrets() -> dict:
    """Load secrets from env vars locally, or Secrets Manager in cloud."""
    # Local dev: prefer env vars if at least one key is present
    if any(os.environ.get(k) for k in _ENV_KEYS):
        return {k: os.environ.get(k, "") for k in _ENV_KEYS}

    # Cloud: load from Secrets Manager
    secret_id = os.environ.get("SECRETS_ID", "financial-bot/api-keys")
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=secret_id)
    return json.loads(response["SecretString"])


def get_secret(key: str) -> str:
    return load_secrets().get(key, "")
