import React, { useState } from 'react';
import { HelpCircle, Info } from 'lucide-react';

export interface BenchmarkGuide {
  title: string;
  ideal: string;
  normal: string;
  warning: string;
  rationale: string;
}

export const BENCHMARKS: Record<string, BenchmarkGuide> = {
  rvol: {
    title: 'RVOL (Relative Volume vs 20D)',
    ideal: '≥ 1.50x on Breakout | ≤ 0.65x in Tight Base (VDU)',
    normal: '0.8x – 1.4x (Consolidation)',
    warning: '> 3.5x (Climax Run) or Indifferent 1.0x on breakouts',
    rationale: 'Breakouts require institutional commitment (≥1.5x). Base contractions require supply exhaustion (VDU ≤0.65x) before pivot burst.',
  },
  delivery: {
    title: 'Delivery % & Volume Surge',
    ideal: 'Surge ≥ 1.50x 20D Avg | High-Beta ≥ 40% | Large/Defensive ≥ 60%',
    normal: '25% – 50% (Routine Institutional Flow)',
    warning: '< 20% (Pure intraday scalper churn / speculative pump)',
    rationale: 'High delivery on up days confirms genuine institutional ownership transfer, not ephemeral speculative noise.',
  },
  turnover: {
    title: 'Daily Cash Turnover (₹ Cr)',
    ideal: '≥ ₹25 Cr (Institutional Liquid) | ≥ ₹10 Cr (Mid/Small Focus)',
    normal: '₹5 – 10 Cr (Selective 3%–5% Sizing)',
    warning: '< ₹5 Cr (Illiquid, risk of 5% upper/lower circuit traps)',
    rationale: 'Enforces risk execution liquidity. Positions of 8%–10% equity require at least ₹25 Cr daily turnover to exit smoothly.',
  },
  ticket: {
    title: 'Ticket Ratio (Trade Size vs 20D)',
    ideal: '≥ 1.25x Whale Participation 🏛️',
    normal: '0.90x – 1.20x (Standard Market Flow)',
    warning: '< 0.80x (Retail-dominated order flow)',
    rationale: 'Measures average order size. High ratios reveal institutional block execution hidden within normal market volume.',
  },
  rs: {
    title: 'RS Percentile (Relative Strength)',
    ideal: '≥ 90.0 (Elite Market Leader 👑) | ≥ 80.0 (Stage 2 Leader)',
    normal: '65.0 – 79.0 (Market Performer)',
    warning: '< 60.0 (Laggard / Drag on Portfolio)',
    rationale: 'Focuses capital purely on the top 10%–20% of the entire Indian equity universe outperforming the Nifty benchmark.',
  },
  stretch: {
    title: 'Distance from 10 EMA (Coil vs Stretch)',
    ideal: '0.0% to +3.0% (Coiled at Moving Average Floor)',
    normal: '+3.0% to +6.0% (Trending)',
    warning: '> +8.0% (Overbought / Extended wick exhaustion)',
    rationale: 'Prevents chasing stocks near exhaustion tops. Optimal low-risk entries occur when price coils tight against the rising 10/20 EMA.',
  },
  pivot: {
    title: 'Distance to Pivot Breakout Level',
    ideal: '-2.5% to +0.5% (Pre-breakout coil or fresh thrust)',
    normal: '-5.0% to -2.5% (Building Right-Hand Base)',
    warning: '> +3.0% (Chasing after pivot release)',
    rationale: 'Entry discipline rule. Buying too far past the pivot widens initial risk and compromises the 2.0R to 3.0R reward profile.',
  },
  squeeze: {
    title: 'Darvas Squeeze % (TopBox to 10 EMA)',
    ideal: '0.0% to 2.0% (Tightest Coiling Under Green Line 🎯)',
    normal: '2.0% to 5.0% (Valid Stage 2 Compression)',
    warning: '> 5.0% (Loose structure / Not in squeeze)',
    rationale: 'Measures tightness between the Darvas Box Top (Green Line) and 10 EMA. Lower squeeze % represents maximum coiled energy before explosive breakout.',
  },
  risk: {
    title: 'Initial Trade Risk % (Stop Distance)',
    ideal: '3.0% to 5.0% (Tight Contraction Floor)',
    normal: '5.0% to 7.0% (Standard Swing Stop)',
    warning: '> 8.5% (Wide stop, reduces position leverage)',
    rationale: 'Keeps risk strictly managed. Small stop distances allow optimal sizing without exceeding the portfolio 0.5%–1.0% risk cap.',
  },
  rr: {
    title: 'Reward-to-Risk Ratio (R:R)',
    ideal: '≥ 3.0R to 5.0R (Asymmetric Multi-Wave Thrust)',
    normal: '2.0R (Minimum Acceptable Swing Setup)',
    warning: '< 1.5R (Poor expectancy, do not enter)',
    rationale: 'Guarantees that winning trades generate multiples of capital risked to maintain positive long-term mathematical expectancy.',
  },
};

