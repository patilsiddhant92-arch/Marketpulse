/**
 * Screener floors (spec 7.3): market cap, price, day volume vs 20-day average
 * volume (distinct, correctly labelled), lookback window, IPO ranking and a
 * taxonomy group. Text inputs commit on Enter / blur so typing never refetches.
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useApiQuery } from '../api/query';
import { cn } from '../lib/cn';
import type { ScreenerState } from './model';

const LEVELS = [
  { id: 'broad_sector', label: 'Broad Sector' },
  { id: 'sector', label: 'Sector' },
  { id: 'broad_industry', label: 'Broad Industry' },
  { id: 'industry', label: 'Industry' },
] as const;

const control = 'h-6 rounded border border-line bg-surface-2 px-1.5 text-xs text-fg focus:border-accent focus:outline-none disabled:opacity-40';

function Field({ label, title, children }: { label: string; title?: string; children: ReactNode }) {
  return (
    <label className="flex items-center gap-1 text-2xs text-fg-3" title={title}>
      <span className="whitespace-nowrap">{label}</span>
      {children}
    </label>
  );
}

function CommitInput({
  value,
  onCommit,
  width = 64,
  placeholder,
  disabled,
  label,
}: {
  value: string;
  onCommit: (v: string) => void;
  width?: number;
  placeholder?: string;
  disabled?: boolean;
  label: string;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    const v = draft.trim();
    if (v !== value) onCommit(v === '' || Number.isFinite(Number(v)) ? v : value);
  };
  return (
    <input
      aria-label={label}
      inputMode="decimal"
      className={cn(control, 'num')}
      style={{ width }}
      value={draft}
      placeholder={placeholder}
      disabled={disabled}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit();
      }}
    />
  );
}

export interface FilterBarProps {
  state: ScreenerState;
  queuePreset: boolean;
  onChange: (patch: Partial<Record<keyof ScreenerState, string | null>>) => void;
  search: string;
  onSearch: (v: string) => void;
}

export function FilterBar({ state, queuePreset, onChange, search, onSearch }: FilterBarProps) {
  const groups = useApiQuery('groups/board', { query: { level: state.level as 'industry', floor: 'all', limit: 500 } }, { enabled: !!state.level });
  const names = useMemo(
    () =>
      (groups.data?.rows ?? [])
        .map((g) => ({ name: g.group_name ?? '', n: g.stocks }))
        .filter((g) => g.name)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [groups.data],
  );
  const floorsOff = queuePreset;
  const floorTitle = floorsOff ? 'Darvas / VCP use the Desk pool; this floor does not apply' : undefined;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-surface px-3 py-1">
      <Field label="Mcap ≥" title={floorTitle ?? 'Market-cap floor, ₹ Cr (point-in-time where available)'}>
        <select className={control} value={state.mcap} disabled={floorsOff} onChange={(e) => onChange({ mcap: e.target.value })}>
          <option value="0">All</option>
          <option value="300">₹300 Cr</option>
          <option value="1000">₹1,000 Cr</option>
          <option value="5000">₹5,000 Cr</option>
          <option value="20000">₹20,000 Cr</option>
        </select>
      </Field>
      <Field label="Price ≥ ₹" title={floorTitle ?? 'Close price floor; empty = none'}>
        <CommitInput label="Minimum price" value={state.price} onCommit={(v) => onChange({ price: v || '0' })} width={52} disabled={floorsOff} />
      </Field>
      <Field label="Day vol ≥" title={floorTitle ?? "Today's session volume (shares); empty = no floor"}>
        <CommitInput label="Minimum day volume" value={state.vol} onCommit={(v) => onChange({ vol: v })} placeholder="any" width={80} disabled={floorsOff} />
      </Field>
      <Field label="20D avg vol ≥" title={floorTitle ?? '20-session average volume (shares); empty = no floor'}>
        <CommitInput label="Minimum 20-day average volume" value={state.avgvol} onCommit={(v) => onChange({ avgvol: v })} placeholder="any" width={80} disabled={floorsOff} />
      </Field>
      <Field label="Lookback" title={floorTitle ?? 'All rules held together on at least one session in this window (floors apply on the as-of date)'}>
        <select className={control} value={state.lb} disabled={floorsOff} onChange={(e) => onChange({ lb: e.target.value })}>
          {['1', '3', '5', '10', '20'].map((d) => (
            <option key={d} value={d}>
              {d === '1' ? 'today' : `${d} sessions`}
            </option>
          ))}
        </select>
      </Field>
      <label className={cn('flex items-center gap-1 text-2xs text-fg-3', floorsOff && 'opacity-40')} title="Rank recent listings in their own IPO peer group when they lack the main strength rank (badged IPO)">
        <input type="checkbox" className="accent-accent" checked={state.ipo === '1'} disabled={floorsOff} onChange={(e) => onChange({ ipo: e.target.checked ? '1' : '0' })} />
        Include IPOs
      </label>
      <Field label="Group">
        <select className={control} value={state.level} onChange={(e) => onChange({ level: e.target.value || null, group: null })} aria-label="Taxonomy level">
          <option value="">Any level</option>
          {LEVELS.map((l) => (
            <option key={l.id} value={l.id}>
              {l.label}
            </option>
          ))}
        </select>
        <select
          className={cn(control, 'max-w-[180px]')}
          value={state.group}
          disabled={!state.level || groups.isLoading}
          onChange={(e) => onChange({ group: e.target.value || null })}
          aria-label="Group"
        >
          <option value="">{state.level ? (groups.isLoading ? 'Loading…' : 'All groups') : '—'}</option>
          {names.map((g) => (
            <option key={g.name} value={g.name}>
              {g.name}
              {g.n != null ? ` (${g.n})` : ''}
            </option>
          ))}
        </select>
      </Field>
      <input
        data-filter-input
        aria-label="Filter rows by symbol, name or industry"
        className={cn(control, 'ml-auto w-44')}
        placeholder="Filter rows  ( / )"
        value={search}
        onChange={(e) => onSearch(e.target.value)}
      />
    </div>
  );
}
