import React, { useEffect, useRef, useState, useCallback } from 'react';
import { createChart, IChartApi, LineType, LineStyle, LogicalRange } from 'lightweight-charts';
import { ChartResponse } from '../types';
import {
  X,
  Maximize2,
  Minimize2,
  Grid,
  Search,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  CheckSquare,
  Square,
  Users,
  Plus,
  Target,
  BarChart2,
  TrendingUp,
  ListFilter,
  Check,
  PanelLeftClose,
  PanelLeftOpen,
  Trash2,
  Zap,
} from 'lucide-react';

interface MultiChartModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialSymbols?: string[];
  onSelectSymbol: (symbol: string) => void;
}

type GridLayout = '1x1' | '1x2' | '2x2' | '2x3' | '2x4' | '3x3' | '3x4';
type ChartStyle = 'candles' | 'line';

/**
 * Dynamic candle allocation based on grid crowdedness.
 * More crowded grids show fewer candles so each candle has clear body, wicks, and indicators.
 */
export const getTargetCandlesForLayout = (layout: GridLayout, isMaximized: boolean): number => {
  if (isMaximized) return 120;
  switch (layout) {
    case '1x1':
      return 120;
    case '1x2':
      return 85;
    case '2x2': // 4 charts
      return 55;
    case '2x3': // 6 charts
      return 42;
    case '2x4': // 8 charts
      return 35;
    case '3x3': // 9 charts
      return 30;
    case '3x4': // 12 charts
      return 24;
    default:
      return 55;
  }
};

interface TileProps {
  tileId: string;
  symbol: string;
  targetCandles: number;
  onSymbolChange: (newSym: string) => void;
  onSelectSymbol: (sym: string) => void;
  isMaximized: boolean;
  onToggleMaximize: () => void;
  chartStyle: ChartStyle;
  onToggleChartStyle: () => void;
  benchmarkSymbol?: string;
  benchmarkDayPct?: number;
  onSetBenchmark?: (sym: string) => void;
  onReportDayPct?: (sym: string, pct: number) => void;
  onRegisterChart?: (id: string, chart: IChartApi) => () => void;
  onBroadcastRange?: (sourceId: string, range: LogicalRange | null) => void;
}

