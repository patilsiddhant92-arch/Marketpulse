/** Stock drawer (verdict, deal-candle chart, buyers / sellers with grades, next action) and house drawer. */
import { useState } from 'react';
import { fmtDate, fmtNum } from '../../lib/fmt';
import { Drawer } from '../../ui/Drawer';
import { EmptyState } from '../../ui/EmptyState';
import { ErrorState } from '../../ui/ErrorState';
import { Skeleton } from '../../ui/Skeleton';
import { useDeals, type HouseContext, type HousePosition, type Party, type StockDetail } from './api';
import { CandleLegend, Chips, DealCandles, DoLine, GradeChip, NotesLine, Signed, StatusChip, TvCopy, VerdictChip } from './kit';
import { readFollowed, spreadSummary, toggleFollowed } from './model';
import { DealIcon } from '../../ui/DealIcon';

function KV({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col rounded border border-line bg-surface-2 px-2 py-1">
      <span className="text-2xs text-fg-3">{k}</span>
      <span className="text-xs text-fg">{children}</span>
    </div>
  );
}

function Parties({ title, list, onHouse }: { title: string; list: readonly Party[]; onHouse: (h: string) => void }) {
  return (
    <div className="space-y-0.5">
      <div className="text-2xs font-semibold uppercase tracking-wide text-fg-3">{title}</div>
      {list.length === 0 ? (
        <div className="text-2xs text-fg-3">None (prop desks excluded)</div>
      ) : (
        list.map((b) => (
          <div key={`${b.house}-${b.name}`} className="flex items-center justify-between gap-2 text-xs">
            <span className="flex min-w-0 items-center gap-1">
              <button type="button" className="truncate text-left text-fg hover:underline" onClick={() => onHouse(b.house)}>
                {b.name}
              </button>
              <span className="text-2xs text-fg-3">{b.buyer_class}</span>
              {(b.buyer_class === 'FII' || b.buyer_class === 'DII') && <GradeChip grade={b.grade} cls={b.buyer_class} />}
            </span>
            <span className="num shrink-0 text-fg-2">₹{fmtNum(b.value_cr, 1)} Cr</span>
          </div>
        ))
      )}
    </div>
  );
}

export function StockDrawer({ symbol, onClose, onHouse }: { symbol: string | null; onClose: () => void; onHouse: (h: string) => void }) {
  const q = useDeals<StockDetail>(`deals/tab/stock/${encodeURIComponent(symbol ?? '')}`, {}, { enabled: !!symbol });
  const d = q.data?.rows[0];
  const x = d?.deal ?? null;
  return (
    <Drawer open={!!symbol} onClose={onClose} title={symbol ? `${symbol}${x ? ` · ${x.name}` : ''}` : 'Stock'} actions={symbol ? <TvCopy list={{ title: `Deals ${symbol}`, symbols: [symbol] }} /> : undefined}>
      {q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : !d || q.isFetching && d.symbol !== symbol ? (
        <div className="p-3">
          <Skeleton height={200} />
        </div>
      ) : (
        <div className="space-y-3 p-3">
          {x ? (
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <VerdictChip verdict={x.verdict} title={x.verdict_title} />
                <span className="text-2xs text-fg-3">
                  {x.event_label} on {fmtDate(x.deal_date)} · {x.industry ?? ''}
                </span>
              </div>
              <div className="text-xs text-fg-2">{x.why}</div>
            </div>
          ) : (
            <EmptyState compact title="No deal in the last 10 deal sessions" detail="The chart shows any older deal candles in this window." />
          )}
          <DealCandles candles={d.candles} markers={d.markers} lines={d.price_lines} />
          <CandleLegend />
          {x && (
            <>
              <div className="grid grid-cols-3 gap-1.5">
                <KV k="Deal price">{x.deal_price == null ? '–' : `₹${fmtNum(x.deal_price, 2)}`}</KV>
                <KV k="Now">
                  ₹{fmtNum(x.close, 2)} <Signed value={x.vs_deal_pct} pct />
                </KV>
                <KV k="Status">
                  <StatusChip status={x.status} days={x.sessions_since} />
                </KV>
                <KV k="Chart">
                  {x.strong_chart ? <span className="text-up">Strong</span> : 'Weak'} · RS {x.rs ?? '–'}
                </KV>
                <KV k="From 52W high">
                  <Signed value={x.from_high_pct} pct />
                </KV>
                <KV k="Last month">
                  <Signed value={x.month_pct} pct />
                </KV>
              </div>
              <Chips chips={x.chips} />
              <Parties title="Bought" list={x.buyers} onHouse={onHouse} />
              <Parties title="Sold" list={x.sellers} onHouse={onHouse} />
              {!!x.earlier?.length && (
                <div className="text-2xs text-fg-3">
                  Earlier in the window:{' '}
                  {x.earlier.map((e) => `${fmtDate(e.deal_date)} ${e.side ?? ''} ₹${fmtNum(Math.abs(e.net_cr), 1)} Cr`).join(' · ')}
                </div>
              )}
              <DoLine>
                <b className="text-fg">What to do:</b> {x.next_action}
              </DoLine>
            </>
          )}
          <NotesLine notes={q.data?.meta.notes} />
        </div>
      )}
    </Drawer>
  );
}

