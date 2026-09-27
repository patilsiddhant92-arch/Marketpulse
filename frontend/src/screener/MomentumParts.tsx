/** Momentum scanner building blocks: filter panel, leaders panel, debug breakdown, evidence table. */
import { Check, Copy, Layers, X } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import type { GroupContext, MomentumEvidenceRow } from '../api/types';
import { GroupHealthChip } from '../context/GroupContext';
import { cn } from '../lib/cn';
import { fmtDate, fmtInt, fmtNum, fmtSignedPct } from '../lib/fmt';
import { Chip } from '../ui/Chip';
import {
  FLAGS,
  LOOKBACKS,
  VOLUME_PRESETS,
  lookback,
  parseFlags,
  toggleFlag,
  volumeMode,
  type DebugCheck,
  type Flag,
  type Leader,
  type MomentumPatch,
  type MomentumState,
} from './momentumModel';

// ------------------------------------------------------------------ small controls

/** Number box that commits on blur / Enter (no request per keystroke); remounts when the value changes elsewhere. */
function NumberField(props: { value: string; onCommit: (v: string) => void; width?: string; label: string; suffix?: string }) {
  return <NumberFieldInner key={props.value} {...props} />;
}

function NumberFieldInner({
  value,
  onCommit,
  width = 'w-20',
  label,
  suffix,
}: {
  value: string;
  onCommit: (v: string) => void;
  width?: string;
  label: string;
  suffix?: string;
}) {
  const [text, setText] = useState(value);
  const commit = () => {
    const n = Number(text);
    if (text.trim() !== '' && Number.isFinite(n) && n >= 0) onCommit(String(n));
    else setText(value);
  };
  return (
    <span className="flex items-center gap-1">
      <input
        type="number"
        min={0}
        aria-label={label}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === 'Enter' && commit()}
        className={cn(
          'h-6 rounded border border-line bg-surface-2 px-1.5 font-mono text-xs text-fg outline-none focus:border-accent',
          width,
        )}
      />
      {suffix && <span className="text-2xs text-fg-3">{suffix}</span>}
    </span>
  );
}

function Seg({
  on,
  onClick,
  children,
  title,
  danger,
}: {
  on: boolean;
  onClick: () => void;
  children: ReactNode;
  title?: string;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      title={title}
      onClick={onClick}
      className={cn(
        'h-6 whitespace-nowrap rounded border px-2 text-xs',
        on
          ? danger
            ? 'border-down bg-down/15 text-down'
            : 'border-accent bg-accent/15 text-accent'
          : 'border-line text-fg-2 hover:text-fg',
      )}
    >
      {children}
    </button>
  );
}

export function CopyButton({
  label,
  text,
  onCopy,
  copied,
  title,
  primary,
  small,
}: {
  label: string;
  text: string;
  onCopy: (label: string, text: string) => void;
  copied: string | null;
  title?: string;
  primary?: boolean;
  small?: boolean;
}) {
  const done = copied === label;
  return (
    <button
      type="button"
      disabled={!text}
      title={title}
      onClick={(e) => {
        e.stopPropagation();
        onCopy(label, text);
      }}
      className={cn(
        'flex shrink-0 items-center gap-1 whitespace-nowrap rounded border disabled:opacity-40',
        small ? 'h-5 px-1.5 text-2xs' : 'h-6 px-2 text-xs',
        primary ? 'border-accent/60 text-accent hover:bg-accent/10' : 'border-line text-fg-2 hover:text-fg',
      )}
    >
      {done ? <Check className="h-3 w-3 text-up" /> : <Copy className="h-3 w-3" />}
      {done ? 'Copied' : label}
    </button>
  );
}

// ------------------------------------------------------------------ filter panel (old two rows)

