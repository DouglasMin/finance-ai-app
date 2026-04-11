# Financial Bot Phase 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 Slack 금융봇(Node.js + OpenAI Agents SDK)을 AgentCore Runtime + LangChain + LangGraph + React 웹UI로 포팅한다. Phase 2+ (매매) 확장성 유지.

**Architecture:** LangChain `create_agent` 오케스트레이터 + LangGraph 리서치 서브그래프(fetch_market ∥ fetch_news → analyze). 순수 Python 검색 노드, gpt-5.4-mini 오케스트레이터, gpt-5.4 분석. AgentCore Memory (세션 단기만), DynamoDB 싱글테이블, Lambda 프록시로 EventBridge→AgentCore 브리핑. Terminal Feed 디자인 React 3-pane UI.

**Tech Stack:** Python 3.13, LangChain + LangGraph, AgentCore Runtime, **LLM provider: OpenAI ↔ Bedrock Claude 스위처블 (env var)**, React + Vite + TailwindCSS v4, AWS CDK, DynamoDB, Lambda, EventBridge, Cognito Identity Pool, S3 + CloudFront, LangSmith

**LLM 설정:**
- `LLM_PROVIDER=openai|bedrock` — 런타임 스위치
- `ORCHESTRATOR_MODEL` — 예: `gpt-5.4-mini` 또는 `us.anthropic.claude-haiku-4-5-20251001-v1:0`
- `ANALYZE_MODEL` — 예: `gpt-5.4` 또는 `us.anthropic.claude-sonnet-4-5-20250929-v1:0`
- 팩토리: `infra/llm.py` — `get_llm(purpose)`가 provider/model env 읽어서 `ChatOpenAI` 또는 `ChatBedrockConverse` 반환

**Spec:** `docs/superpowers/specs/2026-04-10-financial-bot-phase1-design.md`

**Budget:** $200 AWS credits / 6 months = $33/mo target. Alerts at $15/$25/$33. Email: dongik.dev73@gmail.com

---

## File Structure

```
agentcore-service/
├── financial-bot-agent/                   # AgentCore project (new)
│   ├── agentcore/
│   │   ├── agentcore.json
│   │   └── .env.local
│   └── app/FinancialAgent/
│       ├── main.py                        # Entrypoint + custom routes
│       ├── agents/
│       │   ├── orchestrator.py            # LangChain create_agent
│       │   ├── research_graph.py          # LangGraph subgraph
│       │   └── research_tool.py           # @tool wrapper
│       ├── nodes/
│       │   ├── fetch_market.py            # Pure Python, parallel
│       │   ├── fetch_news.py              # Pure Python, parallel
│       │   └── analyze.py                 # LLM node (gpt-5.4)
│       ├── tools/
│       │   ├── watchlist.py
│       │   ├── briefing.py
│       │   ├── preferences.py
│       │   ├── sessions.py
│       │   └── sources/
│       │       ├── okx.py
│       │       ├── alphavantage.py
│       │       ├── pykrx_adapter.py
│       │       ├── frankfurter.py
│       │       ├── finnhub.py
│       │       └── naver.py
│       ├── infra/
│       │   ├── logging_config.py
│       │   ├── cache.py
│       │   ├── retry.py
│       │   ├── circuit_breaker.py
│       │   ├── metrics.py
│       │   └── secrets.py
│       ├── schemas/
│       │   ├── invoke.py
│       │   ├── market.py
│       │   ├── news.py
│       │   └── briefing.py
│       ├── storage/ddb.py
│       ├── memory/agentcore_memory.py
│       ├── prompts/
│       │   ├── orchestrator.md
│       │   ├── analyze.md
│       │   └── briefing.md
│       ├── handlers/briefing.py
│       ├── pyproject.toml
│       └── Dockerfile
├── financial-bot-frontend/                # React app (new)
│   └── src/
│       ├── App.tsx
│       ├── auth/{PasswordGate,identityPool}
│       ├── api/agentcore.ts
│       ├── components/{layout,sessions,briefings,watchlist,chat}
│       ├── hooks/{useAgentStream,useWatchlist,useSessions}
│       ├── styles/terminal.css
│       └── types/
└── financial-bot-infra/                   # CDK stack (new)
    └── lib/
        ├── dynamodb-stack.ts
        ├── cognito-stack.ts
        ├── briefing-stack.ts
        └── frontend-stack.ts
```

---

## Milestone 0 — Day 1 Guardrails & Project Skeleton

**Goal:** 비용 가드레일과 프로젝트 스켈레톤을 먼저 세팅. 코드 작성 전에 안전망 구축.

### Task 0.1: 프로젝트 디렉토리 + README 스텁

**Files:**
- Create: `financial-bot-agent/README.md`
- Create: `financial-bot-frontend/README.md`
- Create: `financial-bot-infra/README.md`
- Create: `financial-bot-agent/.gitignore`, `financial-bot-frontend/.gitignore`, `financial-bot-infra/.gitignore`

- [ ] **Step 1: 세 디렉토리 생성**

```bash
cd /Users/douggy/per-projects/agentcore-service
mkdir -p financial-bot-agent financial-bot-frontend financial-bot-infra
```

- [ ] **Step 2: README 스텁 작성**

각 README에:
- 프로젝트 목적
- Spec 링크: `docs/superpowers/specs/2026-04-10-financial-bot-phase1-design.md`
- Phase status: Phase 1 in progress
- Day 1 Setup 체크리스트 섹션

- [ ] **Step 3: .gitignore 작성**

- `financial-bot-agent/.gitignore`: Python (`.venv/`, `__pycache__/`, `*.pyc`, `.env`, `.env.local`, `.pytest_cache/`, `dist/`, `build/`)
- `financial-bot-frontend/.gitignore`: Node (`node_modules/`, `dist/`, `.env`, `.env.local`)
- `financial-bot-infra/.gitignore`: Node + CDK (`node_modules/`, `cdk.out/`, `.env`)

### Task 0.2: AWS Budget 알림 생성

**Files:** None (AWS CLI commands만)

- [ ] **Step 1: Budget JSON 파일 준비**

```bash
cat > /tmp/financial-bot-budget.json <<'EOF'
{
  "BudgetName": "financial-bot-monthly",
  "BudgetLimit": { "Amount": "33", "Unit": "USD" },
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST",
  "CostFilters": {}
}
EOF
```

- [ ] **Step 2: 3단계 알림 구성 파일**

```bash
cat > /tmp/financial-bot-notifications.json <<'EOF'
[
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 45,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [
      { "SubscriptionType": "EMAIL", "Address": "dongik.dev73@gmail.com" }
    ]
  },
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 75,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [
      { "SubscriptionType": "EMAIL", "Address": "dongik.dev73@gmail.com" }
    ]
  },
  {
    "Notification": {
      "NotificationType": "FORECASTED",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 100,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [
      { "SubscriptionType": "EMAIL", "Address": "dongik.dev73@gmail.com" }
    ]
  }
]
EOF
```

- [ ] **Step 3: Budget 생성**

```bash
ACCOUNT_ID=$(AWS_PROFILE=developer-dongik aws sts get-caller-identity --query Account --output text)

AWS_PROFILE=developer-dongik aws budgets create-budget \
  --account-id $ACCOUNT_ID \
  --budget file:///tmp/financial-bot-budget.json \
  --notifications-with-subscribers file:///tmp/financial-bot-notifications.json
```

Expected: 명령 성공, no output.

- [ ] **Step 4: 검증**

```bash
AWS_PROFILE=developer-dongik aws budgets describe-budgets --account-id $ACCOUNT_ID \
  --query "Budgets[?BudgetName=='financial-bot-monthly']"
```

Expected: JSON 반환, `BudgetLimit.Amount: "33"`.

### Task 0.3: OpenAI 스펜드 캡 (수동)

**Files:** None (수동 단계)

- [ ] **Step 1: OpenAI 콘솔에서 하드 리밋 $100/월 설정**

https://platform.openai.com/account/limits → Usage limits → Hard limit: $100/month

- [ ] **Step 2: 확인 후 README 체크박스 마킹**

`financial-bot-agent/README.md`의 Day 1 Setup 섹션:
```markdown
- [x] OpenAI org spend cap $100/month (set manually)
```

### Task 0.4: Secrets Manager placeholder

**Files:** None (AWS CLI)

- [ ] **Step 1: 빈 시크릿 생성**

```bash
AWS_PROFILE=developer-dongik aws secretsmanager create-secret \
  --name financial-bot/api-keys \
  --region us-east-1 \
  --secret-string '{"OPENAI_API_KEY":"","ALPHA_VANTAGE_API_KEY":"","FINNHUB_API_KEY":"","NAVER_CLIENT_ID":"","NAVER_CLIENT_SECRET":"","LANGSMITH_API_KEY":""}'
```

Expected: ARN 반환.

- [ ] **Step 2: 검증**

```bash
AWS_PROFILE=developer-dongik aws secretsmanager describe-secret \
  --secret-id financial-bot/api-keys \
  --region us-east-1
```

Expected: `Name: "financial-bot/api-keys"`, `ARN: "arn:aws:secretsmanager:..."`.

### Task 0.5: Commit

- [ ] **Step 1: Commit**

```bash
cd /Users/douggy/per-projects/agentcore-service
git add financial-bot-agent/ financial-bot-frontend/ financial-bot-infra/
git commit -m "chore: scaffold financial-bot projects + Day 1 guardrails"
```

---

## Milestone 1 — Backend Foundations + LangGraph Spike

**Goal:** AgentCore 프로젝트 생성, 인프라 모듈 (로깅, 캐시, 재시도, 서킷브레이커) 완성, **LangGraph가 AgentCore 안에서 제대로 스트리밍되는지 검증** (핵심 리스크 R1).

### Task 1.1: AgentCore 프로젝트 생성 (수동 위자드)

**Files:** Create `financial-bot-agent/...` (agentcore create 생성물)

- [ ] **Step 1: agentcore create 실행 (사용자 수동)**

```bash
cd /Users/douggy/per-projects/agentcore-service
AWS_PROFILE=developer-dongik agentcore create
```

위자드 선택:
- Name: `FinancialAgent`
- Type: Create new agent
- Language: Python
- Build: Container
- Protocol: HTTP
- Framework: **LangChain + LangGraph**
- Model: Claude Sonnet 4.5 (일단 기본값, 나중에 OpenAI로 교체)
- Region: us-east-1
- Memory: None (나중에 add memory로 추가)
- Advanced: No, use defaults

- [ ] **Step 2: 디렉토리 이름 확인**

생성된 디렉토리가 `financial-bot-agent/`가 아니면 이동:
```bash
mv <생성된-이름> financial-bot-agent
```

### Task 1.2: pyproject.toml 의존성 + 디렉토리 구조

**Files:**
- Modify: `financial-bot-agent/app/FinancialAgent/pyproject.toml`

- [ ] **Step 1: 의존성 업데이트**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "FinancialAgent"
version = "0.1.0"
description = "AI Financial Bot — Phase 1"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "aws-opentelemetry-distro",
    "bedrock-agentcore >= 1.0.3",
    "boto3 >= 1.42.0",
    "botocore[crt] >= 1.35.0",
    # LangChain stack
    "langchain >= 0.3.0",
    "langchain-openai >= 0.2.0",
    "langchain-aws >= 0.2.0",
    "langgraph >= 0.2.0",
    "langsmith >= 0.1.0",
    # Data layer
    "pydantic >= 2.9.0",
    "pykrx >= 1.0.0",
    "httpx >= 0.27.0",
    "feedparser >= 6.0.0",
    # Reliability
    "tenacity >= 9.0.0",
    "cachetools >= 5.5.0",
    "structlog >= 24.0.0",
]

