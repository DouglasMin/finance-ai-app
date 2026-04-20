"""Strategy management tools — register/list/toggle condition-based strategies.

Strategies are persisted in DDB (STRATEGY#{name}) and evaluated by the
strategy monitoring subgraph on a 30-minute EventBridge cron.
"""
from datetime import datetime, timezone

from langchain_core.tools import tool

from infra.formatting import format_price
from infra.sns import publish_strategy_event
from storage.trading import (
    delete_strategy,
    get_strategy,
    list_strategies,
    log_strategy_trigger,
    upsert_strategy,
)
from schemas.trading import Strategy
from storage.ddb import query_by_sk_prefix


_CONDITION_HUMAN = {
    "price_above": lambda t: f"가격 > {t:,.2f}",
    "price_below": lambda t: f"가격 < {t:,.2f}",
    "change_pct_above": lambda t: f"변동률 > +{t:.1f}%",
    "change_pct_below": lambda t: f"변동률 < -{t:.1f}%",
}


def _condition_human(condition_type: str, threshold: float) -> str:
    renderer = _CONDITION_HUMAN.get(condition_type)
    return renderer(threshold) if renderer else f"{condition_type} {threshold}"


@tool
def create_strategy(
    name: str,
    target_symbol: str,
    condition_type: str,
    threshold: float,
    action: str,
    quantity: float = 0,
    description: str = "",
) -> str:
    """조건 기반 전략을 등록합니다.

    예: "BTC가 $100K 넘으면 알려줘" → create_strategy(
        name="btc_100k", target_symbol="BTC",
        condition_type="price_above", threshold=100000,
        action="alert"
    )

    Args:
        name: 전략 이름 (고유 식별자)
        target_symbol: 모니터링할 종목 심볼
        condition_type: 조건 유형 — price_above, price_below, change_pct_above, change_pct_below
        threshold: 임계값 (가격 또는 변동률 %)
        action: 충족 시 행동 — alert (알림만), buy (가상 매수), sell (가상 매도)
        quantity: 매수/매도 수량 (action이 buy/sell일 때 필수)
        description: 전략 설명 (선택)
    """
    if "#" in name:
        return "❌ 전략 이름에 '#' 문자는 사용할 수 없습니다."
    if condition_type not in ("price_above", "price_below", "change_pct_above", "change_pct_below"):
        return f"❌ 잘못된 condition_type: {condition_type}"
    if action not in ("alert", "buy", "sell"):
        return f"❌ 잘못된 action: {action}"
    if action in ("buy", "sell") and quantity <= 0:
        return "❌ buy/sell action에는 quantity(>0)가 필요합니다."

    existing = get_strategy(name)
    if existing:
        return f"❌ '{name}' 전략이 이미 존재합니다. 다른 이름을 사용해 주세요."

    strategy = Strategy(
        name=name,
        description=description,
        target_symbol=target_symbol.upper().strip(),
        condition_type=condition_type,
        threshold=threshold,
        action=action,
        quantity=quantity if quantity > 0 else None,
        enabled=True,
        created_at=datetime.now(timezone.utc),
    )
    upsert_strategy(strategy)

    condition_str = _condition_human(condition_type, threshold)

    action_str = {"alert": "알림", "buy": f"매수 {quantity}개", "sell": f"매도 {quantity}개"}[action]

    publish_strategy_event(
        "strategy_created",
        {
            "name": strategy.name,
            "symbol": strategy.target_symbol,
            "condition_type": condition_type,
            "threshold": threshold,
            "condition_human": condition_str,
            "action": action,
            "quantity": strategy.quantity,
            "description": description,
            "enabled": True,
            "created_at": strategy.created_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "actor": "user",
        },
    )

    return (
        f"✅ 전략 등록 완료: **{name}**\n"
        f"종목: {target_symbol.upper()} | 조건: {condition_str} | 행동: {action_str}\n"
        f"30분마다 자동 체크됩니다."
    )