export function MomentumFilters({
  state,
  onChange,
  debugInput,
  onDebugInput,
  onDebugSubmit,
}: {
  state: MomentumState;
  onChange: (patch: MomentumPatch) => void;
  debugInput: string;
  onDebugInput: (v: string) => void;
  onDebugSubmit: () => void;
}) {
  const flags = parseFlags(state.mf);
  const mode = volumeMode(state);
  const lb = lookback(state);
  const vol = Number(state.mvol);
  const flag = (f: Flag) => (
    <label key={f} className="flex cursor-pointer items-center gap-1 whitespace-nowrap">
      <input
        type="checkbox"
        className="accent-accent"
        checked={flags.has(f)}
        onChange={(e) => onChange({ mf: toggleFlag(state.mf, f, e.target.checked) })}
      />
      <span className={cn(f === 'ema' && 'text-accent', f === 'sma' && 'text-warn')}>{FLAGS[f]}</span>
    </label>
  );
  return (
    <div className="shrink-0 space-y-1 border-b border-line bg-surface px-3 py-1 text-xs text-fg-2" aria-label="Momentum filters">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="flex items-center gap-1" role="group" aria-label="Lookback">
          <span className="text-fg-3">Lookback</span>
          {LOOKBACKS.map((d) => (
            <Seg
              key={d}
              on={lb === d}
              onClick={() => onChange({ mlb: String(d) })}
              title={`Trigger conditions held on any of the last ${d} sessions`}
            >
              {d}D
            </Seg>
          ))}
        </span>
        <span className="flex items-center gap-1">
          <span className="text-fg-3">Min mcap</span>
          <NumberField label="Minimum market cap (₹ Cr)" value={state.mmcap} onCommit={(v) => onChange({ mmcap: v })} suffix="Cr" />
        </span>
        <span className="flex items-center gap-1 rounded border border-line px-1 py-0.5" role="group" aria-label="Volume gate">
          <span className="pl-0.5 text-fg-3">Volume gate</span>
          <Seg
            on={mode === 'day'}
            onClick={() => onChange({ mvg: 'day' })}
            title="Minimum day volume on the trigger session (mutually exclusive with 20D avg)"
          >
            Day vol
          </Seg>
          <Seg
            on={mode === 'avg20d'}
            onClick={() => onChange({ mvg: 'avg20d' })}
            title="Minimum 20-day average volume (mutually exclusive with day volume)"
          >
            20D avg
          </Seg>
          <Seg on={mode === 'off'} danger onClick={() => onChange({ mvg: 'off' })} title="No volume filter">
            Off
          </Seg>
          {mode !== 'off' && (
            <span className="flex items-center gap-0.5 border-l border-line pl-1">
              <NumberField label="Volume threshold (shares)" value={state.mvol} onCommit={(v) => onChange({ mvol: v })} width="w-20" />
              {VOLUME_PRESETS.map((p) => (
                <Seg key={p.label} on={vol === p.value} onClick={() => onChange({ mvol: String(p.value) })}>
                  {p.label}
                </Seg>
              ))}
            </span>
          )}
        </span>
        <span className="flex items-center gap-1">
          <span className="text-fg-3">Max 52W away</span>
          <NumberField
            label="Maximum % below the 52W high"
            value={state.mhigh}
            onCommit={(v) => onChange({ mhigh: v })}
            width="w-16"
            suffix="%"
          />
        </span>
        <span className="flex items-center gap-1">
          <span className="text-fg-3">Min above 52W low</span>
          <NumberField
            label="Minimum % above the 52W low"
            value={state.mlow}
            onCommit={(v) => onChange({ mlow: v })}
            width="w-16"
            suffix="%"
          />
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {(Object.keys(FLAGS) as Flag[]).map(flag)}
        <span className="flex items-center gap-1" title="Restrict the scan to one symbol and show which conditions pass or fail (Enter)">
          <span className="text-fg-3">Debug</span>
          <input
            type="text"
            aria-label="Debug symbol"
            placeholder="RELIANCE"
            value={debugInput}
            onChange={(e) => onDebugInput(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === 'Enter' && onDebugSubmit()}
            className="h-6 w-20 rounded border border-line bg-surface-2 px-1.5 font-mono text-xs uppercase text-fg outline-none focus:border-accent"
          />
        </span>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ debug breakdown

export function MomentumDebug({
  symbol,
  checks,
  inList,
  onClose,
}: {
  symbol: string;
  checks: DebugCheck[];
  inList: boolean;
  onClose: () => void;
}) {
  const failed = checks.filter((c) => !c.passed).length;
  return (
    <div className="shrink-0 border-b border-line bg-surface-2 px-3 py-1.5 text-xs" aria-label={`Why ${symbol}`}>
      <div className="mb-1 flex items-center gap-2">
        <span className="font-mono font-semibold text-fg">{symbol}</span>
        {inList ? (
          <Chip tone="positive" size="xs">
            in the list
          </Chip>
        ) : (
          <Chip tone="warn" size="xs">
            not in the list · {failed} condition{failed === 1 ? '' : 's'} fail
          </Chip>
        )}
        <span className="text-fg-3">
          Trigger conditions must all hold on one session in the lookback; current conditions on the latest session.
        </span>
        <button type="button" onClick={onClose} className="ml-auto text-fg-3 hover:text-fg" aria-label="Close debug">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="grid grid-cols-1 gap-x-6 gap-y-0.5 md:grid-cols-2">
        {(['trigger', 'current'] as const).map((stage) => (
          <div key={stage}>
            <div className="mp-label mb-0.5">{stage === 'trigger' ? 'Trigger (any session in lookback)' : 'Current (latest session)'}</div>
            {checks
              .filter((c) => c.stage === stage)
              .map((c) => (
                <div key={c.label} className="flex items-center gap-2">
                  <span className={cn('w-8 font-semibold', c.passed ? 'text-up' : 'text-down')}>{c.passed ? 'pass' : 'fail'}</span>
                  <span className="text-fg-2">{c.label}</span>
                  {c.detail && <span className="text-fg-3">· {c.detail}</span>}
                </div>
              ))}
          </div>
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ leaders panel

function LeaderCard({
  kind,
  rank,
  leader,
  onCopy,
  copied,
  selected,
  onSelect,
}: {
  kind: 'Sector' | 'Industry';
  rank: number;
  leader: Leader;
  onCopy: (label: string, text: string) => void;
  copied: string | null;
  selected: boolean;
  onSelect: () => void;
}) {
  const name = kind === 'Sector' ? leader.sector : (leader.industry ?? '');
  const label = `${kind} ${name}`;
  return (
    <div
      className={cn(
        'flex min-w-0 flex-col gap-0.5 rounded-md border bg-surface-2 px-2 py-1',
        selected ? 'border-accent' : 'border-line hover:border-line-strong',
      )}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        <span className={cn('shrink-0 text-2xs font-semibold uppercase tracking-wide', kind === 'Sector' ? 'text-accent' : 'text-violet')}>
          {kind === 'Sector' ? 'Sec' : 'Ind'} #{rank}
        </span>
        <button
          type="button"
          onClick={onSelect}
          className="min-w-0 flex-1 truncate text-left text-xs font-semibold text-fg hover:text-accent"
          title={`${name}${kind === 'Industry' ? ` (${leader.sector})` : ''} — click to filter the table`}
        >
          {name}
        </button>
        <span className="num shrink-0 text-2xs text-fg-3" title="Average strength rank of its stocks in this scan">
          Str {fmtNum(leader.avg_rs, 0)}
        </span>
      </div>
      <div className="flex min-w-0 items-center gap-1.5 text-2xs text-fg-3">
        <span className="num shrink-0 text-fg-2">{leader.stock_count} names</span>
        {leader.new_count > 0 && <span className="shrink-0 text-accent">{leader.new_count} new</span>}
        <GroupHealthChip g={(leader.group ?? undefined) as GroupContext | undefined} spark={false} />
        <span className="ml-auto">
          <CopyButton
            label="Copy TV"
            text={leader.tv_str}
            onCopy={(_l, t) => onCopy(label, t)}
            copied={copied === label ? 'Copy TV' : null}
            small
          />
        </span>
      </div>
    </div>
  );
}

export function MomentumLeaders({
  sectors,
  industries,
  distribution,
  total,
  sectorFilter,
  industryFilter,
  onSector,
  onIndustry,
  onCopy,
  copied,
}: {
  sectors: Leader[];
  industries: Leader[];
  distribution: Leader[];
  total: number;
  sectorFilter: string;
  industryFilter: string;
  onSector: (s: string | null) => void;
  onIndustry: (s: string | null) => void;
  onCopy: (label: string, text: string) => void;
  copied: string | null;
}) {
  return (
    <div className="shrink-0 space-y-1 border-b border-line bg-surface px-3 py-1" aria-label="Top leadership in this scan">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wide text-fg">
          <Layers className="h-3.5 w-3.5 text-accent" /> Top leadership in this scan
          <span className="font-normal normal-case tracking-normal text-fg-3">
            — counts from the filtered results · H = group Health + quadrant
          </span>
        </span>
        <span className="flex items-center gap-1.5">
          <CopyButton
            label="Copy Top Sectors"
            text={sectors.map((s) => s.tv_str).join(',')}
            onCopy={onCopy}
            copied={copied}
            title="Every stock in the top 3 sectors, as a TradingView list"
          />
          <CopyButton
            label="Copy Top Industries"
            text={industries.map((s) => s.tv_str).join(',')}
            onCopy={onCopy}
            copied={copied}
            title="Every stock in the top 3 industries, as a TradingView list"
          />
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
        {sectors.map((s, i) => (
          <LeaderCard
            key={`s-${s.sector}`}
            kind="Sector"
            rank={i + 1}
            leader={s}
            onCopy={onCopy}
            copied={copied}
            selected={sectorFilter === s.sector}
            onSelect={() => onSector(sectorFilter === s.sector ? null : s.sector)}
          />
        ))}
        {industries.map((s, i) => (
          <LeaderCard
            key={`i-${s.sector}-${s.industry}`}
            kind="Industry"
            rank={i + 1}
            leader={s}
            onCopy={onCopy}
            copied={copied}
            selected={industryFilter === s.industry}
            onSelect={() => onIndustry(industryFilter === s.industry ? null : (s.industry ?? null))}
          />
        ))}
      </div>
      {distribution.length > 0 && (
        <div className="flex items-center gap-1 overflow-x-auto pb-0.5 text-2xs" role="group" aria-label="Filter sector">
          <span className="mr-1 shrink-0 font-semibold uppercase tracking-wide text-fg-3">Filter sector</span>
          <Chip
            size="xs"
            selected={!sectorFilter && !industryFilter}
            onClick={() => {
              onSector(null);
              onIndustry(null);
            }}
            className="shrink-0"
          >
            All ({total})
          </Chip>
          {distribution.map((s) => (
            <Chip
              key={s.sector}
              size="xs"
              selected={sectorFilter === s.sector}
              onClick={() => onSector(sectorFilter === s.sector ? null : s.sector)}
              className="shrink-0"
            >
              {s.sector} <span className="num text-fg-3">{s.stock_count}</span>
            </Chip>
          ))}
          {industryFilter && (
            <Chip size="xs" tone="violet" selected onClick={() => onIndustry(null)} className="shrink-0" title="Clear the industry filter">
              {industryFilter} <X className="h-2.5 w-2.5" />
            </Chip>
          )}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ evidence

export function evidenceLine(row: MomentumEvidenceRow | undefined): string | null {
  if (!row || !row.n_20) return null;
  return `past hits: 20D ${fmtSignedPct(row.avg_20, 1)} avg · ${fmtNum(row.hit_rate_20, 0)}% up · n=${fmtInt(row.n_20)}`;
}

export function MomentumEvidenceTable({
  rows,
  start,
  end,
  notes,
  onClose,
  isDefault,
}: {
  rows: MomentumEvidenceRow[];
  start: string | null | undefined;
  end: string | null | undefined;
  notes: string[];
  onClose: () => void;
  isDefault: boolean;
}) {
  const H = [5, 10, 20] as const;
  return (
    <div className="shrink-0 border-b border-line bg-surface-2 px-3 py-1.5 text-xs" aria-label="Momentum evidence">
      <div className="mb-1 flex items-center gap-2">
        <span className="font-semibold text-fg">Evidence per coil bucket</span>
        <span className="text-fg-3">
          past scanner hits with the default settings, {fmtDate(start)} – {fmtDate(end)}; forward return from that close
        </span>
        {!isDefault && (
          <Chip tone="warn" size="xs">
            your filters differ from the defaults — evidence is for the defaults
          </Chip>
        )}
        <button type="button" onClick={onClose} className="ml-auto text-fg-3 hover:text-fg" aria-label="Close evidence">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <table className="w-full max-w-4xl text-left text-xs">
        <thead className="text-2xs uppercase tracking-wide text-fg-3">
          <tr>
            <th className="py-0.5 pr-3 font-semibold">Bucket</th>
            {H.map((h) => (
              <th key={h} className="py-0.5 pr-3 text-right font-semibold" colSpan={3}>
                {h} sessions: avg · median · % up
              </th>
            ))}
            <th className="py-0.5 text-right font-semibold">n (10D)</th>
          </tr>
        </thead>
        <tbody className="num">
          {rows.map((r) => (
            <tr key={r.bucket} className={cn('border-t border-line/50', r.bucket === 'Universe' && 'text-fg-3')}>
              <td className="py-0.5 pr-3 font-sans text-fg-2">{r.bucket}</td>
              {H.map((h) => {
                const rec = r as unknown as Record<string, number | null>;
                const avg = rec[`avg_${h}`];
                return [
                  <td key={`a${h}`} className={cn('py-0.5 text-right', avg == null ? 'text-fg-3' : avg > 0 ? 'text-up' : 'text-down')}>
                    {fmtSignedPct(avg, 2)}
                  </td>,
                  <td key={`m${h}`} className="py-0.5 text-right text-fg-2">
                    {fmtSignedPct(rec[`median_${h}`], 2)}
                  </td>,
                  <td key={`h${h}`} className="py-0.5 pr-3 text-right text-fg-2">
                    {rec[`hit_rate_${h}`] == null ? '—' : `${fmtNum(rec[`hit_rate_${h}`], 1)}%`}
                  </td>,
                ];
              })}
              <td className={cn('py-0.5 text-right', r.insufficient_sample && 'text-warn')}>{fmtInt(r.n_10)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {notes.length > 0 && <div className="mt-1 text-2xs text-fg-3">{notes.join(' ')}</div>}
    </div>
  );
}