[tool.hatch.build.targets.wheel]
packages = ["."]
```

- [ ] **Step 2: 디렉토리 구조 생성**

```bash
cd financial-bot-agent/app/FinancialAgent
mkdir -p agents nodes tools/sources infra schemas storage memory prompts handlers tests
touch agents/__init__.py nodes/__init__.py tools/__init__.py tools/sources/__init__.py \
      infra/__init__.py schemas/__init__.py storage/__init__.py memory/__init__.py handlers/__init__.py
```

- [ ] **Step 3: uv lock**

```bash
cd financial-bot-agent/app/FinancialAgent
uv lock
```

### Task 1.3: Pydantic 스키마 (invoke payload, market, news, briefing)

**Files:**
- Create: `schemas/invoke.py`, `schemas/market.py`, `schemas/news.py`, `schemas/briefing.py`

- [ ] **Step 1: `schemas/invoke.py`**

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field


class InvokeChatPayload(BaseModel):
    action: Literal["chat"] = "chat"
    session_id: str
    message: str
    correlation_id: Optional[str] = None


class InvokeBriefingPayload(BaseModel):
    action: Literal["briefing"] = "briefing"
    time_of_day: Literal["AM", "PM"]
    correlation_id: Optional[str] = None
```

- [ ] **Step 2: `schemas/market.py`**

```python
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class MarketQuote(BaseModel):
    symbol: str
    category: Literal["crypto", "us_stock", "kr_stock", "fx"]
    price: float
    currency: str  # "USD", "KRW", etc.
    change_pct: Optional[float] = None
    volume: Optional[float] = None
    timestamp: datetime
    source: str  # "okx", "alphavantage", "pykrx", "frankfurter"


class MarketSnapshot(BaseModel):
    quotes: list[MarketQuote] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    fetched_at: datetime
```

- [ ] **Step 3: `schemas/news.py`**

```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    title: str
    url: str
    summary: Optional[str] = None
    source: str  # "naver", "finnhub", "alphavantage"
    published_at: Optional[datetime] = None
    sentiment_score: Optional[float] = None  # -1 to 1
    sentiment_label: Optional[str] = None
    related_tickers: list[str] = Field(default_factory=list)
    lang: str = "en"


class NewsSnapshot(BaseModel):
    items: list[NewsItem] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    fetched_at: datetime
```

- [ ] **Step 4: `schemas/briefing.py`**

```python
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


BriefingStatus = Literal["pending", "in_progress", "partial", "success", "failed"]


class BriefingRecord(BaseModel):
    date: str  # "2026-04-11"
    time_of_day: Literal["AM", "PM"]
    status: BriefingStatus
    content: str = ""
    tickers_covered: list[str] = Field(default_factory=list)
    generated_at: datetime
    duration_ms: int = 0
    errors: list[str] = Field(default_factory=list)
```

- [ ] **Step 5: 검증**

```bash
cd financial-bot-agent/app/FinancialAgent
uv run python -c "from schemas.invoke import InvokeChatPayload; from schemas.market import MarketSnapshot; from schemas.news import NewsSnapshot; from schemas.briefing import BriefingRecord; print('OK')"
```

### Task 1.4: 인프라 모듈 — logging, cache, retry, circuit breaker

**Files:**
- Create: `infra/logging_config.py`, `infra/cache.py`, `infra/retry.py`, `infra/circuit_breaker.py`

- [ ] **Step 1: `infra/logging_config.py`**

```python
import logging
import os
import sys
from contextvars import ContextVar

import structlog

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def add_correlation_id(logger, method_name, event_dict):
    cid = correlation_id_var.get()
    if cid:
        event_dict["correlation_id"] = cid
    return event_dict


def setup_logging():
    level = os.environ.get("LOG_LEVEL", "INFO").upper()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            add_correlation_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    return structlog.get_logger(name)
```

- [ ] **Step 2: `infra/cache.py`**

```python
from cachetools import TTLCache

_market_cache: TTLCache = TTLCache(maxsize=200, ttl=30)  # 30s
_news_cache: TTLCache = TTLCache(maxsize=200, ttl=300)  # 5min


def market_cache() -> TTLCache:
    return _market_cache


def news_cache() -> TTLCache:
    return _news_cache


def cache_key(*parts) -> str:
    return "|".join(str(p) for p in parts)
```

- [ ] **Step 3: `infra/retry.py`**

```python
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import httpx


def retry_api(max_attempts: int = 3):
    """Retry transient HTTP errors with exponential backoff."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError, httpx.ReadError)),
        reraise=True,
    )
```

- [ ] **Step 4: `infra/circuit_breaker.py`**

```python
import time
from dataclasses import dataclass, field


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5
    recovery_seconds: float = 60.0
    _failures: int = field(default=0)
    _open_until: float = field(default=0.0)

    def is_open(self) -> bool:
        return time.time() < self._open_until

    def record_success(self):
        self._failures = 0
        self._open_until = 0.0

    def record_failure(self):
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._open_until = time.time() + self.recovery_seconds


# Module-level breakers per source
_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(name: str) -> CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name=name)
    return _breakers[name]
```

- [ ] **Step 5: 검증**

```bash
cd financial-bot-agent/app/FinancialAgent
uv run python -c "
from infra.logging_config import setup_logging, get_logger
from infra.cache import market_cache, cache_key
from infra.retry import retry_api
from infra.circuit_breaker import get_breaker

setup_logging()
log = get_logger('test')
log.info('hello', key='value')

cache = market_cache()
cache['BTC'] = 67000
print('cache:', cache['BTC'])

breaker = get_breaker('okx')
print('breaker open:', breaker.is_open())
print('OK')
"
```

### Task 1.4.5: LLM Provider Factory (OpenAI ↔ Bedrock 스위처블)

**Files:**
- Create: `infra/llm.py`

- [ ] **Step 1: `infra/llm.py`**

```python
import os
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_aws import ChatBedrockConverse

from infra.secrets import get_secret


Purpose = Literal["orchestrator", "analyze"]


def get_llm(purpose: Purpose) -> BaseChatModel:
    """Return a chat model for the given purpose.

    Reads LLM_PROVIDER env var ("openai" | "bedrock") and
    {PURPOSE}_MODEL env var to construct the right client.

    Defaults:
      LLM_PROVIDER=openai
      ORCHESTRATOR_MODEL=gpt-5.4-mini
      ANALYZE_MODEL=gpt-5.4

    Bedrock examples:
      LLM_PROVIDER=bedrock
      ORCHESTRATOR_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
      ANALYZE_MODEL=us.anthropic.claude-sonnet-4-5-20250929-v1:0
    """
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()

    default_models = {
        ("openai", "orchestrator"): "gpt-5.4-mini",
        ("openai", "analyze"): "gpt-5.4",
        ("bedrock", "orchestrator"): "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        ("bedrock", "analyze"): "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    }
    env_var = f"{purpose.upper()}_MODEL"
    model = os.environ.get(env_var) or default_models[(provider, purpose)]

    if provider == "openai":
        return ChatOpenAI(
            model=model,
            api_key=get_secret("OPENAI_API_KEY"),
            max_retries=2,
        )
    elif provider == "bedrock":
        region = os.environ.get("BEDROCK_REGION", "us-east-1")
        return ChatBedrockConverse(
            model=model,
            region_name=region,
            max_retries=2,
        )
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
```

- [ ] **Step 2: 검증 (mocked)**

```bash
cd financial-bot-agent/app/FinancialAgent
uv run python -c "
import os
os.environ['LLM_PROVIDER'] = 'openai'
os.environ['OPENAI_API_KEY'] = 'sk-fake'
from infra.llm import get_llm
llm = get_llm('orchestrator')
print(type(llm).__name__, llm.model_name)
"
```

Expected: `ChatOpenAI gpt-5.4-mini`

### Task 1.5: Secrets loader + DDB helper

**Files:**
- Create: `infra/secrets.py`, `storage/ddb.py`

- [ ] **Step 1: `infra/secrets.py`**

```python
import json
import os
from functools import lru_cache

import boto3


@lru_cache(maxsize=1)
def load_secrets() -> dict:
    """Load secrets from Secrets Manager in cloud, or from env vars locally."""
    # Local dev: prefer env vars
    env_keys = ["OPENAI_API_KEY", "ALPHA_VANTAGE_API_KEY", "FINNHUB_API_KEY",
                "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "LANGSMITH_API_KEY"]
    if os.environ.get("OPENAI_API_KEY"):
        return {k: os.environ.get(k, "") for k in env_keys}

    # Cloud: load from Secrets Manager
    secret_id = os.environ.get("SECRETS_ID", "financial-bot/api-keys")
    client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    response = client.get_secret_value(SecretId=secret_id)
    return json.loads(response["SecretString"])


def get_secret(key: str) -> str:
    return load_secrets().get(key, "")
```

- [ ] **Step 2: `storage/ddb.py`**

```python
import os
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key

# Phase-forward: schema supports future POSITION#, ORDER#, STRATEGY# SKs. See spec §6.
TABLE_NAME = os.environ.get("DDB_TABLE", "financial-bot")
USER_PK = "USER#me"

_table = None


def get_table():
    global _table
    if _table is None:
        dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        _table = dynamodb.Table(TABLE_NAME)
    return _table


def put_item(sk: str, attrs: dict) -> None:
    item = {"PK": USER_PK, "SK": sk, **attrs, "updated_at": datetime.now(timezone.utc).isoformat()}
    get_table().put_item(Item=item)


def get_item(sk: str) -> Optional[dict]:
    response = get_table().get_item(Key={"PK": USER_PK, "SK": sk})
    return response.get("Item")


def query_by_sk_prefix(prefix: str, limit: Optional[int] = None, ascending: bool = True) -> list[dict]:
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("PK").eq(USER_PK) & Key("SK").begins_with(prefix),
        "ScanIndexForward": ascending,
    }
    if limit:
        kwargs["Limit"] = limit
    response = get_table().query(**kwargs)
    return response.get("Items", [])


def delete_item(sk: str) -> None:
    get_table().delete_item(Key={"PK": USER_PK, "SK": sk})
```

### Task 1.6: 🔴 LangGraph in AgentCore 스트리밍 스파이크 (HIGH RISK)

**Files:**
- Create temporarily: `app/FinancialAgent/_spike_main.py`

- [ ] **Step 1: 스파이크 main.py 작성**

```python
# _spike_main.py — 삭제 예정
import asyncio
import json
from typing import TypedDict

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langgraph.graph import StateGraph, START, END

app = BedrockAgentCoreApp()


class State(TypedDict):
    value: int


async def node_a(state: State) -> State:
    return {"value": state["value"] + 10}


async def node_b(state: State) -> State:
    return {"value": state["value"] * 2}


graph_builder = StateGraph(State)
graph_builder.add_node("a", node_a)
graph_builder.add_node("b", node_b)
graph_builder.add_edge(START, "a")
graph_builder.add_edge("a", "b")
graph_builder.add_edge("b", END)
graph = graph_builder.compile()


@app.entrypoint
async def invoke(payload, context):
    yield {"event": "start"}
    async for event in graph.astream({"value": payload.get("start", 1)}):
        yield {"event": "node", "data": event}
    yield {"event": "done"}


if __name__ == "__main__":
    app.run()
```

