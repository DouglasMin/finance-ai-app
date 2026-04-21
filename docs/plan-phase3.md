# Phase 3 Plan (Stub) — HITL Trading + 멀티유저 + LTM 활성화

**Status:** Draft stub (Phase 2 완료, Phase 3 실제 착수 전)
**Last updated:** 2026-04-21
**Prerequisite:** Ops Hardening + Slack Interactive skeleton(M6) 완료

---

## 목적

Phase 2(Paper Trading)에서 자동 체결되던 매매를 **사용자 승인 기반 실매매**로 전환. 동시에 메모리/멀티유저 기반을 함께 정비해서 운영 준비 완료.

---

## 핵심 구성 요소 (Big Picture)

| 축 | 내용 | 비고 |
|---|---|---|
| 실매매 | 브로커 API 연동 (KIS/Alpaca 등 후보) | 종목 classification별로 라우팅 |
| HITL 승인 | Slack Interactive 버튼 → LangGraph `interrupt()` → resume | M6에 스켈레톤 완료 |
| 멀티유저 | `actor_id` 하드코딩 제거, Cognito User Pool 승격 | MFA 포함 |
| 메모리 (LTM) | AgentCore LTM strategies 실제 활성화 + 조회 파이프라인 | 아래 별도 섹션 참조 |
| 거래 한도 | 일일 손실 한도, 주문 size 상한, 긴급 중단 스위치 | Policy Engine 전초 |
| 감사 | 모든 주문 + 승인 이력 DDB 적재, Slack `chat.update`로 상태 갱신 | |

---

## 🔴 반드시 같이 처리할 선행 과제 — LTM 활성화

### 현재 상태 (2026-04-21 확인)

- 메모리 리소스 `FinancialAgentMemory-zkfgNCGggq` 에 LTM strategies **2개 ACTIVE**
  - `SessionSummarizer` (SUMMARIZATION)
  - `UserPreferenceExtractor` (USER_PREFERENCE)
- **실제로는 놀고 있음** — 이벤트를 받지 못해 records 생성 안 됨

### 원인 (공식 문서 확인 결과)

AgentCore Memory LTM은 **체크포인터(`AgentCoreMemorySaver`)만으로 트리거되지 않음.**
`AgentCoreMemoryStore` + `pre_model_hook` 조합이 공식 권장 패턴.

출처: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-integrate-lang.html

### Phase 3에서 해야 할 일

1. **Store 추가:** `orchestrator.py`에 `AgentCoreMemoryStore` 초기화
2. **`pre_model_hook` 도입:**
   ```python
   def pre_model_hook(state, config, *, store):
       actor_id = config["configurable"]["actor_id"]
       thread_id = config["configurable"]["thread_id"]
       namespace = (actor_id, thread_id)
       for msg in reversed(state.get("messages", [])):
           if isinstance(msg, HumanMessage):
               store.put(namespace, str(uuid.uuid4()), {"message": msg})
               break
       return {"llm_input_messages": state["messages"]}
   ```
3. **`create_agent`에 `store` + `pre_model_hook` 연결**
4. **LTM 조회 → 프롬프트 주입:** `pre_model_hook` 내부에서
   ```python
   preferences = store.search(("preferences", actor_id), query=msg.content, limit=5)
   # messages에 context로 추가
   ```
5. **LangGraph 자체의 trim/summary 로직과 AgentCore SUMMARIZATION 이중 실행 방지 검토**

### 왜 Phase 3와 엮는가

- **`actor_id` 멀티유저 전환과 직결** — LTM namespace가 `actor_id` 기반
- **HITL 승인 UX 맞춤화에 활용 가능** — 과거 승인/거부 패턴 → 자동 승인 후보 판단 근거
- 지금 따로 고치면 멀티유저 전환 시 두 번 건드려야 함

### 주의 사항

- LTM 추출은 **비동기** — 쓰기 직후 즉시 조회 불가 (몇 초~수 초 지연)
- SUMMARIZATION namespace는 `{actorId}/{sessionId}` 기반 → 세션 바뀌면 새 요약 생성
- 이전 세션 요약 연속성이 필요하면 `pre_model_hook`에서 명시적으로 prev 요약 검색해 주입

---

## 멀티유저 전환 체크리스트

- [ ] `USER_PK = "USER#me"` 하드코딩 제거
- [ ] Cognito Identity Pool (게스트) → User Pool (이메일/비번) 승격
- [ ] MFA 설정 (TOTP 권장)
- [ ] `actor_id`를 Cognito `sub`에서 주입
- [ ] DDB 모든 PK를 `USER#{sub}` 형태로 동적 변환
- [ ] 기존 `USER#me` 데이터 마이그레이션 스크립트 or 버리고 초기화

---

## HITL 승인 플로우 설계 (outline)

1. Strategy 발동 감지 → AgentCore가 실매매 의도 생성
2. DDB `PENDING_APPROVAL#{orderId}` 레코드 작성 (TTL 15분)
3. AgentCore에서 LangGraph `interrupt()` 호출 → 실행 일시중지
4. Slack에 승인 요청 메시지 포스팅 (Block Kit + buttons)
5. 유저가 승인/거부 버튼 클릭
6. Slack → slack-interactive Lambda (이미 skeleton 완료)
7. Lambda가 signing 검증 후 `Command(resume="approve"|"reject")` 호출
8. AgentCore가 `interrupt()` 재개 → 승인이면 실제 브로커 API, 거부면 주문 폐기
9. `chat.update`로 Slack 메시지 "✅ 승인됨 @ 가격" or "❌ 거부됨"

타임아웃 정책:
- 15분 무응답 → 자동 거부 + Slack 알림

---

## 운영 안전장치

- **일일 손실 한도** (`DAILY_LOSS_LIMIT` env var): 초과 시 모든 매매 중단 + Slack 경고
- **단일 주문 size 상한**: 포트폴리오 대비 10% 이상 주문 시 무조건 승인 요청 (alert 전략도 알림만)
- **긴급 중단 스위치**: SSM 파라미터 `/financeaiapp/trading-enabled = false` → 모든 체결 차단

---

## Phase 3 진입 전 재검토할 것

- Slack Bot이 여전히 1개 워크스페이스 전용이어서 멀티유저 시 구조 변경 필요한지
- Phase 2에서 쌓인 strategy 패턴 통계를 보고 LTM 활용 방향 결정
- AgentCore Memory event 보관 기간 / 비용 확인 (현재 `Event Expiry: None days`)

---

## 연결된 기존 문서

- `plan-ops-hardening.md` — M6 Slack Interactive skeleton (Phase 3 배선)
- `sns-event-schema.md` — `strategy_approval_requested` 예약 타입
- `aws-tagging-strategy.md` — 멀티유저 확장 시 리소스 태그 전략
