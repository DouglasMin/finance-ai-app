# Financial Bot Phase 2 -- Paper Trading Implementation Plan

**Date:** 2026-04-13
**Status:** Draft
**Scope:** Phase 2 -- Virtual Portfolio + Strategy Agent + PnL Tracking
**Prerequisite:** Phase 1 complete (14 tools, research subgraph, watchlist, briefings, terminal UI)

---

## Overview

Phase 1에서 구축한 분석 전용 금융 봇에 **가상 매매(Paper Trading)** 기능을 추가한다. 사용자는 가상 자금으로 매수/매도 주문을 내고, 포지션과 손익(PnL)을 추적하며, 간단한 전략을 등록해 에이전트가 주기적으로 모니터링하도록 할 수 있다. 실제 브로커 API 연동 없이 기존 Phase 1 data sources(OKX, Alpha Vantage, pykrx, Frankfurter)의 시세를 체결 가격으로 사용한다.

## Scope

### 포함

- 가상 포트폴리오 관리 (초기 자금 설정, 잔고 관리)
- 매수/매도 주문 (시장가 즉시 체결, 현재 시세 = 체결가)
- 포지션 추적 (종목별 보유 수량, 평균 단가, 현재 평가액)
- 주문 히스토리 (전체 거래 내역 조회)
- PnL 계산 (포지션별 미실현 손익, 전체 실현/미실현 손익, 일별 스냅샷)
- Strategy Agent (조건 기반 전략 등록, EventBridge cron 주기적 모니터링)
- 기존 브리핑에 포트폴리오 요약 통합

### 제외

- 실제 자금 매매 (Phase 3)
- 브로커 API 연동 (Phase 3)
- Cognito User Pool + MFA 업그레이드 (Phase 3 -- Paper Trading은 금전 위험 없음)
- WebSocket 스트리밍 (Phase 5)
- Backtesting (Phase 5)
- Cross-currency 포트폴리오 합산 (Phase 3+ -- 현재는 currency별 표시만)

---

## Architecture Changes

### DynamoDB -- 기존 싱글 테이블 확장 (마이그레이션 불필요)

Phase 1 design doc에서 예고한 대로(`[phase-forward]` 마커), 같은 `USER#me` PK 아래 새 SK 패턴만 추가한다.

| Access Pattern | PK | SK | 용도 |
|---|---|---|---|
| 포트폴리오 설정 | `USER#me` | `PORTFOLIO` | 초기 자금, 현재 잔고, 실현 PnL 누계 (단일 아이템) |
| 포지션 조회 | `USER#me` | `POSITION#<symbol>` | 종목별 보유 현황 |
| 포지션 전체 목록 | `USER#me` | `begins_with(POSITION#)` | Query |
| 주문 기록 | `USER#me` | `ORDER#<ulid>` | 개별 주문 (ULID로 시간순 정렬) |
| 주문 히스토리 | `USER#me` | `begins_with(ORDER#)` | Query descending |
| 전략 등록 | `USER#me` | `STRATEGY#<name>` | 전략 정의 + 상태 |
| 전략 목록 | `USER#me` | `begins_with(STRATEGY#)` | Query |
| 전략 실행 로그 | `USER#me` | `STRATLOG#<name>#<ulid>` | 전략별 트리거 이력 |
| 일별 PnL 스냅샷 | `USER#me` | `PNL#<yyyy-mm-dd>` | 포트폴리오 일별 성과 기록 |

### Backend -- 새 파일

| 경로 (app/FinancialAgent/ 기준) | 용도 |
|---|---|
| `schemas/trading.py` | Pydantic: Position, Order, Portfolio, Strategy, PnlSnapshot |
| `storage/trading.py` | 매매 관련 DDB CRUD 헬퍼 (기존 ddb.py 위에 래핑) |
| `tools/trading.py` | 오케스트레이터 도구: init_portfolio, buy, sell, get_portfolio, get_positions, get_orders, get_pnl |
| `tools/strategy.py` | 오케스트레이터 도구: create_strategy, list_strategies, remove_strategy, toggle_strategy, get_strategy_log |
| `agents/strategy_graph.py` | LangGraph 전략 모니터링 서브그래프 |
| `nodes/evaluate_strategy.py` | 전략 조건 평가 노드 (순수 Python) |
| `nodes/execute_paper_trade.py` | 가상 체결 실행 노드 (순수 Python) |
| `handlers/strategy_monitor.py` | EventBridge cron 트리거 핸들러 (POST /strategy-monitor) |
| `prompts/strategy.md` | 전략 평가 관련 프롬프트 (있을 경우) |

