# Financial Agent — Phase 1 Design

**Date:** 2026-04-11
**Status:** Draft → review
**Scope:** Phase 1 of a multi-phase personal AI financial bot

---

## Context

This document specifies Phase 1 of porting an existing Slack-based financial briefing bot to a web-native, AgentCore-first architecture. The existing bot (https://github.com/DouglasMin/slack-financial-bot) runs on Node.js + Serverless Framework + OpenAI Agents SDK with 5 Lambda functions.

Phase 1 does **not** include trading execution. That is Phase 2+.

## Phase Roadmap (for context)

| Phase | Goal | Status |
|-------|------|--------|
| **1 — Port** | Web UI, conversational agent, scheduled briefings, watchlist | **This doc** |
| 1.5 — Alerts | Price alerts via browser notification or email | Future |
| 2 — Paper Trading | Strategy agent, virtual portfolio, PnL tracking | Future |
| 3 — HITL Trading | Real trades with Slack-style approval (LangGraph HITL) | Future |
| 4 — Limited Auto | Policy Engine for bounded auto-execution | Future |
| 5 — Production | WebSocket streaming, backtesting, multi-strategy | Future |

Design decisions in Phase 1 must **not paint Phase 2–5 into a corner**. Critical forward-compatible choices are flagged in this document with `[phase-forward]`.

## Goals

1. **Feature parity** with existing Slack bot's core capabilities (conversation, market queries, news, analysis, briefings, watchlist)
2. **Web-native** React UI replacing Slack entirely
3. **AgentCore-first**: all agent logic in AgentCore Runtime, minimal Lambda (only where AgentCore can't natively receive events)
4. **Production-grade foundations**: observability, error handling, cost guardrails from Day 1
5. **Korean market coverage** upgrade: pykrx for KOSPI/KOSDAQ, Naver News API for Korean financial news
6. **Personal single-user** deployment to AWS (not multi-tenant)

## Non-Goals (Phase 1)

- Real-time WebSocket price streaming (Phase 5)
- Trading execution (Phase 2+)
- Price alerts (Phase 1.5)
- Mobile app
- Multi-user / tenant isolation
- Browser push notifications

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│              React Web UI                       │
│  · Terminal Feed aesthetic (amber on black)     │
│  · 3-pane: sessions | watchlist | chat          │
│  · S3 + CloudFront                              │
└─────────────────────────────────────────────────┘
                     │
                     │ UI password gate
                     │ Cognito Identity Pool (guest)
                     │ IAM SigV4 → AgentCore
                     ↓
┌─────────────────────────────────────────────────┐
│          AgentCore Runtime (Python)             │
│                                                 │
│  Orchestrator (LangChain create_agent)          │
│    tools:                                       │
│      - research (→ LangGraph subgraph)          │
│      - list_watchlist                           │
│      - add_watchlist / remove_watchlist         │
│      - get_briefings                            │
│      - get_preferences / set_preference         │
│                                                 │
│  Research Subgraph (LangGraph)                  │
│    START → [fetch_market‖fetch_news] → analyze │
│                                                 │
│  AgentCore Memory                               │
│    · session-scoped short-term only (minimal)   │
└─────────────────────────────────────────────────┘
         │                              ↑
         │ DynamoDB (single-table)      │
         ↓                              │ Lambda proxy
┌──────────────────┐          ┌─────────────────┐
│  financial-bot   │          │  EventBridge    │
│  - watchlist     │          │  cron(KST 09/18)│
│  - briefings     │          └─────────────────┘
│  - sessions      │
│  - preferences   │
└──────────────────┘
```

## Components

### 1. Frontend — React Web UI

**Tech stack:**
- Vite + React 19 + TypeScript
- TailwindCSS v4
- AWS Amplify (`@aws-amplify/core`, `@aws-amplify/auth`) for Cognito Identity Pool integration
- `@smithy/signature-v4` (automatic via AWS SDK) for AgentCore IAM signing
- `@aws-sdk/client-bedrock-agentcore-runtime` for `InvokeAgentRuntime` calls

**Layout (3-pane):**
```
┌──────────┬──────────┬───────────────────┐
│ Sessions │ Watchlist│  Chat Thread      │
│ + Briefs │          │                   │
│          │          │  Messages stream  │
│ [+ new]  │ [BTC +2%]│  with tool calls  │
│ · BTC... │ [TSLA-1%]│  visible          │
│ · TSLA...│ [NVDA+1%]│                   │
│          │ [+ add]  │  [input + send]   │
└──────────┴──────────┴───────────────────┘
```

**Aesthetic: "Terminal Feed"**
- Background: `#0a0e0f` (near black)
- Foreground: `#fba91a` (amber)
- Highlights: `#39ff14` (up), `#ff4444` (down)
- Fonts: JetBrains Mono (body), IBM Plex Mono (data)
- CRT scanlines + vignette overlay
- Fixed-width numeric columns for prices

**Session model:**
- User explicitly creates sessions via "+ new" button
- Sessions have auto-generated titles from first message
- Briefings are a separate section (not in sessions list)
- Click a briefing to open read-only view (not a chat)

**Auth flow:**
1. First visit → password prompt
2. Password is a hardcoded constant in `.env` baked into build (frontend-only check, not real auth)
3. On success, store flag in `localStorage`
4. AWS Amplify initializes Cognito Identity Pool in guest mode → returns temporary IAM credentials
5. All subsequent calls to AgentCore use those credentials (SigV4 automatic)

**Security note:** The password gate is obfuscation, not security. The real access boundary is the IAM policy on the Identity Pool guest role, scoped to a single AgentCore Runtime ARN. See Security section below.

### 2. Backend — AgentCore Runtime

**Tech stack:**
- Python 3.13 (Container build)
- `langchain` + `langchain-openai` + `langgraph`
- `bedrock-agentcore` SDK
- `pydantic` for API response validation
- `tenacity` for retry logic
- `cachetools` for TTL caching
- `langsmith` for tracing (optional env flag)

**Agent structure (2-agent):**

```python
# agents/orchestrator.py
orchestrator = create_agent(
    model=ChatOpenAI(model="gpt-5-mini", max_retries=2),
    tools=[research_tool, *watchlist_tools, *briefing_tools, *preference_tools],
    prompt=ORCHESTRATOR_SYSTEM_PROMPT,
    # Reviewer recommendation: cap tool calls to prevent loops
    # LangChain enforces this via max_iterations on AgentExecutor equivalent
)
```

**Research subgraph:**

```python
# agents/research_graph.py
class ResearchState(TypedDict):
    query: str
    tickers: list[str]
    lang: Literal["ko", "en"]
    market_data: MarketSnapshot | None
    news_data: NewsSnapshot | None
    analysis: str | None
    errors: list[str]

graph = StateGraph(ResearchState)
graph.add_node("fetch_market", fetch_market_node)
graph.add_node("fetch_news", fetch_news_node)
graph.add_node("analyze", analyze_node)

graph.add_edge(START, "fetch_market")
graph.add_edge(START, "fetch_news")  # parallel fan-out
graph.add_edge("fetch_market", "analyze")
graph.add_edge("fetch_news", "analyze")
graph.add_edge("analyze", END)

research_graph = graph.compile()

# Exposed to orchestrator as a single tool
@tool
def research(query: str, tickers: list[str] = None, lang: str = "ko") -> str:
    """Fetches market + news data in parallel and produces structured analysis."""
    result = research_graph.invoke({
        "query": query,
        "tickers": tickers or [],
        "lang": lang,
        "market_data": None,
        "news_data": None,
        "analysis": None,
        "errors": [],
    })
    return format_research_result(result)
```

**Node implementations:**

- **`fetch_market_node`**: Pure Python. Calls tool functions in parallel (`asyncio.gather`) for OKX, Alpha Vantage, pykrx, Frankfurter. Each tool has its own timeout + retry + circuit breaker + cache. Returns `MarketSnapshot` Pydantic model. NO LLM.
- **`fetch_news_node`**: Pure Python. Calls Naver News, Finnhub, AV NEWS_SENTIMENT in parallel. Returns `NewsSnapshot` Pydantic model. NO LLM.
- **`analyze_node`**: LLM call. Model: `gpt-5`. Input: `MarketSnapshot` + `NewsSnapshot` + user query. Output: structured analysis text. Has system prompt focused on concise, evidence-based reasoning.

**Why pure Python nodes for retrieval?** The reviewer flagged that "retrieval on gpt-5-mini" was still a reasoning loop. For data fetching, the LLM is pure overhead — we know exactly what to fetch based on the ticker list. Let Python do the parallel fetching. Only the `analyze` step uses an LLM.

**Custom HTTP routes (Starlette):**

```python
app = BedrockAgentCoreApp()

# Orchestrator invocation (primary)
@app.entrypoint
async def invoke(payload, context):
    # payload: { action: "chat"|"briefing", session_id, message, ... }
    ...

# Briefing generation (called by Lambda proxy from EventBridge)
async def generate_briefing(request: Request) -> JSONResponse:
    ...

app.add_route("/briefing", generate_briefing, methods=["POST"])
```

### 3. LangGraph Research Subgraph — Detailed

**Why LangGraph (not agent.as_tool):**
- Explicit parallel fan-out via edges from START
- Per-node streaming visible to UI
- Typed state shared across nodes
- Per-node timeouts and error handling
- Observable as a flat graph, not nested loops

**Tools used inside nodes (decorators on plain Python functions, NOT exposed to orchestrator LLM):**

| Tool | Source | Cache TTL | Timeout | Retries |
|------|--------|-----------|---------|---------|
| `get_crypto_price_okx` | OKX public | 30s | 5s | 3 |
| `get_us_stock_alphavantage` | Alpha Vantage | 30s | 5s | 3 |
| `get_kr_stock_pykrx` | pykrx | 30s | 10s | 2 |
| `get_fx_frankfurter` | Frankfurter | 5min | 5s | 3 |
| `search_naver_news` | Naver Search | 5min | 10s | 2 |
| `get_finnhub_company_news` | Finnhub | 5min | 5s | 3 |
| `get_av_sentiment_news` | Alpha Vantage | 5min | 10s | 2 |

Every tool:
1. Validates response with Pydantic model
2. Wraps in `tenacity.retry(stop_after_attempt=N, wait=exponential)`
3. Caches result with `cachetools.TTLCache`
4. Circuit-broken via manual state ("if last N calls failed, skip for next M seconds")
5. Emits structured log with correlation ID

### 4. Memory Strategy — Minimal

**Enabled:**
- Session-scoped short-term memory (AgentCore Memory default, auto-managed)

**Disabled for Phase 1:**
- `SummaryMemoryStrategy` — defer to Phase 1.5 when we have enough session data to make summaries useful
- `UserPreferenceMemoryStrategy` — defer, use explicit `set_preference` tool in orchestrator instead
- `SemanticMemoryStrategy` — not needed
- `EpisodicMemoryStrategy` — not needed

**Explicit preferences (not auto-learned):**
- `PK=USER#me SK=PREF#<key>` in DynamoDB
- Orchestrator has `set_preference(key, value)` and `get_preferences()` tools
- System prompt loads preferences at session start and injects into context

**[phase-forward]** If Phase 2 needs preference learning, we can enable `UserPreferenceMemoryStrategy` and migrate the explicit PREF records to AgentCore Memory.

### 5. Data Sources — Option 3 (Balanced)

**Added:**
- `pykrx` — accurate KOSPI/KOSDAQ data (no API key)
- Naver Search News API — Korean financial news (25k req/day free)
- Frankfurter — unlimited free FX (ECB-backed, no key)

**Kept:**
- OKX public — crypto (no key)
- Alpha Vantage — US stocks primary, NEWS_SENTIMENT for ticker-specific sentiment (25 req/day ⚠️)
- Finnhub — US company news (60/min free)
- ExchangeRate-API — FX backup

**Removed:**
- NewsData.io — general news, not finance-focused enough
- OpenAI Agents SDK — replaced by LangChain + LangGraph

**API keys required:**
- `OPENAI_API_KEY`
- `ALPHA_VANTAGE_API_KEY` (existing)
- `FINNHUB_API_KEY` (existing)
- `NAVER_CLIENT_ID` + `NAVER_CLIENT_SECRET` (new, free signup at developers.naver.com)

### 6. State Storage — DynamoDB Single-Table

**Table name:** `financial-bot`
**Billing mode:** PAY_PER_REQUEST
**TTL attribute:** `expireAt` (optional, for soft-delete cleanup)

**Key schema:**
- Partition key (`PK`): String
- Sort key (`SK`): String

**Access patterns:**

| Access | PK | SK | Notes |
|--------|----|----|-------|
| Get user profile | `USER#me` | `PROFILE` | single item |
| List watchlist | `USER#me` | `begins_with(WATCH#)` | Query |
| Add/remove watch | `USER#me` | `WATCH#<symbol>` | PutItem/DeleteItem |
| Get briefing | `USER#me` | `BRIEF#<yyyy-mm-dd>-<AM|PM>` | GetItem |
| List recent briefings | `USER#me` | `begins_with(BRIEF#)` + Limit | Query descending |
| List sessions | `USER#me` | `begins_with(SESS#)` | Query |
| Get session metadata | `USER#me` | `SESS#<uuid>` | GetItem |
| Get preference | `USER#me` | `PREF#<key>` | GetItem |
| List all preferences | `USER#me` | `begins_with(PREF#)` | Query |

**Item shapes (examples):**

```json
// Watchlist
{
  "PK": "USER#me",
  "SK": "WATCH#BTC",
  "symbol": "BTC",
  "category": "crypto",
  "added_at": "2026-04-10T09:00:00Z"
}

// Briefing
{
  "PK": "USER#me",
  "SK": "BRIEF#2026-04-10-AM",
  "date": "2026-04-10",
  "time_of_day": "AM",
  "status": "success",
  "content": "...",
  "tickers_covered": ["BTC", "TSLA", "NVDA"],
  "generated_at": "2026-04-10T00:01:23Z",
  "duration_ms": 12400,
  "errors": []
}

// Session (metadata only; messages in AgentCore Memory)
{
  "PK": "USER#me",
  "SK": "SESS#01HQK...",
  "title": "BTC long view",
  "created_at": "2026-04-10T09:12:34Z",
  "last_active_at": "2026-04-10T09:25:10Z",
  "message_count": 8
}

// Preference
{
  "PK": "USER#me",
  "SK": "PREF#tone",
  "value": "concise",
  "updated_at": "2026-04-10T09:00:00Z"
}
```

**Briefing status enum:**
- `pending` — scheduled, not yet started
- `in_progress` — generation running
- `partial` — completed but some data sources failed
- `success` — all sources OK
- `failed` — generation failed

**[phase-forward]** Phase 2 will add `POSITION#<symbol>`, `ORDER#<id>`, `STRATEGY#<name>` under the same `USER#me` PK. Single-table design accommodates this without migration.

### 7. Scheduled Briefings

**Schedule:**
- Morning: 09:00 KST (00:00 UTC)
- Evening: 18:00 KST (09:00 UTC)

**Flow:**

```
EventBridge Rule (cron)
    ↓ invokes
Lambda Proxy (small, ~30 lines)
    ↓ with retry logic
    ↓ signed IAM call
AgentCore Runtime POST /briefing
    ↓
Orchestrator.generate_briefing(time_of_day)
    ↓
Research Subgraph (fetches all watchlist data)
    ↓
Analysis node (formats briefing)
    ↓
Write to DynamoDB (PK=USER#me SK=BRIEF#...)
    ↓ on failure or timeout
SQS DLQ
    ↓
CloudWatch alarm if no briefing written by T+15min
```

**Why Lambda proxy (not direct EventBridge → AgentCore)?**
The reviewer flagged direct EventBridge invocation as harder to debug and lacking explicit retry logic. A thin Lambda (~30 lines) provides:
- Explicit retry with exponential backoff on AgentCore call failure
- Structured error logging
- DLQ integration
- Easier to add future logic (e.g., skip briefing on market holidays)

### 8. Authentication & Security

**Threat model:** Single-user personal bot. The primary threats are:
1. **Financial DoS** — an attacker who discovers the endpoint drains OpenAI credits
2. **Credit abuse** — runaway bot or loop burns through OpenAI quota

**NOT threats:**
1. Data leakage — market data is public
2. Account compromise — no user accounts exist

**Defense layers:**

| Layer | Control |
|-------|---------|
| Obfuscation | Password gate in React (hardcoded at build time, UI-only) |
| Network | CloudFront in front of frontend + AgentCore (optional WAF) |
| Identity | Cognito Identity Pool guest role, scoped IAM policy |
| Authorization | IAM policy allows ONLY `bedrock-agentcore:InvokeAgentRuntime` on ONE ARN |
| Rate limit | CloudFront throttling + per-session cooldown in orchestrator |
| Budget | AWS Budgets alerts ($25/$50/$100), OpenAI org spend cap ($100/mo) |

**IAM policy (guest role):**
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "bedrock-agentcore:InvokeAgentRuntime",
    "Resource": "arn:aws:bedrock-agentcore:us-east-1:<account>:runtime/financial-bot-*"
  }]
}
```

**[phase-forward]** Phase 2 (real trading) MUST upgrade to Cognito User Pool with MFA. The cost of migration later is real but acceptable given Phase 1's narrow threat surface.

### 9. Observability

**Tracing:**
- LangSmith traces enabled via `LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_API_KEY`
- Every agent invocation, tool call, model call, and graph node appears as a span
- Correlation ID from frontend propagated via custom header

**Logging:**
- Python `structlog` for JSON-formatted structured logs
- Fields: `correlation_id`, `session_id`, `node`, `tool`, `duration_ms`, `status`, `error_type`
- All tool failures logged even when retries succeed (warn level)

**Metrics (CloudWatch EMF):**
- `ToolCallCount` — dimensions: tool_name, status
- `ToolCallDuration` — dimensions: tool_name
- `AgentInvocationDuration`
- `LLMTokenCount` — dimensions: model, purpose (orchestrator/analysis)
- `BriefingGenerationDuration`
- `CacheHitRate` — dimensions: tool_name

**Alarms:**
- Briefing not written within 15 min of scheduled time → SNS alert
- Tool failure rate > 20% over 5 min → SNS alert
- Daily cost > $5 → SNS alert

### 10. Error Handling & Graceful Degradation

**Levels of graceful degradation:**

1. **Tool level** — per-tool retry (tenacity), timeout, circuit breaker. Failures logged with context.
2. **Node level** — `fetch_market` returns `MarketSnapshot` with `errors: list[str]` if some sources failed. Node proceeds with partial data.
3. **Subgraph level** — `analyze` node receives partial data and produces analysis with explicit "data unavailable for X" notes.
4. **Briefing level** — If fewer than N sources returned valid data, briefing status is `partial` with list of failed sources.
5. **UI level** — Failed tool calls shown as visible chips with error tooltip, not hidden.

**Timeout hierarchy:**
- Per-tool: 5-10s
- Per-node: 30s (covers parallel tool calls)
- Research subgraph: 60s total
- Orchestrator invocation: 120s total

**Pydantic everywhere:** Every external API response parsed via Pydantic model. Validation errors are logged + raised as typed exceptions, not silently dropped.

### 11. Deployment

**Frontend:**
- Build: `pnpm build` → static assets
- Host: S3 bucket + CloudFront distribution
- Config injection: build-time env vars for Cognito Identity Pool ID, AgentCore Runtime ARN, region
- Deploy: CDK stack or manual sync

**Backend (AgentCore Runtime):**
- Build: `agentcore deploy` (Container build)
- Region: `us-east-1` (primary for OpenAI latency + AgentCore availability)
- Execution role: auto-created, with permissions for DynamoDB + CloudWatch + Secrets Manager

**Lambda proxy (briefing):**
- Deployed via same Serverless Framework or CDK stack
- Single function, ~30 LoC
- Reads AgentCore ARN from env var

**EventBridge rules:**
- Two rules: morning (UTC 00:00) and evening (UTC 09:00)
- Target: Lambda proxy
- DLQ: SQS queue for failed invocations

**DynamoDB table:**
- `financial-bot` with single-table schema
- Created by CDK or CLI on first deploy

**Secrets:**
- OpenAI, Naver, Alpha Vantage, Finnhub keys in AWS Secrets Manager
- AgentCore Runtime's execution role granted `secretsmanager:GetSecretValue` on specific secrets
- Python code reads secrets at container startup

### 12. Cost Guardrails (Day 1)

**Mandatory before first deploy:**

1. **AWS Budgets alerts** at $25, $50, $100/month (email notification)
2. **OpenAI organization spend cap** at $100/month (hard limit, not soft warning)
3. **CloudWatch alarm** on LLM token usage exceeding daily expected ($1.50/day threshold)
4. **IAM policy** on Identity Pool guest role restricts to ONE runtime ARN (no wildcard)
5. **AgentCore concurrency limit** (if configurable) to prevent runaway parallel invocations

## File Structure

```
financial-bot-agent/                       ← AgentCore project (new)
├── agentcore/
│   ├── agentcore.json                     ← LangChain framework selected
│   └── .env.local                         ← local dev env
├── app/FinancialAgent/
│   ├── main.py                            ← BedrockAgentCoreApp + entrypoint
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── orchestrator.py                ← LangChain create_agent
│   │   └── research_graph.py              ← LangGraph subgraph
│   ├── nodes/
│   │   ├── __init__.py
│   │   ├── fetch_market.py                ← pure Python parallel fetch
│   │   ├── fetch_news.py                  ← pure Python parallel fetch
│   │   └── analyze.py                     ← gpt-5 LLM node
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── watchlist.py                   ← DynamoDB CRUD (orchestrator tools)
│   │   ├── briefing.py                    ← DynamoDB read (orchestrator tools)
│   │   ├── preferences.py                 ← DynamoDB CRUD (orchestrator tools)
│   │   └── sources/
│   │       ├── okx.py
│   │       ├── alphavantage.py
│   │       ├── pykrx_adapter.py
│   │       ├── frankfurter.py
│   │       ├── finnhub.py
│   │       └── naver.py
│   ├── infra/
│   │   ├── cache.py                       ← cachetools TTLCache wrappers
│   │   ├── circuit_breaker.py             ← simple in-memory breaker
│   │   ├── retry.py                       ← tenacity wrappers
│   │   ├── logging_config.py              ← structlog setup
│   │   └── secrets.py                     ← Secrets Manager loader
│   ├── schemas/
│   │   ├── market.py                      ← Pydantic models
│   │   ├── news.py
│   │   └── briefing.py
│   ├── storage/
│   │   └── ddb.py                         ← single-table DynamoDB helpers
│   ├── memory/
│   │   └── agentcore_memory.py            ← MemoryClient adapter
│   ├── prompts/
│   │   ├── orchestrator.md
│   │   └── analyze.md
│   ├── pyproject.toml
│   └── Dockerfile

