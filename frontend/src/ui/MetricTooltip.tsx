import type { MetricDef, MetricZone } from '../api/types';
import { cn } from '../lib/cn';
import { TONE_TEXT, toneForZone } from '../metrics/dictionary';

export interface MetricTooltipBodyProps {
  def: MetricDef | undefined;
  /** Key shown when the dictionary has no entry. */
  metricKey: string;
  activeZone?: MetricZone;
}

/** Body of every metric tooltip: plain name, what it measures, zones, read-with. */
export function MetricTooltipBody({ def, metricKey, activeZone }: MetricTooltipBodyProps) {
  if (!def) {
    return (
      <div className="space-y-0.5">
        <div className="font-mono text-2xs text-fg-3">{metricKey}</div>
        <div>No dictionary entry yet.</div>
      </div>
    );
  }
  return (
    <div className="space-y-1.5">
      <div>
        <div className="font-medium text-fg">{def.plain_name}</div>
        <div className="text-fg-2">{def.measures}</div>
      </div>
      {def.zones.length > 0 && (
        <ul className="space-y-0.5">
          {def.zones.map((z, i) => {
            const tone = toneForZone(z) ?? 'neutral';
            const active = activeZone === z;
            return (
              <li key={i} className={cn('flex gap-2', active && 'rounded bg-surface-3 px-1 -mx-1')}>
                <span className="w-16 shrink-0 font-mono text-fg-3">{z.range}</span>
                <span className={cn('shrink-0 font-medium', TONE_TEXT[tone])}>{z.label}</span>
                {z.why && <span className="text-fg-3">{z.why}</span>}
              </li>
            );
          })}
        </ul>
      )}
      {def.read_with.length > 0 && (
        <div className="text-fg-3">
          Read with: <span className="font-mono">{def.read_with.join(', ')}</span>
          {def.read_with_why && <div className="mt-0.5 text-fg-2">{def.read_with_why}</div>}
        </div>
      )}
      {def.caveats && <div className="border-t border-line pt-1 text-fg-3">{def.caveats}</div>}
    </div>
  );
}
