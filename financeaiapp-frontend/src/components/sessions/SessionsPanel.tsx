import type { BriefingSummary, Session } from "../../types";

interface SessionsPanelProps {
  sessions: Session[];
  activeSessionId: string | null;
  briefings: BriefingSummary[];
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onOpenBriefing: (b: BriefingSummary) => void;
}

function SessionsPanel({
  sessions,
  activeSessionId,
  briefings,
  onSelectSession,
  onNewSession,
  onOpenBriefing,
}: SessionsPanelProps) {
  return (
    <div className="p-3 flex flex-col gap-3">
      <button
        type="button"
        onClick={onNewSession}
        className="w-full bg-fg text-bg py-1.5 text-[11px] font-bold uppercase tracking-wider hover:bg-fg/80 cursor-pointer"
      >
        + new session
      </button>

      <div>
        <div className="text-[10px] text-muted uppercase tracking-widest mb-1 border-b border-border-dim pb-1">
          ── sessions ──
        </div>
        <div className="flex flex-col gap-0.5 mt-1">
          {sessions.length === 0 ? (
            <div className="text-[11px] text-muted italic px-1 py-1">
              no sessions
            </div>
          ) : (
            sessions.map((s) => (
              <button
                type="button"
                key={s.id}
                onClick={() => onSelectSession(s.id)}
                className={`text-left px-2 py-1 text-[11px] truncate cursor-pointer ${
                  activeSessionId === s.id
                    ? "bg-fg text-bg font-bold"
                    : "text-fg-dim hover:bg-bg-alt"
                }`}
              >
                <span>{s.title || "untitled"}</span>
                <span
                  className={`ml-1 text-[9px] ${
                    activeSessionId === s.id ? "text-bg" : "text-muted"
                  }`}
                >
                  ({s.messageCount})
                </span>
              </button>
            ))
          )}
        </div>
      </div>

      <div>
        <div className="text-[10px] text-muted uppercase tracking-widest mb-1 border-b border-border-dim pb-1">
          ── briefings ──
        </div>
        <div className="flex flex-col gap-0.5 mt-1">
          {briefings.length === 0 ? (
            <div className="text-[11px] text-muted italic px-1 py-1">
              no briefings
            </div>
          ) : (
            briefings.map((b) => (
              <button
                type="button"
                key={`${b.date}-${b.timeOfDay}`}
                onClick={() => onOpenBriefing(b)}
                className="text-left px-2 py-1 text-[11px] text-fg-dim hover:bg-bg-alt flex justify-between cursor-pointer"
              >
                <span>
                  {b.date} {b.timeOfDay}
                </span>
                <span
                  className={`text-[9px] ${
                    b.status === "success"
                      ? "text-up"
                      : b.status === "failed"
                      ? "text-down"
                      : "text-muted"
                  }`}
                >
                  {b.status}
                </span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

export default SessionsPanel;
