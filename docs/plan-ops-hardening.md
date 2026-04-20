# Ops Hardening + Dual Slack Bot Plan

**Date:** 2026-04-18
**Status:** Draft
**Scope:** 운영 안정화 + 두 개의 독립 Slack Bot (Infra Monitor + Trading Agent)
**Prerequisite:** Phase 2 완료
**Next:** Phase 3 (HITL Trading — Trading Bot의 승인 로직 실구현)

---

## Overview

**두 개의 완전히 분리된 Slack App**을 만든다:

### 🛠️ Bot A: `aws-infra-monitor-bot`
- **책임:** AWS 인프라 장애 알림
- **대상:** Lambda 에러, DLQ 메시지, duration 초과, 비용 초과
- **방향:** 단방향 (Lambda → Slack)
- **재사용성:** finance-ai-app 외 다른 프로젝트에서도 같은 봇 재활용 가능
- **채널:** `#infra-alerts` (또는 프로젝트별 `#finance-infra` 등)

### 💼 Bot B: `finance-trading-bot`
- **책임:** 매수/매도 최종 승인 (Phase 3 핵심)
- **방향:** 양방향 (Bot이 요청 포스팅 → 유저가 버튼 클릭 → Lambda 처리)
- **도메인:** finance-ai-app 전용
- **채널:** `#finance-trading`

**왜 나누나:**
- Bot A는 인프라 관점(에러/알람), Bot B는 도메인 관점(매매) — 권한/스코프/채널이 완전히 다름
- Bot A는 범용 — 나중에 image-editor-swarm, agentcore-service 등 다른 프로젝트에서 같은 봇 초대만 하면 됨
- Bot B는 Phase 3에서 Interactive(버튼/slash) 스코프 필요 — A는 단순 포스팅만

**웹사이트 UI 변경 없음.** 브리핑/포트폴리오/전략 알림은 기존 웹 전용 유지.

---

## Scope

### 포함
- **M0 Multi-Project Tagging 선적용** (리소스 적을 때 싹 정리)
- **인프라 측:** Strategy Monitor DLQ + alarms, 양쪽 Lambda duration/throttle alarm
- **Bot A (완성):** `aws-infra-monitor-bot` Slack App + Poster Lambda + SNS 구독
- **Bot B (skeleton):** `finance-trading-bot` Slack App + Interactive endpoint + signing 검증
- SSM 파라미터 분리 관리 (봇별 토큰/채널)

### 제외
- **브리핑/포트폴리오/전략 알림 Slack 전송** (웹 전용 유지)
- **Bot B 실제 승인 로직** (Phase 3에서 LangGraph interrupt 연동)
- Bot A를 다른 프로젝트에 실제 통합 (이번엔 finance-ai-app만)
- SMS / Pushover / AWS Chatbot 네이티브

---

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                      Slack Workspace                          │
│                                                               │
│   🛠️ #infra-alerts          💼 #finance-trading               │
│     (Bot A 초대)              (Bot B 초대)                    │
└────────▲──────────────────────────▲───────────────────────────┘
         │                          │
         │ chat.postMessage         │ chat.postMessage
         │                          │ + Interactive callback (Phase 3)
         │                          │
   ┌─────┴──────┐            ┌──────┴──────────────┐
   │  Infra     │            │  Trading Poster +   │
   │  Poster    │            │  Interactive        │
   │  Lambda    │            │  Lambda(s)          │
   └─────▲──────┘            └──────▲──────────────┘
         │                          │
    ┌────┴─────┐                    │ Phase 3: AgentCore
    │   SNS    │                    │ (orchestrator interrupt)
    │(Alerts)  │                    │
    └────▲─────┘                    │
         │
   CloudWatch Alarms
    (Lambda errors, DLQ, duration, throttles, billing)

SSM 분리:
  /financeaiapp/slack-infra-bot-token      (Bot A)
  /financeaiapp/slack-infra-channel
  /financeaiapp/slack-trading-bot-token    (Bot B)
  /financeaiapp/slack-trading-channel
  /financeaiapp/slack-trading-signing-secret
