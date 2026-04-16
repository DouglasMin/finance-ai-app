import { useCallback, useEffect, useState } from "react";
import {
  executeTrade,
  fetchOrders,
  fetchPortfolio,
  initPortfolio,
} from "../../api/agentcore";
import type { OrderData, PortfolioData, PositionData } from "../../types";

function formatPrice(price: number, currency: string): string {
  if (currency === "KRW") return `₩${price.toLocaleString("en", { maximumFractionDigits: 0 })}`;
  if (price >= 1) return `$${price.toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (price >= 0.01) return `$${price.toFixed(4)}`;
  return `$${price.toFixed(8)}`;
}

function PortfolioPanel() {
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null);
  const [positions, setPositions] = useState<PositionData[]>([]);
  const [orders, setOrders] = useState<OrderData[]>([]);
  const [loading, setLoading] = useState(false);
  const [showTradeForm, setShowTradeForm] = useState(false);
  const [showOrders, setShowOrders] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const { portfolio: pf, positions: pos } = await fetchPortfolio();
      setPortfolio(pf);
      setPositions(pos);
    } catch (err) {
      console.error("portfolio fetch failed:", err);
    } finally {
      setLoading(false);
    }
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
    try {
      await initPortfolio(capital, "USD");
      await refresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : "초기화 실패");
    }
  }, [refresh]);

  const handleTrade = useCallback(
    async (side: "direct_buy" | "direct_sell") => {
      const symbol = prompt("종목 심볼 (예: BTC, AAPL)");
      if (!symbol) return;
      const qtyStr = prompt(
        side === "direct_buy" ? "매수 수량" : "매도 수량 (0 = 전량)"
      );
      if (qtyStr === null) return;
      const qty = parseFloat(qtyStr);
      if (isNaN(qty) || (side === "direct_buy" && qty <= 0)) {
        alert("올바른 수량을 입력하세요.");
        return;
      }
      try {
        const result = await executeTrade(side, symbol.trim().toUpperCase(), qty);
        alert(result);
        await refresh();
      } catch (err) {
        alert(err instanceof Error ? err.message : "매매 실패");
      }
    },
    [refresh]
  );

  const handleLoadOrders = useCallback(async () => {
    try {
      const items = await fetchOrders(20);
      setOrders(items);
      setShowOrders(true);
    } catch (err) {
      console.error("orders fetch failed:", err);
    }
  }, []);

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
      {/* Header */}
      <div className="flex justify-between items-center">
        <span className="text-[10px] text-muted uppercase tracking-widest">
          ── portfolio ──
        </span>
        <button
          type="button"
          onClick={refresh}
          disabled={loading}
          className="text-[9px] text-muted hover:text-fg cursor-pointer disabled:opacity-50"
        >
          {loading ? "..." : "↻"}
        </button>
      </div>

      {/* Balance card */}
      <div className="border border-border-dim rounded px-2 py-1.5 space-y-0.5">
        <div className="flex justify-between">
          <span className="text-muted">현금</span>
          <span className="text-fg">
            {formatPrice(portfolio.cash_balance, portfolio.currency)}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted">실현 PnL</span>
          <span className={pnlColor}>
            {formatPrice(pnl, portfolio.currency)}
          </span>
        </div>
      </div>

      {/* Trade buttons */}
      <div className="flex gap-1">
        <button
          type="button"
          onClick={() => handleTrade("direct_buy")}
          className="flex-1 text-[10px] py-1 bg-up/20 text-up rounded cursor-pointer hover:bg-up/30"
        >
          매수
        </button>
        <button
          type="button"
          onClick={() => handleTrade("direct_sell")}
          className="flex-1 text-[10px] py-1 bg-down/20 text-down rounded cursor-pointer hover:bg-down/30"
        >
          매도
        </button>
      </div>

      {/* Positions */}
      <div className="text-[10px] text-muted uppercase tracking-widest mt-1">
        보유 종목 ({positions.length})
      </div>
      {positions.length === 0 ? (
        <div className="text-muted text-[11px] italic">보유 종목 없음</div>
      ) : (
        <div className="flex flex-col gap-0.5">
          {positions.map((pos) => {
            const pnlPct = pos.avg_cost
              ? (((pos.avg_cost - pos.avg_cost) / pos.avg_cost) * 100)
              : 0;
            return (
              <div
                key={pos.symbol}
                className="flex justify-between items-center px-1 py-0.5 hover:bg-bg-alt rounded"
              >
                <div>
                  <span className="text-fg font-bold">{pos.symbol}</span>
                  <span className="text-muted ml-1">
                    {pos.quantity.toLocaleString("en", { maximumFractionDigits: 4 })}
                  </span>
                </div>
                <div className="text-right text-[10px]">
                  <div className="text-muted">
                    avg {formatPrice(pos.avg_cost, pos.currency)}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Orders toggle */}
      <button
        type="button"
        onClick={handleLoadOrders}
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
                  {o.symbol} {o.quantity.toLocaleString("en", { maximumFractionDigits: 4 })}
                </span>
                <span className="text-muted">
                  {formatPrice(o.price, o.currency)}
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
