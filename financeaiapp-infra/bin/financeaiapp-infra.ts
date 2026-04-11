#!/usr/bin/env node
import "source-map-support/register";
import { App } from "aws-cdk-lib";
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

// Briefing Lambda + EventBridge — requires AgentCore Runtime ARN
const runtimeArn = process.env.AGENTCORE_RUNTIME_ARN;
if (runtimeArn) {
  new FinanceaiappBriefingStack(app, "FinanceaiappBriefing", {
    env,
    agentCoreRuntimeArn: runtimeArn,
  });
}

// Frontend S3 + CloudFront — requires built dist/
new FinanceaiappFrontendStack(app, "FinanceaiappFrontend", { env });
