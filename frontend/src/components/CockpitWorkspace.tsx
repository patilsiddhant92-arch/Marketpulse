import React, { useState, useEffect, useMemo } from 'react';
import { CandidateSetup, CockpitResponse } from '../types';
import { Copy, Check, Filter, ArrowUpDown, ArrowUp, ArrowDown, Star, Target, ExternalLink } from 'lucide-react';
import { sortData, SortConfig } from '../utils/tableSort';
import { InfoTooltip, renderRvolBadge } from '../utils/benchmarks';
import { DASH, signedPct, num } from '../utils/nullable';

interface Props {
  selectedSymbol: string | null;
  onSelectSymbol: (symbol: string) => void;
  onAddToBasket: (symbol: string) => void;
}

export const CockpitWorkspace: React.FC<Props> = ({
  selectedSymbol,
  onSelectSymbol,
  onAddToBasket,
}) => {
  const [queue, setQueue] = useState<string>('primary');
  const [candidates, setCandidates] = useState<CandidateSetup[]>([]);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [copied, setCopied] = useState<boolean>(false);
  const [sortConfig, setSortConfig] = useState<SortConfig<CandidateSetup>>({
    key: 'dist_to_pivot_pct',
    direction: 'asc',
  });

  useEffect(() => {
    if (queue === 'darvas_squeeze') {
      setSortConfig({ key: 'squeeze_pct', direction: 'asc' });
    } else {
      setSortConfig({ key: 'dist_to_pivot_pct', direction: 'asc' });
    }
  }, [queue]);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/candidates/cockpit?queue=${queue}`)
      .then((res) => res.json())
      .then((data: CockpitResponse) => {
        const list = data.candidates || [];
        setCandidates(list);
        setAsOf(data.as_of ?? null);
        if (list.length > 0 && !selectedSymbol) {
          onSelectSymbol(list[0].symbol);
        }
      })
      .catch((err) => console.error('Cockpit fetch error:', err))
      .finally(() => setLoading(false));
  }, [queue]);

  const sortedCandidates = useMemo(() => {
    return sortData(candidates, sortConfig.key, sortConfig.direction);
  }, [candidates, sortConfig]);

  const handleCopyAll = () => {
    if (sortedCandidates.length === 0) return;
    const seen = new Set<string>();
    const tokens: string[] = [];
    for (const c of sortedCandidates) {
      const sym = c.symbol ? c.symbol.trim().toUpperCase().replace(/-/g, '_') : '';
      if (!sym) continue;
      const tok = sym.startsWith('NSE:') ? sym : `NSE:${sym}`;
      if (!seen.has(tok)) {
        seen.add(tok);
        tokens.push(tok);
      }
    }
    if (tokens.length === 0) return;
    const tvList = tokens.join(',');

    const copyFallback = () => {
      try {
        const textArea = document.createElement('textarea');
        textArea.value = tvList;
        textArea.style.position = 'fixed';
        textArea.style.opacity = '0';
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
      } catch (err) {
        console.error('Clipboard copy failed:', err);
      }
    };

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(tvList).catch(() => copyFallback());
    } else {
      copyFallback();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSort = (key: keyof CandidateSetup) => {
    setSortConfig((prev) => {
      if (prev.key === key) {
        if (prev.direction === 'asc') return { key, direction: 'desc' };
        if (prev.direction === 'desc') return { key: null, direction: null };
      }
      return { key, direction: 'asc' };
    });
  };


  const renderSortArrow = (key: keyof CandidateSetup) => {
    if (sortConfig.key !== key) {
      return <ArrowUpDown className="w-3 h-3 text-[#55657e] inline ml-1 opacity-60" />;
    }
    return sortConfig.direction === 'asc' ? (
      <ArrowUp className="w-3 h-3 text-[#f0be58] inline ml-1" />
    ) : (
      <ArrowDown className="w-3 h-3 text-[#f0be58] inline ml-1" />
    );
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[#080c14] overflow-hidden">
      {/* Top Filter & Toolbar */}
      <div className="px-4 py-2.5 bg-[#0e1522] border-b border-[#1f2b3c] flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-[#98a7ba] uppercase tracking-wider flex items-center gap-1">
            <Filter className="w-3.5 h-3.5 text-[#f0be58]" />
            Action Queue:
          </span>
          <div className="flex items-center gap-1.5">
            {[
              { id: 'primary', label: 'Primary Setups' },
              { id: 'vcp', label: 'VCP' },
              { id: 'darvas_10ema', label: 'Darvas 10 EMA' },
              { id: 'darvas_squeeze', label: 'Darvas Squeeze' },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setQueue(tab.id)}
                className={`px-3 py-1 text-xs rounded-md font-medium border transition ${
                  queue === tab.id
                    ? 'bg-[#f0be58] text-[#080c14] border-[#f0be58] font-bold shadow'
                    : 'bg-[#151f2b] text-[#f1f4f8] border-[#263447] hover:border-[#f0be58]'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs text-[#98a7ba] font-mono">
            {candidates.length} Qualified Setups
          </span>
          <span className="text-[10px] text-[#98a7ba] font-mono">
            As of {asOf ?? DASH}
          </span>

          <button
            onClick={handleCopyAll}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-bold bg-[#182b46] text-[#74a9ff] border border-[#2b4c7e] hover:border-[#74a9ff] transition"
            title={queue === 'darvas_squeeze' ? "Copy 100% of Darvas Squeeze symbols formatted for TradingView (Rule 1 Compliant)" : "Copy 100% of visible symbols formatted for TradingView (Rule 1 Compliant)"}
          >
            {copied ? <Check className="w-3.5 h-3.5 text-[#45d483]" /> : <Copy className="w-3.5 h-3.5" />}
            {copied ? 'Copied to Clipboard!' : queue === 'darvas_squeeze' ? 'Copy Darvas Squeeze to TV' : 'Copy All to TV'}
          </button>
        </div>
      </div>

      {/* High-Density Candidates Grid with Column Sorting */}
      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="p-8 text-center text-[#98a7ba] text-xs">
            Scanning DuckDB analytical model for primary setups...
          </div>
        ) : sortedCandidates.length === 0 ? (
          <div className="p-8 text-center text-[#98a7ba] text-xs">
            No setups matching {queue} criteria today. Market exposure discipline enforced.
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
                <th onClick={() => handleSort('cmp')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  CMP (₹) {renderSortArrow('cmp')}
                </th>
                <th onClick={() => handleSort('change_1d_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  1D % {renderSortArrow('change_1d_pct')}
                </th>
                <th onClick={() => handleSort('pattern_state')} className="py-2 px-3 font-semibold cursor-pointer hover:text-white">
                  Setup Class {renderSortArrow('pattern_state')}
                </th>
                {queue === 'darvas_squeeze' && (
                  <th onClick={() => handleSort('squeeze_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                    <InfoTooltip param="squeeze" label="Squeeze %" /> {renderSortArrow('squeeze_pct')}
                  </th>
                )}
                <th onClick={() => handleSort('rvol')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  <InfoTooltip param="rvol" label="RVOL" /> {renderSortArrow('rvol')}
                </th>
                <th onClick={() => handleSort('dist_to_pivot_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  <InfoTooltip param="pivot" label="Dist to Pivot" /> {renderSortArrow('dist_to_pivot_pct')}
                </th>
                <th onClick={() => handleSort('risk_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                  <InfoTooltip param="risk" label="Risk %" /> {renderSortArrow('risk_pct')}
                </th>
                <th className="py-2 px-3 font-semibold">Why Now / Setup Rationale</th>
                <th className="py-2 px-3 text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#151f2b] font-mono">
              {sortedCandidates.map((c) => {
                const isSelected = selectedSymbol === c.symbol;
                return (
                  <tr
                    key={`${c.queue}-${c.symbol}`}
                    onClick={() => onSelectSymbol(c.symbol)}
                    className={`cursor-pointer transition hover:bg-[#151f2b]/80 ${
                      isSelected ? 'bg-[#152336] border-l-2 border-[#f0be58]' : ''
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
                      {c.sector ?? DASH}
                    </td>
                    <td className="py-2 px-3 text-right font-medium text-[#f1f4f8]">
                      {c.cmp == null ? DASH : `₹${num(c.cmp)}`}
                    </td>
                    <td className={`py-2 px-3 text-right font-semibold ${
                      c.change_1d_pct == null ? 'text-[#94a3b8]' : c.change_1d_pct >= 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'
                    }`}>
                      {signedPct(c.change_1d_pct)}
                    </td>
                    <td className="py-2 px-3 font-sans">
                      <span className="px-2 py-0.5 rounded text-[10px] font-semibold border border-[#3a2f18] bg-[#3a2f18]/60 text-[#f0be58]">
                        {c.pattern_state}
                      </span>
                    </td>
                    {queue === 'darvas_squeeze' && (
                      <td className="py-2 px-3 text-right font-semibold text-[#f0be58]">
                        {c.squeeze_pct !== undefined && c.squeeze_pct !== null ? `${c.squeeze_pct.toFixed(1)}%` : DASH}
                      </td>
                    )}
                    <td className="py-2 px-3 text-right">
                      {renderRvolBadge(c.rvol)}
                    </td>
                    <td className="py-2 px-3 text-right">
                      <span className={c.dist_to_pivot_pct == null ? 'text-[#94a3b8]' : c.dist_to_pivot_pct >= -2.5 && c.dist_to_pivot_pct <= 0.5 ? 'text-[#34d399] font-bold' : c.dist_to_pivot_pct > 3.0 ? 'text-[#fda4af]' : 'text-[#f0be58]'}>
                        {signedPct(c.dist_to_pivot_pct, 1)}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-right">
                      <span className={c.risk_pct == null ? 'text-[#94a3b8]' : c.risk_pct <= 5.0 ? 'text-[#34d399] font-semibold' : c.risk_pct > 8.0 ? 'text-[#f43f5e] font-bold' : 'text-[#fda4af]'}>
                        {c.risk_pct == null ? DASH : `${num(c.risk_pct, 1)}%`}
                      </span>
                    </td>
                    <td className="py-2 px-3 font-sans text-[11px] text-[#98a7ba] truncate max-w-[280px]">
                      {c.why_now || DASH}
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
