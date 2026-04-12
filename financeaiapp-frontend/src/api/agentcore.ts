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
import { fromCognitoIdentityPool } from "@aws-sdk/credential-providers";

import {
  agentCoreRuntimeArn,
  awsRegion,
  identityPoolId,
  isDev,
} from "../env";
import type { WatchlistItem } from "../types";

export interface InvokePayload {
  action: "chat" | "briefing" | "list_watchlist";
  session_id?: string;
  message?: string;
  time_of_day?: "AM" | "PM";
  correlation_id?: string;
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

let _client: BedrockAgentCoreClient | null = null;

function getClient(): BedrockAgentCoreClient {
  if (_client) return _client;
  _client = new BedrockAgentCoreClient({
    region: awsRegion,
    credentials: fromCognitoIdentityPool({
      clientConfig: { region: awsRegion },
      identityPoolId,
    }),
  });
  return _client;
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

  // Prod: AWS SDK with Cognito creds
  const client = getClient();
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
