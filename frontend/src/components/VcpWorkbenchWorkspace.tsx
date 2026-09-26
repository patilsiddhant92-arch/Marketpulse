import React, { useState, useEffect, useMemo } from 'react';
import { VcpCandidate, VcpScreenerResponse } from '../types';
import { Layers, Calculator, ShieldCheck, Activity, Copy, Check, Star, ArrowUpDown, ArrowUp, ArrowDown, ExternalLink } from 'lucide-react';
import { sortData, SortConfig } from '../utils/tableSort';
import { DASH, num } from '../utils/nullable';

interface Props {
  selectedSymbol: string | null;
  onSelectSymbol: (symbol: string) => void;
  onAddToBasket: (symbol: string) => void;
}

export const VcpWorkbenchWorkspace: React.FC<Props> = ({
  selectedSymbol,
  onSelectSymbol,
  onAddToBasket,
}) => {
  const [candidates, setCandidates] = useState<VcpCandidate[]>([]);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [riskBudget, setRiskBudget] = useState<number>(25000);
  const [copied, setCopied] = useState<boolean>(false);

  // Sorting
  const [sortConfig, setSortConfig] = useState<SortConfig<VcpCandidate>>({
    key: 'dist_to_pivot_pct',
    direction: 'asc',
  });

  useEffect(() => {
    setLoading(true);
    fetch('/api/screener/vcp')
      .then((res) => res.json())
      .then((data: VcpScreenerResponse) => {
        const list = data.candidates || [];
        setCandidates(list);
        setAsOf(data.as_of ?? null);
        if (list.length > 0 && !selectedSymbol) {
          onSelectSymbol(list[0].symbol);
        }
      })
      .catch((err) => console.error('VCP fetch error:', err))
      .finally(() => setLoading(false));
  }, []);

  const handleCopyAll = () => {
    if (candidates.length === 0) return;
    const tvList = candidates.map((c) => `NSE:${c.symbol}`).join(', ');
    navigator.clipboard.writeText(tvList);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSort = (key: keyof VcpCandidate) => {
    setSortConfig((prev) => {
      if (prev.key === key) {
        if (prev.direction === 'asc') return { key, direction: 'desc' };
        if (prev.direction === 'desc') return { key: null, direction: null };
      }
      return { key, direction: 'asc' };
    });
  };

  const sortedCandidates = useMemo(() => {
    return sortData(candidates, sortConfig.key, sortConfig.direction);
  }, [candidates, sortConfig]);

  const renderSortArrow = (key: keyof VcpCandidate) => {
    if (sortConfig.key !== key) {
      return <ArrowUpDown className="w-3 h-3 text-[#55657e] inline ml-1 opacity-60" />;
    }
    return sortConfig.direction === 'asc' ? (
      <ArrowUp className="w-3 h-3 text-[#f0be58] inline ml-1" />
    ) : (
      <ArrowDown className="w-3 h-3 text-[#f0be58] inline ml-1" />
    );
  };

  const selectedCandidate = candidates.find((c) => c.symbol === selectedSymbol) || candidates[0];

  return (
    <div className="flex-1 flex flex-col h-full bg-[#080c14] overflow-hidden">
      {/* Top Banner */}
      <div className="px-4 py-2.5 bg-[#0e1522] border-b border-[#1f2b3c] flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-[#f0be58]" />
          <div>
            <h2 className="text-xs font-bold text-[#f1f4f8] uppercase tracking-wider">
              Volatility Contraction Pattern (VCP) Workbench
            </h2>
            <p className="text-[10px] text-[#98a7ba]">
              Stage 2 Technical Verification • Progressive Contractions (T1 &gt; T2 &gt; T3) • Volume Dry-Up (VDU &le; 0.80)
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs text-[#98a7ba] font-mono">
            {candidates.length} VCP Setups Confirmed
          </span>
          <span className="text-[10px] text-[#98a7ba] font-mono">
            As of {asOf ?? DASH}
          </span>

          <button
            onClick={handleCopyAll}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-bold bg-[#3a2f18] text-[#f0be58] border border-[#6b5423] hover:border-[#f0be58] transition"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-[#45d483]" /> : <Copy className="w-3.5 h-3.5" />}
            {copied ? 'Copied to Clipboard!' : 'Copy All to TV'}
          </button>
        </div>
      </div>

      {/* Main Split: Candidate Table & Deep-Dive Execution Calculator */}
      <div className="flex-1 flex overflow-hidden">
        {/* Candidates List with Column Sorting */}
        <div className="flex-1 overflow-auto border-r border-[#1f2b3c]">
          {loading ? (
            <div className="p-8 text-center text-[#98a7ba] text-xs">
              Decomposing wave structures across Stage 2 universe...
            </div>
          ) : sortedCandidates.length === 0 ? (
            <div className="p-8 text-center text-[#98a7ba] text-xs">
              No VCP setups in the pool today.
            </div>
          ) : (
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-[#0e1522] text-[#98a7ba] uppercase font-mono text-[11px] tracking-wider border-b border-[#1f2b3c] sticky top-0 z-10 select-none">
                  <th onClick={() => handleSort('symbol')} className="py-2 px-3 font-semibold cursor-pointer hover:text-white">
                    Symbol {renderSortArrow('symbol')}
                  </th>
                  <th onClick={() => handleSort('cmp')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                    CMP (₹) {renderSortArrow('cmp')}
                  </th>
                  <th className="py-2 px-3 font-semibold">Contraction Sequence</th>
                  <th onClick={() => handleSort('vdu_ratio')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                    VDU Ratio {renderSortArrow('vdu_ratio')}
                  </th>
                  <th onClick={() => handleSort('pivot_entry')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                    Pivot Trigger {renderSortArrow('pivot_entry')}
                  </th>
                  <th onClick={() => handleSort('stop_loss')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                    Stop Loss {renderSortArrow('stop_loss')}
                  </th>
                  <th onClick={() => handleSort('risk_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                    Risk % {renderSortArrow('risk_pct')}
                  </th>
                  <th onClick={() => handleSort('dist_to_pivot_pct')} className="py-2 px-3 font-semibold text-right cursor-pointer hover:text-white">
                    Dist to Pivot {renderSortArrow('dist_to_pivot_pct')}
                  </th>
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
                      <td className="py-2 px-3 text-right font-medium text-[#f1f4f8]">
                        {c.cmp == null ? DASH : `₹${num(c.cmp)}`}
                      </td>
                      <td className="py-2 px-3 font-sans">
                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-[#182b46] text-[#74a9ff] border border-[#2b4c7e]">
                          {c.wave_sequence ?? DASH}
                        </span>
                      </td>
                      <td className="py-2 px-3 text-right">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          c.vdu_ratio == null
                            ? 'text-[#94a3b8]'
                            : c.vdu_confirmed
                            ? 'bg-[#163526] text-[#45d483] border border-[#235338]'
                            : 'text-[#f0be58]'
                        }`}>
                          {c.vdu_ratio == null ? DASH : `${num(c.vdu_ratio)} ${c.vdu_confirmed ? '✓' : ''}`}
                        </span>
                      </td>
                      <td className={`py-2 px-3 text-right font-bold ${c.pivot_entry == null ? 'text-[#94a3b8]' : 'text-[#f0be58]'}`}>
                        {c.pivot_entry == null ? DASH : `₹${num(c.pivot_entry)}`}
                      </td>
                      <td className={`py-2 px-3 text-right ${c.stop_loss == null ? 'text-[#94a3b8]' : 'text-[#f43f5e]'}`}>
                        {c.stop_loss == null ? DASH : `₹${num(c.stop_loss)}`}
                      </td>
                      <td className={`py-2 px-3 text-right font-semibold ${c.risk_pct == null ? 'text-[#94a3b8]' : 'text-[#45d483]'}`}>
                        {c.risk_pct == null ? DASH : `${num(c.risk_pct, 1)}%`}
                      </td>
                      <td className={`py-2 px-3 text-right ${c.dist_to_pivot_pct == null ? 'text-[#94a3b8]' : 'text-[#38bdf8]'}`}>
                        {c.dist_to_pivot_pct == null ? DASH : (c.dist_to_pivot_pct >= 0 ? `+${num(c.dist_to_pivot_pct, 1)}%` : `${num(c.dist_to_pivot_pct, 1)}%`)}
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

        {/* Execution & Risk Matrix Side Panel */}
        {selectedCandidate && (
          <div className="w-[340px] bg-[#0c121d] p-4 flex flex-col justify-between overflow-y-auto">
            <div>
              <div className="flex items-center gap-2 mb-3 pb-2 border-b border-[#1f2b3c]">
                <Calculator className="w-4 h-4 text-[#45d483]" />
                <h3 className="text-xs font-bold text-[#f1f4f8] uppercase tracking-wider">
                  Position Risk Sizing ({selectedCandidate.symbol})
                </h3>
              </div>

              {/* Geometry Cards */}
              <div className="space-y-2 mb-4 font-mono text-xs">
                <div className="p-2.5 rounded-lg bg-[#101721] border border-[#1f2b3c] flex justify-between">
                  <span className="text-[#98a7ba]">Pivot Breakout Entry:</span>
                  <span className="font-bold text-[#f0be58]">{selectedCandidate.pivot_entry == null ? DASH : `₹${num(selectedCandidate.pivot_entry)}`}</span>
                </div>
                <div className="p-2.5 rounded-lg bg-[#101721] border border-[#1f2b3c] flex justify-between">
                  <span className="text-[#98a7ba]">Stop Loss Swing Low:</span>
                  <span className="font-bold text-[#f43f5e]">{selectedCandidate.stop_loss == null ? DASH : `₹${num(selectedCandidate.stop_loss)}`}</span>
                </div>
                <div className="p-2.5 rounded-lg bg-[#101721] border border-[#1f2b3c] flex justify-between">
                  <span className="text-[#98a7ba]">Controlled Trade Risk:</span>
                  <span className="font-bold text-[#45d483]">{selectedCandidate.risk_pct == null ? DASH : `${num(selectedCandidate.risk_pct)}% (Target 3-5%)`}</span>
                </div>
              </div>

              {/* Position Sizer Input */}
              <div className="p-3 rounded-xl bg-[#101721] border border-[#263447] mb-4">
                <label className="text-[11px] font-semibold text-[#98a7ba] uppercase block mb-1.5">
                  Account Risk Budget (₹)
                </label>
                <div className="flex items-center gap-2 mb-3">
                  {[10000, 25000, 50000].map((amt) => (
                    <button
                      key={amt}
                      onClick={() => setRiskBudget(amt)}
                      className={`px-2.5 py-1 text-xs rounded font-mono border transition ${
                        riskBudget === amt
                          ? 'bg-[#f0be58] text-[#080c14] border-[#f0be58] font-bold'
                          : 'bg-[#151f2b] text-[#f1f4f8] border-[#263447]'
                      }`}
                    >
                      ₹{(amt / 1000).toFixed(0)}k
                    </button>
                  ))}
                </div>

                <div className="pt-2 border-t border-[#1f2b3c] font-mono text-xs space-y-1">
                  {(() => {
                    const { pivot_entry: pivot, stop_loss: stop } = selectedCandidate;
                    const canSize = pivot != null && stop != null && pivot > stop;
                    const qty = canSize ? Math.floor(riskBudget / (pivot - stop)) : null;
                    return (
                      <>
                        <div className="flex justify-between">
                          <span className="text-[#98a7ba]">Suggested Shares:</span>
                          <span className="font-bold text-base text-[#45d483]">
                            {qty == null ? DASH : `${qty.toLocaleString('en-IN')} Qty`}
                          </span>
                        </div>
                        <div className="flex justify-between text-[11px]">
                          <span className="text-[#98a7ba]">Total Position Value:</span>
                          <span className="text-[#f1f4f8]">
                            {qty == null ? DASH : `₹${(qty * pivot!).toLocaleString('en-IN')}`}
                          </span>
                        </div>
                      </>
                    );
                  })()}
                </div>
              </div>
            </div>

            <button
              onClick={() => onAddToBasket(selectedCandidate.symbol)}
              className="w-full py-2 rounded-lg font-bold text-xs bg-[#f0be58] text-[#080c14] hover:bg-[#e8c766] transition flex items-center justify-center gap-1.5 shadow-md"
            >
              <Star className="w-3.5 h-3.5 fill-[#080c14]" />
              Add {selectedCandidate.symbol} to Active Watchlist
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
