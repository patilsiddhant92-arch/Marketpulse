/**
 * DealIcon — the cross-tab deal icon beside a symbol on every stock list (Pulse, Setups, Sector Intel, Deals,
 * Charts, Research). Shows only when the stock had a bulk / block deal within the last 10 deal sessions
 * (GET /api/v2/deals/flags via context/dealFlags.ts, one cached request per as_of). Colour = the Deals verdict
 * (or the side when there is no verdict); hover for the story; click opens the Deals stock drawer.
 */
import { useNavigate } from 'react-router';
import { dealHref, dealTitle, dealTone, useDealFlags, type DealFlag } from '../context/dealFlags';
import { cn } from '../lib/cn';
import { useAsOf } from '../shell/urlState';
import type { ChipTone } from './Chip';

const TONE_CLASS: Record<ChipTone, string> = {
  neutral: 'border-line-strong text-fg-3',
  positive: 'border-up/50 bg-up/10 text-up',
  negative: 'border-down/50 bg-down/10 text-down',
  warn: 'border-warn/50 bg-warn/10 text-warn',
  info: 'border-info/50 bg-info/10 text-info',
  accent: 'border-accent/50 bg-accent/10 text-accent',
  violet: 'border-violet/50 bg-violet/10 text-violet',
};

/** Presentational: the badge for one flag (null -> nothing). */
export function DealBadge({ flag, onClick, className }: { flag: DealFlag | null | undefined; onClick?: () => void; className?: string }) {
  if (!flag?.has_recent_deal) return null;
  const tone = dealTone(flag);
  const title = dealTitle(flag);
  const cls = cn(
    'inline-flex h-[14px] min-w-[14px] shrink-0 items-center justify-center rounded-[3px] border px-[2px] text-[9px] font-bold leading-none',
    TONE_CLASS[tone],
    onClick && 'cursor-pointer hover:brightness-125',
    className,
  );
  const label = `Deal: ${title}`;
  if (onClick) {
    return (
      <button
        type="button"
        className={cls}
        title={title}
        aria-label={label}
        data-testid="deal-icon"
        data-tone={tone}
        onClick={(e) => {
          e.stopPropagation();
          onClick();
        }}
      >
        D
      </button>
    );
  }
  return (
    <span className={cls} title={title} aria-label={label} role="img" data-testid="deal-icon" data-tone={tone}>
      D
    </span>
  );
}

/** Connected: the deal icon for a symbol (renders nothing when there is no recent deal). */
export function DealIcon({ symbol, className, link = true }: { symbol: string | null | undefined; className?: string; link?: boolean }) {
  const { map } = useDealFlags(!!symbol);
  const navigate = useNavigate();
  const [asOf] = useAsOf();
  if (!symbol) return null;
  const flag = map.get(symbol.toUpperCase());
  if (!flag) return null;
  const href = dealHref(symbol);
  return (
    <DealBadge
      flag={flag}
      className={className}
      onClick={link ? () => navigate(asOf ? `${href}&as_of=${asOf}` : href) : undefined}
    />
  );
}

/** Symbol text + deal icon: the standard symbol cell for any stock table. */
export function SymbolWithDeal({ symbol, className, children }: { symbol: string; className?: string; children?: React.ReactNode }) {
  return (
    <span className={cn('inline-flex min-w-0 items-center gap-1', className)}>
      {children ?? <span className="font-mono font-medium text-fg">{symbol}</span>}
      <DealIcon symbol={symbol} />
    </span>
  );
}
