# SNS Event Schema — Strategy Lifecycle & Triggers

**Status:** Draft v1
**Owner:** Platform
**Last updated:** 2026-04-20

---

## 1. Overview

This document defines the JSON payload contract published to SNS topic `financeaiapp-alerts` by the Strategy Agent (LangGraph) and the 30-min strategy monitor cron. The `slack-poster` Lambda (`financeaiapp-infra/src/slack-poster.ts`) is the primary subscriber and renders each payload as a Slack Block Kit message in `#finance-ops`.

### Design principles

1. **Discriminator-first.** Every strategy event carries a top-level `type` field so `slack-poster.ts` can branch in one `switch` instead of shape-sniffing. CloudWatch alarms (which have `AlarmName` + `NewStateValue`) do **not** have `type`, and that is how we distinguish them without breaking the existing path.
2. **Self-contained payloads.** The Lambda must never re-query DDB. If Slack needs it, the publisher puts it in the message. Strategy fields mirror what `create_strategy` stores and what the cron's `execute_node` already computes.
3. **Schema-versioned.** `schema_version` lets us evolve the contract without a flag day. Consumers must treat unknown fields as ignorable.
4. **ISO-8601 UTC timestamps.** Always `Z`-suffixed, produced by `datetime.now(timezone.utc).isoformat()`.
5. **Future-proofed for approvals.** The envelope reserves `correlation_id` and `reply_to` so Phase 3 `strategy_approval_requested` can attach Slack interactive buttons that round-trip back to AgentCore.
6. **Idempotent keys.** `event_id` (ULID/UUIDv7) lets Slack de-duplicate on retry and lets us correlate against DDB `STRATLOG#` entries.

### SNS `Subject` convention

Human-readable short label for email readers, ≤100 chars (SNS hard limit). Format:

```
[financeaiapp] <type> · <strategy_name>
```

Examples: `[financeaiapp] strategy_triggered · btc_100k`, `[financeaiapp] strategy_created · eth_dip_buy`.
The Lambda does not rely on `Subject` for routing — it is cosmetic only.

---

## 2. Common envelope

All strategy events share this envelope. Event-specific fields live under `data`.

| Field | Type | Req | Description |
|---|---|---|---|
| `type` | string enum | yes | `strategy_created` \| `strategy_removed` \| `strategy_toggled` \| `strategy_triggered` (reserved: `strategy_approval_requested`) |
| `schema_version` | string | yes | Semver. Current: `"1.0"` |
| `event_id` | string | yes | ULID or UUIDv7, unique per emission |
| `timestamp` | string (ISO-8601 UTC) | yes | When the event was emitted |
| `source` | string | yes | Emitter: `"strategy_agent"` (chat tools) or `"strategy_monitor_cron"` (30-min graph) |
| `environment` | string | yes | `"prod"` \| `"dev"` \| `"local"` |
| `correlation_id` | string | no | Ties this event to a chat turn / cron run. Required for approval flow (Phase 3). |
| `reply_to` | string | no | Reserved. ARN/URL a Slack interactive callback should POST to. |
| `data` | object | yes | Event-type-specific payload, schemas below. |

### Minimal envelope shape

```json
{
  "type": "strategy_created",
  "schema_version": "1.0",
  "event_id": "01HXYZ...",
  "timestamp": "2026-04-20T03:14:15Z",
  "source": "strategy_agent",
  "environment": "prod",
  "correlation_id": "chat_turn_abc123",
  "data": { /* see per-type sections */ }
}
```

---

## 3. Per-event schemas

### 3.1 `strategy_created`

Emitted by `create_strategy` tool after `upsert_strategy` succeeds.

**`data` fields:**

| Field | Type | Req | Notes |
|---|---|---|---|
| `name` | string | yes | Strategy identifier (no `#` per existing validation) |
| `symbol` | string | yes | Upper-cased target symbol |
| `condition_type` | enum | yes | `price_above` \| `price_below` \| `change_pct_above` \| `change_pct_below` |
| `threshold` | number | yes | Raw numeric threshold |
| `condition_human` | string | yes | Pre-rendered for Slack (e.g. `"가격 > 80,000.00"`) |
| `action` | enum | yes | `alert` \| `buy` \| `sell` |
| `quantity` | number \| null | cond | Required when `action` in `{buy, sell}`, else null |
| `description` | string | no | User-supplied |
| `enabled` | bool | yes | Always `true` on create |
| `created_at` | ISO-8601 | yes | Matches `Strategy.created_at` |
| `actor` | string | no | `"user"` \| `"agent"` — who initiated |