### Backend -- 수정 파일

| 경로 | 변경 |
|---|---|
| `agents/orchestrator.py` | `_TOOLS`에 trading 7개 + strategy 5개 = 12개 도구 추가 (총 26개) |
| `prompts/orchestrator.md` | 매매/전략 도구 가이드, Phase 2 규칙 추가, Phase 1 매매 거부 문구 제거 |
| `main.py` | strategy-monitor route 추가, get_portfolio/get_orders action 추가 |
| `handlers/briefing.py` | 포트폴리오 존재 시 브리핑에 보유 현황 + PnL 요약 섹션 추가 |
| `prompts/briefing.md` | 포트폴리오 요약 출력 지시 추가 |

### Frontend -- 새 파일

| 경로 (src/ 기준) | 용도 |
|---|---|
| `components/portfolio/PortfolioPanel.tsx` | 잔고, 총 평가액, PnL 요약 패널 |
| `components/portfolio/PositionRow.tsx` | 개별 포지션 행 |
| `components/portfolio/OrderHistory.tsx` | 주문 내역 테이블 |
| `components/portfolio/PnlChart.tsx` | 일별 PnL 추이 차트 |
| `components/strategy/StrategyPanel.tsx` | 전략 목록 + 상태 |

### Frontend -- 수정 파일

| 경로 | 변경 |
|---|---|
| `App.tsx` | 중앙 패널 탭 구조 (Watchlist / Portfolio / Strategies) |
| `components/layout/TerminalFrame.tsx` | PHASE 2 표기 |
| `types.ts` | Position, Order, Portfolio, Strategy, PnlSnapshot 타입 추가 |
| `api/agentcore.ts` | InvokePayload 새 action, fetchPortfolio 함수 |
| `hooks/useAgentStream.ts` | portfolio/strategy 관련 SSE 이벤트 처리 |

### Infra -- 수정 파일

| 경로 | 변경 |
|---|---|
| `serverless.yml` | strategyMonitorProxy Lambda + EventBridge rule 추가 |
| `src/strategy-monitor-proxy.ts` (신규) | briefing-proxy.ts 동일 패턴 복제 |

---

## Implementation Steps

### Milestone 1: Data Layer + Schemas

**Goal:** DDB 스키마 확장과 Pydantic 모델 정의. 매매 로직의 기반.

#### Task 1.1: Pydantic 스키마 정의

- **File:** `schemas/trading.py`
- **Models:**
  - `Portfolio`: initial_capital, cash_balance, realized_pnl, currency, created_at
  - `Position`: symbol, category, quantity, avg_cost, currency, opened_at, updated_at
  - `Order`: order_id (ULID), symbol, side (buy/sell), quantity, price, total_cost, currency, status (filled), created_at
  - `Strategy`: name, description, condition_type (price_above/price_below/change_pct_above/change_pct_below), target_symbol, threshold, action (alert/buy/sell), quantity, enabled, created_at, last_triggered, trigger_count
  - `PnlSnapshot`: date, total_value, cash, unrealized_pnl, realized_pnl, positions_count
- **Dependencies:** 없음
- **Risk:** Low

#### Task 1.2: Trading DDB 헬퍼

- **File:** `storage/trading.py`
- **Functions:** (기존 `storage/ddb.py`의 put_item/get_item/query_by_sk_prefix/delete_item 재사용)
  - Portfolio: get_portfolio, upsert_portfolio
  - Position: get_position, upsert_position, delete_position, list_positions
  - Order: create_order (ULID 기반 SK 자동 생성), list_orders
  - Strategy: get_strategy, upsert_strategy, delete_strategy, list_strategies, log_strategy_trigger
  - PnL: save_pnl_snapshot, list_pnl_snapshots
- **Dependencies:** Task 1.1
- **Risk:** Low

---

### Milestone 2: Core Trading Engine

**Goal:** 가상 매수/매도의 핵심 로직. 오케스트레이터 도구로 노출.

#### Task 2.1: Trading 도구

