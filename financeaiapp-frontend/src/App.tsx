import { useCallback, useEffect, useMemo, useState } from "react";
import TerminalFrame from "./components/layout/TerminalFrame";
import SessionsPanel from "./components/sessions/SessionsPanel";
import WatchlistPanel from "./components/watchlist/WatchlistPanel";
import ChatPanel from "./components/chat/ChatPanel";
import { useAgentStream } from "./hooks/useAgentStream";
import type {
  BriefingSummary,
  ChatMessage,
  Session,
  StreamEvent,
  WatchlistItem,
} from "./types";

const LS_SESSIONS_KEY = "finbot.sessions.v1";
const LS_WATCHLIST_KEY = "finbot.watchlist.v1";

function loadSessions(): Session[] {
  try {
    const raw = localStorage.getItem(LS_SESSIONS_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as Session[];
  } catch {
    return [];
  }
}

function saveSessions(sessions: Session[]): void {
  localStorage.setItem(LS_SESSIONS_KEY, JSON.stringify(sessions));
}

function loadWatchlist(): WatchlistItem[] {
  try {
    const raw = localStorage.getItem(LS_WATCHLIST_KEY);
    if (!raw)
      return [
        {
          symbol: "BTC",
          category: "crypto",
          price: 72761.3,
          currency: "USD",
          changePct: 1.39,
          sparkline: [70000, 70500, 71200, 71800, 72300, 72500, 72761],
        },
        {
          symbol: "005930",
          category: "kr_stock",
          price: 73200,
          currency: "KRW",
          changePct: 0.41,
          sparkline: [72500, 72600, 72800, 73000, 72900, 73100, 73200],
        },
        {
          symbol: "USD/KRW",
          category: "fx",
          price: 1483.27,
          currency: "KRW",
          changePct: -0.12,
          sparkline: [1485, 1486, 1484, 1485, 1483, 1484, 1483],
        },
      ];
    return JSON.parse(raw) as WatchlistItem[];
  } catch {
    return [];
  }
}

function saveWatchlist(items: WatchlistItem[]): void {
  localStorage.setItem(LS_WATCHLIST_KEY, JSON.stringify(items));
}

function newSessionId(): string {
  return `sess-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

function extractAssistantMessageFromEvents(
  events: StreamEvent[],
): ChatMessage | null {
  const assistantEvents = events.filter((e) => e.type === "assistant");
  const toolCalls = events.filter((e) => e.type === "tool_call");
  const toolResults = events.filter((e) => e.type === "tool_result");

  if (!assistantEvents.length && !toolCalls.length) return null;

  const content =
    assistantEvents.length > 0
      ? String(
          (assistantEvents[assistantEvents.length - 1].data as Record<string, unknown>)
            .content ?? "",
        )
      : "";

  const finalToolCalls = toolCalls.map((tc) => {
    const data = tc.data as Record<string, unknown>;
    const name = String(data.tool ?? "?");
    const args = (data.args as Record<string, unknown>) ?? {};
    const result = toolResults.find((tr) => {
      const rd = tr.data as Record<string, unknown>;
      return String(rd.tool ?? "") === name;
    });
    return {
      name,
      args,
      result: result
        ? String((result.data as Record<string, unknown>).content ?? "")
        : undefined,
      status: (result ? "done" : "running") as "running" | "done",
    };
  });

  return {
    id: `asst-${Date.now()}`,
    role: "assistant",
    content,
    timestamp: Date.now(),
    toolCalls: finalToolCalls.length > 0 ? finalToolCalls : undefined,
  };
}

function App() {
  const [sessions, setSessions] = useState<Session[]>(loadSessions);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(() => {
    const loaded = loadSessions();
    return loaded.length > 0 ? loaded[0].id : null;
  });
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>(loadWatchlist);
  const [briefings] = useState<BriefingSummary[]>([]);

  const { events, isStreaming, error, sendMessage, reset } = useAgentStream();

  const activeSession = useMemo(
    () => sessions.find((s) => s.id === activeSessionId) ?? null,
    [sessions, activeSessionId],
  );

  // Persist
  useEffect(() => {
    saveSessions(sessions);
  }, [sessions]);

  useEffect(() => {
    saveWatchlist(watchlist);
  }, [watchlist]);

  const handleNewSession = useCallback(() => {
    const id = newSessionId();
    const now = Date.now();
    const session: Session = {
      id,
      title: "새 대화",
      createdAt: now,
      messageCount: 0,
      messages: [],
    };
    setSessions((prev) => [session, ...prev]);
    setActiveSessionId(id);
    reset();
  }, [reset]);

  const handleSelectSession = useCallback(
    (id: string) => {
      setActiveSessionId(id);
      reset();
    },
    [reset],
  );

  const handleSend = useCallback(
    async (message: string) => {
      if (!activeSession) return;

      // Append user message immediately
      const userMsg: ChatMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        content: message,
        timestamp: Date.now(),
      };
      setSessions((prev) =>
        prev.map((s) =>
          s.id === activeSession.id
            ? {
                ...s,
                messages: [...s.messages, userMsg],
                messageCount: s.messageCount + 1,
                title:
                  s.messages.length === 0 ? message.slice(0, 40) : s.title,
              }
            : s,
        ),
      );

      await sendMessage(activeSession.id, message);
    },
    [activeSession, sendMessage],
  );

  // When streaming completes, commit the assistant message to the session
  useEffect(() => {
    if (!isStreaming && events.length > 0 && activeSession) {
      const hasComplete = events.some((e) => e.type === "complete");
      if (hasComplete) {
        const asstMsg = extractAssistantMessageFromEvents(events);
        if (asstMsg) {
          setSessions((prev) =>
            prev.map((s) =>
              s.id === activeSession.id
                ? {
                    ...s,
                    messages: [...s.messages, asstMsg],
                    messageCount: s.messageCount + 1,
                  }
                : s,
            ),
          );
        }
        reset();
      }
    }
  }, [isStreaming, events, activeSession, reset]);

  const handleAddWatchlist = useCallback(() => {
    const symbol = prompt("종목 심볼을 입력하세요 (예: BTC, AAPL, 005930)");
    if (!symbol) return;
    const s = symbol.trim().toUpperCase();
    const category: WatchlistItem["category"] = s.includes("/")
      ? "fx"
      : /^\d{6}$/.test(s)
      ? "kr_stock"
      : ["BTC", "ETH", "SOL", "XRP", "DOGE"].includes(s)
      ? "crypto"
      : "us_stock";
    setWatchlist((prev) => [...prev, { symbol: s, category }]);
  }, []);

  const handleRemoveWatchlist = useCallback((symbol: string) => {
    setWatchlist((prev) => prev.filter((i) => i.symbol !== symbol));
  }, []);

  const handleRefreshWatchlist = useCallback(() => {
    // TODO: call research tool for each ticker once backend is deployed
  }, []);

  const handleOpenBriefing = useCallback((_b: BriefingSummary) => {
    // TODO: open briefing reader modal
  }, []);

  return (
    <TerminalFrame
      left={
        <SessionsPanel
          sessions={sessions}
          activeSessionId={activeSessionId}
          briefings={briefings}
          onSelectSession={handleSelectSession}
          onNewSession={handleNewSession}
          onOpenBriefing={handleOpenBriefing}
        />
      }
      middle={
        <WatchlistPanel
          items={watchlist}
          isRefreshing={false}
          onRefresh={handleRefreshWatchlist}
          onAdd={handleAddWatchlist}
          onRemove={handleRemoveWatchlist}
        />
      }
      right={
        <ChatPanel
          session={activeSession}
          events={events}
          isStreaming={isStreaming}
          error={error}
          onSend={handleSend}
        />
      }
    />
  );
}

export default App;
