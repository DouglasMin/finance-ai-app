/**
 * AgentCore Runtime client.
 *
 * Dev: uses `/api/invocations` via Vite proxy to local agentcore dev server.
 * Prod: uses AWS SDK with Cognito Identity Pool guest credentials and SigV4.
 */
import {
  BedrockAgentCoreClient,
  InvokeAgentRuntimeCommand,
} from "@aws-sdk/client-bedrock-agentcore";
import {
  CognitoIdentityClient,
  GetIdCommand,
  GetOpenIdTokenCommand,
} from "@aws-sdk/client-cognito-identity";
import {
  STSClient,
  AssumeRoleWithWebIdentityCommand,
} from "@aws-sdk/client-sts";

import {
  agentCoreRuntimeArn,
  awsRegion,
  identityPoolId,
  isDev,
} from "../env";
import type { WatchlistItem } from "../types";

export interface InvokePayload {
  action: "chat" | "briefing" | "list_watchlist" | "list_briefings" | "add_watchlist" | "remove_watchlist" | "get_llm_provider" | "set_llm_provider";
  session_id?: string;
  message?: string;
  time_of_day?: "AM" | "PM";
  correlation_id?: string;
  provider?: string;
  symbol?: string;
  category?: string;
}

export async function addWatchlistItem(symbol: string, category?: string): Promise<void> {
  const payload: InvokePayload = { action: "add_watchlist", symbol, category };
  const controller = new AbortController();
  const events: Array<Record<string, unknown>> = [];
  for await (const chunk of streamInvocation(payload, controller.signal)) {
    events.push(...parseSseFrames(chunk));
  }
  const errorEvent = events.find((e) => e.event === "error");
  if (errorEvent) {
    const message =
      typeof errorEvent.message === "string"
        ? errorEvent.message
        : "종목을 추가하지 못했습니다.";
    throw new Error(message);
  }
}

export async function removeWatchlistItem(symbol: string): Promise<void> {
  const payload: InvokePayload = { action: "remove_watchlist", symbol };
  const controller = new AbortController();
  for await (const _ of streamInvocation(payload, controller.signal)) {
    // drain stream
  }
}

interface WatchlistApiItem {
  symbol: string;
  category: string;
  added_at?: string;
  price?: number;
  currency?: string;
  changePct?: number;
  open?: number;
  high?: number;
  low?: number;
  volume?: number;
  sparkline?: number[];
}

function parseSseFrames(chunk: string): Array<Record<string, unknown>> {
  const events: Array<Record<string, unknown>> = [];
  for (const line of chunk.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("data:")) continue;
    const jsonStr = trimmed.slice("data:".length).trim();
    if (!jsonStr) continue;
    try {
      events.push(JSON.parse(jsonStr) as Record<string, unknown>);
    } catch {
      // ignore malformed frame
    }
  }
  return events;
}

// Basic (classic) auth flow — avoids Cognito enhanced flow's session
// policy which blocks bedrock-agentcore:InvokeAgentRuntime.
// Flow: GetId → GetOpenIdToken → STS AssumeRoleWithWebIdentity
const GUEST_ROLE_ARN = "arn:aws:iam::612529367436:role/financeaiapp-guest-role";

let _cachedCreds: {
  accessKeyId: string;
  secretAccessKey: string;
  sessionToken: string;
  expiration: Date;
} | null = null;

async function getBasicFlowCredentials() {
  // Reuse cached credentials if not expired (5 min buffer)
  if (_cachedCreds && _cachedCreds.expiration.getTime() - Date.now() > 300_000) {
    return _cachedCreds;
  }

  const cognitoClient = new CognitoIdentityClient({ region: awsRegion });

  const { IdentityId } = await cognitoClient.send(
    new GetIdCommand({ IdentityPoolId: identityPoolId })
  );

  const { Token } = await cognitoClient.send(
    new GetOpenIdTokenCommand({ IdentityId })
  );

  const stsClient = new STSClient({ region: awsRegion });
  const { Credentials } = await stsClient.send(
    new AssumeRoleWithWebIdentityCommand({
      RoleArn: GUEST_ROLE_ARN,
      RoleSessionName: "financeaiapp-guest",
      WebIdentityToken: Token!,
    })
  );

  _cachedCreds = {
    accessKeyId: Credentials!.AccessKeyId!,
    secretAccessKey: Credentials!.SecretAccessKey!,
    sessionToken: Credentials!.SessionToken!,
    expiration: Credentials!.Expiration!,
  };
  return _cachedCreds;
}

