/**
 * Slack Interactive Lambda — receives button clicks / slash commands from Slack.
 *
 * Phase 2 (now): Skeleton that verifies Slack signatures and returns a
 * placeholder message. No business logic.
 *
 * Phase 3 (next): Will parse payload.type === "block_actions", route on
 * payload.actions[].action_id (e.g. "approve_trade" / "reject_trade"), look
 * up pending approval in DDB, and resume the LangGraph interrupt.
 *
 * Security:
 *   - Slack signs every request with HMAC-SHA256 over `v0:{ts}:{body}`.
 *   - We reject requests where timestamp drifts more than 5 minutes (replay).
 *   - Signing secret loaded once from SSM SecureString, cached across warm
 *     invocations.
 */
import { createHmac, timingSafeEqual } from "node:crypto";
import { SSMClient, GetParameterCommand } from "@aws-sdk/client-ssm";
import type { LambdaFunctionURLEvent, LambdaFunctionURLResult } from "aws-lambda";

const REGION = process.env.AWS_REGION ?? "ap-northeast-2";

function requireEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing required env var: ${name}`);
  return v;
}

const SIGNING_SECRET_PARAM = requireEnv("SLACK_SIGNING_SECRET_PARAM");

const ssm = new SSMClient({ region: REGION });
let cachedSigningSecret: string | undefined;

async function getSigningSecret(): Promise<string> {
  if (!cachedSigningSecret) {
    const res = await ssm.send(
      new GetParameterCommand({ Name: SIGNING_SECRET_PARAM, WithDecryption: true }),
    );
    const value = res.Parameter?.Value;
    if (!value) throw new Error(`SSM parameter ${SIGNING_SECRET_PARAM} has no value`);
    cachedSigningSecret = value;
  }
  return cachedSigningSecret;
}

function getHeader(
  headers: Record<string, string | undefined> | undefined,
  name: string,
): string | undefined {
  if (!headers) return undefined;
  const lower = name.toLowerCase();
  for (const [k, v] of Object.entries(headers)) {
    if (k.toLowerCase() === lower) return v;
  }
  return undefined;
}

function verifySignature(
  signingSecret: string,
  timestamp: string,
  rawBody: string,
  receivedSignature: string,
): boolean {
  const basestring = `v0:${timestamp}:${rawBody}`;
  const expected = `v0=${createHmac("sha256", signingSecret).update(basestring).digest("hex")}`;

  // Buffers must be equal length for timingSafeEqual
  const expectedBuf = Buffer.from(expected);
  const receivedBuf = Buffer.from(receivedSignature);
  if (expectedBuf.length !== receivedBuf.length) return false;

  return timingSafeEqual(expectedBuf, receivedBuf);
}

function jsonResponse(statusCode: number, body: unknown): LambdaFunctionURLResult {
  return {
    statusCode,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const handler = async (
  event: LambdaFunctionURLEvent,
): Promise<LambdaFunctionURLResult> => {
  const reqId = event.requestContext.requestId;

  // Method gate — Slack always POSTs
  const method = event.requestContext.http.method;
  if (method !== "POST") {
    return jsonResponse(405, { error: "Method not allowed" });
  }

  // Body extraction (Function URL may base64-encode)
  let rawBody = event.body ?? "";
  if (event.isBase64Encoded) {
    rawBody = Buffer.from(rawBody, "base64").toString("utf-8");
  }

  const timestamp = getHeader(event.headers, "x-slack-request-timestamp");
  const signature = getHeader(event.headers, "x-slack-signature");

  if (!timestamp || !signature) {
    console.warn(JSON.stringify({ event: "slack.missing_headers", reqId }));
    return jsonResponse(400, { error: "Missing Slack signature headers" });
  }

  // Reject replays (>5 min drift in either direction)
  const tsNum = Number.parseInt(timestamp, 10);
  if (!Number.isFinite(tsNum)) {
    return jsonResponse(400, { error: "Invalid timestamp" });
  }
  const nowSec = Math.floor(Date.now() / 1000);
  if (Math.abs(nowSec - tsNum) > 300) {
    console.warn(
      JSON.stringify({ event: "slack.stale_timestamp", reqId, drift: nowSec - tsNum }),
    );
    return jsonResponse(401, { error: "Stale timestamp" });
  }

  // Verify HMAC
  let signingSecret: string;
  try {
    signingSecret = await getSigningSecret();
  } catch (err) {
    console.error(
      JSON.stringify({
        event: "slack.ssm_error",
        reqId,
        error: err instanceof Error ? err.message : String(err),
      }),
    );
    return jsonResponse(500, { error: "Internal error" });
  }

  if (!verifySignature(signingSecret, timestamp, rawBody, signature)) {
    console.warn(JSON.stringify({ event: "slack.invalid_signature", reqId }));
    return jsonResponse(401, { error: "Invalid signature" });
  }

  // Signature verified. Log the payload shape (not contents) and return placeholder.
  // Slack Interactive payloads arrive as `payload=<url-encoded-json>` form body.
  let payloadType: string | undefined;
  try {
    const params = new URLSearchParams(rawBody);
    const payloadStr = params.get("payload");
    if (payloadStr) {
      const payload = JSON.parse(payloadStr) as { type?: string };
      payloadType = payload.type;
    }
  } catch {
    // Ignore — just informational logging
  }

  console.log(
    JSON.stringify({
      event: "slack.interactive_received",
      reqId,
      payloadType,
      hasBody: rawBody.length > 0,
    }),
  );

  // Placeholder ephemeral response. Phase 3 will replace this with real
  // approve/reject routing + DDB pending-approval update + LangGraph resume.
  return jsonResponse(200, {
    response_type: "ephemeral",
    text: "⏳ 승인 처리 기능은 Phase 3에서 구현 예정입니다. 지금은 엔드포인트 연결만 검증되었습니다.",
  });
};
