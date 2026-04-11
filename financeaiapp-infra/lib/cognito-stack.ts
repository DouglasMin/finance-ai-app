import { CfnOutput, Stack, StackProps } from "aws-cdk-lib";
import {
  CfnIdentityPool,
  CfnIdentityPoolRoleAttachment,
} from "aws-cdk-lib/aws-cognito";
import {
  Effect,
  FederatedPrincipal,
  PolicyStatement,
  Role,
} from "aws-cdk-lib/aws-iam";
import { Construct } from "constructs";

export class FinanceaiappCognitoStack extends Stack {
  public readonly identityPoolId: string;

  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    const pool = new CfnIdentityPool(this, "IdentityPool", {
      identityPoolName: "financeaiapp_pool",
      allowUnauthenticatedIdentities: true,
    });

    const guestRole = new Role(this, "GuestRole", {
      roleName: "financeaiapp-guest-role",
      assumedBy: new FederatedPrincipal(
        "cognito-identity.amazonaws.com",
        {
          StringEquals: {
            "cognito-identity.amazonaws.com:aud": pool.ref,
          },
          "ForAnyValue:StringLike": {
            "cognito-identity.amazonaws.com:amr": "unauthenticated",
          },
        },
        "sts:AssumeRoleWithWebIdentity",
      ),
    });

    // Scoped IAM: only InvokeAgentRuntime on our specific runtimes
    guestRole.addToPolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ["bedrock-agentcore:InvokeAgentRuntime"],
        resources: [
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:runtime/financial-bot-*`,
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:runtime/financeaiapp-*`,
        ],
      }),
    );

    new CfnIdentityPoolRoleAttachment(this, "PoolRoles", {
      identityPoolId: pool.ref,
      roles: {
        unauthenticated: guestRole.roleArn,
      },
    });

    this.identityPoolId = pool.ref;

    new CfnOutput(this, "IdentityPoolIdOutput", {
      value: pool.ref,
      description: "Cognito Identity Pool ID for frontend",
    });
  }
}
