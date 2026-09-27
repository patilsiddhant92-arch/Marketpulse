/** Groups "at a glance" band — market line, health split, quadrant, top 3 by Health (board data only). */
import { useMemo } from 'react';
import type { GroupRow } from '../../api/types';
import { fmtDate, fmtInt, fmtNum } from '../../lib/fmt';
import { GlanceBand } from '../../ui/GlanceBand';
import { KpiList, KpiTile } from '../../ui/KpiTile';
import type { MarketContext } from './groupsModel';

export interface GroupsGlanceProps {
  rows: readonly GroupRow[];
  market: MarketContext | undefined;
  contextLine: string | null;
  quadrants: Record<string, number>;
  levelLabel: string;
  floorLabel: string | undefined;
  asOf: string | null | undefined;
  loading: boolean;
  onDrill: (id: string) => void;
}

export function GroupsGlance({ rows, market, contextLine, quadrants, levelLabel, floorLabel, asOf, loading, onDrill }: GroupsGlanceProps) {
  const top3 = useMemo(
    () =>
      [...rows]
        .filter((r) => typeof r.health === 'number')
        .sort((a, b) => (a.health_rank ?? Infinity) - (b.health_rank ?? Infinity) || (b.health ?? 0) - (a.health ?? 0))
        .slice(0, 3),
    [rows],
  );
  const zones = market?.health_zones;
  const ret = market?.midsml400_ret_21d ?? null;
  const lead = quadrants.Leading ?? market?.quadrants?.Leading ?? null;
  return (
    <GlanceBand
      label="Groups at a glance"
      aside={
        <>
          <span>
            <span className="num text-fg-2">{fmtInt(rows.length)}</span> {levelLabel.toLowerCase()} groups
          </span>
          {floorLabel && (
            <span className="max-w-[180px] truncate" title={floorLabel}>
              floor {floorLabel}
            </span>
          )}
          {asOf && <span>as of {fmtDate(asOf)}</span>}
        </>
      }
    >
      <KpiTile
        hero
        tone={ret == null ? 'neutral' : ret >= 0 ? 'up' : 'down'}
        label={<>Market{market?.verdict ? ` ${market.verdict}` : ''} · MidSml400 21d</>}
        value={ret}
        format="signedPct"
        digits={1}
        caption={
          contextLine ? (
            <span data-testid="groups-context" title={contextLine}>
              {market?.groups != null && market?.falling_21d != null
                ? `${market.falling_21d} of ${market.groups} groups down over 21 sessions`
                : contextLine}
            </span>
          ) : undefined
        }
        loading={loading}
        className="!min-w-[240px] !flex-[1.3]"
      />
      <KpiTile
        label="Healthy groups"
        value={zones ? (zones.Healthy ?? 0) : null}
        format="int"
        tone="up"
        caption={market?.health_median != null ? `median health ${fmtNum(market.health_median, 0)}` : 'groups with ≥ 3 members'}
        hint="Groups (≥ 3 members) in the Healthy Health zone"
        loading={loading}
      />
      <KpiTile
        label="Weak groups"
        value={zones ? (zones.Weak ?? 0) : null}
        format="int"
        tone="down"
        caption={zones ? `${fmtInt(zones.Mixed ?? 0)} mixed` : undefined}
        hint="Groups (≥ 3 members) in the Weak Health zone"
        loading={loading}
      />
      <KpiTile
        label="Leading vs peers"
        value={lead}
        format="int"
        tone="neutral"
        caption={market?.leading_falling != null ? `${market.leading_falling} falling in absolute terms` : 'RRG quadrant'}
        hint="RRG 'Leading' = strongest relative strength and momentum vs the other groups"
        loading={loading}
      />
      <KpiList
        label="Top 3 by Health"
        loading={loading}
        empty="Health not built for this date"
        className="!min-w-[260px] !flex-[1.6]"
        items={top3.map((g) => ({
          id: g.id,
          label: g.group_name,
          value: fmtNum(g.health, 0),
          tone: 'up' as const,
          onClick: () => onDrill(g.id),
          title: `${g.group_name} · Health ${fmtNum(g.health, 0)} · ${g.stocks ?? '—'} stocks — open`,
        }))}
      />
    </GlanceBand>
  );
}
