import { useState } from 'react';
import type { QueueRow } from '../api/types';
import { cn } from '../lib/cn';
import { fmtDateShort, fmtINR, fmtInt, fmtNum, fmtPct, fmtSignedPct } from '../lib/fmt';
import { Chip } from '../ui/Chip';
import { Metric } from '../ui/Metric';
import { Panel } from '../ui/Panel';
import { Tooltip } from '../ui/Tooltip';
import { loadSizer, parseRupees, saveSizer, sizePosition, type SizerInput } from './sizer';
import { QUEUE_LABEL, QUEUE_ORDER } from './stockModel';

function SetupDetail({ q, row }: { q: string; row: QueueRow }) {
  if (q === 'darvas_squeeze') {
    return (
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        <Metric metricKey="squeeze_pct" label="Squeeze" value={row.squeeze_pct} format="pct" digits={2} size="sm" />
        <Metric metricKey="candle_range_pct" label="Candle range" value={row.candle_range_pct} format="pct" digits={2} size="sm" />
        <Metric metricKey="darvas_box_bottom" label="Box bottom" value={row.darvas_box_bottom} format="num" size="sm" zoneColor={false} />
      </div>
    );
  }
  if (q === 'darvas_10ema') {
    return (
      <div className="flex flex-wrap items-center gap-2 text-2xs text-fg-3">
        {row.darvas_10ema_flavor && <Chip tone="info">{row.darvas_10ema_flavor}</Chip>}
        {row.signal_date && <span>10 EMA touch {fmtDateShort(row.signal_date)}</span>}
      </div>
    );
  }
  if (q === 'vcp') {
    const cs = row.vcp_contractions ?? [];
    return (
      <div className="space-y-1">
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          <Metric metricKey="vcp_contractions" label="Contractions" value={cs.length || null} format="int" size="sm" zoneColor={false} />
          <Metric metricKey="vdu_ratio" label="Volume dry-up" value={row.vdu_ratio} format="ratio" size="sm" />
        </div>
        {cs.length > 0 && (
          <Tooltip
            content={
              <ul className="num space-y-0.5">
                {cs.map((c) => (
                  <li key={c.label}>
                    {c.label}: {fmtPct(c.depth_pct, 1)} deep · {fmtInt(c.bars)} bars · vol {fmtNum(c.volume_ratio)}× ·{' '}
                    {fmtDateShort(c.start_date)}–{fmtDateShort(c.end_date)}
                  </li>
                ))}
              </ul>
            }
          >
            <div className="num flex items-center gap-1 text-2xs text-fg-2" tabIndex={0}>
              Depths{' '}
              {cs.map((c, i) => (
                <span key={c.label}>
                  {i > 0 && <span className="text-fg-3">→</span>} {fmtPct(c.depth_pct, 1)}
                </span>
              ))}
            </div>
          </Tooltip>
        )}
      </div>
    );
  }
  return null;
}

function Levels({ row }: { row: QueueRow }) {
  const dist = row.distance_to_trigger_pct;
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1">
      <Metric metricKey="trigger_price" label="Trigger" value={row.trigger_price} format="num" size="sm" zoneColor={false} />
      <Metric metricKey="stop_price" label="Stop" value={row.stop_price} format="num" size="sm" zoneColor={false} />
      <Metric metricKey="risk_pct" label="Risk" value={row.risk_pct} format="pct" digits={2} size="sm" />
      {dist != null && dist < 0 ? (
        <Tooltip content="Close is already above the trigger — buying now means more risk than the setup planned.">
          <span className="inline-flex flex-col gap-0.5" tabIndex={0}>
            <span className="text-2xs uppercase tracking-wide text-fg-3">Distance to trigger</span>
            <span className="num text-xs font-medium text-warn">{fmtSignedPct(dist, 2)} past</span>
          </span>
        </Tooltip>
      ) : (
        <Metric metricKey="distance_to_trigger_pct" label="To trigger" value={dist} format="signedPct" digits={2} size="sm" />
      )}
    </div>
  );
}