**Example:**

```json
{
  "type": "strategy_created",
  "schema_version": "1.0",
  "event_id": "01HXYA3M7F9B2K8N4P5Q",
  "timestamp": "2026-04-20T03:14:15Z",
  "source": "strategy_agent",
  "environment": "prod",
  "data": {
    "name": "btc_100k",
    "symbol": "BTC",
    "condition_type": "price_above",
    "threshold": 100000,
    "condition_human": "가격 > 100,000.00",
    "action": "alert",
    "quantity": null,
    "description": "BTC 10만 달러 돌파 알림",
    "enabled": true,
    "created_at": "2026-04-20T03:14:15Z",
    "actor": "user"
  }
}
```

---

### 3.2 `strategy_removed`

Emitted by `remove_strategy_tool` after successful `delete_strategy`.

**`data` fields:**

| Field | Type | Req | Notes |
|---|---|---|---|
| `name` | string | yes | Deleted strategy name |
| `symbol` | string | yes | Snapshot of `target_symbol` at delete time |
| `condition_human` | string | no | For Slack context — "what they just killed" |
| `action` | enum | no | Last-known action |
| `trigger_count` | int | no | Lifetime triggers before deletion |
| `last_triggered` | ISO-8601 \| null | no | Last trigger timestamp |
| `actor` | string | no | `"user"` \| `"agent"` |

**Example:**

```json
{
  "type": "strategy_removed",
  "schema_version": "1.0",
  "event_id": "01HXYA4ND0KPQW5R9S1T",
  "timestamp": "2026-04-20T03:20:02Z",
  "source": "strategy_agent",
  "environment": "prod",
  "data": {
    "name": "btc_100k",
    "symbol": "BTC",
    "condition_human": "가격 > 100,000.00",
    "action": "alert",
    "trigger_count": 3,
    "last_triggered": "2026-04-18T22:00:00Z",
    "actor": "user"
  }
}
```

---

### 3.3 `strategy_toggled`

Emitted by `toggle_strategy` after `upsert_strategy`.

**`data` fields:**

| Field | Type | Req | Notes |
|---|---|---|---|
| `name` | string | yes | |
| `symbol` | string | yes | |
| `enabled` | bool | yes | New state after toggle |
| `previous_enabled` | bool | no | State before toggle (for "resumed vs re-paused" clarity) |
| `condition_human` | string | no | For Slack context |
| `action` | enum | no | |
| `actor` | string | no | |

**Example:**

```json
{
  "type": "strategy_toggled",
  "schema_version": "1.0",
  "event_id": "01HXYA5PV2LRS8M6T3U7",
  "timestamp": "2026-04-20T03:25:40Z",
  "source": "strategy_agent",
  "environment": "prod",
  "data": {
    "name": "eth_dip_buy",
    "symbol": "ETH",
    "enabled": false,
    "previous_enabled": true,
    "condition_human": "변동률 < -5.0%",
    "action": "buy",
    "actor": "user"
  }
}
```

---

### 3.4 `strategy_triggered`

Emitted by the cron's `execute_node` once per triggered strategy. Highest-volume and most detail-rich event.

**`data` fields:**

