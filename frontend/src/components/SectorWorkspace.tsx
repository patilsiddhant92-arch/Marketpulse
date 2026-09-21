import React, { useState, useEffect, useMemo } from 'react';
import { SectorRecord } from '../types';
import { PieChart, ArrowUpDown, ArrowUp, ArrowDown, Filter, LayoutGrid, X, ExternalLink } from 'lucide-react';
import { sortData, SortConfig } from '../utils/tableSort';

interface Props {
  onSelectSymbol: (symbol: string) => void;
  onOpenMultiChart?: (symbols: string[]) => void;
}

const ROTATION_STATES = [
  {
    id: 'Leading',
    label: 'Leading',
    icon: '🚀',
    desc: 'Top RS rank + accelerating thrust',
    activeBg: 'bg-[#163526]',
    activeText: 'text-[#45d483]',
    activeBorder: 'border-[#45d483]',
    countColor: 'bg-[#235338] text-[#45d483]',
  },
  {
    id: 'Emerging',
    label: 'Emerging',
    icon: '🌱',
    desc: 'Fresh rank surge >= +5 with positive score',
    activeBg: 'bg-[#0f2d3d]',
    activeText: 'text-[#38bdf8]',
    activeBorder: 'border-[#38bdf8]',
    countColor: 'bg-[#163b4f] text-[#38bdf8]',
  },
  {
    id: 'Improving',
    label: 'Improving',
    icon: '📈',
    desc: 'Rank gain >= +2 & week return > 0',
    activeBg: 'bg-[#123238]',
    activeText: 'text-[#2dd4bf]',
    activeBorder: 'border-[#2dd4bf]',
    countColor: 'bg-[#1a444a] text-[#2dd4bf]',
  },
  {
    id: 'Weakening',
    label: 'Weakening',
    icon: '⚠️',
    desc: 'High rank but losing 5D score momentum',
    activeBg: 'bg-[#3a2f18]',
    activeText: 'text-[#f0be58]',
    activeBorder: 'border-[#f0be58]',
    countColor: 'bg-[#4d3e1d] text-[#f0be58]',
  },
  {
    id: 'Lagging',
    label: 'Lagging',
    icon: '📉',
    desc: 'Sub-par rank & negative relative strength',
    activeBg: 'bg-[#3a2027]',
    activeText: 'text-[#f27c84]',
    activeBorder: 'border-[#f27c84]',
    countColor: 'bg-[#4d2831] text-[#f27c84]',
  },
  {
    id: 'Neutral',
    label: 'Neutral',
    icon: '⚪',
    desc: 'Sideways consolidation',
    activeBg: 'bg-[#1e2633]',
    activeText: 'text-[#98a7ba]',
    activeBorder: 'border-[#98a7ba]',
    countColor: 'bg-[#2b3749] text-[#98a7ba]',
  },
];

