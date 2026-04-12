"""Secrets loader — always reads from AWS Secrets Manager.

Single code path for local dev and cloud:
- Local `agentcore dev` mounts ~/.aws read-only and forwards AWS_PROFILE,
  so boto3 uses the developer's credentials to fetch the secret.
- Deployed AgentCore Runtime uses its execution role (which must have
  `secretsmanager:GetSecretValue` on the target secret ARN).

No fallback, no env-var branch — one deterministic load path.
"""
import json
import os
from functools import lru_cache

import boto3


@lru_cache(maxsize=1)
def load_secrets() -> dict:
    """Fetch all secrets from AWS Secrets Manager once per process."""
    secret_id = os.environ.get("SECRETS_ID", "financial-bot/api-keys")
    region = os.environ.get("AWS_REGION", "ap-northeast-2")
    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=secret_id)
    return json.loads(response["SecretString"])


def get_secret(key: str) -> str:
    return load_secrets().get(key, "")
