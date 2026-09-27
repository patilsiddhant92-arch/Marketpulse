import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { apiPut } from '../api/client';
import { useApiQuery } from '../api/query';
import type { Envelope, StockDealRow, StockEventRow } from '../api/types';
import { cn } from '../lib/cn';
import { fmtCr, fmtDateShort, fmtDateWithDay, fmtINR, fmtNum } from '../lib/fmt';
import { Chip } from '../ui/Chip';
import { ErrorState } from '../ui/ErrorState';
import { Panel } from '../ui/Panel';
import { Skeleton } from '../ui/Skeleton';
import { dealNet, dealSide } from './stockModel';

const SHOW = 8;

function MoreToggle({ shown, total, open, onToggle }: { shown: number; total: number; open: boolean; onToggle: () => void }) {
  if (total <= SHOW) return null;
  return (
    <button type="button" onClick={onToggle} className="px-3 py-1.5 text-left text-2xs text-info hover:underline">
      {open ? 'Show fewer' : `Showing ${shown} of ${total} · show all`}
    </button>
  );
}

function eventLabel(t: string | null | undefined): string {
  if (!t) return 'event';
  return t.replace(/^adjustment:/, 'adjustment · ').replace(/_/g, ' ');
}

export function EventsBlock({
  q,
  className,
}: {
  q: { data?: Envelope<StockEventRow>; isLoading: boolean; error: unknown; refetch: () => unknown };
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const rows = q.data?.rows ?? [];
  const upcoming = rows.filter((r) => r.upcoming).sort((a, b) => (a.event_date ?? '').localeCompare(b.event_date ?? ''));
  const past = rows.filter((r) => !r.upcoming);
  const list = open ? past : past.slice(0, SHOW);
  return (
    <Panel title="Events" meta={q.data ? `${upcoming.length} upcoming ≤ 14 days · ${past.length} past` : undefined} className={className}>
      {q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} compact />
      ) : q.isLoading ? (
        <div className="p-3">
          <Skeleton height={48} />
        </div>
      ) : rows.length === 0 ? (
        <p className="px-3 py-2 text-2xs text-fg-3">No announcements or corporate actions on record.</p>
      ) : (
        <ul className="divide-y divide-line text-xs">
          {upcoming.map((e, i) => (
            <li key={`u${i}`} className="flex gap-2 bg-warn/5 px-3 py-1.5">
              <span className="num w-16 shrink-0 font-medium text-warn">{fmtDateShort(e.event_date)}</span>
              <span className="min-w-0">
                <Chip tone="warn">{eventLabel(e.event_type)}</Chip> <span className="text-fg-2">{e.headline ?? ''}</span>
              </span>
            </li>
          ))}
          {list.map((e, i) => (
            <li key={`p${i}`} className="flex gap-2 px-3 py-1.5" title={fmtDateWithDay(e.event_date)}>
              <span className="num w-16 shrink-0 text-fg-3">{fmtDateShort(e.event_date)}</span>
              <span className="min-w-0 text-fg-2">
                <span className="text-fg-3">{eventLabel(e.event_type)}</span>
                {e.headline ? <span className="line-clamp-2"> {e.headline}</span> : null}
              </span>
            </li>
          ))}
        </ul>
      )}
      <MoreToggle shown={list.length} total={past.length} open={open} onToggle={() => setOpen((o) => !o)} />
    </Panel>
  );
}

