#!/usr/bin/env node
import "source-map-support/register";
import * as fs from "fs";
import * as path from "path";
import { App } from "aws-cdk-lib";
import { FinanceaiappAlarmsStack } from "../lib/alarms-stack";
import { FinanceaiappBriefingStack } from "../lib/briefing-stack";
import { FinanceaiappCognitoStack } from "../lib/cognito-stack";
import { FinanceaiappFrontendStack } from "../lib/frontend-stack";
import { FinanceaiappOidcStack } from "../lib/oidc-stack";

const app = new App();

const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION ?? "us-east-1",
};

// OIDC stack — deploy manually once using local AWS credentials; afterwards
// GitHub Actions uses the generated role to deploy everything else.
new FinanceaiappOidcStack(app, "FinanceaiappOidc", {
  env,
  githubOwner: process.env.GITHUB_OWNER ?? "DouglasMin",
  githubRepo: process.env.GITHUB_REPO ?? "finance-ai-app",
});

// Cognito Identity Pool — always deployable
new FinanceaiappCognitoStack(app, "FinanceaiappCognito", { env });

// CloudWatch alarms + SNS topic
new FinanceaiappAlarmsStack(app, "FinanceaiappAlarms", {
  env,
  alertEmail: process.env.ALERT_EMAIL ?? "dongik.dev73@gmail.com",
});

// Briefing Lambda + EventBridge — requires AgentCore Runtime ARN
const runtimeArn = process.env.AGENTCORE_RUNTIME_ARN;
if (runtimeArn) {
  new FinanceaiappBriefingStack(app, "FinanceaiappBriefing", {
    env,
    agentCoreRuntimeArn: runtimeArn,
  });
}

// Frontend S3 + CloudFront — only when the built `dist/` exists, because
// BucketDeployment reads it at synth time. Otherwise skip so OIDC / Cognito /
// Briefing stacks can be deployed independently.
const frontendDist = path.resolve(
  __dirname,
  "../../financeaiapp-frontend/dist",
);
if (fs.existsSync(frontendDist)) {
  new FinanceaiappFrontendStack(app, "FinanceaiappFrontend", { env });
}