@tool
def list_all_strategies() -> str:
    """등록된 모든 전략의 목록과 상태를 반환합니다."""
    strategies = list_strategies()
    if not strategies:
        return "등록된 전략이 없습니다."

    lines = ["## ⚙️ 전략 목록\n"]
    for s in strategies:
        status = "🟢 활성" if s.enabled else "⚪ 비활성"
        condition = {
            "price_above": f"> {s.threshold:,.2f}",
            "price_below": f"< {s.threshold:,.2f}",
            "change_pct_above": f"> +{s.threshold:.1f}%",
            "change_pct_below": f"< -{s.threshold:.1f}%",
        }.get(s.condition_type, s.condition_type)

        action_str = {"alert": "알림", "buy": "매수", "sell": "매도"}.get(s.action, s.action)
        if s.quantity:
            action_str += f" {s.quantity:,.4g}개"

        triggered = f" | 마지막 트리거: {str(s.last_triggered)[:16]}" if s.last_triggered else ""

        lines.append(
            f"- **{s.name}** {status}\n"
            f"  {s.target_symbol} {condition} → {action_str}"
            f" | 횟수: {s.trigger_count}{triggered}"
        )
    return "\n".join(lines)


@tool
def remove_strategy_tool(name: str) -> str:
    """전략을 삭제합니다.

    Args:
        name: 삭제할 전략 이름
    """
    existing = get_strategy(name)
    if not existing:
        return f"❌ '{name}' 전략을 찾을 수 없습니다."
    delete_strategy(name)

    publish_strategy_event(
        "strategy_removed",
        {
            "name": existing.name,
            "symbol": existing.target_symbol,
            "condition_human": _condition_human(existing.condition_type, existing.threshold),
            "action": existing.action,
            "trigger_count": existing.trigger_count,
            "last_triggered": (
                existing.last_triggered.isoformat(timespec="seconds").replace("+00:00", "Z")
                if existing.last_triggered
                else None
            ),
            "actor": "user",
        },
    )

    return f"🗑️ '{name}' 전략이 삭제되었습니다."


@tool
def toggle_strategy(name: str, enabled: bool) -> str:
    """전략을 활성화/비활성화합니다.

    Args:
        name: 전략 이름
        enabled: True = 활성화, False = 비활성화
    """
    existing = get_strategy(name)
    if not existing:
        return f"❌ '{name}' 전략을 찾을 수 없습니다."
    previous_enabled = existing.enabled
    existing.enabled = enabled
    upsert_strategy(existing)
    status = "활성화" if enabled else "비활성화"

    publish_strategy_event(
        "strategy_toggled",
        {
            "name": existing.name,
            "symbol": existing.target_symbol,
            "enabled": enabled,
            "previous_enabled": previous_enabled,
            "condition_human": _condition_human(existing.condition_type, existing.threshold),
            "action": existing.action,
            "actor": "user",
        },
    )

    return f"✅ '{name}' 전략이 {status}되었습니다."


@tool
def get_strategy_log(name: str, limit: int = 10) -> str:
    """전략의 실행 이력을 반환합니다.

    Args:
        name: 전략 이름
        limit: 반환할 이력 수 (기본 10)
    """
    existing = get_strategy(name)
    if not existing:
        return f"❌ '{name}' 전략을 찾을 수 없습니다."

    items = query_by_sk_prefix(
        f"STRATLOG#{name}#", limit=min(max(limit, 1), 50), ascending=False
    )
    if not items:
        return f"'{name}' 전략의 실행 이력이 없습니다."

    lines = [f"## 📋 '{name}' 실행 이력\n"]
    for item in items:
        ts = str(item.get("updated_at", ""))[:16]
        result = item.get("result", "")
        price = item.get("price")
        price_str = f" @ {price}" if price else ""
        lines.append(f"- {ts}{price_str} → {result}")
    return "\n".join(lines)
