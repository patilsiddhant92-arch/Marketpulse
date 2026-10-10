/**
 * Charts source picker (spec 7.8): Desk queues · Screener presets / last custom run · Setups views ·
 * Groups at any level (searchable) · Pulse movers · Deals (session, Watch, History, house buys) ·
 * Watchlist · Peers · Paste list. "Pre-move watch" was dropped (sprint 2 wiring).
 */
import { ChevronDown } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { apiQueryKey, useApiQuery } from '../api/query';
import { getRawEnvelope } from '../api/raw';
import { cn } from '../lib/cn';
import { useEscapeLayer } from '../lib/layers';
import { loadLastRun } from '../screener/model';
import { useAsOf } from '../shell/urlState';
import { DEALS_LABELS, LEVEL_LABELS, PULSE_MOVER_LABELS, QUEUE_LABELS, SETUPS_LABELS, parseSource, parseSymbolText, type ParsedSource } from './sources';

type Cat = 'desk' | 'screener' | 'setups' | 'groups' | 'pulse' | 'deals' | 'watchlist' | 'peers' | 'paste';
const CATS: { id: Cat; label: string }[] = [
  { id: 'desk', label: 'Desk queues' },
  { id: 'screener', label: 'Screener' },
  { id: 'setups', label: 'Setups' },
  { id: 'groups', label: 'Groups' },
  { id: 'pulse', label: 'Pulse movers' },
  { id: 'deals', label: 'Deals' },
  { id: 'watchlist', label: 'Watchlist' },
  { id: 'peers', label: 'Peers' },
  { id: 'paste', label: 'Paste list' },
];

function catOf(src: ParsedSource | null): Cat {
  switch (src?.kind) {
    case 'screener':
      return 'screener';
    case 'group':
      return 'groups';
    case 'deals':
      return 'deals';
    case 'pulse':
      return 'pulse';
    case 'setups':
      return 'setups';
    case 'watchlist':
      return 'watchlist';
    case 'list':
      return 'paste';
    case 'peers':
      return 'peers';
    default:
      return 'desk';
  }
}

export interface SourcePickerProps {
  value: string;
  label: string;
  count: number | null;
  watchCount: number;
  onChange: (src: string) => void;
  /** Current chart symbol (Peers of …). */
  current?: string | null;
  /** Pasted symbols (TradingView export or one per line) -> an editable list. */
  onPaste?: (symbols: string[]) => void;
}

