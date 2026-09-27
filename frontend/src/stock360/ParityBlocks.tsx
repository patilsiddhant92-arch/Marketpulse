/**
 * Blocks restored from the old Inspector sidecar (parity audit 2026-09-27):
 *   - ProfileBlock: Minervini 8-point checklist, institutional footprint (turnover / delivery /
 *     order ticket vs 20-day baselines + tags) and the 5-session activity trail.
 *   - PeersBlock: industry peer leaderboard with rank, "stronger and near its 10 EMA" names,
 *     copy to TradingView (same "NSE:A,NSE:B" text the old Peers tab copied) and Open in Charts.
 * Values come from GET /api/v2/stock/{sym}/profile and /peers; NULL renders "—".
 */
import { Check, CheckCircle2, CircleDashed, ClipboardCopy, LayoutGrid, XCircle } from 'lucide-react';
import { useState } from 'react';
import { useApiQuery } from '../api/query';
import { copyText } from '../lib/clipboard';
import { cn } from '../lib/cn';
import { fmtCr, fmtDateShort, fmtNum, fmtPct, fmtSignedPct } from '../lib/fmt';
import { formatTradingViewList } from '../lib/tradingview';
import { useShell } from '../shell/ShellContext';
import { Chip } from '../ui/Chip';
import { ErrorState } from '../ui/ErrorState';
import { Panel } from '../ui/Panel';
import { Skeleton } from '../ui/Skeleton';

const signTone = (v: number | null | undefined) => (v == null ? 'text-fg-3' : v >= 0 ? 'text-up' : 'text-down');

