import { AlertTriangle, CloudOff, Hourglass, PackageOpen } from 'lucide-react';
import type { ReactNode } from 'react';
import { isApiError } from '../api/client';
import { cn } from '../lib/cn';

export interface ErrorDescription {
  title: string;
  detail: string;
  tone: 'down' | 'warn' | 'muted';
  icon: ReactNode;
}

/** Map any thrown value to user-facing copy. Exported for banners/tests. */
export function describeError(error: unknown): ErrorDescription {
  if (isApiError(error)) {
    switch (error.kind) {
      case 'network':
        return {
          title: 'API unreachable',
          detail: 'The MarketPulse server is not responding. Start it, then retry.',
          tone: 'down',
          icon: <CloudOff className="h-5 w-5" />,
        };
      case 'not_found':
        return {
          title: 'Not available yet',
          detail: `${error.path} has not shipped on this server (404).`,
          tone: 'muted',
          icon: <PackageOpen className="h-5 w-5" />,
        };
      case 'busy': {
        const s = error.retryAfterMs != null ? Math.ceil(error.retryAfterMs / 1000) : null;
        return {
          title: 'Database busy',
          detail: s != null ? `The EOD job holds the database. Retrying in ${s}s.` : 'The database is busy or data is being refreshed.',
          tone: 'warn',
          icon: <Hourglass className="h-5 w-5" />,
        };
      }
      case 'parse':
        return {
          title: 'Unexpected response',
          detail: `${error.path} did not return a v2 envelope.`,
          tone: 'down',
          icon: <AlertTriangle className="h-5 w-5" />,
        };
      default:
        return {
          title: error.status ? `Request failed (${error.status})` : 'Request failed',
          detail: error.message,
          tone: 'down',
          icon: <AlertTriangle className="h-5 w-5" />,
        };
    }
  }
  return {
    title: 'Something went wrong',
    detail: error instanceof Error ? error.message : String(error),
    tone: 'down',
    icon: <AlertTriangle className="h-5 w-5" />,
  };
}

export interface ErrorStateProps {
  error: unknown;
  onRetry?: () => void;
  /** Override the title (keep the mapped detail). */
  title?: string;
  compact?: boolean;
  className?: string;
}

const TONE: Record<ErrorDescription['tone'], string> = {
  down: 'text-down',
  warn: 'text-warn',
  muted: 'text-fg-3',
};
const DISC: Record<ErrorDescription['tone'], string> = {
  down: 'border-down/30 bg-down/10',
  warn: 'border-warn/30 bg-warn/10',
  muted: 'border-line bg-surface-2',
};

export function ErrorState({ error, onRetry, title, compact, className }: ErrorStateProps) {
  const d = describeError(error);
  return (
    <div role="alert" className={cn('mp-fade-in flex flex-col items-center justify-center gap-1.5 text-center', compact ? 'p-3' : 'p-10', className)}>
      <div
        className={cn(
          'flex items-center justify-center rounded-full border [&>svg]:h-4 [&>svg]:w-4',
          compact ? 'h-7 w-7' : 'mb-1 h-9 w-9',
          TONE[d.tone],
          DISC[d.tone],
        )}
      >
        {d.icon}
      </div>
      <div className={cn('text-sm font-medium', TONE[d.tone])}>{title ?? d.title}</div>
      <div className="max-w-md text-xs leading-relaxed text-fg-3">{d.detail}</div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded border border-line-strong bg-surface-2 px-3 py-1 text-xs font-medium text-fg-2 transition-colors duration-fast hover:bg-surface-3 hover:text-fg"
        >
          Retry
        </button>
      )}
    </div>
  );
}