financial-bot-frontend/                    ← React app (new)
├── package.json
├── vite.config.ts
├── tailwind.config.js
├── index.html
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── auth/
    │   ├── PasswordGate.tsx
    │   └── identityPool.ts                ← Amplify config
    ├── api/
    │   └── agentcore.ts                   ← InvokeAgentRuntime wrapper
    ├── components/
    │   ├── layout/
    │   │   ├── TerminalFrame.tsx          ← 3-pane layout shell
    │   │   └── Header.tsx
    │   ├── sessions/
    │   │   ├── SessionList.tsx
    │   │   ├── SessionItem.tsx
    │   │   └── NewSessionButton.tsx
    │   ├── briefings/
    │   │   ├── BriefingList.tsx
    │   │   └── BriefingReader.tsx
    │   ├── watchlist/
    │   │   ├── Watchlist.tsx
    │   │   ├── StockRow.tsx
    │   │   └── AddSymbolDialog.tsx
    │   └── chat/
    │       ├── ChatThread.tsx
    │       ├── Message.tsx
    │       ├── ToolCallChip.tsx
    │       └── ChatInput.tsx
    ├── hooks/
    │   ├── useAgentStream.ts              ← SSE streaming from AgentCore
    │   ├── useWatchlist.ts                ← DynamoDB via AgentCore tools
    │   └── useSessions.ts
    ├── styles/
    │   └── terminal.css                   ← scanlines, CRT glow
    └── types/
        └── index.ts

