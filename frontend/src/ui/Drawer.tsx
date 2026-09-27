import { X } from 'lucide-react';
import { useEffect, useRef, type ReactNode } from 'react';
import { useEscapeLayer } from '../lib/layers';
import { cn } from '../lib/cn';

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  side?: 'right' | 'left';
  width?: number | string;
  /** Header extras (buttons) placed before the close button. */
  actions?: ReactNode;
  className?: string;
}

/** Modal side panel. Esc closes it (innermost layer only); focus moves in. */
export function Drawer({ open, onClose, title, children, side = 'right', width = 520, actions, className }: DrawerProps) {
  useEscapeLayer(open, onClose);
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) panelRef.current?.focus();
  }, [open]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex" role="presentation">
      <div className="absolute inset-0 bg-bg/70" onClick={onClose} aria-hidden />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : undefined}
        tabIndex={-1}
        className={cn(
          'relative flex h-full max-w-full flex-col border-line bg-surface shadow-2xl outline-none',
          side === 'right' ? 'ml-auto border-l' : 'mr-auto border-r',
          className,
        )}
        style={{ width }}
      >
        <div className="flex h-10 shrink-0 items-center gap-2 border-b border-line px-3">
          <div className="min-w-0 flex-1 truncate text-sm font-semibold text-fg">{title}</div>
          {actions}
          <button type="button" onClick={onClose} className="rounded p-1 text-fg-3 hover:bg-surface-3 hover:text-fg" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">{children}</div>
      </div>
    </div>
  );
}
