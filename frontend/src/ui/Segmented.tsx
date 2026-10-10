/** Segmented control (radiogroup): the one toggle style every tab uses for views, levels and windows. */
import type { ReactNode } from 'react';
import { cn } from '../lib/cn';

export interface SegmentedOption<V extends string> {
  value: V;
  label: ReactNode;
  title?: string;
}

export function Segmented<V extends string>({
  options,
  value,
  onChange,
  label,
  size = 'sm',
}: {
  options: readonly SegmentedOption<V>[];
  value: V;
  onChange: (v: V) => void;
  label: string;
  size?: 'xs' | 'sm';
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex shrink-0 rounded border border-line bg-surface-2 p-px">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          title={o.title}
          onClick={() => onChange(o.value)}
          className={cn(
            'whitespace-nowrap rounded-[3px] font-medium',
            size === 'xs' ? 'px-1.5 py-0.5 text-2xs' : 'px-2 py-0.5 text-xs',
            o.value === value ? 'bg-surface-3 text-fg shadow-sm' : 'text-fg-3 hover:text-fg',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