financial-bot-infra/                       ← CDK or SLS stack (new, optional)
├── bin/
├── lib/
│   ├── dynamodb-stack.ts
│   ├── briefing-lambda-stack.ts
│   ├── frontend-stack.ts                  ← S3 + CloudFront
│   └── cognito-stack.ts
└── package.json
```

## Open Questions (resolve before Plan)

1. **LangSmith account**: do we have one? If not, start with local logging only, add LangSmith in Phase 1.5.
2. **CDK vs SLS for infra**: CDK is AWS-native and aligns with AgentCore's internal CDK use. Recommend CDK.
3. **First deploy iteration**: local `agentcore dev` until feature-complete, THEN `agentcore deploy`. Agree?

## Success Criteria

Phase 1 is complete when:

1. User can log in via password gate on deployed web URL
2. User can have a multi-session conversation with the bot about markets
3. User can ask "BTC 시세", "엔비디아 뉴스 요약해줘", "오늘 시장 어때" in Korean and get accurate, timely answers
4. User can add/remove/list watchlist items via conversation
5. Morning and evening briefings are automatically generated and appear in the Briefings section
6. User can click a past briefing and read it
7. Deployed infra fits within budget alerts ($50/mo target)
8. LangSmith traces (or local logs) are available for every agent invocation
9. A deliberately broken data source causes a `partial` briefing, not a crash
10. Tool call duration metrics visible in CloudWatch
