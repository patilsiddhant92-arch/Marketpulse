/** §4 Participation grid + expansion log, §5 participation trend chart. */
import { DataWarningChip } from '../../ui/DataWarningChip';
import { Panel } from '../../ui/Panel';
import type { PulseResult } from './data';
import {
  EMA_ROWS,
  XP_COLOURS,
  cellBackground,
  cellText,
  fixed,
  gridSessions,
  intIN,
  isNum,
  linePoints,
  longDate,
  pctlTone,
  rangePos,
  shortDate,
  signed,
  toneClass,
} from './model';
import { Legend, LineChart, Note, SectionBody } from './parts';
import type { BreadthContext, BreadthRow, ExpansionRow, ExpansionStat, Units } from './types';

export function BreadthGrid({ q, units, lookback }: { q: PulseResult<BreadthRow, BreadthContext>; units: Units; lookback: number }) {
  const rows = q.rows ?? [];
  const ctx = q.ctx;
  const cols = gridSessions(rows, lookback);
  const today = rows[rows.length - 1];
  return (
    <Panel
      title="Participation"
      meta={today ? `All ${intIN(today.stocks)} stocks · above each average` : undefined}
      actions={<DataWarningChip warning={ctx?.data_warning} />}
    >
      <SectionBody q={q} rows={5}>
        <div className="overflow-x-auto">
          <table className="w-full text-xs tabular-nums" aria-label="Participation grid">
            <thead>
              <tr className="text-2xs text-fg-3">
                <th className="px-2 py-1 text-left font-medium">Above</th>
                {cols.map((r, i) => (
                  <th key={r.trade_date} className="px-1 py-1 text-right font-medium">
                    {i === cols.length - 1 ? 'Today' : shortDate(r.trade_date)}
                  </th>
                ))}
                {lookback > 10 && <th className="px-1 py-1 text-right font-medium">{lookback}D ago</th>}
                <th className="px-1 py-1 text-right font-medium">Δ {lookback}D</th>
                <th className="px-2 py-1 font-medium">vs history</th>
                <th className="px-2 py-1 text-right font-medium">Pctl</th>
              </tr>
            </thead>
            <tbody>
              {EMA_ROWS.map(({ key, label }) => {
                const st = ctx?.stats.find((s) => s.key === key);
                const delta = units === 'pct' ? st?.delta : st?.delta_count;
                const pos = rangePos(st?.today ?? null, st?.min ?? null, st?.max ?? null);
                const p10 = rangePos(st?.p10 ?? null, st?.min ?? null, st?.max ?? null);
                const p90 = rangePos(st?.p90 ?? null, st?.min ?? null, st?.max ?? null);
                return (
                  <tr key={key} className="border-t border-line/60">
                    <td className="whitespace-nowrap px-2 py-1 text-fg-2">{label}</td>
                    {cols.map((r) => {
                      const c = r[key];
                      const xp = c?.flag ?? 0;
                      return (
                        <td
                          key={r.trade_date}
                          data-testid={`cell-${key}-${r.trade_date}`}
                          data-flag={xp}
                          data-unusual={c?.unusual ? 'true' : undefined}
                          className="relative px-1 py-1 text-right text-fg"
                          style={{
                            background: cellBackground(c),
                            outline: c?.unusual ? '1px solid rgb(var(--c-warn))' : undefined,
                            outlineOffset: -1,
                            boxShadow: xp ? `inset 0 -2px 0 ${xp > 0 ? XP_COLOURS.up : XP_COLOURS.down}` : undefined,
                          }}
                          title={
                            c
                              ? `Change ${signed(c.chg, 1)} pts (${signed(c.z, 1)}σ) · count ${signed(c.chg_count, 0)} (${signed(c.rel_pct, 0)}%)${r.gap_before ? ' · after a data gap' : ''}`
                              : undefined
                          }
                        >
                          {cellText(c, units)}
                          {xp !== 0 && (
                            <span className="ml-0.5 text-[9px] font-semibold" style={{ color: xp > 0 ? XP_COLOURS.up : XP_COLOURS.down }}>
                              {xp > 0 ? '▲' : '▼'}
                              {signed(c?.rel_pct, 0)}%
                            </span>
                          )}
                        </td>
                      );
                    })}
                    {lookback > 10 && (
                      <td className="px-1 py-1 text-right text-fg-2">{units === 'pct' ? fixed(st?.lb_value, 0) : intIN(st?.lb_count)}</td>
                    )}
                    <td className={`px-1 py-1 text-right ${toneClass(delta)}`}>{signed(delta, 0)}</td>
                    <td className="px-2 py-1">
                      <span
                        className="relative block h-2 w-28 rounded-full bg-surface-3"
                        title={`min ${fixed(st?.min, 0)}% · p10 ${fixed(st?.p10, 0)}% · p90 ${fixed(st?.p90, 0)}% · max ${fixed(st?.max, 0)}%`}
                        aria-label={`${label}: today ${fixed(st?.today, 0)}%, archive ${fixed(st?.min, 0)} to ${fixed(st?.max, 0)}%`}
                      >
                        {p10 !== null && p90 !== null && (
                          <b className="absolute inset-y-0 rounded-full bg-fg-3/40" style={{ left: `${p10}%`, width: `${p90 - p10}%` }} />
                        )}
                        {pos !== null && <i className="absolute -inset-y-0.5 w-0.5 bg-accent" style={{ left: `calc(${pos}% - 1px)` }} />}
                      </span>
                    </td>
                    <td className={`px-2 py-1 text-right ${pctlTone(st?.pctl ?? null)}`}>{fixed(st?.pctl, 0)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <Note>
          Cell colour shows the change from the prior session, scaled to each row&apos;s usual daily move. Amber outline = unusual move
          (over 2σ of the last 60 daily changes). Cyan / rose underline = breadth expansion / contraction. Pctl = how today ranks against
          every day since {ctx ? longDate(ctx.archive_start) : '—'}.
        </Note>
      </SectionBody>
    </Panel>
  );
}

export function ExpansionLog({ q }: { q: PulseResult<ExpansionRow, { stats: ExpansionStat[]; total_days: number }> }) {
  const stats = q.ctx?.stats ?? [];
  return (
    <Panel title="Expansion log" meta="Days the count of stocks above an average jumped or dropped unusually in one session">
      <div className="space-y-0.5 px-3 pt-2 text-2xs text-fg-3" aria-label="Expansion summary">
        {stats.map((s) => (
          <div key={s.key}>
            <b className="text-fg-2">{s.label}</b>: expansions {s.expansions.n}× (next 20D median {signed(s.expansions.median_fwd_20d_pct, 1)}%,
            up {s.expansions.up_20d}/{s.expansions.n_with_fwd}) · contractions {s.contractions.n}× (next 20D median{' '}
            {signed(s.contractions.median_fwd_20d_pct, 1)}%, up {s.contractions.up_20d}/{s.contractions.n_with_fwd})
          </div>
        ))}
      </div>
      <SectionBody q={q} rows={4} emptyTitle="No expansion or contraction days yet">
        <div className="overflow-x-auto">
          <table className="w-full text-xs tabular-nums" aria-label="Expansion log">
            <thead>
              <tr className="text-2xs text-fg-3">
                {['Date', 'Signal', 'Averages', 'Stocks', 'Next 10D', 'Next 20D'].map((h) => (
                  <th key={h} className={`px-2 py-1 font-medium ${h.startsWith('Next') ? 'text-right' : 'text-left'}`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(q.rows ?? []).map((r) => (
                <tr key={`${r.trade_date}-${r.dir}`} className="border-t border-line/60">
                  <td className="px-2 py-1">{r.is_today ? <b>Today</b> : longDate(r.trade_date)}</td>
                  <td className="px-2 py-1" style={{ color: r.dir > 0 ? XP_COLOURS.up : XP_COLOURS.down }}>
                    {r.signal}
                  </td>
                  <td className="px-2 py-1 text-fg-3">{r.keys.map((k) => k.slice(1)).join(', ')} EMA</td>
                  <td className="px-2 py-1">
                    {r.shown_key.slice(1)} EMA: {intIN(r.from)} → {intIN(r.to)}{' '}
                    <span className={toneClass(r.dir)}>({signed(r.rel_pct, 0)}%)</span>
                  </td>
                  <td className={`px-2 py-1 text-right ${toneClass(r.fwd_10d_pct)}`}>{isNum(r.fwd_10d_pct) ? `${signed(r.fwd_10d_pct)}%` : '…'}</td>
                  <td className={`px-2 py-1 text-right ${toneClass(r.fwd_20d_pct)}`}>{isNum(r.fwd_20d_pct) ? `${signed(r.fwd_20d_pct)}%` : '…'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Note>
          Flag: the one-day change in the count is in the top or bottom 5% of that row&apos;s own history, at least 15% and at least 100
          stocks. Next 10D / 20D = equal-weight average of all stocks. “…” = not enough sessions yet.
        </Note>
      </SectionBody>
    </Panel>
  );
}

const TREND_LINES = [
  { key: 'e10' as const, name: '% above 10 EMA', colour: 'rgb(var(--c-ema-10))' },
  { key: 'e50' as const, name: '% above 50 EMA', colour: 'rgb(var(--c-ema-50))' },
  { key: 'e200' as const, name: '% above 200 EMA', colour: 'rgb(var(--c-ema-200))' },
];

export function TrendChart({ q, lookback }: { q: PulseResult<BreadthRow, BreadthContext>; lookback: number }) {
  const rows = q.rows ?? [];
  const n = Math.max(lookback, 20);
  const view = rows.slice(Math.max(0, rows.length - n - 1));
  const e50 = q.ctx?.stats.find((s) => s.key === 'e50');
  const band: [number, number] | null = e50 && isNum(e50.p10) && isNum(e50.p90) ? [e50.p10, e50.p90] : null;
  return (
    <Panel title="Participation trend" meta={`Last ${view.length - 1 > 0 ? view.length - 1 : 0} sessions`}>
      <SectionBody q={q} rows={4}>
        <div className="px-2 pt-2">
          <LineChart
            label="Percent of stocks above their 10, 50 and 200 EMA"
            labels={view.map((r) => shortDate(r.trade_date))}
            series={TREND_LINES.map((l) => ({ name: l.name, colour: l.colour, values: linePoints(view, l.key) }))}
            band={band}
            yMin={0}
            yMax={100}
          />
        </div>
        <Legend items={[...TREND_LINES, { name: 'normal range of % above 50 EMA (p10–p90)', colour: 'rgb(var(--c-up))' }]} />
      </SectionBody>
    </Panel>
  );
}