- [ ] **Step 2: 원래 main.py 백업 + 스파이크로 교체**

```bash
cd financial-bot-agent/app/FinancialAgent
cp main.py main.py.bak
cp _spike_main.py main.py
```

- [ ] **Step 3: agentcore dev 실행 + 테스트**

터미널 1:
```bash
cd financial-bot-agent/agentcore
export AWS_PROFILE=developer-dongik
agentcore dev
```

터미널 2:
```bash
curl -N -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"start": 5}'
```

Expected 출력 (스트림):
```
data: {"event": "start"}
data: {"event": "node", "data": {"a": {"value": 15}}}
data: {"event": "node", "data": {"b": {"value": 30}}}
data: {"event": "done"}
```

**성공 시**: R1 해소. 다음 태스크로 진행.
**실패 시**: STOP, 에러 보고, 플랜 재검토.

- [ ] **Step 4: 스파이크 정리**

```bash
cd financial-bot-agent/app/FinancialAgent
mv main.py.bak main.py
rm _spike_main.py
```

### Task 1.7: Commit

- [ ] **Step 1: Commit**

```bash
git add financial-bot-agent/
git commit -m "feat(m1): backend foundations + LangGraph AgentCore spike verified"
```

---

## Milestone 2a — Research Subgraph + Data Source Adapters

**Goal:** 6개 데이터 소스 어댑터 + 3개 LangGraph 노드 + research 서브그래프 조립. 헤드리스 (에이전트 X) 상태로 `run_research()` 호출 가능.

### Task 2a.1: OKX 크립토 어댑터

**Files:**
- Create: `tools/sources/okx.py`

- [ ] **Step 1: `tools/sources/okx.py`**

```python
import asyncio
from datetime import datetime, timezone

import httpx

from infra.cache import market_cache, cache_key
from infra.circuit_breaker import get_breaker
from infra.logging_config import get_logger
from infra.retry import retry_api
from schemas.market import MarketQuote

log = get_logger("okx")
BASE_URL = "https://www.okx.com/api/v5/market/ticker"


@retry_api(max_attempts=3)
async def _fetch(symbol: str) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(BASE_URL, params={"instId": symbol})
        response.raise_for_status()
        return response.json()


async def get_crypto_price(symbol: str) -> MarketQuote:
    """Fetch crypto price from OKX. symbol format: BTC-USDT, ETH-USDT."""
    okx_symbol = symbol if "-" in symbol else f"{symbol}-USDT"
    key = cache_key("okx", okx_symbol)
    cache = market_cache()

    if key in cache:
        return cache[key]

    breaker = get_breaker("okx")
    if breaker.is_open():
        raise RuntimeError(f"OKX circuit breaker open")

    try:
        data = await _fetch(okx_symbol)
        breaker.record_success()

        ticker = data["data"][0]
        quote = MarketQuote(
            symbol=symbol.replace("-USDT", ""),
            category="crypto",
            price=float(ticker["last"]),
            currency="USD",
            change_pct=(float(ticker["last"]) / float(ticker["open24h"]) - 1) * 100,
            volume=float(ticker["vol24h"]),
            timestamp=datetime.now(timezone.utc),
            source="okx",
        )
        cache[key] = quote
        log.info("okx.fetch", symbol=symbol, price=quote.price)
        return quote
    except Exception as e:
        breaker.record_failure()
        log.error("okx.fetch.failed", symbol=symbol, error=str(e))
        raise
```

### Task 2a.2: Alpha Vantage 어댑터 (US 주식 + 뉴스 감성)

**Files:**
- Create: `tools/sources/alphavantage.py`

- [ ] **Step 1: `tools/sources/alphavantage.py`**

```python
import os
from datetime import datetime, timezone

import httpx

from infra.cache import market_cache, news_cache, cache_key
from infra.circuit_breaker import get_breaker
from infra.logging_config import get_logger
from infra.retry import retry_api
from infra.secrets import get_secret
from schemas.market import MarketQuote
from schemas.news import NewsItem, NewsSnapshot

log = get_logger("alphavantage")
BASE_URL = "https://www.alphavantage.co/query"


@retry_api(max_attempts=2)
async def _call(params: dict) -> dict:
    key = get_secret("ALPHA_VANTAGE_API_KEY")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(BASE_URL, params={**params, "apikey": key})
        response.raise_for_status()
        return response.json()


async def get_us_stock(symbol: str) -> MarketQuote:
    key_c = cache_key("av_stock", symbol)
    cache = market_cache()
    if key_c in cache:
        return cache[key_c]

    breaker = get_breaker("alphavantage")
    if breaker.is_open():
        raise RuntimeError("Alpha Vantage circuit breaker open")

    try:
        data = await _call({"function": "GLOBAL_QUOTE", "symbol": symbol})
        breaker.record_success()
        quote_data = data.get("Global Quote", {})
        if not quote_data:
            raise ValueError(f"No data for {symbol}")

        price = float(quote_data["05. price"])
        change_pct_str = quote_data.get("10. change percent", "0%").rstrip("%")

        quote = MarketQuote(
            symbol=symbol,
            category="us_stock",
            price=price,
            currency="USD",
            change_pct=float(change_pct_str),
            timestamp=datetime.now(timezone.utc),
            source="alphavantage",
        )
        cache[key_c] = quote
        return quote
    except Exception as e:
        breaker.record_failure()
        log.error("av.get_us_stock.failed", symbol=symbol, error=str(e))
        raise


async def get_sentiment_news(tickers: list[str], limit: int = 10) -> NewsSnapshot:
    """Alpha Vantage NEWS_SENTIMENT — finance-specific with sentiment scores."""
    key_c = cache_key("av_news", ",".join(sorted(tickers)), limit)
    cache = news_cache()
    if key_c in cache:
        return cache[key_c]

    breaker = get_breaker("alphavantage")
    if breaker.is_open():
        return NewsSnapshot(items=[], errors=["circuit open"], fetched_at=datetime.now(timezone.utc))

    try:
        data = await _call({
            "function": "NEWS_SENTIMENT",
            "tickers": ",".join(tickers),
            "limit": limit,
            "sort": "LATEST",
        })
        breaker.record_success()

        items = []
        for feed in data.get("feed", [])[:limit]:
            items.append(NewsItem(
                title=feed.get("title", ""),
                url=feed.get("url", ""),
                summary=feed.get("summary", ""),
                source="alphavantage",
                sentiment_score=float(feed.get("overall_sentiment_score", 0)),
                sentiment_label=feed.get("overall_sentiment_label"),
                related_tickers=[t["ticker"] for t in feed.get("ticker_sentiment", [])],
                lang="en",
            ))
        snapshot = NewsSnapshot(items=items, fetched_at=datetime.now(timezone.utc))
        cache[key_c] = snapshot
        return snapshot
    except Exception as e:
        breaker.record_failure()
        log.error("av.get_sentiment_news.failed", error=str(e))
        return NewsSnapshot(items=[], errors=[str(e)], fetched_at=datetime.now(timezone.utc))
```

### Task 2a.3: pykrx 한국 주식 어댑터

**Files:**
- Create: `tools/sources/pykrx_adapter.py`

- [ ] **Step 1: `tools/sources/pykrx_adapter.py`**

```python
import asyncio
from datetime import datetime, timezone

from pykrx import stock

from infra.cache import market_cache, cache_key
from infra.circuit_breaker import get_breaker
from infra.logging_config import get_logger
from schemas.market import MarketQuote

log = get_logger("pykrx")


def _fetch_ohlcv_sync(symbol: str) -> dict:
    today = datetime.now().strftime("%Y%m%d")
    df = stock.get_market_ohlcv(today, today, symbol)
    if df.empty:
        raise ValueError(f"No data for {symbol}")
    row = df.iloc[-1]
    return {
        "close": float(row["종가"]),
        "open": float(row["시가"]),
        "volume": float(row["거래량"]),
    }


async def get_kr_stock(symbol: str) -> MarketQuote:
    """Fetch Korean stock price via pykrx (sync lib, wrapped in to_thread)."""
    key = cache_key("pykrx", symbol)
    cache = market_cache()
    if key in cache:
        return cache[key]

    breaker = get_breaker("pykrx")
    if breaker.is_open():
        raise RuntimeError("pykrx circuit open")

    try:
        # pykrx is synchronous — run in thread to not block event loop
        data = await asyncio.to_thread(_fetch_ohlcv_sync, symbol)
        breaker.record_success()

        change_pct = (data["close"] / data["open"] - 1) * 100 if data["open"] else 0

        quote = MarketQuote(
            symbol=symbol,
            category="kr_stock",
            price=data["close"],
            currency="KRW",
            change_pct=change_pct,
            volume=data["volume"],
            timestamp=datetime.now(timezone.utc),
            source="pykrx",
        )
        cache[key] = quote
        return quote
    except Exception as e:
        breaker.record_failure()
        log.error("pykrx.fetch.failed", symbol=symbol, error=str(e))
        raise
```

### Task 2a.4: Frankfurter FX 어댑터

**Files:**
- Create: `tools/sources/frankfurter.py`

- [ ] **Step 1: `tools/sources/frankfurter.py`**

```python
from datetime import datetime, timezone

import httpx

from infra.cache import market_cache, cache_key
from infra.circuit_breaker import get_breaker
from infra.logging_config import get_logger
from infra.retry import retry_api
from schemas.market import MarketQuote

log = get_logger("frankfurter")
BASE_URL = "https://api.frankfurter.dev/v1/latest"


@retry_api(max_attempts=3)
async def _fetch(base: str, symbols: str) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(BASE_URL, params={"base": base, "symbols": symbols})
        response.raise_for_status()
        return response.json()


async def get_fx(base: str = "USD", quote: str = "KRW") -> MarketQuote:
    key = cache_key("frankfurter", base, quote)
    cache = market_cache()
    if key in cache:
        return cache[key]

    breaker = get_breaker("frankfurter")
    if breaker.is_open():
        raise RuntimeError("Frankfurter circuit open")

    try:
        data = await _fetch(base, quote)
        breaker.record_success()

        rate = float(data["rates"][quote])
        q = MarketQuote(
            symbol=f"{base}/{quote}",
            category="fx",
            price=rate,
            currency=quote,
            timestamp=datetime.now(timezone.utc),
            source="frankfurter",
        )
        cache[key] = q
        return q
    except Exception as e:
        breaker.record_failure()
        log.error("frankfurter.fetch.failed", error=str(e))
        raise
```

### Task 2a.5: Finnhub 뉴스 어댑터

**Files:**
- Create: `tools/sources/finnhub.py`

- [ ] **Step 1: `tools/sources/finnhub.py`**

