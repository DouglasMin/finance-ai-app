import { useCallback, useRef, useState } from "react";
import type { StreamEvent, StreamEventType } from "../types";

interface UseAgentStreamResult {
  events: StreamEvent[];
  isStreaming: boolean;
  error: string | null;
  sendMessage: (sessionId: string, message: string) => Promise<void>;
  reset: () => void;
}

const KNOWN_EVENT_TYPES: readonly StreamEventType[] = [
  "session_start",
  "tool_call",
  "tool_result",
  "assistant",
  "complete",
  "error",
];

function coerceEventType(raw: unknown): StreamEventType {
  if (typeof raw === "string" && (KNOWN_EVENT_TYPES as readonly string[]).includes(raw)) {
    return raw as StreamEventType;
  }
  return "unknown";
}

export function useAgentStream(): UseAgentStreamResult {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setEvents([]);
    setIsStreaming(false);
    setError(null);
  }, []);

  const sendMessage = useCallback(
    async (sessionId: string, message: string): Promise<void> => {
      setError(null);
      setIsStreaming(true);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const response = await fetch("/api/invocations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "chat",
            session_id: sessionId,
            message,
            correlation_id: crypto.randomUUID(),
          }),
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const reader = response.body?.getReader();
        if (!reader) throw new Error("No response body");
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";

          for (const frame of frames) {
            const line = frame.trim();
            if (!line.startsWith("data: ")) continue;
            const rawJson = line.slice(6);

            try {
              let parsed: unknown = JSON.parse(rawJson);
              // AgentCore sometimes wraps strings — parse twice if needed
              if (typeof parsed === "string") {
                try {
                  parsed = JSON.parse(parsed);
                } catch {
                  // plain text chunk
                  setEvents((prev) => [
                    ...prev,
                    {
                      type: "assistant",
                      data: { content: parsed },
                      timestamp: Date.now(),
                    },
                  ]);
                  continue;
                }
              }

              const obj = parsed as Record<string, unknown>;
              const evtType = coerceEventType(obj.event);
              setEvents((prev) => [
                ...prev,
                { type: evtType, data: obj, timestamp: Date.now() },
              ]);
            } catch {
              // ignore unparseable frame
            }
          }
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name !== "AbortError") {
          setError(err.message);
        }
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [],
  );

  return { events, isStreaming, error, sendMessage, reset };
}
