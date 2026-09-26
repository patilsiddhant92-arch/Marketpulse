import React, { useState, useEffect, useMemo } from 'react';
import { MomentumCandidate, SectorLeaderSummary, IndustryLeaderSummary } from '../types';
import { Copy, Check, Filter, Zap, ArrowUpDown, ArrowUp, ArrowDown, Star, RefreshCw, X, Layers, Briefcase, ExternalLink } from 'lucide-react';
import { sortData, SortConfig } from '../utils/tableSort';
import { InfoTooltip, renderRvolBadge, renderDeliveryBadge, renderRsBadge } from '../utils/benchmarks';
import { DASH, signedPct } from '../utils/nullable';

interface Props {
  selectedSymbol: string | null;
  onSelectSymbol: (symbol: string) => void;
  onAddToBasket: (symbol: string) => void;
}

export const MomentumWorkspace: React.FC<Props> = ({
  selectedSymbol,
  onSelectSymbol,
  onAddToBasket,
}) => {
  // Filter States (Full MarketPulse 2.0 parity with user defaults)
  const [lookbackDays, setLookbackDays] = useState<number>(20); // Default 20D per user spec
  const [minMcapCr, setMinMcapCr] = useState<number>(1000); // Default 1000 Cr per user spec
  const [volumeMode, setVolumeMode] = useState<'day' | 'avg20d' | 'off'>('day'); // Either Day or 20D Avg, never both
  const [volumeThreshold, setVolumeThreshold] = useState<number>(1000000); // Default 1,000,000 (1M) per user spec
  const [max52wAwayPct, setMax52wAwayPct] = useState<number>(25);
  const [min52wLowPct, setMin52wLowPct] = useState<number>(50); // Default 50% per user spec
  const [cmpGt10, setCmpGt10] = useState<boolean>(true);
  const [cmpGt200, setCmpGt200] = useState<boolean>(true);
  const [ohlcGt10, setOhlcGt10] = useState<boolean>(false);
  const [ohlcGt20, setOhlcGt20] = useState<boolean>(false);
  const [emaStack, setEmaStack] = useState<boolean>(true); // Default true (ticked by default) per user spec
  const [smaTemplate, setSmaTemplate] = useState<boolean>(false);
  const [deliveryThrust, setDeliveryThrust] = useState<boolean>(false);
  const [coilingNr7, setCoilingNr7] = useState<boolean>(false);
  const [weeklyRsi60, setWeeklyRsi60] = useState<boolean>(false);
  const [debugSymbol, setDebugSymbol] = useState<string>('');

  const minVolume = volumeMode === 'day' ? volumeThreshold : 0;
  const minAvgVolume20d = volumeMode === 'avg20d' ? volumeThreshold : 0;

  const [candidates, setCandidates] = useState<MomentumCandidate[]>([]);
  const [topSectors, setTopSectors] = useState<SectorLeaderSummary[]>([]);
  const [topIndustries, setTopIndustries] = useState<IndustryLeaderSummary[]>([]);
  const [sectorDistribution, setSectorDistribution] = useState<SectorLeaderSummary[]>([]);
  const [selectedSectorFilter, setSelectedSectorFilter] = useState<string | null>(null);

  const [loading, setLoading] = useState<boolean>(true);
  const [copied, setCopied] = useState<boolean>(false);
  const [copiedLabel, setCopiedLabel] = useState<string | null>(null);
  const [showFilterPanel, setShowFilterPanel] = useState<boolean>(true);
  const [bucketsTv, setBucketsTv] = useState<string>('');

  // Sorting (Default: NiceGUI 2.0 coil distance to 10 EMA ascending)
  const [sortConfig, setSortConfig] = useState<SortConfig<MomentumCandidate>>({
    key: 'away_10ema_pct',
    direction: 'asc',
  });

  const fetchCandidates = () => {
    setLoading(true);
    const params = new URLSearchParams({
      lookback_days: lookbackDays.toString(),
      min_mcap_cr: minMcapCr.toString(),
      min_volume: minVolume.toString(),
      min_avg_volume_20d: minAvgVolume20d.toString(),
      max_52w_away_pct: max52wAwayPct.toString(),
      min_52w_low_pct: min52wLowPct.toString(),
      cmp_gt_10: cmpGt10.toString(),
      cmp_gt_200: cmpGt200.toString(),
      ohlc_gt_10: ohlcGt10.toString(),
      ohlc_gt_20: ohlcGt20.toString(),
      ema10_gt_20: emaStack.toString(),
      ema20_gt_50: emaStack.toString(),
      ema50_gt_100: emaStack.toString(),
      ema100_gt_200: emaStack.toString(),
      sma50_gt_150: smaTemplate.toString(),
      sma150_gt_200: smaTemplate.toString(),
      sma_cmp_gt_50: smaTemplate.toString(),
      sma_cmp_gt_150_200: smaTemplate.toString(),
      sma200_rising: smaTemplate.toString(),
      delivery_thrust: deliveryThrust.toString(),
      coiling_nr7: coilingNr7.toString(),
      weekly_rsi_60: weeklyRsi60.toString(),
      limit: '300',
    });

    if (debugSymbol.trim()) {
      params.append('debug_symbol', debugSymbol.trim().toUpperCase());
    }

    fetch(`/api/screener/momentum?${params.toString()}`)
      .then((res) => res.json())
      .then((data) => {
        const list = data.candidates || [];
        setCandidates(list);
        setTopSectors(data.top_sectors || []);
        setTopIndustries(data.top_industries || []);
        setSectorDistribution(data.sector_distribution || []);
        setBucketsTv(data.buckets_tv || '');
        if (list.length > 0 && !selectedSymbol) {
          onSelectSymbol(list[0].symbol);
        }
      })
      .catch((err) => console.error('Momentum fetch error:', err))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchCandidates();
  }, [
    lookbackDays,
    minMcapCr,
    volumeMode,
    volumeThreshold,
    max52wAwayPct,
    min52wLowPct,
    cmpGt10,
    cmpGt200,
    ohlcGt10,
    ohlcGt20,
    emaStack,
    smaTemplate,
    deliveryThrust,
    coilingNr7,
    weeklyRsi60,
  ]);

  // Preset Handlers
  const applyPreset = (name: string) => {
    switch (name) {
      case 'stage2':
        setCmpGt200(true);
        setCmpGt10(true);
        setMax52wAwayPct(25);
        setMin52wLowPct(50);
        setMinMcapCr(1000);
        setEmaStack(true);
        setSmaTemplate(false);
        setDeliveryThrust(false);
        setCoilingNr7(false);
        break;
      case 'breakouts':
        setMax52wAwayPct(5);
        setMin52wLowPct(50);
        setMinMcapCr(1000);
        setCmpGt10(true);
        setCmpGt200(true);
        setEmaStack(false);
        break;
      case 'sma_template':
        setSmaTemplate(true);
        setEmaStack(false);
        setMax52wAwayPct(25);
        setMin52wLowPct(50);
        setMinMcapCr(1000);
        break;
      case 'delivery':
        setDeliveryThrust(true);
        setCmpGt200(true);
        setMinMcapCr(1000);
        break;
      case 'coiling':
        setCoilingNr7(true);
        setMax52wAwayPct(15);
        setMin52wLowPct(50);
        setMinMcapCr(1000);
        break;
      case 'mtf':
        setWeeklyRsi60(true);
        setCmpGt10(true);
        setCmpGt200(true);
        setMinMcapCr(1000);
        break;
      case 'clear':
        setCmpGt10(false);
        setCmpGt200(false);
        setOhlcGt10(false);
        setOhlcGt20(false);
        setEmaStack(false);
        setSmaTemplate(false);
        setDeliveryThrust(false);
        setCoilingNr7(false);
        setWeeklyRsi60(false);
        setMax52wAwayPct(99);
        setMin52wLowPct(0);
        setMinMcapCr(0);
        setVolumeMode('off');
        break;
      default:
        break;
    }
  };

  const handleCopyTv = (label: string, tvStr: string) => {
    if (!tvStr) return;
    navigator.clipboard.writeText(tvStr);
    setCopiedLabel(label);
    setTimeout(() => setCopiedLabel(null), 2000);
  };

  const handleCopyAll = () => {
    if (candidates.length === 0) return;
    const tvList = candidates.map((c) => `NSE:${c.symbol}`).join(', ');
    navigator.clipboard.writeText(tvList);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSort = (key: keyof MomentumCandidate) => {
    setSortConfig((prev) => {
      if (prev.key === key) {
        if (prev.direction === 'asc') return { key, direction: 'desc' };
        if (prev.direction === 'desc') return { key: null, direction: null };
      }
      return { key, direction: 'asc' };
    });
  };

  const filteredCandidates = useMemo(() => {
    if (!selectedSectorFilter) return candidates;
    return candidates.filter((c) => c.sector === selectedSectorFilter);
  }, [candidates, selectedSectorFilter]);

  const sortedCandidates = useMemo(() => {
    return sortData(filteredCandidates, sortConfig.key, sortConfig.direction);
  }, [filteredCandidates, sortConfig]);

  const formatVol = (v?: number) => {
    if (!v || v === 0) return '—';
    if (v >= 10000000) return `${(v / 10000000).toFixed(1)}Cr`;
    if (v >= 100000) return `${(v / 100000).toFixed(1)}L`;
    if (v >= 1000) return `${(v / 1000).toFixed(0)}k`;
    return v.toString();
  };

  const renderSortArrow = (key: keyof MomentumCandidate) => {
    if (sortConfig.key !== key) {
      return <ArrowUpDown className="w-3 h-3 text-[#55657e] inline ml-1 opacity-60" />;
    }
    return sortConfig.direction === 'asc' ? (
      <ArrowUp className="w-3 h-3 text-[#38bdf8] inline ml-1" />
    ) : (
      <ArrowDown className="w-3 h-3 text-[#38bdf8] inline ml-1" />
    );
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[#080c14] overflow-hidden">
      {/* Top Presets & Controls Bar */}
      <div className="px-4 py-2 bg-[#0e1522] border-b border-[#1f2b3c] flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-bold text-[#38bdf8] uppercase tracking-wider flex items-center gap-1">
            <Zap className="w-3.5 h-3.5" />
            Presets:
          </span>
          <button
            onClick={() => applyPreset('stage2')}
            className="px-2.5 py-1 text-xs rounded bg-[#151f2b] text-[#f1f4f8] border border-[#263447] hover:border-[#38bdf8] font-medium"
          >
            Stage 2 Template
          </button>
          <button
            onClick={() => applyPreset('sma_template')}
            className="px-2.5 py-1 text-xs rounded bg-[#151f2b] text-[#74a9ff] border border-[#263447] hover:border-[#74a9ff] font-medium"
          >
            SMA Template
          </button>
          <button
            onClick={() => applyPreset('breakouts')}
            className="px-2.5 py-1 text-xs rounded bg-[#151f2b] text-[#f0be58] border border-[#263447] hover:border-[#f0be58] font-medium"
          >
            Near 52W High (&le;5%)
          </button>
          <button
            onClick={() => applyPreset('delivery')}
            className="px-2.5 py-1 text-xs rounded bg-[#151f2b] text-[#10b981] border border-[#263447] hover:border-[#10b981] font-medium"
          >
            Delivery Thrust
          </button>
          <button
            onClick={() => applyPreset('coiling')}
            className="px-2.5 py-1 text-xs rounded bg-[#151f2b] text-[#ec4899] border border-[#263447] hover:border-[#ec4899] font-medium"
          >
            NR7 Coiling
          </button>
          <button
            onClick={() => applyPreset('mtf')}
            className="px-2.5 py-1 text-xs rounded bg-[#151f2b] text-[#a855f7] border border-[#263447] hover:border-[#a855f7] font-medium"
          >
            Weekly RSI &ge; 60
          </button>
          <button
            onClick={() => applyPreset('clear')}
            className="px-2 py-1 text-xs text-[#f43f5e] hover:underline"
          >
            Clear all
          </button>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs text-[#98a7ba] font-mono">
            {candidates.length} Leaders Found
          </span>
          {bucketsTv && (
            <button
              onClick={() => handleCopyTv('Buckets', bucketsTv)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-bold bg-[#152336] text-[#38bdf8] border border-[#253c5e] hover:border-[#38bdf8] transition"
              title="Copy watchlists partitioned into coil buckets (###0_2%, ###2_5%, etc.) for TradingView"
            >
              {copiedLabel === 'Buckets' ? <Check className="w-3.5 h-3.5 text-[#45d483]" /> : <Copy className="w-3.5 h-3.5" />}
              <span>{copiedLabel === 'Buckets' ? 'Buckets Copied!' : 'Copy Buckets'}</span>
            </button>
          )}
          <button
            onClick={handleCopyAll}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-bold bg-[#182b46] text-[#74a9ff] border border-[#2b4c7e] hover:border-[#74a9ff] transition"
            title="Copy 100% of visible symbols formatted for TradingView (Rule 1 Compliant)"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-[#45d483]" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? 'Copied to Clipboard!' : 'Copy All to TV'}</span>
          </button>
          <button
            onClick={() => setShowFilterPanel(!showFilterPanel)}
            className="px-2.5 py-1 text-xs rounded bg-[#101721] text-[#98a7ba] border border-[#263447] hover:text-white"
          >
            {showFilterPanel ? 'Hide Filters' : 'Show Filters'}
          </button>
        </div>
      </div>

      {/* Collapsible Complete Filter Panel (MarketPulse 2.0 Parity) */}
      {showFilterPanel && (
        <div className="px-4 py-2.5 bg-[#0b1018] border-b border-[#1f2b3c] space-y-2 text-xs">
          {/* Row 1: Lookback, MCap, 52W Distances */}
          <div className="flex items-center gap-4 flex-wrap text-[#c5d1e0]">
            <div className="flex items-center gap-1.5">
              <span className="text-[#98a7ba]">Lookback:</span>
              {[1, 3, 5, 10, 20, 30].map((d) => (
                <button
                  key={d}
                  onClick={() => setLookbackDays(d)}
                  className={`px-2 py-0.5 rounded text-[11px] font-mono border ${
                    lookbackDays === d
                      ? 'bg-[#38bdf8] text-[#080c14] border-[#38bdf8] font-bold'
                      : 'bg-[#151f2b] text-[#98a7ba] border-[#263447]'
                  }`}
                >
                  {d}D
                </button>
              ))}
            </div>

            <div className="flex items-center gap-1.5">
              <span className="text-[#98a7ba]">Min MCap:</span>
              <input
                type="number"
                value={minMcapCr}
                onChange={(e) => setMinMcapCr(Number(e.target.value))}
                className="w-20 px-2 py-0.5 rounded bg-[#151f2b] border border-[#263447] text-white font-mono text-xs"
              />
              <span className="text-[10px] text-[#7888a0]">Cr</span>
            </div>

            {/* Mutual Exclusive Volume Gate Selector */}
            <div className="flex items-center gap-2 p-1 rounded bg-[#101721] border border-[#263447]">
              <span className="text-[#98a7ba] font-semibold text-[11px] pl-1">Volume Gate:</span>
              
              {/* Mutual Exclusion Mode Selector */}
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setVolumeMode('day')}
                  className={`px-2 py-0.5 rounded text-[11px] font-medium transition ${
                    volumeMode === 'day'
                      ? 'bg-[#38bdf8] text-[#080c14] font-bold shadow-sm'
                      : 'bg-[#151f2b] text-[#98a7ba] hover:text-white'
                  }`}
                  title="Filter by Minimum Day Volume (mutually exclusive with 20D Avg)"
                >
                  Min Day Vol
                </button>
                <button
                  type="button"
                  onClick={() => setVolumeMode('avg20d')}
                  className={`px-2 py-0.5 rounded text-[11px] font-medium transition ${
                    volumeMode === 'avg20d'
                      ? 'bg-[#38bdf8] text-[#080c14] font-bold shadow-sm'
                      : 'bg-[#151f2b] text-[#98a7ba] hover:text-white'
                  }`}
                  title="Filter by Minimum 20D Average Volume (mutually exclusive with Day Vol)"
                >
                  Min 20D Avg
                </button>
                <button
                  type="button"
                  onClick={() => setVolumeMode('off')}
                  className={`px-1.5 py-0.5 rounded text-[11px] font-medium transition ${
                    volumeMode === 'off'
                      ? 'bg-[#f43f5e] text-white font-bold'
                      : 'bg-[#151f2b] text-[#7888a0] hover:text-white'
                  }`}
                  title="Disable Volume Filter"
                >
                  Off
                </button>
              </div>

              {/* Threshold & Presets when active */}
              {volumeMode !== 'off' && (
                <div className="flex items-center gap-1 pl-1 border-l border-[#263447]">
                  <input
                    type="number"
                    value={volumeThreshold}
                    onChange={(e) => setVolumeThreshold(Number(e.target.value))}
                    className="w-24 px-2 py-0.5 rounded bg-[#151f2b] border border-[#263447] text-white font-mono text-xs"
                    title="Volume Threshold"
                  />
                  <div className="flex items-center gap-0.5">
                    {[
                      { label: '5L', val: 500000 },
                      { label: '10L (1M)', val: 1000000 },
                      { label: '25L', val: 2500000 },
                      { label: '50L', val: 5000000 },
                    ].map((p) => (
                      <button
                        key={p.label}
                        type="button"
                        onClick={() => setVolumeThreshold(p.val)}
                        className={`px-1.5 py-0.5 rounded text-[10px] font-mono border ${
                          volumeThreshold === p.val
                            ? 'bg-[#38bdf8] text-[#080c14] border-[#38bdf8] font-bold'
                            : 'bg-[#101721] text-[#7888a0] border-[#263447] hover:text-white'
                        }`}
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="flex items-center gap-1.5">
              <span className="text-[#98a7ba]">Max 52W Away:</span>
              <input
                type="number"
                value={max52wAwayPct}
                onChange={(e) => setMax52wAwayPct(Number(e.target.value))}
                className="w-16 px-2 py-0.5 rounded bg-[#151f2b] border border-[#263447] text-white font-mono text-xs"
              />
              <span className="text-[10px] text-[#7888a0]">%</span>
            </div>

            <div className="flex items-center gap-1.5">
              <span className="text-[#98a7ba]">Min Above 52W Low:</span>
              <input
                type="number"
                value={min52wLowPct}
                onChange={(e) => setMin52wLowPct(Number(e.target.value))}
                className="w-16 px-2 py-0.5 rounded bg-[#151f2b] border border-[#263447] text-white font-mono text-xs"
              />
              <span className="text-[10px] text-[#7888a0]">%</span>
            </div>

            <div className="flex items-center gap-1.5">
              <span className="text-[#98a7ba]">Debug Symbol:</span>
              <input
                type="text"
                placeholder="RELIANCE"
                value={debugSymbol}
                onChange={(e) => setDebugSymbol(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && fetchCandidates()}
                className="w-24 px-2 py-0.5 rounded bg-[#151f2b] border border-[#263447] text-white font-mono text-xs uppercase"
              />
            </div>
          </div>

          {/* Row 2: Checkboxes for Moving Averages and Advanced Filters */}
          <div className="flex items-center gap-4 flex-wrap text-xs text-[#c5d1e0]">
            <label className="flex items-center gap-1 cursor-pointer">
              <input type="checkbox" checked={cmpGt10} onChange={(e) => setCmpGt10(e.target.checked)} className="rounded bg-[#151f2b]" />
              <span>CMP &gt; 10 EMA</span>
            </label>
            <label className="flex items-center gap-1 cursor-pointer">
              <input type="checkbox" checked={cmpGt200} onChange={(e) => setCmpGt200(e.target.checked)} className="rounded bg-[#151f2b]" />
              <span>CMP &gt; 200 EMA</span>
            </label>
            <label className="flex items-center gap-1 cursor-pointer">
              <input type="checkbox" checked={ohlcGt10} onChange={(e) => setOhlcGt10(e.target.checked)} className="rounded bg-[#151f2b]" />
              <span>OHLC &gt; 10 EMA</span>
            </label>
            <label className="flex items-center gap-1 cursor-pointer">
              <input type="checkbox" checked={emaStack} onChange={(e) => { setEmaStack(e.target.checked); if (e.target.checked) setSmaTemplate(false); }} className="rounded bg-[#151f2b]" />
              <span className="text-[#38bdf8]">EMA Stack (10&gt;20&gt;50&gt;200)</span>
            </label>
            <label className="flex items-center gap-1 cursor-pointer">
              <input type="checkbox" checked={smaTemplate} onChange={(e) => { setSmaTemplate(e.target.checked); if (e.target.checked) setEmaStack(false); }} className="rounded bg-[#151f2b]" />
              <span className="text-[#f59e0b]">SMA Template (50&gt;150&gt;200)</span>
            </label>
            <label className="flex items-center gap-1 cursor-pointer">
              <input type="checkbox" checked={deliveryThrust} onChange={(e) => setDeliveryThrust(e.target.checked)} className="rounded bg-[#151f2b]" />
              <span>Delivery Thrust</span>
            </label>
            <label className="flex items-center gap-1 cursor-pointer">
              <input type="checkbox" checked={coilingNr7} onChange={(e) => setCoilingNr7(e.target.checked)} className="rounded bg-[#151f2b]" />
              <span>NR7 / Inside Bar</span>
            </label>
            <label className="flex items-center gap-1 cursor-pointer">
              <input type="checkbox" checked={weeklyRsi60} onChange={(e) => setWeeklyRsi60(e.target.checked)} className="rounded bg-[#151f2b]" />
              <span>Weekly RSI &ge; 60</span>
            </label>
          </div>
        </div>
      )}

      {/* Prominent Top Sector & Industry Leadership Cards (NiceGUI Parity) */}
      {!loading && candidates.length > 0 && (
        <div className="px-4 py-2 bg-[#0a0f18] border-b border-[#1f2b3c] space-y-2">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <span className="text-[11px] font-bold text-[#f1f4f8] uppercase tracking-wider flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5 text-[#38bdf8]" />
              Top Leadership in This Scan
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => handleCopyTv('Top Sectors', topSectors.map((s) => s.tv_str).join(','))}
                className="px-2 py-0.5 rounded text-[11px] font-medium bg-[#151f2b] text-[#74a9ff] border border-[#263447] hover:border-[#74a9ff] transition flex items-center gap-1"
                title="Copy all stocks in top 3 sectors formatted for TradingView (Rule 1 Compliant)"
              >
                {copiedLabel === 'Top Sectors' ? <Check className="w-3 h-3 text-[#45d483]" /> : <Copy className="w-3 h-3" />}
                <span>Copy Top Sectors</span>
              </button>
              <button
                onClick={() => handleCopyTv('Top Industries', topIndustries.map((i) => i.tv_str).join(','))}
                className="px-2 py-0.5 rounded text-[11px] font-medium bg-[#151f2b] text-[#a855f7] border border-[#263447] hover:border-[#a855f7] transition flex items-center gap-1"
                title="Copy all stocks in top 3 industries formatted for TradingView (Rule 1 Compliant)"
              >
                {copiedLabel === 'Top Industries' ? <Check className="w-3 h-3 text-[#45d483]" /> : <Copy className="w-3 h-3" />}
                <span>Copy Top Industries</span>
              </button>
            </div>
          </div>

          {/* Cards Grid: Top 3 Sectors + Top 3 Industries */}
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2">
            {topSectors.map((s, idx) => (
              <div
                key={s.sector}
                className="p-2 rounded-md bg-[#0f1724] border border-[#1f2b3c] hover:border-[#38bdf8]/50 transition flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-center justify-between text-[9px] font-bold text-[#38bdf8] uppercase tracking-wider mb-0.5">
                    <span>Sector #{idx + 1}</span>
                    <span className="text-[#98a7ba] font-mono">RS {s.avg_rs.toFixed(0)}</span>
                  </div>
                  <div className="text-xs font-bold text-white truncate" title={s.sector}>
                    {s.sector}
                  </div>
                  <div className="text-[10px] text-[#98a7ba] font-mono mt-0.5">
                    {s.stock_count} names
                  </div>
                </div>
                <button
                  onClick={() => handleCopyTv(`Sector ${s.sector}`, s.tv_str)}
                  className="mt-1.5 w-full py-0.5 text-[10px] font-semibold rounded bg-[#162235] text-[#38bdf8] hover:bg-[#38bdf8] hover:text-[#080c14] border border-[#253c5e] transition flex items-center justify-center gap-1"
                >
                  {copiedLabel === `Sector ${s.sector}` ? <Check className="w-2.5 h-2.5 text-[#45d483]" /> : <Copy className="w-2.5 h-2.5" />}
                  <span>{copiedLabel === `Sector ${s.sector}` ? 'Copied' : 'Copy TV'}</span>
                </button>
              </div>
            ))}

            {topIndustries.map((ind, idx) => (
              <div
                key={ind.industry}
                className="p-2 rounded-md bg-[#0f1724] border border-[#1f2b3c] hover:border-[#a855f7]/50 transition flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-center justify-between text-[9px] font-bold text-[#a855f7] uppercase tracking-wider mb-0.5">
                    <span>Industry #{idx + 1}</span>
                    <span className="text-[#98a7ba] font-mono">RS {ind.avg_rs.toFixed(0)}</span>
                  </div>
                  <div className="text-xs font-bold text-white truncate" title={ind.industry}>
                    {ind.industry}
                  </div>
                  <div className="text-[10px] text-[#98a7ba] font-mono mt-0.5 truncate">
                    {ind.stock_count} names · {ind.sector}
                  </div>
                </div>
                <button
                  onClick={() => handleCopyTv(`Industry ${ind.industry}`, ind.tv_str)}
                  className="mt-1.5 w-full py-0.5 text-[10px] font-semibold rounded bg-[#231735] text-[#a855f7] hover:bg-[#a855f7] hover:text-[#080c14] border border-[#3e2761] transition flex items-center justify-center gap-1"
                >
                  {copiedLabel === `Industry ${ind.industry}` ? <Check className="w-2.5 h-2.5 text-[#45d483]" /> : <Copy className="w-2.5 h-2.5" />}
                  <span>{copiedLabel === `Industry ${ind.industry}` ? 'Copied' : 'Copy TV'}</span>
                </button>
              </div>
            ))}
          </div>

          {/* Sector Quick Filter Chips Bar */}
          {sectorDistribution.length > 0 && (
            <div className="pt-1 flex items-center gap-1.5 overflow-x-auto no-scrollbar text-[11px]">
              <span className="text-[10px] text-[#7888a0] font-semibold uppercase tracking-wider shrink-0 mr-1">
                Filter Sector:
              </span>
              <button
                onClick={() => setSelectedSectorFilter(null)}
                className={`px-2 py-0.5 rounded-full font-medium transition shrink-0 ${
                  selectedSectorFilter === null
                    ? 'bg-[#38bdf8] text-[#080c14] font-bold'
                    : 'bg-[#151f2b] text-[#98a7ba] hover:text-white border border-[#263447]'
                }`}
              >
                All ({candidates.length})
              </button>
              {sectorDistribution.map((s) => (
                <button
                  key={s.sector}
                  onClick={() => setSelectedSectorFilter(selectedSectorFilter === s.sector ? null : s.sector)}
                  className={`px-2 py-0.5 rounded-full font-medium transition shrink-0 flex items-center gap-1 ${
                    selectedSectorFilter === s.sector
                      ? 'bg-[#38bdf8] text-[#080c14] font-bold'
                      : 'bg-[#151f2b] text-[#98a7ba] hover:text-white border border-[#263447]'
                  }`}
                >
                  <span>{s.sector}</span>
                  <span
                    className={`text-[10px] px-1 py-0.1 rounded font-mono ${
                      selectedSectorFilter === s.sector ? 'bg-[#080c14] text-[#38bdf8]' : 'bg-[#101721] text-[#6b7c93]'
                    }`}
                  >
                    {s.stock_count}
                  </span>
                </button>
              ))}
              {selectedSectorFilter && (
                <button
                  onClick={() => setSelectedSectorFilter(null)}
                  className="text-[10px] text-[#f43f5e] hover:underline shrink-0 ml-1 font-semibold"
                >
                  Clear filter
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* Grid with Interactive Column Sorting */}
      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="p-8 text-center text-[#98a7ba] text-xs">
            Scanning 589 sessions of indicator history across Indian stock universe...
          </div>
        ) : sortedCandidates.length === 0 ? (
          <div className="p-8 text-center text-[#98a7ba] text-xs">
            No momentum candidates matching these strict filters today. Try easing 52W high distance or stack constraints.
          </div>
        ) : (
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="bg-[#0e1522] text-[#98a7ba] uppercase font-mono text-[11px] tracking-wider border-b border-[#1f2b3c] sticky top-0 z-10 select-none">
                <th onClick={() => handleSort('symbol')} className="py-2 px-3 font-semibold cursor-pointer hover:text-white">
                  Symbol {renderSortArrow('symbol')}
                </th>
                <th onClick={() => handleSort('sector')} className="py-2 px-3 font-semibold cursor-pointer hover:text-white">
                  Sector {renderSortArrow('sector')}
                </th>
                <th onClick={() => handleSort('trigger_date')} className="py-2 px-3 font-semibold text-center cursor-pointer hover:text-white" title="Date when momentum/volume breakout triggered">
                  Trigger {renderSortArrow('trigger_date')}
                </th>
                <th onClick={() => handleSort('cmp')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  CMP (₹) {renderSortArrow('cmp')}
                </th>
                <th onClick={() => handleSort('change_1d_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  1D % {renderSortArrow('change_1d_pct')}
                </th>
                <th onClick={() => handleSort('away_10ema_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  <InfoTooltip param="stretch" label="vs 10 EMA" /> {renderSortArrow('away_10ema_pct')}
                </th>
                <th onClick={() => handleSort('return_5d_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  5D % {renderSortArrow('return_5d_pct')}
                </th>
                <th onClick={() => handleSort('return_1m_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  1M % {renderSortArrow('return_1m_pct')}
                </th>
                <th onClick={() => handleSort('rs_percentile')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  <InfoTooltip param="rs" label="RS Rating" /> {renderSortArrow('rs_percentile')}
                </th>
                <th onClick={() => handleSort('dist_52w_high_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  <InfoTooltip param="pivot" label="Away 52W High" /> {renderSortArrow('dist_52w_high_pct')}
                </th>
                <th onClick={() => handleSort('dist_52w_low_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  Above 52W Low {renderSortArrow('dist_52w_low_pct')}
                </th>
                <th onClick={() => handleSort('volume')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  Day Vol {renderSortArrow('volume')}
                </th>
                <th onClick={() => handleSort('avg_volume_20d')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  20D Avg Vol {renderSortArrow('avg_volume_20d')}
                </th>
                <th onClick={() => handleSort('rvol')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  <InfoTooltip param="rvol" label="RVOL" /> {renderSortArrow('rvol')}
                </th>
                <th onClick={() => handleSort('delivery_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  <InfoTooltip param="delivery" label="Delivery %" /> {renderSortArrow('delivery_pct')}
                </th>
                <th className="py-2 px-3 text-center">Indicators</th>
                <th className="py-2 px-3 text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#151f2b] font-mono">
              {sortedCandidates.map((c) => {
                const isSelected = selectedSymbol === c.symbol;
                return (
                  <tr
                    key={c.symbol}
                    onClick={() => onSelectSymbol(c.symbol)}
                    className={`cursor-pointer transition hover:bg-[#151f2b]/80 ${
                      isSelected ? 'bg-[#152336] border-l-2 border-[#38bdf8]' : ''
                    }`}
                  >
                    <td className="py-2 px-3 font-bold text-[#f1f4f8]">
                      <a
                        href={`https://www.tradingview.com/chart/?symbol=NSE:${c.symbol.replace(/-/g, '_')}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="text-[#38bdf8] hover:underline inline-flex items-center gap-1 group font-mono font-bold"
                        title={`Open ${c.symbol} on TradingView`}
                      >
                        <span>{c.symbol}</span>
                        <ExternalLink className="w-2.5 h-2.5 opacity-60 group-hover:opacity-100" />
                      </a>
                    </td>
                    <td className="py-2 px-3 text-[#98a7ba] font-sans truncate max-w-[130px]">
                      {c.sector}
                    </td>
                    <td className="py-2 px-3 text-center text-[#74a9ff] font-mono text-[11px] whitespace-nowrap">
                      {c.trigger_date || '—'}
                    </td>
                    <td className="py-2 px-3 text-right font-medium text-[#f1f4f8]">
                      ₹{c.cmp.toFixed(2)}
                    </td>
                    <td className={`py-2 px-3 text-right font-semibold ${
                      c.change_1d_pct >= 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'
                    }`}>
                      {c.change_1d_pct >= 0 ? `+${c.change_1d_pct.toFixed(2)}%` : `${c.change_1d_pct.toFixed(2)}%`}
                    </td>
                    <td className="py-2 px-3 text-right">
                      <span
                        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-mono font-semibold ${
                          c.away_10ema_pct == null
                            ? 'text-[#94a3b8]'
                            : c.away_10ema_pct >= 0 && c.away_10ema_pct <= 2
                            ? 'bg-[#10b981]/15 text-[#34d399] border border-[#10b981]/30'
                            : c.away_10ema_pct > 2 && c.away_10ema_pct <= 5
                            ? 'bg-[#0284c7]/15 text-[#38bdf8] border border-[#0284c7]/30'
                            : c.away_10ema_pct > 5 && c.away_10ema_pct <= 10
                            ? 'bg-[#475569]/20 text-[#cbd5e1] border border-[#475569]/30'
                            : 'bg-[#f43f5e]/15 text-[#fb7185] border border-[#f43f5e]/30'
                        }`}
                        title={`Coil Bucket: ${c.bucket || '0_2%'}`}
                      >
                        {signedPct(c.away_10ema_pct)}
                        {c.away_10ema_pct != null && c.away_10ema_pct >= 0 && c.away_10ema_pct <= 2 && <span className="text-[9px]">🎯</span>}
                        {c.away_10ema_pct != null && c.away_10ema_pct > 10 && <span className="text-[9px]">⚠️</span>}
                      </span>
                    </td>
                    <td className={`py-2 px-3 text-right ${
                      c.return_5d_pct >= 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'
                    }`}>
                      {c.return_5d_pct >= 0 ? `+${c.return_5d_pct.toFixed(1)}%` : `${c.return_5d_pct.toFixed(1)}%`}
                    </td>
                    <td className={`py-2 px-3 text-right ${
                      c.return_1m_pct >= 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'
                    }`}>
                      {c.return_1m_pct >= 0 ? `+${c.return_1m_pct.toFixed(1)}%` : `${c.return_1m_pct.toFixed(1)}%`}
                    </td>
                    <td className="py-2 px-3 text-right">
                      {c.rs_percentile == null ? DASH : renderRsBadge(c.rs_percentile)}
                    </td>
                    <td className="py-2 px-3 text-right text-[#f0be58] font-medium">
                      {c.dist_52w_high_pct >= 0 ? `+${c.dist_52w_high_pct.toFixed(1)}%` : `${c.dist_52w_high_pct.toFixed(1)}%`}
                    </td>
                    <td className="py-2 px-3 text-right text-[#45d483] font-medium">
                      +{c.dist_52w_low_pct.toFixed(1)}%
                    </td>
                    <td className="py-2 px-3 text-right font-medium text-[#f1f4f8]">
                      {formatVol(c.volume)}
                    </td>
                    <td className="py-2 px-3 text-right text-[#98a7ba]">
                      {formatVol(c.avg_volume_20d)}
                    </td>
                    <td className="py-2 px-3 text-right">
                      {renderRvolBadge(c.rvol)}
                    </td>
                    <td className="py-2 px-3 text-right">
                      {c.delivery_pct == null ? DASH : renderDeliveryBadge(c.delivery_pct, undefined, c.delivery_spike)}
                    </td>
                    <td className="py-2 px-3 text-center">
                      <div className="flex items-center justify-center gap-1">
                        {c.bullish_stack && (
                          <span className="px-1.5 py-0.5 rounded text-[9px] bg-[#163526] text-[#45d483] font-mono" title="Bullish EMA Stack">
                            10&gt;20&gt;50
                          </span>
                        )}
                        {c.delivery_spike && (
                          <span className="px-1.5 py-0.5 rounded text-[9px] bg-[#1e293b] text-[#38bdf8] font-mono" title="Delivery Spike">
                            THRUST
                          </span>
                        )}
                        {c.coiling && (
                          <span className="px-1.5 py-0.5 rounded text-[9px] bg-[#33240e] text-[#f0be58] font-mono" title="NR7 / Coiling">
                            NR7
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="py-2 px-3 text-center">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onAddToBasket(c.symbol);
                        }}
                        className="px-2 py-1 rounded bg-[#101721] hover:bg-[#163526] hover:text-[#45d483] border border-[#263447] text-[10px] transition flex items-center gap-1 mx-auto"
                        title="Add to active trade watchlist"
                      >
                        <Star className="w-3 h-3 text-[#f0be58]" />
                        <span>Watchlist</span>
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
