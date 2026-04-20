"""SNS publisher for strategy lifecycle + trigger events.

Fire-and-forget: failures are logged but never raised, so the calling
tool/graph node always succeeds regardless of notification delivery.
Schema contract: docs/sns-event-schema.md.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Literal

import boto3
import structlog
from ulid import ULID

log = structlog.get_logger(__name__)

SCHEMA_VERSION = "1.0"

StrategyEventType = Literal[
    "strategy_created",
    "strategy_removed",
    "strategy_toggled",
    "strategy_triggered",
]

_client = None
_client_lock = threading.Lock()


def _get_client():
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                region = os.environ.get("AWS_REGION", "ap-northeast-2")
                _client = boto3.client("sns", region_name=region)
    return _client


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _sanitize_header(value: str) -> str:
    """Strip newlines/carriage returns to prevent header injection."""
    return value.replace("\n", " ").replace("\r", " ").replace("\t", " ")


def publish_strategy_event(
    event_type: StrategyEventType,
    data: dict[str, Any],
    *,
    source: Literal["strategy_agent", "strategy_monitor_cron"] = "strategy_agent",
    correlation_id: str | None = None,
) -> None:
    """Publish a strategy event envelope to the alert SNS topic.

    Never raises. Silently logs and returns if ALERT_TOPIC_ARN is unset,
    SNS client fails, or the topic rejects the message.
    """
    topic_arn = os.environ.get("ALERT_TOPIC_ARN")
    if not topic_arn:
        log.debug("sns.skip_no_topic", event_type=event_type)
        return

    envelope = {
        "type": event_type,
        "schema_version": SCHEMA_VERSION,
        "event_id": str(ULID()),
        "timestamp": now_iso(),
        "source": source,
        "environment": os.environ.get("ENVIRONMENT", "prod"),
        "data": data,
    }
    if correlation_id:
        envelope["correlation_id"] = correlation_id

    name = _sanitize_header(str(data.get("name", "unknown")))
    subject = _truncate(f"[financeaiapp] {event_type} · {name}", 100)

    try:
        client = _get_client()
        resp = client.publish(
            TopicArn=topic_arn,
            Subject=subject,
            Message=json.dumps(envelope, ensure_ascii=False, default=str),
        )
        log.info(
            "sns.published",
            event_type=event_type,
            message_id=resp.get("MessageId"),
            name=name,
        )
    except Exception as e:
        log.warning(
            "sns.publish_failed",
            event_type=event_type,
            name=name,
            error=str(e),
        )