```python
from datetime import datetime, timedelta, timezone

import httpx

from infra.cache import news_cache, cache_key
from infra.circuit_breaker import get_breaker
from infra.logging_config import get_logger
from infra.retry import retry_api
from infra.secrets import get_secret
from schemas.news import NewsItem, NewsSnapshot

log = get_logger("finnhub")
BASE_URL = "https://finnhub.io/api/v1"


@retry_api(max_attempts=3)
async def _fetch(path: str, params: dict) -> list:
    key = get_secret("FINNHUB_API_KEY")
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{BASE_URL}{path}", params={**params, "token": key})
        response.raise_for_status()
        return response.json()


async def get_company_news(symbol: str, days: int = 3) -> NewsSnapshot:
    key = cache_key("finnhub_news", symbol, days)
    cache = news_cache()
    if key in cache:
        return cache[key]

    breaker = get_breaker("finnhub")
    if breaker.is_open():
        return NewsSnapshot(items=[], errors=["circuit open"], fetched_at=datetime.now(timezone.utc))

    try:
        today = datetime.now()
        since = today - timedelta(days=days)
        data = await _fetch("/company-news", {
            "symbol": symbol,
            "from": since.strftime("%Y-%m-%d"),
            "to": today.strftime("%Y-%m-%d"),
        })
        breaker.record_success()

        items = []
        for raw in data[:10]:
            items.append(NewsItem(
                title=raw.get("headline", ""),
                url=raw.get("url", ""),
                summary=raw.get("summary", ""),
                source="finnhub",
                published_at=datetime.fromtimestamp(raw.get("datetime", 0), tz=timezone.utc) if raw.get("datetime") else None,
                related_tickers=[symbol],
                lang="en",
            ))
        snapshot = NewsSnapshot(items=items, fetched_at=datetime.now(timezone.utc))
        cache[key] = snapshot
        return snapshot
    except Exception as e:
        breaker.record_failure()
        log.error("finnhub.fetch.failed", error=str(e))
        return NewsSnapshot(items=[], errors=[str(e)], fetched_at=datetime.now(timezone.utc))
```

### Task 2a.6: Naver 뉴스 어댑터

**Files:**
- Create: `tools/sources/naver.py`

- [ ] **Step 1: `tools/sources/naver.py`**

```python
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from infra.cache import news_cache, cache_key
from infra.circuit_breaker import get_breaker
from infra.logging_config import get_logger
from infra.retry import retry_api
from infra.secrets import get_secret
from schemas.news import NewsItem, NewsSnapshot

log = get_logger("naver")
BASE_URL = "https://openapi.naver.com/v1/search/news.json"


@retry_api(max_attempts=2)
async def _fetch(query: str, display: int = 10) -> dict:
    cid = get_secret("NAVER_CLIENT_ID")
    csec = get_secret("NAVER_CLIENT_SECRET")
    headers = {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            BASE_URL,
            params={"query": query, "display": display, "sort": "sim"},
            headers=headers,
        )
        response.raise_for_status()
        return response.json()


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).replace("&quot;", '"').replace("&amp;", "&")


async def search_naver_news(query: str, display: int = 10) -> NewsSnapshot:
    """Search Korean financial news via Naver Search API."""
    # Bias toward financial news
    finance_query = f"{query} 주식 OR 증시 OR 금융"

    key = cache_key("naver_news", finance_query, display)
    cache = news_cache()
    if key in cache:
        return cache[key]

    breaker = get_breaker("naver")
    if breaker.is_open():
        return NewsSnapshot(items=[], errors=["circuit open"], fetched_at=datetime.now(timezone.utc))

    try:
        data = await _fetch(finance_query, display)
        breaker.record_success()

        items = []
        for raw in data.get("items", []):
            pub_at = None
            try:
                pub_at = parsedate_to_datetime(raw.get("pubDate", ""))
            except Exception:
                pass

            items.append(NewsItem(
                title=_strip_html(raw.get("title", "")),
                url=raw.get("link", ""),
                summary=_strip_html(raw.get("description", "")),
                source="naver",
                published_at=pub_at,
                lang="ko",
            ))
        snapshot = NewsSnapshot(items=items, fetched_at=datetime.now(timezone.utc))
        cache[key] = snapshot
        return snapshot
    except Exception as e:
        breaker.record_failure()
        log.error("naver.fetch.failed", error=str(e))
        return NewsSnapshot(items=[], errors=[str(e)], fetched_at=datetime.now(timezone.utc))
```

### Task 2a.7: fetch_market 노드 (병렬 시세 수집)

**Files:**
- Create: `nodes/fetch_market.py`

- [ ] **Step 1: `nodes/fetch_market.py`**

```python
import asyncio
import re
from datetime import datetime, timezone
from typing import TypedDict

from infra.logging_config import get_logger
from schemas.market import MarketSnapshot, MarketQuote
from tools.sources import okx, alphavantage, pykrx_adapter, frankfurter

log = get_logger("fetch_market_node")


def _categorize(ticker: str) -> str:
    """Rough ticker category detection."""
    t = ticker.upper()
    if re.fullmatch(r"\d{6}", t):
        return "kr_stock"
    if "/" in t:
        return "fx"
    if t in {"BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "DOT"} or t.endswith("-USDT"):
        return "crypto"
    return "us_stock"


async def _fetch_one(ticker: str) -> MarketQuote | None:
    category = _categorize(ticker)
    try:
        if category == "crypto":
            return await okx.get_crypto_price(ticker)
        elif category == "us_stock":
            return await alphavantage.get_us_stock(ticker)
        elif category == "kr_stock":
            return await pykrx_adapter.get_kr_stock(ticker)
        elif category == "fx":
            base, quote = ticker.split("/")
            return await frankfurter.get_fx(base, quote)
    except Exception as e:
        log.warning("fetch_market.ticker.failed", ticker=ticker, error=str(e))
        return None


async def fetch_market_node(state: dict) -> dict:
    tickers: list[str] = state.get("tickers", [])
    if not tickers:
        return {"market_data": MarketSnapshot(fetched_at=datetime.now(timezone.utc))}

    results = await asyncio.gather(*[_fetch_one(t) for t in tickers], return_exceptions=True)

    quotes: list[MarketQuote] = []
    errors: list[str] = []
    for t, r in zip(tickers, results):
        if isinstance(r, MarketQuote):
            quotes.append(r)
        elif isinstance(r, Exception):
            errors.append(f"{t}: {r}")
        elif r is None:
            errors.append(f"{t}: no data")

    snapshot = MarketSnapshot(
        quotes=quotes,
        errors=errors,
        fetched_at=datetime.now(timezone.utc),
    )
    return {"market_data": snapshot}
```

### Task 2a.8: fetch_news 노드 (병렬 뉴스 수집)

**Files:**
- Create: `nodes/fetch_news.py`

- [ ] **Step 1: `nodes/fetch_news.py`**

```python
import asyncio
from datetime import datetime, timezone

from infra.logging_config import get_logger
from schemas.news import NewsSnapshot, NewsItem
from tools.sources import naver, finnhub, alphavantage

log = get_logger("fetch_news_node")


async def fetch_news_node(state: dict) -> dict:
    query: str = state.get("query", "")
    tickers: list[str] = state.get("tickers", [])
    lang: str = state.get("lang", "ko")

    coros = []

    # Korean: Naver search is primary
    if lang == "ko" and query:
        coros.append(naver.search_naver_news(query, display=5))

    # US tickers: Finnhub company news + AV sentiment
    us_tickers = [t for t in tickers if not t.replace("/", "").isdigit() and "/" not in t and not t.upper() in {"BTC","ETH","SOL","XRP","DOGE","ADA","DOT"}]
    if us_tickers:
        coros.extend([finnhub.get_company_news(t) for t in us_tickers[:3]])
        coros.append(alphavantage.get_sentiment_news(us_tickers[:3]))

    if not coros:
        return {"news_data": NewsSnapshot(fetched_at=datetime.now(timezone.utc))}

    results = await asyncio.gather(*coros, return_exceptions=True)

    items: list[NewsItem] = []
    errors: list[str] = []
    for r in results:
        if isinstance(r, NewsSnapshot):
            items.extend(r.items)
            errors.extend(r.errors)
        elif isinstance(r, Exception):
            errors.append(str(r))

    return {
        "news_data": NewsSnapshot(
            items=items[:15],  # 상위 15개로 제한
            errors=errors,
            fetched_at=datetime.now(timezone.utc),
        )
    }
```

### Task 2a.9: analyze 노드 (LLM)

**Files:**
- Create: `nodes/analyze.py`, `prompts/analyze.md`

- [ ] **Step 1: `prompts/analyze.md`**

```markdown
당신은 시니어 금융 애널리스트입니다.

주어진 시세 데이터와 뉴스를 종합하여 한국어로 근거 기반 분석을 제공하세요.

## 분석 포맷
- 현재 가격 동향 요약 (종목명 굵게, 가격/변동률 명시)
- 뉴스와 가격의 연관성 (명시적 인용)
- 단기 방향성 판단 (근거 기반, 추측 금지)
- 리스크 요인 (구체적으로)

## 제약
- 간결하게 핵심만 (장황한 설명 금지)
- 데이터가 부족하면 "데이터 부족" 명시
- 매매 권유 금지 (Phase 1은 분석만)
- 코인은 $, 한국 주식은 ₩ 접두사
```

- [ ] **Step 2: `nodes/analyze.py`**

```python
import os

from langchain_core.messages import SystemMessage, HumanMessage

from infra.llm import get_llm
from infra.logging_config import get_logger
from schemas.market import MarketSnapshot
from schemas.news import NewsSnapshot

log = get_logger("analyze_node")


def _load_prompt() -> str:
    prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "analyze.md")
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def _format_context(market: MarketSnapshot, news: NewsSnapshot, query: str) -> str:
    parts = [f"## 사용자 질문\n{query}\n"]

    if market.quotes:
        parts.append("## 시세 데이터")
        for q in market.quotes:
            parts.append(
                f"- **{q.symbol}** ({q.category}): {q.currency} {q.price:,.2f} "
                f"({q.change_pct:+.2f}% 변동)" if q.change_pct else
                f"- **{q.symbol}** ({q.category}): {q.currency} {q.price:,.2f}"
            )
    if market.errors:
        parts.append(f"\n⚠️ 시세 누락: {', '.join(market.errors[:3])}")

    if news.items:
        parts.append("\n## 뉴스")
        for n in news.items[:10]:
            sentiment = f" [감성: {n.sentiment_label}]" if n.sentiment_label else ""
            parts.append(f"- {n.title}{sentiment}")
            if n.summary:
                parts.append(f"  요약: {n.summary[:150]}")

    return "\n".join(parts)


async def analyze_node(state: dict) -> dict:
    market: MarketSnapshot = state["market_data"]
    news: NewsSnapshot = state["news_data"]
    query: str = state.get("query", "")

    system_prompt = _load_prompt()
    context = _format_context(market, news, query)

    llm = get_llm("analyze")

    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=context),
        ])
        analysis = response.content
        log.info("analyze.success", length=len(analysis))
        return {"analysis": analysis}
    except Exception as e:
        log.error("analyze.failed", error=str(e))
        return {"analysis": f"분석 실패: {e}", "errors": state.get("errors", []) + [str(e)]}
```

### Task 2a.10: research_graph 조립 + 래퍼 도구

**Files:**
- Create: `agents/research_graph.py`, `agents/research_tool.py`

- [ ] **Step 1: `agents/research_graph.py`**

