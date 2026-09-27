import React, { useState, useEffect, useMemo } from 'react';
import { DealsDeskResponse, TierDealRecord, FundLeaderboardRecord } from '../types';
import { ShieldAlert, TrendingUp, Users, DollarSign, Filter, Copy, Check, Star, ArrowUpDown, ArrowUp, ArrowDown, ExternalLink } from 'lucide-react';
import { sortData, SortConfig } from '../utils/tableSort';

interface Props {
  selectedSymbol: string | null;
  onSelectSymbol: (symbol: string) => void;
  onAddToBasket: (symbol: string) => void;
}

export const DealsWorkspace: React.FC<Props> = ({
  selectedSymbol,
  onSelectSymbol,
  onAddToBasket,
}) => {
  const [lookbackDays, setLookbackDays] = useState<number>(20);
  const [setupFilter, setSetupFilter] = useState<string>('ALL');
  const [activeTab, setActiveTab] = useState<
    'today' | 'play' | 'conviction' | 'fresh' | 'star' | 'leaderboard' | 'prop' | 'distribution'
  >('play');
  const [openFund, setOpenFund] = useState<string | null>(null);
  const [persistenceFilter, setPersistenceFilter] = useState<number>(0); // 0 = all, 2, 3, 4+

  const [data, setData] = useState<DealsDeskResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [copiedMsg, setCopiedMsg] = useState<string | null>(null);

  // Sorting
  const [sortConfig, setSortConfig] = useState<SortConfig<TierDealRecord>>({
    key: 'deal_days',
    direction: 'desc',
  });

  const fetchDeals = () => {
    setLoading(true);
    fetch(`/api/deals/institutional?lookback_days=${lookbackDays}&setup_filter=${setupFilter}`)
      .then((res) => res.json())
      .then((resData: DealsDeskResponse) => {
        setData(resData);
        const first = resData.play?.[0] || resData.conviction?.[0];
        if (first && !selectedSymbol) {
          onSelectSymbol(first.symbol);
        }
      })
      .catch((err) => console.error('Deals fetch error:', err))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchDeals();
  }, [lookbackDays, setupFilter]);

  const copyToClipboard = (text: string, label: string) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedMsg(label);
    setTimeout(() => setCopiedMsg(null), 2000);
  };

  const copySymbols = (symbols: string[], label: string, section?: string) => {
    const toks = symbols
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean)
      .map((s) => `NSE:${s.replace(/-/g, '_')}`);
    if (!toks.length) return;
    const payload = section ? `###${section},${toks.join(',')}` : toks.join(',');
    copyToClipboard(payload, label);
  };

  const handleSort = (key: keyof TierDealRecord) => {
    setSortConfig((prev) => {
      if (prev.key === key) {
        if (prev.direction === 'asc') return { key, direction: 'desc' };
        if (prev.direction === 'desc') return { key: null, direction: null };
      }
      return { key, direction: 'asc' };
    });
  };

  const renderSortArrow = (key: keyof TierDealRecord) => {
    if (sortConfig.key !== key) {
      return <ArrowUpDown className="w-3 h-3 text-[#55657e] inline ml-1 opacity-60" />;
    }
    return sortConfig.direction === 'asc' ? (
      <ArrowUp className="w-3 h-3 text-[#74a9ff] inline ml-1" />
    ) : (
      <ArrowDown className="w-3 h-3 text-[#74a9ff] inline ml-1" />
    );
  };

  // Get current active records
  const currentRecords: TierDealRecord[] = useMemo(() => {
    if (!data) return [];
    let list: TierDealRecord[] = [];
    if (activeTab === 'play' || activeTab === 'conviction' || activeTab === 'fresh') {
      list = data.play && data.play.length ? data.play : [...data.conviction, ...data.fresh_radar];
    } else if (activeTab === 'prop') list = data.prop_only;
    else if (activeTab === 'distribution') list = data.distribution;

    if (persistenceFilter > 0) {
      if (persistenceFilter === 4) list = list.filter((r) => r.deal_days >= 4);
      else list = list.filter((r) => r.deal_days === persistenceFilter);
    }
    return sortData(list, sortConfig.key, sortConfig.direction);
  }, [data, activeTab, persistenceFilter, sortConfig]);

  return (
    <div className="flex-1 flex flex-col h-full bg-[#080c14] overflow-hidden">
      {/* Top Controls Toolbar: Lookback & Setup Filters */}
      <div className="px-4 py-2.5 bg-[#0e1522] border-b border-[#1f2b3c] flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          {/* Lookback Selector */}
          <div className="flex items-center gap-1 bg-[#131b26] p-1 rounded-md border border-[#1f2b3c]">
            <span className="text-[11px] text-[#98a7ba] font-semibold px-1.5 uppercase tracking-wider">Lookback:</span>
            {[
              { days: 10, label: '10 Days' },
              { days: 20, label: '20 Days (Default)' },
              { days: 30, label: '30 Days' },
            ].map((b) => (
              <button
                key={b.days}
                onClick={() => setLookbackDays(b.days)}
                className={`px-2.5 py-0.5 text-xs rounded font-medium transition ${
                  lookbackDays === b.days
                    ? 'bg-[#74a9ff] text-[#080c14] font-bold shadow'
                    : 'text-[#98a7ba] hover:text-white'
                }`}
              >
                {b.label}
              </button>
            ))}
          </div>

          {/* Setup Filter */}
          <div className="flex items-center gap-1 bg-[#131b26] p-1 rounded-md border border-[#1f2b3c]">
            <span className="text-[11px] text-[#98a7ba] font-semibold px-1.5 uppercase tracking-wider">Setup:</span>
            {[
              { id: 'ALL', label: 'All Setups' },
              { id: 'ABOVE_200', label: 'Stage 2 (>200 EMA)' },
              { id: 'TURNAROUND', label: 'Base / Turnaround' },
            ].map((s) => (
              <button
                key={s.id}
                onClick={() => setSetupFilter(s.id)}
                className={`px-2.5 py-0.5 text-xs rounded font-medium transition ${
                  setupFilter === s.id
                    ? 'bg-[#f0be58] text-[#080c14] font-bold shadow'
                    : 'text-[#98a7ba] hover:text-white'
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        {/* Quick Export Buttons */}
        <div className="flex items-center gap-2 flex-wrap">
          {(data?.play?.length || data?.counts?.play) ? (
            <button
              onClick={() =>
                copySymbols(
                  (data.play && data.play.length ? data.play : [...data.conviction, ...data.fresh_radar]).map((r) => r.symbol),
                  'Play TV',
                  'Play'
                )
              }
              className="flex items-center gap-1 px-2.5 py-1 rounded text-xs font-bold bg-[#182b46] text-[#74a9ff] border border-[#2b4c7e] hover:border-[#74a9ff]"
            >
              {copiedMsg === 'Play TV' ? <Check className="w-3 h-3 text-[#45d483]" /> : <Copy className="w-3 h-3" />}
              <span>Copy Play ({data.counts.play || data.play?.length || 0})</span>
            </button>
          ) : null}

          {data?.prop_only?.length ? (
            <button
              onClick={() => copySymbols(data.prop_only.map((r) => r.symbol), 'HFT TV', '🎯 Prop HFT Churn')}
              className="flex items-center gap-1 px-2.5 py-1 rounded text-xs font-semibold bg-[#3a2a12] text-[#f0be58] border border-[#6b5420] hover:border-[#f0be58]"
            >
              {copiedMsg === 'HFT TV' ? <Check className="w-3 h-3 text-[#45d483]" /> : <Copy className="w-3 h-3" />}
              <span>Copy HFT ({data.prop_only.length})</span>
            </button>
          ) : null}

          {data?.tv_strings?.star_radar_tv && (
            <button
              onClick={() => copyToClipboard(data.tv_strings.star_radar_tv, 'Star Radar TV')}
              className="flex items-center gap-1 px-2.5 py-1 rounded text-xs font-semibold bg-[#33240e] text-[#f0be58] border border-[#523d1d] hover:border-[#f0be58]"
            >
              {copiedMsg === 'Star Radar TV' ? <Check className="w-3 h-3 text-[#45d483]" /> : <Copy className="w-3 h-3" />}
              <span>Copy Star Radar</span>
            </button>
          )}
        </div>
      </div>

      {/* 3-Tier Classification Navigation Tabs */}
      <div className="px-4 py-1.5 bg-[#090d16] border-b border-[#1f2b3c] flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-1.5 flex-wrap">
          <button
            onClick={() => { setActiveTab('today'); setPersistenceFilter(0); }}
            className={`px-3 py-1.5 text-xs rounded-t font-semibold transition border-b-2 ${
              activeTab === 'today'
                ? 'bg-[#152336] text-[#f0be58] border-[#f0be58]'
                : 'text-[#98a7ba] border-transparent hover:text-white'
            }`}
          >
            Today ({data?.counts?.today || 0})
          </button>
          <button
            onClick={() => { setActiveTab('play'); setPersistenceFilter(0); }}
            className={`px-3 py-1.5 text-xs rounded-t font-semibold transition border-b-2 ${
              activeTab === 'play'
                ? 'bg-[#152336] text-[#45d483] border-[#45d483]'
                : 'text-[#98a7ba] border-transparent hover:text-white'
            }`}
          >
            Play ({data?.counts?.play || 0})
          </button>
          <button
            onClick={() => setActiveTab('star')}
            className={`px-3 py-1.5 text-xs rounded-t font-semibold transition border-b-2 ${
              activeTab === 'star'
                ? 'bg-[#152336] text-[#f0be58] border-[#f0be58]'
                : 'text-[#98a7ba] border-transparent hover:text-white'
            }`}
          >
            ⭐ Star Fund Radar ({data?.counts?.star_deals || 0})
          </button>
          <button
            onClick={() => setActiveTab('leaderboard')}
            className={`px-3 py-1.5 text-xs rounded-t font-semibold transition border-b-2 ${
              activeTab === 'leaderboard'
                ? 'bg-[#152336] text-[#a855f7] border-[#a855f7]'
                : 'text-[#98a7ba] border-transparent hover:text-white'
            }`}
          >
            🏆 Fund Leaderboard &amp; Alpha ({data?.counts?.funds || 0})
          </button>
          <button
            onClick={() => { setActiveTab('prop'); setPersistenceFilter(0); }}
            className={`px-3 py-1.5 text-xs rounded-t font-semibold transition border-b-2 ${
              activeTab === 'prop'
                ? 'bg-[#152336] text-[#f59e0b] border-[#f59e0b]'
                : 'text-[#98a7ba] border-transparent hover:text-white'
            }`}
          >
            🎯 Tier 3A: Prop HFT ({data?.counts?.prop_only || 0})
          </button>
          <button
            onClick={() => { setActiveTab('distribution'); setPersistenceFilter(0); }}
            className={`px-3 py-1.5 text-xs rounded-t font-semibold transition border-b-2 ${
              activeTab === 'distribution'
                ? 'bg-[#152336] text-[#f43f5e] border-[#f43f5e]'
                : 'text-[#98a7ba] border-transparent hover:text-white'
            }`}
          >
            🔴 Distribution ({data?.counts?.distribution || 0})
          </button>
        </div>

        {/* Multi-Day Persistence Pills (Active inside Tier 1) */}
        {(activeTab === 'play' || activeTab === 'conviction') && (
          <div className="flex items-center gap-1 text-xs">
            <span className="text-[#7888a0] text-[10px] uppercase font-mono mr-1">Sessions:</span>
            {[
              { filter: 0, label: 'All' },
              { filter: 4, label: `4+ Days (${data?.counts?.four_plus_days || 0})` },
              { filter: 3, label: `3 Days (${data?.counts?.three_days || 0})` },
              { filter: 2, label: `2 Days (${data?.counts?.two_days || 0})` },
            ].map((p) => (
              <button
                key={p.filter}
                onClick={() => setPersistenceFilter(p.filter)}
                className={`px-2 py-0.5 rounded text-[10px] font-mono border ${
                  persistenceFilter === p.filter
                    ? 'bg-[#163526] text-[#45d483] border-[#235338] font-bold'
                    : 'bg-[#101721] text-[#98a7ba] border-[#263447]'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="p-8 text-center text-[#98a7ba] text-xs">
            Aggregating multi-session block and bulk deal accumulation across {lookbackDays} sessions...
          </div>
        ) : activeTab === 'today' ? (
          <div className="p-4 space-y-3">
            <div className="p-3 rounded-lg bg-[#101721] border border-[#1f2b3c] text-xs text-[#98a7ba]">
              <span className="text-[#f0be58] font-bold">Today&apos;s prints</span> on the latest NSE bulk/block tape, mcap ≥ ₹1,000 Cr. Matched buy=sell on the same name is often a transfer, not new money.
            </div>
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-[#0e1522] text-[#98a7ba] uppercase font-mono text-[11px] border-b border-[#1f2b3c] sticky top-0">
                  <th className="py-2 px-3">Symbol</th>
                  <th className="py-2 px-3">Client / House</th>
                  <th className="py-2 px-3">Side</th>
                  <th className="py-2 px-3 text-right">₹ Cr</th>
                  <th className="py-2 px-3 text-right">Price</th>
                  <th className="py-2 px-3">Clientele</th>
                  <th className="py-2 px-3 text-right">MCap</th>
                  <th className="py-2 px-3">Sector</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#151f2b] font-mono">
                {(data?.today_deals || []).map((td, i) => (
                  <tr
                    key={`${td.symbol}-${td.client_name}-${i}`}
                    onClick={() => onSelectSymbol(td.symbol)}
                    className="cursor-pointer hover:bg-[#151f2b] transition"
                  >
                    <td className="py-2 px-3 font-bold text-[#38bdf8]">{td.symbol}</td>
                    <td className="py-2 px-3 text-[#c5d1e0] font-sans">
                      <div>{td.fund_house || td.client_name}</div>
                      {td.fund_house && td.fund_house !== td.client_name && (
                        <div className="text-[10px] text-[#64748b]">{td.client_name}</div>
                      )}
                    </td>
                    <td className={`py-2 px-3 font-bold ${td.side === 'BUY' ? 'text-[#10b981]' : 'text-[#f43f5e]'}`}>
                      {td.side}
                    </td>
                    <td className="py-2 px-3 text-right text-[#f0be58] font-bold">₹{td.deal_cr.toFixed(1)}</td>
                    <td className="py-2 px-3 text-right">₹{td.price.toFixed(2)}</td>
                    <td className="py-2 px-3 text-[#98a7ba]">
                      {td.clientele}
                      {td.is_prop ? ' · PROP' : ''}
                    </td>
                    <td className="py-2 px-3 text-right text-[#98a7ba]">₹{td.mcap_cr.toFixed(0)} Cr</td>
                    <td className="py-2 px-3 text-[#98a7ba] font-sans">{td.sector}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : activeTab === 'star' ? (
          <div className="p-4 space-y-3">
            <div className="p-3 rounded-lg bg-[#101721] border border-[#1f2b3c] text-xs text-[#98a7ba]">
              <span className="text-[#f0be58] font-bold">Star Fund Radar:</span> recent prints by high-score houses. Click a fund on the Leaderboard tab to see every name they printed in this window (net buy vs sell). This is the NSE bulk/block tape, not a full holdings file.
            </div>
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-[#0e1522] text-[#98a7ba] uppercase font-mono text-[11px] border-b border-[#1f2b3c] sticky top-0">
                  <th className="py-2 px-3">Symbol</th>
                  <th className="py-2 px-3">Fund House</th>
                  <th className="py-2 px-3">Tier</th>
                  <th className="py-2 px-3 text-right">Win Rate</th>
                  <th className="py-2 px-3">Date</th>
                  <th className="py-2 px-3 text-right">Deal Price</th>
                  <th className="py-2 px-3 text-right">CMP</th>
                  <th className="py-2 px-3 text-right">Gain %</th>
                  <th className="py-2 px-3 text-right">Peak Runup</th>
                  <th className="py-2 px-3 text-right">Holding Days</th>
                  <th className="py-2 px-3 text-right">Deal Value</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#151f2b] font-mono">
                {data?.star_radar.map((sd, i) => (
                  <tr
                    key={i}
                    onClick={() => onSelectSymbol(sd.symbol)}
                    className="cursor-pointer hover:bg-[#151f2b] transition"
                  >
                    <td className="py-2 px-3 font-bold text-[#f1f4f8]">
                      <a
                        href={`https://www.tradingview.com/chart/?symbol=NSE:${sd.symbol.replace(/-/g, '_')}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="text-[#38bdf8] hover:underline inline-flex items-center gap-1 group font-mono font-bold"
                        title={`Open ${sd.symbol} on TradingView`}
                      >
                        <span>{sd.symbol}</span>
                        <ExternalLink className="w-2.5 h-2.5 opacity-60 group-hover:opacity-100" />
                      </a>
                    </td>
                    <td className="py-2 px-3 text-[#c5d1e0] font-sans font-medium">{sd.fund_house}</td>
                    <td className="py-2 px-3"><span className="px-1.5 py-0.5 rounded text-[10px] bg-[#33240e] text-[#f0be58]">{sd.tier}</span></td>
                    <td className="py-2 px-3 text-right text-[#45d483] font-bold">{sd.win_rate}%</td>
                    <td className="py-2 px-3 text-[#98a7ba]">{sd.deal_date}</td>
                    <td className="py-2 px-3 text-right text-[#98a7ba]">₹{sd.deal_price.toFixed(2)}</td>
                    <td className="py-2 px-3 text-right font-medium text-[#f1f4f8]">₹{sd.cmp.toFixed(2)}</td>
                    <td className={`py-2 px-3 text-right font-bold ${sd.gain_pct >= 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'}`}>
                      {sd.gain_pct >= 0 ? `+${sd.gain_pct.toFixed(1)}%` : `${sd.gain_pct.toFixed(1)}%`}
                    </td>
                    <td className="py-2 px-3 text-right text-[#10b981]">+{sd.peak_runup.toFixed(1)}%</td>
                    <td className="py-2 px-3 text-right text-[#98a7ba]">{sd.holding_days}d</td>
                    <td className="py-2 px-3 text-right text-[#f0be58] font-bold">₹{sd.deal_cr.toFixed(1)}Cr</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : activeTab === 'leaderboard' ? (
          <div className="p-4 space-y-3">
            <div className="p-3 rounded-lg bg-[#101721] border border-[#1f2b3c] text-xs text-[#98a7ba]">
              <span className="text-[#a855f7] font-bold">Fund Leaderboard:</span> click a house to open the names they printed in this window. Bets = print count. Names = unique stocks. Net long = buy ₹ minus sell ₹ still positive. NSE bulk/block is not a full portfolio file.
            </div>
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-[#0e1522] text-[#98a7ba] uppercase font-mono text-[11px] border-b border-[#1f2b3c] sticky top-0">
                  <th className="py-2 px-3">Fund House</th>
                  <th className="py-2 px-3">Tier</th>
                  <th className="py-2 px-3 text-right">Catalyst</th>
                  <th className="py-2 px-3 text-right">20D Win</th>
                  <th className="py-2 px-3 text-right">Avg Peak</th>
                  <th className="py-2 px-3 text-right">Bets</th>
                  <th className="py-2 px-3 text-right">Names</th>
                  <th className="py-2 px-3 text-right">Net long</th>
                  <th className="py-2 px-3 text-right">₹ Cr</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#151f2b] font-mono">
                {data?.fund_leaderboard.map((fl) => {
                  const open = openFund === fl.fund_house;
                  const holds = fl.holdings || [];
                  return (
                    <React.Fragment key={fl.fund_house}>
                      <tr
                        className="hover:bg-[#151f2b] transition cursor-pointer"
                        onClick={() => setOpenFund(open ? null : fl.fund_house)}
                      >
                        <td className="py-2 px-3 font-bold text-[#f1f4f8] font-sans">
                          {open ? '▾ ' : '▸ '}
                          {fl.fund_house}
                        </td>
                        <td className="py-2 px-3"><span className="px-1.5 py-0.5 rounded text-[10px] bg-[#1e293b] text-[#74a9ff]">{fl.tier}</span></td>
                        <td className="py-2 px-3 text-right text-[#f0be58] font-bold">{fl.catalyst_score.toFixed(1)}</td>
                        <td className="py-2 px-3 text-right text-[#45d483] font-bold">{fl.win_rate_20d}%</td>
                        <td className="py-2 px-3 text-right text-[#10b981]">+{fl.avg_runup.toFixed(1)}%</td>
                        <td className="py-2 px-3 text-right text-[#98a7ba]">{fl.bets_count}</td>
                        <td className="py-2 px-3 text-right text-[#c5d1e0] font-bold">{fl.names_count ?? holds.length}</td>
                        <td className="py-2 px-3 text-right text-[#38bdf8]">{fl.net_long_count ?? 0}</td>
                        <td className="py-2 px-3 text-right text-[#f0be58]">₹{(fl.total_cr || 0).toFixed(0)}</td>
                      </tr>
                      {open && (
                        <tr>
                          <td colSpan={9} className="bg-[#0a101a] px-4 py-3">
                            {holds.length === 0 ? (
                              <div className="text-[#7888a0] text-[11px]">No ≥ ₹5 Cr prints in this window for this house.</div>
                            ) : (
                              <table className="w-full text-left text-[11px]">
                                <thead>
                                  <tr className="text-[#7888a0] uppercase">
                                    <th className="py-1">Symbol</th>
                                    <th className="py-1 text-right">Net ₹ Cr</th>
                                    <th className="py-1 text-right">Buy</th>
                                    <th className="py-1 text-right">Sell</th>
                                    <th className="py-1">Last</th>
                                    <th className="py-1">Side</th>
                                    <th className="py-1 text-right">Ret</th>
                                    <th className="py-1 text-right">Prints</th>
                                    <th className="py-1">Sector</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {holds.map((h) => (
                                    <tr
                                      key={h.symbol}
                                      className="cursor-pointer hover:bg-[#151f2b]"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        onSelectSymbol(h.symbol);
                                      }}
                                    >
                                      <td className="py-1 font-bold text-[#38bdf8]">{h.symbol}</td>
                                      <td className={`py-1 text-right font-bold ${h.net_cr >= 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'}`}>
                                        {h.net_cr >= 0 ? '+' : ''}{h.net_cr.toFixed(1)}
                                      </td>
                                      <td className="py-1 text-right text-[#98a7ba]">{h.buy_cr.toFixed(1)}</td>
                                      <td className="py-1 text-right text-[#98a7ba]">{h.sell_cr.toFixed(1)}</td>
                                      <td className="py-1 text-[#98a7ba]">{h.last_date}</td>
                                      <td className={h.last_side === 'BUY' ? 'text-[#10b981]' : 'text-[#f43f5e]'}>{h.last_side}</td>
                                      <td className={`py-1 text-right ${ (h.ret_pct || 0) >= 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'}`}>
                                        {h.ret_pct == null ? '—' : `${h.ret_pct >= 0 ? '+' : ''}${h.ret_pct.toFixed(1)}%`}
                                      </td>
                                      <td className="py-1 text-right">{h.prints}</td>
                                      <td className="py-1 text-[#98a7ba] font-sans">{h.sector}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            )}
                            {holds.length > 0 && (
                              <button
                                className="mt-2 px-2 py-1 text-[10px] rounded bg-[#182b46] text-[#74a9ff] border border-[#2b4c7e]"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  copyToClipboard(
                                    holds.map((h) => `NSE:${h.symbol}`).join(', '),
                                    `${fl.fund_house} TV`
                                  );
                                }}
                              >
                                Copy {holds.length} symbols
                              </button>
                            )}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          /* Multi-Session Accumulation Table View */
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="bg-[#0e1522] text-[#98a7ba] uppercase font-mono text-[11px] tracking-wider border-b border-[#1f2b3c] sticky top-0 z-10 select-none">
                <th onClick={() => handleSort('symbol')} className="py-2 px-3 font-semibold cursor-pointer hover:text-white">
                  Symbol {renderSortArrow('symbol')}
                </th>
                <th onClick={() => handleSort('play_reason')} className="py-2 px-3 font-semibold cursor-pointer hover:text-white">
                  Why {renderSortArrow('play_reason')}
                </th>
                <th onClick={() => handleSort('trend')} className="py-2 px-3 font-semibold cursor-pointer hover:text-white">
                  Trend {renderSortArrow('trend')}
                </th>
                <th onClick={() => handleSort('deal_days')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  Deal Days {renderSortArrow('deal_days')}
                </th>
                <th onClick={() => handleSort('clientele')} className="py-2 px-3 font-semibold cursor-pointer hover:text-white">
                  Clientele {renderSortArrow('clientele')}
                </th>
                <th onClick={() => handleSort('net_cr')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  Net Flow (₹ Cr) {renderSortArrow('net_cr')}
                </th>
                <th onClick={() => handleSort('buy_cr')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  Buy Flow (₹ Cr) {renderSortArrow('buy_cr')}
                </th>
                <th onClick={() => handleSort('close_price')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  CMP (₹) {renderSortArrow('close_price')}
                </th>
                <th onClick={() => handleSort('away_52w_high_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  Away 52W High {renderSortArrow('away_52w_high_pct')}
                </th>
                <th onClick={() => handleSort('rs_percentile')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  RS Rating {renderSortArrow('rs_percentile')}
                </th>
                <th onClick={() => handleSort('market_cap_cr')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  MCap (Cr) {renderSortArrow('market_cap_cr')}
                </th>
                <th onClick={() => handleSort('sector')} className="py-2 px-3 font-semibold cursor-pointer hover:text-white">
                  Sector {renderSortArrow('sector')}
                </th>
                <th className="py-2 px-3 text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#151f2b] font-mono">
              {currentRecords.map((r) => {
                const isSelected = selectedSymbol === r.symbol;
                return (
                  <tr
                    key={r.symbol}
                    onClick={() => onSelectSymbol(r.symbol)}
                    className={`cursor-pointer transition hover:bg-[#151f2b]/80 ${
                      isSelected ? 'bg-[#152336] border-l-2 border-[#74a9ff]' : ''
                    }`}
                  >
                    <td className="py-2 px-3 font-bold text-[#f1f4f8]">
                      <a
                        href={`https://www.tradingview.com/chart/?symbol=NSE:${r.symbol.replace(/-/g, '_')}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="text-[#38bdf8] hover:underline inline-flex items-center gap-1 group font-mono font-bold"
                        title={`Open ${r.symbol} on TradingView`}
                      >
                        <span>{r.symbol}</span>
                        <ExternalLink className="w-2.5 h-2.5 opacity-60 group-hover:opacity-100" />
                      </a>
                    </td>
                    <td className="py-2 px-3">
                      <span className="px-1.5 py-0.5 rounded text-[10px] bg-[#152336] text-[#74a9ff] border border-[#2b4c7e]">
                        {r.play_reason || '—'}
                      </span>
                      {r.transfer_cr && r.transfer_cr > 0 ? (
                        <span className="ml-1 text-[10px] text-[#f0be58]">xfer {r.transfer_cr.toFixed(0)}</span>
                      ) : null}
                    </td>
                    <td className="py-2 px-3">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                        r.trend.includes('200')
                          ? 'bg-[#163526] text-[#45d483] border border-[#235338]'
                          : 'bg-[#33240e] text-[#f0be58] border-[#523d1d]'
                      }`}>
                        {r.trend}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-right font-bold text-[#f0be58]">
                      {r.deal_days} {r.deal_days > 1 ? 'Sessions ⚡' : 'Day'}
                    </td>
                    <td className="py-2 px-3 text-[#38bdf8] font-semibold">
                      {r.clientele}
                    </td>
                    <td className={`py-2 px-3 text-right font-bold ${
                      r.net_cr >= 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'
                    }`}>
                      {r.net_cr >= 0 ? `+₹${r.net_cr.toFixed(1)}Cr` : `-₹${Math.abs(r.net_cr).toFixed(1)}Cr`}
                    </td>
                    <td className="py-2 px-3 text-right text-[#10b981]">
                      ₹{r.buy_cr.toFixed(1)}Cr
                    </td>
                    <td className="py-2 px-3 text-right font-medium text-[#f1f4f8]">
                      ₹{r.close_price.toFixed(2)}
                    </td>
                    <td className="py-2 px-3 text-right text-[#f0be58]">
                      {r.away_52w_high_pct >= 0 ? `+${r.away_52w_high_pct.toFixed(1)}%` : `${r.away_52w_high_pct.toFixed(1)}%`}
                    </td>
                    <td className="py-2 px-3 text-right text-[#74a9ff]">
                      {r.rs_percentile.toFixed(1)}
                    </td>
                    <td className="py-2 px-3 text-right text-[#98a7ba]">
                      ₹{r.market_cap_cr.toLocaleString()}
                    </td>
                    <td className="py-2 px-3 text-[#98a7ba] font-sans truncate max-w-[120px]">
                      {r.sector}
                    </td>
                    <td className="py-2 px-3 text-center">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onAddToBasket(r.symbol);
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
