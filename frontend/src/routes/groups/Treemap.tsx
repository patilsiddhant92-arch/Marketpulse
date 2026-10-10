/**
 * Taxonomy heatmap: Broad Sector blocks, each tiled by its groups at the chosen
 * level (Sector › Broad Industry › Industry), sized by 20-session average
 * turnover and coloured by Health or 21-day equal-weight return. Lightweight
 * custom SVG (squarified layout in groupsModel.ts); click a tile to drill in.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useApiQuery } from '../../api/query';
import type { GroupTreeRow } from '../../api/types';
import { cn } from '../../lib/cn';
import { fmtCr, fmtNum, fmtSignedPct } from '../../lib/fmt';
import { EmptyState } from '../../ui/EmptyState';
import { ErrorState } from '../../ui/ErrorState';
import { Skeleton } from '../../ui/Skeleton';
import { squarify, type Floor, type Level } from './groupsModel';
import { Segmented } from '../../ui/Segmented';
import { SourceNote } from '../../ui/SourceNote';

export type MapColour = 'health' | 'ret21';
type LeafLevel = Exclude<Level, 'broad_sector'>;

const EMPTY: GroupTreeRow[] = [];
const HEADER = 15;

/** Tone + opacity for a tile. Health centres on the Mixed zone (45-65); returns on 0. */
export function tileTone(row: Pick<GroupTreeRow, 'health' | 'return_ew_21d'>, by: MapColour): { tone: 'up' | 'down' | 'warn' | 'none'; alpha: number } {
  if (by === 'health') {
    const h = row.health;
    if (typeof h !== 'number') return { tone: 'none', alpha: 0 };
    if (h >= 65) return { tone: 'up', alpha: Math.min(0.9, 0.35 + (h - 65) / 50) };
    if (h < 45) return { tone: 'down', alpha: Math.min(0.9, 0.35 + (45 - h) / 50) };
    return { tone: 'warn', alpha: 0.3 };
  }
  const r = row.return_ew_21d;
  if (typeof r !== 'number') return { tone: 'none', alpha: 0 };
  const a = Math.min(0.9, 0.18 + Math.abs(r) / 12);
  return { tone: r >= 0 ? 'up' : 'down', alpha: a };
}

const FILL = { up: 'fill-up', down: 'fill-down', warn: 'fill-warn', none: 'fill-surface-3' } as const;

interface Block {
  sector: GroupTreeRow;
  leaves: GroupTreeRow[];
  size: number;
}

/** Leaves grouped under their Broad Sector (walking parent_id up the taxonomy). */
export function blocksFor(rows: readonly GroupTreeRow[], leaf: LeafLevel): Block[] {
  const byId = new Map(rows.map((r) => [r.id, r]));
  const top = (r: GroupTreeRow): GroupTreeRow | null => {
    let cur: GroupTreeRow | undefined = r;
    for (let i = 0; i < 4 && cur; i += 1) {
      if (cur.level === 'broad_sector') return cur;
      cur = cur.parent_id ? byId.get(cur.parent_id) : undefined;
    }
    return null;
  };
  const blocks = new Map<string, Block>();
  for (const r of rows) {
    if (r.level !== leaf || !(typeof r.turnover_20d_cr === 'number' && r.turnover_20d_cr > 0)) continue;
    const s = top(r);
    if (!s) continue;
    const b = blocks.get(s.id) ?? { sector: s, leaves: [], size: 0 };
    b.leaves.push(r);
    b.size += r.turnover_20d_cr;
    blocks.set(s.id, b);
  }
  return [...blocks.values()];
}

