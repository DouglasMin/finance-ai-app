import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import type { ChatMessage, Session, StreamEvent, ToolCall } from "../../types";
import MessageBubble from "./MessageBubble";

interface ChatPanelProps {
  session: Session | null;
  events: StreamEvent[];
  isStreaming: boolean;
  error: string | null;
  onSend: (message: string) => void;
}

function eventsToMessages(
  baseMessages: ChatMessage[],
  events: StreamEvent[],
): ChatMessage[] {
  const messages = [...baseMessages];

  // Build/update the in-progress assistant message from events
  let current: ChatMessage | null = null;

  for (const ev of events) {
    const data = ev.data;
    if (ev.type === "session_start") {
      continue;
    }
    if (ev.type === "tool_call") {
      if (!current) {
        current = {
          id: `asst-${ev.timestamp}`,
          role: "assistant",
          content: "",
          timestamp: ev.timestamp,
          toolCalls: [],
        };
        messages.push(current);
      }
      const tool = String(data.tool ?? "?");
      const args = (data.args as Record<string, unknown>) ?? {};
      current.toolCalls = [
        ...(current.toolCalls ?? []),
        { name: tool, args, status: "running" } satisfies ToolCall,
      ];
    } else if (ev.type === "tool_result") {
      if (current?.toolCalls) {
        const tool = String(data.tool ?? "");
        const content = String(data.content ?? "");
        const last = [...current.toolCalls]
          .reverse()
          .find((tc) => tc.name === tool && tc.status === "running");
        if (last) {
          last.status = "done";
          last.result = content;
        }
      }
    } else if (ev.type === "assistant") {
      if (!current) {
        current = {
          id: `asst-${ev.timestamp}`,
          role: "assistant",
          content: "",
          timestamp: ev.timestamp,
          toolCalls: [],
        };
        messages.push(current);
      }
      const content = String(data.content ?? "");
      // Replace (not append) — each assistant event carries full content
      current = { ...current, content };
      messages[messages.length - 1] = current;
    } else if (ev.type === "error") {
      messages.push({
        id: `err-${ev.timestamp}`,
        role: "assistant",
        content: `ERROR: ${data.message ?? "unknown"}`,
        timestamp: ev.timestamp,
      });
      current = null;
    } else if (ev.type === "complete") {
      current = null;
    }
  }

  return messages;
}

function ChatPanel({
  session,
  events,
  isStreaming,
  error,
  onSend,
}: ChatPanelProps) {
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const messages = useMemo(
    () => eventsToMessages(session?.messages ?? [], events),
    [session?.messages, events],
  );

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages.length, events.length]);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming || !session) return;
    onSend(trimmed);
    setInput("");
  };

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="h-full flex flex-col">
      {/* header */}
      <div className="border-b border-border px-4 py-2 flex items-center justify-between">
        <div className="text-[11px] text-fg uppercase tracking-wider">
          {session ? session.title : "[no session]"}
        </div>
        <div className="text-[10px] text-muted">
          {session ? `${messages.length} msgs` : ""}
          {isStreaming ? " · streaming..." : ""}
        </div>
      </div>

      {/* messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4">
        {!session ? (
          <div className="text-[12px] text-muted italic text-center mt-8">
            -- select a session or create a new one --
          </div>
        ) : messages.length === 0 ? (
          <div className="text-[12px] text-muted italic text-center mt-8">
            -- start typing below --
          </div>
        ) : (
          messages.map((m) => (
            <MessageBubble
              key={m.id}
              message={m}
              isStreaming={isStreaming && m.role === "assistant"}
            />
          ))
        )}

        {error && (
          <div className="text-[11px] text-down border border-down/40 p-2 mt-2">
            ERROR: {error}
          </div>
        )}
      </div>

      {/* input */}
      <div className="border-t border-border p-2 flex gap-2 items-start">
        <span className="text-fg text-[13px] pt-1.5 font-bold">{">"}</span>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKey}
          disabled={!session || isStreaming}
          placeholder={
            session ? "ask about markets..." : "no session selected"
          }
          rows={2}
          className="flex-1 bg-transparent border border-border focus:border-fg outline-none text-[12px] text-fg-dim font-mono p-2 resize-none placeholder:text-muted disabled:opacity-50"
        />
        <button
          type="button"
          onClick={handleSend}
          disabled={!input.trim() || isStreaming || !session}
          className="bg-fg text-bg px-3 py-1.5 text-[10px] font-bold uppercase disabled:opacity-30 hover:bg-fg/80 cursor-pointer"
        >
          SEND
        </button>
      </div>
    </div>
  );
}

export default ChatPanel;