export function SourcePicker({ value, label, count, watchCount, onChange, current, onPaste }: SourcePickerProps) {
  const [pasteText, setPasteText] = useState('');
  const pasted = useMemo(() => parseSymbolText(pasteText), [pasteText]);
  const [open, setOpen] = useState(false);
  const parsed = parseSource(value);
  const [cat, setCat] = useState<Cat>(catOf(parsed));
  const [level, setLevel] = useState<string>(parsed?.kind === 'group' ? parsed.key : 'industry');
  const [q, setQ] = useState('');
  const ref = useRef<HTMLDivElement>(null);
  useEscapeLayer(open, () => setOpen(false));
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener('mousedown', onDown);
    return () => window.removeEventListener('mousedown', onDown);
  }, [open, value]);

  const presets = useApiQuery('screener/presets', {}, { staleTime: Infinity, enabled: open });
  const board = useApiQuery(
    'groups/board',
    { query: { level: level as 'industry', floor: '1000', limit: 500 } },
    { enabled: open && cat === 'groups' },
  );
  const groups = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (board.data?.rows ?? [])
      .filter((g) => g.group_name && (!s || g.group_name.toLowerCase().includes(s)))
      .sort((a, b) => (a.rank ?? 9999) - (b.rank ?? 9999));
  }, [board.data, q]);
  const lastRun = open ? loadLastRun() : null;
  const [asOf] = useAsOf();
  const houses = useQuery({
    queryKey: apiQueryKey('deals/tab/houses', null, { limit: 500 }, asOf),
    queryFn: ({ signal }) => getRawEnvelope<{ house: string; bought_cr?: number | null; symbols?: string[] }>('deals/tab/houses', { limit: 500, ...(asOf ? { as_of: asOf } : {}) }, signal),
    enabled: open && cat === 'deals',
    staleTime: 5 * 60_000,
    retry: false,
  });

  const pick = (src: string) => {
    onChange(src);
    setOpen(false);
  };
  const item = (src: string, text: string, sub?: string, disabled?: boolean) => (
    <button
      key={src}
      type="button"
      disabled={disabled}
      onClick={() => pick(src)}
      className={cn(
        'flex w-full items-baseline gap-2 rounded px-2 py-1 text-left text-xs hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-40',
        value === src ? 'bg-accent/10 text-accent' : 'text-fg',
      )}
    >
      <span className="truncate">{text}</span>
      {sub && <span className="ml-auto shrink-0 text-2xs text-fg-3">{sub}</span>}
    </button>
  );

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => {
          if (!open) setCat(catOf(parseSource(value)));
          setOpen(!open);
        }}
        aria-expanded={open}
        aria-haspopup="dialog"
        className="flex h-7 max-w-[340px] items-center gap-1.5 rounded border border-line-strong bg-surface-2 px-2 text-xs text-fg hover:border-accent"
      >
        <span className="text-2xs uppercase tracking-wide text-fg-3">Source</span>
        <span className="truncate font-medium">{label}</span>
        {count != null && <span className="num text-fg-3">({count})</span>}
        <ChevronDown className="h-3 w-3 shrink-0 text-fg-3" />
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Choose chart source"
          className="absolute left-0 top-full z-40 mt-1 flex h-[380px] w-[560px] overflow-hidden rounded-md border border-line-strong bg-surface-2 shadow-2xl"
        >
          <div className="w-36 shrink-0 border-r border-line p-1">
            {CATS.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setCat(c.id)}
                className={cn(
                  'block w-full rounded px-2 py-1 text-left text-xs',
                  cat === c.id ? 'bg-surface-3 text-fg' : 'text-fg-2 hover:text-fg',
                )}
              >
                {c.label}
              </button>
            ))}
          </div>
          <div className="flex min-w-0 flex-1 flex-col overflow-hidden p-1">
            {cat === 'desk' && (
              <div className="overflow-auto">
                {item('queue:all', 'All queues', 'merged, de-duplicated')}
                {Object.entries(QUEUE_LABELS).map(([k, l]) => item(`queue:${k}`, l))}
                <p className="px-2 pt-2 text-2xs text-fg-3">
                  Same predicates as the Desk. The first call of a session computes live and can take 10–30 s.
                </p>
              </div>
            )}
            {cat === 'screener' && (
              <div className="overflow-auto">
                {item('screener:custom', lastRun ? `Last custom run — ${lastRun.label}` : 'Last custom run', undefined, !lastRun)}
                <div className="my-1 border-t border-line" />
                {(presets.data?.rows ?? []).map((p) => item(`screener:${p.id}`, p.label, p.category ?? undefined, !p.available))}
                {presets.isLoading && <div className="px-2 py-1 text-xs text-fg-3">Loading presets…</div>}
              </div>
            )}
            {cat === 'groups' && (
              <>
                <div className="flex shrink-0 gap-1 pb-1">
                  {Object.entries(LEVEL_LABELS).map(([k, l]) => (
                    <button
                      key={k}
                      type="button"
                      onClick={() => setLevel(k)}
                      className={cn('rounded px-1.5 py-0.5 text-2xs', level === k ? 'bg-accent/15 text-accent' : 'text-fg-2 hover:text-fg')}
                    >
                      {l}
                    </button>
                  ))}
                </div>
                <input
                  autoFocus
                  aria-label="Search groups"
                  placeholder={`Search ${LEVEL_LABELS[level]}…`}
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  className="mb-1 h-6 shrink-0 rounded border border-line bg-surface px-1.5 text-xs text-fg focus:border-accent focus:outline-none"
                />
                <div className="min-h-0 flex-1 overflow-auto">
                  {board.isLoading && <div className="px-2 py-1 text-xs text-fg-3">Loading groups…</div>}
                  {groups.map((g) =>
                    item(`group:${level}:${g.group_name}`, g.group_name ?? '', g.rank != null ? `rank #${g.rank}` : undefined),
                  )}
                  {!board.isLoading && groups.length === 0 && <div className="px-2 py-1 text-xs text-fg-3">No group matches.</div>}
                </div>
              </>
            )}
            {cat === 'setups' && (
              <div className="overflow-auto">
                {Object.entries(SETUPS_LABELS).map(([k, l]) => item(`setups:${k}`, l))}
                <p className="px-2 pt-2 text-2xs text-fg-3">The Setups board with its default momentum template and volume gate.</p>
              </div>
            )}
            {cat === 'pulse' && (
              <div className="overflow-auto">
                {Object.entries(PULSE_MOVER_LABELS).map(([k, l]) => item(`pulse:${k}`, l, 'top 20'))}
                <p className="px-2 pt-2 text-2xs text-fg-3">Pulse "Stocks that moved" (≥ ₹1,000 Cr).</p>
              </div>
            )}
            {cat === 'deals' && (
              <div className="min-h-0 flex-1 overflow-auto">
                {(['watch', 'history', 'houses', 'buy', 'sell'] as const).map((k) => item(`deals:${k}`, DEALS_LABELS[k]))}
                <div className="mt-1 border-t border-line px-2 pb-0.5 pt-1.5 text-2xs uppercase tracking-wide text-fg-3">House buys · one house</div>
                {houses.isLoading && <div className="px-2 py-1 text-xs text-fg-3">Loading houses…</div>}
                {(houses.data?.rows ?? []).slice(0, 60).map((h) =>
                  item(`deals:house:${h.house}`, h.house, `${(h.symbols ?? []).length} stock${(h.symbols ?? []).length === 1 ? '' : 's'}`),
                )}
                {!houses.isLoading && !houses.data?.rows.length && <div className="px-2 py-1 text-xs text-fg-3">No houses bought in the window.</div>}
              </div>
            )}
            {cat === 'watchlist' && <div className="overflow-auto">{item('watchlist', 'Watchlist', `${watchCount} stocks`)}</div>}
            {cat === 'peers' && (
              <div className="overflow-auto">
                {current ? item(`peers:${current}`, `Peers of ${current}`, 'same industry, by strength') : null}
                <p className="px-2 pt-2 text-2xs text-fg-3">
                  {current ? 'The stock first, then its industry peers (≥ ₹1,000 Cr), strongest first.' : 'Open a stock first.'}
                </p>
              </div>
            )}
            {cat === 'paste' && (
              <div className="flex min-h-0 flex-1 flex-col gap-1 p-1">
                <textarea
                  aria-label="Paste symbols"
                  value={pasteText}
                  onChange={(e) => setPasteText(e.target.value)}
                  placeholder={'NSE:HAL,NSE:BEL or one symbol per line\n(a TradingView export works as-is)'}
                  className="min-h-0 flex-1 resize-none rounded border border-line bg-surface p-1.5 font-mono text-xs text-fg focus:border-accent focus:outline-none"
                />
                <button
                  type="button"
                  disabled={!pasted.length || !onPaste}
                  onClick={() => {
                    onPaste?.(pasted);
                    setPasteText('');
                    setOpen(false);
                  }}
                  className="h-7 shrink-0 rounded border border-line bg-accent/15 px-2 text-xs text-accent disabled:opacity-40"
                >
                  Open {pasted.length} symbol{pasted.length === 1 ? '' : 's'} as a list
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
