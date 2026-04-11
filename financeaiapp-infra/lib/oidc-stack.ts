import { CfnOutput, Stack, StackProps } from "aws-cdk-lib";
import {
  Effect,
  OpenIdConnectProvider,
  PolicyStatement,
  Role,
  WebIdentityPrincipal,
} from "aws-cdk-lib/aws-iam";
import { Construct } from "constructs";

interface OidcStackProps extends StackProps {
  githubOwner: string;
  githubRepo: string;
}

/**
 * GitHub Actions → AWS OIDC trust configuration.
 *
 * Creates the IAM OIDC provider for GitHub and a deploy role that GitHub
 * Actions can assume using token.actions.githubusercontent.com JWT. The
 * role trust policy is scoped to this specific repository.
 *
 * This stack MUST be deployed manually ONCE (`cdk deploy FinanceaiappOidc`)
 * before the GitHub Actions workflows can run, because without this role
 * the workflows have no way to authenticate to AWS.
 */
export class FinanceaiappOidcStack extends Stack {
  public readonly deployRoleArn: string;

  constructor(scope: Construct, id: string, props: OidcStackProps) {
    super(scope, id, props);

    const provider = new OpenIdConnectProvider(this, "GithubOIDC", {
      url: "https://token.actions.githubusercontent.com",
      clientIds: ["sts.amazonaws.com"],
    });

    const deployRole = new Role(this, "GithubDeployRole", {
      roleName: "finance-ai-app-github-deploy",
      description: "Assumed by GitHub Actions for finance-ai-app deployments",
      assumedBy: new WebIdentityPrincipal(provider.openIdConnectProviderArn, {
        StringEquals: {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        },
        StringLike: {
          "token.actions.githubusercontent.com:sub": `repo:${props.githubOwner}/${props.githubRepo}:*`,
        },
      }),
      maxSessionDuration: Stack.of(this).node.tryGetContext("deployRoleMaxSession") ?? undefined,
    });

    // For a personal deploy role: broad permissions scoped to CDK bootstrap +
    // agentcore deploy + infra resources. In production, break this down.
    deployRole.addToPolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: [
          // CloudFormation — CDK deploys via CFN
          "cloudformation:*",
          // S3 — CDK asset bucket, frontend bucket
          "s3:*",
          // Lambda — briefing proxy
          "lambda:*",
          // IAM — CDK creates roles for resources
          "iam:*",
          // CloudFront — frontend distribution
          "cloudfront:*",
          // DynamoDB — existing financial-bot table
          "dynamodb:*",
          // SQS — briefing DLQ
          "sqs:*",
          // EventBridge — cron rules
          "events:*",
          // Cognito — identity pool
          "cognito-identity:*",
          "cognito-idp:*",
          // Secrets Manager — read API keys
          "secretsmanager:*",
          // Logs
          "logs:*",
          // SSM — CDK bootstrap parameters
          "ssm:*",
          // STS — assume roles for CDK bootstrap
          "sts:AssumeRole",
          "sts:GetCallerIdentity",
          // ECR — agentcore container push
          "ecr:*",
          "ecr-public:*",
          // CodeBuild — agentcore uses codebuild for container builds
          "codebuild:*",
          // Bedrock AgentCore
          "bedrock-agentcore:*",
          "bedrock:*",
          // CloudWatch alarms
          "cloudwatch:*",
        ],
        resources: ["*"],
      }),
    );

    this.deployRoleArn = deployRole.roleArn;

    new CfnOutput(this, "DeployRoleArn", {
      value: deployRole.roleArn,
      description: "Add this as GitHub secret AWS_DEPLOY_ROLE_ARN",
      exportName: "FinanceaiappDeployRoleArn",
    });
  }
}
