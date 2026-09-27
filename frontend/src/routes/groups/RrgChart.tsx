/**
 * Relative Rotation Graph: RS-Ratio (x) vs RS-Momentum (y), both centred on
 * 100, with weekly tails (every 5th session). Groups rotate clockwise:
 * Improving (top-left) → Leading (top-right) → Weakening (bottom-right) →
 * Lagging (bottom-left). Click a head to drill into the group.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import type { RrgRow } from '../../api/types';
import { cn } from '../../lib/cn';
import { fmtDateShort, fmtNum } from '../../lib/fmt';
import { isQuadrant, QUADRANT_TOKEN, type Quadrant } from './kit';
import { rrgDomain } from './groupsModel';

const STROKE: Record<string, string> = { up: 'stroke-up', info: 'stroke-info', warn: 'stroke-warn', down: 'stroke-down' };
const FILL: Record<string, string> = { up: 'fill-up', info: 'fill-info', warn: 'fill-warn', down: 'fill-down' };

function tokenOf(q: string | null | undefined): string {
  return isQuadrant(q) ? QUADRANT_TOKEN[q] : 'info';
}

export interface RrgChartProps {
  rows: readonly RrgRow[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  /** Label every head when there are at most this many (else only hovered/selected/top 8). */
  labelAll?: number;
  className?: string;
}

