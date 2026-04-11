import { Duration, Stack, StackProps } from "aws-cdk-lib";
import {
  Alarm,
  ComparisonOperator,
  Metric,
  TreatMissingData,
} from "aws-cdk-lib/aws-cloudwatch";
import { SnsAction } from "aws-cdk-lib/aws-cloudwatch-actions";
import { Topic } from "aws-cdk-lib/aws-sns";
import { EmailSubscription } from "aws-cdk-lib/aws-sns-subscriptions";
import { Construct } from "constructs";

interface AlarmsStackProps extends StackProps {
  alertEmail: string;
}

/**
 * CloudWatch alarms for operational visibility.
 *
 * - Daily cost > $5 → email alert (AWS/Billing metric)
 * - Briefing Lambda errors
 * - DLQ depth > 0 — failed briefing invocations
 */
export class FinanceaiappAlarmsStack extends Stack {
  public readonly alertTopic: Topic;

  constructor(scope: Construct, id: string, props: AlarmsStackProps) {
    super(scope, id, props);

    this.alertTopic = new Topic(this, "AlertTopic", {
      topicName: "financeaiapp-alerts",
      displayName: "finance-ai-app alerts",
    });

    this.alertTopic.addSubscription(new EmailSubscription(props.alertEmail));

    // Daily cost alarm
    const dailyCostAlarm = new Alarm(this, "DailyCostAlarm", {
      alarmName: "financeaiapp-daily-cost",
      alarmDescription: "Daily AWS cost > $5 — possible runaway",
      metric: new Metric({
        namespace: "AWS/Billing",
        metricName: "EstimatedCharges",
        dimensionsMap: { Currency: "USD" },
        statistic: "Maximum",
        period: Duration.hours(6),
      }),
      threshold: 5,
      evaluationPeriods: 1,
      comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: TreatMissingData.NOT_BREACHING,
    });
    dailyCostAlarm.addAlarmAction(new SnsAction(this.alertTopic));

    // Briefing Lambda errors
    const briefingLambdaErrors = new Alarm(this, "BriefingLambdaErrorsAlarm", {
      alarmName: "financeaiapp-briefing-lambda-errors",
      alarmDescription: "Briefing Lambda errors in last 15 min",
      metric: new Metric({
        namespace: "AWS/Lambda",
        metricName: "Errors",
        dimensionsMap: { FunctionName: "financeaiapp-briefing-proxy" },
        statistic: "Sum",
        period: Duration.minutes(15),
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator:
        ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: TreatMissingData.NOT_BREACHING,
    });
    briefingLambdaErrors.addAlarmAction(new SnsAction(this.alertTopic));

    // DLQ depth > 0
    const dlqDepth = new Alarm(this, "BriefingDLQDepthAlarm", {
      alarmName: "financeaiapp-briefing-dlq-depth",
      alarmDescription: "Briefing DLQ has messages — failed invocations",
      metric: new Metric({
        namespace: "AWS/SQS",
        metricName: "ApproximateNumberOfMessagesVisible",
        dimensionsMap: { QueueName: "financeaiapp-briefing-dlq" },
        statistic: "Maximum",
        period: Duration.minutes(5),
      }),
      threshold: 0,
      evaluationPeriods: 1,
      comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: TreatMissingData.NOT_BREACHING,
    });
    dlqDepth.addAlarmAction(new SnsAction(this.alertTopic));
  }
}