export const SectorWorkspace: React.FC<Props> = ({ onSelectSymbol, onOpenMultiChart }) => {
  const [level, setLevel] = useState<string>('Broad Industry');
  const [lookbackDays, setLookbackDays] = useState<number>(30);
  const [sectors, setSectors] = useState<SectorRecord[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [selectedStates, setSelectedStates] = useState<string[]>([]);

  // Sorting
  const [sortConfig, setSortConfig] = useState<SortConfig<SectorRecord>>({
    key: 'rs_percentile',
    direction: 'desc',
  });

  const fetchSectors = () => {
    setLoading(true);
    fetch(`http://127.0.0.1:8000/api/sector/rotation?level=${encodeURIComponent(level)}&lookback_days=${lookbackDays}`)
      .then((res) => res.json())
      .then((data) => setSectors(data.sectors || []))
      .catch((err) => console.error('Sector fetch error:', err))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchSectors();
  }, [level, lookbackDays]);

  // Compute live counts per rotation state
  const stateCounts = useMemo(() => {
    const counts: Record<string, number> = {
      Leading: 0,
      Emerging: 0,
      Improving: 0,
      Weakening: 0,
      Lagging: 0,
      Neutral: 0,
    };
    sectors.forEach((s) => {
      const st = s.rotation_state || 'Neutral';
      counts[st] = (counts[st] || 0) + 1;
    });
    return counts;
  }, [sectors]);

  const toggleState = (stId: string) => {
    setSelectedStates((prev) => {
      if (prev.includes(stId)) {
        return prev.filter((s) => s !== stId);
      } else {
        return [...prev, stId];
      }
    });
  };

  const isStrongGroupsActive = useMemo(() => {
    return (
      selectedStates.length === 3 &&
      selectedStates.includes('Leading') &&
      selectedStates.includes('Emerging') &&
      selectedStates.includes('Improving')
    );
  }, [selectedStates]);

  const toggleStrongGroups = () => {
    if (isStrongGroupsActive) {
      setSelectedStates([]);
    } else {
      setSelectedStates(['Leading', 'Emerging', 'Improving']);
    }
  };

  const handleSort = (key: keyof SectorRecord) => {
    setSortConfig((prev) => {
      if (prev.key === key) {
        if (prev.direction === 'asc') return { key, direction: 'desc' };
        if (prev.direction === 'desc') return { key: null, direction: null };
      }
      return { key, direction: 'asc' };
    });
  };

  const filteredSectors = useMemo(() => {
    if (selectedStates.length === 0) return sectors;
    return sectors.filter((s) => selectedStates.includes(s.rotation_state));
  }, [sectors, selectedStates]);

  const sortedSectors = useMemo(() => {
    return sortData(filteredSectors, sortConfig.key, sortConfig.direction);
  }, [filteredSectors, sortConfig]);

  const renderSortArrow = (key: keyof SectorRecord) => {
    if (sortConfig.key !== key) {
      return <ArrowUpDown className="w-3 h-3 text-[#55657e] inline ml-1 opacity-60" />;
    }
    return sortConfig.direction === 'asc' ? (
      <ArrowUp className="w-3 h-3 text-[#45d483] inline ml-1" />
    ) : (
      <ArrowDown className="w-3 h-3 text-[#45d483] inline ml-1" />
    );
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[#080c14] overflow-hidden">
      {/* Top Header & Level/Horizon Selectors */}
      <div className="px-4 py-2.5 bg-[#0e1522] border-b border-[#1f2b3c] flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <PieChart className="w-4 h-4 text-[#45d483]" />
            <h2 className="text-xs font-bold text-[#f1f4f8] uppercase tracking-wider">
              Sector Rotation &amp; Historical Breadth Matrix
            </h2>
          </div>

          {/* Level Selector */}
          <div className="flex items-center gap-1 bg-[#131b26] p-1 rounded-md border border-[#1f2b3c]">
            <span className="text-[10px] text-[#98a7ba] font-semibold px-1.5 uppercase tracking-wider">Level:</span>
            {['Broad Industry', 'Sector', 'Industry'].map((lvl) => (
              <button
                key={lvl}
                onClick={() => setLevel(lvl)}
                className={`px-2.5 py-0.5 text-xs rounded font-medium transition ${
                  level === lvl
                    ? 'bg-[#45d483] text-[#080c14] font-bold shadow'
                    : 'text-[#98a7ba] hover:text-white'
                }`}
              >
                {lvl}
              </button>
            ))}
          </div>

          {/* Lookback Selector */}
          <div className="flex items-center gap-1 bg-[#131b26] p-1 rounded-md border border-[#1f2b3c]">
            <span className="text-[10px] text-[#98a7ba] font-semibold px-1.5 uppercase tracking-wider">Horizon:</span>
            {[
              { d: 10, label: '10D' },
              { d: 30, label: '30D' },
              { d: 63, label: '63D (1Q)' },
            ].map((h) => (
              <button
                key={h.d}
                onClick={() => setLookbackDays(h.d)}
                className={`px-2 py-0.5 text-xs rounded font-mono transition ${
                  lookbackDays === h.d
                    ? 'bg-[#38bdf8] text-[#080c14] font-bold'
                    : 'text-[#98a7ba] hover:text-white'
                }`}
              >
                {h.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-[#98a7ba] font-mono">
            {filteredSectors.length} of {sectors.length} Groups
          </span>
        </div>
      </div>

      {/* Rotation State Filter Chips Bar */}
      <div className="px-4 py-2 bg-[#0a101a] border-b border-[#1f2b3c] flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[10px] font-bold uppercase tracking-wider text-[#98a7ba] flex items-center gap-1 mr-1">
            <Filter className="w-3 h-3 text-[#d8ac3d]" /> State Chips:
          </span>

          {/* All States Button */}
          <button
            onClick={() => setSelectedStates([])}
            className={`px-2.5 py-1 text-xs rounded-full font-medium border transition flex items-center gap-1.5 ${
              selectedStates.length === 0
                ? 'bg-[#d8ac3d] text-[#080c14] font-bold border-[#d8ac3d] shadow-sm'
                : 'bg-[#131b26] text-[#98a7ba] border-[#1f2b3c] hover:border-[#d8ac3d]/50 hover:text-white'
            }`}
          >
            <span>All</span>
            <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-mono font-bold ${
              selectedStates.length === 0 ? 'bg-[#080c14] text-[#d8ac3d]' : 'bg-[#101721] text-[#6b7c93]'
            }`}>
              {sectors.length}
            </span>
          </button>

          {/* Strong Groups Preset (L+E+I) */}
          <button
            onClick={toggleStrongGroups}
            className={`px-2.5 py-1 text-xs rounded-full font-semibold border transition flex items-center gap-1.5 ${
              isStrongGroupsActive
                ? 'bg-[#1b3d2b] text-[#45d483] border-[#45d483] shadow-sm'
                : 'bg-[#131b26] text-[#c4d1e0] border-[#1f2b3c] hover:border-[#45d483]/60'
            }`}
            title="Leading + Emerging + Improving (Strong Money-Flow Tailwinds)"
          >
            <span>✨ Strong (L+E+I)</span>
            <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-[#101721] text-[#45d483] font-mono font-bold">
              {(stateCounts['Leading'] || 0) + (stateCounts['Emerging'] || 0) + (stateCounts['Improving'] || 0)}
            </span>
          </button>

          <span className="h-4 w-px bg-[#263447] mx-1"></span>

          {/* Individual State Filter Chips */}
          {ROTATION_STATES.map((st) => {
            const isSelected = selectedStates.includes(st.id);
            const count = stateCounts[st.id] || 0;
            return (
              <button
                key={st.id}
                onClick={() => toggleState(st.id)}
                title={st.desc}
                className={`px-2.5 py-1 text-xs rounded-full font-medium border transition flex items-center gap-1.5 select-none ${
                  isSelected
                    ? `${st.activeBg} ${st.activeText} ${st.activeBorder} font-bold shadow-sm`
                    : 'bg-[#131b26] text-[#8699b0] border-[#1f2b3c] hover:border-[#2d3e56] hover:text-[#c4d1e0]'
                }`}
              >
                <span>{st.icon}</span>
                <span>{st.label}</span>
                <span
                  className={`text-[10px] px-1.5 py-0.2 rounded-full font-mono font-bold ${
                    isSelected ? st.countColor : 'bg-[#101721] text-[#6b7c93]'
                  }`}
                >
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        {/* Clear Filter Button */}
        {selectedStates.length > 0 && (
          <button
            onClick={() => setSelectedStates([])}
            className="px-2.5 py-1 text-[11px] rounded bg-[#201217] text-[#f27c84] hover:bg-[#3a2027] border border-[#522933] transition flex items-center gap-1 font-semibold"
          >
            <X className="w-3 h-3" /> Clear ({selectedStates.length} active)
          </button>
        )}
      </div>

      {/* Sector Matrix Table with Sorting */}
      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="p-8 text-center text-[#98a7ba] text-xs">
            Calculating multi-horizon RS trends and breadth divergence across 589 sessions...
          </div>
        ) : sortedSectors.length === 0 ? (
          <div className="p-8 text-center text-[#98a7ba] text-xs">
            No groups match the selected rotation states ({selectedStates.join(', ')}).
            <button
              onClick={() => setSelectedStates([])}
              className="ml-2 text-[#d8ac3d] underline hover:text-white"
            >
              Reset filters
            </button>
          </div>
        ) : (
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="bg-[#0e1522] text-[#98a7ba] uppercase font-mono text-[11px] tracking-wider border-b border-[#1f2b3c] sticky top-0 z-10 select-none">
                <th onClick={() => handleSort('sector')} className="py-2 px-3 font-semibold cursor-pointer hover:text-white">
                  Group / Sector {renderSortArrow('sector')}
                </th>
                <th onClick={() => handleSort('rotation_state')} className="py-2 px-3 font-semibold text-center cursor-pointer hover:text-white">
                  Rotation State {renderSortArrow('rotation_state')}
                </th>
                <th onClick={() => handleSort('stage2_percentage')} className="py-2 px-3 font-semibold text-center cursor-pointer hover:text-white" title="Minervini Stage 2 Participation (Close > 200 EMA & Within 25% of 52W High)">
                  Stage 2 % {renderSortArrow('stage2_percentage')}
                </th>
                <th onClick={() => handleSort('rs_percentile')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  Avg RS {renderSortArrow('rs_percentile')}
                </th>
                <th onClick={() => handleSort('return_5d_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  5D RS % {renderSortArrow('return_5d_pct')}
                </th>
                <th onClick={() => handleSort('return_20d_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  1M RS % {renderSortArrow('return_20d_pct')}
                </th>
                <th onClick={() => handleSort('above_50_ema_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  &gt; 50 EMA {renderSortArrow('above_50_ema_pct')}
                </th>
                <th onClick={() => handleSort('above_200_ema_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  &gt; 200 EMA {renderSortArrow('above_200_ema_pct')}
                </th>
                <th onClick={() => handleSort('near_52w_highs')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  52W Highs {renderSortArrow('near_52w_highs')}
                </th>
                <th onClick={() => handleSort('turnover_share_delta_5d')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white" title="5D Turnover Share Surge & Institutional Money Flow">
                  Institutional Flow {renderSortArrow('turnover_share_delta_5d')}
                </th>
                <th className="py-2 px-3 font-semibold">Top Leaders / Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#151f2b] font-mono">
              {sortedSectors.map((s, idx) => {
                const s2Count = s.stage2_count || 0;
                const total = s.total_stocks || 1;
                const s2Pct = s.stage2_percentage || 0;
                const shareDelta5d = s.turnover_share_delta_5d || 0;

                return (
                  <tr key={idx} className="transition hover:bg-[#151f2b]/80">
                    <td className="py-2 px-3 font-bold text-[#f1f4f8] font-sans">
                      <div className="flex items-center gap-1.5">
                        <span>{s.sector}</span>
                        <span className="text-[10px] text-[#6b7c93] font-mono font-normal">
                          ({s.total_stocks} stocks)
                        </span>
                      </div>
                    </td>
                    <td className="py-2 px-3 text-center">
                      <span
                        className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold inline-flex items-center gap-1 ${
                          s.rotation_state === 'Leading'
                            ? 'bg-[#163526] text-[#45d483] border border-[#235338]'
                            : s.rotation_state === 'Emerging'
                            ? 'bg-[#0f2d3d] text-[#38bdf8] border border-[#1a4a63]'
                            : s.rotation_state === 'Improving'
                            ? 'bg-[#123238] text-[#2dd4bf] border border-[#1e535e]'
                            : s.rotation_state === 'Weakening'
                            ? 'bg-[#3a2f18] text-[#f0be58] border border-[#6b5423]'
                            : s.rotation_state === 'Lagging'
                            ? 'bg-[#3a2027] text-[#f27c84] border border-[#522933]'
                            : 'bg-[#1e2633] text-[#98a7ba] border border-[#2d3a4d]'
                        }`}
                      >
                        <span>
                          {s.rotation_state === 'Leading'
                            ? '🚀'
                            : s.rotation_state === 'Emerging'
                            ? '🌱'
                            : s.rotation_state === 'Improving'
                            ? '📈'
                            : s.rotation_state === 'Weakening'
                            ? '⚠️'
                            : s.rotation_state === 'Lagging'
                            ? '📉'
                            : '⚪'}
                        </span>
                        {s.rotation_state}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-center">
                      <div className="flex flex-col items-center gap-1">
                        <div className="flex items-center gap-1 text-[11px] font-bold">
                          <span className={s2Pct >= 50 ? 'text-[#45d483]' : s2Pct >= 30 ? 'text-[#38bdf8]' : 'text-[#98a7ba]'}>
                            {s2Count}/{total}
                          </span>
                          <span className="text-[10px] text-[#6b7c93]">({s2Pct.toFixed(0)}%)</span>
                        </div>
                        <div className="w-20 bg-[#162232] h-1.5 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${
                              s2Pct >= 50 ? 'bg-[#45d483]' : s2Pct >= 30 ? 'bg-[#38bdf8]' : 'bg-[#f0be58]'
                            }`}
                            style={{ width: `${Math.min(100, s2Pct)}%` }}
                          />
                        </div>
                      </div>
                    </td>
                    <td className="py-2 px-3 text-right">
                      <div className="flex flex-col items-end">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                            s.rs_percentile >= 75 ? 'bg-[#182b46] text-[#74a9ff]' : 'text-[#98a7ba]'
                          }`}
                        >
                          {s.rs_percentile.toFixed(1)}
                        </span>
                        {s.median_rs !== undefined && (
                          <span className="text-[9px] text-[#6b7c93] mt-0.5">
                            Med {s.median_rs.toFixed(0)}
                          </span>
                        )}
                      </div>
                    </td>
                    <td
                      className={`py-2 px-3 text-right font-semibold ${
                        s.return_5d_pct >= 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'
                      }`}
                    >
                      {s.return_5d_pct >= 0 ? `+${s.return_5d_pct.toFixed(1)}%` : `${s.return_5d_pct.toFixed(1)}%`}
                    </td>
                    <td
                      className={`py-2 px-3 text-right ${
                        s.return_20d_pct >= 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'
                      }`}
                    >
                      {s.return_20d_pct >= 0 ? `+${s.return_20d_pct.toFixed(1)}%` : `${s.return_20d_pct.toFixed(1)}%`}
                    </td>
                    <td className="py-2 px-3 text-right text-[#f0be58]">
                      {s.above_50_ema_pct.toFixed(1)}%
                    </td>
                    <td className="py-2 px-3 text-right text-[#45d483]">
                      {s.above_200_ema_pct.toFixed(1)}%
                    </td>
                    <td className="py-2 px-3 text-right font-bold text-[#38bdf8]">
                      {s.near_52w_highs}
                    </td>
                    <td className="py-2 px-3 text-right font-mono">
                      <div className="flex flex-col items-end">
                        <span className="text-xs text-[#f1f4f8] font-semibold">
                          ₹{s.turnover_1d_cr.toLocaleString()} Cr
                        </span>
                        <div className="flex items-center gap-1 mt-0.5">
                          {shareDelta5d >= 1.0 ? (
                            <span className="text-[9px] px-1.5 py-0.2 rounded font-bold bg-[#163526] text-[#45d483] border border-[#235338]">
                              🔥 +{shareDelta5d.toFixed(1)} pp
                            </span>
                          ) : shareDelta5d <= -1.0 ? (
                            <span className="text-[9px] px-1 py-0.2 rounded font-bold bg-[#33161c] text-[#f43f5e]">
                              {shareDelta5d.toFixed(1)} pp
                            </span>
                          ) : (
                            <span className="text-[9px] text-[#7888a0]">
                              {shareDelta5d >= 0 ? `+${shareDelta5d.toFixed(1)}` : shareDelta5d.toFixed(1)} pp
                            </span>
                          )}
                          {s.turnover_share_pct !== undefined && (
                            <span className="text-[9px] text-[#6b7c93]">
                              ({s.turnover_share_pct.toFixed(1)}%)
                            </span>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="py-2 px-3 font-sans">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {s.leader_chips && s.leader_chips.length > 0 ? (
                          s.leader_chips.map((chip) => (
                            <div
                              key={chip.symbol}
                              className="px-2 py-0.5 rounded bg-[#101721] hover:bg-[#1f2f45] border border-[#263447] text-[10px] font-mono transition flex items-center gap-1 cursor-pointer"
                              onClick={() => onSelectSymbol(chip.symbol)}
                              title={`${chip.symbol} · RS ${chip.rs_percentile} · 1D ${chip.change_1d_pct >= 0 ? '+' : ''}${chip.change_1d_pct}%`}
                            >
                              <span className="font-bold text-[#f1f4f8]">{chip.symbol}</span>
                              <span className="text-[9px] px-1 rounded bg-[#182b46] text-[#74a9ff]">
                                {chip.rs_percentile.toFixed(0)}
                              </span>
                              <span className={`text-[9px] ${chip.change_1d_pct >= 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'}`}>
                                {chip.change_1d_pct >= 0 ? `+${chip.change_1d_pct.toFixed(1)}%` : `${chip.change_1d_pct.toFixed(1)}%`}
                              </span>
                              <a
                                href={`https://www.tradingview.com/chart/?symbol=NSE:${chip.symbol.replace(/-/g, '_')}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                onClick={(e) => e.stopPropagation()}
                                className="text-[#38bdf8] hover:text-white ml-0.5 p-0.5"
                                title="Open in TradingView"
                              >
                                <ExternalLink className="w-2.5 h-2.5" />
                              </a>
                            </div>
                          ))
                        ) : (
                          s.leaders.map((sym) => (
                            <button
                              key={sym}
                              onClick={() => onSelectSymbol(sym)}
                              className="px-1.5 py-0.5 rounded bg-[#101721] hover:bg-[#45d483] hover:text-[#080c14] border border-[#263447] text-[10px] font-mono transition"
                            >
                              {sym}
                            </button>
                          ))
                        )}
                        {s.leaders.length >= 2 && onOpenMultiChart && (
                          <button
                            onClick={() => onOpenMultiChart(s.leaders)}
                            title={`Open ${s.sector} leaders in Multi-Chart Tiles`}
                            className="px-1.5 py-0.5 rounded bg-[#162235] text-[#38bdf8] hover:bg-[#38bdf8] hover:text-[#080c14] border border-[#253c5e] text-[10px] font-medium transition flex items-center gap-1"
                          >
                            <LayoutGrid className="w-2.5 h-2.5" /> Tiles
                          </button>
                        )}
                      </div>
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
