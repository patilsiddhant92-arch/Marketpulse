/** Setups → Presets "at a glance" band — built from the run the tab already loaded. */
import { useMemo } from 'react';
import type { EvidenceRow } from '../api/types';
import { countWhere, medianOf, topCount } from '../lib/glance';
import { fmtDate, fmtInt, fmtNum } from '../lib/fmt';
import { GlanceBand } from '../ui/GlanceBand';
import { KpiTile } from '../ui/KpiTile';
import type { SRow } from './columns';

export interface ScreenerGlanceProps {
  presetLabel: string;
  rows: readonly SRow[];
  total: number | null | undefined;
  asOf: string | null | undefined;
  newCount: number | null | undefined;
  droppedCount: number;
  previousSession: string | null | undefined;
  evidence: EvidenceRow | undefined;
  custom: boolean;
  loading: boolean;
}

export function ScreenerGlance({
  presetLabel,
  rows,
  total,
  asOf,
  newCount,
  droppedCount,
  previousSession,
  evidence,
  custom,
  loading,
}: ScreenerGlanceProps) {
  const top = useMemo(() => topCount(rows, (r) => r.industry), [rows]);
  const leaders = useMemo(() => countWhere(rows, (r) => (r.rs_percentile ?? -1) >= 90), [rows]);
  const medStrength = useMemo(() => medianOf(rows, (r) => r.rs_percentile), [rows]);
  const n = rows.length;
  const ev = custom || !evidence ? null : evidence.insufficient_sample ? null : evidence.hit_rate_2r;
  return (
    <GlanceBand label="Presets at a glance">
      <KpiTile
        hero
        tone="accent"
        label={<>{custom ? 'Custom rules' : presetLabel} · passing</>}
        value={total ?? null}
        format="int"
        caption={asOf ? `stocks passing every rule · ${fmtDate(asOf)}` : undefined}
        loading={loading}
        className="!min-w-[220px] !flex-[1.3]"
      />
      <KpiTile
        label="New today"
        value={newCount ?? null}
        format="int"
        tone={newCount ? 'up' : 'neutral'}
        caption={previousSession ? `not in list on ${fmtDate(previousSession)}` : undefined}
        loading={loading}
      />
      <KpiTile
        label="Dropped"
        value={loading ? null : droppedCount}
        format="int"
        tone={droppedCount ? 'warn' : 'neutral'}
        caption="left the list since yesterday"
        loading={loading}
      />
      <KpiTile
        label="Top group"
        value={top ? <span className="text-title text-fg">{top.key}</span> : null}
        caption={top ? `${fmtInt(top.count)} of ${fmtInt(n)} in the list` : 'no industry data'}
        hint={top ? 'Industry with the most stocks in this run' : undefined}
        loading={loading}
        className="!min-w-[200px] !flex-[1.4]"
      />
      <KpiTile
        label="Strength ≥ 90"
        metricKey="rs_percentile"
        value={loading ? null : n ? leaders : null}
        format="int"
        tone="neutral"
        caption={medStrength != null ? `median strength ${fmtNum(medStrength, 0)}` : undefined}
        loading={loading}
      />
      <KpiTile
        label="Evidence · hit +2R"
        value={
          ev ?? (
            <span className="text-sm text-fg-3">
              {custom ? 'n/a — custom' : evidence?.insufficient_sample ? `n=${evidence.n}, too few` : '—'}
            </span>
          )
        }
        format="pct"
        digits={0}
        tone="neutral"
        caption={evidence && ev != null ? `avg ${fmtNum(evidence.avg_r, 2)}R · n=${fmtInt(evidence.n)}` : 'stored outcomes per setup'}
        loading={loading}
      />
    </GlanceBand>
  );
}
