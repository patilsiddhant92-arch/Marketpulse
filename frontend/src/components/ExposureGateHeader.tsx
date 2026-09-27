import React from 'react';
import { MarketRegimeResponse } from '../types';
import { ShieldCheck, Activity, TrendingUp, Layers, Flame, Compass, ChevronRight, BarChart2, Zap } from 'lucide-react';
import { DASH } from '../utils/nullable';

interface Props {
  regime: MarketRegimeResponse | null;
  loading: boolean;
  onOpenBreadth?: () => void;
  onNavigateTab?: (tab: 'cockpit' | 'momentum' | 'deals' | 'vcp' | 'sector') => void;
}

export const ExposureGateHeader: React.FC<Props> = ({
  regime,
  loading,
  onOpenBreadth,
  onNavigateTab,
}) => {
  if (loading || !regime) {
    return (
      <div className="bg-[#101721] border-b border-[#263447] px-4 py-3 animate-pulse flex items-center justify-between">
        <div className="h-6 w-48 bg-[#151f2b] rounded"></div>
        <div className="h-6 w-96 bg-[#151f2b] rounded"></div>
      </div>
    );
  }

  const { exposure_gate, vix, breadth, leading_themes, tape, setups_summary } = regime;

  const low = exposure_gate.band_low;
  const exposureTone =
    low == null
      ? 'text-[#94a3b8] border-[#263447] bg-[#151f2b]/60'
      : low >= 75
      ? 'text-[#45d483] border-[#163526] bg-[#163526]/60'
      : low >= 50
      ? 'text-[#f0be58] border-[#3a2f18] bg-[#3a2f18]/60'
      : 'text-[#f27c84] border-[#3a2027] bg-[#3a2027]/60';

  const vixTone =
    vix.current == null
      ? 'text-[#94a3b8]'
      : vix.current < 15
      ? 'text-[#45d483]'
      : vix.current < 20
      ? 'text-[#f0be58]'
      : 'text-[#f27c84]';

  return (
    <header className="bg-[#090d16] border-b border-[#1f2b3c] px-4 py-2 flex flex-wrap items-center justify-between gap-2 shadow-md text-xs select-none">
      {/* Group 1: Actionable Trading Posture & Exposure Rule */}
      <div className="flex items-center gap-2.5 flex-wrap">
        {/* Exposure Gate & Actionable Guidance */}
        <div
          onClick={() => onNavigateTab && onNavigateTab('cockpit')}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border ${exposureTone} shadow-sm cursor-pointer hover:opacity-90 transition`}
          title={exposure_gate.execution_playbook || exposure_gate.guidance}
        >
          <ShieldCheck className="w-4 h-4 shrink-0" />
          <div className="flex flex-col">
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] uppercase tracking-wider font-bold">
                {exposure_gate.state ?? 'Unknown'} · Exposure {exposure_gate.band ?? '—'}
              </span>
              {exposure_gate.max_position_size && (
                <span className="text-[9px] px-1 py-0.2 rounded bg-[#080c14] font-mono">
                  Pos: {exposure_gate.max_position_size}
                </span>
              )}
            </div>
            <span className="text-[11px] font-medium text-[#c5d1e0] truncate max-w-[280px]">
              {exposure_gate.action_bias || exposure_gate.guidance}
            </span>
          </div>
        </div>

        {/* Market Tape: Advances vs Declines & Volume Flow */}
        {tape && (
          <div
            className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg border border-[#263447] bg-[#101721]"
            title={`Session Tape: ${tape.advancers} Advances / ${tape.decliners} Declines / ${tape.unchanged} Unchanged. Volume participation: ${tape.advance_volume_pct.toFixed(1)}%`}
          >
            <div className="flex flex-col">
              <span className="text-[9px] uppercase tracking-wider font-semibold text-[#8898aa]">
                Tape &amp; Volume Flow
              </span>
              <div className="flex items-center gap-1.5 font-mono text-[11px]">
                <span className="font-bold text-[#45d483]">
                  {tape.advancers} Up
                </span>
                <span className="text-[#64748b]">/</span>
                <span className="font-bold text-[#f43f5e]">
                  {tape.decliners} Down
                </span>
                <span
                  className={`text-[10px] px-1 py-0.1 rounded font-bold ${
                    tape.net_advancers >= 0 ? 'bg-[#163526] text-[#45d483]' : 'bg-[#33161c] text-[#f43f5e]'
                  }`}
                >
                  {tape.net_advancers >= 0 ? `+${tape.net_advancers}` : tape.net_advancers}
                </span>
                <span className="text-[10px] text-[#38bdf8] ml-0.5">
                  ({tape.advance_volume_pct.toFixed(0)}% Vol)
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Trend Participation Breadth (Click to open 180D Radar Drawer) */}
        <div
          onClick={onOpenBreadth}
          className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg border border-[#263447] hover:border-[#38bdf8] bg-[#101721] cursor-pointer transition group"
          title="Click to open 180-Session Market Breadth & Liquidity Expansion Dashboard"
        >
          <TrendingUp className="w-3.5 h-3.5 text-[#d8ac3d] group-hover:text-[#38bdf8] transition shrink-0" />
          <div className="flex flex-col">
            <div className="flex items-center gap-1">
              <span className="text-[9px] uppercase tracking-wider font-semibold text-[#8898aa]">
                Trend Breadth
              </span>
              <span className="text-[9px] px-1 py-0.1 rounded bg-[#162235] text-[#38bdf8] font-bold font-mono group-hover:bg-[#38bdf8] group-hover:text-[#080c14] transition">
                180D ↗
              </span>
            </div>
            <div className="flex items-center gap-1.5 font-mono text-[11px]">
              <span className="text-[#c5d1e0]">
                &gt;20: <strong className="text-[#38bdf8]">{breadth.above_20_ema_pct.toFixed(0)}%</strong>
              </span>
              <span className="text-[#64748b]">·</span>
              <span className="text-[#c5d1e0]">
                &gt;50: <strong className="text-[#f1f4f8]">{breadth.above_50_ema_pct.toFixed(0)}%</strong>
              </span>
              <span className="text-[#64748b]">·</span>
              <span className="text-[#c5d1e0]">
                &gt;200: <strong className="text-[#f0be58]">{breadth.above_200_ema_pct.toFixed(0)}%</strong>
              </span>
              {breadth.near_52w_highs !== undefined && breadth.near_52w_highs > 0 && (
                <>
                  <span className="text-[#64748b]">·</span>
                  <span className="text-[#45d483] font-semibold text-[10px]">
                    {breadth.near_52w_highs} near 52W
                  </span>
                </>
              )}
            </div>
          </div>
        </div>

        {/* India VIX */}
        <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg border border-[#263447] bg-[#101721]">
          <Activity className="w-3.5 h-3.5 text-[#74a9ff] shrink-0" />
          <div className="flex flex-col">
            <span className="text-[9px] uppercase tracking-wider font-semibold text-[#8898aa]">India VIX</span>
            <div className="flex items-center gap-1 font-mono text-[11px]">
              <span className={`font-bold ${vixTone}`}>{vix.current == null ? DASH : vix.current.toFixed(2)}</span>
              {vix.change_1d_pct != null && (
                <span className={`text-[10px] ${vix.change_1d_pct <= 0 ? 'text-[#45d483]' : 'text-[#f27c84]'}`}>
                  {vix.change_1d_pct >= 0 ? `+${vix.change_1d_pct.toFixed(1)}%` : `${vix.change_1d_pct.toFixed(1)}%`}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Group 2: Action Desks Shortcut & Leading Themes */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Active Setups Ready Button (Jumps to Cockpit / VCP) */}
        {setups_summary && (
          <button
            onClick={() => onNavigateTab && onNavigateTab('cockpit')}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-[#142236] hover:bg-[#1e3454] border border-[#224068] text-[#38bdf8] font-mono text-[11px] font-bold transition shadow-sm"
            title="Click to view Action Desk primary queues"
          >
            <Zap className="w-3.5 h-3.5 text-[#f0be58]" />
            <span
              className="text-white"
              title="Stocks above their 200 EMA and within 25% of the 52-week high"
            >
              Stage-2 pool: {setups_summary.stage2_pool_count}
            </span>
            <ChevronRight className="w-3 h-3 text-[#74a9ff]" />
          </button>
        )}

        {/* Leading Themes Pill Bar (Jumps to Sector Matrix) */}
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] font-bold text-[#8898aa] uppercase tracking-wider flex items-center gap-1">
            <Flame className="w-3.5 h-3.5 text-[#d8ac3d]" />
            Themes:
          </span>
          <div className="flex items-center gap-1">
            {leading_themes.slice(0, 3).map((theme) => (
              <button
                key={theme.name}
                onClick={() => onNavigateTab && onNavigateTab('sector')}
                className="flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium border border-[#263447] bg-[#151f2b] text-[#f1f4f8] hover:border-[#d8ac3d] hover:text-[#d8ac3d] transition cursor-pointer"
                title={`Click to open Sector Matrix. Leaders: ${theme.leaders.join(', ')}`}
              >
                <span className="w-1.5 h-1.5 rounded-full bg-[#45d483]"></span>
                <span className="truncate max-w-[90px]">{theme.name}</span>
                <span className="text-[10px] font-mono text-[#d8ac3d]">
                  +{theme.return_5d_pct.toFixed(1)}%
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </header>
  );
};
