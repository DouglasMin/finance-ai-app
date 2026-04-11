import type { ReactNode } from "react";

interface TerminalFrameProps {
  left: ReactNode;
  middle: ReactNode;
  right: ReactNode;
}

function TerminalFrame({ left, middle, right }: TerminalFrameProps) {
  const now = new Date().toISOString().replace("T", " ").slice(0, 19);

  return (
    <div className="h-screen flex flex-col font-mono bg-bg text-fg-dim">
      {/* top bar */}
      <div className="bg-fg text-bg px-4 py-1 flex justify-between items-center text-[11px] font-bold uppercase tracking-[0.15em]">
        <span>FINBOT v0.1 · PHASE 1</span>
        <span>{now} · ONLINE</span>
      </div>

      {/* 3-pane layout */}
      <div className="flex-1 grid grid-cols-[220px_300px_1fr] overflow-hidden">
        <div className="border-r border-border overflow-y-auto">{left}</div>
        <div className="border-r border-border overflow-y-auto">{middle}</div>
        <div className="overflow-hidden flex flex-col">{right}</div>
      </div>

      {/* bottom bar */}
      <div className="bg-bg-alt border-t border-border px-4 py-1 flex justify-between text-[10px] text-muted">
        <span>-- FINANCIAL AGENT TERMINAL --</span>
        <span>[F1] help · [F2] sessions · [F3] watchlist</span>
      </div>
    </div>
  );
}

export default TerminalFrame;
