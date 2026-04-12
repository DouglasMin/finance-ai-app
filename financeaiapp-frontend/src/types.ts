export type StreamEventType =
  | "session_start"
  | "tool_call"
  | "tool_result"
  | "news_links"
  | "assistant"
  | "complete"
  | "error"
  | "unknown";

export interface StreamEvent {
  type: StreamEventType;
  data: Record<string, unknown>;
  timestamp: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  toolCalls?: ToolCall[];
}

export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result?: string;
  status: "running" | "done" | "error";
}

export interface Session {
  id: string;
  title: string;
  createdAt: number;
  messageCount: number;
  messages: ChatMessage[];
}

export interface WatchlistItem {
  symbol: string;
  category: "crypto" | "us_stock" | "kr_stock" | "fx";
  price?: number;
  currency?: string;
  changePct?: number;
  open?: number;
  high?: number;
  low?: number;
  volume?: number;
  sparkline?: number[];
}

export interface BriefingSummary {
  date: string;
  timeOfDay: "AM" | "PM";
  status: "pending" | "in_progress" | "partial" | "success" | "failed";
  tickersCovered: string[];
}
