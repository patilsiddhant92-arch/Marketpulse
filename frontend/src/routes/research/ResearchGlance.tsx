/**
 * Research "at a glance" — what the market analogs say (research/analogs, the
 * tab's default study; shared cache with the Analogs view).
 */
import { useMemo } from 'react';
import type { MarketAnalogRow } from '../../api/types';
import { fmtDate, fmtNum, fmtSignedPct } from '../../lib/fmt';
import { GlanceBand } from '../../ui/GlanceBand';
import { KpiTile } from '../../ui/KpiTile';
import { useResearchQuery } from './data';
import { summarizeAnalogs } from './model';

const EMPTY: MarketAnalogRow[] = [];

export function ResearchGlance() {
  const q = useResearchQuery('research/analogs');
  const rows = q.data?.rows ?? EMPTY;
  const s = useMemo(() => summarizeAnalogs(rows), [rows]);
  const nearest = useMemo(
    () => [...rows].filter((r) => r.distance != null).sort((a, b) => (a.distance ?? 0) - (b.distance ?? 0))[0],
    [rows],
  );
  const latest = useMemo(
    () => [...rows].filter((r) => r.analog_date).sort((a, b) => (b.analog_date ?? '').localeCompare(a.analog_date ?? ''))[0],
    [rows],
  );
  const loading = q.isLoading;
  const unavailable = !loading && (q.error || q.data?.meta.status === 'unavailable' || rows.length === 0);
  const h20 = s.horizons[1];
  const agree = s.agreement20;

  if (unavailable) {
    return (
      <GlanceBand label="Research at a glance" compact>
        <KpiTile
          compact
          label="Market analogs"
          value={
            <span className="text-sm text-fg-3">{q.error ? 'could not load' : q.data?.meta.status === 'unavailable' ? 'not built yet — see the study below' : 'no analogs for this date'}</span>
          }
        />
      </GlanceBand>
    );
  }

  return (
    <GlanceBand label="Research at a glance">
      <KpiTile
        hero
        tone={agree.direction === 'up' ? 'up' : agree.direction === 'down' ? 'down' : 'neutral'}
        label={<>Analogs say · next 20 sessions</>}
        value={agree.share == null ? null : `${Math.round(agree.share * 100)}% ${agree.direction === 'up' ? 'higher' : 'lower'}`}
        caption={`${s.k} nearest past dates · median ${fmtSignedPct(h20.median, 1)}${s.disagree ? ' · analogs split' : ''}`}
        hint="Share of the nearest past market environments whose MidSmallcap 400 moved the same way 20 sessions later (n printed)."
        loading={loading}
        className="!min-w-[260px] !flex-[1.4]"
      />
      <KpiTile
        label="Nearest match"
        value={nearest ? <span className="text-title text-fg">{fmtDate(nearest.analog_date)}</span> : null}
        caption={
          nearest
            ? `distance ${fmtNum(nearest.distance, 2)}${nearest.verdict_then ? ` · then ${nearest.verdict_then}` : ''} · 20d ${fmtSignedPct(nearest.fwd_midsml400_20d_pct, 1)}`
            : undefined
        }
        loading={loading}
        className="!min-w-[200px]"
      />
      <KpiTile
        label={<>Most recent analog{latest?.analog_date ? ` · ${fmtDate(latest.analog_date)}` : ''}</>}
        value={latest?.fwd_midsml400_20d_pct ?? null}
        format="signedPct"
        digits={1}
        tone={latest?.fwd_midsml400_20d_pct == null ? 'neutral' : latest.fwd_midsml400_20d_pct >= 0 ? 'up' : 'down'}
        caption={latest ? `20 sessions later · 60d ${fmtSignedPct(latest.fwd_midsml400_60d_pct, 1)}` : undefined}
        loading={loading}
        className="!min-w-[200px]"
      />
      <KpiTile
        label="Median next 60 sessions"
        value={s.horizons[2].median}
        format="signedPct"
        digits={1}
        tone={s.horizons[2].median == null ? 'neutral' : s.horizons[2].median >= 0 ? 'up' : 'down'}
        caption={`${s.horizons[2].up} up / ${s.horizons[2].down} down · n=${s.horizons[2].n}`}
        loading={loading}
      />
      <KpiTile
        label="Follow-through (median)"
        value={s.followThrough.median}
        format="pct"
        digits={1}
        tone="neutral"
        caption={`next-month breakout follow-through · n=${s.followThrough.n}`}
        loading={loading}
      />
    </GlanceBand>
  );
}
