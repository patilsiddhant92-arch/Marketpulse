import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '../lib/cn';

export interface CardProps extends HTMLAttributes<HTMLElement> {
  children: ReactNode;
  /** `raised` lifts the card one surface step (popovers, focused panels). */
  tone?: 'base' | 'raised' | 'inset';
  as?: 'section' | 'div' | 'article';
}

const TONES = {
  base: 'bg-surface border-line',
  raised: 'bg-surface-2 border-line-strong/70',
  inset: 'bg-bg border-line',
} as const;

/**
 * The one surface container: hairline border, 6px radius, soft drop shadow.
 * Everything that groups content on a tab (panels, bands, drawers) sits on it.
 */
export function Card({ children, tone = 'base', as: Tag = 'section', className, ...rest }: CardProps) {
  return (
    <Tag {...rest} className={cn('rounded-card border shadow-card', TONES[tone], className)}>
      {children}
    </Tag>
  );
}

export interface SectionHeaderProps {
  title: ReactNode;
  /** Muted text after the title (counts, as-of, source). */
  meta?: ReactNode;
  /** Right-aligned controls. */
  actions?: ReactNode;
  /** Optional leading icon (lucide, 14px). */
  icon?: ReactNode;
  /** `bar` = panel header strip with bottom rule; `plain` = inline heading. */
  variant?: 'bar' | 'plain';
  /** Heading level (default h2). */
  level?: 2 | 3;
  className?: string;
}

/** Section title row: uppercase label title + muted meta + right actions. */
export function SectionHeader({ title, meta, actions, icon, variant = 'bar', level = 2, className }: SectionHeaderProps) {
  const H = level === 2 ? 'h2' : 'h3';
  return (
    <header
      className={cn(
        'flex shrink-0 items-center gap-2',
        variant === 'bar' ? 'h-9 border-b border-line/80 px-3' : 'min-h-6',
        className,
      )}
    >
      {icon && <span className="flex text-fg-3 [&>svg]:h-3.5 [&>svg]:w-3.5">{icon}</span>}
      <H className="mp-label whitespace-nowrap !text-fg-2">{title}</H>
      {meta && <span className="min-w-0 truncate text-2xs text-fg-3">{meta}</span>}
      {actions && <div className="ml-auto flex shrink-0 items-center gap-1">{actions}</div>}
    </header>
  );
}