export function DealsBlock({
  q,
  className,
}: {
  q: { data?: Envelope<StockDealRow>; isLoading: boolean; error: unknown; refetch: () => unknown };
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const rows = q.data?.rows ?? [];
  const inst = rows.filter((r) => r.institutional === true);
  const net = dealNet(inst);
  const list = open ? rows : rows.slice(0, SHOW);
  return (
    <Panel
      title="Bulk / block deals"
      meta={
        q.data
          ? `${rows.length} prints · institutional net ${net.net == null ? '—' : fmtCr(net.net, 1)}`
          : undefined
      }
      className={className}
    >
      {q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} compact />
      ) : q.isLoading ? (
        <div className="p-3">
          <Skeleton height={48} />
        </div>
      ) : rows.length === 0 ? (
        <p className="px-3 py-2 text-2xs text-fg-3">No disclosed bulk or block deals up to this date.</p>
      ) : (
        <table className="w-full text-table">
          <thead className="text-2xs text-fg-3">
            <tr className="border-b border-line">
              <th className="px-3 py-1 text-left font-medium">Date</th>
              <th className="px-1 py-1 text-left font-medium">Client</th>
              <th className="px-1 py-1 text-left font-medium" title="Client class (FII / DII / corporate / individual…)">
                Class
              </th>
              <th className="px-1 py-1 text-left font-medium">Side</th>
              <th className="px-3 py-1 text-right font-medium">₹ Cr</th>
            </tr>
          </thead>
          <tbody>
            {list.map((d, i) => {
              const side = dealSide(d.side);
              return (
                <tr key={i} className="border-b border-line/60 last:border-0">
                  <td className="num px-3 py-1 text-fg-3">{fmtDateShort(d.trade_date)}</td>
                  <td className="max-w-[180px] truncate px-1 py-1 text-fg-2" title={`${d.client ?? ''}${d.price != null ? ` @ ${fmtINR(d.price)}` : ''} · ${d.deal_types ?? ''}`}>
                    {d.client ?? '—'}
                  </td>
                  <td className="px-1 py-1">
                    <span className={cn('text-2xs', d.institutional ? 'text-info' : 'text-fg-3')}>
                      {d.clientele ?? '—'}
                      {d.is_prop ? ' · prop' : ''}
                    </span>
                  </td>
                  <td className={cn('px-1 py-1 text-2xs font-semibold', side === 'buy' ? 'text-up' : side === 'sell' ? 'text-down' : 'text-fg-3')}>
                    {side ? side.toUpperCase() : (d.side ?? '—')}
                  </td>
                  <td className="num px-3 py-1 text-right text-fg">{fmtNum(d.value_cr, 2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <MoreToggle shown={list.length} total={rows.length} open={open} onToggle={() => setOpen((o) => !o)} />
    </Panel>
  );
}

/** Per-symbol note, saved to /api/v2/notes/{sym}. */
export function NotesBlock({ symbol, className }: { symbol: string; className?: string }) {
  const qc = useQueryClient();
  const q = useApiQuery('notes/{sym}', { params: { sym: symbol } });
  const saved = q.data?.rows[0];
  const [text, setText] = useState(saved?.body ?? '');
  const [state, setState] = useState<'idle' | 'saving' | 'error'>('idle');
  // Adopt the served note whenever it changes (load / after save); the block is keyed per symbol.
  const [seen, setSeen] = useState(saved?.body);
  if (seen !== saved?.body) {
    setSeen(saved?.body);
    setText(saved?.body ?? '');
  }
  const dirty = text !== (saved?.body ?? '');
  // Esc closes the sidecar (and unmounts this block): flush an unsaved note first.
  const pending = useRef<{ symbol: string; text: string; dirty: boolean }>({ symbol, text, dirty });
  useEffect(() => {
    pending.current = { symbol, text, dirty };
  });
  useEffect(
    () => () => {
      const p = pending.current;
      if (p.dirty) void apiPut('notes/{sym}', { body: p.text }, { params: { sym: p.symbol } }).catch(() => undefined);
    },
    [symbol],
  );

  const save = () => {
    if (!dirty) return;
    setState('saving');
    apiPut('notes/{sym}', { body: text }, { params: { sym: symbol } })
      .then((env) => {
        qc.setQueryData(['v2', 'notes/{sym}', { sym: symbol }, { as_of: null }], env);
        setState('idle');
      })
      .catch(() => setState('error'));
  };

  const updated = saved?.updated_at ? new Date(saved.updated_at) : null;
  return (
    <Panel
      title="Notes"
      meta={
        state === 'saving'
          ? 'saving…'
          : state === 'error'
            ? 'not saved — server unreachable'
            : dirty
              ? 'unsaved'
              : updated
                ? `saved ${updated.toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}`
                : undefined
      }
      actions={
        <button
          type="button"
          onClick={save}
          disabled={!dirty || state === 'saving'}
          className="rounded px-2 py-0.5 text-2xs font-semibold text-accent hover:bg-accent/10 disabled:text-fg-3 disabled:hover:bg-transparent"
        >
          Save
        </button>
      }
      className={className}
    >
      {q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} compact />
      ) : (
        <textarea
          aria-label={`Notes for ${symbol}`}
          value={text}
          disabled={q.isLoading}
          onChange={(e) => setText(e.target.value)}
          onBlur={save}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              save();
            }
          }}
          placeholder="Your plan, levels, why you're watching… (Ctrl+Enter saves)"
          className={cn(
            'block h-24 w-full resize-y bg-transparent px-3 py-2 text-xs text-fg placeholder:text-fg-3 focus:outline-none',
            state === 'error' && 'bg-down/5',
          )}
          maxLength={20000}
        />
      )}
    </Panel>
  );
}
