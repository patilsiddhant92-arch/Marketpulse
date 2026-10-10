/**
 * Case study D / W / M trait strip (10-tab-research.md §§12-13): which "Before the big moves" traits
 * were on, week by week, in the 13 weeks before the stock's early lift. One row per trait (grouped
 * Daily / Weekly / Monthly / Accumulation / Improvement / Base), one square per weekly checkpoint.
 * A square is on when the value sat in the better third of the family's past lifts (runners vs fizzles).
 */
import { cn } from '../../lib/cn';
import { fmtDate, fmtDateShort, fmtNum, fmtPct } from '../../lib/fmt';
import type { components } from '../../api/types.gen';
import type { EnvelopeMeta } from '../../api/types';
import { Chip } from '../../ui/Chip';
import { useResearchQuery } from './data';
import { context } from './lab';
import { Summary } from './LabParts';
import { Panel, QueryState } from './parts';

export type TraitStripRow = components['schemas']['TraitStripRow'];

export interface TraitStripContext {
  caveat: string;
  symbol: string;
  lift: { date: string; close: number | null; found: boolean; why: string; family: string; family_label: string };
  columns: { date: string; label: string }[];
  groups: { group: string; label: string; traits: number; on: number[] }[];
  score: number[];
  score_max: number;
  family_base_runner_pct: number | null;
  family_events: number;
  summary: string[];
  definition: string;
  in_sample_note: string;
}

const GROUP_ORDER = ['D', 'W', 'M', 'A', 'I', 'B'] as const;

/** Rows grouped in D/W/M/A/I/B order (stable within a group). Pure; unit-tested. */
export function groupTraits(rows: readonly TraitStripRow[]): { group: string; rows: TraitStripRow[] }[] {
  const out: { group: string; rows: TraitStripRow[] }[] = [];
  for (const g of GROUP_ORDER) {
    const rs = rows.filter((r) => r.group === g);
    if (rs.length) out.push({ group: g, rows: rs });
  }
  return out;
}

function Cell({ on, value, title }: { on: boolean | null | undefined; value: number | null | undefined; title: string }) {
  return (
    <td className="p-0.5" title={`${title}: ${value == null ? 'n/a' : fmtNum(value, 2)}${on == null ? '' : on ? ' · on' : ' · off'}`}>
      <span
        data-on={on == null ? 'na' : on ? 'on' : 'off'}
        className={cn(
          'block h-3.5 w-full min-w-[14px] rounded-sm',
          on == null ? 'bg-surface-3/40' : on ? 'bg-up/70' : 'bg-surface-3',
        )}
      />
    </td>
  );
}

export function TraitStripTable({ rows, ctx }: { rows: TraitStripRow[]; ctx: Partial<TraitStripContext> }) {
  const cols = ctx.columns ?? [];
  const groups = groupTraits(rows);
  const gLabel = Object.fromEntries((ctx.groups ?? []).map((g) => [g.group, g]));
  return (
    <div className="overflow-auto">
      <table className="w-full text-table" aria-label="Trait strip">
        <thead className="text-2xs text-fg-3">
          <tr>
            <th className="px-2 py-1 text-left font-medium">Trait</th>
            {cols.map((c) => (
              <th key={c.date} className={cn('px-0.5 py-1 text-center font-medium', c.label === 'lift' && 'text-fg')} title={fmtDate(c.date)}>
                {c.label === 'lift' || c.label === 'now' ? c.label : c.label.replace('w', '')}
              </th>
            ))}
            <th className="px-2 py-1 text-right font-medium" title="Weeks on in the 13 weeks before the lift">Wks on</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <GroupRows key={g.group} label={gLabel[g.group]?.label ?? g.group} counts={gLabel[g.group]?.on} rows={g.rows} n={cols.length} />
          ))}
          <tr className="border-t border-line-strong">
            <td className="px-2 py-1 text-2xs font-medium text-fg-2">Score traits on (of {ctx.score_max ?? 0})</td>
            {(ctx.score ?? []).map((s, i) => (
              <td key={i} className="num px-0.5 py-1 text-center text-2xs text-fg-2">
                {s}
              </td>
            ))}
            <td />
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function GroupRows({ label, counts, rows, n }: { label: string; counts?: number[]; rows: TraitStripRow[]; n: number }) {
  return (
    <>
      <tr className="border-t border-line bg-surface-2/60">
        <td className="px-2 py-0.5 text-2xs font-semibold uppercase tracking-wide text-fg-2">{label}</td>
        {Array.from({ length: n }, (_, i) => (
          <td key={i} className="num px-0.5 text-center text-2xs text-fg-3">
            {counts?.[i] ?? ''}
          </td>
        ))}
        <td />
      </tr>
      {rows.map((r) => (
        <tr key={r.trait}>
          <td className="max-w-[260px] truncate px-2 py-0.5 text-2xs text-fg-2" title={`Better when ${r.better_when} · cut ${fmtNum(r.cut ?? null, 2)} · runners ${fmtNum(r.lift ?? null, 2)}× the base in the better third`}>
            {r.label}
            {r.score_trait && (
              <Chip tone="violet" className="ml-1">
                score
              </Chip>
            )}
          </td>
          {(r.on ?? []).map((on, i) => (
            <Cell key={i} on={on} value={r.values?.[i] ?? null} title={r.label} />
          ))}
          <td className="num px-2 text-right text-2xs text-fg-3">
            {r.weeks_on}/{r.weeks_known}
          </td>
        </tr>
      ))}
    </>
  );
}

export function TraitStripPanel({ symbol }: { symbol: string }) {
  const q = useResearchQuery('research/case-study/{sym}/traits', { params: { sym: symbol } });
  return (
    <QueryState q={q} what={`The D/W/M trait strip for ${symbol}: which pre-move traits were on in the 13 weeks before its lift.`} compact>
      {(env) => <TraitStripBody rows={env.rows as TraitStripRow[]} meta={env.meta} />}
    </QueryState>
  );
}

function TraitStripBody({ rows, meta }: { rows: TraitStripRow[]; meta: EnvelopeMeta }) {
  const c = context<TraitStripContext>(meta);
  const lift = c.lift;
  return (
    <Panel
      title="Before the lift: D / W / M trait strip"
      subtitle={
        lift
          ? `${lift.family_label} · ${lift.found ? 'lift' : 'latest session'} ${fmtDateShort(lift.date)} at ${fmtNum(lift.close, 1)} · past runner rate ${fmtPct(c.family_base_runner_pct ?? null, 0)} (n=${c.family_events ?? 0})`
          : undefined
      }
      bodyClassName="space-y-2 p-2"
    >
      <Summary lines={c.summary} />
      <TraitStripTable rows={rows} ctx={c} />
      <p className="text-2xs text-fg-3">
        {c.definition} Green = on, grey = off, faint = no value yet. {c.in_sample_note}
      </p>
    </Panel>
  );
}
