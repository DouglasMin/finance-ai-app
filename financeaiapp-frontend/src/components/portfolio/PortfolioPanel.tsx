import { useCallback, useEffect, useState } from "react";
import {
  executeTrade,
  fetchOrders,
  fetchPortfolio,
  initPortfolio,
} from "../../api/agentcore";
import type { OrderData, PortfolioData, PositionData } from "../../types";

function formatPrice(price: number, currency: string): string {
  if (currency === "KRW")
    return `₩${price.toLocaleString("en", { maximumFractionDigits: 0 })}`;
  if (price >= 1)
    return `$${price.toLocaleString("en", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  if (price >= 0.01) return `$${price.toFixed(4)}`;
  return `$${price.toFixed(8)}`;
}

// Hard-coded rate for display toggle — in production this should come from
// the backend's Frankfurter adapter, but for instant UI switching a cached
// rate is acceptable. Refreshed on each portfolio load.
let _cachedFxRate: number | null = null;

function convert(
  value: number,
  fromCurrency: string,
  toCurrency: string,
): number {
  if (fromCurrency === toCurrency) return value;
  if (!_cachedFxRate) return value;
  if (fromCurrency === "USD" && toCurrency === "KRW")
    return value * _cachedFxRate;
  if (fromCurrency === "KRW" && toCurrency === "USD")
    return value / _cachedFxRate;
  return value;
}

function PortfolioPanel() {
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null);
  const [positions, setPositions] = useState<PositionData[]>([]);
  const [orders, setOrders] = useState<OrderData[]>([]);
  const [loading, setLoading] = useState(false);
  const [showOrders, setShowOrders] = useState(false);
  const [displayCurrency, setDisplayCurrency] = useState<"USD" | "KRW">("USD");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const { portfolio: pf, positions: pos } = await fetchPortfolio();
      setPortfolio(pf);
      setPositions(pos);
      if (pf) setDisplayCurrency(pf.currency as "USD" | "KRW");
    } catch (err) {
      console.error("portfolio fetch failed:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch FX rate on mount for display conversion
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(
          "https://api.frankfurter.dev/v1/latest?base=USD&symbols=KRW",
        );
        const data = await r.json();
        _cachedFxRate = data?.rates?.KRW ?? null;
      } catch {
        _cachedFxRate = null;
      }
    })();
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleInit = useCallback(async () => {
    const input = prompt("초기 자금을 입력하세요 (예: 10000)");
    if (!input) return;
    const capital = parseFloat(input);
    if (isNaN(capital) || capital <= 0) {
      alert("올바른 금액을 입력하세요.");
      return;
    }
    const cur = confirm("USD로 생성합니다. KRW로 하려면 '취소'를 누르세요.")
      ? "USD"
      : "KRW";
    try {
      await initPortfolio(capital, cur);
      await refresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : "초기화 실패");
    }
  }, [refresh]);

  const handleBuy = useCallback(async () => {
    const symbol = prompt("매수할 종목 심볼 (예: BTC, AAPL)");
    if (!symbol) return;
    const qtyStr = prompt("매수 수량");
    if (qtyStr === null) return;
    const qty = parseFloat(qtyStr);
    if (isNaN(qty) || qty <= 0) {
      alert("올바른 수량을 입력하세요.");
      return;
    }
    try {
      const result = await executeTrade(
        "direct_buy",
        symbol.trim().toUpperCase(),
        qty,
      );
      alert(result);
      await refresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : "매수 실패");
    }
  }, [refresh]);

  const handleSell = useCallback(
    async (symbol: string, maxQty: number) => {
      const qtyStr = prompt(
        `${symbol} 매도 수량 (보유: ${maxQty.toLocaleString("en", { maximumFractionDigits: 6 })}, 전량 매도는 0)`,
        "0",
      );
      if (qtyStr === null) return;
      const qty = parseFloat(qtyStr);
      if (isNaN(qty) || qty < 0) {
        alert("올바른 수량을 입력하세요.");
        return;
      }
      try {
        const result = await executeTrade("direct_sell", symbol, qty);
        alert(result);
        await refresh();
      } catch (err) {
        alert(err instanceof Error ? err.message : "매도 실패");
      }
    },
    [refresh],
  );

  const handleToggleOrders = useCallback(async () => {
    if (showOrders) {
      setShowOrders(false);
      setOrders([]);
      return;
    }
    try {
      const items = await fetchOrders(20);
      setOrders(items);
      setShowOrders(true);
    } catch (err) {
      alert(err instanceof Error ? err.message : "주문 내역 로딩 실패");
    }
  }, [showOrders]);

  /** Display a value in the selected display currency */
  const dp = (value: number, fromCurrency?: string) => {
    const from = fromCurrency ?? portfolio?.currency ?? "USD";
    const converted = convert(value, from, displayCurrency);
    return formatPrice(converted, displayCurrency);
  };

  // No portfolio yet
  if (!portfolio) {
    return (
      <div className="p-3 flex flex-col items-center justify-center gap-3 h-full">
        <div className="text-muted text-[11px] text-center">
          가상 포트폴리오가 없습니다
        </div>
        <button
          type="button"
          onClick={handleInit}
          className="text-[11px] px-3 py-1 bg-fg text-bg rounded cursor-pointer hover:opacity-80"
        >
          + 포트폴리오 생성
        </button>
      </div>
    );
  }

  const pnl = portfolio.realized_pnl;
  const pnlColor = pnl >= 0 ? "text-up" : "text-down";

  return (
    <div className="p-3 flex flex-col gap-2 text-[11px]">
      {/* Header + currency toggle */}
      <div className="flex justify-between items-center">
        <span className="text-[10px] text-muted uppercase tracking-widest">
          ── portfolio ──
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() =>
              setDisplayCurrency((c) => (c === "USD" ? "KRW" : "USD"))
            }
            className="text-[9px] text-muted hover:text-fg cursor-pointer border border-border-dim rounded px-1.5 py-0.5"
          >
            {displayCurrency === "USD" ? "$ USD" : "₩ KRW"}
          </button>
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            aria-label="포트폴리오 새로고침"
            className="text-[10px] text-fg hover:text-up cursor-pointer disabled:opacity-50"
          >
            {loading ? "..." : "↻"}
          </button>
        </div>
      </div>

      {/* Balance card */}
      <div className="border border-border-dim rounded px-2 py-1.5 space-y-0.5">
        <div className="flex justify-between">
          <span className="text-muted">현금</span>
          <span className="text-fg">{dp(portfolio.cash_balance)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted">실현 PnL</span>
          <span className={pnlColor}>{dp(pnl)}</span>
        </div>
      </div>

      {/* Buy button */}
      <button
        type="button"
        onClick={handleBuy}
        className="w-full text-[10px] py-1 bg-up/20 text-up rounded cursor-pointer hover:bg-up/30"
      >
        + 매수
      </button>

      {/* Positions */}
      <div className="text-[10px] text-muted uppercase tracking-widest mt-1">
        보유 종목 ({positions.length})
      </div>
      {positions.length === 0 ? (
        <div className="text-muted text-[11px] italic">보유 종목 없음</div>
      ) : (
        <div className="flex flex-col gap-0.5">
          {positions.map((pos) => (
            <div
              key={pos.symbol}
              className="flex justify-between items-center px-1 py-0.5 hover:bg-bg-alt rounded group"
            >
              <div>
                <span className="text-fg font-bold">{pos.symbol}</span>
                <span className="text-muted ml-1">
                  {pos.quantity.toLocaleString("en", {
                    maximumFractionDigits: 4,
                  })}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] text-muted">
                  avg {dp(pos.avg_cost, pos.currency)}
                </span>
                <button
                  type="button"
                  onClick={() => handleSell(pos.symbol, pos.quantity)}
                  className="text-[9px] text-down opacity-0 group-hover:opacity-100 hover:bg-down/20 px-1.5 py-0.5 rounded cursor-pointer transition-opacity"
                >
                  매도
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Orders toggle */}
      <button
        type="button"
        onClick={handleToggleOrders}
        className="text-[10px] text-muted hover:text-fg cursor-pointer mt-1 text-left"
      >
        {showOrders ? "▾ 주문 내역 접기" : "▸ 주문 내역 보기"}
      </button>
      {showOrders && (
        <div className="flex flex-col gap-0.5 max-h-[150px] overflow-y-auto">
          {orders.length === 0 ? (
            <div className="text-muted italic">주문 없음</div>
          ) : (
            orders.map((o) => (
              <div
                key={o.order_id}
                className="flex justify-between text-[10px] px-1"
              >
                <span>
                  <span className={o.side === "buy" ? "text-up" : "text-down"}>
                    {o.side === "buy" ? "매수" : "매도"}
                  </span>{" "}
                  {o.symbol}{" "}
                  {o.quantity.toLocaleString("en", {
                    maximumFractionDigits: 4,
                  })}
                </span>
                <span className="text-muted">
                  {dp(o.price, o.currency)}
                </span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

export default PortfolioPanel;
