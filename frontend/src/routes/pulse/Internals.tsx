/** §6 Market internals: six cards (value, change vs lookback average, archive percentile, sparkline, meaning). */
import { DataWarningChip } from '../../ui/DataWarningChip';
import { KpiTile } from '../../ui/KpiTile';
import type { PulseResult } from './data';
import { fixed, lookbackLabel, signed } from './model';
import { SectionBody } from './parts';
import type { InternalRow } from './types';

function valueText(r: InternalRow): string {
  if (r.unit === 'pct') return `${fixed(r.value, 0)}%`;
  if (r.unit === 'count') return signed(r.value, 0);
  return fixed(r.value, 1);
}

export function Internals({ q, lookback }: { q: PulseResult<InternalRow, unknown>; lookback: number }) {
  return (
    <section aria-label="Market internals">
      <SectionBody q={q} rows={2}>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
          {(q.rows ?? []).map((r) => (
            <KpiTile
              key={r.key}
              label={
                <span className="inline-flex items-center gap-1">
                  {r.label}
                  <DataWarningChip warning={r.data_warning} />
                </span>
              }
              value={r.value === null ? null : valueText(r)}
              delta={r.change}
              deltaFormat="signed"
              deltaTone={r.good_direction < 0 ? 'invert' : 'auto'}
              spark={r.series.map((p) => p.value)}
              sparkLabel={`${r.label}, last ${r.series.length} sessions`}
              caption={
                <span>
                  vs {lookbackLabel(lookback)} avg · pctl {fixed(r.pctl, 0)}
                  {r.history_sessions < 120 ? ` (${r.history_sessions} sessions)` : ''}
                  <br />
                  {r.meaning}
                </span>
              }
              compact
            />
          ))}
        </div>
      </SectionBody>
    </section>
  );
}