export const InfoTooltip: React.FC<{ param: keyof typeof BENCHMARKS; label?: string }> = ({
  param,
  label,
}) => {
  const [show, setShow] = useState(false);
  const guide = BENCHMARKS[param];
  if (!guide) return <span>{label}</span>;

  return (
    <span
      className="relative inline-flex items-center gap-1 cursor-help group"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
      onClick={(e) => {
        e.stopPropagation();
        setShow((prev) => !prev);
      }}
    >
      <span>{label}</span>
      <HelpCircle className="w-3 h-3 text-[#5f748d] group-hover:text-[#38bdf8] transition shrink-0" />

      {show && (
        <div
          className="absolute top-full left-0 mt-1.5 w-72 p-2.5 bg-[#0b121e] border border-[#23354d] text-left rounded-lg shadow-2xl z-[100] text-[11px] font-sans pointer-events-none select-none backdrop-blur-md animate-in fade-in zoom-in-95 duration-100"
          style={{ minWidth: '260px' }}
        >
          <div className="font-bold text-[#f1f4f8] text-xs pb-1 border-b border-[#1f2b3c] flex items-center justify-between">
            <span>{guide.title}</span>
            <span className="text-[9px] font-mono text-[#38bdf8] uppercase">Ideal Criteria</span>
          </div>

          <div className="pt-2 space-y-1.5">
            <div className="flex items-start gap-1.5">
              <span className="text-[#10b981] font-bold shrink-0">🎯 Ideal:</span>
              <span className="text-[#34d399] font-medium leading-tight">{guide.ideal}</span>
            </div>

            <div className="flex items-start gap-1.5">
              <span className="text-[#94a3b8] font-bold shrink-0">⚪ Normal:</span>
              <span className="text-[#cbd5e1] leading-tight">{guide.normal}</span>
            </div>

            <div className="flex items-start gap-1.5">
              <span className="text-[#f43f5e] font-bold shrink-0">⚠️ Avoid:</span>
              <span className="text-[#fda4af] leading-tight">{guide.warning}</span>
            </div>

            <div className="pt-1.5 text-[10px] text-[#98a7ba] italic border-t border-[#172336] leading-relaxed">
              {guide.rationale}
            </div>
          </div>
        </div>
      )}
    </span>
  );
};

