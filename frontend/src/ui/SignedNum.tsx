/** A signed number coloured by sign (up / down tokens); NULL renders as the standard "—". One look on every tab. */
import { cn } from '../lib/cn';
import { fmtValue, isNum, type FormatKind } from '../lib/fmt';

export function SignedNum({ value, format = 'signedPct', digits = 1, className }: { value: unknown; format?: FormatKind; digits?: number; className?: string }) {
  const v = isNum(value) ? value : null;
  return <span className={cn('num', v === null ? 'text-fg-3' : v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-fg-2', className)}>{fmtValue(v, format, digits)}</span>;
}
