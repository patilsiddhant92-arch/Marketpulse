import { TriangleAlert } from 'lucide-react';
import { Chip } from './Chip';

/**
 * Served `data_warning` (an unexplained price gap inside a metric window — the API serves those
 * metrics as NULL, shown as "—"). Renders nothing when there is no warning.
 */
export function DataWarningChip({ warning, size = 'xs' }: { warning?: string | null; size?: 'xs' | 'sm' }) {
  if (!warning) return null;
  return (
    <Chip tone="warn" size={size} title={warning} icon={<TriangleAlert className="h-3 w-3" aria-hidden />}>
      <span aria-label={`Data warning: ${warning}`}>data gap</span>
    </Chip>
  );
}
