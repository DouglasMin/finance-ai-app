"""User preference tools — explicit preferences stored in DynamoDB.

[phase-forward] In Phase 2, consider migrating to AgentCore Memory's
UserPreferenceMemoryStrategy for auto-learned preferences. Phase 1 uses
explicit tool-triggered preferences only.
"""
from datetime import datetime, timezone

from langchain_core.tools import tool

from storage.ddb import put_item, query_by_sk_prefix


@tool
def get_preferences() -> str:
    """사용자 선호도 전체를 반환합니다."""
    items = query_by_sk_prefix("PREF#")
    if not items:
        return "저장된 선호도가 없습니다."
    lines = ["## 사용자 선호도"]
    for item in items:
        key = (item.get("SK", "")).replace("PREF#", "")
        value = item.get("value", "")
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


@tool
def set_preference(key: str, value: str) -> str:
    """사용자 선호도를 설정합니다.

    예: set_preference("tone", "concise") → 응답 톤을 간결하게
         set_preference("language", "ko") → 기본 언어 한국어
         set_preference("focus", "crypto") → 주요 관심사 크립토
    """
    put_item(
        f"PREF#{key}",
        {
            "value": value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return f"✅ 선호도 '{key}' = '{value}' 저장됨"
