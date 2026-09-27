import { useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { cn } from '../lib/cn';

export interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  side?: 'top' | 'bottom';
  /** Delay before showing, ms. */
  delay?: number;
  className?: string;
  /** Extra classes for the popover panel. */
  panelClassName?: string;
}

/**
 * Hover/focus tooltip rendered in a portal with fixed positioning so it is
 * never clipped by scroll containers (table headers, drawers).
 */
export function Tooltip({ content, children, side = 'bottom', delay = 250, className, panelClassName }: TooltipProps) {
  const id = useId();
  const triggerRef = useRef<HTMLSpanElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);

  const show = () => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(true), delay);
  };
  const hide = () => {
    window.clearTimeout(timer.current);
    setOpen(false);
  };

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const r = triggerRef.current.getBoundingClientRect();
    const panel = panelRef.current;
    const pw = panel?.offsetWidth ?? 280;
    const ph = panel?.offsetHeight ?? 0;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const left = Math.min(Math.max(8, r.left + r.width / 2 - pw / 2), Math.max(8, vw - pw - 8));
    let top = side === 'top' ? r.top - ph - 6 : r.bottom + 6;
    if (top + ph > vh - 8) top = r.top - ph - 6;
    if (top < 8) top = r.bottom + 6;
    setPos({ left, top });
  }, [open, side]);

  if (content === null || content === undefined || content === false) return <>{children}</>;

  return (
    <span
      ref={triggerRef}
      className={cn('inline-flex', className)}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      aria-describedby={open ? id : undefined}
    >
      {children}
      {open &&
        createPortal(
          <div
            ref={panelRef}
            id={id}
            role="tooltip"
            className={cn(
              'pointer-events-none fixed z-[1000] max-w-[320px] rounded border border-line-strong bg-surface-2 px-2.5 py-2 text-xs text-fg-2 shadow-xl',
              panelClassName,
            )}
            style={{ left: pos?.left ?? -9999, top: pos?.top ?? -9999 }}
          >
            {content}
          </div>,
          document.body,
        )}
    </span>
  );
}