| Field | Type | Req | Notes |
|---|---|---|---|
| `name` | string | yes | Strategy name |
| `symbol` | string | yes | `target_symbol` |
| `action` | enum | yes | `alert` \| `buy` \| `sell` |
| `quantity` | number \| null | cond | Required for buy/sell |
| `condition_type` | enum | yes | |
| `threshold` | number | yes | |
| `condition_human` | string | yes | Pre-rendered condition |
| `price` | number | yes | Spot price at evaluation |
| `currency` | string | yes | Quote currency |
| `change_pct` | number \| null | no | From the evaluated quote |
| `success` | bool | yes | `not result_msg.startswith("❌")` |
| `result_msg` | string | yes | Truncated to 200 chars (DDB log consistency). Populated for all outcomes. |
| `error_msg` | string \| null | cond | Present only when `success=false` AND an exception was caught. Null on clean failures. |
| `fill_price` | number \| null | cond | Present on successful `buy`/`sell`. May equal `price` in paper-trade mode; kept separate so real-fill integration is a non-breaking change. |
| `cash_after` | number \| null | cond | Cash balance after the trade, for Slack context |
| `realized_pnl_pct` | number \| null | no | Only meaningful on `sell` that closed a position |
| `trigger_count` | int | yes | Post-increment count |
| `strategy_log_sk` | string | no | DDB sort key `STRATLOG#{name}#{ts}` — lets Slack link back to the log record |
| `auto_disabled` | bool | no | `true` when this successful trigger caused `enabled=false` to be set. Prevents repeat execution (e.g. exhausting cash on buy-buy-buy). User must manually re-enable via `toggle_strategy`. |

**Example — successful buy:**

```json
{
  "type": "strategy_triggered",
  "schema_version": "1.0",
  "event_id": "01HXYB0QR4MTU6N9V2W1",
  "timestamp": "2026-04-20T04:00:12Z",
  "source": "strategy_monitor_cron",
  "environment": "prod",
  "correlation_id": "cron_run_2026-04-20T04:00Z",
  "data": {
    "name": "eth_dip_buy",
    "symbol": "ETH",
    "action": "buy",
    "quantity": 0.5,
    "condition_type": "change_pct_below",
    "threshold": 5.0,
    "condition_human": "변동률 < -5.0%",
    "price": 2850.42,
    "currency": "USD",
    "change_pct": -5.7,
    "success": true,
    "result_msg": "✅ ETH 0.5개 매수 완료 @ 2,850.42",
    "error_msg": null,
    "fill_price": 2850.42,
    "cash_after": 8574.79,
    "realized_pnl_pct": null,
    "trigger_count": 4,
    "strategy_log_sk": "STRATLOG#eth_dip_buy#2026-04-20T04:00:12Z"
  }
}
```

**Example — alert only:**

```json
{
  "type": "strategy_triggered",
  "schema_version": "1.0",
  "event_id": "01HXYB1S5NVWX7P0Y3Z2",
  "timestamp": "2026-04-20T04:00:12Z",
  "source": "strategy_monitor_cron",
  "environment": "prod",
  "data": {
    "name": "btc_100k",
    "symbol": "BTC",
    "action": "alert",
    "quantity": null,
    "condition_type": "price_above",
    "threshold": 100000,
    "condition_human": "가격 > 100,000.00",
    "price": 100420.11,
    "currency": "USD",
    "change_pct": 1.2,
    "success": true,
    "result_msg": "조건 충족 알림: BTC = 100420.11",
    "error_msg": null,
    "fill_price": null,
    "cash_after": null,
    "realized_pnl_pct": null,
    "trigger_count": 1
  }
}
```

**Example — failed sell:**

```json
{
  "type": "strategy_triggered",
  "schema_version": "1.0",
  "event_id": "01HXYB2T6PWXZ8Q1A4B3",
  "timestamp": "2026-04-20T04:00:12Z",
  "source": "strategy_monitor_cron",
  "environment": "prod",
  "data": {
    "name": "sol_take_profit",
    "symbol": "SOL",
    "action": "sell",
    "quantity": 10,
    "condition_type": "price_above",
    "threshold": 200,
    "condition_human": "가격 > 200.00",
    "price": 204.5,
    "currency": "USD",
    "change_pct": 3.1,
    "success": false,
    "result_msg": "❌ 보유 수량 부족",
    "error_msg": null,
    "fill_price": null,
    "cash_after": null,
    "realized_pnl_pct": null,
    "trigger_count": 2
  }
}
```

---

## 4. Reserved — `strategy_approval_requested` (Phase 3)

Not in scope for this PR; documented so the envelope stays stable.

