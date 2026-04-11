import { Duration, Stack, StackProps } from "aws-cdk-lib";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { Runtime, Architecture } from "aws-cdk-lib/aws-lambda";
import { NodejsFunction } from "aws-cdk-lib/aws-lambda-nodejs";
import { Rule, Schedule, RuleTargetInput } from "aws-cdk-lib/aws-events";
import { LambdaFunction } from "aws-cdk-lib/aws-events-targets";
import { Queue } from "aws-cdk-lib/aws-sqs";
import { Construct } from "constructs";
import * as path from "path";

interface BriefingStackProps extends StackProps {
  agentCoreRuntimeArn: string;
}

export class FinanceaiappBriefingStack extends Stack {
  constructor(scope: Construct, id: string, props: BriefingStackProps) {
    super(scope, id, props);

    // SQS DLQ for failed briefing invocations
    const dlq = new Queue(this, "BriefingDLQ", {
      queueName: "financeaiapp-briefing-dlq",
      retentionPeriod: Duration.days(14),
    });

    // Lambda proxy — invoked by EventBridge cron, calls AgentCore /briefing
    const proxyFn = new NodejsFunction(this, "BriefingProxy", {
      functionName: "financeaiapp-briefing-proxy",
      runtime: Runtime.NODEJS_22_X,
      architecture: Architecture.ARM_64,
      entry: path.join(__dirname, "../lambda/briefing-proxy/index.ts"),
      handler: "handler",
      timeout: Duration.minutes(5),
      memorySize: 256,
      environment: {
        AGENTCORE_RUNTIME_ARN: props.agentCoreRuntimeArn,
      },
      deadLetterQueue: dlq,
      bundling: {
        minify: false,
        sourceMap: true,
        externalModules: [],
      },
    });

    proxyFn.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ["bedrock-agentcore:InvokeAgentRuntime"],
        resources: [props.agentCoreRuntimeArn],
      }),
    );

    // Morning: 09:00 KST = 00:00 UTC
    new Rule(this, "MorningBriefingRule", {
      ruleName: "financeaiapp-briefing-morning",
      description: "Daily morning briefing at 09:00 KST",
      schedule: Schedule.cron({ minute: "0", hour: "0" }),
      targets: [
        new LambdaFunction(proxyFn, {
          event: RuleTargetInput.fromObject({ time_of_day: "AM" }),
        }),
      ],
    });

    // Evening: 18:00 KST = 09:00 UTC
    new Rule(this, "EveningBriefingRule", {
      ruleName: "financeaiapp-briefing-evening",
      description: "Daily evening briefing at 18:00 KST",
      schedule: Schedule.cron({ minute: "0", hour: "9" }),
      targets: [
        new LambdaFunction(proxyFn, {
          event: RuleTargetInput.fromObject({ time_of_day: "PM" }),
        }),
      ],
    });
  }
}
