import { useEffect, useRef } from "react";
import { createChart, LineSeries } from "lightweight-charts";

interface ChartSeries {
  symbol: string;
  currency: string;
  data: Array<{ time: string; value: number }>;
}

interface ComparisonChartData {
  type: string;
  tickers: string[];
  series: ChartSeries[];
}

const LINE_COLORS = ["#39ff14", "#ff6600", "#00bfff", "#ff4081", "#ffd700"];

interface ComparisonChartProps {
  data: ComparisonChartData;
}

function ComparisonChart({ data }: ComparisonChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current || !data.series.length) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 200,
      layout: {
        background: { color: "transparent" },
        textColor: "#808080",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.05)" },
        horzLines: { color: "rgba(255,255,255,0.05)" },
      },
      rightPriceScale: {
        borderColor: "rgba(255,255,255,0.1)",
      },
      timeScale: {
        borderColor: "rgba(255,255,255,0.1)",
        timeVisible: false,
      },
      crosshair: {
        vertLine: { color: "rgba(57,255,20,0.3)" },
        horzLine: { color: "rgba(57,255,20,0.3)" },
      },
    });

    // If tickers have different currencies/scales, use percentage mode
    const currencies = new Set(data.series.map((s) => s.currency));
    const usePercentage = currencies.size > 1;

    data.series.forEach((s, idx) => {
      const lineSeries = chart.addSeries(LineSeries, {
        color: LINE_COLORS[idx % LINE_COLORS.length],
        lineWidth: 2,
        title: s.symbol,
        priceScaleId: usePercentage ? "right" : undefined,
      });

      if (usePercentage && s.data.length > 0) {
        const baseValue = s.data[0].value;
        const normalizedData = s.data.map((d) => ({
          time: d.time,
          value: ((d.value / baseValue) - 1) * 100,
        }));
        lineSeries.setData(normalizedData);
      } else {
        lineSeries.setData(s.data);
      }
    });

    chart.timeScale().fitContent();

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [data]);

  if (!data.series.length) return null;

  const currencies = new Set(data.series.map((s) => s.currency));

  return (
    <div className="my-2">
      <div className="flex items-center gap-3 mb-1">
        {data.series.map((s, idx) => (
          <span key={s.symbol} className="text-[10px] flex items-center gap-1">
            <span
              className="inline-block w-2 h-2 rounded-full"
              style={{ backgroundColor: LINE_COLORS[idx % LINE_COLORS.length] }}
            />
            {s.symbol}
          </span>
        ))}
        {currencies.size > 1 && (
          <span className="text-[9px] text-muted">(% 기준 비교)</span>
        )}
      </div>
      <div
        ref={containerRef}
        className="w-full border border-border-dim rounded"
      />
    </div>
  );
}

export default ComparisonChart;