```

---

## Milestones

### M0 — Multi-Project Tagging Foundation (선행, 필수)

**왜 지금:** 현재 계정 리소스가 적고 전부 IaC(Serverless, CDK) 관리 중이라 한 번에 태깅 가능. 앞으로 프로젝트 늘어나기 전에 규약 고정.

**현재 상태:**
- 프로젝트 태그(`Project`, `Owner`, `ManagedBy`) 전무
- `STAGE=prod` (Serverless 자동 생성)만 존재
- 고아 리소스: `image-editor-agent-bucket` (태그 0개)

**태그 스키마 (공통 규약):**
```yaml
Project:     <project-name>       # financeaiapp, imageeditor, agentcore, ...
Owner:       dongik
ManagedBy:   serverless | cdk | terraform | manual
Environment: prod | dev | staging
CostCenter:  personal | client-<name>
```

**M0.1 — Serverless stack tags**

`financeaiapp-infra/serverless.yml` `provider:` 아래 추가:
```yaml
stackTags:
  Project: financeaiapp
  Owner: dongik
  ManagedBy: serverless
  Environment: ${self:provider.stage}
  CostCenter: personal
```
→ `serverless deploy` → 스택 내 모든 리소스 자동 전파.

**M0.2 — CDK stack tags**

`FinanceaiappStorage`, `FinanceaiappOidc` 앱 진입점에:
```typescript
import { Tags } from 'aws-cdk-lib';
Tags.of(app).add('Project', 'financeaiapp');
Tags.of(app).add('Owner', 'dongik');
Tags.of(app).add('ManagedBy', 'cdk');
Tags.of(app).add('Environment', 'prod');
Tags.of(app).add('CostCenter', 'personal');
```
→ `cdk deploy --all` → 전체 리소스 자동 전파.

**M0.3 — 고아 리소스 정리**
- `image-editor-agent-bucket`: 현재 쓰는지 확인 → 안 쓰면 삭제, 쓰면 태그만 수동 부착
- `bedrock-agentcore-*`, `cdk-hnb659fds-*`: AWS/CDK 관리 리소스, 건드리지 않음

**M0.4 — Cost Allocation Tags 활성화 (수동, 한 번만)**

AWS Billing 콘솔 → **Cost allocation tags** → 다음 4개 **Activate**:
- `Project`
- `Owner`
- `Environment`
- `CostCenter`

활성화 후 24~48시간 지나야 Cost Explorer 필터 가능.

**M0.5 — Tagging Strategy 문서**

**신규 파일:** `finance-ai-app/docs/aws-tagging-strategy.md` (또는 별도 공용 레포에 두고 심볼릭 링크)
- 태그 스키마 정의
- IaC별 적용 예시 (Serverless, CDK, Terraform, 수동)
- 네이밍 규약 (`<project>-<component>-<purpose>`)
- SNS 토픽 분리 원칙 (프로젝트별 독립 토픽, 봇이 구독만 추가)
- 다음 신규 프로젝트 시작 시 체크리스트

**검증:**
```bash
AWS_PROFILE=developer-dongik aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=Project,Values=financeaiapp \
  --region ap-northeast-2 --query 'ResourceTagMappingList[].ResourceARN'
```
→ 모든 financeaiapp 리소스 ARN 반환 확인.

**예상 소요:** 30–40분.

---

### M1 — Strategy Monitor 안전망

**파일:** `financeaiapp-infra/serverless.yml`

- `StrategyMonitorDLQ` (SQS, 14일 보존)
- `StrategyMonitorEventInvokeConfig` (Lambda → DLQ 연결)
- IAM: `sqs:SendMessage` DLQ ARN 추가
- `StrategyMonitorLambdaErrorsAlarm` (15분 내 ≥1건)
- `StrategyMonitorDLQDepthAlarm` (>0)

---

### M2 — 공통 Lambda Alarm

양쪽 Lambda (briefing, strategyMonitor, 추후 infra/trading poster):

- **Duration alarm** — p95 > 100,000ms (timeout 120s 대비 여유)
- **Throttles alarm** — 5분 내 >0건

---

### M3 — Slack App A: `aws-infra-monitor-bot` (수동)

1. https://api.slack.com/apps → Create New App → From scratch
2. App 이름: **`aws-infra-monitor-bot`**
3. **OAuth & Permissions** → Bot Token Scopes:
   - `chat:write`
4. Install to Workspace → Bot Token 복사
5. Slack 채널 생성: `#infra-alerts`
6. 봇 초대: `/invite @aws-infra-monitor-bot`
7. 채널 ID 복사

