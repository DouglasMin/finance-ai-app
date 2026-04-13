import { useCallback, useEffect, useMemo, useState } from "react";
import TerminalFrame from "./components/layout/TerminalFrame";
import SessionsPanel from "./components/sessions/SessionsPanel";
import WatchlistPanel from "./components/watchlist/WatchlistPanel";
import ChatPanel from "./components/chat/ChatPanel";
import { fetchBriefings, fetchWatchlist } from "./api/agentcore";
import { useAgentStream } from "./hooks/useAgentStream";
import type {
  BriefingSummary,
  ChatMessage,
  Session,
  StreamEvent,
  WatchlistItem,
} from "./types";

const LS_SESSIONS_KEY = "finbot.sessions.v1";

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

function newSessionId(): string {
  return `sess-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

function formatNewsLinksMarkdown(
  items: Array<{ title: string; url: string }>,
): string {
  if (!items.length) return "";
  const cards = items
    .map((item) => `> [${item.title}](${item.url})`)
    .join("\n>\n");
  return `\n\n---\n**📰 관련 뉴스 원문**\n${cards}`;
}

function extractAssistantMessageFromEvents(
  events: StreamEvent[],
): ChatMessage | null {
  const assistantEvents = events.filter((e) => e.type === "assistant");
  const toolCalls = events.filter((e) => e.type === "tool_call");
  const toolResults = events.filter((e) => e.type === "tool_result");
  const newsLinksEvents = events.filter((e) => e.type === "news_links");

  if (!assistantEvents.length && !toolCalls.length) return null;

  let content =
    assistantEvents.length > 0
      ? String(
          (assistantEvents[assistantEvents.length - 1].data as Record<string, unknown>)
            .content ?? "",
        )
      : "";

  // Append news links from research tool results
  if (newsLinksEvents.length > 0) {
    const lastLinks = newsLinksEvents[newsLinksEvents.length - 1];
    const items = (lastLinks.data as Record<string, unknown>).items as Array<{
      title: string;
      url: string;
    }>;
    if (items?.length) {
      content += formatNewsLinksMarkdown(items);
    }
  }

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
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [isRefreshingWatchlist, setIsRefreshingWatchlist] = useState(false);
  const [briefings, setBriefings] = useState<BriefingSummary[]>([]);

  const { events, isStreaming, error, sendMessage, reset } = useAgentStream();

  const activeSession = useMemo(
    () => sessions.find((s) => s.id === activeSessionId) ?? null,
    [sessions, activeSessionId],
  );

  // Persist sessions locally
  useEffect(() => {
    saveSessions(sessions);
  }, [sessions]);

  // Load watchlist from backend (DDB) — single source of truth
  const refreshWatchlist = useCallback(async () => {
    setIsRefreshingWatchlist(true);
    try {
      const items = await fetchWatchlist();
      setWatchlist(items);
    } catch (err) {
      console.error("watchlist fetch failed:", err);
    } finally {
      setIsRefreshingWatchlist(false);
    }
  }, []);

  useEffect(() => {
    refreshWatchlist();
  }, [refreshWatchlist]);

  // Load briefings from backend (DDB)
  useEffect(() => {
    (async () => {
      try {
        const items = await fetchBriefings();
        setBriefings(
          items.map((b) => ({
            date: b.date,
            timeOfDay: b.timeOfDay,
            status: b.status as BriefingSummary["status"],
            tickersCovered: b.tickersCovered,
          })),
        );
      } catch (err) {
        console.error("briefings fetch failed:", err);
      }
    })();
  }, []);

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
  // and refresh the watchlist in case the agent added/removed items.
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
        const touchedWatchlist = events.some((e) => {
          if (e.type !== "tool_call") return false;
          const name = String(
            (e.data as Record<string, unknown>).tool ?? "",
          );
          return (
            name === "add_watchlist" ||
            name === "remove_watchlist" ||
            name === "list_watchlist"
          );
        });
        if (touchedWatchlist) {
          refreshWatchlist();
        }
        reset();
      }
    }
  }, [isStreaming, events, activeSession, reset, refreshWatchlist]);

  const handleAddWatchlist = useCallback(() => {
    const symbol = prompt("종목 심볼을 입력하세요 (예: BTC, AAPL, 005930)");
    if (!symbol) return;
    // Route the add through chat so the agent handles validation + DDB write,
    // then refreshWatchlist() on stream complete picks up the new item.
    if (activeSession) {
      handleSend(`${symbol.trim().toUpperCase()} 관심종목에 추가해줘`);
    }
  }, [activeSession]);

  const handleRemoveWatchlist = useCallback(
    (symbol: string) => {
      if (activeSession) {
        handleSend(`${symbol} 관심종목에서 제거해줘`);
      }
    },
    [activeSession],
  );

  const handleDeleteSession = useCallback(
    (id: string) => {
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (activeSessionId === id) {
        setActiveSessionId(null);
        reset();
      }
    },
    [activeSessionId, reset],
  );

  const handleClearAllSessions = useCallback(() => {
    setSessions([]);
    setActiveSessionId(null);
    reset();
  }, [reset]);

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
          onDeleteSession={handleDeleteSession}
          onClearAllSessions={handleClearAllSessions}
          onOpenBriefing={handleOpenBriefing}
        />
      }
      middle={
        <WatchlistPanel
          items={watchlist}
          isRefreshing={isRefreshingWatchlist}
          onRefresh={refreshWatchlist}
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
