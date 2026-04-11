import type { WatchlistItem } from "../../types";

interface WatchlistPanelProps {
  items: WatchlistItem[];
  onRefresh: () => void;
  onAdd: () => void;
  onRemove: (symbol: string) => void;
  isRefreshing: boolean;
}

function formatPrice(item: WatchlistItem): string {
  if (item.price == null) return "--";
  const prefix =
    item.currency === "USD" ? "$" : item.currency === "KRW" ? "₩" : "";
  if (item.currency === "KRW") {
    return `${prefix}${Math.round(item.price).toLocaleString()}`;
  }
  return `${prefix}${item.price.toLocaleString(undefined, {
    maximumFractionDigits: 2,
  })}`;
}

function Sparkline({ data, up }: { data: number[]; up: boolean }) {
  if (!data.length) {
    return <div className="h-5 text-[9px] text-muted">-- no data --</div>;
  }
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * 100;
      const y = 100 - ((v - min) / range) * 100;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      className="w-full h-5"
    >
      <polyline
        points={points}
        fill="none"
        stroke={up ? "#39ff14" : "#ff4444"}
        strokeWidth="2"
      />
    </svg>
  );
}

function WatchlistPanel({
  items,
  onRefresh,
  onAdd,
  onRemove,
  isRefreshing,
}: WatchlistPanelProps) {
  return (
    <div className="p-3 flex flex-col gap-2">
      <div className="flex items-center justify-between border-b border-border-dim pb-1">
        <div className="text-[10px] text-muted uppercase tracking-widest">
          ── watchlist ──
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={isRefreshing}
          className="text-[10px] text-fg hover:text-up disabled:text-muted cursor-pointer"
        >
          {isRefreshing ? "..." : "↻"}
        </button>
      </div>

      {items.length === 0 ? (
        <div className="text-[11px] text-muted italic py-2">
          no watchlist items
        </div>
      ) : (
        <div className="flex flex-col gap-1">
          {items.map((item) => {
            const isUp = (item.changePct ?? 0) >= 0;
            return (
              <div
                key={item.symbol}
                className="border border-border-dim hover:border-border p-2 group"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[12px] text-fg font-bold">
                    {item.symbol}
                  </span>
                  <span
                    className={`text-[11px] font-data ${
                      item.changePct == null
                        ? "text-muted"
                        : isUp
                        ? "text-up"
                        : "text-down"
                    }`}
                  >
                    {item.changePct == null
                      ? "--"
                      : `${isUp ? "+" : ""}${item.changePct.toFixed(2)}%`}
                  </span>
                </div>
                <div className="flex items-center justify-between mt-0.5">
                  <span className="text-[10px] text-muted uppercase">
                    {item.category}
                  </span>
                  <span className="text-[11px] font-data text-fg-dim">
                    {formatPrice(item)}
                  </span>
                </div>
                <div className="mt-1">
                  <Sparkline data={item.sparkline ?? []} up={isUp} />
                </div>
                <button
                  type="button"
                  onClick={() => onRemove(item.symbol)}
                  className="text-[9px] text-muted hover:text-down opacity-0 group-hover:opacity-100 cursor-pointer"
                >
                  [x] remove
                </button>
              </div>
            );
          })}
        </div>
      )}

      <button
        type="button"
        onClick={onAdd}
        className="mt-1 py-1 text-[10px] text-muted border border-border-dim hover:border-fg hover:text-fg cursor-pointer"
      >
        [ + add symbol ]
      </button>
    </div>
  );
}

export default WatchlistPanel;
