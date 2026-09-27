/**
 * Deals "at a glance" band for Today: net flow, accumulate / distribute counts,
 * biggest net buys and the top house. Uses deals/session (already loaded) and
 * deals/houses with the Houses view's own default query (shared cache).
 */
import { useMemo } from 'react';
import { useApiQuery } from '../../api/query';
import type { DealSessionRow } from '../../api/types';
import { fmtCr, fmtDateWithDay, fmtInt, fmtSigned } from '../../lib/fmt';
import { sumOf } from '../../lib/glance';
import { useShell } from '../../shell/ShellContext';
import { GlanceBand } from '../../ui/GlanceBand';
import { KpiList, KpiTile } from '../../ui/KpiTile';

export interface DealsGlanceProps {
  rows: readonly DealSessionRow[];
  session: string | null | undefined;
  eventCounts: Record<string, number> | undefined;
  loading: boolean;
  onHouse: (house: string) => void;
}

const signedCr = (v: number | null | undefined) => (v == null ? '—' : `${v > 0 ? '+' : ''}${fmtCr(v)}`);

export function DealsGlance({ rows, session, eventCounts, loading, onHouse }: DealsGlanceProps) {
  const shell = useShell();
  const houses = useApiQuery('deals/houses', { query: { session_only: true, limit: 5000 } });
  const net = useMemo(() => sumOf(rows, (r) => r.net_ex_prop_cr), [rows]);
  const buy = useMemo(() => sumOf(rows, (r) => r.buy_cr), [rows]);
  const sell = useMemo(() => sumOf(rows, (r) => r.sell_cr), [rows]);
  const topBuys = useMemo(
    () =>
      rows
        .filter((r) => r.symbol && (r.net_ex_prop_cr ?? 0) > 0 && r.event_type !== 'churn')
        .sort((a, b) => (b.net_ex_prop_cr ?? 0) - (a.net_ex_prop_cr ?? 0))
        .slice(0, 3),
    [rows],
  );
  const topHouse = useMemo(() => {
    const list = (houses.data?.rows ?? []).filter((h) => !h.churner && typeof h.session_net_cr === 'number');
    return list.sort((a, b) => Math.abs(b.session_net_cr ?? 0) - Math.abs(a.session_net_cr ?? 0))[0] ?? null;
  }, [houses.data]);
  const ec = eventCounts ?? {};
  const n = (k: string) => ec[k] ?? 0;

  return (
    <GlanceBand label="Deals at a glance">
      <KpiTile
        hero
        tone={net == null ? 'neutral' : net >= 0 ? 'up' : 'down'}
        label={<>Net flow ex-PROP{session ? ` · ${fmtDateWithDay(session)}` : ''}</>}
        value={net == null ? null : <span className="num">{signedCr(net)}</span>}
        caption={buy != null || sell != null ? `buy ${fmtCr(buy)} · sell ${fmtCr(sell)}` : undefined}
        hint="Sum of net bulk + block deal value across every stock of the session, PROP desks excluded (₹ Cr)"
        loading={loading}
        className="!min-w-[240px] !flex-[1.3]"
      />
      <KpiTile
        label="Accumulate"
        value={loading ? null : n('accumulate')}
        format="int"
        tone="up"
        caption={`${fmtInt(n('fresh'))} fresh buyers`}
        hint="Net buying again within 10 sessions (fresh = first net buying in 10 sessions)"
        loading={loading}
      />
      <KpiTile
        label="Distribute"
        value={loading ? null : n('distribute')}
        format="int"
        tone="down"
        caption={`${fmtInt(n('transfer_interse') + n('placement'))} strategic · ${fmtInt(n('churn'))} churn`}
        hint="Net selling, PROP excluded"
        loading={loading}
      />
      <KpiList
        label="Biggest net buys · ₹ Cr"
        loading={loading}
        empty="No net buying this session"
        className="!min-w-[220px] !flex-[1.4]"
        items={topBuys.map((r) => ({
          id: r.symbol as string,
          label: <span className="font-mono">{r.symbol}</span>,
          value: fmtSigned(r.net_ex_prop_cr, 1),
          tone: 'up' as const,
          onClick: () => r.symbol && shell.openSymbol(r.symbol),
          title: `${r.security_name ?? r.symbol} · ${r.industry ?? ''} — open Stock 360`,
        }))}
      />
      <KpiTile
        label="Top house this session"
        value={
          topHouse ? (
            <span className="block max-w-full truncate text-title text-fg" title={topHouse.house}>
              {topHouse.house}
            </span>
          ) : houses.error ? (
            <span className="text-sm text-fg-3">unavailable</span>
          ) : null
        }
        caption={
          topHouse
            ? `net ${signedCr(topHouse.session_net_cr)} · ${topHouse.session_symbols?.length ?? 0} stocks`
            : 'by |session net|, churners excluded'
        }
        onClick={topHouse ? () => onHouse(topHouse.house) : undefined}
        loading={houses.isLoading}
        className="!min-w-[200px] !flex-[1.3]"
      />
    </GlanceBand>
  );
}
