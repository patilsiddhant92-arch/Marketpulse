import React, { useState, useEffect, useMemo } from 'react';
import { HistoricalBreadthRecord } from '../types';
import { X, TrendingUp, BarChart2, Activity, ShieldAlert, ArrowUpRight, ArrowDownRight, Layers } from 'lucide-react';

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

export const MarketBreadthDrawer: React.FC<Props> = ({ isOpen, onClose }) => {
  const [history, setHistory] = useState<HistoricalBreadthRecord[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [horizon, setHorizon] = useState<number>(60); // 15, 30, 60, 180

  useEffect(() => {
    if (!isOpen) return;
    setLoading(true);
    fetch('http://127.0.0.1:8000/api/market/breadth/historical?days=180')
      .then((res) => res.json())
      .then((data) => {
        setHistory(data.history || []);
      })
      .catch((err) => console.error('Error fetching breadth history:', err))
      .finally(() => setLoading(false));
  }, [isOpen]);

  // Filter by selected horizon
  const visibleHistory = useMemo(() => {
    return history.slice(0, horizon);
  }, [history, horizon]);

  const latest = history[0];

  // 20D turnover average
  const avgTurnover20d = useMemo(() => {
    if (history.length === 0) return 0;
    const sample = history.slice(0, 20);
    const sum = sample.reduce((acc, h) => acc + (h.turnover_cr || 0), 0);
    return Math.round(sum / sample.length);
  }, [history]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/70 backdrop-blur-sm animate-fadeIn">
      <div className="w-full max-w-4xl bg-[#0a0f18] h-full flex flex-col border-l border-[#1f2b3c] shadow-2xl overflow-hidden">
        {/* Top Header */}
        <div className="px-5 py-3.5 bg-[#0e1522] border-b border-[#1f2b3c] flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-[#152336] flex items-center justify-center border border-[#253c5e]">
              <TrendingUp className="w-4 h-4 text-[#38bdf8]" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-[#f1f4f8] flex items-center gap-2">
                Market Breadth &amp; Liquidity Expansion Engine
                <span className="text-[10px] px-2 py-0.5 rounded-full font-mono font-bold bg-[#152336] text-[#38bdf8] border border-[#253c5e]">
                  180 Sessions
                </span>
              </h2>
              <p className="text-[11px] text-[#7888a0]">
                Multi-timeframe participation (% &gt; 20/50/200 EMA), Adv/Dec net, and institutional cash turnover
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Horizon selector */}
            <div className="flex items-center gap-1 bg-[#131b26] p-1 rounded-md border border-[#1f2b3c]">
              {[
                { d: 15, label: '15D' },
                { d: 30, label: '30D' },
                { d: 60, label: '60D' },
                { d: 180, label: '180D' },
              ].map((h) => (
                <button
                  key={h.d}
                  onClick={() => setHorizon(h.d)}
                  className={`px-2.5 py-0.5 text-xs rounded font-mono transition ${
                    horizon === h.d
                      ? 'bg-[#38bdf8] text-[#080c14] font-bold shadow'
                      : 'text-[#98a7ba] hover:text-white'
                  }`}
                >
                  {h.label}
                </button>
              ))}
            </div>

            <button
              onClick={onClose}
              className="p-1.5 rounded-md hover:bg-[#151f2b] text-[#98a7ba] hover:text-white transition"
              title="Close drawer (Esc)"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Latest Snapshot KPI Strip */}
        {latest && (
          <div className="px-5 py-3 bg-[#0d131f] border-b border-[#1f2b3c] grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 gap-3">
            <div className="p-2 rounded bg-[#131b26] border border-[#1f2b3c]">
              <span className="text-[10px] text-[#7888a0] font-semibold uppercase tracking-wider block">
                Breadth State
              </span>
              <span className={`text-xs font-bold font-mono mt-0.5 inline-block ${
                latest.breadth_state === 'Leading' ? 'text-[#45d483]' :
                latest.breadth_state === 'Weakening' ? 'text-[#f0be58]' :
                latest.breadth_state === 'Lagging' ? 'text-[#f43f5e]' : 'text-[#38bdf8]'
              }`}>
                {latest.breadth_state}
              </span>
            </div>

            <div className="p-2 rounded bg-[#131b26] border border-[#1f2b3c]">
              <span className="text-[10px] text-[#7888a0] font-semibold uppercase tracking-wider block">
                &gt; 20 EMA
              </span>
              <span className={`text-xs font-bold font-mono mt-0.5 inline-block ${
                latest.above_20ema_pct >= 50 ? 'text-[#45d483]' : 'text-[#f0be58]'
              }`}>
                {latest.above_20ema_pct.toFixed(1)}%
              </span>
            </div>

            <div className="p-2 rounded bg-[#131b26] border border-[#1f2b3c]">
              <span className="text-[10px] text-[#7888a0] font-semibold uppercase tracking-wider block">
                &gt; 50 EMA
              </span>
              <span className={`text-xs font-bold font-mono mt-0.5 inline-block ${
                latest.above_50ema_pct >= 50 ? 'text-[#45d483]' : 'text-[#f0be58]'
              }`}>
                {latest.above_50ema_pct.toFixed(1)}%
              </span>
            </div>

            <div className="p-2 rounded bg-[#131b26] border border-[#1f2b3c]">
              <span className="text-[10px] text-[#7888a0] font-semibold uppercase tracking-wider block">
                &gt; 200 EMA
              </span>
              <span className={`text-xs font-bold font-mono mt-0.5 inline-block ${
                latest.above_200ema_pct >= 50 ? 'text-[#45d483]' : 'text-[#f0be58]'
              }`}>
                {latest.above_200ema_pct.toFixed(1)}%
              </span>
            </div>

            <div className="p-2 rounded bg-[#131b26] border border-[#1f2b3c]">
              <span className="text-[10px] text-[#7888a0] font-semibold uppercase tracking-wider block">
                A / D Ratio (1D)
              </span>
              <span className="text-xs font-bold font-mono text-[#f1f4f8] mt-0.5 inline-block">
                {latest.advancers} : {latest.decliners} ({latest.advance_pct.toFixed(0)}%)
              </span>
            </div>

            <div className="p-2 rounded bg-[#131b26] border border-[#1f2b3c]">
              <span className="text-[10px] text-[#7888a0] font-semibold uppercase tracking-wider block">
                Cash T/O vs 20D Avg
              </span>
              <span className="text-xs font-bold font-mono text-[#38bdf8] mt-0.5 inline-block">
                ₹{Math.round(latest.turnover_cr).toLocaleString()} Cr
              </span>
            </div>
          </div>
        )}

        {/* Historical Table */}
        <div className="flex-1 overflow-auto p-4">
          {loading ? (
            <div className="p-12 text-center text-[#98a7ba] text-xs font-mono">
              Loading 180 sessions of breadth metrics...
            </div>
          ) : visibleHistory.length === 0 ? (
            <div className="p-12 text-center text-[#98a7ba] text-xs font-mono">
              No historical breadth data found.
            </div>
          ) : (
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-[#0e1522] text-[#98a7ba] uppercase font-mono text-[11px] tracking-wider border-b border-[#1f2b3c] sticky top-0 z-10 select-none">
                  <th className="py-2.5 px-3 font-semibold">Trade Date</th>
                  <th className="py-2.5 px-3 font-semibold text-center">State</th>
                  <th className="py-2.5 px-3 font-semibold text-center">Participation (% &gt; 20 / 50 / 200 EMA)</th>
                  <th className="py-2.5 px-3 font-semibold text-right">&gt; 20 EMA</th>
                  <th className="py-2.5 px-3 font-semibold text-right">&gt; 50 EMA</th>
                  <th className="py-2.5 px-3 font-semibold text-right">&gt; 200 EMA</th>
                  <th className="py-2.5 px-3 font-semibold text-right">Adv % (5D Avg)</th>
                  <th className="py-2.5 px-3 font-semibold text-right">52W Highs</th>
                  <th className="py-2.5 px-3 font-semibold text-right">Turnover (₹ Cr)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#151f2b] font-mono">
                {visibleHistory.map((row) => {
                  const isHighTurnover = avgTurnover20d > 0 && row.turnover_cr >= avgTurnover20d * 1.15;
                  return (
                    <tr key={row.trade_date} className="hover:bg-[#131b26]/70 transition">
                      <td className="py-2 px-3 font-bold text-[#f1f4f8]">
                        {row.trade_date}
                      </td>
                      <td className="py-2 px-3 text-center">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          row.breadth_state === 'Leading' ? 'bg-[#163526] text-[#45d483] border border-[#235338]' :
                          row.breadth_state === 'Emerging' ? 'bg-[#0f2d3d] text-[#38bdf8] border border-[#1a4a63]' :
                          row.breadth_state === 'Weakening' ? 'bg-[#3a2f18] text-[#f0be58] border border-[#6b5423]' :
                          row.breadth_state === 'Lagging' ? 'bg-[#3a2027] text-[#f27c84] border border-[#522933]' :
                          'bg-[#1e2633] text-[#98a7ba] border border-[#2d3a4d]'
                        }`}>
                          {row.breadth_state}
                        </span>
                      </td>
                      <td className="py-2 px-3">
                        <div className="w-36 mx-auto flex flex-col gap-1">
                          {/* Mini stacked bars */}
                          <div className="flex items-center gap-1.5 text-[10px]">
                            <span className="w-7 text-[9px] text-[#7888a0]">20E</span>
                            <div className="flex-1 bg-[#162232] h-1.5 rounded-full overflow-hidden">
                              <div
                                className={`h-full rounded-full ${row.above_20ema_pct >= 50 ? 'bg-[#45d483]' : 'bg-[#f0be58]'}`}
                                style={{ width: `${Math.min(100, row.above_20ema_pct)}%` }}
                              />
                            </div>
                          </div>
                          <div className="flex items-center gap-1.5 text-[10px]">
                            <span className="w-7 text-[9px] text-[#7888a0]">50E</span>
                            <div className="flex-1 bg-[#162232] h-1.5 rounded-full overflow-hidden">
                              <div
                                className={`h-full rounded-full ${row.above_50ema_pct >= 50 ? 'bg-[#45d483]' : 'bg-[#f0be58]'}`}
                                style={{ width: `${Math.min(100, row.above_50ema_pct)}%` }}
                              />
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className={`py-2 px-3 text-right font-medium ${
                        row.above_20ema_pct >= 50 ? 'text-[#45d483]' : 'text-[#f0be58]'
                      }`}>
                        {row.above_20ema_pct.toFixed(1)}%
                      </td>
                      <td className={`py-2 px-3 text-right font-medium ${
                        row.above_50ema_pct >= 50 ? 'text-[#45d483]' : 'text-[#f0be58]'
                      }`}>
                        {row.above_50ema_pct.toFixed(1)}%
                      </td>
                      <td className={`py-2 px-3 text-right font-medium ${
                        row.above_200ema_pct >= 50 ? 'text-[#45d483]' : 'text-[#f0be58]'
                      }`}>
                        {row.above_200ema_pct.toFixed(1)}%
                      </td>
                      <td className="py-2 px-3 text-right">
                        <span className={row.advance_pct >= 50 ? 'text-[#10b981] font-bold' : 'text-[#f43f5e]'}>
                          {row.advance_pct.toFixed(0)}%
                        </span>
                        <span className="text-[10px] text-[#6b7c93] ml-1">
                          ({row.advance_pct_5d_avg.toFixed(0)}%)
                        </span>
                      </td>
                      <td className="py-2 px-3 text-right font-bold text-[#38bdf8]">
                        {row.near_52w_highs}
                      </td>
                      <td className="py-2 px-3 text-right font-medium">
                        <span className={isHighTurnover ? 'text-[#45d483] font-bold' : 'text-[#c5d1e0]'}>
                          ₹{Math.round(row.turnover_cr).toLocaleString()} Cr
                        </span>
                        {isHighTurnover && (
                          <span className="ml-1 text-[9px] px-1 py-0.2 rounded bg-[#163526] text-[#45d483]">
                            EXP
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
};
