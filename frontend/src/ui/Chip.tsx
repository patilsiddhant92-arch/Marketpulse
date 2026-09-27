import type { ReactNode } from 'react';
import { cn } from '../lib/cn';

export type ChipTone = 'neutral' | 'positive' | 'negative' | 'warn' | 'info' | 'accent' | 'violet';

const TONES: Record<ChipTone, string> = {
  neutral: 'bg-surface-3 text-fg-2 border-line',
  positive: 'bg-up/10 text-up border-up/30',
  negative: 'bg-down/10 text-down border-down/30',
  warn: 'bg-warn/10 text-warn border-warn/30',
  info: 'bg-info/10 text-info border-info/30',
  accent: 'bg-accent/10 text-accent border-accent/30',
  violet: 'bg-violet/10 text-violet border-violet/30',
};

export interface ChipProps {
  children: ReactNode;
  tone?: ChipTone;
  size?: 'xs' | 'sm';
  title?: string;
  icon?: ReactNode;
  /** Makes the chip a button (e.g. removable filter chip, quadrant link). */
  onClick?: () => void;
  selected?: boolean;
  className?: string;
}

/** Small status / label pill. Renders a <button> when onClick is given. */
export function Chip({ children, tone = 'neutral', size = 'xs', title, icon, onClick, selected, className }: ChipProps) {
  const cls = cn(
    'inline-flex items-center gap-1 whitespace-nowrap rounded border font-medium leading-none',
    size === 'xs' ? 'h-[18px] px-1.5 text-2xs' : 'h-6 px-2 text-xs',
    TONES[tone],
    selected && 'ring-1 ring-inset ring-accent',
    onClick && 'cursor-pointer hover:brightness-125',
    className,
  );
  if (onClick) {
    return (
      <button type="button" className={cls} title={title} onClick={onClick} aria-pressed={selected}>
        {icon}
        {children}
      </button>
    );
  }
  return (
    <span className={cls} title={title}>
      {icon}
      {children}
    </span>
  );
}