export const renderRvolBadge = (rvol: number) => {
  if (rvol >= 2.5) {
    return (
      <span
        className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-[#a855f7]/20 text-[#c084fc] border border-[#a855f7]/30"
        title="Institutional Whale Volume Surge (≥ 2.5x)"
      >
        {rvol.toFixed(1)}x 🏛️
      </span>
    );
  }
  if (rvol >= 1.5) {
    return (
      <span
        className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-[#10b981]/20 text-[#34d399] border border-[#10b981]/30"
        title="Breakout Volume Confirmation (≥ 1.5x)"
      >
        {rvol.toFixed(1)}x ⚡
      </span>
    );
  }
  if (rvol <= 0.65) {
    return (
      <span
        className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-[#38bdf8]/15 text-[#38bdf8] border border-[#38bdf8]/25"
        title="Volume Dry-Up / Supply Exhaustion (VDU ≤ 0.65x)"
      >
        {rvol.toFixed(1)}x 💤
      </span>
    );
  }
  return (
    <span className="font-mono text-xs text-[#98a7ba]">
      {rvol.toFixed(1)}x
    </span>
  );
};

export const renderDeliveryBadge = (delivPct: number, ratio?: number, spike?: boolean) => {
  if (spike || (ratio !== undefined && ratio >= 1.5)) {
    return (
      <span
        className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-[#10b981]/20 text-[#34d399] border border-[#10b981]/30 flex items-center gap-1"
        title={`Delivery Volume Spike: ${delivPct.toFixed(1)}% (${ratio ? ratio.toFixed(1) : '1.5'}x 20D Baseline)`}
      >
        <span>{delivPct.toFixed(1)}%</span>
        <span>📦</span>
      </span>
    );
  }
  if (delivPct >= 50) {
    return (
      <span className="font-mono text-xs font-semibold text-[#10b981]">
        {delivPct.toFixed(1)}%
      </span>
    );
  }
  if (delivPct < 20) {
    return (
      <span
        className="font-mono text-xs text-[#fda4af]"
        title="Low Delivery (< 20%): High intraday churn"
      >
        {delivPct.toFixed(1)}%
      </span>
    );
  }
  return (
    <span className="font-mono text-xs text-[#c5d1e0]">
      {delivPct.toFixed(1)}%
    </span>
  );
};

export const renderTurnoverBadge = (cr: number) => {
  if (cr >= 50) {
    return (
      <span className="font-mono text-xs font-bold text-[#34d399]" title="Institutional Liquid Universe (≥ ₹50 Cr)">
        ₹{cr >= 1000 ? `${(cr / 1000).toFixed(1)}K` : cr.toFixed(0)} Cr
      </span>
    );
  }
  if (cr >= 20) {
    return (
      <span className="font-mono text-xs font-semibold text-[#38bdf8]" title="Tradable Swing Universe (≥ ₹20 Cr)">
        ₹{cr.toFixed(0)} Cr
      </span>
    );
  }
  if (cr < 5) {
    return (
      <span className="font-mono text-xs text-[#f43f5e]" title="Warning: Low Liquidity (< ₹5 Cr) - Avoid large positions">
        ₹{cr.toFixed(1)} Cr ⚠️
      </span>
    );
  }
  return (
    <span className="font-mono text-xs text-[#98a7ba]">
      ₹{cr.toFixed(0)} Cr
    </span>
  );
};

export const renderRsBadge = (rs: number) => {
  if (rs >= 90) {
    return (
      <span className="px-1.5 py-0.2 rounded text-[10px] font-mono font-bold bg-[#f0be58]/20 text-[#f0be58] border border-[#f0be58]/35" title="Elite Market Leader (Top 10%)">
        {rs.toFixed(0)} 👑
      </span>
    );
  }
  if (rs >= 80) {
    return (
      <span className="px-1.5 py-0.2 rounded text-[10px] font-mono font-bold bg-[#10b981]/20 text-[#34d399] border border-[#10b981]/30" title="Stage 2 Outperformer (≥ 80)">
        {rs.toFixed(0)}
      </span>
    );
  }
  if (rs < 60) {
    return (
      <span className="font-mono text-xs text-[#64748b]" title="Laggard (< 60)">
        {rs.toFixed(0)}
      </span>
    );
  }
  return (
    <span className="font-mono text-xs text-[#94a3b8]">
      {rs.toFixed(0)}
    </span>
  );
};
