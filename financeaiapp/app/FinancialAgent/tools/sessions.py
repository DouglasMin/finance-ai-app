"""Session metadata tools and helpers (LangGraph checkpointer handles messages)."""
from datetime import datetime, timezone

from langchain_core.tools import tool

from storage.ddb import get_item, put_item, query_by_sk_prefix


@tool
def list_sessions(limit: int = 20) -> str:
    """최근 대화 세션 목록을 반환합니다 (최신순).

    Args:
        limit: 반환할 세션 개수 (기본 20)
    """
    items = query_by_sk_prefix("SESS#", limit=limit, ascending=False)
    if not items:
        return "세션이 없습니다."
    lines = ["## 최근 세션"]
    for item in items:
        title = item.get("title", "제목 없음")
        count = item.get("message_count", 0)
        last = (item.get("last_active_at") or "")[:10]
        lines.append(f"- {title} ({count}개 메시지, 최근: {last})")
    return "\n".join(lines)


def upsert_session(
    session_id: str, title: str = "", increment_message: bool = True
) -> None:
    """Internal helper — NOT a tool. Called from main.py entrypoint."""
    existing = get_item(f"SESS#{session_id}")
    now = datetime.now(timezone.utc).isoformat()
    if existing:
        count = int(existing.get("message_count", 0)) + (1 if increment_message else 0)
        put_item(
            f"SESS#{session_id}",
            {
                "title": existing.get("title") or title,
                "created_at": existing.get("created_at", now),
                "last_active_at": now,
                "message_count": count,
            },
        )
    else:
        put_item(
            f"SESS#{session_id}",
            {
                "title": title or "새 대화",
                "created_at": now,
                "last_active_at": now,
                "message_count": 1 if increment_message else 0,
            },
        )