```python
from typing import Literal, TypedDict, Optional

from langgraph.graph import StateGraph, START, END

from nodes.fetch_market import fetch_market_node
from nodes.fetch_news import fetch_news_node
from nodes.analyze import analyze_node
from schemas.market import MarketSnapshot
from schemas.news import NewsSnapshot


class ResearchState(TypedDict):
    query: str
    tickers: list[str]
    lang: Literal["ko", "en"]
    market_data: Optional[MarketSnapshot]
    news_data: Optional[NewsSnapshot]
    analysis: Optional[str]
    errors: list[str]


def build_research_graph():
    g = StateGraph(ResearchState)
    g.add_node("fetch_market", fetch_market_node)
    g.add_node("fetch_news", fetch_news_node)
    g.add_node("analyze", analyze_node)

    # 병렬 fan-out
    g.add_edge(START, "fetch_market")
    g.add_edge(START, "fetch_news")
    # fan-in to analyze (LangGraph waits for both)
    g.add_edge("fetch_market", "analyze")
    g.add_edge("fetch_news", "analyze")
    g.add_edge("analyze", END)

    return g.compile()


research_graph = build_research_graph()


def format_research_result(state: ResearchState) -> str:
    parts = []
    if state.get("analysis"):
        parts.append(state["analysis"])

    market = state.get("market_data")
    if market and market.errors:
        parts.append(f"\n\n⚠️ 일부 시세 수집 실패: {', '.join(market.errors[:3])}")

    news = state.get("news_data")
    if news and news.errors:
        parts.append(f"\n⚠️ 일부 뉴스 수집 실패: {', '.join(news.errors[:3])}")

    return "\n".join(parts) if parts else "데이터를 조회하지 못했습니다."


async def run_research(query: str, tickers: list[str], lang: str = "ko") -> str:
    initial: ResearchState = {
        "query": query,
        "tickers": tickers,
        "lang": lang,
        "market_data": None,
        "news_data": None,
        "analysis": None,
        "errors": [],
    }
    result = await research_graph.ainvoke(initial)
    return format_research_result(result)
```

- [ ] **Step 2: `agents/research_tool.py`**

```python
from langchain_core.tools import tool

from agents.research_graph import run_research


@tool
async def research(query: str, tickers: list[str] | None = None, lang: str = "ko") -> str:
    """금융 시장 리서치 도구. 시세와 뉴스를 병렬로 수집해 종합 분석을 반환합니다.

    Args:
        query: 사용자의 질문 (예: "BTC 시세 어때", "반도체 전망")
        tickers: 분석할 종목 리스트. 크립토는 BTC/ETH, 미국 주식은 AAPL/TSLA,
                 한국 주식은 6자리 종목코드 (예: 005930), 환율은 USD/KRW 형식.
        lang: 응답 언어 ("ko" 또는 "en", 기본 ko)

    Returns:
        구조화된 분석 텍스트. 시세 + 뉴스 + 판단 + 리스크.
    """
    return await run_research(query, tickers or [], lang)
```

### Task 2a.11: 헤드리스 테스트

- [ ] **Step 1: 로컬 테스트 스크립트로 검증**

```bash
cd financial-bot-agent/app/FinancialAgent
export OPENAI_API_KEY=<your-key>
export ALPHA_VANTAGE_API_KEY=<key>
export FINNHUB_API_KEY=<key>
export NAVER_CLIENT_ID=<id>
export NAVER_CLIENT_SECRET=<secret>

uv run python -c "
import asyncio
from infra.logging_config import setup_logging
from agents.research_graph import run_research

setup_logging()
result = asyncio.run(run_research('BTC 요즘 어때?', ['BTC'], 'ko'))
print(result)
"
```

Expected: 분석 텍스트가 출력됨 (시세 + 뉴스 요약 + 판단).

### Task 2a.12: Commit

- [ ] **Step 1: Commit**

```bash
git add financial-bot-agent/
git commit -m "feat(m2a): research subgraph with 6 data source adapters"
```

---

## Milestone 2b — Orchestrator + Supporting Tools

**Goal:** LangChain `create_agent` 오케스트레이터 + watchlist/briefing/preferences/sessions 도구. `agentcore dev`로 대화형 봇 로컬 테스트.

### Task 2b.1: Watchlist 도구

**Files:**
- Create: `tools/watchlist.py`

- [ ] **Step 1: `tools/watchlist.py`**

```python
from datetime import datetime, timezone

from langchain_core.tools import tool

from storage.ddb import put_item, get_item, query_by_sk_prefix, delete_item


def _detect_category(symbol: str) -> str:
    s = symbol.upper()
    if s.isdigit() and len(s) == 6:
        return "kr_stock"
    if "/" in s:
        return "fx"
    if s in {"BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "DOT"}:
        return "crypto"
    return "us_stock"


@tool
def list_watchlist() -> str:
    """사용자의 관심 종목 목록을 반환합니다."""
    items = query_by_sk_prefix("WATCH#")
    if not items:
        return "관심 종목이 없습니다."
    lines = ["## 관심 종목"]
    for item in items:
        lines.append(f"- {item['symbol']} ({item['category']}) — 추가: {item.get('added_at', '?')}")
    return "\n".join(lines)


@tool
def add_watchlist(symbol: str, category: str = "") -> str:
    """관심 종목에 추가합니다.

    Args:
        symbol: 종목 심볼 (BTC, AAPL, 005930, USD/KRW 등)
        category: crypto/us_stock/kr_stock/fx 중 하나. 비워두면 자동 감지.
    """
    cat = category or _detect_category(symbol)
    put_item(f"WATCH#{symbol.upper()}", {
        "symbol": symbol.upper(),
        "category": cat,
        "added_at": datetime.now(timezone.utc).isoformat(),
    })
    return f"✅ {symbol} ({cat}) 관심 종목에 추가됨"


@tool
def remove_watchlist(symbol: str) -> str:
    """관심 종목에서 제거합니다."""
    delete_item(f"WATCH#{symbol.upper()}")
    return f"🗑️ {symbol} 관심 종목에서 제거됨"
```

### Task 2b.2: Briefing 조회 도구

**Files:**
- Create: `tools/briefing.py`

- [ ] **Step 1: `tools/briefing.py`**

```python
from langchain_core.tools import tool

from storage.ddb import get_item, query_by_sk_prefix


@tool
def get_briefings(limit: int = 5) -> str:
    """최근 브리핑 목록을 반환합니다."""
    items = query_by_sk_prefix("BRIEF#", limit=limit, ascending=False)
    if not items:
        return "브리핑이 없습니다."
    lines = ["## 최근 브리핑"]
    for item in items:
        lines.append(f"- {item['date']} {item['time_of_day']} [{item.get('status', '?')}]")
    return "\n".join(lines)


@tool
def get_briefing(date: str, time_of_day: str) -> str:
    """특정 브리핑의 전체 내용을 반환합니다.

    Args:
        date: YYYY-MM-DD
        time_of_day: AM 또는 PM
    """
    item = get_item(f"BRIEF#{date}-{time_of_day.upper()}")
    if not item:
        return f"{date} {time_of_day} 브리핑을 찾을 수 없습니다."
    return f"## {date} {time_of_day} 브리핑\n\n{item.get('content', '(내용 없음)')}"
```

### Task 2b.3: Preferences 도구

**Files:**
- Create: `tools/preferences.py`

- [ ] **Step 1: `tools/preferences.py`**

```python
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
        key = item["SK"].replace("PREF#", "")
        lines.append(f"- {key}: {item.get('value', '')}")
    return "\n".join(lines)


@tool
def set_preference(key: str, value: str) -> str:
    """사용자 선호도를 설정합니다.

    예: set_preference("tone", "concise") → 응답 톤을 간결하게
         set_preference("language", "ko") → 기본 언어 한국어
    """
    # Phase-forward: migrate to UserPreferenceMemoryStrategy in Phase 2
    put_item(f"PREF#{key}", {
        "value": value,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return f"✅ 선호도 '{key}' = '{value}' 저장됨"
```

### Task 2b.4: Sessions 도구

**Files:**
- Create: `tools/sessions.py`

- [ ] **Step 1: `tools/sessions.py`**

```python
from datetime import datetime, timezone

from langchain_core.tools import tool

from storage.ddb import put_item, get_item, query_by_sk_prefix


@tool
def list_sessions(limit: int = 20) -> str:
    """최근 대화 세션 목록."""
    items = query_by_sk_prefix("SESS#", limit=limit, ascending=False)
    if not items:
        return "세션이 없습니다."
    lines = ["## 최근 세션"]
    for item in items:
        lines.append(f"- {item.get('title', '제목 없음')} ({item.get('message_count', 0)}개 메시지)")
    return "\n".join(lines)


def upsert_session(session_id: str, title: str = "", increment_message: bool = True):
    """내부 함수: 세션 메타데이터 업데이트. Tool로 노출 안 함."""
    existing = get_item(f"SESS#{session_id}")
    now = datetime.now(timezone.utc).isoformat()
    if existing:
        count = existing.get("message_count", 0) + (1 if increment_message else 0)
        put_item(f"SESS#{session_id}", {
            "title": existing.get("title", title),
            "created_at": existing.get("created_at", now),
            "last_active_at": now,
            "message_count": count,
        })
    else:
        put_item(f"SESS#{session_id}", {
            "title": title or "새 대화",
            "created_at": now,
            "last_active_at": now,
            "message_count": 1 if increment_message else 0,
        })
```

### Task 2b.5: 오케스트레이터 시스템 프롬프트

**Files:**
- Create: `prompts/orchestrator.md`

- [ ] **Step 1: `prompts/orchestrator.md`**

```markdown
당신은 개인 금융 어시스턴트입니다. 사용자의 질문을 분석하고 적절한 도구를 호출해 답변합니다.

## 역할
- 금융/경제 관련 질문 답변 (시세, 뉴스, 분석)
- 관심 종목 관리 (추가/제거/조회)
- 사용자 선호도 저장/조회
- 브리핑 히스토리 조회

## 도구 사용 원칙
- **research**: 시세/뉴스/분석이 필요할 때. 여러 종목을 한 번에 처리 가능.
- **list_watchlist / add_watchlist / remove_watchlist**: 관심 종목 관리
- **get_briefings / get_briefing**: 과거 브리핑 조회
- **get_preferences / set_preference**: 사용자 선호도
- **list_sessions**: 과거 대화 목록

## 규칙
- 사용자에게 "조회하겠습니다" 같은 예고 없이 즉시 도구 호출
- 복합 요청은 필요한 도구를 모두 호출 (예: "BTC 시세랑 관심종목에 추가해줘" → research + add_watchlist)
- 오타 허용: "비ㅌ코인" = 비트코인, "엔비디야" = 엔비디아
- 한국어 응답이 기본 (사용자가 영어로 요청하면 영어)

## Phase 1 제약 (중요)
- **매매 기능 없음**: 사용자가 "BTC 사줘" 같은 매매 요청을 하면 "Phase 1에서는 분석만 제공합니다. 매매는 Phase 2부터 지원 예정입니다."라고 응답
- 실제 주문/체결 기능 없음

## 출력 포맷
- 코인 가격: $ 접두사, 한국 주식: ₩ 접두사
- 변동률: 🔺(상승) / 🔻(하락) 이모지
- 뉴스: 번호 + 제목 + 1-2줄 요약
- 간결하게, 장황한 설명 금지
```

### Task 2b.6: 오케스트레이터 조립

**Files:**
- Create: `agents/orchestrator.py`

- [ ] **Step 1: `agents/orchestrator.py`**

```python
import os

from langgraph.prebuilt import create_react_agent

from agents.research_tool import research
from infra.llm import get_llm
from tools.watchlist import list_watchlist, add_watchlist, remove_watchlist
from tools.briefing import get_briefings, get_briefing
from tools.preferences import get_preferences, set_preference
from tools.sessions import list_sessions

_orchestrator = None


def _load_prompt() -> str:
    prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "orchestrator.md")
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        llm = get_llm("orchestrator")

        tools = [
            research,
            list_watchlist, add_watchlist, remove_watchlist,
            get_briefings, get_briefing,
            get_preferences, set_preference,
            list_sessions,
        ]

        _orchestrator = create_react_agent(
            llm,
            tools=tools,
            prompt=_load_prompt(),
        )
    return _orchestrator
```