export function RrgChart({ rows, selectedId, onSelect, labelAll = 24, className }: RrgChartProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 400, h: 320 });
  const [hover, setHover] = useState<string | null>(null);

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

  const dom = useMemo(() => rrgDomain(rows), [rows]);
  const m = { l: 34, r: 10, t: 10, b: 24 };
  const iw = Math.max(10, size.w - m.l - m.r);
  const ih = Math.max(10, size.h - m.t - m.b);
  const sx = (v: number) => m.l + ((v - dom.x[0]) / (dom.x[1] - dom.x[0])) * iw;
  const sy = (v: number) => m.t + (1 - (v - dom.y[0]) / (dom.y[1] - dom.y[0])) * ih;
  const cx = sx(100);
  const cy = sy(100);
  const topIds = useMemo(
    () => new Set([...rows].sort((a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9)).slice(0, 12).map((r) => r.id)),
    [rows],
  );
  const hovered = rows.find((r) => r.id === hover) ?? null;
  // Greedy label placement: best-ranked first; skip a label that would overlap one already placed.
  const labelled = new Set<string>();
  {
    const boxes: { x: number; y: number; w: number }[] = [];
    for (const r of [...rows].sort((a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9))) {
      if (typeof r.rs_ratio !== 'number' || typeof r.rs_momentum !== 'number') continue;
      if (rows.length > labelAll && !topIds.has(r.id)) continue;
      const x = sx(r.rs_ratio) + 7;
      const y = sy(r.rs_momentum);
      const w = Math.min(22, r.group_name.length) * 6;
      if (boxes.some((b) => Math.abs(b.y - y) < 12 && x < b.x + b.w && b.x < x + w)) continue;
      boxes.push({ x, y, w });
      labelled.add(r.id);
    }
  }
  const ticks = (d: [number, number]) => {
    const span = d[1] - d[0];
    const step = span > 12 ? 5 : span > 6 ? 2 : span > 3 ? 1 : 0.5;
    const out: number[] = [];
    for (let v = Math.ceil(d[0] / step) * step; v <= d[1]; v += step) out.push(Number(v.toFixed(2)));
    return out;
  };

  const quad = (q: Quadrant, x: number, y: number, w: number, h: number) => (
    <rect x={x} y={y} width={Math.max(0, w)} height={Math.max(0, h)} className={cn(FILL[QUADRANT_TOKEN[q]], 'opacity-[0.07]')} />
  );

  return (
    <div ref={ref} className={cn('relative h-full min-h-[220px] w-full select-none', className)}>
      <svg width={size.w} height={size.h} role="img" aria-label={`Relative rotation graph, ${rows.length} groups`}>
        {quad('Improving', m.l, m.t, cx - m.l, cy - m.t)}
        {quad('Leading', cx, m.t, m.l + iw - cx, cy - m.t)}
        {quad('Lagging', m.l, cy, cx - m.l, m.t + ih - cy)}
        {quad('Weakening', cx, cy, m.l + iw - cx, m.t + ih - cy)}
        {ticks(dom.x).map((v) => (
          <g key={`x${v}`}>
            <line x1={sx(v)} x2={sx(v)} y1={m.t} y2={m.t + ih} className="stroke-line/60" />
            <text x={sx(v)} y={size.h - 8} textAnchor="middle" className="fill-fg-3 text-2xs">
              {v}
            </text>
          </g>
        ))}
        {ticks(dom.y).map((v) => (
          <g key={`y${v}`}>
            <line x1={m.l} x2={m.l + iw} y1={sy(v)} y2={sy(v)} className="stroke-line/60" />
            <text x={m.l - 4} y={sy(v) + 3} textAnchor="end" className="fill-fg-3 text-2xs">
              {v}
            </text>
          </g>
        ))}
        <line x1={cx} x2={cx} y1={m.t} y2={m.t + ih} className="stroke-line-strong" />
        <line x1={m.l} x2={m.l + iw} y1={cy} y2={cy} className="stroke-line-strong" />
        <text x={m.l + 4} y={m.t + 12} className="fill-info text-2xs font-semibold uppercase">
          Improving
        </text>
        <text x={m.l + iw - 4} y={m.t + 12} textAnchor="end" className="fill-up text-2xs font-semibold uppercase">
          Leading
        </text>
        <text x={m.l + 4} y={m.t + ih - 5} className="fill-down text-2xs font-semibold uppercase">
          Lagging
        </text>
        <text x={m.l + iw - 4} y={m.t + ih - 5} textAnchor="end" className="fill-warn text-2xs font-semibold uppercase">
          Weakening
        </text>
        <text x={m.l + iw / 2} y={m.t + ih + 20} textAnchor="middle" className="hidden" />

        {rows.map((r) => {
          const tok = tokenOf(r.rrg_quadrant);
          const pts = r.tail.filter((p) => typeof p.rs_ratio === 'number' && typeof p.rs_momentum === 'number');
          const active = r.id === hover || r.id === selectedId;
          const dim = (hover || selectedId) && !active;
          return (
            <g key={r.id} className={cn(dim && 'opacity-30')}>
              {pts.length > 1 && (
                <polyline
                  points={pts.map((p) => `${sx(p.rs_ratio as number)},${sy(p.rs_momentum as number)}`).join(' ')}
                  className={cn(STROKE[tok], 'fill-none', active ? 'opacity-90' : 'opacity-45')}
                  strokeWidth={active ? 1.8 : 1.1}
                />
              )}
              {pts.slice(0, -1).map((p, i) => (
                <circle
                  key={i}
                  cx={sx(p.rs_ratio as number)}
                  cy={sy(p.rs_momentum as number)}
                  r={1.6}
                  className={cn(FILL[tok], 'opacity-50')}
                />
              ))}
            </g>
          );
        })}
        {rows.map((r) => {
          if (typeof r.rs_ratio !== 'number' || typeof r.rs_momentum !== 'number') return null;
          const tok = tokenOf(r.rrg_quadrant);
          const active = r.id === hover || r.id === selectedId;
          const dim = (hover || selectedId) && !active;
          const showLabel = active || labelled.has(r.id);
          const x = sx(r.rs_ratio);
          const y = sy(r.rs_momentum);
          return (
            <g
              key={`h-${r.id}`}
              className={cn('cursor-pointer', dim && 'opacity-40')}
              onMouseEnter={() => setHover(r.id)}
              onMouseLeave={() => setHover((h) => (h === r.id ? null : h))}
              onClick={() => onSelect?.(r.id)}
            >
              <circle cx={x} cy={y} r={active ? 6 : 4.2} className={cn(FILL[tok], 'stroke-bg')} strokeWidth={1.2} />
              <circle cx={x} cy={y} r={10} className="fill-transparent" />
              {showLabel && (
                <text x={x + 7} y={y + 3} className={cn('text-2xs', active ? 'fill-fg font-semibold' : 'fill-fg-2')}>
                  {r.group_name.length > 22 ? `${r.group_name.slice(0, 21)}…` : r.group_name}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {hovered && typeof hovered.rs_ratio === 'number' && typeof hovered.rs_momentum === 'number' && (
        <div
          className="pointer-events-none absolute z-10 w-56 rounded border border-line-strong bg-surface-3 p-2 text-2xs shadow-xl"
          style={{
            left: Math.min(size.w - 230, sx(hovered.rs_ratio) + 12),
            top: Math.max(4, Math.min(size.h - 110, sy(hovered.rs_momentum) - 20)),
          }}
        >
          <div className="mb-1 text-xs font-semibold text-fg">{hovered.group_name}</div>
          <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-fg-2">
            <span>Quadrant</span>
            <span className="text-right text-fg">
              {hovered.rrg_quadrant ?? '—'}
              {hovered.days_in_quadrant != null ? ` · ${hovered.days_in_quadrant}d` : ''}
            </span>
            <span>RS-Ratio</span>
            <span className="num text-right text-fg">{fmtNum(hovered.rs_ratio, 2)}</span>
            <span>RS-Momentum</span>
            <span className="num text-right text-fg">{fmtNum(hovered.rs_momentum, 2)}</span>
            <span>Rank</span>
            <span className="num text-right text-fg">{hovered.rank ?? '—'}</span>
            <span>Members</span>
            <span className="num text-right text-fg">{hovered.stocks ?? '—'}</span>
          </div>
          {hovered.tail.length > 1 && (
            <div className="mt-1 text-fg-3">
              Tail from {fmtDateShort(hovered.tail[0].trade_date ?? null)} (weekly points). Click to drill in.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
