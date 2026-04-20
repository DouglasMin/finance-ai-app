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

function requireEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing required env var: ${name}`);
  return v;
}

const SLACK_TOKEN_PARAM = requireEnv("SLACK_TOKEN_PARAM");
const SLACK_CHANNEL_PARAM = requireEnv("SLACK_CHANNEL_PARAM");
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

// See docs/sns-event-schema.md for the contract.
type StrategyEventType =
  | "strategy_created"
  | "strategy_removed"
  | "strategy_toggled"
  | "strategy_triggered";

interface StrategyEnvelope {
  type: StrategyEventType;
  schema_version: string;
  event_id: string;
  timestamp: string;
  source: string;
  environment: string;
  correlation_id?: string;
  data: Record<string, unknown>;
}

const SUPPORTED_STRATEGY_TYPES: ReadonlySet<StrategyEventType> = new Set([
  "strategy_created",
  "strategy_removed",
  "strategy_toggled",
  "strategy_triggered",
]);

function isStrategyEnvelope(obj: unknown): obj is StrategyEnvelope {
  if (!obj || typeof obj !== "object") return false;
  const t = (obj as { type?: unknown }).type;
  return typeof t === "string" && SUPPORTED_STRATEGY_TYPES.has(t as StrategyEventType);
}

function str(v: unknown): string | undefined {
  return typeof v === "string" && v.length > 0 ? v : undefined;
}

function num(v: unknown): number | undefined {
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
}

function bool(v: unknown): boolean | undefined {
  return typeof v === "boolean" ? v : undefined;
}

function fmtNum(n: number, digits = 2): string {
  return n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function buildStrategyBlocks(env: StrategyEnvelope): unknown[] {
  const d = env.data;
  const name = str(d.name) ?? "unknown";
  const symbol = str(d.symbol) ?? "?";
  const condition = str(d.condition_human) ?? "";
  const action = str(d.action);
  const quantity = num(d.quantity);
  const actor = str(d.actor) ?? "user";

  let icon = "🔔";
  let title = "";
  const fields: string[] = [];

  switch (env.type) {
    case "strategy_created": {
      icon = "🆕";
      title = `전략 등록 · ${name}`;
      fields.push(`> *종목:* ${symbol}`);
      if (condition) fields.push(`> *조건:* ${condition}`);
      if (action) {
        const actionStr =
          action === "alert"
            ? "알림만"
            : `${action === "buy" ? "매수" : "매도"}${quantity ? ` ${quantity}개` : ""}`;
        fields.push(`> *행동:* ${actionStr}`);
      }
      const description = str(d.description);
      if (description) fields.push(`> *설명:* ${description}`);
      fields.push(`> _by ${actor}_`);
      break;
    }
    case "strategy_removed": {
      icon = "🗑️";
      title = `전략 삭제 · ${name}`;
      fields.push(`> *종목:* ${symbol}`);
      if (condition) fields.push(`> *조건:* ${condition}`);
      const triggerCount = num(d.trigger_count);
      if (triggerCount !== undefined) fields.push(`> *누적 발동:* ${triggerCount}회`);
      const lastTriggered = str(d.last_triggered);
      if (lastTriggered) fields.push(`> *마지막 발동:* ${lastTriggered}`);
      break;
    }
    case "strategy_toggled": {
      const enabled = bool(d.enabled) ?? true;
      icon = enabled ? "▶️" : "⏸️";
      title = `전략 ${enabled ? "활성화" : "비활성화"} · ${name}`;
      fields.push(`> *종목:* ${symbol}`);
      if (condition) fields.push(`> *조건:* ${condition}`);
      fields.push(`> *상태:* ${enabled ? "🟢 활성" : "⚪ 비활성"}`);
      break;
    }
    case "strategy_triggered": {
      const success = bool(d.success) ?? false;
      const price = num(d.price);
      const currency = str(d.currency) ?? "";
      const changePct = num(d.change_pct);
      const fillPrice = num(d.fill_price);
      const cashAfter = num(d.cash_after);
      const realizedPnl = num(d.realized_pnl_pct);
      const triggerCount = num(d.trigger_count);
      const resultMsg = str(d.result_msg);
      const errorMsg = str(d.error_msg);

      if (!success) {
        icon = "⚠️";
        title = `실행 실패 · ${name}`;
      } else if (action === "alert") {
        icon = "🔔";
        title = `조건 충족 · ${name}`;
      } else if (action === "buy") {
        icon = "🟢";
        title = `자동 매수 · ${name}`;
      } else if (action === "sell") {
        icon = realizedPnl !== undefined && realizedPnl < 0 ? "🔴" : "🟢";
        title = `자동 매도 · ${name}`;
      } else {
        icon = "🔔";
        title = `전략 발동 · ${name}`;
      }

      fields.push(`> *종목:* ${symbol}`);
      if (condition) fields.push(`> *조건:* ${condition}`);
      if (price !== undefined) {
        const changeStr =
          changePct !== undefined ? ` (${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%)` : "";
        fields.push(`> *시세:* ${fmtNum(price)} ${currency}${changeStr}`);
      }
      if (success && (action === "buy" || action === "sell") && fillPrice !== undefined) {
        const qtyStr = quantity !== undefined ? `${quantity}개 ` : "";
        fields.push(`> *체결:* ${qtyStr}@ ${fmtNum(fillPrice)} ${currency}`);
      }
      if (success && realizedPnl !== undefined) {
        fields.push(
          `> *실현 손익:* ${realizedPnl >= 0 ? "+" : ""}${realizedPnl.toFixed(2)}%`,
        );
      }
      if (success && cashAfter !== undefined) {
        fields.push(`> *잔여 현금:* ${fmtNum(cashAfter)} ${currency}`);
      }
      if (triggerCount !== undefined) {
        fields.push(`> *누적 발동:* ${triggerCount}회`);
      }
      if (!success) {
        if (resultMsg) fields.push(`> *결과:* ${resultMsg}`);
        if (errorMsg) fields.push(`> *에러:* ${errorMsg.slice(0, 200)}`);
      } else if (action === "alert" && resultMsg) {
        fields.push(`> ${resultMsg}`);
      }
      break;
    }
  }

  const headerText = `${icon} *[${PROJECT_TAG}]* ${title}`;
  const body = fields.join("\n");

  const blocks: unknown[] = [
    { type: "section", text: { type: "mrkdwn", text: headerText } },
  ];
  if (body.length > 0) {
    blocks.push({ type: "section", text: { type: "mrkdwn", text: body } });
  }
  blocks.push({ type: "divider" });
  return blocks;
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
    let blocks: unknown[] = [];
    let fallbackText = sns.Subject ?? "Notification";

    try {
      const parsed: unknown = JSON.parse(sns.Message);

      if (isStrategyEnvelope(parsed)) {
        blocks = buildStrategyBlocks(parsed);
        const dataName = str((parsed.data as { name?: unknown } | undefined)?.name);
        fallbackText = `[${PROJECT_TAG}] ${parsed.type}${dataName ? ` · ${dataName}` : ""}`;
      } else if (
        parsed !== null &&
        typeof parsed === "object" &&
        typeof (parsed as { AlarmName?: unknown }).AlarmName === "string" &&
        typeof (parsed as { NewStateValue?: unknown }).NewStateValue === "string"
      ) {
        const alarm = parsed as CloudWatchAlarmMessage;
        blocks = buildAlarmBlocks(alarm);
        fallbackText = `[${PROJECT_TAG}] ${alarm.AlarmName} → ${alarm.NewStateValue}`;
      } else {
        blocks = buildFallbackBlocks(sns.Subject, sns.Message);
      }
    } catch {
      blocks = buildFallbackBlocks(sns.Subject, sns.Message);
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