### Task 2b.7: main.py entrypoint 연결

**Files:**
- Modify: `app/FinancialAgent/main.py`

- [ ] **Step 1: `main.py`**

```python
import json
import os
import uuid

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langchain_core.messages import HumanMessage

from agents.orchestrator import get_orchestrator
from infra.logging_config import setup_logging, get_logger, correlation_id_var
from schemas.invoke import InvokeChatPayload
from tools.sessions import upsert_session

setup_logging()
log = get_logger("main")

app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload, context):
    action = payload.get("action", "chat")
    correlation_id = payload.get("correlation_id") or str(uuid.uuid4())
    correlation_id_var.set(correlation_id)

    log.info("invoke.start", action=action)

    if action == "chat":
        parsed = InvokeChatPayload(**payload)
        orchestrator = get_orchestrator()

        yield {"event": "session_start", "session_id": parsed.session_id}

        messages = [HumanMessage(content=parsed.message)]
        final_text = ""

        async for chunk in orchestrator.astream(
            {"messages": messages},
            stream_mode="updates",
        ):
            for node_name, node_output in chunk.items():
                if "messages" in node_output:
                    for msg in node_output["messages"]:
                        if msg.type == "tool":
                            yield {"event": "tool_result", "tool": msg.name, "content": msg.content[:500]}
                        elif msg.type == "ai" and msg.tool_calls:
                            for tc in msg.tool_calls:
                                yield {"event": "tool_call", "tool": tc["name"], "args": tc["args"]}
                        elif msg.type == "ai" and msg.content:
                            final_text = msg.content
                            yield {"event": "assistant", "content": msg.content}

        # 세션 메타데이터 업데이트
        upsert_session(parsed.session_id, title=parsed.message[:50])

        yield {"event": "complete"}
        log.info("invoke.complete", session_id=parsed.session_id)


if __name__ == "__main__":
    app.run()
```

### Task 2b.8: 로컬 통합 테스트

- [ ] **Step 1: dev.sh 스크립트**

Create `financial-bot-agent/dev.sh`:
```bash
#!/bin/bash
export AWS_PROFILE=developer-dongik
export OPENAI_API_KEY=<your-key>
export ALPHA_VANTAGE_API_KEY=<key>
export FINNHUB_API_KEY=<key>
export NAVER_CLIENT_ID=<id>
export NAVER_CLIENT_SECRET=<secret>
export LANGSMITH_API_KEY=<key>
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_PROJECT=financial-bot-phase1
export DDB_TABLE=financial-bot

# Use local DynamoDB for dev? Or create real table first.
cd agentcore
agentcore dev
```

```bash
chmod +x financial-bot-agent/dev.sh
```

- [ ] **Step 2: DynamoDB 테이블 생성 (로컬용, 임시)**

```bash
AWS_PROFILE=developer-dongik aws dynamodb create-table \
  --table-name financial-bot \
  --attribute-definitions AttributeName=PK,AttributeType=S AttributeName=SK,AttributeType=S \
  --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

- [ ] **Step 3: agentcore dev 실행**

```bash
cd financial-bot-agent
./dev.sh
```

- [ ] **Step 4: curl 테스트 3가지**

```bash
# 1. 간단한 시세
curl -N -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"action":"chat","session_id":"test1","message":"BTC 시세 알려줘"}'

# 2. Watchlist 추가
curl -N -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"action":"chat","session_id":"test1","message":"NVDA 관심종목에 추가해줘"}'

# 3. 시장 분석
curl -N -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"action":"chat","session_id":"test1","message":"오늘 반도체 섹터 어때?"}'
```

Expected: 각 요청마다 tool_call → tool_result → assistant 이벤트가 스트림됨.

### Task 2b.9: Commit

- [ ] **Step 1: Commit**

```bash
git add financial-bot-agent/
git commit -m "feat(m2b): orchestrator + supporting tools + local e2e tested"
```

---

## Milestone 3 — Frontend Shell (React + Terminal Feed + SigV4)

**Goal:** React 프로젝트 + Terminal Feed 디자인 + 3-pane 레이아웃 + 로컬 백엔드 연동. SigV4는 M5에서 배포 후 연결.

### Task 3.1: Vite + React 프로젝트 생성

- [ ] **Step 1: 프로젝트 생성**

```bash
cd /Users/douggy/per-projects/agentcore-service
pnpm create vite financial-bot-frontend --template react-ts
cd financial-bot-frontend
pnpm install
pnpm install -D tailwindcss @tailwindcss/vite
pnpm install @aws-amplify/core @aws-amplify/auth \
             @aws-sdk/client-bedrock-agentcore-runtime \
             @aws-sdk/credential-providers
```

- [ ] **Step 2: vite.config.ts**

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3000,
    proxy: {
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
```

### Task 3.2: Terminal Feed CSS + 3-pane 레이아웃

**Files:**
- Modify: `src/index.css`
- Create: `src/components/layout/TerminalFrame.tsx`

- [ ] **Step 1: `src/index.css`**

```css
@import url("https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500;700&display=swap");
@import "tailwindcss";

@theme {
  --font-mono: "JetBrains Mono", monospace;
  --font-data: "IBM Plex Mono", monospace;

  --color-bg: #0a0e0f;
  --color-fg: #fba91a;
  --color-fg-dim: #c0b8a5;
  --color-muted: #5c6b75;
  --color-border: #2a3237;
  --color-up: #39ff14;
  --color-down: #ff4444;
  --color-accent: #fba91a;
}

html {
  background: var(--color-bg);
  color-scheme: dark;
}

body {
  font-family: var(--font-mono);
  background: var(--color-bg);
  color: var(--color-fg-dim);
  min-height: 100vh;
}

/* CRT scanlines */
#root::before {
  content: "";
  position: fixed;
  inset: 0;
  z-index: 9999;
  pointer-events: none;
  background: linear-gradient(rgba(251, 169, 26, 0.02) 50%, transparent 50%);
  background-size: 100% 3px;
}

/* Vignette */
#root::after {
  content: "";
  position: fixed;
  inset: 0;
  z-index: 9998;
  pointer-events: none;
  background: radial-gradient(ellipse at center, transparent 40%, rgba(0,0,0,0.5) 100%);
}

::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--color-border); }
```

- [ ] **Step 2: `src/components/layout/TerminalFrame.tsx`**

```tsx
import type { ReactNode } from "react";

interface TerminalFrameProps {
  sessions: ReactNode;
  watchlist: ReactNode;
  chat: ReactNode;
}

function TerminalFrame({ sessions, watchlist, chat }: TerminalFrameProps) {
  return (
    <div className="h-screen flex flex-col">
      <div className="bg-fg text-bg px-4 py-1.5 flex justify-between text-xs font-bold uppercase tracking-widest">
        <span>FINBOT 0.1 · PHASE 1</span>
        <span>{new Date().toISOString().replace("T", " ").slice(0, 19)} · ONLINE</span>
      </div>
      <div className="flex-1 grid grid-cols-[200px_280px_1fr] overflow-hidden">
        <div className="border-r border-border p-3 overflow-y-auto">{sessions}</div>
        <div className="border-r border-border p-3 overflow-y-auto">{watchlist}</div>
        <div className="overflow-hidden flex flex-col">{chat}</div>
      </div>
    </div>
  );
}

export default TerminalFrame;
```

### Task 3.3: 간단한 채팅 + 로컬 백엔드 연동

**Files:**
- Create: `src/hooks/useAgentStream.ts`
- Create: `src/components/chat/ChatPane.tsx`
- Modify: `src/App.tsx`

- [ ] **Step 1: `src/hooks/useAgentStream.ts`**

```typescript
import { useState, useCallback, useRef } from "react";

export interface StreamEvent {
  event: string;
  [key: string]: unknown;
}

export function useAgentStream() {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setEvents([]);
    setIsStreaming(false);
  }, []);

  const sendMessage = useCallback(async (sessionId: string, message: string) => {
    setIsStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch("/api/invocations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "chat",
          session_id: sessionId,
          message,
          correlation_id: crypto.randomUUID(),
        }),
        signal: controller.signal,
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const reader = response.body?.getReader();
      if (!reader) throw new Error("No body");
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() || "";

        for (const frame of frames) {
          const line = frame.trim();
          if (!line.startsWith("data: ")) continue;
          try {
            let parsed = JSON.parse(line.slice(6));
            if (typeof parsed === "string") parsed = JSON.parse(parsed);
            setEvents((prev) => [...prev, parsed]);
          } catch {
            // ignore
          }
        }
      }
    } catch (err) {
      if (err instanceof Error && err.name !== "AbortError") {
        setEvents((prev) => [...prev, { event: "error", message: err.message }]);
      }
    } finally {
      setIsStreaming(false);
    }
  }, []);

  return { events, isStreaming, sendMessage, reset };
}
```

- [ ] **Step 2: `src/components/chat/ChatPane.tsx`**

```tsx
import { useState, useRef, useEffect } from "react";
import { useAgentStream, type StreamEvent } from "../../hooks/useAgentStream";

interface ChatPaneProps {
  sessionId: string;
}

function renderEvent(ev: StreamEvent, idx: number) {
  switch (ev.event) {
    case "tool_call":
      return (
        <div key={idx} className="text-xs text-muted my-1">
          ▸ <span className="text-fg">{String(ev.tool)}</span>({JSON.stringify(ev.args).slice(0, 80)})
        </div>
      );
    case "tool_result":
      return (
        <div key={idx} className="text-xs text-up my-1 ml-4">
          ✓ {String(ev.tool)} → {String(ev.content).slice(0, 200)}
        </div>
      );
    case "assistant":
      return (
        <div key={idx} className="text-sm text-fg whitespace-pre-wrap my-2 border-l-2 border-fg pl-3">
          {String(ev.content)}
        </div>
      );
    case "complete":
      return <div key={idx} className="text-xs text-muted">── done ──</div>;
    case "error":
      return <div key={idx} className="text-sm text-down">ERROR: {String(ev.message)}</div>;
    default:
      return null;
  }
}

function ChatPane({ sessionId }: ChatPaneProps) {
  const [input, setInput] = useState("");
  const { events, isStreaming, sendMessage } = useAgentStream();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [events.length]);

  const handleSend = () => {
    if (!input.trim() || isStreaming) return;
    sendMessage(sessionId, input);
    setInput("");
  };

  return (
    <div className="h-full flex flex-col">
      <div className="border-b border-border px-4 py-2 text-xs text-fg uppercase tracking-wider">
        {sessionId} · {events.length} events
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4">
        {events.map(renderEvent)}
        {isStreaming && <span className="inline-block w-2 h-4 bg-fg animate-pulse" />}
      </div>
      <div className="border-t border-border p-3">
        <div className="flex gap-2">
          <input
            className="flex-1 bg-transparent border border-border px-3 py-2 text-sm text-fg-dim font-mono outline-none focus:border-fg"
            placeholder="> Ask about markets..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            disabled={isStreaming}
          />
          <button
            onClick={handleSend}
            disabled={isStreaming || !input.trim()}
            className="bg-fg text-bg px-4 py-2 text-xs font-bold uppercase disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

export default ChatPane;
```

- [ ] **Step 3: `src/App.tsx`**

