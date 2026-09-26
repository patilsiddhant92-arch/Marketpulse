import React, { useState, useEffect, useMemo } from 'react';
import {
  Landmark,
  TrendingUp,
  TrendingDown,
  ExternalLink,
  Copy,
  Check,
  Zap,
  Activity,
  BarChart3,
  Layers,
  Star,
  RefreshCw,
} from 'lucide-react';
import { CapitalFlowResponse, CapitalFlowGroup, StockAccumulator } from '../types';
import {
  InfoTooltip,
  renderDeliveryBadge,
  renderTurnoverBadge,
  renderRsBadge,
} from '../utils/benchmarks';

interface Props {
  onSelectSymbol: (symbol: string) => void;
  onOpenMultiChart?: (symbols: string[]) => void;
  onAddToBasket?: (symbol: string) => void;
}

export const CapitalFlowDashboard: React.FC<Props> = ({
  onSelectSymbol,
  onOpenMultiChart,
  onAddToBasket,
}) => {
  const [level, setLevel] = useState<'sector' | 'industry'>('sector');
  const [timeframe, setTimeframe] = useState<'1D' | '5D' | '1M'>('1D');
  const [data, setData] = useState<CapitalFlowResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedGroup, setCopiedGroup] = useState<string | null>(null);
  const [copiedAccumulators, setCopiedAccumulators] = useState<boolean>(false);
  const [searchFilter, setSearchFilter] = useState<string>('');

  const fetchCapitalFlow = () => {
    setLoading(true);
    setError(null);
    fetch(`/api/market/capital-flow?level=${level}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP error ${res.status}`);
        return res.json();
      })
      .then((json: CapitalFlowResponse) => {
        setData(json);
      })
      .catch((err) => {
        console.error('Failed to fetch capital flow data:', err);
        setError('Unable to load institutional capital flow radar.');
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchCapitalFlow();
  }, [level]);

  // Active timeframe inflows & outflows
  const { activeInflows, activeOutflows } = useMemo(() => {
    if (!data) return { activeInflows: [], activeOutflows: [] };
    if (timeframe === '1D') {
      return { activeInflows: data.top_inflows_1d, activeOutflows: data.top_outflows_1d };
    }
    if (timeframe === '5D') {
      return { activeInflows: data.top_inflows_5d, activeOutflows: data.top_outflows_5d };
    }
    return { activeInflows: data.top_inflows_1m, activeOutflows: data.top_outflows_1m };
  }, [data, timeframe]);

  // Filtered accumulators
  const filteredAccumulators = useMemo(() => {
    if (!data?.stock_accumulators) return [];
    if (!searchFilter.trim()) return data.stock_accumulators;
    const q = searchFilter.toLowerCase();
    return data.stock_accumulators.filter(
      (s) =>
        s.symbol.toLowerCase().includes(q) ||
        s.sector.toLowerCase().includes(q) ||
        s.industry.toLowerCase().includes(q) ||
        s.security_name.toLowerCase().includes(q)
    );
  }, [data, searchFilter]);

  const handleCopyTvSymbols = (groupName: string, symbols: string[]) => {
    if (!symbols || symbols.length === 0) return;
    const tvList = symbols.map((s) => `NSE:${s}`).join(', ');
    navigator.clipboard.writeText(tvList);
    setCopiedGroup(groupName);
    setTimeout(() => setCopiedGroup(null), 2000);
  };

  const handleCopyAllAccumulators = () => {
    if (filteredAccumulators.length === 0) return;
    const tvList = filteredAccumulators.map((s) => `NSE:${s.symbol}`).join(', ');
    navigator.clipboard.writeText(tvList);
    setCopiedAccumulators(true);
    setTimeout(() => setCopiedAccumulators(false), 2000);
  };

  const formatDeltaShare = (val: number) => {
    const sign = val > 0 ? '+' : '';
    const color =
      val > 0.3 ? 'text-[#34d399]' : val < -0.3 ? 'text-[#f43f5e]' : 'text-[#98a7ba]';
    return <span className={`font-mono font-bold ${color}`}>{sign}{val.toFixed(2)}%</span>;
  };

  const shareDelta = (group: CapitalFlowGroup) => {
    if (timeframe === '1D') return group.turnover_share_delta_1d;
    if (timeframe === '5D') return group.turnover_share_delta_5d;
    return group.turnover_share_delta_21d ?? 0;
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[#080c14] overflow-y-auto font-sans select-none">
      {/* Top Header & Navigation Strip */}
      <div className="px-5 py-3 bg-[#0e1522] border-b border-[#1f2b3c] flex items-center justify-between flex-wrap gap-4 sticky top-0 z-20 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-[#16291e] border border-[#235338] text-[#45d483]">
            <Landmark className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-extrabold text-[#f1f4f8] tracking-tight">
                Capital Flow &amp; Money Rotation Radar
              </h1>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#38bdf8]/15 text-[#38bdf8] border border-[#38bdf8]/30 font-bold">
                ≥ ₹1,000 Cr
              </span>
            </div>
            <p className="text-[11px] text-[#7888a0]">
              Liquid tape only: mcap ≥ ₹1,000 Cr · ADV ≥ ₹3 Cr · CMP ≥ ₹10. Share of that universe, not penny-stock noise.
              {data?.universe?.stock_count ? ` · ${data.universe.stock_count} names` : ''}
            </p>
          </div>
        </div>

        {/* Controls: Timeframe (1D/5D/1M) & Grouping Level */}
        <div className="flex items-center gap-3 flex-wrap">
          {/* Group Level (Sector vs Industry) */}
          <div className="flex items-center bg-[#151f2b] p-0.5 rounded-lg border border-[#263447]">
            <button
              onClick={() => setLevel('sector')}
              className={`px-3 py-1 rounded-md text-xs font-semibold transition ${
                level === 'sector'
                  ? 'bg-[#38bdf8] text-[#080c14] shadow'
                  : 'text-[#98a7ba] hover:text-[#f1f4f8]'
              }`}
            >
              Sectors (19)
            </button>
            <button
              onClick={() => setLevel('industry')}
              className={`px-3 py-1 rounded-md text-xs font-semibold transition ${
                level === 'industry'
                  ? 'bg-[#38bdf8] text-[#080c14] shadow'
                  : 'text-[#98a7ba] hover:text-[#f1f4f8]'
              }`}
            >
              Industries (80+)
            </button>
          </div>

          {/* Timeframe Filter (1D / 5D / 1M) */}
          <div className="flex items-center bg-[#151f2b] p-0.5 rounded-lg border border-[#263447]">
            {(['1D', '5D', '1M'] as const).map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-3 py-1 rounded-md text-xs font-semibold transition flex items-center gap-1 ${
                  timeframe === tf
                    ? 'bg-[#f0be58] text-[#080c14] shadow font-bold'
                    : 'text-[#98a7ba] hover:text-[#f1f4f8]'
                }`}
              >
                <span>{tf}</span>
                <span className="text-[10px] opacity-75">
                  {tf === '1D' ? 'Tape' : tf === '5D' ? 'Week' : 'Month'}
                </span>
              </button>
            ))}
          </div>

          {/* Refresh Button */}
          <button
            onClick={fetchCapitalFlow}
            disabled={loading}
            className="p-1.5 rounded-lg bg-[#151f2b] hover:bg-[#1f2b3c] border border-[#263447] text-[#98a7ba] hover:text-white transition"
            title="Refresh Capital Flow Data"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-[#38bdf8]' : ''}`} />
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="p-5 space-y-6">
        {loading && !data ? (
          <div className="p-12 text-center text-[#98a7ba] text-xs">
            <div className="inline-block animate-spin mb-2">⚡</div>
            <div>Analyzing multi-day institutional turnover trends and delivery flow...</div>
          </div>
        ) : error ? (
          <div className="p-6 rounded-lg bg-[#3a1a1e] border border-[#f43f5e]/40 text-[#fda4af] text-xs text-center">
            {error}
          </div>
        ) : (
          <>
            {/* 1. Inflows vs Outflows Cards Grid */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <h2 className="text-xs font-bold uppercase tracking-wider text-[#c5d1e0] flex items-center gap-1.5">
                    <Activity className="w-4 h-4 text-[#38bdf8]" />
                    <span>{timeframe} Capital Rotation: Net Inflows vs Outflows ({level === 'sector' ? 'Sectors' : 'Industries'})</span>
                  </h2>
                  <span className="text-[10px] font-mono text-[#7888a0]">
                    As of: {data?.as_of || 'Latest Session'}
                  </span>
                </div>
                <div className="text-[11px] text-[#98a7ba] flex items-center gap-3">
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-[#10b981]" /> Net Inflow
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-[#f43f5e]" /> Net Outflow
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Top Inflows Column */}
                <div className="rounded-xl bg-[#0b121d] border border-[#1d3326] p-4 flex flex-col justify-between shadow-lg">
                  <div className="flex items-center justify-between pb-3 border-b border-[#1f382a] mb-3">
                    <div className="flex items-center gap-2">
                      <div className="p-1.5 rounded bg-[#10b981]/20 text-[#34d399] border border-[#10b981]/40">
                        <TrendingUp className="w-4 h-4" />
                      </div>
                      <div>
                        <span className="font-extrabold text-sm text-[#34d399]">
                          Top Capital Inflow Clusters
                        </span>
                        <div className="text-[10px] text-[#7888a0]">
                          {timeframe === '1D'
                            ? 'Largest liquid-turnover share expansion today'
                            : timeframe === '5D'
                              ? '5-session share of liquid tape'
                              : '21-session share of liquid tape'}
                        </div>
                      </div>
                    </div>
                    <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#163526] text-[#34d399] border border-[#235338] font-bold">
                      INFLOW 🟢
                    </span>
                  </div>

                  <div className="space-y-2.5">
                    {activeInflows.length === 0 ? (
                      <div className="p-4 text-center text-xs text-[#7888a0]">
                        No high-conviction inflow clusters detected for this timeframe.
                      </div>
                    ) : (
                      activeInflows.map((group, idx) => (
                        <div
                          key={group.group_name}
                          className="p-3 rounded-lg bg-[#0e1726] border border-[#1f2b3c] hover:border-[#34d399]/50 transition group flex flex-col gap-2"
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-xs font-bold text-[#7888a0]">
                                #{idx + 1}
                              </span>
                              <span className="font-bold text-xs text-[#f1f4f8]">
                                {group.group_name}
                              </span>
                              <span
                                className={`px-1.5 py-0.2 rounded text-[9px] font-semibold border ${
                                  group.rotation_state === 'Leading'
                                    ? 'bg-[#163526] text-[#45d483] border-[#45d483]/40'
                                    : group.rotation_state === 'Emerging'
                                    ? 'bg-[#0f2d3d] text-[#38bdf8] border-[#38bdf8]/40'
                                    : 'bg-[#1e2633] text-[#98a7ba] border-[#2b3749]'
                                }`}
                              >
                                {group.rotation_state}
                              </span>
                            </div>

                            <div className="text-right font-mono text-xs flex items-center gap-2">
                              <div>
                                <span className="text-[#98a7ba] text-[10px] mr-1">Share Δ:</span>
                                {formatDeltaShare(shareDelta(group))}
                              </div>
                            </div>
                          </div>

                          {/* Detail metrics strip */}
                          <div className="flex items-center justify-between text-[11px] font-mono text-[#98a7ba] pt-1 border-t border-[#172336]">
                            <div className="flex items-center gap-3">
                              <span>
                                Vol: <strong className="text-white">₹{group.turnover_cr.toFixed(0)}Cr</strong>
                              </span>
                              <span>
                                Share: <strong className="text-white">{group.turnover_share_pct.toFixed(1)}%</strong>
                              </span>
                              <span>
                                Stage 2: <strong className="text-[#34d399]">{group.above_200_ema_pct.toFixed(0)}%</strong>
                              </span>
                              {group.deal_net_cr !== undefined && group.deal_net_cr !== 0 && (
                                <span className={group.deal_net_cr > 0 ? 'text-[#34d399]' : 'text-[#f43f5e]'}>
                                  Deals: {group.deal_net_cr > 0 ? `+₹${group.deal_net_cr.toFixed(0)}Cr` : `-₹${Math.abs(group.deal_net_cr).toFixed(0)}Cr`}
                                </span>
                              )}
                            </div>

                            {/* Action to copy TV symbols or open multi-chart */}
                            {group.leaders && group.leaders.length > 0 && (
                              <div className="flex items-center gap-1.5">
                                <button
                                  onClick={() => handleCopyTvSymbols(group.group_name, group.leaders)}
                                  className="px-1.5 py-0.5 rounded text-[10px] bg-[#151f2b] hover:bg-[#38bdf8] hover:text-[#080c14] border border-[#263447] text-[#98a7ba] transition flex items-center gap-1"
                                  title={`Copy ${group.leaders.length} leading symbols to clipboard`}
                                >
                                  {copiedGroup === group.group_name ? (
                                    <Check className="w-2.5 h-2.5 text-[#34d399]" />
                                  ) : (
                                    <Copy className="w-2.5 h-2.5" />
                                  )}
                                  <span>{copiedGroup === group.group_name ? 'Copied' : 'TV'}</span>
                                </button>
                                {onOpenMultiChart && (
                                  <button
                                    onClick={() => onOpenMultiChart(group.leaders)}
                                    className="px-1.5 py-0.5 rounded text-[10px] bg-[#151f2b] hover:bg-[#f0be58] hover:text-[#080c14] border border-[#263447] text-[#f0be58] transition"
                                    title="Open Leaders in Multi-Chart Tiles"
                                  >
                                    ⊞
                                  </button>
                                )}
                              </div>
                            )}
                          </div>

                          {/* Leader chips */}
                          {group.leaders && group.leaders.length > 0 && (
                            <div className="flex items-center gap-1.5 flex-wrap pt-0.5">
                              <span className="text-[10px] text-[#7888a0]">Pacesetters:</span>
                              {group.leaders.slice(0, 6).map((sym) => (
                                <div key={sym} className="inline-flex items-center gap-0.5">
                                  <button
                                    onClick={() => onSelectSymbol(sym)}
                                    className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-[#132238] text-[#38bdf8] hover:bg-[#38bdf8] hover:text-[#080c14] transition"
                                    title={`Select ${sym} in Stock Inspector`}
                                  >
                                    {sym}
                                  </button>
                                  <a
                                    href={`https://www.tradingview.com/chart/?symbol=NSE:${sym.replace(/-/g, '_')}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-[#7888a0] hover:text-[#38bdf8] p-0.5"
                                    title={`Open ${sym} on TradingView`}
                                  >
                                    <ExternalLink className="w-2.5 h-2.5" />
                                  </a>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                </div>

                {/* Top Outflows Column */}
                <div className="rounded-xl bg-[#0b121d] border border-[#3b1d22] p-4 flex flex-col justify-between shadow-lg">
                  <div className="flex items-center justify-between pb-3 border-b border-[#3d2026] mb-3">
                    <div className="flex items-center gap-2">
                      <div className="p-1.5 rounded bg-[#f43f5e]/20 text-[#fda4af] border border-[#f43f5e]/40">
                        <TrendingDown className="w-4 h-4" />
                      </div>
                      <div>
                        <span className="font-extrabold text-sm text-[#f43f5e]">
                          Top Capital Outflow Clusters
                        </span>
                        <div className="text-[10px] text-[#7888a0]">
                          {timeframe === '1D'
                            ? 'Largest liquid-turnover share contraction today'
                            : timeframe === '5D'
                              ? '5-session share leaving the liquid tape'
                              : '21-session share leaving the liquid tape'}
                        </div>
                      </div>
                    </div>
                    <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#3a2027] text-[#fda4af] border border-[#4d2831] font-bold">
                      OUTFLOW 🔴
                    </span>
                  </div>

                  <div className="space-y-2.5">
                    {activeOutflows.length === 0 ? (
                      <div className="p-4 text-center text-xs text-[#7888a0]">
                        No major outflow clusters detected for this timeframe.
                      </div>
                    ) : (
                      activeOutflows.map((group, idx) => (
                        <div
                          key={group.group_name}
                          className="p-3 rounded-lg bg-[#0e1726] border border-[#1f2b3c] hover:border-[#f43f5e]/50 transition group flex flex-col gap-2"
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-xs font-bold text-[#7888a0]">
                                #{idx + 1}
                              </span>
                              <span className="font-bold text-xs text-[#f1f4f8]">
                                {group.group_name}
                              </span>
                              <span
                                className={`px-1.5 py-0.2 rounded text-[9px] font-semibold border ${
                                  group.rotation_state === 'Lagging'
                                    ? 'bg-[#3a2027] text-[#f27c84] border-[#4d2831]'
                                    : 'bg-[#1e2633] text-[#98a7ba] border-[#2b3749]'
                                }`}
                              >
                                {group.rotation_state}
                              </span>
                            </div>

                            <div className="text-right font-mono text-xs flex items-center gap-2">
                              <div>
                                <span className="text-[#98a7ba] text-[10px] mr-1">Share Δ:</span>
                                {formatDeltaShare(shareDelta(group))}
                              </div>
                            </div>
                          </div>

                          {/* Detail metrics strip */}
                          <div className="flex items-center justify-between text-[11px] font-mono text-[#98a7ba] pt-1 border-t border-[#172336]">
                            <div className="flex items-center gap-3">
                              <span>
                                Vol: <strong className="text-white">₹{group.turnover_cr.toFixed(0)}Cr</strong>
                              </span>
                              <span>
                                Share: <strong className="text-white">{group.turnover_share_pct.toFixed(1)}%</strong>
                              </span>
                              <span>
                                Stage 2: <strong className="text-[#98a7ba]">{group.above_200_ema_pct.toFixed(0)}%</strong>
                              </span>
                              {group.deal_net_cr !== undefined && group.deal_net_cr !== 0 && (
                                <span className={group.deal_net_cr > 0 ? 'text-[#34d399]' : 'text-[#f43f5e]'}>
                                  Deals: {group.deal_net_cr > 0 ? `+₹${group.deal_net_cr.toFixed(0)}Cr` : `-₹${Math.abs(group.deal_net_cr).toFixed(0)}Cr`}
                                </span>
                              )}
                            </div>

                            {group.leaders && group.leaders.length > 0 && (
                              <button
                                onClick={() => handleCopyTvSymbols(group.group_name, group.leaders)}
                                className="px-1.5 py-0.5 rounded text-[10px] bg-[#151f2b] hover:bg-[#f43f5e] hover:text-white border border-[#263447] text-[#98a7ba] transition flex items-center gap-1"
                                title={`Copy ${group.leaders.length} symbols to clipboard`}
                              >
                                {copiedGroup === group.group_name ? (
                                  <Check className="w-2.5 h-2.5 text-[#34d399]" />
                                ) : (
                                  <Copy className="w-2.5 h-2.5" />
                                )}
                                <span>{copiedGroup === group.group_name ? 'Copied' : 'TV'}</span>
                              </button>
                            )}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* 2. Top Stock Capital Accumulators Section */}
            <div className="rounded-xl bg-[#0b121d] border border-[#1f2b3c] overflow-hidden shadow-xl">
              {/* Section Header */}
              <div className="p-4 bg-[#0e1726] border-b border-[#1f2b3c] flex items-center justify-between flex-wrap gap-3">
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded bg-[#38bdf8]/15 text-[#38bdf8] border border-[#38bdf8]/30">
                    <BarChart3 className="w-4 h-4" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-sm font-extrabold text-[#f1f4f8]">
                        Top Stock Capital Accumulators (Liquidity Influx)
                      </h2>
                      <span className="px-2 py-0.2 rounded text-[10px] font-mono bg-[#163526] text-[#34d399] border border-[#235338] font-bold">
                        ≥ ₹1,000 Cr · T/O ≥ ₹10 Cr · +30% SURGE
                      </span>
                    </div>
                    <p className="text-[11px] text-[#7888a0]">
                      Tradeable names only. Ranked by rupees, not percentage spikes on thin paper.
                    </p>
                  </div>
                </div>

                {/* Search & Actions */}
                <div className="flex items-center gap-2 flex-wrap">
                  <input
                    type="text"
                    placeholder="Search symbol, sector..."
                    value={searchFilter}
                    onChange={(e) => setSearchFilter(e.target.value)}
                    className="px-2.5 py-1 rounded-md bg-[#151f2b] border border-[#263447] text-white text-xs placeholder-[#5f748d] w-48 focus:outline-none focus:border-[#38bdf8]"
                  />
                  <button
                    onClick={handleCopyAllAccumulators}
                    className="px-3 py-1 text-xs font-bold rounded-md bg-[#1b2838] text-[#38bdf8] hover:bg-[#38bdf8] hover:text-[#080c14] border border-[#234567] transition flex items-center gap-1.5 shadow-sm"
                  >
                    {copiedAccumulators ? <Check className="w-3.5 h-3.5 text-[#34d399]" /> : <Copy className="w-3.5 h-3.5" />}
                    <span>{copiedAccumulators ? 'Copied All TV' : `Copy All (${filteredAccumulators.length})`}</span>
                  </button>
                  {onOpenMultiChart && (
                    <button
                      onClick={() => onOpenMultiChart(filteredAccumulators.map((s) => s.symbol))}
                      className="px-3 py-1 text-xs font-bold rounded-md bg-[#251e12] text-[#f0be58] hover:bg-[#f0be58] hover:text-[#080c14] border border-[#4a391e] transition flex items-center gap-1.5 shadow-sm"
                      title="Open all accumulators in Multi-Chart Tiles"
                    >
                      <Layers className="w-3.5 h-3.5" />
                      <span>Tiles View</span>
                    </button>
                  )}
                </div>
              </div>

              {/* Accumulator Table */}
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="bg-[#0e1522] text-[#98a7ba] uppercase font-mono text-[11px] tracking-wider border-b border-[#1f2b3c] sticky top-0 z-10 select-none">
                      <th className="py-2.5 px-3 font-semibold">Symbol</th>
                      <th className="py-2.5 px-3 font-semibold">Sector &amp; Industry</th>
                      <th className="py-2.5 px-3 font-semibold text-right">MCap</th>
                      <th className="py-2.5 px-3 font-semibold text-right">CMP (₹)</th>
                      <th className="py-2.5 px-3 font-semibold text-right">1D %</th>
                      <th className="py-2.5 px-3 font-semibold text-right">
                        <InfoTooltip param="turnover" label="Turnover" />
                      </th>
                      <th className="py-2.5 px-3 font-semibold text-right">
                        Turnover Surge
                      </th>
                      <th className="py-2.5 px-3 font-semibold text-right">
                        <InfoTooltip param="delivery" label="Delivery %" />
                      </th>
                      <th className="py-2.5 px-3 font-semibold text-right">
                        <InfoTooltip param="ticket" label="Ticket Ratio" />
                      </th>
                      <th className="py-2.5 px-3 font-semibold text-right">
                        <InfoTooltip param="rs" label="RS Rating" />
                      </th>
                      <th className="py-2.5 px-3 text-center">Institutional Tags</th>
                      <th className="py-2.5 px-3 text-center">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#151f2b] font-mono">
                    {filteredAccumulators.length === 0 ? (
                      <tr>
                        <td colSpan={12} className="py-8 text-center text-[#7888a0] font-sans text-xs">
                          No stocks matching capital accumulation criteria found.
                        </td>
                      </tr>
                    ) : (
                      filteredAccumulators.map((s) => (
                        <tr
                          key={s.symbol}
                          onClick={() => onSelectSymbol(s.symbol)}
                          className="cursor-pointer transition hover:bg-[#151f2b]/80 group"
                        >
                          <td className="py-2 px-3 font-bold text-[#f1f4f8]">
                            <a
                              href={`https://www.tradingview.com/chart/?symbol=NSE:${s.symbol.replace(/-/g, '_')}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="text-[#38bdf8] hover:underline inline-flex items-center gap-1 group-hover:text-[#60a5fa] font-mono font-bold"
                              title={`Open ${s.symbol} on TradingView`}
                            >
                              <span>{s.symbol}</span>
                              <ExternalLink className="w-2.5 h-2.5 opacity-60 group-hover:opacity-100" />
                            </a>
                          </td>

                          <td className="py-2 px-3 text-[#98a7ba] font-sans truncate max-w-[170px]">
                            <div className="font-medium text-white truncate">{s.sector}</div>
                            <div className="text-[10px] text-[#64748b] truncate">{s.industry}</div>
                          </td>

                          <td className="py-2 px-3 text-right font-medium text-[#f1f4f8]">
                            {s.mcap_cr ? `₹${(s.mcap_cr / 1000).toFixed(s.mcap_cr >= 10000 ? 0 : 1)}k Cr` : '—'}
                          </td>

                          <td className="py-2 px-3 text-right font-medium text-[#f1f4f8]">
                            ₹{s.cmp.toFixed(2)}
                          </td>

                          <td className="py-2 px-3 text-right font-semibold text-[#10b981]">
                            +{s.day_pct.toFixed(2)}%
                          </td>

                          <td className="py-2 px-3 text-right">
                            {renderTurnoverBadge(s.turnover_cr)}
                          </td>

                          <td className="py-2 px-3 text-right">
                            <span
                              className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                s.turnover_expansion_pct >= 200
                                  ? 'bg-[#10b981]/20 text-[#34d399] border border-[#10b981]/40'
                                  : 'bg-[#38bdf8]/15 text-[#38bdf8] border border-[#38bdf8]/30'
                              }`}
                              title={`Turnover is ${(s.turnover_expansion_pct + 100).toFixed(0)}% of 20D baseline`}
                            >
                              +{s.turnover_expansion_pct.toFixed(0)}% 🚀
                            </span>
                          </td>

                          <td className="py-2 px-3 text-right">
                            {renderDeliveryBadge(s.delivery_pct, s.delivery_ratio, s.deliv_spike)}
                          </td>

                          <td className="py-2 px-3 text-right">
                            <span
                              className={`text-xs ${
                                s.ticket_ratio >= 1.25
                                  ? 'text-[#f0be58] font-bold'
                                  : 'text-[#98a7ba]'
                              }`}
                              title="Average trade value vs 20D average"
                            >
                              {s.ticket_ratio.toFixed(2)}x
                            </span>
                          </td>

                          <td className="py-2 px-3 text-right">
                            {s.rs_percentile == null ? (
                              <span className="text-[#7888a0]">—</span>
                            ) : (
                              renderRsBadge(s.rs_percentile)
                            )}
                          </td>

                          <td className="py-2 px-3 text-center">
                            <div className="flex items-center justify-center gap-1 flex-wrap">
                              {s.is_whale && (
                                <span
                                  className="px-1.5 py-0.2 rounded text-[9px] bg-[#a855f7]/20 text-[#c084fc] border border-[#a855f7]/35"
                                  title="Whale Order Execution Detected"
                                >
                                  Whale 🏛️
                                </span>
                              )}
                              {s.deliv_spike && (
                                <span
                                  className="px-1.5 py-0.2 rounded text-[9px] bg-[#10b981]/20 text-[#34d399] border border-[#10b981]/30"
                                  title="Delivery Volume Spike"
                                >
                                  Deliv 📦
                                </span>
                              )}
                              {s.acc_vol && (
                                <span
                                  className="px-1.5 py-0.2 rounded text-[9px] bg-[#38bdf8]/20 text-[#38bdf8] border border-[#38bdf8]/30"
                                  title="Price Up + Delivery Volume Up"
                                >
                                  Acc Vol 📈
                                </span>
                              )}
                            </div>
                          </td>

                          <td className="py-2 px-3 text-center">
                            {onAddToBasket && (
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onAddToBasket(s.symbol);
                                }}
                                className="px-2 py-1 rounded bg-[#101721] hover:bg-[#163526] hover:text-[#45d483] border border-[#263447] text-[10px] transition flex items-center gap-1 mx-auto"
                                title="Add to Watchlist"
                              >
                                <Star className="w-3 h-3 text-[#f0be58]" />
                                <span className="font-sans font-semibold">+ Stage</span>
                              </button>
                            )}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
};
