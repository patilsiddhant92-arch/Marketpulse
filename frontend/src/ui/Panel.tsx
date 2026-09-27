import type { ReactNode } from 'react';
import { cn } from '../lib/cn';
import { Card, SectionHeader } from './Card';

export interface PanelProps {
  title: ReactNode;
  /** Small muted text after the title (counts, as-of, source). */
  meta?: ReactNode;
  /** Right-aligned header controls. */
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  /** aria-label when the title is not plain text. */
  label?: string;
  icon?: ReactNode;
}

/** A titled card section used by Desk, Groups, Research and Stock 360. */
export function Panel({ title, meta, actions, children, className, bodyClassName, label, icon }: PanelProps) {
  return (
    <Card
      aria-label={label ?? (typeof title === 'string' ? title : undefined)}
      className={cn('flex min-h-0 flex-col overflow-hidden', className)}
    >
      <SectionHeader title={title} meta={meta} actions={actions} icon={icon} />
      <div className={cn('min-h-0 flex-1', bodyClassName)}>{children}</div>
    </Card>
  );
}