```tsx
import { useState } from "react";
import TerminalFrame from "./components/layout/TerminalFrame";
import ChatPane from "./components/chat/ChatPane";

function App() {
  const [sessionId] = useState(() => `sess-${Date.now()}`);

  return (
    <TerminalFrame
      sessions={
        <div>
          <button className="w-full bg-fg text-bg text-xs font-bold py-2 mb-3 uppercase">+ New</button>
          <div className="text-xs text-muted uppercase mb-2">── Sessions ──</div>
          <div className="text-xs text-fg">{sessionId}</div>
        </div>
      }
      watchlist={
        <div>
          <div className="text-xs text-muted uppercase mb-2">── Watchlist ──</div>
          <div className="text-xs text-fg-dim">Loading...</div>
        </div>
      }
      chat={<ChatPane sessionId={sessionId} />}
    />
  );
}

export default App;
```

### Task 3.4: 로컬 프론트엔드 테스트

- [ ] **Step 1: 두 터미널에서 실행**

터미널 1:
```bash
cd financial-bot-agent
./dev.sh
```

터미널 2:
```bash
cd financial-bot-frontend
pnpm dev
```

- [ ] **Step 2: 브라우저 테스트**

http://localhost:3000 → "BTC 시세" 입력 → tool_call + tool_result + assistant 이벤트가 화면에 나와야 함.

### Task 3.5: Commit

- [ ] **Step 1: Commit**

```bash
git add financial-bot-frontend/
git commit -m "feat(m3): react terminal feed UI + local backend integration"
```

---

## Milestone 4 — Briefing Flow

**Goal:** `/briefing` 커스텀 라우트 + 브리핑 생성 핸들러 + (M5에서 Lambda 배포 전) 로컬 curl 테스트.

### Task 4.1: `/briefing` 라우트 핸들러

**Files:**
- Create: `handlers/briefing.py`
- Create: `prompts/briefing.md`
- Modify: `main.py`

- [ ] **Step 1: `prompts/briefing.md`**

```markdown
당신은 개인 금융 브리핑 작성자입니다. 사용자의 관심 종목과 시장 데이터를 기반으로 한국어 일간 브리핑을 작성합니다.

## 브리핑 구조
### 🌅 [아침/저녁] 브리핑 — YYYY-MM-DD

#### 📊 시장 요약
(주요 지수 변동, 전반적 분위기 1-2문장)

#### 💼 관심 종목
- **SYMBOL**: 가격 변동률 + 간단한 코멘트
- (관심 종목 개수만큼)

#### 📰 주요 뉴스 (3-5건)
1. [제목] — 요약 1-2줄

#### 🎯 오늘/내일 주목 포인트
(1-2개 불릿 포인트)

## 제약
- 간결하게 (800자 내외)
- 매매 권유 금지
- 데이터 없는 종목은 "데이터 누락" 표시
```

- [ ] **Step 2: `handlers/briefing.py`**

```python
import asyncio
from datetime import datetime, timezone
from typing import Literal

from starlette.requests import Request
from starlette.responses import JSONResponse

from agents.research_graph import run_research
from infra.logging_config import get_logger
from schemas.briefing import BriefingRecord
from storage.ddb import put_item, query_by_sk_prefix

log = get_logger("briefing_handler")


def _kst_date() -> str:
    # Convert UTC to KST (UTC+9)
    from datetime import timedelta
    kst = datetime.now(timezone.utc) + timedelta(hours=9)
    return kst.strftime("%Y-%m-%d")


async def generate_briefing(request: Request) -> JSONResponse:
    body = await request.json()
    time_of_day: Literal["AM", "PM"] = body.get("time_of_day", "AM")
    date_str = _kst_date()
    brief_sk = f"BRIEF#{date_str}-{time_of_day}"

    start = datetime.now(timezone.utc)
    log.info("briefing.start", date=date_str, time=time_of_day)

    # 1. 초기 pending 레코드
    put_item(brief_sk, {
        "date": date_str,
        "time_of_day": time_of_day,
        "status": "pending",
        "content": "",
        "generated_at": start.isoformat(),
    })

    try:
        # 2. Watchlist 로드
        watch_items = query_by_sk_prefix("WATCH#")
        tickers = [item["symbol"] for item in watch_items]

        if not tickers:
            put_item(brief_sk, {
                "date": date_str,
                "time_of_day": time_of_day,
                "status": "failed",
                "content": "관심 종목이 없어 브리핑을 생성할 수 없습니다.",
                "generated_at": start.isoformat(),
                "duration_ms": 0,
            })
            return JSONResponse({"status": "failed", "reason": "empty_watchlist"})

        # 3. Research 실행
        query = f"{date_str} {'아침' if time_of_day == 'AM' else '저녁'} 브리핑: {', '.join(tickers)} 시세와 뉴스를 분석해 일간 브리핑을 작성해줘."
        content = await run_research(query, tickers, lang="ko")

        # 4. 상태 판정
        duration_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        # TODO: 더 정교한 partial 판정 (fetch_market.errors 개수 기반)
        status = "success"

        # 5. 최종 저장
        record = BriefingRecord(
            date=date_str,
            time_of_day=time_of_day,
            status=status,
            content=content,
            tickers_covered=tickers,
            generated_at=start,
            duration_ms=duration_ms,
            errors=[],
        )
        put_item(brief_sk, {
            "date": record.date,
            "time_of_day": record.time_of_day,
            "status": record.status,
            "content": record.content,
            "tickers_covered": record.tickers_covered,
            "generated_at": record.generated_at.isoformat(),
            "duration_ms": record.duration_ms,
            "errors": record.errors,
        })

        log.info("briefing.complete", sk=brief_sk, duration_ms=duration_ms)
        return JSONResponse({"status": status, "briefing_sk": brief_sk})

    except Exception as e:
        log.error("briefing.failed", error=str(e))
        put_item(brief_sk, {
            "date": date_str,
            "time_of_day": time_of_day,
            "status": "failed",
            "content": f"브리핑 생성 실패: {e}",
            "generated_at": start.isoformat(),
            "errors": [str(e)],
        })
        return JSONResponse({"status": "failed", "error": str(e)}, status_code=500)
```

- [ ] **Step 3: `main.py`에 라우트 등록**

```python
# main.py 상단 import 추가
from handlers.briefing import generate_briefing

# app 선언 후
app.add_route("/briefing", generate_briefing, methods=["POST"])
```

### Task 4.2: 로컬 브리핑 테스트

- [ ] **Step 1: Watchlist에 종목 몇 개 추가 (채팅으로 or 직접)**

- [ ] **Step 2: curl로 브리핑 생성**

```bash
curl -X POST http://localhost:8080/briefing \
  -H "Content-Type: application/json" \
  -d '{"time_of_day":"AM"}'
```

Expected: `{"status":"success","briefing_sk":"BRIEF#..."}`

- [ ] **Step 3: DDB에서 확인**

```bash
AWS_PROFILE=developer-dongik aws dynamodb scan \
  --table-name financial-bot \
  --filter-expression "begins_with(SK, :prefix)" \
  --expression-attribute-values '{":prefix":{"S":"BRIEF#"}}' \
  --region us-east-1
```

### Task 4.3: Commit

- [ ] **Step 1: Commit**

```bash
git add financial-bot-agent/
git commit -m "feat(m4): briefing generation handler + local tested"
```

---

## Milestone 5 — Cloud Deploy

**Goal:** CDK로 인프라 배포, `agentcore deploy`로 백엔드 배포, 프론트엔드 S3+CloudFront 배포. 첫 프로덕션 라이브.

### Task 5.1: CDK 프로젝트 초기화

**Files:**
- `financial-bot-infra/` CDK TypeScript 프로젝트

- [ ] **Step 1: CDK init**

```bash
cd /Users/douggy/per-projects/agentcore-service/financial-bot-infra
pnpm init -y
pnpm install -D aws-cdk aws-cdk-lib constructs typescript @types/node ts-node
npx cdk init app --language typescript
```

### Task 5.2: DynamoDB 스택

**Files:**
- Create: `financial-bot-infra/lib/dynamodb-stack.ts`

- [ ] **Step 1: `lib/dynamodb-stack.ts`**

```typescript
import { Stack, StackProps, RemovalPolicy } from "aws-cdk-lib";
import { Table, AttributeType, BillingMode } from "aws-cdk-lib/aws-dynamodb";
import { Construct } from "constructs";

export class FinancialBotDynamoDBStack extends Stack {
  public readonly table: Table;

  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    this.table = new Table(this, "FinancialBotTable", {
      tableName: "financial-bot",
      partitionKey: { name: "PK", type: AttributeType.STRING },
      sortKey: { name: "SK", type: AttributeType.STRING },
      billingMode: BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: "expireAt",
      removalPolicy: RemovalPolicy.RETAIN,
    });
  }
}
```

### Task 5.3: Cognito Identity Pool 스택

**Files:**
- Create: `financial-bot-infra/lib/cognito-stack.ts`

- [ ] **Step 1: `lib/cognito-stack.ts`**

```typescript
import { Stack, StackProps, CfnOutput } from "aws-cdk-lib";
import { CfnIdentityPool, CfnIdentityPoolRoleAttachment } from "aws-cdk-lib/aws-cognito";
import { Role, FederatedPrincipal, PolicyStatement, Effect } from "aws-cdk-lib/aws-iam";
import { Construct } from "constructs";

export class FinancialBotCognitoStack extends Stack {
  public readonly identityPoolId: string;

  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    const pool = new CfnIdentityPool(this, "FinancialBotIdentityPool", {
      identityPoolName: "financial_bot_pool",
      allowUnauthenticatedIdentities: true,
    });

    const guestRole = new Role(this, "GuestRole", {
      assumedBy: new FederatedPrincipal(
        "cognito-identity.amazonaws.com",
        {
          StringEquals: { "cognito-identity.amazonaws.com:aud": pool.ref },
          "ForAnyValue:StringLike": { "cognito-identity.amazonaws.com:amr": "unauthenticated" },
        },
        "sts:AssumeRoleWithWebIdentity",
      ),
    });

    guestRole.addToPolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["bedrock-agentcore:InvokeAgentRuntime"],
      resources: [
        `arn:aws:bedrock-agentcore:${this.region}:${this.account}:runtime/financial-bot-*`,
      ],
    }));

    new CfnIdentityPoolRoleAttachment(this, "PoolRoles", {
      identityPoolId: pool.ref,
      roles: { unauthenticated: guestRole.roleArn },
    });

    this.identityPoolId = pool.ref;

    new CfnOutput(this, "IdentityPoolIdOutput", { value: pool.ref });
  }
}
```

### Task 5.4: 브리핑 Lambda + EventBridge 스택

**Files:**
- Create: `financial-bot-infra/lib/briefing-stack.ts`
- Create: `financial-bot-infra/lambda/briefing-proxy/index.ts`
- Create: `financial-bot-infra/lambda/briefing-proxy/package.json`

- [ ] **Step 1: Lambda 코드**

`lambda/briefing-proxy/package.json`:
```json
{
  "name": "briefing-proxy",
  "version": "1.0.0",
  "type": "module",
  "dependencies": {
    "@aws-sdk/client-bedrock-agentcore-runtime": "^3.700.0"
  }
}
```