const ChartTile: React.FC<TileProps> = ({
  tileId,
  symbol,
  targetCandles,
  onSymbolChange,
  onSelectSymbol,
  isMaximized,
  onToggleMaximize,
  chartStyle,
  onToggleChartStyle,
  benchmarkSymbol,
  benchmarkDayPct,
  onSetBenchmark,
  onReportDayPct,
  onRegisterChart,
  onBroadcastRange,
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const [chartData, setChartData] = useState<ChartResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [editingSymbol, setEditingSymbol] = useState<boolean>(false);
  const [symbolInput, setSymbolInput] = useState<string>(symbol);

  useEffect(() => {
    setSymbolInput(symbol);
    if (!symbol) return;
    setLoading(true);
    fetch(`http://127.0.0.1:8000/api/stock/${symbol}/chart?limit=180`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: ChartResponse) => {
        setChartData(data);
        setLoading(false);
        if (data.candles && data.candles.length >= 2) {
          const last = data.candles[data.candles.length - 1];
          const prev = data.candles[data.candles.length - 2];
          if (prev.close > 0) {
            const pct = ((last.close - prev.close) / prev.close) * 100;
            if (onReportDayPct) onReportDayPct(symbol, pct);
          }
        }
      })
      .catch((err) => {
        console.error(`Failed to fetch chart for tile ${symbol}:`, err);
        setLoading(false);
      });
  }, [symbol]);

  // Render Lightweight Charts canvas (Candlestick OR TradingView Line/Area)
  useEffect(() => {
    if (!chartContainerRef.current || !chartData || chartData.candles.length === 0) return;

    const container = chartContainerRef.current;
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      layout: {
        background: { color: '#090d16' },
        textColor: '#8898aa',
      },
      grid: {
        vertLines: { color: '#131c2b' },
        horzLines: { color: '#131c2b' },
      },
      timeScale: {
        borderColor: '#223044',
        timeVisible: false,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: '#223044',
        scaleMargins: {
          top: 0.1,
          bottom: 0.15,
        },
      },
    });

    let mainPriceSeries: any = null;

    if (chartStyle === 'line') {
      // Sleek TradingView-Style Area / Line Series
      const areaSeries = chart.addAreaSeries({
        topColor: 'rgba(56, 189, 248, 0.32)',
        bottomColor: 'rgba(56, 189, 248, 0.01)',
        lineColor: '#38bdf8',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
      });
      areaSeries.setData(
        chartData.candles.map((c) => ({
          time: c.time,
          value: c.close,
        }))
      );
      mainPriceSeries = areaSeries;
    } else {
      // Standard Candlestick Series
      const candleSeries = chart.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#f43f5e',
        borderVisible: false,
        wickUpColor: '#10b981',
        wickDownColor: '#f43f5e',
        priceLineVisible: false,
      });
      candleSeries.setData(
        chartData.candles.map((c) => ({
          time: c.time,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        }))
      );
      mainPriceSeries = candleSeries;
    }

    // 10 EMA Line (White per Pine Script SUCCESS reference)
    const ema10Series = chart.addLineSeries({
      color: '#f8fafc',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    ema10Series.setData(
      chartData.candles
        .filter((c) => c.ema10 !== undefined && c.ema10 > 0)
        .map((c) => ({ time: c.time, value: c.ema10 }))
    );

    // 20 EMA Line (Yellow)
    const ema20Series = chart.addLineSeries({
      color: '#fbbf24',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    ema20Series.setData(
      chartData.candles
        .filter((c) => c.ema20 !== undefined && c.ema20 > 0)
        .map((c) => ({ time: c.time, value: c.ema20 }))
    );

    // Darvas Top Step Line (Green)
    const darvasTopSeries = chart.addLineSeries({
      color: '#22c55e',
      lineWidth: 2,
      lineType: LineType.WithSteps,
      lineStyle: LineStyle.Solid,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    darvasTopSeries.setData(
      chartData.candles
        .filter((c) => c.darvas_top !== undefined && c.darvas_top > 0)
        .map((c) => ({ time: c.time, value: c.darvas_top }))
    );

    // Darvas Bottom Step Line (Red)
    const darvasBottomSeries = chart.addLineSeries({
      color: '#ef4444',
      lineWidth: 2,
      lineType: LineType.WithSteps,
      lineStyle: LineStyle.Solid,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    darvasBottomSeries.setData(
      chartData.candles
        .filter((c) => c.darvas_bottom !== undefined && c.darvas_bottom > 0)
        .map((c) => ({ time: c.time, value: c.darvas_bottom }))
    );

    // Future 5 Sessions Projections (Dotted Lines: Top, Floor, and 10 EMA)
    if (chartData.darvas_future && chartData.darvas_future.length > 0) {
      const darvasTopFutureSeries = chart.addLineSeries({
        color: '#22c55e',
        lineWidth: 2,
        lineType: LineType.WithSteps,
        lineStyle: LineStyle.Dotted,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      darvasTopFutureSeries.setData(
        chartData.darvas_future
          .filter((f) => f.top > 0)
          .map((f) => ({ time: f.time, value: f.top }))
      );

      const darvasBottomFutureSeries = chart.addLineSeries({
        color: '#ef4444',
        lineWidth: 2,
        lineType: LineType.WithSteps,
        lineStyle: LineStyle.Dotted,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      darvasBottomFutureSeries.setData(
        chartData.darvas_future
          .filter((f) => f.bottom > 0)
          .map((f) => ({ time: f.time, value: f.bottom }))
      );

      // 10 EMA Future Projection (White dotted line per Pine Script SUCCESS reference)
      const ema10FutureSeries = chart.addLineSeries({
        color: '#f8fafc',
        lineWidth: 2,
        lineType: LineType.Simple,
        lineStyle: LineStyle.Dotted,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      ema10FutureSeries.setData(
        chartData.darvas_future
          .filter((f) => f.ema10 !== undefined && f.ema10 > 0)
          .map((f) => ({ time: f.time, value: f.ema10! }))
      );
    }

    // Stamp clean circular deal dots above the candles / price line
    if (chartData.deal_markers && chartData.deal_markers.length > 0 && mainPriceSeries) {
      mainPriceSeries.setMarkers(
        chartData.deal_markers.map((m) => ({
          time: m.time,
          position: m.position || 'aboveBar',
          color: m.color || '#a855f7',
          shape: m.shape || 'circle',
          text: '',
        }))
      );
    }

    // Center chart with optimal candle count and right margin for 5-session future projections
    const totalBars = chartData.candles.length + 5;
    const rightMarginBars = Math.max(3, Math.round(targetCandles * 0.08));
    const to = totalBars - 1 + rightMarginBars;
    const from = Math.max(0, to - targetCandles);
    chart.timeScale().setVisibleLogicalRange({ from, to });

    chartRef.current = chart;

    // Register with grid-level sync coordinator
    const unregister = onRegisterChart ? onRegisterChart(tileId, chart) : () => {};

    // Broadcast time range changes on user pan/zoom
    const handleRangeChange = (newRange: LogicalRange | null) => {
      if (newRange && onBroadcastRange) {
        onBroadcastRange(tileId, newRange);
      }
    };

    chart.timeScale().subscribeVisibleLogicalRangeChange(handleRangeChange);

    const handleResize = () => {
      if (chartRef.current && container) {
        chartRef.current.applyOptions({
          width: container.clientWidth,
          height: container.clientHeight,
        });
      }
    };

    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      if (chartRef.current) {
        chartRef.current.timeScale().unsubscribeVisibleLogicalRangeChange(handleRangeChange);
        unregister();
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [chartData, isMaximized, chartStyle]);

  // Synchronously adjust visible candle count and centering when grid layout changes
  useEffect(() => {
    if (!chartRef.current || !chartData || chartData.candles.length === 0) return;
    const totalBars = chartData.candles.length + 5;
    const rightMarginBars = Math.max(3, Math.round(targetCandles * 0.08));
    const to = totalBars - 1 + rightMarginBars;
    const from = Math.max(0, to - targetCandles);
    chartRef.current.timeScale().setVisibleLogicalRange({ from, to });
  }, [targetCandles]);

  const handleInputSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const clean = symbolInput.trim().toUpperCase();
    if (clean && clean !== symbol) {
      onSymbolChange(clean);
    }
    setEditingSymbol(false);
  };

  const lastCandle = chartData?.candles[chartData.candles.length - 1];
  const prevCandle = chartData?.candles[chartData.candles.length - 2];
  const dayPct =
    lastCandle && prevCandle && prevCandle.close > 0
      ? ((lastCandle.close - prevCandle.close) / prevCandle.close) * 100
      : 0;

  // Comparison relative to benchmark
  const isBenchmark = benchmarkSymbol === symbol;
  const relativeDiff =
    !isBenchmark && benchmarkDayPct !== undefined && !isNaN(benchmarkDayPct)
      ? dayPct - benchmarkDayPct
      : null;

  const peerInfo = chartData?.peer_info;

  return (
    <div className="flex flex-col h-full bg-[#090d16] rounded-lg border border-[#1f2b3c] overflow-hidden shadow">
      {/* Tile Header */}
      <div className="px-2 py-1.5 bg-[#0e1522] border-b border-[#1f2b3c] flex items-center justify-between gap-1 text-xs select-none">
        <div className="flex items-center gap-1.5 flex-wrap min-w-0">
          {editingSymbol ? (
            <form onSubmit={handleInputSubmit} className="flex items-center gap-1">
              <input
                type="text"
                autoFocus
                value={symbolInput}
                onChange={(e) => setSymbolInput(e.target.value)}
                onBlur={() => setEditingSymbol(false)}
                className="w-20 px-1 py-0.5 text-xs font-mono font-bold bg-[#141d2b] text-[#f1f4f8] border border-[#38bdf8] rounded outline-none"
              />
            </form>
          ) : (
            <div className="flex items-center gap-1">
              <button
                onClick={() => setEditingSymbol(true)}
                className="font-mono font-bold text-sm text-[#f1f4f8] hover:text-[#38bdf8] transition flex items-center gap-0.5"
                title="Click to change symbol"
              >
                <span>{symbol}</span>
                <Search className="w-2.5 h-2.5 text-[#5f748d]" />
              </button>
              <a
                href={`https://www.tradingview.com/chart/?symbol=NSE:${symbol.replace(/-/g, '_')}`}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="text-[#5f748d] hover:text-[#38bdf8] transition"
                title={`Open ${symbol} in TradingView`}
              >
                <ExternalLink className="w-2.5 h-2.5" />
              </a>
            </div>
          )}

          {lastCandle && (
            <span className="font-mono text-xs text-[#c5d1e0]">
              ₹{lastCandle.close.toFixed(2)}
            </span>
          )}

          {lastCandle && (
            <span
              className={`font-mono text-[11px] font-semibold ${
                dayPct >= 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'
              }`}
            >
              {dayPct >= 0 ? `+${dayPct.toFixed(1)}%` : `${dayPct.toFixed(1)}%`}
            </span>
          )}

          {/* Benchmark comparison badge */}
          {isBenchmark ? (
            <span className="px-1 py-0.2 rounded bg-[#38bdf8]/20 text-[#38bdf8] font-bold text-[9px] flex items-center gap-0.5">
              <Target className="w-2.5 h-2.5" />
              <span>BM</span>
            </span>
          ) : relativeDiff !== null ? (
            <span
              className={`font-mono text-[10px] px-1 py-0.2 rounded font-semibold ${
                relativeDiff >= 0
                  ? 'bg-[#10b981]/15 text-[#10b981]'
                  : 'bg-[#f43f5e]/15 text-[#f43f5e]'
              }`}
              title={`Relative performance vs ${benchmarkSymbol}`}
            >
              {relativeDiff >= 0 ? `+${relativeDiff.toFixed(1)}%` : `${relativeDiff.toFixed(1)}%`} vs {benchmarkSymbol}
            </span>
          ) : null}
        </div>

        <div className="flex items-center gap-1">
          {/* Peer Rank Badge */}
          {peerInfo && (
            <span
              className={`px-1.5 py-0.2 rounded text-[9px] font-mono font-bold whitespace-nowrap ${
                peerInfo.is_leader
                  ? 'bg-[#10b981]/25 text-[#34d399] border border-[#10b981]/40'
                  : 'bg-[#1a2536] text-[#93c5fd]'
              }`}
              title={`Peer Rank: #${peerInfo.target_rank} of ${peerInfo.total_peers} in ${peerInfo.industry}`}
            >
              {peerInfo.is_leader ? '👑 #1 Leader' : `#${peerInfo.target_rank}/${peerInfo.total_peers}`}
            </span>
          )}

          {/* RS Percentile Badge */}
          {peerInfo?.rs_percentile !== undefined && peerInfo.rs_percentile > 0 && (
            <span className="px-1 py-0.2 rounded bg-[#f0be58]/15 text-[#f0be58] font-mono text-[9px] font-bold">
              RS {peerInfo.rs_percentile.toFixed(0)}
            </span>
          )}

          {/* Chart Style Toggle (Candles vs Line) */}
          <button
            onClick={onToggleChartStyle}
            className={`p-1 rounded transition text-[10px] flex items-center gap-0.5 ${
              chartStyle === 'line'
                ? 'bg-[#38bdf8]/20 text-[#38bdf8]'
                : 'text-[#98a7ba] hover:text-white hover:bg-[#162235]'
            }`}
            title={`Toggle between Candles and TradingView Line chart (Current: ${chartStyle})`}
          >
            {chartStyle === 'line' ? <TrendingUp className="w-3 h-3" /> : <BarChart2 className="w-3 h-3" />}
          </button>

          {/* Benchmark Setter */}
          {!isBenchmark && onSetBenchmark && (
            <button
              onClick={() => onSetBenchmark(symbol)}
              className="p-1 rounded text-[#98a7ba] hover:text-[#38bdf8] hover:bg-[#162235] transition"
              title={`Set ${symbol} as active benchmark to compare all other charts against`}
            >
              <Target className="w-3 h-3" />
            </button>
          )}

          {/* Inspect in Sidecar */}
          <button
            onClick={() => onSelectSymbol(symbol)}
            className="p-1 rounded text-[#74a9ff] hover:bg-[#162235] transition"
            title="Inspect in sidecar"
          >
            <ExternalLink className="w-3 h-3" />
          </button>

          {/* Maximize Toggle */}
          <button
            onClick={onToggleMaximize}
            className="p-1 rounded text-[#98a7ba] hover:text-white hover:bg-[#162235] transition"
            title={isMaximized ? 'Restore Grid' : 'Maximize Tile'}
          >
            {isMaximized ? <Minimize2 className="w-3 h-3" /> : <Maximize2 className="w-3 h-3" />}
          </button>
        </div>
      </div>

      {/* Chart Canvas Area */}
      <div className="flex-1 relative bg-[#090d16]">
        {loading && (
          <div className="absolute inset-0 bg-[#090d16]/75 flex items-center justify-center z-10 text-[11px] text-[#98a7ba]">
            Loading {symbol}...
          </div>
        )}
        <div ref={chartContainerRef} className="w-full h-full" />
      </div>
    </div>
  );
};

export const MultiChartModal: React.FC<MultiChartModalProps> = ({
  isOpen,
  onClose,
  initialSymbols = ['HAL', 'MTARTECH', 'ROSSTECH', 'PARAS'],
  onSelectSymbol,
}) => {
  // Pool of all candidate symbols available in this session
  const [poolSymbols, setPoolSymbols] = useState<string[]>(initialSymbols);
  // Symbols currently selected to show in tiles
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>(initialSymbols);
  const [layout, setLayout] = useState<GridLayout>('2x2');
  const [maximizedIndex, setMaximizedIndex] = useState<number | null>(null);

  // Global and per-tile chart style ('candles' | 'line')
  const [globalChartStyle, setGlobalChartStyle] = useState<ChartStyle>('candles');
  const [tileChartStyles, setTileChartStyles] = useState<Record<string, ChartStyle>>({});

  // Pagination & Navigation
  const [currentPage, setCurrentPage] = useState<number>(0);
  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(true);

  // Search & Add Symbol in drawer
  const [searchAddInput, setSearchAddInput] = useState<string>('');
  const [loadingPeers, setLoadingPeers] = useState<boolean>(false);

  // Benchmark stock for relative comparison
  const [benchmarkSymbol, setBenchmarkSymbol] = useState<string>(initialSymbols[0] || 'HAL');
  const [symbolDayPcts, setSymbolDayPcts] = useState<Record<string, number>>({});

  // Synchronize initial symbols when modal opens
  useEffect(() => {
    if (isOpen && initialSymbols && initialSymbols.length > 0) {
      const cleanUnique = Array.from(new Set(initialSymbols.map((s) => s.trim().toUpperCase())));
      setPoolSymbols(cleanUnique);
      setSelectedSymbols(cleanUnique);
      setBenchmarkSymbol(cleanUnique[0] || 'HAL');
      setCurrentPage(0);
      setMaximizedIndex(null);
    }
  }, [isOpen, initialSymbols]);

  // Determine tile capacity and target visible candles based on layout
  let tileCapacity = 4;
  if (layout === '1x1') tileCapacity = 1;
  else if (layout === '1x2') tileCapacity = 2;
  else if (layout === '2x2') tileCapacity = 4;
  else if (layout === '2x3') tileCapacity = 6;
  else if (layout === '2x4') tileCapacity = 8;
  else if (layout === '3x3') tileCapacity = 9;
  else if (layout === '3x4') tileCapacity = 12;

  // Dynamic candle count: more crowded grids show fewer candles so candles remain thick and clear!
  const targetCandles = getTargetCandlesForLayout(layout, maximizedIndex !== null);

  // Time scale pan/zoom sync across all active charts in the grid
  const [isSyncEnabled, setIsSyncEnabled] = useState<boolean>(true);
  const registeredChartsRef = useRef<Map<string, IChartApi>>(new Map());
  const isBroadcastingRef = useRef<boolean>(false);

  const handleRegisterChart = useCallback((id: string, chart: IChartApi) => {
    registeredChartsRef.current.set(id, chart);
    return () => {
      registeredChartsRef.current.delete(id);
    };
  }, []);

  const handleBroadcastRange = useCallback(
    (sourceId: string, range: LogicalRange | null) => {
      if (!isSyncEnabled || !range || isBroadcastingRef.current) return;
      isBroadcastingRef.current = true;
      registeredChartsRef.current.forEach((chart, id) => {
        if (id !== sourceId) {
          try {
            chart.timeScale().setVisibleLogicalRange(range);
          } catch (e) {
            // Ignore if chart is updating or unmounted
          }
        }
      });
      requestAnimationFrame(() => {
        isBroadcastingRef.current = false;
      });
    },
    [isSyncEnabled]
  );

  const handleRecenterAll = useCallback(() => {
    registeredChartsRef.current.forEach((chart) => {
      try {
        const to = 185 + 3;
        const from = Math.max(0, to - targetCandles);
        chart.timeScale().setVisibleLogicalRange({ from, to });
      } catch (e) {}
    });
  }, [targetCandles]);

  const totalPages = Math.max(1, Math.ceil(selectedSymbols.length / tileCapacity));

  // Ensure current page is valid
  useEffect(() => {
    if (currentPage >= totalPages) {
      setCurrentPage(Math.max(0, totalPages - 1));
    }
  }, [selectedSymbols.length, tileCapacity, totalPages, currentPage]);

  // Keyboard navigation for pagination & escape
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) return;

      if (e.key === 'ArrowRight' || e.key === ']') {
        setCurrentPage((prev) => Math.min(totalPages - 1, prev + 1));
      } else if (e.key === 'ArrowLeft' || e.key === '[') {
        setCurrentPage((prev) => Math.max(0, prev - 1));
      } else if (e.key === 'Escape') {
        if (maximizedIndex !== null) {
          setMaximizedIndex(null);
        } else {
          onClose();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, totalPages, maximizedIndex, onClose]);

  if (!isOpen) return null;

  // Active symbols displayed on the current page
  const pageStart = currentPage * tileCapacity;
  const activeSymbols = selectedSymbols.slice(pageStart, pageStart + tileCapacity);

  // Toggle selection of a symbol in the pool
  const handleToggleSelectSymbol = (sym: string) => {
    if (selectedSymbols.includes(sym)) {
      if (selectedSymbols.length <= 1) return; // Keep at least 1 symbol
      setSelectedSymbols((prev) => prev.filter((s) => s !== sym));
    } else {
      setSelectedSymbols((prev) => [...prev, sym]);
    }
  };

  // Add symbol from search box
  const handleAddSymbol = (e: React.FormEvent) => {
    e.preventDefault();
    const clean = searchAddInput.trim().toUpperCase();
    if (!clean) return;
    if (!poolSymbols.includes(clean)) {
      setPoolSymbols((prev) => [...prev, clean]);
    }
    if (!selectedSymbols.includes(clean)) {
      setSelectedSymbols((prev) => [...prev, clean]);
    }
    setSearchAddInput('');
  };

  // Remove symbol completely from pool
  const handleRemoveFromPool = (sym: string) => {
    setPoolSymbols((prev) => prev.filter((s) => s !== sym));
    setSelectedSymbols((prev) => prev.filter((s) => s !== sym));
  };

  // Load all industry peers for the active benchmark stock
  const handleLoadPeers = () => {
    const target = benchmarkSymbol || selectedSymbols[0] || poolSymbols[0];
    if (!target) return;
    setLoadingPeers(true);
    fetch(`http://127.0.0.1:8000/api/stock/${target}/peers`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        if (data && data.peers && data.peers.length > 0) {
          const peerSymbols = data.peers.map((p: any) => String(p.symbol).toUpperCase());
          const merged = Array.from(new Set([target, ...peerSymbols, ...poolSymbols]));
          setPoolSymbols(merged);
          // By default select all peers (or top 12)
          setSelectedSymbols(merged);
        }
      })
      .catch((err) => console.error('Failed to load peers:', err))
      .finally(() => setLoadingPeers(false));
  };

  const handleToggleTileChartStyle = (sym: string) => {
    setTileChartStyles((prev) => {
      const current = prev[sym] || globalChartStyle;
      return {
        ...prev,
        [sym]: current === 'candles' ? 'line' : 'candles',
      };
    });
  };

  const handleToggleMaximize = (index: number) => {
    if (maximizedIndex === index) {
      setMaximizedIndex(null);
    } else {
      setMaximizedIndex(index);
    }
  };

  const handleReportDayPct = (sym: string, pct: number) => {
    setSymbolDayPcts((prev) => ({ ...prev, [sym]: pct }));
  };

  const benchmarkDayPct = benchmarkSymbol ? symbolDayPcts[benchmarkSymbol] : undefined;

  return (
    <div className="fixed inset-0 z-50 bg-black/85 flex flex-col p-2.5 animate-in fade-in duration-150 backdrop-blur-sm">
      {/* Top Navigation & Toolbar Bar */}
      <div className="flex items-center justify-between pb-2 mb-2 border-b border-[#1f2b3c] flex-wrap gap-2 text-xs">
        {/* Left: Title + Drawer Toggle */}
        <div className="flex items-center gap-2.5">
          <button
            onClick={() => setIsDrawerOpen((prev) => !prev)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded font-semibold transition border ${
              isDrawerOpen
                ? 'bg-[#152538] text-[#38bdf8] border-[#224067]'
                : 'bg-[#101722] text-[#98a7ba] border-[#1f2b3c] hover:text-white'
            }`}
            title="Toggle Symbol Navigation & Peer Selector Drawer"
          >
            {isDrawerOpen ? <PanelLeftClose className="w-3.5 h-3.5" /> : <PanelLeftOpen className="w-3.5 h-3.5" />}
            <span>Symbols &amp; Peers ({selectedSymbols.length}/{poolSymbols.length})</span>
          </button>

          <div className="flex items-center gap-1.5">
            <Grid className="w-4 h-4 text-[#38bdf8]" />
            <span className="font-bold text-[#f1f4f8] uppercase tracking-wider text-xs">
              Multi-Chart Tiles
            </span>
          </div>

          {/* Global Chart Style Toggle: Candles vs Line (TradingView style) */}
          <div className="flex items-center bg-[#101722] p-0.5 rounded border border-[#1f2b3c]">
            <button
              onClick={() => {
                setGlobalChartStyle('candles');
                setTileChartStyles({});
              }}
              className={`px-2 py-0.5 rounded text-[11px] font-semibold transition flex items-center gap-1 ${
                globalChartStyle === 'candles'
                  ? 'bg-[#10b981] text-[#080c14] font-bold'
                  : 'text-[#98a7ba] hover:text-white'
              }`}
              title="Show Candlestick Charts across all tiles"
            >
              <BarChart2 className="w-3 h-3" />
              <span>Candles</span>
            </button>
            <button
              onClick={() => {
                setGlobalChartStyle('line');
                setTileChartStyles({});
              }}
              className={`px-2 py-0.5 rounded text-[11px] font-semibold transition flex items-center gap-1 ${
                globalChartStyle === 'line'
                  ? 'bg-[#38bdf8] text-[#080c14] font-bold'
                  : 'text-[#98a7ba] hover:text-white'
              }`}
              title="Show TradingView-Style Area/Line Charts across all tiles"
            >
              <TrendingUp className="w-3 h-3" />
              <span>Line / Area</span>
            </button>
          </div>
        </div>

        {/* Center: Pagination Controls */}
        <div className="flex items-center gap-2 bg-[#101722] px-2.5 py-1 rounded border border-[#1f2b3c]">
          <button
            onClick={() => setCurrentPage((p) => Math.max(0, p - 1))}
            disabled={currentPage === 0}
            className="p-1 rounded text-[#c5d1e0] hover:text-white hover:bg-[#1a2638] disabled:opacity-30 disabled:pointer-events-none transition"
            title="Previous Page (Key: [ or Left Arrow)"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>

          <span className="font-mono text-xs text-[#c5d1e0]">
            Page <span className="text-[#38bdf8] font-bold">{currentPage + 1}</span> of{' '}
            <span className="font-bold">{totalPages}</span>{' '}
            <span className="text-[#64748b]">
              ({pageStart + 1}–{Math.min(pageStart + tileCapacity, selectedSymbols.length)} of {selectedSymbols.length})
            </span>
          </span>

          <button
            onClick={() => setCurrentPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={currentPage >= totalPages - 1}
            className="p-1 rounded text-[#c5d1e0] hover:text-white hover:bg-[#1a2638] disabled:opacity-30 disabled:pointer-events-none transition"
            title="Next Page (Key: ] or Right Arrow)"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>

        {/* Right: Layout Switcher & Close */}
        <div className="flex items-center gap-2">
          {/* Grid Time Scale Sync Toggle */}
          <button
            onClick={() => setIsSyncEnabled(!isSyncEnabled)}
            className={`px-2 py-0.5 rounded text-[11px] font-semibold border transition flex items-center gap-1 ${
              isSyncEnabled
                ? 'bg-[#10b981]/15 text-[#34d399] border-[#10b981]/40'
                : 'bg-[#151f2b] text-[#64748b] border-[#263447] hover:text-white'
            }`}
            title="Synchronize time scale scrolling and zooming across all visible charts"
          >
            <Zap className={`w-3 h-3 ${isSyncEnabled ? 'text-[#34d399]' : 'text-[#64748b]'}`} />
            <span>{isSyncEnabled ? 'Sync ON' : 'Sync OFF'}</span>
          </button>

          {/* Re-center All Charts */}
          <button
            onClick={handleRecenterAll}
            className="px-2 py-0.5 rounded text-[11px] font-semibold bg-[#151f2b] text-[#98a7ba] hover:text-white border border-[#263447] transition flex items-center gap-1"
            title={`Re-center all charts to default view (${targetCandles} candles with future projections)`}
          >
            <Target className="w-3 h-3 text-[#38bdf8]" />
            <span>Center</span>
          </button>

          {/* Grid Layout Switcher */}
          <div className="flex items-center gap-0.5 bg-[#101722] p-0.5 rounded border border-[#1f2b3c]">
            <span className="text-[10px] text-[#64748b] px-1 uppercase font-semibold">Grid:</span>
            {[
              { id: '1x1', label: '1' },
              { id: '1x2', label: '2' },
              { id: '2x2', label: '2x2 (4)' },
              { id: '2x3', label: '2x3 (6)' },
              { id: '2x4', label: '2x4 (8)' },
              { id: '3x3', label: '3x3 (9)' },
              { id: '3x4', label: '3x4 (12)' },
            ].map((ly) => (
              <button
                key={ly.id}
                onClick={() => {
                  setLayout(ly.id as GridLayout);
                  setMaximizedIndex(null);
                }}
                className={`px-1.5 py-0.5 text-[11px] rounded font-mono transition ${
                  layout === ly.id && maximizedIndex === null
                    ? 'bg-[#38bdf8] text-[#080c14] font-bold'
                    : 'text-[#98a7ba] hover:text-white'
                }`}
              >
                {ly.label}
              </button>
            ))}
          </div>

          {/* Close Button */}
          <button
            onClick={onClose}
            className="p-1.5 rounded-md bg-[#162232] text-[#c5d1e0] hover:bg-[#f43f5e] hover:text-white border border-[#23354d] transition"
            title="Close Tiles Window (Esc)"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Main Workspace Body: Drawer + Grid */}
      <div className="flex-1 w-full h-full min-h-0 flex gap-2.5 overflow-hidden">
        {/* Navigation & Peer Selector Drawer (Left Panel) */}
        {isDrawerOpen && (
          <aside className="w-64 bg-[#0e1522] border border-[#1f2b3c] rounded-lg flex flex-col h-full overflow-hidden shrink-0 shadow-lg text-xs">
            {/* Drawer Header & Search */}
            <div className="p-2 border-b border-[#1f2b3c] bg-[#121c2d] flex flex-col gap-2">
              <form onSubmit={handleAddSymbol} className="flex items-center gap-1">
                <input
                  type="text"
                  placeholder="Add symbol (e.g. BEL)..."
                  value={searchAddInput}
                  onChange={(e) => setSearchAddInput(e.target.value)}
                  className="flex-1 px-2 py-1 bg-[#090d16] text-[#f1f4f8] placeholder-[#5f748d] rounded border border-[#26374f] font-mono text-xs outline-none focus:border-[#38bdf8]"
                />
                <button
                  type="submit"
                  className="px-2 py-1 rounded bg-[#38bdf8] text-[#080c14] font-bold text-xs hover:bg-[#7dd3fc] transition flex items-center gap-0.5"
                  title="Add stock to tiles pool"
                >
                  <Plus className="w-3 h-3" />
                </button>
              </form>

              {/* Load Industry Peers button */}
              <button
                onClick={handleLoadPeers}
                disabled={loadingPeers}
                className="w-full py-1 px-2 rounded bg-[#16253b] text-[#38bdf8] hover:bg-[#38bdf8] hover:text-[#080c14] border border-[#23416b] font-semibold text-[11px] transition flex items-center justify-center gap-1.5"
                title={`Load all industry peers of ${benchmarkSymbol || 'target stock'}`}
              >
                <Users className="w-3 h-3" />
                <span>{loadingPeers ? 'Loading Peers...' : `Load Peers of ${benchmarkSymbol || 'Selected'} 👥`}</span>
              </button>

              {/* Quick Select Filters */}
              <div className="flex items-center justify-between text-[10px] text-[#98a7ba] pt-1">
                <span>Quick Select:</span>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setSelectedSymbols([...poolSymbols])}
                    className="hover:text-white underline"
                  >
                    All
                  </button>
                  <span>·</span>
                  <button
                    onClick={() => setSelectedSymbols(poolSymbols.slice(0, 4))}
                    className="hover:text-white underline"
                  >
                    Top 4
                  </button>
                  <span>·</span>
                  <button
                    onClick={() => setSelectedSymbols(poolSymbols.slice(0, 6))}
                    className="hover:text-white underline"
                  >
                    Top 6
                  </button>
                  <span>·</span>
                  <button
                    onClick={() => setSelectedSymbols(poolSymbols.slice(0, 9))}
                    className="hover:text-white underline"
                  >
                    Top 9
                  </button>
                  <span>·</span>
                  <button
                    onClick={() => setSelectedSymbols([])}
                    className="hover:text-[#f43f5e] underline"
                  >
                    Clear
                  </button>
                </div>
              </div>
            </div>

            {/* Scrollable Symbol Pool List */}
            <div className="flex-1 overflow-y-auto divide-y divide-[#172233]">
              {poolSymbols.map((sym) => {
                const isSelected = selectedSymbols.includes(sym);
                const isBm = benchmarkSymbol === sym;
                const dayPct = symbolDayPcts[sym];

                return (
                  <div
                    key={sym}
                    className={`px-2 py-1.5 flex items-center justify-between gap-1 hover:bg-[#142033] transition ${
                      isSelected ? 'bg-[#101927]' : 'opacity-60'
                    }`}
                  >
                    <label className="flex items-center gap-2 cursor-pointer flex-1 min-w-0">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => handleToggleSelectSymbol(sym)}
                        className="rounded border-[#26374f] bg-[#090d16] text-[#38bdf8] focus:ring-0 cursor-pointer"
                      />
                      <span className="font-mono font-bold text-xs text-[#f1f4f8] truncate">
                        {sym}
                      </span>
                      {dayPct !== undefined && (
                        <span
                          className={`font-mono text-[10px] ${
                            dayPct >= 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'
                          }`}
                        >
                          {dayPct >= 0 ? `+${dayPct.toFixed(1)}%` : `${dayPct.toFixed(1)}%`}
                        </span>
                      )}
                    </label>

                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => setBenchmarkSymbol(sym)}
                        className={`p-1 rounded text-[10px] transition ${
                          isBm
                            ? 'bg-[#38bdf8] text-[#080c14] font-bold'
                            : 'text-[#64748b] hover:text-[#38bdf8]'
                        }`}
                        title={isBm ? 'Current comparison benchmark' : `Set ${sym} as comparison benchmark`}
                      >
                        <Target className="w-2.5 h-2.5" />
                      </button>

                      <button
                        onClick={() => handleRemoveFromPool(sym)}
                        className="p-1 rounded text-[#64748b] hover:text-[#f43f5e] transition"
                        title="Remove from pool"
                      >
                        <Trash2 className="w-2.5 h-2.5" />
                      </button>
                    </div>
                  </div>
                );
              })}

              {poolSymbols.length === 0 && (
                <div className="p-4 text-center text-[#64748b] text-xs">
                  No symbols in pool. Use the search bar above or click "Load Peers".
                </div>
              )}
            </div>

            {/* Bottom Drawer Summary */}
            <div className="p-2 border-t border-[#1f2b3c] bg-[#121c2d] flex items-center justify-between text-[11px] text-[#98a7ba]">
              <span>Selected: <strong className="text-[#38bdf8]">{selectedSymbols.length}</strong></span>
              <span>Benchmark: <strong className="text-[#f0be58] font-mono">{benchmarkSymbol || 'None'}</strong></span>
            </div>
          </aside>
        )}

        {/* Main Grid View Area */}
        <div className="flex-1 w-full h-full min-h-0 flex flex-col overflow-hidden">
          {maximizedIndex !== null && activeSymbols[maximizedIndex] ? (
            <div className="w-full h-full">
              <ChartTile
                tileId={`maximized-${activeSymbols[maximizedIndex]}`}
                symbol={activeSymbols[maximizedIndex]}
                targetCandles={120}
                onSymbolChange={(s) => {
                  const updated = [...selectedSymbols];
                  const globalIdx = pageStart + maximizedIndex;
                  updated[globalIdx] = s;
                  setSelectedSymbols(updated);
                }}
                onSelectSymbol={onSelectSymbol}
                isMaximized={true}
                onToggleMaximize={() => setMaximizedIndex(null)}
                chartStyle={tileChartStyles[activeSymbols[maximizedIndex]] || globalChartStyle}
                onToggleChartStyle={() => handleToggleTileChartStyle(activeSymbols[maximizedIndex])}
                benchmarkSymbol={benchmarkSymbol}
                benchmarkDayPct={benchmarkDayPct}
                onSetBenchmark={setBenchmarkSymbol}
                onReportDayPct={handleReportDayPct}
                onRegisterChart={handleRegisterChart}
                onBroadcastRange={handleBroadcastRange}
              />
            </div>
          ) : selectedSymbols.length === 0 ? (
            <div className="w-full h-full flex flex-col items-center justify-center text-center p-6 bg-[#090d16] rounded-lg border border-[#1f2b3c]">
              <Grid className="w-12 h-12 text-[#38bdf8]/40 mb-3" />
              <h4 className="text-base font-bold text-[#f1f4f8] mb-1">No Symbols Selected</h4>
              <p className="text-xs text-[#98a7ba] max-w-sm mb-4">
                Use the Symbols &amp; Peers panel on the left to select stocks or click below to restore all.
              </p>
              <button
                onClick={() => setSelectedSymbols([...poolSymbols])}
                className="px-4 py-2 rounded bg-[#38bdf8] text-[#080c14] font-bold text-xs hover:bg-[#7dd3fc] transition"
              >
                Select All Symbols ({poolSymbols.length})
              </button>
            </div>
          ) : (
            <div
              className={`w-full h-full gap-2 grid ${
                layout === '1x1'
                  ? 'grid-cols-1 grid-rows-1'
                  : layout === '1x2'
                  ? 'grid-cols-2 grid-rows-1'
                  : layout === '2x2'
                  ? 'grid-cols-2 grid-rows-2'
                  : layout === '2x3'
                  ? 'grid-cols-3 grid-rows-2'
                  : layout === '2x4'
                  ? 'grid-cols-4 grid-rows-2'
                  : layout === '3x3'
                  ? 'grid-cols-3 grid-rows-3'
                  : 'grid-cols-4 grid-rows-3'
              }`}
            >
              {activeSymbols.map((sym, idx) => (
                <ChartTile
                  key={`${sym}-${idx}`}
                  tileId={`${sym}-${idx}`}
                  symbol={sym}
                  targetCandles={targetCandles}
                  onSymbolChange={(s) => {
                    const updated = [...selectedSymbols];
                    updated[pageStart + idx] = s;
                    setSelectedSymbols(updated);
                  }}
                  onSelectSymbol={onSelectSymbol}
                  isMaximized={false}
                  onToggleMaximize={() => handleToggleMaximize(idx)}
                  chartStyle={tileChartStyles[sym] || globalChartStyle}
                  onToggleChartStyle={() => handleToggleTileChartStyle(sym)}
                  benchmarkSymbol={benchmarkSymbol}
                  benchmarkDayPct={benchmarkDayPct}
                  onSetBenchmark={setBenchmarkSymbol}
                  onReportDayPct={handleReportDayPct}
                  onRegisterChart={handleRegisterChart}
                  onBroadcastRange={handleBroadcastRange}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
