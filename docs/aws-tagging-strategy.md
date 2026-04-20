# AWS Tagging Strategy — 공용 규약

**Date:** 2026-04-18
**Status:** Active
**Scope:** `developer-dongik` 프로파일 계정(612529367436)에 배포되는 모든 프로젝트
**Goal:** 프로젝트 수 증가에 대비한 비용/권한/운영 분리 기반 마련

---

## 적용 원칙

1. **모든 리소스는 IaC로 태깅한다.** 수동 태깅은 CDK 소스 소실 등 예외적인 경우에만.
2. **신규 프로젝트 시작 시 이 문서의 체크리스트를 먼저 실행한다.**
3. **태그 값은 소문자 lowercase + kebab-case 통일.** 단 태그 키는 PascalCase (`Project`, `Owner`).
4. **Cost Allocation Tags 활성화는 첫 프로젝트 1회만.** 이후 프로젝트는 같은 키를 재사용하므로 추가 활성화 불필요.

---

## Tag Schema (5 필수 태그)

```yaml
Project:      <project-slug>        # financeaiapp, imageeditor, agentcore, ...
Owner:        dongik                # 계정 소유자. 팀 확장 시 개인 식별자
ManagedBy:    serverless | cdk | terraform | manual
Environment:  prod | dev | staging
CostCenter:   personal | client-<name>
```

**왜 이 5개:**
- `Project` → Cost Explorer에서 프로젝트별 비용 필터
- `Owner` → 다계정/팀 확장 시 책임자 식별
- `ManagedBy` → 리소스 수정 시 올바른 IaC 도구 선택 단서
- `Environment` → 환경별 정책 적용 (dev는 auto-stop, prod는 알람 강화 등)
- `CostCenter` → 개인 프로젝트 vs 클라이언트 작업 분리

**선택 태그 (프로젝트별 추가 가능):**
- `Component` — 같은 프로젝트 내 서브시스템 구분 (예: `frontend`, `agent`, `infra`)
- `CreatedBy` — CI/CD 파이프라인 ID
- `Version` — 릴리스 버전 태그

---

## Naming Convention

```
<project>-<component>-<purpose>
```

**예시:**
- `financeaiapp-briefing-proxy` (Lambda)
- `financeaiapp-briefing-dlq` (SQS)
- `financeaiapp-alerts` (SNS)
- `imageeditor-swarm-orchestrator` (Lambda)

**원칙:**
- **프로젝트명이 리소스 이름 앞에 반드시 붙는다.** CloudWatch 알람 이름이 `strategy-monitor-errors`만 되면 어느 프로젝트 알람인지 불명확. `financeaiapp-strategy-monitor-errors`는 명확.
- **kebab-case** 통일 (AWS 콘솔 UI 일관성).
- **리전/환경은 이름에 넣지 않는다** — 태그로 구분 (중복 방지).

---

## IaC별 적용 방법

### Serverless Framework

`serverless.yml` `provider:` 아래 추가:

```yaml
provider:
  name: aws
  region: ap-northeast-2
  stackTags:
    Project: <project-slug>
    Owner: dongik
    ManagedBy: serverless
    Environment: ${self:provider.stage}
    CostCenter: personal
```

`stackTags`는 CloudFormation 스택 레벨 태그로 적용되며, **태그 전파를 지원하는 모든 하위 리소스(Lambda, SNS, SQS, S3, CloudFront, DynamoDB, Cognito 등)에 자동 상속**된다.

### AWS CDK

앱 진입점(`bin/*.ts` 또는 `app.py`)에서:

```typescript
import { App, Tags } from 'aws-cdk-lib';

const app = new App();
Tags.of(app).add('Project', '<project-slug>');
Tags.of(app).add('Owner', 'dongik');
Tags.of(app).add('ManagedBy', 'cdk');
Tags.of(app).add('Environment', 'prod');
Tags.of(app).add('CostCenter', 'personal');
```

앱 전체에 태그가 전파되므로 스택/Construct별 반복 불필요.

### Terraform

`provider "aws"` 블록에 default_tags:

```hcl
provider "aws" {
  region = "ap-northeast-2"
  default_tags {
    tags = {
      Project     = "<project-slug>"
      Owner       = "dongik"
      ManagedBy   = "terraform"
      Environment = "prod"
      CostCenter  = "personal"
    }
  }
}
```

### 수동 태깅 (IaC 불가 시)

**Resource Groups Tagging API** (대부분의 서비스 지원):
```bash
AWS_PROFILE=developer-dongik aws resourcegroupstaggingapi tag-resources \
  --region ap-northeast-2 \
  --resource-arn-list <ARN1> <ARN2> \
  --tags Project=<slug>,Owner=dongik,ManagedBy=manual,Environment=prod,CostCenter=personal
```

