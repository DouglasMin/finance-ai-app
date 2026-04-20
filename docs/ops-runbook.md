# Ops Runbook — financeaiapp

**Last Updated:** 2026-04-21
**Scope:** 운영 중 이메일/(향후) Slack 알림 수신 시 대응 절차

---

## 알림 수신 시 첫 3단계

1. **메시지 원문 읽기** — AlarmName + AlarmDescription으로 어떤 리소스의 어떤 메트릭인지 확인
2. **CloudWatch 콘솔 진입** — 메시지에 포함된 링크 또는 `AlarmName`으로 검색
3. **Logs Insights** → 해당 Lambda 로그 그룹에서 최근 15분 에러 확인

---

## Alarm별 대응 가이드

### `financeaiapp-briefing-lambda-errors`
**의미:** Briefing Lambda 15분 내 1건 이상 실패.

**확인:**
```bash
aws logs tail /aws/lambda/financeaiapp-briefing-proxy --since 30m --follow
```

**흔한 원인:**
- AgentCore Runtime 다운/타임아웃 → AWS 콘솔에서 AgentCore 상태 확인
- IAM 권한 누락 (과거 실제 사례: `runtime-endpoint/DEFAULT` 서브리소스 빠짐)
- SSM 파라미터 만료/삭제 (`/financeaiapp/agentcore-runtime-arn`)

**복구:**
- 일시적 장애면 다음 cron (AM/PM)에 자동 재시도
- 재발 시 briefing DLQ 확인 + 수동 재실행
  ```bash
  aws lambda invoke --function-name financeaiapp-briefing-proxy \
    --payload '{"time_of_day":"AM"}' /tmp/out.json
  ```

---

### `financeaiapp-briefing-dlq-depth`
**의미:** Briefing DLQ에 메시지 1건 이상 존재 (비동기 3회 재시도 모두 실패한 invocation).

**확인:**
```bash
aws sqs receive-message --queue-url https://sqs.ap-northeast-2.amazonaws.com/612529367436/financeaiapp-briefing-dlq \
  --max-number-of-messages 10 --visibility-timeout 30 \
  --output json | jq '.Messages[].Body | fromjson'
```

**대응:**
- `responsePayload.errorMessage` 읽고 근본 원인 파악
- 원인 수정 후 DLQ purge:
  ```bash
  aws sqs purge-queue --queue-url <dlq-url>
  ```
- 필요 시 `requestPayload`로 수동 재실행

---

### `financeaiapp-briefing-lambda-duration`
**의미:** Briefing Lambda p95 duration > 100s (timeout 120s 대비 여유).

**확인:**
- AgentCore Runtime 응답 지연이 원인일 가능성 높음
- Frankfurter/OKX/Alpha Vantage 외부 API slow down 체크

**대응:**
- 반복되면 Lambda timeout 180s로 상향 또는 메모리 512MB로 증가 (둘 다 `serverless.yml`)
- 외부 API 문제면 일시적이라 모니터링만

---

### `financeaiapp-briefing-lambda-throttles`
**의미:** Briefing Lambda 동시 실행 한도 초과.

**확인:** 브리핑은 AM/PM 각 1회 cron이라 발생 가능성 매우 낮음. 발생 시 코드 무한루프 의심.

**대응:**
- CloudWatch → Lambda → Configuration → Concurrency → Reserved 설정 점검
- 계정 기본 unreserved 한도(1000) 문제면 AWS 서포트 문의

---

### `financeaiapp-strategy-monitor-*` (4종)
**의미:** Strategy Monitor Lambda 관련 (errors / dlq-depth / duration / throttles). 동일한 대응 패턴 적용.

**특이점:** 30분마다 실행되므로 errors는 `financeaiapp-strategy-monitor` 로그에서 최근 2시간 정도 확인 권장.

```bash
aws logs tail /aws/lambda/financeaiapp-strategy-monitor --since 2h --follow
```

---

### `financeaiapp-daily-cost`
**의미:** 계정 일일 추정 비용 $5 초과.

**확인:**
- Cost Explorer → Group by: Service → 어느 서비스가 폭주했는지
- Cost Explorer → Group by: Tag → Project → `financeaiapp`인지 다른 프로젝트인지

**흔한 원인:**
- AgentCore Runtime 세션 누수 (사용 후 세션 종료 안 됨)
- Bedrock 모델 호출 과다 (Claude Sonnet 토큰 사용량)
- DDB on-demand read/write spike

**대응:**
- AgentCore Runtime에 비정상 장기 세션 있는지 콘솔 확인
- 필요 시 AgentCore Runtime 재시작
- Phase 3 진입 후엔 강제 중단 스위치 필요 (Policy Engine)

---

## DLQ 메시지 재처리 일반 절차

```bash
# 1. DLQ에서 메시지 하나 받기
MSG=$(aws sqs receive-message --queue-url <dlq-url> --max-number-of-messages 1 \
  --visibility-timeout 30 --output json)

# 2. requestPayload 추출
PAYLOAD=$(echo $MSG | jq -r '.Messages[0].Body | fromjson | .requestPayload')

# 3. 원본 Lambda 수동 호출
aws lambda invoke --function-name <fn-name> --payload "$PAYLOAD" /tmp/out.json
cat /tmp/out.json

# 4. 성공하면 메시지 삭제 (ReceiptHandle 필요)
RH=$(echo $MSG | jq -r '.Messages[0].ReceiptHandle')
aws sqs delete-message --queue-url <dlq-url> --receipt-handle "$RH"
```

---

## Escalation

- **15분 내 미해결 + 중요 이슈:** AgentCore 콘솔/Bedrock 서비스 상태 페이지 확인 → AWS 서포트 케이스 (Business 이상)
- **데이터 손상 의심 (DDB 포트폴리오/포지션):** 즉시 애플리케이션 정지 (Cognito 비활성화) → DDB PITR 복원 고려
- **Phase 3+에서 실매매 관련 이슈:** 우선 Trading Bot의 승인 워크플로우 차단 → 수동으로 강제 중단 스위치 토글

---

## 참고 리소스

- 인프라 구조: [plan-ops-hardening.md](./plan-ops-hardening.md)
- 태깅 규약: [aws-tagging-strategy.md](./aws-tagging-strategy.md)
- AgentCore Runtime ARN: SSM `/financeaiapp/agentcore-runtime-arn`
- DynamoDB 테이블: `financial-bot`
- CloudFront: `ERKSO9H1ZH66F`
- SNS 토픽: `arn:aws:sns:ap-northeast-2:612529367436:financeaiapp-alerts`
- 이메일 수신자: `dongik.dev73@gmail.com` (confirmed)
