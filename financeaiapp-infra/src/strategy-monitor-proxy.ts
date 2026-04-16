/**
 * Strategy Monitor Proxy Lambda — triggered by EventBridge cron (every 30 min).
 *
 * Calls AgentCore Runtime via InvokeAgentRuntimeCommand with
 * {action: "strategy_monitor"} payload. Same retry pattern as briefing-proxy.
 */
import {
  BedrockAgentCoreClient,
  InvokeAgentRuntimeCommand,
} from "@aws-sdk/client-bedrock-agentcore";

interface StrategyMonitorResult {
  status: "success" | "failed";
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

export const handler = async (): Promise<StrategyMonitorResult> => {
  console.log(JSON.stringify({ event: "strategy-monitor.start" }));

  if (!RUNTIME_ARN) {
    const msg = "AGENTCORE_RUNTIME_ARN env var not set";
    console.error(JSON.stringify({ event: "strategy-monitor.config_error", error: msg }));
    throw new Error(msg);
  }

  const body = {
    action: "strategy_monitor",
    correlation_id: `strategy-${Date.now()}`,
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
      console.log(JSON.stringify({ event: "strategy-monitor.success", attempt }));
      return { status: "success", attempt };
    } catch (err: unknown) {
      lastError = err;
      const message = err instanceof Error ? err.message : String(err);
      console.error(JSON.stringify({ event: "strategy-monitor.attempt_failed", attempt, error: message }));
      if (attempt < MAX_ATTEMPTS) {
        await delay(1000 * 2 ** attempt);
      }
    }
  }

  const finalMsg = lastError instanceof Error ? lastError.message : "unknown";
  console.error(JSON.stringify({ event: "strategy-monitor.all_attempts_failed", error: finalMsg }));
  throw new Error(`Strategy monitor failed after ${MAX_ATTEMPTS} attempts: ${finalMsg}`);
};