**IAM 리소스는 서비스별 API 사용** (Resource Groups API 미지원):
```bash
aws iam tag-role --role-name <name> --tags Key=Project,Value=<slug> ...
aws iam tag-policy --policy-arn <arn> --tags Key=Project,Value=<slug> ...
aws iam tag-user --user-name <name> --tags Key=Project,Value=<slug> ...
aws iam tag-open-id-connect-provider --open-id-connect-provider-arn <arn> --tags Key=Project,Value=<slug> ...
```

---

## SNS Topic 분리 원칙 (인프라 모니터링 봇 대비)

**프로젝트별 독립 SNS 토픽**을 유지한다:
- `financeaiapp-alerts`
- `imageeditor-alerts`
- `agentcore-alerts`

**이유:**
- 프로젝트 폐기 시 토픽만 삭제하면 됨 (필터 수정 불필요)
- IAM 권한을 프로젝트 SNS에 한정 가능
- 한 프로젝트 알람 폭주가 다른 프로젝트에 영향 주지 않음

**공용 Slack 인프라 봇(`aws-infra-monitor-bot`)은 각 토픽에 구독만 추가하는 방식으로 확장.** 메시지 라우팅은 Lambda에서 `TopicArn` 파싱으로 프로젝트 식별 → Slack 메시지에 `[project]` prefix 자동 부착.

자세한 내용은 `plan-ops-hardening.md` 참고.

---

## Cost Allocation Tags 활성화 (계정당 1회)

**절차:**
1. https://us-east-1.console.aws.amazon.com/billing/home#/tags 접속 (Billing은 반드시 `us-east-1`)
2. **User-Defined Cost Allocation Tags** 탭 선택
3. 5개 태그 키 체크: `Project`, `Owner`, `ManagedBy`, `Environment`, `CostCenter`
4. **Activate** 클릭

**타임라인:**
- 태그 적용 → 목록 노출: **최대 24시간**
- Activate → Cost Explorer 반영: **추가 최대 24시간**
- 태깅부터 완전 조회까지: **최대 48시간**

**과거 데이터는 소급 적용 안 됨.** 필요 시 `StartCostAllocationTagBackfill` API로 최대 12개월 과거 데이터 백필 가능 (24시간당 1회 제한).

---

## 검증 쿼리

### 프로젝트별 전체 리소스 조회
```bash
AWS_PROFILE=developer-dongik aws resourcegroupstaggingapi get-resources \
  --region ap-northeast-2 \
  --tag-filters Key=Project,Values=<project-slug> \
  --query 'ResourceTagMappingList[].ResourceARN' --output json
```

### 태그 없는 리소스 찾기 (컴플라이언스 체크)
```bash
# 특정 서비스 리소스 중 Project 태그 없는 것 검출
AWS_PROFILE=developer-dongik aws resourcegroupstaggingapi get-resources \
  --region ap-northeast-2 \
  --resource-type-filters lambda:function dynamodb:table s3 sns sqs \
  --query 'ResourceTagMappingList[?!(Tags[?Key==`Project`])].ResourceARN' \
  --output json
```

### 특정 IAM 역할 태그 확인
```bash
aws iam list-role-tags --role-name <name>
aws iam list-open-id-connect-provider-tags --open-id-connect-provider-arn <arn>
```

---

## 신규 프로젝트 시작 체크리스트

- [ ] 프로젝트 슬러그 결정 (kebab-case, 예: `newproject`)
- [ ] IaC 도구 선택 (Serverless / CDK / Terraform) 후 default tag 설정
- [ ] 리소스 네이밍: `<project>-<component>-<purpose>` 규약 준수
- [ ] 프로젝트 전용 SNS 토픽 `<project>-alerts` 생성
- [ ] 첫 배포 후 `get-resources --tag-filters Key=Project,Values=<slug>`로 태깅 검증
- [ ] (공용 인프라 봇 운영 중이라면) `<project>-alerts` 토픽에 `aws-infra-monitor-bot` 구독 추가
- [ ] AWS Budgets에 프로젝트별 예산 생성 (선택): `TagKeyValue: user:Project$<slug>` 필터

---

## 참고 문서

- [AWS Resource Tagging Best Practices](https://docs.aws.amazon.com/whitepapers/latest/tagging-best-practices/tagging-best-practices.html)
- [Cost Allocation Tags](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/cost-alloc-tags.html)
- [Activating User-Defined Tags](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/activating-tags.html)
- `plan-ops-hardening.md` — Slack Bot + 인프라 모니터링 계획