**SSM:**
```bash
export AWS_PROFILE=developer-dongik

aws ssm put-parameter --name /financeaiapp/slack-infra-bot-token \
  --value "xoxb-..." --type SecureString

aws ssm put-parameter --name /financeaiapp/slack-infra-channel \
  --value "C0XXXXXXX" --type String
```

**재사용성 노트:** 이 봇은 finance-ai-app 전용이 아니므로, 향후 다른 프로젝트 도입 시 해당 프로젝트의 SNS 토픽에 봇의 Poster Lambda를 추가 구독시키기만 하면 됨.

---

### M4 — Infra Poster Lambda

**신규 파일:** `financeaiapp-infra/src/slack-infra-poster.ts`

**책임:**
- SNS `AlertTopic` 구독
- CloudWatch alarm payload 파싱 → Slack Block Kit 변환
- `#infra-alerts`에 포스팅

**메시지 포맷:**
```
🚨 *[financeaiapp]* financeaiapp-strategy-monitor-errors
> Strategy Monitor Lambda 에러 3건 in 15m
> State: ALARM
> [CloudWatch 로그 보기](https://...)
```

**serverless.yml:**
```yaml
slackInfraPoster:
  handler: src/slack-infra-poster.handler
  timeout: 30
  memorySize: 256
  environment:
    SLACK_TOKEN_PARAM: /financeaiapp/slack-infra-bot-token
    SLACK_CHANNEL_PARAM: /financeaiapp/slack-infra-channel
    PROJECT_TAG: "financeaiapp"
  events:
    - sns:
        arn: !Ref AlertTopic
```

**검증:** 의도적 알람 → `#infra-alerts` 수신.

---

### M5 — Slack App B: `finance-trading-bot` (수동)

1. Slack → Create New App → `finance-trading-bot`
2. **OAuth & Permissions** → Bot Token Scopes:
   - `chat:write`
   - `chat:write.public` (선택)
3. **Interactivity & Shortcuts** → Enable (Request URL은 M6에서 채움)
4. Install to Workspace → Bot Token 복사
5. **Basic Information** → Signing Secret 복사
6. Slack 채널 생성: `#finance-trading`
7. 봇 초대: `/invite @finance-trading-bot`

**SSM:**
```bash
aws ssm put-parameter --name /financeaiapp/slack-trading-bot-token \
  --value "xoxb-..." --type SecureString

aws ssm put-parameter --name /financeaiapp/slack-trading-channel \
  --value "C0YYYYYYY" --type String

aws ssm put-parameter --name /financeaiapp/slack-trading-signing-secret \
  --value "..." --type SecureString
```

---

### M6 — Trading Interactive Skeleton (Phase 3 준비)

**신규 파일:** `financeaiapp-infra/src/slack-trading-interactive.ts`

**지금 단계 (skeleton):**
- Lambda Function URL (AuthType: NONE — Slack signing으로 검증)
- Slack signing secret + timestamp 검증 (5분 윈도우)
- 모든 버튼 payload에 `"⏳ Phase 3에서 구현 예정"` 임시 응답
- 검증 실패 시 401 반환

**Slack App 설정:**
- Interactivity Request URL = Function URL

**Phase 3에서 얹을 것:**
- `approve` / `reject` 버튼 라우팅
- DDB `PENDING_APPROVAL#<orderId>` 조회/업데이트
- AgentCore orchestrator `Command(resume=...)` 호출
- `chat.update`으로 "✅ 승인됨 (체결: BTC 0.05 @$68,421)" 같이 메시지 업데이트

**검증:** Slack에서 Interactive payload 직접 전송 (curl 또는 Slack debug) → signing 검증 통과 + placeholder 응답 확인.

---

### M7 — SNS 이메일 구독 점검 + Runbook