export function GroupsTreemap({ floor, onDrill }: { floor: Floor; onDrill: (id: string) => void }) {
  const q = useApiQuery('groups/treemap', { query: { floor, limit: 5000 } });
  const [leaf, setLeaf] = useState<LeafLevel>('broad_industry');
  const [by, setBy] = useState<MapColour>('health');
  const [hover, setHover] = useState<GroupTreeRow | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 900, h: 520 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) setSize({ w: Math.round(r.width), h: Math.round(r.height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const rows = q.data?.rows ?? EMPTY;
  const layout = useMemo(() => {
    const blocks = blocksFor(rows, leaf);
    return squarify(blocks, (b) => b.size, 0, 0, size.w, size.h).map((t) => ({
      ...t,
      tiles: squarify(t.item.leaves, (l) => l.turnover_20d_cr ?? 0, t.x + 1, t.y + HEADER, Math.max(0, t.w - 2), Math.max(0, t.h - HEADER - 1)),
    }));
  }, [rows, leaf, size]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-8 shrink-0 items-center gap-3 border-b border-line bg-surface px-3 text-2xs text-fg-3">
        <span className="font-semibold uppercase tracking-wide text-fg-2">Taxonomy map</span>
        <Segmented
          size="xs"
          label="Tile level"
          value={leaf}
          onChange={setLeaf}
          options={[
            { value: 'sector', label: 'Sector' },
            { value: 'broad_industry', label: 'Broad Ind.' },
            { value: 'industry', label: 'Industry' },
          ]}
        />
        <Segmented
          size="xs"
          label="Colour by"
          value={by}
          onChange={setBy}
          options={[
            { value: 'health', label: 'Health', title: 'Green ≥ 65 Healthy · amber 45–65 Mixed · red < 45 Weak' },
            { value: 'ret21', label: '21d return', title: 'Equal-weight 21-session return' },
          ]}
        />
        <span>Blocks = Broad Sector · tile size = avg daily turnover (20 sessions)</span>
        <span className="ml-auto">
          <SourceNote meta={q.data?.meta} />
        </span>
      </div>
      <div ref={ref} className="relative min-h-0 flex-1 overflow-hidden bg-bg">
        {q.error ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : q.isLoading ? (
          <Skeleton className="h-full w-full" />
        ) : layout.length === 0 ? (
          <EmptyState title="No map data" detail={q.data?.meta.reason ?? 'No groups with turnover at this floor.'} />
        ) : (
          <svg width={size.w} height={size.h} role="img" aria-label={`Taxonomy heatmap coloured by ${by === 'health' ? 'Health' : '21-day return'}`}>
            {layout.map((b) => (
              <g key={b.item.sector.id}>
                <rect x={b.x} y={b.y} width={Math.max(0, b.w)} height={Math.max(0, b.h)} className="fill-surface stroke-line-strong" strokeWidth={1} />
                {b.w > 40 && (
                  <text
                    x={b.x + 4}
                    y={b.y + 11}
                    className="cursor-pointer fill-fg-2 text-2xs font-semibold uppercase"
                    onClick={() => onDrill(b.item.sector.id)}
                  >
                    {b.item.sector.group_name.length * 6 > b.w - 8 ? `${b.item.sector.group_name.slice(0, Math.max(3, Math.floor((b.w - 14) / 6)))}…` : b.item.sector.group_name}
                  </text>
                )}
                {b.tiles.map((t) => {
                  const tone = tileTone(t.item, by);
                  const val = by === 'health' ? fmtNum(t.item.health ?? null, 0) : fmtSignedPct(t.item.return_ew_21d ?? null, 1);
                  const fits = t.w > 46 && t.h > 22;
                  const maxChars = Math.max(3, Math.floor((t.w - 6) / 5.6));
                  return (
                    <g
                      key={t.item.id}
                      className="cursor-pointer"
                      onClick={() => onDrill(t.item.id)}
                      onMouseEnter={() => setHover(t.item)}
                      onMouseLeave={() => setHover((h) => (h?.id === t.item.id ? null : h))}
                    >
                      <rect x={t.x} y={t.y} width={Math.max(0, t.w)} height={Math.max(0, t.h)} className="fill-surface-2" />
                      <rect
                        x={t.x}
                        y={t.y}
                        width={Math.max(0, t.w)}
                        height={Math.max(0, t.h)}
                        className={cn(FILL[tone.tone], 'stroke-bg', hover?.id === t.item.id && 'stroke-fg')}
                        fillOpacity={tone.alpha}
                        strokeWidth={hover?.id === t.item.id ? 1.5 : 1}
                      />
                      {fits && (
                        <>
                          <text x={t.x + 3} y={t.y + 11} className="pointer-events-none fill-fg text-2xs">
                            {t.item.group_name.length > maxChars ? `${t.item.group_name.slice(0, maxChars - 1)}…` : t.item.group_name}
                          </text>
                          <text x={t.x + 3} y={t.y + 21} className="num pointer-events-none fill-fg-2 text-2xs">
                            {val}
                          </text>
                        </>
                      )}
                    </g>
                  );
                })}
              </g>
            ))}
          </svg>
        )}
        {hover && (
          <div className="pointer-events-none absolute right-2 top-2 z-10 w-60 rounded border border-line-strong bg-surface-3 p-2 text-2xs shadow-xl">
            <div className="mb-1 text-xs font-semibold text-fg">{hover.group_name}</div>
            <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-fg-2">
              <span>Health</span>
              <span className="num text-right text-fg">{fmtNum(hover.health ?? null, 1)}</span>
              <span>21d return</span>
              <span className="num text-right text-fg">{fmtSignedPct(hover.return_ew_21d ?? null, 1)}</span>
              <span>RRG</span>
              <span className="text-right text-fg">{hover.rrg_quadrant ?? '—'}</span>
              <span>Own trend</span>
              <span className="text-right text-fg">{hover.abs_trend ?? '—'}</span>
              <span>Turnover 20d</span>
              <span className="num text-right text-fg">{fmtCr(hover.turnover_20d_cr ?? null, 0)}</span>
              <span>Members</span>
              <span className="num text-right text-fg">{hover.stocks ?? '—'}</span>
            </div>
            {hover.quadrant_note && <div className="mt-1 font-medium text-warn">{hover.quadrant_note}</div>}
          </div>
        )}
      </div>
    </div>
  );
}