export function ProfileBlock({ symbol, className }: { symbol: string; className?: string }) {
  const q = useApiQuery('stock/{sym}/profile', { params: { sym: symbol } });
  const r = q.data?.rows[0];
  return (
    <Panel
      title="Trend template & footprint"
      meta={r ? `${r.trend_template_pass_n ?? '—'}/8 · ${fmtDateShort(r.trade_date)}` : undefined}
      className={className}
      bodyClassName="space-y-2 p-3"
    >
      {q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} compact />
      ) : q.isLoading ? (
        <Skeleton height={96} />
      ) : !r ? (
        <p className="text-2xs text-fg-3">{q.data?.meta.reason ?? 'No profile for this date.'}</p>
      ) : (
        <>
          <ul className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-2xs" aria-label="Trend template criteria">
            {r.criteria.map((c) => (
              <li key={c.key} className="flex items-center gap-1" title={c.passed == null ? 'Input missing or window spans a price gap' : undefined}>
                {c.passed == null ? (
                  <CircleDashed className="h-3 w-3 shrink-0 text-fg-3" aria-label="no data" />
                ) : c.passed ? (
                  <CheckCircle2 className="h-3 w-3 shrink-0 text-up" aria-label="pass" />
                ) : (
                  <XCircle className="h-3 w-3 shrink-0 text-down" aria-label="fail" />
                )}
                <span className={c.passed ? 'text-fg-2' : 'text-fg-3'}>{c.label}</span>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-1">
            {r.price_up_delivery_up && <Chip tone="info" title="Price up and delivery quantity up vs yesterday">Acc vol</Chip>}
            {r.delivery_spike && <Chip tone="positive" title="Delivery quantity spike vs its 20-day average">Deliv surge</Chip>}
            {r.whale_ticket && <Chip tone="violet" title="Average trade size ≥ 1.25× its 20-day average">Whale ticket</Chip>}
            {r.nr7 && <Chip tone="warn" title="Narrowest daily range of the last 7 sessions">NR7</Chip>}
          </div>
          <dl className="grid grid-cols-3 gap-2 text-2xs">
            <div>
              <dt className="text-fg-3" title="Traded value today vs its 20-day average">Turnover</dt>
              <dd className="num text-fg">{fmtCr(r.turnover_cr, 1)}</dd>
              <dd className={cn('num', signTone(r.turnover_surge_pct))}>{fmtSignedPct(r.turnover_surge_pct, 0)} vs 20d</dd>
            </div>
            <div>
              <dt className="text-fg-3">Delivery</dt>
              <dd className="num text-fg">{fmtPct(r.delivery_pct)}</dd>
              <dd className="num text-fg-3">20d {fmtPct(r.avg_delivery_pct_20d)}</dd>
            </div>
            <div>
              <dt className="text-fg-3" title="Average trade size ÷ its 20-day average">Order ticket</dt>
              <dd className="num text-fg">{r.ticket_ratio == null ? '—' : `${fmtNum(r.ticket_ratio)}×`}</dd>
            </div>
          </dl>
          {r.trail.length > 0 && (
            <div>
              <div className="mb-0.5 text-2xs text-fg-3">Last {r.trail.length} sessions (oldest → today)</div>
              <div className="grid grid-cols-5 gap-1 text-center text-2xs">
                {r.trail.map((t, i) => (
                  <div
                    key={t.trade_date ?? i}
                    className={cn('rounded border px-1 py-0.5', i === r.trail.length - 1 ? 'border-accent/50 bg-accent/5' : 'border-line')}
                    title={fmtDateShort(t.trade_date)}
                  >
                    <div className={cn('num font-semibold', signTone(t.change_pct))}>{fmtSignedPct(t.change_pct, 1)}</div>
                    <div className="num text-fg-2">{t.rvol == null ? '—' : `${fmtNum(t.rvol, 1)}×`}</div>
                    <div className="num text-fg-3">{t.delivery_pct == null ? '—' : `${fmtNum(t.delivery_pct, 0)}% dl`}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </Panel>
  );
}

const PEERS_SHOW = 12;

export function PeersBlock({ symbol, className }: { symbol: string; className?: string }) {
  const shell = useShell();
  const q = useApiQuery('stock/{sym}/peers', { params: { sym: symbol }, query: { limit: 5000 } });
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const rows = q.data?.rows ?? [];
  const ctx = (q.data?.meta.context ?? {}) as { industry?: string; target_rank?: number | null; ranked?: number };
  const syms = rows.map((r) => r.symbol).filter((s): s is string => !!s);
  const better = rows.filter((r) => r.stronger_near_10ema);
  const list = open ? rows : rows.slice(0, PEERS_SHOW);
  const copy = async () => {
    const { text, count } = formatTradingViewList([{ symbols: syms }]);
    const ok = count > 0 && (await copyText(text));
    setMsg(ok ? `Copied ${count}` : 'Copy failed');
    window.setTimeout(() => setMsg(null), 2500);
  };
  return (
    <Panel
      title="Industry peers"
      meta={q.data && ctx.industry ? `#${ctx.target_rank ?? '—'} of ${ctx.ranked ?? rows.length} in ${ctx.industry}` : undefined}
      actions={
        syms.length > 0 ? (
          <span className="inline-flex items-center gap-1 text-2xs">
            {msg && (
              <span role="status" className="inline-flex items-center gap-0.5 text-up">
                <Check className="h-3 w-3" /> {msg}
              </span>
            )}
            <button
              type="button"
              onClick={() => void copy()}
              title="Copy every peer as a TradingView watchlist (NSE:A,NSE:B,…)"
              className="inline-flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-fg-2 hover:bg-surface-3"
            >
              <ClipboardCopy className="h-3 w-3" /> TV ({syms.length})
            </button>
            <button
              type="button"
              onClick={() => shell.openCharts([symbol, ...syms.filter((s) => s !== symbol)])}
              title="Open the stock and its peers in Charts"
              className="inline-flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-fg-2 hover:bg-surface-3"
            >
              <LayoutGrid className="h-3 w-3" /> Charts
            </button>
          </span>
        ) : undefined
      }
      className={className}
    >
      {q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} compact />
      ) : q.isLoading ? (
        <div className="p-3">
          <Skeleton height={64} />
        </div>
      ) : rows.length === 0 ? (
        <p className="px-3 py-2 text-2xs text-fg-3">{q.data?.meta.reason ?? 'No industry peers.'}</p>
      ) : (
        <>
          {better.length > 0 && (
            <div className="flex flex-wrap items-center gap-1 border-b border-line px-3 py-1.5 text-2xs">
              <span className="text-fg-3" title="Higher strength rank than this stock and within ±3% of their 10 EMA">
                Stronger, near 10 EMA:
              </span>
              {better.slice(0, 6).map((b) => (
                <button
                  key={b.symbol}
                  type="button"
                  onClick={() => b.symbol && shell.openSymbol(b.symbol)}
                  className="rounded border border-accent/40 px-1 font-mono text-accent hover:bg-accent/10"
                  title={`${b.symbol} · rank ${fmtNum(b.rs_percentile, 0)} · ${fmtSignedPct(b.away_10ema_pct, 1)} vs 10 EMA`}
                >
                  {b.symbol}
                </button>
              ))}
            </div>
          )}
          <table className="w-full text-table">
            <thead className="text-2xs text-fg-3">
              <tr className="border-b border-line">
                <th className="px-2 py-1 text-right font-medium">#</th>
                <th className="px-1 py-1 text-left font-medium">Symbol</th>
                <th className="px-1 py-1 text-right font-medium" title="Strength rank (0–100)">RS</th>
                <th className="px-1 py-1 text-right font-medium">Close</th>
                <th className="px-1 py-1 text-right font-medium">1D</th>
                <th className="px-2 py-1 text-right font-medium" title="Close vs 10 EMA">10E</th>
              </tr>
            </thead>
            <tbody>
              {list.map((p) => (
                <tr
                  key={p.symbol}
                  onClick={() => p.symbol && p.symbol !== symbol && shell.openSymbol(p.symbol)}
                  className={cn('cursor-pointer border-b border-line/60 last:border-0 hover:bg-surface-3', p.is_target && 'bg-accent/10 font-semibold')}
                >
                  <td className="num px-2 py-0.5 text-right text-fg-3">{p.rank ?? '—'}</td>
                  <td className="px-1 py-0.5 font-mono text-fg">{p.symbol}</td>
                  <td className="num px-1 py-0.5 text-right text-fg-2">{fmtNum(p.rs_percentile, 0)}</td>
                  <td className="num px-1 py-0.5 text-right text-fg-2">{fmtNum(p.close)}</td>
                  <td className={cn('num px-1 py-0.5 text-right', signTone(p.change_1d_pct))}>{fmtSignedPct(p.change_1d_pct, 1)}</td>
                  <td className={cn('num px-2 py-0.5 text-right', signTone(p.away_10ema_pct))}>{fmtSignedPct(p.away_10ema_pct, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > PEERS_SHOW && (
            <button type="button" onClick={() => setOpen((o) => !o)} className="px-3 py-1.5 text-left text-2xs text-info hover:underline">
              {open ? 'Show fewer' : `Showing ${list.length} of ${rows.length} · show all`}
            </button>
          )}
        </>
      )}
    </Panel>
  );
}
