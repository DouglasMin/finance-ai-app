import type { ChatMessage } from "../../types";
import ToolCallChip from "./ToolCallChip";

interface MessageBubbleProps {
  message: ChatMessage;
  isStreaming?: boolean;
}

function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const label = isUser ? "YOU" : "AGENT";
  const labelColor = isUser ? "text-user" : "text-assistant";

  return (
    <div className="animate-fade-in mb-3">
      <div className="flex items-baseline gap-2 mb-0.5">
        <span className={`text-[10px] font-bold ${labelColor}`}>
          [{label}]
        </span>
        <span className="text-[9px] text-muted">
          {new Date(message.timestamp).toTimeString().slice(0, 8)}
        </span>
      </div>
      <div className="pl-3 border-l-2 border-border-dim">
        {message.toolCalls?.map((tc, i) => (
          <ToolCallChip key={i} toolCall={tc} />
        ))}
        {message.content && (
          <div
            className={`text-[13px] whitespace-pre-wrap break-words ${
              isUser ? "text-fg" : "text-fg-dim"
            } ${isStreaming ? "cursor-blink" : ""}`}
            style={{ overflowWrap: "anywhere" }}
          >
            {message.content}
          </div>
        )}
      </div>
    </div>
  );
}

export default MessageBubble;