- **File:** `tools/trading.py`
- **Tools (7개):**
  - `init_portfolio(initial_capital, currency)`: 포트폴리오 초기화
  - `get_portfolio()`: 잔고 + 보유 종목 수 + 총 평가액
  - `get_positions()`: 전체 포지션 목록 (현재 시세 enrichment)
  - `buy(symbol, quantity)`: 매수 실행
  - `sell(symbol, quantity)`: 매도 실행
  - `get_orders(limit)`: 최근 주문 내역
  - `get_pnl()`: 포트폴리오 전체 손익 요약
- **핵심 설계 결정:**
  - 시세 조회: `handlers/watchlist.py`의 `_quote_for()` 함수 재사용 (공통 모듈로 추출)
  - ULID로 주문 ID 생성 (시간순 정렬 보장, DDB SK에 최적)
  - 평균 단가 계산: 기존 보유 수량과 신규 매수의 가중 평균
  - 부분 매도: 실현 손익 = (매도가 - 평균 단가) x 매도 수량
  - 포트폴리오 미존재 시 매매 거부 + 초기화 안내 메시지
  - currency별 분리 관리 (cross-currency 합산은 Phase 3+)
- **Dependencies:** Task 1.1, 1.2
- **Risk:** Medium -- 시세 조회 실패 처리, PnL 계산 정확성

#### Task 2.2: 오케스트레이터 연동

- **Files:** `agents/orchestrator.py`, `prompts/orchestrator.md`
- **Changes:**
  - `_TOOLS` 리스트에 trading 도구 7개 import + 추가
  - 오케스트레이터 프롬프트 업데이트:
    - Phase 1 "매매 기능 없음" 문구 제거
    - Phase 2 매매 규칙 섹션 추가 ("가상 매매, 실제 돈 아님" 명시)
    - buy/sell 전 research로 시세 확인 권장 패턴
    - 에러 시 사용자 친화적 안내 (잔고 부족, 보유량 초과 등)
- **Dependencies:** Task 2.1
- **Risk:** Low

---

### Milestone 3: Portfolio UI

**Goal:** 프론트엔드에서 포트폴리오 확인 가능.

#### Task 3.1: TypeScript 타입

- **File:** `types.ts`
- **Types:** Position, Order, Portfolio, PnlSnapshot, Strategy
- **StreamEventType 추가:** portfolio_update, strategy_triggered
- **Dependencies:** 없음
- **Risk:** Low

#### Task 3.2: Portfolio 패널 컴포넌트

- **Files:** `components/portfolio/PortfolioPanel.tsx`, `PositionRow.tsx`, `OrderHistory.tsx`
- **Design:**
  - terminal 스타일 유지 (amber 텍스트, 검은 배경, JetBrains Mono)
  - 상단: 잔고 카드 (현금, 총 평가액, 전체 PnL)
  - 중간: 포지션 리스트 (종목, 수량, 평단가, 현재가, 손익률)
  - 하단: 최근 주문 내역 (접이식)
  - 손익 색상: 기존 `#39ff14` (이익), `#ff4444` (손실) 그대로 사용
- **Dependencies:** Task 3.1
- **Risk:** Low

#### Task 3.3: 레이아웃 조정 -- 중앙 패널 탭 전환

- **Files:** `App.tsx`, `TerminalFrame.tsx`
- **Changes:**
  - 중앙 패널(현재 watchlist 300px 고정)을 탭 구조로 변경
  - 탭: [Watchlist] [Portfolio] [Strategies]
  - 좌측(세션 220px)과 우측(채팅 1fr) 패널은 그대로 유지
- **Dependencies:** Task 3.2
- **Risk:** Medium -- 기존 watchlist 패널 통합 시 state 관리

#### Task 3.4: Portfolio 데이터 로딩

- **Files:** `api/agentcore.ts`, `App.tsx`
- **Changes:**
  - `fetchPortfolio()` 함수 추가 (fetchWatchlist 패턴 동일)
  - Portfolio 탭 활성화 시 데이터 로딩
  - 매매 관련 tool_call 완료 후 포트폴리오 자동 리프레시
- **Dependencies:** Task 3.3
- **Risk:** Low

---

### Milestone 4: PnL Tracking

**Goal:** 일별 포트폴리오 성과 기록 및 시각화.

#### Task 4.1: PnL 스냅샷 자동 생성

