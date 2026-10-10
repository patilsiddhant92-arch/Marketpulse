/**
 * Index study (10-tab-research.md §6), on what the local archive supports: the
 * equal-weight market of stocks ≥ ₹1,000 Cr, every fall > 8% with its depth,
 * time down, time to recover and breadth at the low (today's row highlighted),
 * and large vs mid vs small leadership. Nifty / MidSml400 / Smallcap250 cycles
 * wait for the index-history backfill (data gap #3).
 */
import { fmtDate, fmtInt, fmtNum, fmtPct, fmtSignedPct } from '../../lib/fmt';
import { GlanceBand } from '../../ui/GlanceBand';
import { KpiTile } from '../../ui/KpiTile';
import { useResearchQuery } from './data';
import { caveatOf, context, dateTicks, rebasePct, type DrawdownRow, type IndexContext } from './lab';
import { Caveat, Muted, SimpleTable } from './LabParts';
import { Legend, PathChart, Panel, QueryState } from './parts';

const BANDS = [
  { key: 'large', label: 'Large (top 100)' },
  { key: 'mid', label: 'Mid (101–250)' },
  { key: 'small', label: 'Small (rest ≥ ₹1,000 Cr)' },
] as const;

export function IndexStudyView() {
  const q = useResearchQuery('research/index-study');
  return (
    <QueryState q={q} what="Every fall of more than 8% in the equal-weight market, and which size band led.">
      {(env) => {
        const c = context<IndexContext>(env.meta);
        const s = c.series ?? [];
        const dates = s.map((r) => r.trade_date);
        const rows = env.rows as DrawdownRow[];
        const l20 = c.leadership?.find((l) => l.horizon === 20);
        const l60 = c.leadership?.find((l) => l.horizon === 60);
        const bandSeries = BANDS.map((b, i) => ({
          id: b.key,
          label: b.label,
          tone: (['accent', 'up', 'violet'] as const)[i],
          points: rebasePct(s.map((r) => r[`ew_${b.key}` as 'ew_large'] ?? null)).map((y, x) => ({ x, y })),
        }));
        return (
          <div className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3">
            <Caveat text={caveatOf(env.meta)} />
            <GlanceBand label="Index study">
              <KpiTile hero label="EW market drawdown now" value={fmtSignedPct(c.today_drawdown_pct ?? null, 1)} caption={`from its high · as of ${fmtDate(env.as_of)}`} />
              <KpiTile label="Falls > 8% in the archive" value={fmtInt(rows.length)} caption={`since ${fmtDate(dates[0] ?? null)}`} />
              <KpiTile label="Leader, 20 sessions" value={l20?.leader_now ?? '—'} caption={`L ${fmtSignedPct(l20?.large_pct, 1)} · M ${fmtSignedPct(l20?.mid_pct, 1)} · S ${fmtSignedPct(l20?.small_pct, 1)}`} />
              <KpiTile label="Leader, 60 sessions" value={l60?.leader_now ?? '—'} caption={`L ${fmtSignedPct(l60?.large_pct, 1)} · M ${fmtSignedPct(l60?.mid_pct, 1)} · S ${fmtSignedPct(l60?.small_pct, 1)}`} />
            </GlanceBand>
            <div className="grid gap-3 xl:grid-cols-2">
              <Panel title="Equal-weight market and its drawdown" bodyClassName="space-y-1 p-2">
                <PathChart
                  label="EW market drawdown from its high"
                  series={[{ id: 'dd', label: 'Drawdown', tone: 'down', points: s.map((r, i) => ({ x: i, y: r.drawdown_pct })) }]}
                  xTicks={dateTicks(dates, 6)}
                  yFormat={(v) => `${fmtNum(v, 0)}%`}
                  height={170}
                />
              </Panel>
              <Panel title="Size leadership (rebased to 0%)" bodyClassName="space-y-1 p-2">
                <PathChart label="Large vs mid vs small equal-weight" series={bandSeries} xTicks={dateTicks(dates, 6)} yFormat={(v) => `${fmtNum(v, 0)}%`} height={170} />
                <Legend items={bandSeries.map((b) => ({ label: b.label, tone: b.tone }))} />
                <p className="text-2xs text-fg-3">
                  Share of days each band led over 60 sessions: large {fmtPct(l60?.large_led_share_pct, 0)}, mid {fmtPct(l60?.mid_led_share_pct, 0)}, small{' '}
                  {fmtPct(l60?.small_led_share_pct, 0)} (n={fmtInt(l60?.n)}).
                </p>
              </Panel>
            </div>
            <Panel title="Every fall > 8% (equal-weight market)">
              <SimpleTable<DrawdownRow>
                label="Drawdown table"
                rows={rows}
                rowKey={(r) => r.peak_date ?? ''}
                rowClassName={(r) => (r.ongoing ? 'bg-accent/10' : undefined)}
                empty="No fall of more than 8% in the archive."
                columns={[
                  { id: 'pk', header: 'High', cell: (r) => fmtDate(r.peak_date ?? null) },
                  { id: 'lo', header: 'Low', cell: (r) => fmtDate(r.trough_date ?? null) },
                  { id: 'd', header: 'Depth', align: 'right', cell: (r) => <span className="text-down">{fmtSignedPct(r.depth_pct, 1)}</span> },
                  { id: 'sd', header: 'Sessions down', align: 'right', cell: (r) => fmtInt(r.sessions_down) },
                  { id: 'rec', header: 'Recovered', cell: (r) => (r.ongoing ? <Muted>not yet</Muted> : fmtDate(r.recovered_date ?? null)) },
                  { id: 'sr', header: 'Sessions to recover', align: 'right', cell: (r) => fmtInt(r.sessions_to_recover) },
                  { id: 'b', header: 'Above 50 EMA at the low', align: 'right', cell: (r) => fmtPct(r.breadth_above_50ema_at_low, 0) },
                ]}
              />
              <ul className="space-y-0.5 px-3 py-1.5 text-2xs text-fg-3">
                {(c.notes ?? []).map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </Panel>
          </div>
        );
      }}
    </QueryState>
  );
}
