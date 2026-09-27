import React, { useEffect, useRef, useState } from 'react';
import { createChart, createSeriesMarkers, CandlestickSeries, LineSeries, IChartApi, ISeriesApi, LineType, LineStyle } from 'lightweight-charts';
import { Candle, DealMarker, ChartResponse, PeerComparisonResponse } from '../types';
import {
  Activity,
  ExternalLink,
  Star,
  Layers,
  TrendingUp,
  CheckCircle2,
  XCircle,
  Users,
  Grid,
  Copy,
  ChevronRight,
  Sparkles,
  Landmark,
  Package,
  BarChart3,
} from 'lucide-react';
import { copyTextToClipboard } from '../utils/clipboard';
import { InfoTooltip } from '../utils/benchmarks';

interface InspectorSidecarProps {
  symbol: string | null;
  onAddToBasket?: (symbol: string) => void;
  isStaged?: boolean;
  onSelectSymbol?: (symbol: string) => void;
  onOpenMultiChart?: (symbols: string[]) => void;
}

export const InspectorSidecar: React.FC<InspectorSidecarProps> = ({
  symbol,
  onAddToBasket,
  isStaged = false,
  onSelectSymbol,
  onOpenMultiChart,
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlestickSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

  const [chartData, setChartData] = useState<ChartResponse | null>(null);
  const [peerData, setPeerData] = useState<PeerComparisonResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [peersLoading, setPeersLoading] = useState<boolean>(false);
  const [showSma, setShowSma] = useState<boolean>(false);
  const [copiedPeers, setCopiedPeers] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<'overview' | 'peers' | 'deals'>('overview');

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    fetch(`/api/stock/${symbol}/chart?limit=180`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: ChartResponse) => {
        setChartData(data);
        setLoading(false);
      })
      .catch((err) => {
        console.error('Failed to fetch chart data:', err);
        setLoading(false);
      });

    // Fetch Peer Comparison
    setPeersLoading(true);
    fetch(`/api/stock/${symbol}/peers`)
      .then((res) => {
        if (!res.ok) return null;
        return res.json();
      })
      .then((data: PeerComparisonResponse | null) => {
        setPeerData(data);
        setPeersLoading(false);
      })
      .catch((err) => {
        console.error('Failed to fetch peers:', err);
        setPeersLoading(false);
      });
  }, [symbol]);

  useEffect(() => {
    if (!chartContainerRef.current || !chartData || chartData.candles.length === 0) return;

    const container = chartContainerRef.current;
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 240,
      layout: {
        background: { color: '#090d16' },
        textColor: '#98a7ba',
      },
      grid: {
        vertLines: { color: '#141c2b' },
        horzLines: { color: '#141c2b' },
      },
      timeScale: {
        borderColor: '#263447',
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: '#263447',
        scaleMargins: {
          top: 0.08,
          bottom: 0.12,
        },
      },
    });

    // 1. Candlestick Series
    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#f43f5e',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#f43f5e',
      priceLineVisible: false,
    });

    const formattedCandles = chartData.candles.map((c) => ({
      time: c.time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
    candlestickSeries.setData(formattedCandles);

    // 2. Darvas Box Top (Green Line) - Physical Step Line
    const darvasTopSeries = chart.addSeries(LineSeries, {
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

    // 3. Darvas Box Floor (Red Line) - Physical Step Line
    const darvasBottomSeries = chart.addSeries(LineSeries, {
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

    // 3b. Future 5 Trading Sessions Projection (Green/Red/Cyan Dotted Lines)
    if (chartData.darvas_future && chartData.darvas_future.length > 0) {
      const darvasTopFutureSeries = chart.addSeries(LineSeries, {
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

      const darvasBottomFutureSeries = chart.addSeries(LineSeries, {
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
      const ema10FutureSeries = chart.addSeries(LineSeries, {
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

    if (!showSma) {
      // 4. EMA 10 (White) & EMA 20 (Yellow) per Pine Script SUCCESS reference
      const ema10Series = chart.addSeries(LineSeries, {
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

      const ema20Series = chart.addSeries(LineSeries, {
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
    } else {
      // 5. SMA 50, 150, 200 Overlays
      const sma50Series = chart.addSeries(LineSeries, {
        color: '#f59e0b',
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      sma50Series.setData(
        chartData.candles
          .filter((c) => c.sma50 !== undefined && c.sma50 > 0)
          .map((c) => ({ time: c.time, value: c.sma50 }))
      );

      const sma150Series = chart.addSeries(LineSeries, {
        color: '#a855f7',
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      sma150Series.setData(
        chartData.candles
          .filter((c) => c.sma150 !== undefined && c.sma150 > 0)
          .map((c) => ({ time: c.time, value: c.sma150 }))
      );

      const sma200Series = chart.addSeries(LineSeries, {
        color: '#ec4899',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      sma200Series.setData(
        chartData.candles
          .filter((c) => c.sma200 !== undefined && c.sma200 > 0)
          .map((c) => ({ time: c.time, value: c.sma200 }))
      );
    }

    // 6. Stamp Institutional Block/Bulk Deal Markers - Clean dots above candle, no text clutter
    if (chartData.deal_markers && chartData.deal_markers.length > 0) {
      createSeriesMarkers(candlestickSeries, 
        chartData.deal_markers.map((m: DealMarker) => ({
          time: m.time,
          position: m.position || 'aboveBar',
          color: m.color || '#a855f7',
          shape: m.shape || 'circle',
          text: '', // Strictly empty text so candles remain 100% visible
        }))
      );
    }

    // Center chart with 60 clear candles and 4 bars breathing room on right for the 5-session future projection
    const totalBars = chartData.candles.length + 5;
    const targetCandles = 60;
    const to = totalBars - 1 + 4;
    const from = Math.max(0, to - targetCandles);
    chart.timeScale().setVisibleLogicalRange({ from, to });
    chartRef.current = chart;
    candlestickSeriesRef.current = candlestickSeries;

    const handleResize = () => {
      if (chartRef.current && chartContainerRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [chartData, showSma]);

  if (!symbol) {
    return (
      <aside className="w-80 bg-[#0b1019] border-l border-[#1f2b3c] flex flex-col items-center justify-center p-6 text-center text-[#98a7ba]">
        <Activity className="w-8 h-8 text-[#55657e] mb-2 opacity-50" />
        <p className="text-xs">Select any stock from Cockpit, Momentum, Deals, or Sector to view 360° Inspector.</p>
        <span className="text-[10px] text-[#55657e] mt-1 font-mono">Shortcuts: J / K to navigate • Space to stage</span>
      </aside>
    );
  }

  const tpl = chartData?.minervini_template;

  const handleCopyPeers = () => {
    if (!peerData || !peerData.tv_copy_str) return;
    copyTextToClipboard(peerData.tv_copy_str);
    setCopiedPeers(true);
    setTimeout(() => setCopiedPeers(false), 2000);
  };

  const handleOpenPeersInMultiChart = () => {
    if (!onOpenMultiChart || !peerData) return;
    const peerSyms = [symbol, ...peerData.peers.filter((p) => p.symbol !== symbol).map((p) => p.symbol)];
    onOpenMultiChart(peerSyms);
  };

  return (
    <aside className="w-96 bg-[#0b1019] border-l border-[#1f2b3c] flex flex-col h-full overflow-hidden">
      {/* Header Info */}
      <div className="p-3 border-b border-[#1f2b3c] flex items-center justify-between bg-[#0e1522]">
        <div>
          <div className="flex items-center gap-2">
            <a
              href={`https://www.tradingview.com/chart/?symbol=NSE:${symbol.replace(/-/g, '_')}`}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono font-bold text-base text-[#f1f4f8] hover:text-[#38bdf8] flex items-center gap-1 group cursor-pointer"
              title={`Open ${symbol} on TradingView`}
            >
              <span>{symbol}</span>
              <ExternalLink className="w-3.5 h-3.5 text-[#38bdf8] opacity-70 group-hover:opacity-100" />
            </a>
            {peerData && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#101f33] text-[#38bdf8] font-mono border border-[#1e3d66]">
                #{peerData.target_rank}/{peerData.total_peers}
              </span>
            )}
          </div>
          <span className="text-[11px] text-[#98a7ba] truncate max-w-[200px] block">
            {peerData?.industry || peerData?.sector || 'NSE Equity'}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          {onOpenMultiChart && peerData && peerData.peers.length > 1 && (
            <button
              onClick={handleOpenPeersInMultiChart}
              className="p-1.5 rounded border border-[#1e385c] bg-[#12233a] text-[#38bdf8] hover:bg-[#38bdf8] hover:text-[#080c14] transition flex items-center gap-1"
              title="Open Peers in Multi-Chart Grid (2x2)"
            >
              <Grid className="w-3.5 h-3.5" />
            </button>
          )}

          {onAddToBasket && (
            <button
              onClick={() => onAddToBasket(symbol)}
              className={`px-2 py-1 rounded border transition flex items-center gap-1 font-semibold ${
                isStaged
                  ? 'bg-[#163526] text-[#45d483] border-[#235338]'
                  : 'bg-[#151f2b] text-[#f1f4f8] border-[#263447] hover:border-[#f0be58]'
              }`}
              title="Add to active trade watchlist"
            >
              <Star className={`w-3.5 h-3.5 ${isStaged ? 'fill-[#45d483]' : ''}`} />
              <span className="text-[10px]">{isStaged ? 'Watchlist' : '+ Watchlist'}</span>
            </button>
          )}

          <a
            href={`https://www.tradingview.com/chart/?symbol=NSE:${symbol.replace('-', '_')}`}
            target="_blank"
            rel="noreferrer"
            className="p-1.5 rounded border border-[#263447] bg-[#151f2b] text-[#74a9ff] hover:border-[#74a9ff] transition flex items-center"
            title="Open in TradingView Chart"
          >
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        </div>
      </div>

      {/* Sidecar Tabs Bar */}
      <div className="px-3 py-1 bg-[#0a101a] border-b border-[#1f2b3c] flex items-center justify-between text-xs">
        <div className="flex items-center gap-1">
          <button
            onClick={() => setActiveTab('overview')}
            className={`px-2.5 py-1 rounded text-[11px] font-semibold transition ${
              activeTab === 'overview'
                ? 'bg-[#1e293b] text-[#38bdf8] border border-[#38bdf8]/40'
                : 'text-[#8898aa] hover:text-white'
            }`}
          >
            Chart &amp; Setup
          </button>
          <button
            onClick={() => setActiveTab('peers')}
            className={`px-2.5 py-1 rounded text-[11px] font-semibold transition flex items-center gap-1 ${
              activeTab === 'peers'
                ? 'bg-[#1e293b] text-[#45d483] border border-[#45d483]/40'
                : 'text-[#8898aa] hover:text-white'
            }`}
          >
            <Users className="w-3 h-3" />
            <span>Peers ({peerData?.total_peers || 0})</span>
          </button>
          <button
            onClick={() => setActiveTab('deals')}
            className={`px-2.5 py-1 rounded text-[11px] font-semibold transition ${
              activeTab === 'deals'
                ? 'bg-[#1e293b] text-[#f0be58] border border-[#f0be58]/40'
                : 'text-[#8898aa] hover:text-white'
            }`}
          >
            Deals ({chartData?.deal_markers?.length || 0})
          </button>
        </div>

        {activeTab === 'overview' && (
          <div className="flex items-center gap-1">
            <button
              onClick={() => setShowSma(false)}
              className={`px-1.5 py-0.5 rounded text-[10px] font-mono transition ${
                !showSma ? 'text-[#38bdf8] font-bold underline' : 'text-[#7888a0]'
              }`}
            >
              EMA
            </button>
            <span className="text-[#334155]">/</span>
            <button
              onClick={() => setShowSma(true)}
              className={`px-1.5 py-0.5 rounded text-[10px] font-mono transition ${
                showSma ? 'text-[#f59e0b] font-bold underline' : 'text-[#7888a0]'
              }`}
            >
              SMA
            </button>
          </div>
        )}
      </div>

      {/* Tab 1: Chart & Technical Setup Overview */}
      {activeTab === 'overview' && (
        <div className="flex-1 overflow-y-auto flex flex-col">
          {/* Lightweight Candlestick Chart */}
          <div className="relative border-b border-[#1f2b3c] bg-[#090d16]">
            {loading && (
              <div className="absolute inset-0 bg-[#090d16]/80 flex items-center justify-center z-10 text-xs text-[#98a7ba]">
                Loading 400D Geometry &amp; Canvas...
              </div>
            )}
            <div ref={chartContainerRef} className="w-full h-[240px]" />
          </div>

          {/* Darvas Box Metrics Card */}
          <div className="p-3 border-b border-[#1f2b3c] bg-[#101721] space-y-2">
            <div className="flex items-center justify-between">
              <h4 className="text-[11px] font-bold text-[#f0be58] uppercase tracking-wider flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5" />
                Darvas Box Geometry (400D Basis)
              </h4>
              {chartData?.is_darvas_squeeze && (
                <span className="text-[10px] px-2 py-0.5 rounded bg-[#163526] text-[#45d483] font-bold border border-[#235338]">
                  ⚡ 10 EMA Squeeze ({chartData.squeeze_pct}%)
                </span>
              )}
            </div>

            {chartData && (
              <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                <div className="p-2 rounded bg-[#151f2b] border border-[#263447]">
                  <span className="text-[10px] text-[#98a7ba] block">Green Line (Top Box)</span>
                  <span className="font-bold text-[#22c55e]">
                    {chartData.latest_darvas_top > 0 ? `₹${chartData.latest_darvas_top.toFixed(2)}` : 'Coiling'}
                  </span>
                </div>
                <div className="p-2 rounded bg-[#151f2b] border border-[#263447]">
                  <span className="text-[10px] text-[#98a7ba] block">Red Line (Box Floor Stop)</span>
                  <span className="font-bold text-[#ef4444]">
                    {chartData.latest_darvas_bottom > 0 ? `₹${chartData.latest_darvas_bottom.toFixed(2)}` : 'Coiling'}
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Institutional Footprint & Delivery/Turnover Expansion Card */}
          {chartData?.institutional_footprint && (
            <div className="p-3 border-b border-[#1f2b3c] bg-[#0d1420] space-y-2.5 select-none">
              <div className="flex items-center justify-between flex-wrap gap-1">
                <h4 className="text-[11px] font-bold text-[#38bdf8] uppercase tracking-wider flex items-center gap-1.5">
                  <Landmark className="w-3.5 h-3.5 text-[#f0be58]" />
                  <span>Institutional Footprint</span>
                </h4>

                <div className="flex items-center gap-1 flex-wrap">
                  {chartData.institutional_footprint.price_up_delivery_up && (
                    <span className="text-[9px] px-1.5 py-0.2 rounded bg-[#10b981]/20 text-[#34d399] font-bold border border-[#10b981]/35" title="Accumulation Volume: Price Up + Delivery Up">
                      Acc Vol 📈
                    </span>
                  )}
                  {chartData.institutional_footprint.delivery_spike && (
                    <span className="text-[9px] px-1.5 py-0.2 rounded bg-[#10b981]/25 text-[#10b981] font-bold border border-[#10b981]/40" title="Delivery Volume Spike: ≥ 1.5x of 20D Baseline">
                      Deliv Surge 📦
                    </span>
                  )}
                  {chartData.institutional_footprint.is_whale_ticket && (
                    <span className="text-[9px] px-1.5 py-0.2 rounded bg-[#a855f7]/20 text-[#c084fc] font-bold border border-[#a855f7]/35" title="Whale Tickets: Average Trade Size ≥ 1.25x Baseline">
                      Whale 🏛️
                    </span>
                  )}
                  {chartData.institutional_footprint.is_nr7 && (
                    <span className="text-[9px] px-1.5 py-0.2 rounded bg-[#f0be58]/20 text-[#f0be58] font-bold border border-[#f0be58]/35" title="Narrowest Range in 7 Sessions: Explosive Expansion Coiling">
                      NR7 ⚡
                    </span>
                  )}
                </div>
              </div>

              {/* Turnover & Delivery Baseline Comparators */}
              <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                {/* Turnover Expansion */}
                <div className="p-2 rounded bg-[#131b26] border border-[#233347] flex flex-col justify-between">
                  <div className="flex items-center justify-between text-[10px] text-[#98a7ba]">
                    <InfoTooltip param="turnover" label="Turnover" />
                    <span
                      className={`font-bold ${
                        chartData.institutional_footprint.turnover_expansion_pct >= 0
                          ? 'text-[#10b981]'
                          : 'text-[#94a3b8]'
                      }`}
                    >
                      {chartData.institutional_footprint.turnover_expansion_pct >= 0 ? '+' : ''}
                      {chartData.institutional_footprint.turnover_expansion_pct.toFixed(0)}%
                    </span>
                  </div>
                  <div className="pt-1">
                    <span className="text-sm font-bold text-[#f1f4f8]">
                      ₹{chartData.institutional_footprint.turnover_cr.toFixed(1)} Cr
                    </span>
                    <span className="text-[10px] text-[#64748b] block">
                      20D Avg: ₹{chartData.institutional_footprint.avg_turnover_20d_cr.toFixed(1)} Cr
                    </span>
                  </div>
                </div>

                {/* Delivery % vs 20D Baseline */}
                <div className="p-2 rounded bg-[#131b26] border border-[#233347] flex flex-col justify-between">
                  <div className="flex items-center justify-between text-[10px] text-[#98a7ba]">
                    <InfoTooltip param="delivery" label="Delivery" />
                    <span
                      className={`font-bold ${
                        chartData.institutional_footprint.delivery_ratio >= 1.2
                          ? 'text-[#10b981]'
                          : 'text-[#94a3b8]'
                      }`}
                    >
                      {chartData.institutional_footprint.delivery_ratio.toFixed(1)}x Baseline
                    </span>
                  </div>
                  <div className="pt-1">
                    <span className="text-sm font-bold text-[#f1f4f8]">
                      {chartData.institutional_footprint.delivery_pct.toFixed(1)}%
                    </span>
                    <span className="text-[10px] text-[#64748b] block">
                      20D Avg: {chartData.institutional_footprint.avg_delivery_pct_20d.toFixed(1)}%
                    </span>
                  </div>
                </div>
              </div>

              {/* 5-Session Volume & Delivery Activity Trail */}
              {chartData.institutional_footprint.rvol_trail_5d && chartData.institutional_footprint.rvol_trail_5d.length > 0 && (
                <div className="p-2 rounded bg-[#101722] border border-[#1e2c3e] space-y-1.5">
                  <div className="flex items-center justify-between text-[10px]">
                    <span className="text-[#98a7ba] font-semibold flex items-center gap-1">
                      <BarChart3 className="w-3 h-3 text-[#38bdf8]" />
                      <span>5-Session Activity Trail (T-4 → T-0)</span>
                    </span>
                    <span className="text-[9px] font-mono text-[#64748b]">
                      Order Ticket: {chartData.institutional_footprint.ticket_ratio.toFixed(2)}x
                    </span>
                  </div>

                  <div className="grid grid-cols-5 gap-1 text-center font-mono">
                    {chartData.institutional_footprint.rvol_trail_5d.map((rv, idx) => {
                      const deliv = chartData.institutional_footprint!.deliv_trail_5d?.[idx] ?? 0;
                      const pct = chartData.institutional_footprint!.day_pct_trail_5d?.[idx] ?? 0;
                      const isLatest = idx === chartData.institutional_footprint!.rvol_trail_5d.length - 1;

                      return (
                        <div
                          key={idx}
                          className={`p-1 rounded border text-[9px] ${
                            isLatest
                              ? 'bg-[#182638] border-[#38bdf8]/40 text-[#f1f4f8]'
                              : 'bg-[#131b26] border-[#1e2a3a] text-[#94a3b8]'
                          }`}
                        >
                          <div
                            className={`font-bold ${
                              pct >= 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'
                            }`}
                          >
                            {pct >= 0 ? `+${pct.toFixed(0)}%` : `${pct.toFixed(0)}%`}
                          </div>
                          <div className="text-[10px] text-[#38bdf8] font-semibold">
                            {rv.toFixed(1)}x
                          </div>
                          <div className="text-[#64748b] text-[8px]">
                            {deliv.toFixed(0)}% del
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Minervini 8-Point Trend Template Card */}
          {tpl && (
            <div className="p-3 border-b border-[#1f2b3c] bg-[#0c121d] space-y-2">
              <div className="flex items-center justify-between">
                <h4 className="text-[11px] font-bold text-[#38bdf8] uppercase tracking-wider">
                  Minervini Trend Template ({tpl.score}/8)
                </h4>
                <span
                  className={`text-[10px] px-2 py-0.5 rounded font-bold border ${
                    tpl.passes_template
                      ? 'bg-[#163526] text-[#45d483] border-[#235338]'
                      : 'bg-[#33240e] text-[#f0be58] border-[#523d1d]'
                  }`}
                >
                  {tpl.passes_template ? 'Stage 2 Verified' : 'Consolidating'}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-1 text-[10px] font-sans">
                <div className="flex items-center gap-1.5 p-1 rounded bg-[#131b26]">
                  {tpl.criteria.cmp_above_150_200_sma ? (
                    <CheckCircle2 className="w-3 h-3 text-[#10b981]" />
                  ) : (
                    <XCircle className="w-3 h-3 text-[#f43f5e]" />
                  )}
                  <span className="text-[#c5d1e0]">Price &gt; 150/200 SMA</span>
                </div>
                <div className="flex items-center gap-1.5 p-1 rounded bg-[#131b26]">
                  {tpl.criteria.sma_150_above_200 ? (
                    <CheckCircle2 className="w-3 h-3 text-[#10b981]" />
                  ) : (
                    <XCircle className="w-3 h-3 text-[#f43f5e]" />
                  )}
                  <span className="text-[#c5d1e0]">150 SMA &gt; 200 SMA</span>
                </div>
                <div className="flex items-center gap-1.5 p-1 rounded bg-[#131b26]">
                  {tpl.criteria.sma_200_rising ? (
                    <CheckCircle2 className="w-3 h-3 text-[#10b981]" />
                  ) : (
                    <XCircle className="w-3 h-3 text-[#f43f5e]" />
                  )}
                  <span className="text-[#c5d1e0]">200 SMA Rising</span>
                </div>
                <div className="flex items-center gap-1.5 p-1 rounded bg-[#131b26]">
                  {tpl.criteria.sma_50_above_150_200 ? (
                    <CheckCircle2 className="w-3 h-3 text-[#10b981]" />
                  ) : (
                    <XCircle className="w-3 h-3 text-[#f43f5e]" />
                  )}
                  <span className="text-[#c5d1e0]">50 SMA &gt; 150/200</span>
                </div>
                <div className="flex items-center gap-1.5 p-1 rounded bg-[#131b26]">
                  {tpl.criteria.cmp_above_50_sma ? (
                    <CheckCircle2 className="w-3 h-3 text-[#10b981]" />
                  ) : (
                    <XCircle className="w-3 h-3 text-[#f43f5e]" />
                  )}
                  <span className="text-[#c5d1e0]">Price &gt; 50 SMA</span>
                </div>
                <div className="flex items-center gap-1.5 p-1 rounded bg-[#131b26]">
                  {tpl.criteria.within_25pct_52w_high ? (
                    <CheckCircle2 className="w-3 h-3 text-[#10b981]" />
                  ) : (
                    <XCircle className="w-3 h-3 text-[#f43f5e]" />
                  )}
                  <span className="text-[#c5d1e0]">Within 25% 52W High</span>
                </div>
                <div className="flex items-center gap-1.5 p-1 rounded bg-[#131b26]">
                  {tpl.criteria.above_30pct_52w_low ? (
                    <CheckCircle2 className="w-3 h-3 text-[#10b981]" />
                  ) : (
                    <XCircle className="w-3 h-3 text-[#f43f5e]" />
                  )}
                  <span className="text-[#c5d1e0]">&gt; 30% Above 52W Low</span>
                </div>
                <div className="flex items-center gap-1.5 p-1 rounded bg-[#131b26]">
                  {tpl.criteria.rs_above_70 ? (
                    <CheckCircle2 className="w-3 h-3 text-[#10b981]" />
                  ) : (
                    <XCircle className="w-3 h-3 text-[#f43f5e]" />
                  )}
                  <span className="text-[#c5d1e0]">RS Rating &ge; 70</span>
                </div>
              </div>
            </div>
          )}

          {/* Quick Peers Preview Banner */}
          {peerData && (
            <div className="p-3 bg-[#111927] border-b border-[#1f2b3c] flex items-center justify-between">
              <div>
                <span className="text-[10px] text-[#98a7ba] uppercase font-bold tracking-wider block">
                  Industry Relative Strength
                </span>
                <span className="text-xs font-semibold text-[#f1f4f8]">
                  #{peerData.target_rank} of {peerData.total_peers} in {peerData.group_name}
                </span>
              </div>
              <button
                onClick={() => setActiveTab('peers')}
                className="px-2 py-1 rounded bg-[#1a293c] text-[#38bdf8] hover:bg-[#38bdf8] hover:text-[#080c14] border border-[#2b4260] text-[10px] font-semibold transition flex items-center gap-1"
              >
                View Peers <ChevronRight className="w-3 h-3" />
              </button>
            </div>
          )}
        </div>
      )}

      {/* Tab 2: Industry Peer Comparison & Relative Strength Leaderboard */}
      {activeTab === 'peers' && (
        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          {peersLoading ? (
            <div className="p-8 text-center text-xs text-[#98a7ba]">Loading industry peers and RS ranks...</div>
          ) : !peerData ? (
            <div className="p-8 text-center text-xs text-[#98a7ba]">No peer group found for {symbol}.</div>
          ) : (
            <>
              {/* Header Stats & Copy */}
              <div className="p-2.5 rounded-lg bg-[#0e1624] border border-[#1f2b3c] space-y-2">
                <div className="flex items-center justify-between flex-wrap gap-1">
                  <div>
                    <span className="text-[10px] font-bold text-[#38bdf8] uppercase tracking-wider block">
                      {peerData.group_type}: {peerData.group_name}
                    </span>
                    <span className="text-xs text-[#c5d1e0]">
                      Parent Sector: <strong className="text-white">{peerData.sector}</strong>
                    </span>
                  </div>
                  <span
                    className={`px-2 py-0.5 rounded text-[11px] font-mono font-bold ${
                      peerData.target_rank <= 3
                        ? 'bg-[#163526] text-[#45d483] border border-[#235338]'
                        : 'bg-[#142236] text-[#74a9ff] border border-[#233d60]'
                    }`}
                  >
                    Rank #{peerData.target_rank} of {peerData.total_peers}
                  </span>
                </div>

                <div className="flex items-center gap-2 pt-1 border-t border-[#1b283b] flex-wrap">
                  <button
                    onClick={handleCopyPeers}
                    className="px-2 py-1 rounded bg-[#141f2d] text-[#c5d1e0] hover:text-white border border-[#263447] text-[10px] font-mono transition flex items-center gap-1"
                  >
                    <Copy className="w-3 h-3 text-[#d8ac3d]" />
                    <span>{copiedPeers ? 'Copied ✓' : `Copy All (${peerData.peers.length})`}</span>
                  </button>

                  {onOpenMultiChart && (
                    <button
                      onClick={handleOpenPeersInMultiChart}
                      className="px-2 py-1 rounded bg-[#142338] text-[#38bdf8] hover:bg-[#38bdf8] hover:text-[#080c14] border border-[#224067] text-[10px] font-semibold transition flex items-center gap-1"
                    >
                      <Grid className="w-3 h-3" />
                      <span>Tiles View (2x2)</span>
                    </button>
                  )}
                </div>
              </div>

              {/* Better Options in this Industry */}
              {peerData.better_options && peerData.better_options.length > 0 && (
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1.5 text-xs font-bold text-[#45d483] uppercase tracking-wider">
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>Better Options in this Industry</span>
                  </div>
                  <div className="grid grid-cols-2 gap-1.5">
                    {peerData.better_options.slice(0, 4).map((bo) => (
                      <div
                        key={bo.symbol}
                        onClick={() => onSelectSymbol && onSelectSymbol(bo.symbol)}
                        className="p-2 rounded bg-[#111d17] border border-[#235338] hover:border-[#45d483] transition cursor-pointer flex flex-col justify-between gap-1"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-mono font-bold text-xs text-[#38bdf8]">{bo.symbol}</span>
                          <span className="text-[10px] font-bold text-[#45d483] font-mono">RS {bo.rs_percentile}</span>
                        </div>
                        <div className="flex items-center justify-between text-[11px] font-mono">
                          <span className="text-[#c5d1e0]">₹{bo.close_price.toFixed(1)}</span>
                          <span className={bo.day_pct >= 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'}>
                            {bo.day_pct >= 0 ? `+${bo.day_pct.toFixed(1)}%` : `${bo.day_pct.toFixed(1)}%`}
                          </span>
                        </div>
                        <span className="text-[10px] text-[#86efac] font-medium truncate">{bo.reason}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Full Peers Leaderboard Table */}
              <div className="space-y-1">
                <span className="text-[10px] font-bold text-[#98a7ba] uppercase tracking-wider block">
                  All Industry Members ({peerData.peers.length})
                </span>
                <div className="rounded border border-[#1f2b3c] overflow-hidden">
                  <table className="w-full text-left border-collapse text-[11px] font-mono">
                    <thead className="bg-[#0e1622] text-[#8898aa] border-b border-[#1f2b3c] text-[10px] uppercase">
                      <tr>
                        <th className="py-1 px-1.5">#</th>
                        <th className="py-1 px-2">Symbol</th>
                        <th className="py-1 px-2 text-right">RS</th>
                        <th className="py-1 px-2 text-right">CMP</th>
                        <th className="py-1 px-2 text-right">1D %</th>
                        <th className="py-1 px-2 text-right">10 EMA</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#151f2b]">
                      {peerData.peers.map((p) => (
                        <tr
                          key={p.symbol}
                          onClick={() => onSelectSymbol && onSelectSymbol(p.symbol)}
                          className={`cursor-pointer transition ${
                            p.symbol === symbol
                              ? 'bg-[#1a2d47] text-white font-bold'
                              : 'hover:bg-[#141e2b] text-[#c5d1e0]'
                          }`}
                        >
                          <td className="py-1 px-1.5 text-[#8898aa]">{p.rs_rank}</td>
                          <td className="py-1 px-2 font-bold text-[#38bdf8]">
                            <a
                              href={`https://www.tradingview.com/chart/?symbol=NSE:${p.symbol.replace(/-/g, '_')}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="hover:underline flex items-center gap-1"
                              title={`Open ${p.symbol} on TradingView`}
                            >
                              {p.symbol}
                              <ExternalLink className="w-2.5 h-2.5 opacity-60 hover:opacity-100" />
                            </a>
                          </td>
                          <td className="py-1 px-2 text-right font-bold text-[#45d483]">{p.rs_percentile}</td>
                          <td className="py-1 px-2 text-right">₹{p.close_price.toFixed(1)}</td>
                          <td
                            className={`py-1 px-2 text-right font-semibold ${
                              p.day_pct >= 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'
                            }`}
                          >
                            {p.day_pct >= 0 ? `+${p.day_pct.toFixed(1)}%` : `${p.day_pct.toFixed(1)}%`}
                          </td>
                          <td className="py-1 px-2 text-right text-[#8898aa]">
                            {p.away_10ema_pct >= 0 ? `+${p.away_10ema_pct.toFixed(1)}%` : `${p.away_10ema_pct.toFixed(1)}%`}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* Tab 3: Institutional Deals */}
      {activeTab === 'deals' && (
        <div className="p-3 flex-1 overflow-y-auto">
          <h4 className="text-[11px] font-bold text-[#74a9ff] uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <TrendingUp className="w-3.5 h-3.5" />
            Institutional Footprint Deals ({chartData?.deal_markers.length || 0})
          </h4>

          {!chartData?.deal_markers || chartData.deal_markers.length === 0 ? (
            <p className="text-xs text-[#7888a0] italic py-2">No block/bulk deals recorded in past 90 days.</p>
          ) : (
            <div className="space-y-1.5">
              {chartData.deal_markers
                .slice(-10)
                .reverse()
                .map((m, idx) => (
                  <div
                    key={idx}
                    className="p-2 rounded bg-[#151f2b] border border-[#263447] text-xs font-mono flex items-center justify-between"
                  >
                    <div>
                      <span className="text-[10px] text-[#98a7ba] block">{m.time}</span>
                      <span className="font-medium text-[#f1f4f8]">{m.text}</span>
                    </div>
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                        m.color === '#10b981' ? 'bg-[#163526] text-[#45d483]' : 'bg-[#3a2027] text-[#f27c84]'
                      }`}
                    >
                      {m.color === '#10b981' ? 'BUY' : 'SELL'}
                    </span>
                  </div>
                ))}
            </div>
          )}
        </div>
      )}
    </aside>
  );
};
