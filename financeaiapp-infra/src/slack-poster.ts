/**
 * Slack Poster Lambda — triggered by SNS AlertTopic.
 *
 * Converts CloudWatch alarm payload into Slack Block Kit message
 * and posts to the ops channel. Failures are logged but never
 * thrown back (fire-and-forget) to avoid notification loops.
 */
import { WebClient } from "@slack/web-api";
import { SSMClient, GetParameterCommand } from "@aws-sdk/client-ssm";
import type { SNSEvent } from "aws-lambda";

const REGION = process.env.AWS_REGION ?? "ap-northeast-2";
const SLACK_TOKEN_PARAM = process.env.SLACK_TOKEN_PARAM!;
const SLACK_CHANNEL_PARAM = process.env.SLACK_CHANNEL_PARAM!;
const PROJECT_TAG = process.env.PROJECT_TAG ?? "financeaiapp";

const ssm = new SSMClient({ region: REGION });

let cachedToken: string | undefined;
let cachedChannel: string | undefined;

async function getParam(name: string, withDecryption: boolean): Promise<string> {
  const res = await ssm.send(
    new GetParameterCommand({ Name: name, WithDecryption: withDecryption }),
  );
  const value = res.Parameter?.Value;
  if (!value) throw new Error(`SSM parameter ${name} has no value`);
  return value;
}

async function getSlackClient(): Promise<{ client: WebClient; channel: string }> {
  if (!cachedToken) cachedToken = await getParam(SLACK_TOKEN_PARAM, true);
  if (!cachedChannel) cachedChannel = await getParam(SLACK_CHANNEL_PARAM, false);
  return { client: new WebClient(cachedToken), channel: cachedChannel };
}

interface CloudWatchAlarmMessage {
  AlarmName: string;
  AlarmDescription?: string;
  NewStateValue: "OK" | "ALARM" | "INSUFFICIENT_DATA";
  NewStateReason: string;
  Region: string;
  AWSAccountId: string;
  StateChangeTime: string;
  Trigger?: {
    MetricName?: string;
    Namespace?: string;
    Threshold?: number;
    ComparisonOperator?: string;
    Period?: number;
  };
}

function buildAlarmBlocks(alarm: CloudWatchAlarmMessage): unknown[] {
  const emoji =
    alarm.NewStateValue === "ALARM"
      ? "🚨"
      : alarm.NewStateValue === "OK"
        ? "✅"
        : "⚠️";
  const headerText = `${emoji} *[${PROJECT_TAG}]* ${alarm.AlarmName}`;
  const consoleUrl = `https://${alarm.Region}.console.aws.amazon.com/cloudwatch/home?region=${alarm.Region}#alarmsV2:alarm/${encodeURIComponent(alarm.AlarmName)}`;

  const fields: string[] = [];
  if (alarm.AlarmDescription) fields.push(`> ${alarm.AlarmDescription}`);
  fields.push(`> *State:* ${alarm.NewStateValue}`);
  if (alarm.Trigger?.MetricName) {
    const { MetricName, Threshold, ComparisonOperator } = alarm.Trigger;
    fields.push(`> *Metric:* ${MetricName} ${ComparisonOperator ?? ""} ${Threshold ?? ""}`);
  }
  fields.push(`> *Reason:* ${alarm.NewStateReason.slice(0, 300)}`);

  return [
    {
      type: "section",
      text: { type: "mrkdwn", text: headerText },
    },
    {
      type: "section",
      text: { type: "mrkdwn", text: fields.join("\n") },
    },
    {
      type: "actions",
      elements: [
        {
          type: "button",
          text: { type: "plain_text", text: "CloudWatch에서 보기" },
          url: consoleUrl,
        },
      ],
    },
    { type: "divider" },
  ];
}

function buildFallbackBlocks(subject: string | undefined, message: string): unknown[] {
  return [
    {
      type: "section",
      text: { type: "mrkdwn", text: `📢 *[${PROJECT_TAG}]* ${subject ?? "Notification"}` },
    },
    {
      type: "section",
      text: { type: "mrkdwn", text: `\`\`\`${message.slice(0, 2800)}\`\`\`` },
    },
    { type: "divider" },
  ];
}

export const handler = async (event: SNSEvent): Promise<void> => {
  console.log(JSON.stringify({ event: "slack-poster.start", records: event.Records.length }));

  const { client, channel } = await getSlackClient();

  for (const record of event.Records) {
    const sns = record.Sns;
    let blocks: unknown[];
    let fallbackText: string;

    try {
      const parsed = JSON.parse(sns.Message) as CloudWatchAlarmMessage;
      if (parsed.AlarmName && parsed.NewStateValue) {
        blocks = buildAlarmBlocks(parsed);
        fallbackText = `[${PROJECT_TAG}] ${parsed.AlarmName} → ${parsed.NewStateValue}`;
      } else {
        blocks = buildFallbackBlocks(sns.Subject, sns.Message);
        fallbackText = sns.Subject ?? "Notification";
      }
    } catch {
      blocks = buildFallbackBlocks(sns.Subject, sns.Message);
      fallbackText = sns.Subject ?? "Notification";
    }

    try {
      const res = await client.chat.postMessage({
        channel,
        text: fallbackText,
        blocks: blocks as never,
      });
      console.log(
        JSON.stringify({
          event: "slack-poster.posted",
          ts: res.ts,
          messageId: sns.MessageId,
        }),
      );
    } catch (err) {
      console.error(
        JSON.stringify({
          event: "slack-poster.post_failed",
          messageId: sns.MessageId,
          error: err instanceof Error ? err.message : String(err),
        }),
      );
      // Swallow error — never fail the Lambda (prevents notification loops).
    }
  }
};
