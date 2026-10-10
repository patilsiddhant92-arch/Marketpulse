/** Data source note: "ok" / "computed live" (partial) / "unavailable" chip with the server's reason in a tooltip. */
import { Info } from 'lucide-react';
import type { EnvelopeMeta } from '../api/types';
import { Chip, type ChipTone } from './Chip';
import { Tooltip } from './Tooltip';

/** "Computed live" / "Partial" / "Unavailable" chip with the server's reason in a tooltip. */
export function SourceNote({ meta, liveLabel = 'computed live' }: { meta: EnvelopeMeta | undefined; liveLabel?: string }) {
  if (!meta) return null;
  const status = meta.status ?? 'ok';
  if (status === 'ok') {
    return (
      <Chip tone="positive" title={`Source: ${(meta.sources ?? []).join(', ')}`}>
        {(meta.sources ?? [])[0] ?? 'ok'}
      </Chip>
    );
  }
  const tone: ChipTone = status === 'partial' ? 'warn' : 'negative';
  return (
    <Tooltip
      content={
        <div className="max-w-sm space-y-1">
          <div className="font-medium text-fg">{status === 'partial' ? 'Partial source' : 'Unavailable'}</div>
          {meta.reason && <div className="text-fg-2">{meta.reason}</div>}
          {(meta.notes ?? []).map((n) => (
            <div key={n} className="text-fg-3">
              {n}
            </div>
          ))}
          {meta.sources && meta.sources.length > 0 && <div className="text-fg-3">Tables: {meta.sources.join(', ')}</div>}
        </div>
      }
    >
      <span tabIndex={0} className="inline-flex">
        <Chip tone={tone} icon={<Info className="h-3 w-3" />}>
          {status === 'partial' ? liveLabel : 'unavailable'}
        </Chip>
      </span>
    </Tooltip>
  );
}