async function getClient(): Promise<BedrockAgentCoreClient> {
  const creds = await getBasicFlowCredentials();
  return new BedrockAgentCoreClient({
    region: awsRegion,
    credentials: {
      accessKeyId: creds.accessKeyId,
      secretAccessKey: creds.secretAccessKey,
      sessionToken: creds.sessionToken,
    },
  });
}

/**
 * Stream an invocation and yield raw SSE data lines (as already-parsed JSON).
 * The caller handles frame parsing in useAgentStream.
 */
export async function* streamInvocation(
  payload: InvokePayload,
  signal: AbortSignal,
): AsyncGenerator<string, void, unknown> {
  if (isDev) {
    // Dev: plain fetch via Vite proxy
    const response = await fetch("/api/invocations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    const reader = response.body?.getReader();
    if (!reader) throw new Error("No response body");
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      yield decoder.decode(value, { stream: true });
    }
    return;
  }

  // Prod: AWS SDK with Cognito basic flow creds
  const client = await getClient();
  const command = new InvokeAgentRuntimeCommand({
    agentRuntimeArn: agentCoreRuntimeArn,
    payload: new TextEncoder().encode(JSON.stringify(payload)),
    qualifier: "DEFAULT",
  });

  const response = await client.send(command, { abortSignal: signal });
  const body = response.response;
  if (!body) return;

  const decoder = new TextDecoder();
  // The response body from InvokeAgentRuntime is a Uint8Array async iterable
  const reader =
    (body as unknown as { transformToWebStream?: () => ReadableStream })
      .transformToWebStream?.() ?? null;

  if (reader) {
    const r = reader.getReader();
    while (true) {
      const { done, value } = await r.read();
      if (done) break;
      if (value) yield decoder.decode(value, { stream: true });
    }
    return;
  }

  // Fallback: SdkStream with transformToByteArray
  const bytes = await (
    body as unknown as { transformToByteArray?: () => Promise<Uint8Array> }
  ).transformToByteArray?.();
  if (bytes) {
    yield decoder.decode(bytes);
  }
}

/**
 * Fetch the user's watchlist directly from the backend.
 *
 * Uses the unified `/invocations` entrypoint with `action: "list_watchlist"`
 * so the same payload shape works in both dev (Vite proxy → localhost:8080)
 * and prod (InvokeAgentRuntimeCommand via Cognito + SigV4).
 *
 * The backend yields two SSE frames:
 *   data: {"event": "watchlist", "items": [...]}
 *   data: {"event": "complete"}
 */
export async function fetchWatchlist(): Promise<WatchlistItem[]> {
  const payload: InvokePayload = { action: "list_watchlist" };
  const controller = new AbortController();

  const events: Array<Record<string, unknown>> = [];
  for await (const chunk of streamInvocation(payload, controller.signal)) {
    events.push(...parseSseFrames(chunk));
  }

  const watchlistEvent = events.find((e) => e.event === "watchlist");
  if (!watchlistEvent) return [];

  const rawItems = (watchlistEvent.items ?? []) as WatchlistApiItem[];
  return rawItems.map((raw) => ({
    symbol: raw.symbol,
    category: raw.category as WatchlistItem["category"],
    price: raw.price,
    currency: raw.currency,
    changePct: raw.changePct,
    open: raw.open,
    high: raw.high,
    low: raw.low,
    volume: raw.volume,
    sparkline: raw.sparkline,
  }));
}

/**
 * Fetch recent briefings from the backend.
 */
export async function fetchBriefings(): Promise<
  Array<{
    date: string;
    timeOfDay: "AM" | "PM";
    status: string;
    tickersCovered: string[];
    content: string;
  }>
> {
  const payload: InvokePayload = { action: "list_briefings" };
  const controller = new AbortController();

  const events: Array<Record<string, unknown>> = [];
  for await (const chunk of streamInvocation(payload, controller.signal)) {
    events.push(...parseSseFrames(chunk));
  }

  const briefingsEvent = events.find((e) => e.event === "briefings");
  if (!briefingsEvent) return [];

  const rawItems = (briefingsEvent.items ?? []) as Array<Record<string, unknown>>;
  return rawItems.map((raw) => ({
    date: (raw.date as string) ?? "",
    timeOfDay: (raw.time_of_day as "AM" | "PM") ?? "AM",
    status: (raw.status as string) ?? "",
    tickersCovered: (raw.tickers_covered as string[]) ?? [],
    content: (raw.content as string) ?? "",
  }));
}