function SizerRow({ row, input }: { row: QueueRow; input: SizerInput }) {
  const out = sizePosition(row.trigger_price, row.stop_price, input);
  if (!out.ok) return <p className="text-2xs text-fg-3">{out.reason}</p>;
  const r = out.result;
  return (
    <p className="num text-2xs text-fg-2">
      <span className="font-semibold text-fg">{fmtInt(r.shares)} sh</span> · position {fmtINR(r.positionValue, 0)} · loses{' '}
      {fmtINR(r.actualRisk, 0)} at stop
      {r.pctOfCapital != null && (
        <span className={cn(r.overCap ? 'font-semibold text-warn' : 'text-fg-3')}>
          {' '}
          · {fmtPct(r.pctOfCapital, 1)} of capital{r.overCap && ` (> ${input.capPct}% cap)`}
        </span>
      )}
    </p>
  );
}

function RupeeInput({ label, value, onChange, placeholder }: { label: string; value: number | null; onChange: (v: number | null) => void; placeholder: string }) {
  const [text, setText] = useState(value != null ? String(value) : '');
  const [prev, setPrev] = useState(value);
  if (prev !== value) {
    setPrev(value);
    setText(value != null ? String(value) : '');
  }
  return (
    <label className="flex items-center gap-1.5 text-2xs text-fg-3">
      {label}
      <input
        inputMode="decimal"
        value={text}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => onChange(parseRupees(text))}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onChange(parseRupees(text));
        }}
        className="num h-6 w-24 rounded border border-line bg-surface-2 px-1.5 text-xs text-fg placeholder:text-fg-3 focus:border-accent focus:outline-none"
      />
    </label>
  );
}

export interface SetupsBlockProps {
  setups: Record<string, QueueRow | null | undefined> | undefined;
  loading?: boolean;
  className?: string;
}

/** Status of the stock in each Desk queue (same predicates as the Desk) + the position sizer. */
export function SetupsBlock({ setups, loading, className }: SetupsBlockProps) {
  const [sizer, setSizer] = useState<SizerInput>(loadSizer);
  const update = (patch: Partial<SizerInput>) =>
    setSizer((s) => {
      const next = { ...s, ...patch };
      saveSizer(next);
      return next;
    });
  const active = QUEUE_ORDER.filter((q) => setups?.[q]);
  return (
    <Panel
      title="Setups"
      meta={loading ? 'loading…' : active.length ? `in ${active.length} of 3 Desk queues` : 'in no Desk queue today'}
      className={className}
      bodyClassName="divide-y divide-line"
    >
      {QUEUE_ORDER.map((q) => {
        const row = setups?.[q];
        return (
          <div key={q} className={cn('space-y-1.5 px-3 py-2', !row && 'py-1.5')}>
            <div className="flex items-center gap-2">
              <span className={cn('h-2 w-2 rounded-full', row ? 'bg-up' : 'bg-line-strong')} aria-hidden />
              <span className={cn('text-xs font-medium', row ? 'text-fg' : 'text-fg-3')}>{QUEUE_LABEL[q]}</span>
              {row ? (
                row.risk_flag && (
                  <Chip tone="negative" title="Risk to stop above 8%">
                    wide risk
                  </Chip>
                )
              ) : (
                <span className="text-2xs text-fg-3">{loading ? '…' : 'not in queue'}</span>
              )}
            </div>
            {row && (
              <>
                <Levels row={row} />
                <SetupDetail q={q} row={row} />
                <SizerRow row={row} input={sizer} />
              </>
            )}
          </div>
        );
      })}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
        <span className="text-2xs font-semibold uppercase tracking-wide text-fg-3">Sizer</span>
        <RupeeInput label="₹ risk" value={sizer.riskRupees} onChange={(v) => update({ riskRupees: v })} placeholder="per trade" />
        <RupeeInput label="Capital" value={sizer.capital} onChange={(v) => update({ capital: v })} placeholder="optional" />
        <span className="text-2xs text-fg-3">Kept in this browser. Shares = ₹ risk ÷ (trigger − stop).</span>
      </div>
    </Panel>
  );
}
