"""Briefing read tools — list and fetch past briefings from DynamoDB."""
from langchain_core.tools import tool

from storage.ddb import get_item, query_by_sk_prefix


@tool
def get_briefings(limit: int = 5) -> str:
    """최근 브리핑 목록을 반환합니다 (최신순).

    Args:
        limit: 반환할 브리핑 개수 (기본 5)
    """
    items = query_by_sk_prefix("BRIEF#", limit=limit, ascending=False)
    if not items:
        return "브리핑이 없습니다."
    lines = ["## 최근 브리핑"]
    for item in items:
        date = item.get("date", "?")
        tod = item.get("time_of_day", "?")
        status = item.get("status", "?")
        lines.append(f"- {date} {tod} [{status}]")
    return "\n".join(lines)


@tool
def get_briefing(date: str, time_of_day: str) -> str:
    """특정 브리핑의 전체 내용을 반환합니다.

    Args:
        date: YYYY-MM-DD 형식
        time_of_day: "AM" 또는 "PM"
    """
    tod = time_of_day.upper().strip()
    item = get_item(f"BRIEF#{date}-{tod}")
    if not item:
        return f"{date} {tod} 브리핑을 찾을 수 없습니다."
    content = item.get("content", "")
    status = item.get("status", "?")
    return f"## {date} {tod} 브리핑 ({status})\n\n{content or '(내용 없음)'}"