`lambda/briefing-proxy/index.ts`:
```typescript
import {
  BedrockAgentCoreRuntimeClient,
  InvokeAgentRuntimeCommand,
} from "@aws-sdk/client-bedrock-agentcore-runtime";

const client = new BedrockAgentCoreRuntimeClient({
  region: process.env.AWS_REGION || "us-east-1",
});

const RUNTIME_ARN = process.env.AGENTCORE_RUNTIME_ARN!;

interface Event {
  time_of_day: "AM" | "PM";
  dry_run?: boolean;
}

export const handler = async (event: Event) => {
  console.log("briefing-proxy.start", event);

  if (event.dry_run) {
    return { status: "dry_run", event };
  }

  const maxAttempts = 3;
  let lastError: unknown;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const command = new InvokeAgentRuntimeCommand({
        agentRuntimeArn: RUNTIME_ARN,
        payload: new TextEncoder().encode(JSON.stringify({
          time_of_day: event.time_of_day,
          correlation_id: `briefing-${Date.now()}`,
        })),
        qualifier: "DEFAULT",
      });

      const response = await client.send(command);
      console.log("briefing-proxy.success", attempt);
      return { status: "success", attempt };
    } catch (err) {
      lastError = err;
      console.error(`briefing-proxy.attempt_${attempt}_failed`, err);
      if (attempt < maxAttempts) {
        await new Promise((resolve) => setTimeout(resolve, 1000 * Math.pow(2, attempt)));
      }
    }
  }

  throw lastError;
};
```

- [ ] **Step 2: `lib/briefing-stack.ts`**

```typescript
import { Stack, StackProps, Duration } from "aws-cdk-lib";
import { NodejsFunction } from "aws-cdk-lib/aws-lambda-nodejs";
import { Runtime } from "aws-cdk-lib/aws-lambda";
import { Rule, Schedule } from "aws-cdk-lib/aws-events";
import { LambdaFunction } from "aws-cdk-lib/aws-events-targets";
import { Queue } from "aws-cdk-lib/aws-sqs";
import { PolicyStatement, Effect } from "aws-cdk-lib/aws-iam";
import { Construct } from "constructs";
import * as path from "path";

interface BriefingStackProps extends StackProps {
  agentCoreRuntimeArn: string;
}

export class FinancialBotBriefingStack extends Stack {
  constructor(scope: Construct, id: string, props: BriefingStackProps) {
    super(scope, id, props);

    const dlq = new Queue(this, "BriefingDLQ", {
      queueName: "financial-bot-briefing-dlq",
      retentionPeriod: Duration.days(14),
    });

    const proxyFn = new NodejsFunction(this, "BriefingProxy", {
      functionName: "financial-bot-briefing-proxy",
      runtime: Runtime.NODEJS_22_X,
      entry: path.join(__dirname, "../lambda/briefing-proxy/index.ts"),
      handler: "handler",
      timeout: Duration.minutes(5),
      environment: {
        AGENTCORE_RUNTIME_ARN: props.agentCoreRuntimeArn,
      },
      deadLetterQueue: dlq,
    });

    proxyFn.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["bedrock-agentcore:InvokeAgentRuntime"],
      resources: [props.agentCoreRuntimeArn],
    }));

    // Morning briefing: 09:00 KST = 00:00 UTC
    new Rule(this, "MorningBriefingRule", {
      schedule: Schedule.cron({ minute: "0", hour: "0" }),
      targets: [new LambdaFunction(proxyFn, {
        event: { bind: () => ({ inputPathsMap: {}, inputTemplate: '{"time_of_day":"AM"}' }) } as any,
      })],
    });

    // Evening briefing: 18:00 KST = 09:00 UTC
    new Rule(this, "EveningBriefingRule", {
      schedule: Schedule.cron({ minute: "0", hour: "9" }),
      targets: [new LambdaFunction(proxyFn, {
        event: { bind: () => ({ inputPathsMap: {}, inputTemplate: '{"time_of_day":"PM"}' }) } as any,
      })],
    });
  }
}
```

### Task 5.5: Frontend 스택 (S3 + CloudFront)

**Files:**
- Create: `financial-bot-infra/lib/frontend-stack.ts`

- [ ] **Step 1: `lib/frontend-stack.ts`**

```typescript
import { Stack, StackProps, RemovalPolicy, CfnOutput, Duration } from "aws-cdk-lib";
import { Bucket, BlockPublicAccess } from "aws-cdk-lib/aws-s3";
import {
  Distribution,
  ViewerProtocolPolicy,
  AllowedMethods,
  CachePolicy,
  OriginAccessIdentity,
} from "aws-cdk-lib/aws-cloudfront";
import { S3Origin } from "aws-cdk-lib/aws-cloudfront-origins";
import { BucketDeployment, Source } from "aws-cdk-lib/aws-s3-deployment";
import { Construct } from "constructs";
import * as path from "path";

export class FinancialBotFrontendStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    const bucket = new Bucket(this, "FrontendBucket", {
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      removalPolicy: RemovalPolicy.RETAIN,
    });

    const oai = new OriginAccessIdentity(this, "OAI");
    bucket.grantRead(oai);

    const dist = new Distribution(this, "Distribution", {
      defaultBehavior: {
        origin: new S3Origin(bucket, { originAccessIdentity: oai }),
        viewerProtocolPolicy: ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: AllowedMethods.ALLOW_GET_HEAD,
        cachePolicy: CachePolicy.CACHING_OPTIMIZED,
      },
      defaultRootObject: "index.html",
      errorResponses: [
        { httpStatus: 404, responseHttpStatus: 200, responsePagePath: "/index.html" },
      ],
    });

    new BucketDeployment(this, "Deploy", {
      sources: [Source.asset(path.join(__dirname, "../../financial-bot-frontend/dist"))],
      destinationBucket: bucket,
      distribution: dist,
      distributionPaths: ["/*"],
    });

    new CfnOutput(this, "BucketNameOutput", { value: bucket.bucketName });
    new CfnOutput(this, "DistributionDomainOutput", { value: dist.distributionDomainName });
  }
}
```

### Task 5.6: CDK 앱 엔트리 + 배포

**Files:**
- Modify: `financial-bot-infra/bin/financial-bot-infra.ts`

- [ ] **Step 1: `bin/financial-bot-infra.ts`**

```typescript
#!/usr/bin/env node
import "source-map-support/register";
import { App } from "aws-cdk-lib";
import { FinancialBotDynamoDBStack } from "../lib/dynamodb-stack";
import { FinancialBotCognitoStack } from "../lib/cognito-stack";
import { FinancialBotBriefingStack } from "../lib/briefing-stack";
import { FinancialBotFrontendStack } from "../lib/frontend-stack";

const app = new App();
const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION || "us-east-1",
};

new FinancialBotDynamoDBStack(app, "FinancialBotDynamoDB", { env });
new FinancialBotCognitoStack(app, "FinancialBotCognito", { env });

const runtimeArn = process.env.AGENTCORE_RUNTIME_ARN;
if (runtimeArn) {
  new FinancialBotBriefingStack(app, "FinancialBotBriefing", { env, agentCoreRuntimeArn: runtimeArn });
}

new FinancialBotFrontendStack(app, "FinancialBotFrontend", { env });
```

- [ ] **Step 2: DynamoDB + Cognito 먼저 배포**

```bash
cd financial-bot-infra
AWS_PROFILE=developer-dongik pnpm cdk deploy FinancialBotDynamoDB FinancialBotCognito
```

Expected: DDB 테이블 + Identity Pool 생성. Identity Pool ID 출력.

- [ ] **Step 3: Secrets 실제 키 입력**

AWS Console에서 `financial-bot/api-keys` 시크릿에 실제 키 값 입력.

- [ ] **Step 4: AgentCore 백엔드 배포**

```bash
cd financial-bot-agent
AWS_PROFILE=developer-dongik agentcore deploy
```

Expected: Runtime ARN 출력. 복사해서 env로 export.

```bash
export AGENTCORE_RUNTIME_ARN=<output-arn>
```

- [ ] **Step 5: 브리핑 Lambda 배포**

```bash
cd financial-bot-infra
AWS_PROFILE=developer-dongik AGENTCORE_RUNTIME_ARN=$AGENTCORE_RUNTIME_ARN pnpm cdk deploy FinancialBotBriefing
```

- [ ] **Step 6: 프론트엔드 빌드 + 배포**

```bash
cd financial-bot-frontend

# .env.production 생성
cat > .env.production <<EOF
VITE_APP_PASSWORD=<choose-password>
VITE_IDENTITY_POOL_ID=<from-step-2>
VITE_AGENTCORE_RUNTIME_ARN=$AGENTCORE_RUNTIME_ARN
VITE_AWS_REGION=us-east-1
EOF

pnpm build

cd ../financial-bot-infra
AWS_PROFILE=developer-dongik pnpm cdk deploy FinancialBotFrontend
```

Expected: CloudFront URL 출력.

### Task 5.7: SigV4 프론트엔드 통합 (프로덕션용)

**Files:**
- Create: `src/api/agentcore.ts`
- Create: `src/auth/PasswordGate.tsx`
- Modify: `src/hooks/useAgentStream.ts`, `src/App.tsx`

- [ ] **Step 1: SigV4 API 래퍼**

(상세 구현 생략 — `BedrockAgentCoreRuntimeClient` + `fromCognitoIdentityPool` 사용)

이 Task는 M5 배포 후 프로덕션에서 실제로 동작 확인하는 단계입니다. 로컬에서는 Vite proxy로 로컬 백엔드에 붙고, 프로덕션에서는 SigV4로 배포된 AgentCore에 붙습니다.

- [ ] **Step 2: 프로덕션 스모크 테스트**

CloudFront URL 열기 → 비밀번호 입력 → 채팅 테스트 → 브리핑 생성 테스트.

### Task 5.8: CloudWatch 알람

- [ ] **Step 1: 브리핑 누락 알람 + 비용 알람**

(CDK에 추가 or AWS CLI로 수동 생성)

### Task 5.9: Commit

- [ ] **Step 1: Commit**

```bash
git add financial-bot-infra/ financial-bot-frontend/
git commit -m "feat(m5): cloud deployment — cdk infra + agentcore + frontend live"
```

---

## Milestone 6 — Polish & Phase-Forward Audit

**Goal:** 문서화, 운영 런북, Phase 2 준비 감사.

### Task 6.1: README 완성

- [ ] **Step 1: 세 프로젝트 README에 배포/로컬 개발 지침 추가**

### Task 6.2: 운영 런북

**Files:**
- Create: `financial-bot-infra/docs/RUNBOOK.md`

- [ ] **Step 1: 키 로테이션, 수동 브리핑 호출, CloudWatch 로그 확인, DDB 데이터 수정 방법**

### Task 6.3: Phase-forward 감사 문서

**Files:**
- Create: `docs/phase-forward-audit.md`

- [ ] **Step 1: `[phase-forward]` 태그 전체 목록 + Phase 2 준비도 체크**

- DDB 스키마: `POSITION#`, `ORDER#`, `STRATEGY#` 추가 가능 확인
- Orchestrator: 새 도구 추가 시 변경 최소 확인
- LangGraph: HITL interrupt 노드 추가 가능 확인
- Memory: UserPreferenceMemoryStrategy 활성화 경로 확인

### Task 6.4: 코드 리뷰 패스

- [ ] **Step 1: code-reviewer agent로 세 프로젝트 전체 리뷰**

CRITICAL + HIGH 이슈 수정.

### Task 6.5: Commit

- [ ] **Step 1: Final commit**

```bash
git add docs/ financial-bot-*/README.md financial-bot-infra/docs/
git commit -m "docs(m6): readme, runbook, phase-forward audit"
```
