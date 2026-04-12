import type { BriefingSummary, Session } from "../../types";

interface SessionsPanelProps {
  sessions: Session[];
  activeSessionId: string | null;
  briefings: BriefingSummary[];
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onDeleteSession: (id: string) => void;
  onClearAllSessions: () => void;
  onOpenBriefing: (b: BriefingSummary) => void;
}

function SessionsPanel({
  sessions,
  activeSessionId,
  briefings,
  onSelectSession,
  onNewSession,
  onDeleteSession,
  onClearAllSessions,
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
        <div className="flex items-center justify-between border-b border-border-dim pb-1 mb-1">
          <div className="text-[10px] text-muted uppercase tracking-widest">
            ── sessions ──
          </div>
          {sessions.length > 0 && (
            <button
              type="button"
              onClick={onClearAllSessions}
              className="text-[9px] text-muted hover:text-down cursor-pointer"
            >
              clear all
            </button>
          )}
        </div>
        <div className="flex flex-col gap-0.5 mt-1">
          {sessions.length === 0 ? (
            <div className="text-[11px] text-muted italic px-1 py-1">
              no sessions
            </div>
          ) : (
            sessions.map((s) => (
              <div
                key={s.id}
                className={`flex items-center group ${
                  activeSessionId === s.id
                    ? "bg-fg text-bg"
                    : "text-fg-dim hover:bg-bg-alt"
                }`}
              >
                <button
                  type="button"
                  onClick={() => onSelectSession(s.id)}
                  className={`flex-1 text-left px-2 py-1 text-[11px] truncate cursor-pointer ${
                    activeSessionId === s.id ? "font-bold" : ""
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
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteSession(s.id);
                  }}
                  className={`px-1 text-[9px] opacity-0 group-hover:opacity-100 cursor-pointer ${
                    activeSessionId === s.id
                      ? "text-bg hover:text-down"
                      : "text-muted hover:text-down"
                  }`}
                >
                  ✕
                </button>
              </div>
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
