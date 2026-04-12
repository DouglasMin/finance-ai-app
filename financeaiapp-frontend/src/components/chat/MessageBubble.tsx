import { useMemo } from "react";
import Markdown from "react-markdown";
import type { ChatMessage } from "../../types";
import ComparisonChart from "./ComparisonChart";
import ToolCallChip from "./ToolCallChip";

const CHART_REGEX = /\[CHART\]\n([\s\S]*?)\n\[\/CHART\]/g;

function extractCharts(content: string): {
  markdown: string;
  charts: Array<{ type: string; tickers: string[]; series: Array<{ symbol: string; currency: string; data: Array<{ time: string; value: number }> }> }>;
} {
  const charts: Array<ReturnType<typeof extractCharts>["charts"][0]> = [];
  const markdown = content.replace(CHART_REGEX, (_match, jsonStr) => {
    try {
      charts.push(JSON.parse(jsonStr));
    } catch {
      // ignore malformed chart data
    }
    return "";
  });
  return { markdown: markdown.trim(), charts };
}

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
        {message.content &&
          (isUser ? (
            <div
              className="text-[13px] whitespace-pre-wrap break-words text-fg"
              style={{ overflowWrap: "anywhere" }}
            >
              {message.content}
            </div>
          ) : (
            <AssistantContent content={message.content} isStreaming={isStreaming} />
          ))}
      </div>
    </div>
  );
}

function AssistantContent({
  content,
  isStreaming,
}: {
  content: string;
  isStreaming?: boolean;
}) {
  const { markdown, charts } = useMemo(() => extractCharts(content), [content]);

  return (
    <div
      className={`text-[13px] text-fg-dim markdown-body ${
        isStreaming ? "cursor-blink" : ""
      }`}
    >
      <Markdown
                components={{
                  a: ({ href, children }) => (
                    <a
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-up hover:underline"
                    >
                      {children}
                    </a>
                  ),
                  table: ({ children }) => (
                    <table className="border-collapse my-2 text-[12px] w-full">
                      {children}
                    </table>
                  ),
                  th: ({ children }) => (
                    <th className="border border-border-dim px-2 py-1 text-left text-fg font-bold bg-bg-alt">
                      {children}
                    </th>
                  ),
                  td: ({ children }) => (
                    <td className="border border-border-dim px-2 py-1 text-fg-dim">
                      {children}
                    </td>
                  ),
                  strong: ({ children }) => (
                    <strong className="text-fg font-bold">{children}</strong>
                  ),
                  h2: ({ children }) => (
                    <h2 className="text-[14px] text-fg font-bold mt-3 mb-1">
                      {children}
                    </h2>
                  ),
                  h3: ({ children }) => (
                    <h3 className="text-[13px] text-fg font-bold mt-2 mb-1">
                      {children}
                    </h3>
                  ),
                  ul: ({ children }) => (
                    <ul className="list-disc pl-4 my-1">{children}</ul>
                  ),
                  ol: ({ children }) => (
                    <ol className="list-decimal pl-4 my-1">{children}</ol>
                  ),
                  li: ({ children }) => (
                    <li className="mb-0.5">{children}</li>
                  ),
                  code: ({ children }) => (
                    <code className="bg-bg-alt text-up px-1 py-0.5 text-[12px] rounded">
                      {children}
                    </code>
                  ),
                  blockquote: ({ children }) => (
                    <blockquote className="border-l-2 border-up/40 pl-3 my-2 py-1 bg-bg-alt/30">
                      {children}
                    </blockquote>
                  ),
                  p: ({ children }) => (
                    <p className="mb-1.5">{children}</p>
                  ),
                }}
              >
                {markdown}
              </Markdown>
              {charts.map((chartData, idx) => (
                <ComparisonChart key={idx} data={chartData} />
              ))}
            </div>
          );
        }

export default MessageBubble;
