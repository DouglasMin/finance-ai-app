import type { ToolCall } from "../../types";

interface ToolCallChipProps {
  toolCall: ToolCall;
}

function ToolCallChip({ toolCall }: ToolCallChipProps) {
  const statusColor =
    toolCall.status === "running"
      ? "text-fg animate-pulse"
      : toolCall.status === "done"
      ? "text-up"
      : "text-down";

  const argsPreview = JSON.stringify(toolCall.args).slice(0, 80);

  return (
    <div className="my-1 text-[11px] font-data border-l-2 border-fg/40 pl-2 py-0.5">
      <div className="flex items-center gap-2">
        <span className={statusColor}>▸</span>
        <span className="text-fg font-bold">{toolCall.name}</span>
        <span className="text-muted">({argsPreview})</span>
      </div>
      {toolCall.result && (
        <div className="text-muted text-[10px] pl-3 mt-0.5 whitespace-pre-wrap break-words">
          {toolCall.result.slice(0, 200)}
          {toolCall.result.length > 200 && "..."}
        </div>
      )}
    </div>
  );
}

export default ToolCallChip;
