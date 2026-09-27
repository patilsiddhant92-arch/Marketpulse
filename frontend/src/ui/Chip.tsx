import type { ReactNode } from 'react';
import { cn } from '../lib/cn';

export type ChipTone = 'neutral' | 'positive' | 'negative' | 'warn' | 'info' | 'accent' | 'violet';

/** soft = tinted fill (default); outline = border only; dot = coloured dot + quiet text. */
export type ChipVariant = 'soft' | 'outline' | 'dot';

const SOFT: Record<ChipTone, string> = {
  neutral: 'bg-surface-3/80 text-fg-2 border-line/80',
  positive: 'bg-up/10 text-up border-up/25',
  negative: 'bg-down/10 text-down border-down/25',
  warn: 'bg-warn/10 text-warn border-warn/25',
  info: 'bg-info/10 text-info border-info/25',
  accent: 'bg-accent/10 text-accent border-accent/30',
  violet: 'bg-violet/10 text-violet border-violet/25',
};
const OUTLINE: Record<ChipTone, string> = {
  neutral: 'text-fg-2 border-line-strong',
  positive: 'text-up border-up/40',
  negative: 'text-down border-down/40',
  warn: 'text-warn border-warn/40',
  info: 'text-info border-info/40',
  accent: 'text-accent border-accent/40',
  violet: 'text-violet border-violet/40',
};
const DOT: Record<ChipTone, string> = {
  neutral: 'bg-fg-3',
  positive: 'bg-up',
  negative: 'bg-down',
  warn: 'bg-warn',
  info: 'bg-info',
  accent: 'bg-accent',
  violet: 'bg-violet',
};

export interface ChipProps {
  children: ReactNode;
  tone?: ChipTone;
  variant?: ChipVariant;
  size?: 'xs' | 'sm';
  title?: string;
  icon?: ReactNode;
  /** Makes the chip a button (e.g. removable filter chip, quadrant link). */
  onClick?: () => void;
  selected?: boolean;
  className?: string;
}

/** Small status / label pill. Renders a <button> when onClick is given. */
export function Chip({ children, tone = 'neutral', variant = 'soft', size = 'xs', title, icon, onClick, selected, className }: ChipProps) {
  const cls = cn(
    'inline-flex items-center gap-1 whitespace-nowrap rounded-[3px] font-medium leading-none',
    size === 'xs' ? 'h-[18px] px-1.5 text-2xs' : 'h-6 px-2 text-xs',
    variant === 'dot' ? 'border border-transparent text-fg-2' : cn('border', variant === 'outline' ? OUTLINE[tone] : SOFT[tone]),
    selected && 'ring-1 ring-inset ring-accent',
    onClick && 'cursor-pointer transition-[filter,background-color] duration-fast hover:brightness-125',
    className,
  );
  const content = (
    <>
      {variant === 'dot' && <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', DOT[tone])} aria-hidden />}
      {icon}
      {children}
    </>
  );
  if (onClick) {
    return (
      <button type="button" className={cls} title={title} onClick={onClick} aria-pressed={selected}>
        {content}
      </button>
    );
  }
  return (
    <span className={cls} title={title}>
      {content}
    </span>
  );
}

export interface BadgeProps {
  children: ReactNode;
  tone?: ChipTone;
  title?: string;
  className?: string;
}

/** Compact numeric badge (counts on tabs, "+26 new"). */
export function Badge({ children, tone = 'neutral', title, className }: BadgeProps) {
  return (
    <span
      title={title}
      className={cn(
        'num inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1.5 text-2xs font-semibold leading-none',
        SOFT[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