export function HouseDrawer({ house, onClose, onStock }: { house: string | null; onClose: () => void; onStock: (s: string) => void }) {
  const q = useDeals<HousePosition, HouseContext>(`deals/tab/house/${encodeURIComponent(house ?? '')}`, {}, { enabled: !!house });
  const [followed, setFollowed] = useState<string[]>(() => readFollowed());
  const h = q.data?.meta.context?.house;
  const rows = q.data?.rows ?? [];
  const isF = !!house && followed.includes(house);
  return (
    <Drawer
      open={!!house}
      onClose={onClose}
      title={h?.name ?? house ?? 'House'}
      actions={
        house ? (
          <button type="button" className="rounded border border-line px-2 py-0.5 text-xs text-fg-2 hover:bg-surface-3" onClick={() => setFollowed(toggleFollowed(house))}>
            {isF ? 'Following' : 'Follow'}
          </button>
        ) : undefined
      }
    >
      {q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : !h ? (
        <div className="p-3">
          <Skeleton height={160} />
        </div>
      ) : (
        <div className="space-y-3 p-3">
          <div className="text-2xs text-fg-3">
            {h.buyer_class}
            {h.bought_cr != null && ` · bought ₹${fmtNum(h.bought_cr, 1)} Cr in the last 10 deal sessions`}
          </div>
          <div className="grid grid-cols-3 gap-1.5">
            <KV k="Grade">
              <GradeChip grade={h.grade} cls={h.buyer_class} />
            </KV>
            <KV k="Finished trades">{h.record_n || '–'}</KV>
            <KV k="Avg vs market">
              <Signed value={h.record_avg_pct} pct />
            </KV>
          </div>
          {h.spread.length > 0 && (
            <div className="text-2xs text-fg-3">
              Spread: {spreadSummary(h.spread).groups} groups ·{' '}
              {h.spread
                .slice(0, 5)
                .map((g) => `${g.industry} ${g.share_pct}%`)
                .join(' · ')}
            </div>
          )}
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-2xs font-semibold uppercase tracking-wide text-fg-3">Buys, last 20 deal sessions · vs market since entry</span>
              <TvCopy list={{ title: `${h.name} buys`, symbols: rows.map((r) => r.symbol) }} />
            </div>
            {rows.length === 0 ? (
              <div className="text-2xs text-fg-3">No buys in the window.</div>
            ) : (
              <table className="w-full text-table">
                <thead>
                  <tr className="text-left text-2xs text-fg-3">
                    <th className="py-0.5 font-medium">Stock</th>
                    <th className="text-right font-medium">₹ Cr</th>
                    <th className="text-right font-medium">Since entry</th>
                    <th className="text-right font-medium">vs mkt</th>
                    <th className="pl-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={`${r.symbol}-${r.deal_date}`} className="border-t border-line/60">
                      <td className="py-1">
                        <button type="button" className="font-mono text-fg hover:underline" onClick={() => onStock(r.symbol)}>
                          {r.symbol}
                        </button>
                        <DealIcon symbol={r.symbol} className="ml-1 align-middle" />
                        <span className="ml-1 text-2xs text-fg-3">{fmtDate(r.deal_date)}</span>
                      </td>
                      <td className="num text-right">{fmtNum(r.bought_cr, 1)}</td>
                      <td className="text-right">{r.entry_date ? <Signed value={r.since_entry_pct} pct /> : <span className="text-2xs text-fg-3">entry next open</span>}</td>
                      <td className="text-right">
                        <Signed value={r.vs_market_pct} pct />
                      </td>
                      <td className="pl-2">{r.verdict_title ? <span className="text-2xs text-fg-2">{r.verdict_title}</span> : <StatusChip status={r.status} />}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          {q.data?.meta.context?.advice && <DoLine>{q.data.meta.context.advice}</DoLine>}
          <NotesLine notes={q.data?.meta.notes} />
        </div>
      )}
    </Drawer>
  );
}
