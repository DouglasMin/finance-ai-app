/**
 * Briefing Proxy Lambda — triggered by EventBridge cron.
 *
 * Calls AgentCore Runtime via InvokeAgentRuntimeCommand with
 * {action: "briefing", time_of_day: "AM"|"PM"} payload.
 * Implements exponential backoff retries and throws on final
 * failure so the Lambda's SQS DLQ captures the error.
 */
import {
  BedrockAgentCoreClient,
  InvokeAgentRuntimeCommand,
} from "@aws-sdk/client-bedrock-agentcore";

interface BriefingEvent {
  time_of_day: "AM" | "PM";
  dry_run?: boolean;
}

interface BriefingResult {
  status: "success" | "dry_run" | "failed";
  attempt?: number;
  error?: string;
}

const REGION = process.env.AWS_REGION ?? "ap-northeast-2";
const RUNTIME_ARN = process.env.AGENTCORE_RUNTIME_ARN;
const MAX_ATTEMPTS = 3;

const client = new BedrockAgentCoreClient({ region: REGION });

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export const handler = async (event: BriefingEvent): Promise<BriefingResult> => {
  console.log(JSON.stringify({ event: "briefing-proxy.start", payload: event }));

  if (!RUNTIME_ARN) {
    const msg = "AGENTCORE_RUNTIME_ARN env var not set";
    console.error(JSON.stringify({ event: "briefing-proxy.config_error", error: msg }));
    throw new Error(msg);
  }

  if (event.dry_run) {
    console.log(JSON.stringify({ event: "briefing-proxy.dry_run", time_of_day: event.time_of_day }));
    return { status: "dry_run" };
  }

  const correlationId = `briefing-${Date.now()}-${event.time_of_day}`;
  const body = {
    action: "briefing",
    time_of_day: event.time_of_day,
    correlation_id: correlationId,
  };

  let lastError: unknown;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    try {
      const command = new InvokeAgentRuntimeCommand({
        agentRuntimeArn: RUNTIME_ARN,
        payload: new TextEncoder().encode(JSON.stringify(body)),
        qualifier: "DEFAULT",
      });
      await client.send(command);
      console.log(
        JSON.stringify({
          event: "briefing-proxy.success",
          attempt,
          correlation_id: correlationId,
        }),
      );
      return { status: "success", attempt };
    } catch (err: unknown) {
      lastError = err;
      const message = err instanceof Error ? err.message : String(err);
      console.error(
        JSON.stringify({
          event: "briefing-proxy.attempt_failed",
          attempt,
          error: message,
        }),
      );
      if (attempt < MAX_ATTEMPTS) {
        const backoffMs = 1000 * 2 ** attempt;
        await delay(backoffMs);
      }
    }
  }

  const finalMsg = lastError instanceof Error ? lastError.message : "unknown";
  console.error(
    JSON.stringify({
      event: "briefing-proxy.all_attempts_failed",
      error: finalMsg,
    }),
  );
  throw new Error(`Briefing invocation failed after ${MAX_ATTEMPTS} attempts: ${finalMsg}`);
};