- **File:** `handlers/briefing.py`
- **Changes:**
  - 브리핑 생성 시 포트폴리오가 존재하면 `PNL#<yyyy-mm-dd>` 스냅샷 자동 저장
  - 스냅샷: date, total_value, cash, unrealized_pnl, realized_pnl, positions_count
  - 포트폴리오 미존재 시 skip (하위 호환)
- **Dependencies:** Task 2.1
- **Risk:** Low

#### Task 4.2: PnL 차트 컴포넌트

- **File:** `components/portfolio/PnlChart.tsx`
- **Design:**
  - 일별 PnL 추이 라인 차트
  - terminal 테마: amber 라인 (#fba91a), 검은 배경 (#0a0e0f)
  - 이익 구간 green, 손실 구간 red
- **Dependencies:** Task 4.1, 3.2
- **Risk:** Low

---

### Milestone 5: Strategy Agent

**Goal:** 조건 기반 전략 등록 + 주기적 모니터링.

#### Task 5.1: Strategy 도구

- **File:** `tools/strategy.py`
- **Tools (5개):**
  - `create_strategy(name, target_symbol, condition_type, threshold, action, quantity, description)`: 전략 등록
  - `list_strategies()`: 전체 전략 목록 + 상태
  - `remove_strategy(name)`: 전략 삭제
  - `toggle_strategy(name, enabled)`: 활성화/비활성화
  - `get_strategy_log(name, limit)`: 전략 실행 이력
- **condition_type:** price_above, price_below, change_pct_above, change_pct_below
- **action:** alert (알림 기록만), buy (가상 매수), sell (가상 매도)
- **Dependencies:** Task 1.1, 1.2
- **Risk:** Low

#### Task 5.2: 오케스트레이터에 Strategy 도구 추가

- **Files:** `agents/orchestrator.py`, `prompts/orchestrator.md`
- **Changes:**
  - `_TOOLS`에 strategy 도구 5개 추가
  - 프롬프트에 전략 사용 가이드 추가
  - 자연어 → 전략 파라미터 매핑 예시: "BTC가 10만 달러 넘으면 알려줘" → price_above, 100000, alert
- **Dependencies:** Task 5.1
- **Risk:** Low

#### Task 5.3: Strategy 모니터링 서브그래프

- **File:** `agents/strategy_graph.py`
- **LangGraph StateGraph:**
  - `load_strategies`: 활성화된 전략 목록 DDB에서 로드 (순수 Python)
  - `fetch_prices`: 전략 대상 종목 deduplicate 후 일괄 시세 조회 (순수 Python)
  - `evaluate`: 각 전략의 조건 충족 여부 판단 (순수 Python -- 비교 연산)
  - `execute`: 충족된 전략에 따라 action 실행 (alert → STRATLOG 기록, buy/sell → paper trade)
- **Graph 구조:** load_strategies → fetch_prices → evaluate → execute (순차)
- **Dependencies:** Task 2.1, 5.1
- **Risk:** Medium -- 시세 조회 실패 시 해당 전략 skip 처리

#### Task 5.4: Strategy Monitor Lambda + EventBridge

- **Files:** `handlers/strategy_monitor.py`, `main.py`, `serverless.yml`, `src/strategy-monitor-proxy.ts` (신규)
- **Changes:**
  - `handlers/strategy_monitor.py`: briefing 핸들러 패턴 복제. POST /strategy-monitor
  - `main.py`: `app.add_route("/strategy-monitor", ...)` 추가
  - `serverless.yml`: `strategyMonitorProxy` Lambda + EventBridge rule `cron(*/30 * * * ? *)` (매 30분)
  - `strategy-monitor-proxy.ts`: briefing-proxy.ts 복제, endpoint만 변경
- **Dependencies:** Task 5.3
- **Risk:** Medium -- cron 빈도 vs API rate limit 균형

#### Task 5.5: Strategy UI

- **File:** `components/strategy/StrategyPanel.tsx`
- **Design:**
  - 전략 목록: 이름, 대상 종목, 조건, 액션, 상태(활성/비활성), 마지막 트리거
  - 활성/비활성 토글 (채팅 통해 toggle_strategy 호출)
  - 전략 추가/삭제는 채팅으로 (자연어 → 에이전트가 도구 호출)
- **Dependencies:** Task 5.2, 3.3
- **Risk:** Low

---

### Milestone 6: Integration + Polish

**Goal:** Phase 1-2 기능 통합 마무리.

#### Task 6.1: SSE 이벤트 확장

- **Files:** `main.py`, `hooks/useAgentStream.ts`
- **Changes:**
  - buy/sell tool_result 후 portfolio_update 이벤트 자동 emit
  - frontend: portfolio_update 수신 시 포트폴리오 패널 리프레시
  - strategy_triggered 이벤트: 전략 트리거 발생 시 채팅에 알림 표시
- **Dependencies:** Task 2.1, 3.4
- **Risk:** Low

#### Task 6.2: 브리핑 포트폴리오 섹션

- **Files:** `handlers/briefing.py`, `prompts/briefing.md`
- **Changes:**
  - 브리핑 본문에 포트폴리오 보유 현황 + 일간 PnL 변동 요약 추가
  - 포트폴리오 미존재 시 기존 형식 유지 (하위 호환)
- **Dependencies:** Task 4.1
- **Risk:** Low

#### Task 6.3: Observability 확장

- **새 CloudWatch 메트릭:**
  - `PaperTradeCount` (dimensions: side, symbol)
  - `StrategyEvaluationCount` (dimensions: strategy_name, triggered)
  - `PortfolioValue` (daily)
- **structlog 필드 추가:** trade_id, strategy_name
- **Dependencies:** Task 2.1, 5.3
- **Risk:** Low

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| 시세 조회 실패 시 매매 불가 | Medium | 명확한 에러 메시지 + 재시도 안내. 시세 없으면 매매 거부 |
| 동시 매수/매도로 잔고 불일치 | Low | 싱글 유저 + AgentCore 직렬 실행. DDB conditional write로 추가 보호 가능 |
| Strategy monitor cron이 API rate limit 소모 | Medium | 전략 대상 종목 deduplicate 후 일괄 조회, cron 주기 조절 가능 |
| Cross-currency 포트폴리오 합산 부정확 | Low | Phase 2는 currency별 표시만, 합산은 Phase 3에서 FX 환산 추가 |
| 도구 수 증가 (14→26)로 오케스트레이터 혼란 | Medium | 프롬프트에 도구 선택 가이드 명확히, 도구 docstring 정밀 작성 |

---

## Security

- Phase 2는 Paper Trading (가상 매매)이므로 실제 금전 위험 없음
- Cognito MFA 업그레이드는 Phase 3 (HITL Trading)으로 연기
- 기존 Cognito Identity Pool (guest) + password gate 유지

---

## Dependencies (외부 라이브러리)

| 패키지 | 용도 | 신규 여부 |
|---|---|---|
| `ulid-py` 또는 `python-ulid` | 주문 ID 생성 | 신규 |
| `recharts` (frontend) | PnL 차트 | 신규 |

---

## Milestone Summary

| Milestone | 주요 산출물 | 예상 복잡도 |
|---|---|---|
| M1: Data Layer | schemas/trading.py, storage/trading.py | Low |
| M2: Trading Engine | tools/trading.py + orchestrator 연동 | Medium |
| M3: Portfolio UI | PortfolioPanel + 탭 레이아웃 | Medium |
| M4: PnL Tracking | PnL 스냅샷 + 차트 | Low |
| M5: Strategy Agent | strategy 도구 + 서브그래프 + cron | High |
| M6: Integration | SSE 확장 + 브리핑 통합 + observability | Low |

M1 → M2 순차 필수. M3/M4/M5는 M2 완료 후 병렬 가능.

---

## Success Criteria

- [ ] "포트폴리오 만들어줘 1만 달러로" → 가상 포트폴리오 생성됨
- [ ] "BTC 0.1개 사줘" → 시세 조회 → 잔고 차감 → 포지션 생성 → 주문 기록
- [ ] "BTC 전량 팔아" → 매도 → 실현 손익 계산 → 포지션 삭제
- [ ] "포트폴리오 보여줘" → 잔고 + 보유 종목 + 평가 손익 표시
- [ ] "주문 내역 보여줘" → 최근 거래 내역 반환
- [ ] 포트폴리오 패널에서 보유 종목, 평가액, 손익 시각적 확인
- [ ] PnL 차트에 일별 추이 표시
- [ ] "BTC가 $100K 넘으면 알려줘" → 전략 등록 성공
- [ ] 전략 패널에서 등록된 전략 목록/상태 확인
- [ ] 브리핑에 포트폴리오 보유 현황 요약 포함
- [ ] 기존 Phase 1 기능 정상 동작 유지
