/** VCP detail for the focused row (spec 7.3): contractions, depths, bars, volume ratio, pivot / stop, risk. */
import { fmtDateShort, fmtNum, fmtPct, fmtRatio } from '../lib/fmt';
import { cn } from '../lib/cn';
import { Chip } from '../ui/Chip';
import type { SRow } from './columns';

export function VcpDetail({ row }: { row: SRow }) {
  const ts = row.vcp_contractions ?? [];
  const risk = row.risk_pct;
  return (
    <div className="shrink-0 border-t border-line bg-surface px-3 py-2">
      <div className="mb-1 flex flex-wrap items-center gap-3 text-xs">
        <span className="font-mono font-semibold text-fg">{row.symbol}</span>
        <span className="text-fg-3">VCP geometry (detect_contractions)</span>
        <span className="num text-fg-2">
          pivot <span className="text-fg">{fmtNum(row.trigger_price)}</span>
        </span>
        <span className="num text-fg-2">
          stop <span className="text-fg">{fmtNum(row.stop_price)}</span>
        </span>
        <span className="num text-fg-2">
          risk <span className={cn(row.risk_flag ? 'text-warn' : 'text-fg')}>{fmtPct(risk)}</span>
        </span>
        {row.risk_flag && (
          <Chip tone="warn" size="xs" title="Stop is more than 8% below the pivot — size down or wait for a tighter base">
            risk &gt; 8%
          </Chip>
        )}
        <span className="num text-fg-2" title="Volume dry-up: last 3 sessions' average volume ÷ 20-session average">
          VDU <span className="text-fg">{fmtRatio(row.vdu_ratio)}</span>
        </span>
      </div>
      {ts.length === 0 ? (
        <div className="text-xs text-fg-3">No contraction list served for this row.</div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {ts.map((t, i) => (
            <div key={i} className="rounded border border-line bg-surface-2 px-2 py-1 text-2xs">
              <div className="font-mono font-semibold text-fg">{t.label}</div>
              <div className="num text-fg-2">
                depth <span className="text-fg">{fmtPct(t.depth_pct)}</span> · {t.bars ?? '—'} bars
              </div>
              <div className="num text-fg-3">
                {fmtNum(t.peak)} → {fmtNum(t.trough)} · vol {fmtRatio(t.volume_ratio)}
              </div>
              <div className="text-fg-3">
                {fmtDateShort(t.start_date)} – {fmtDateShort(t.end_date)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
