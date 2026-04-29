# finance-ai-app

[Visit Website]https://d240f0ye2047ec.cloudfront.net/

Personal AI financial assistant on AWS Bedrock AgentCore.

A Phase 1 port of a Slack-based briefing bot to a React web UI. Multi-session chat with a LangChain orchestrator, LangGraph research subgraph (parallel market + news fetch → GPT-5.4 analysis), auto-generated morning/evening briefings, and a Bloomberg-style terminal UI.

## Architecture

```
┌────────────────┐  Cognito Identity Pool  ┌────────────────────┐
│  React UI      │ ─────────────────────▶ │  AgentCore Runtime │
│  Terminal Feed │         IAM SigV4       │  (Python/LangChain)│
└────────────────┘                         └────────────────────┘
        │                                            │
        │                                            ├─ LangGraph research subgraph
        │                                            │  (fetch_market ∥ fetch_news → analyze)
        │                                            │
        │                                            ├─ Orchestrator tools
        │                                            │  (watchlist, briefings, preferences)
        │                                            │
        └──── S3 + CloudFront                        └─ DynamoDB single-table
                                                            ▲
                                      EventBridge cron ─────┤
                                      (Lambda proxy)        │
                                                            │
```

## Repositories

| Directory | Purpose | Tech |
|-----------|---------|------|
| `financeaiapp/` | AgentCore Runtime backend | Python 3.13, LangChain, LangGraph, Bedrock Claude / OpenAI |
| `financeaiapp-frontend/` | Web UI | React 19, Vite, TailwindCSS v4 |
| `financeaiapp-infra/` | AWS infrastructure | CDK v2 (TypeScript) |

## Phase Roadmap

| Phase | Scope | Status |
|-------|-------|--------|
| **1** | Port: web UI, conversation, watchlist, briefings | in progress |
| 1.5 | Price alerts | future |
| 2 | Paper trading (virtual portfolio) | future |
| 3 | HITL real trades (Slack-style approval) | future |
| 4 | Policy-based limited auto | future |
| 5 | WebSocket streaming, backtesting, multi-strategy | future |

## Local Development

### Backend

```bash
cd financeaiapp
AWS_PROFILE=developer-dongik agentcore dev
```

Requires `agentcore/.env.local` with at minimum `OPENAI_API_KEY` (for default LLM provider), or configure Bedrock via `LLM_PROVIDER=bedrock`.

### Frontend

```bash
cd financeaiapp-frontend
pnpm install
pnpm dev
```

Opens on `http://localhost:3000`, proxies `/api` → `http://localhost:8080`.

### Infrastructure

```bash
cd financeaiapp-infra
pnpm install
AGENTCORE_RUNTIME_ARN=<arn-after-agentcore-deploy> npx cdk synth
```

## Deployment

Deployment is fully automated via GitHub Actions on push to `main`. See:
- `.github/workflows/deploy-backend.yml` — `agentcore deploy`
- `.github/workflows/deploy-infra.yml` — CDK deploy (Cognito, Briefing Lambda, Frontend hosting)
- `.github/workflows/deploy-frontend.yml` — Vite build + S3 sync + CloudFront invalidation

AWS auth uses **OIDC** (no long-lived keys). See `financeaiapp-infra/lib/oidc-stack.ts`.

## Documentation

- [`docs/design.md`](docs/design.md) — Phase 1 design spec
- [`docs/plan.md`](docs/plan.md) — Implementation plan

## License

MIT