```json
{
  "type": "strategy_approval_requested",
  "schema_version": "1.0",
  "event_id": "...",
  "timestamp": "...",
  "source": "strategy_monitor_cron",
  "correlation_id": "approval_01HXYZ...",
  "reply_to": "https://agentcore.../callbacks/approval",
  "data": {
    "name": "eth_dip_buy",
    "symbol": "ETH",
    "action": "buy",
    "quantity": 0.5,
    "price": 2850.42,
    "currency": "USD",
    "expires_at": "2026-04-20T04:15:00Z",
    "approval_token": "opaque-signed-jwt"
  }
}
```

`slack-poster` will render this with Block Kit `actions` block (Approve / Reject buttons) whose `value` is `approval_token`, and the interaction handler POSTs to `reply_to`.

---

## 5. Slack rendering hints

All strategy types share a common header format:

```
<icon> *[financeaiapp]* <title>
```

| Type | Icon | Title | Key surfaced fields | Extras |
|---|---|---|---|---|
| `strategy_created` | 🆕 | `전략 등록 · {name}` | `symbol`, `condition_human`, `action` (+ `quantity`), `description` | Context line: "by {actor}" |
| `strategy_removed` | 🗑️ | `전략 삭제 · {name}` | `symbol`, `condition_human`, `trigger_count`, `last_triggered` | Muted color |
| `strategy_toggled` | ⏸️ if `enabled=false` else ▶️ | `전략 {활성\|비활성} · {name}` | `symbol`, `condition_human`, new `enabled` state | — |
| `strategy_triggered` (alert) | 🔔 | `조건 충족 · {name}` | `symbol`, `price`, `currency`, `change_pct`, `condition_human` | — |
| `strategy_triggered` (buy success) | 🟢 | `자동 매수 · {name}` | `symbol`, `quantity`, `fill_price`, `cash_after`, `trigger_count` | Green accent |
| `strategy_triggered` (sell success) | 🔴 | `자동 매도 · {name}` | `symbol`, `quantity`, `fill_price`, `realized_pnl_pct`, `cash_after` | Red/green by pnl sign |
| `strategy_triggered` (any failure) | ⚠️ | `실행 실패 · {name}` | `action`, `symbol`, `result_msg`, `error_msg` | Divider + retry hint |

**Branching rule in `slack-poster.ts`:**

```text
if (parsed.type?.startsWith("strategy_")) → buildStrategyBlocks(parsed)
else if (parsed.AlarmName && parsed.NewStateValue) → buildAlarmBlocks(parsed)   // existing
else → buildFallbackBlocks(subject, message)                                    // existing
```

The new branch is inserted **before** the alarm check so CloudWatch alarms remain unaffected.

---

## 6. Backward compatibility

- **CloudWatch alarm path unchanged.** CloudWatch never sets `type`, so the new branch falls through to the existing `AlarmName`/`NewStateValue` check. No behavior change for alarms.
- **Fallback path unchanged.** Any SNS publisher that does not emit a recognized strategy `type` and is not a CloudWatch alarm still hits `buildFallbackBlocks`. This is the safety net for CLI pokes and ad-hoc `sns publish` calls.
- **Schema evolution.** Consumers MUST ignore unknown envelope fields and unknown `data` keys. Additive changes stay at `schema_version: "1.0"`. Removing or renaming a field bumps to `2.0` and the Lambda gains a version switch.
- **No Subject dependency.** The existing Lambda reads `sns.Subject` only in fallback/error branches. The new branch uses the JSON body exclusively, so Subject remains free-form for humans.
- **Payload size.** SNS hard limit is 256 KB; richest payload (`strategy_triggered` with 200-char `result_msg`) is well under 2 KB.

---

## 7. Publisher checklist

Before emitting an event:

- [ ] All envelope fields populated (`type`, `schema_version`, `event_id`, `timestamp`, `source`, `environment`)
- [ ] `data` required fields present per type
- [ ] Numeric fields are JSON numbers, not strings
- [ ] Timestamps are ISO-8601 UTC with `Z` suffix
- [ ] `result_msg` truncated to 200 chars (DDB log consistency)
- [ ] `Subject` ≤100 chars and follows `[financeaiapp] <type> · <name>` convention
- [ ] SNS publish failure is logged but does not fail the calling tool/graph (fire-and-forget)