- `aws sns list-subscriptions-by-topic` → `PendingConfirmation` 확인
- Pending이면 이메일에서 Confirm
- `docs/ops-runbook.md` 초안:
  - Slack 알림 수신 → CloudWatch → DLQ → 재실행 절차
  - Bot Token rotation 절차 (A, B 각각)
  - Slack 포스팅 실패 시 원인 (채널 초대 누락, 토큰 만료)

---

## Deployment

```bash
cd financeaiapp-infra
npm install         # @slack/web-api 추가
serverless deploy
```

배포 전 Slack 수동 설정 + SSM 저장 (M3, M5) 선행 필요.

---

## Risks

| Risk | Mitigation |
|------|-----------|
| 두 봇 토큰 혼동 | SSM 파라미터 이름으로 명확 구분 (`slack-infra-*`, `slack-trading-*`) |
| Bot Token 유출 | SecureString + 최소 권한 |
| Interactive endpoint 악용 | Slack signing secret + 5분 timestamp 검증 필수 |
| Slack 포스팅 실패 = 알림 유실 | 이메일 구독 병행 유지 (이중 채널) |
| Rate limit | chat.postMessage Tier 1 = 1/sec. 장애 알림/승인 빈도 낮음 |
| Bot A를 다른 프로젝트에서 쓸 때 충돌 | `PROJECT_TAG` 환경변수로 메시지에 프로젝트명 명시 |

---

## Checklist

- [ ] M0.1: Serverless stackTags 추가 + `serverless deploy`
- [ ] M0.2: CDK `Tags.of(app).add(...)` 양쪽 stack + `cdk deploy`
- [ ] M0.3: 고아 S3 `image-editor-agent-bucket` 처리 (삭제/태그)
- [ ] M0.4: Billing 콘솔에서 Cost allocation tags 4개 Activate (수동)
- [ ] M0.5: `docs/aws-tagging-strategy.md` 작성
- [ ] M1: StrategyMonitor DLQ + Errors + DLQ depth alarm
- [ ] M2: Duration/Throttles alarm (양쪽 Lambda)
- [ ] M3: Slack App A (`aws-infra-monitor-bot`) 생성 + Bot 초대 + SSM (수동)
- [ ] M4: slack-infra-poster Lambda + SNS 구독
- [ ] M5: Slack App B (`finance-trading-bot`) 생성 + Bot 초대 + SSM (수동)
- [ ] M6: slack-trading-interactive skeleton + Function URL + signing 검증
- [ ] M7: SNS 구독 확인 + runbook 초안
- [ ] 통합 테스트: 의도적 에러 → `#infra-alerts` / Slack Interactive curl → `#finance-trading` 동작 검증
- [ ] 메모리 업데이트 (SSM 파라미터명/채널명)

---

## Timeline (대략)

- M0: 30–40분 (태깅 기반 선구축)
- M1 + M2: 30분
- M3 + M5: 25분 (Slack 수동 두 개)
- M4: 1–1.5시간 (Block Kit 포맷 포함)
- M6: 1시간 (skeleton + signing 검증)
- M7: 30분
- 통합 테스트: 30분

**총 4.5–5시간.**

---

## Phase 3 연결점

이번 작업 후 Phase 3에서 할 것:

1. `slack-trading-interactive.ts`에 실제 버튼 핸들러 작성
2. AgentCore orchestrator에 `interrupt` 노드 추가 (실매매 전 대기)
3. DDB `PENDING_APPROVAL#<orderId>` 레코드 생성 + TTL
4. 매매 요청 시 Trading Bot이 `#finance-trading`에 포스팅:
   ```
   💼 *매수 승인 요청*
   BTC 0.05개 @$68,421 (예상 체결가)
   보유 현금: $9,300 → $5,879 예상
   [ 승인 ] [ 거부 ]
   ```
5. 버튼 클릭 → Function URL → signing 검증 → `Command(resume=...)` → 체결

Slack 인프라는 이번에 완성, 승인 로직만 Phase 3에서 얹기.

---

## Future

- Bot A를 다른 프로젝트(image-editor, agentcore 등)에도 도입
- 슬래시 커맨드 `/finance status`, `/finance positions` (Bot B 확장, 조회용)
- AWS Chatbot으로 Bot A 대체 검토 (네이티브 통합 vs 커스텀 유연성 트레이드오프)
- 멀티 워크스페이스 (Phase 3+)
