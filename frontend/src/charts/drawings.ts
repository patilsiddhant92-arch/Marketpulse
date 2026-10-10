/**
 * Drawing tools (HarkPro/09-tab-charts.md §7, 12-sprint2-plan.md "Chart tools"): horizontal line,
 * trend line, rectangle, long / short position and anchored VWAP, saved per symbol in this browser
 * (localStorage) and shared by every chart of that symbol. Measure is a temporary tool (not saved).
 * Bar replay and compare are chart modes, not drawings. No line alerts.
 */
import { useSyncExternalStore } from 'react';
import { readJSON, writeJSON } from '../lib/storage';
import { tokenColor } from '../lib/tokens';
import type { ChartLevel, ChartSegment } from '../ui/Chart';

export type DrawTool = 'none' | 'hline' | 'trend' | 'rect' | 'measure' | 'long' | 'short' | 'avwap' | 'replay';

export interface DrawPoint {
  time: string;
  price: number;
}

export type Drawing =
  | { id: string; kind: 'hline'; a: DrawPoint }
  | { id: string; kind: 'trend'; a: DrawPoint; b: DrawPoint }
  | { id: string; kind: 'rect'; a: DrawPoint; b: DrawPoint }
  /** Position: a = entry, b = stop (time = the end of the box), target at `rr` × risk. */
  | { id: string; kind: 'long' | 'short'; a: DrawPoint; b: DrawPoint; rr: number }
  | { id: string; kind: 'avwap'; a: DrawPoint };

/** Default reward : risk of a new position. */
export const DEFAULT_RR = 2;

/** Target price of a position drawing. */
export function positionTarget(d: { kind: 'long' | 'short'; a: DrawPoint; b: DrawPoint; rr: number }): number {
  const risk = Math.abs(d.a.price - d.b.price);
  return d.kind === 'long' ? d.a.price + d.rr * risk : d.a.price - d.rr * risk;
}

/** Measure read-out between two points: "+12.4% · 23 bars". */
export function measureText(a: DrawPoint & { index: number }, b: DrawPoint & { index: number }): string {
  const ch = a.price > 0 ? (b.price / a.price - 1) * 100 : 0;
  const bars = Math.abs(b.index - a.index);
  return `${ch >= 0 ? '+' : '−'}${Math.abs(ch).toFixed(1)}% · ${(b.price - a.price >= 0 ? '+' : '−') + Math.abs(b.price - a.price).toFixed(2)} · ${bars} bar${bars === 1 ? '' : 's'}`;
}

type Store = Record<string, Drawing[]>;

const KEY = 'mp.chart.drawings.v1';
const MAX_PER_SYMBOL = 50;

const isPoint = (p: unknown): p is DrawPoint =>
  !!p && typeof (p as DrawPoint).time === 'string' && typeof (p as DrawPoint).price === 'number' && Number.isFinite((p as DrawPoint).price);

/** Drop malformed entries (storage is user-editable). */
export function sanitize(raw: unknown): Store {
  const out: Store = {};
  if (!raw || typeof raw !== 'object') return out;
  for (const [sym, list] of Object.entries(raw as Record<string, unknown>)) {
    if (!Array.isArray(list)) continue;
    const ok = list.filter(
      (d): d is Drawing =>
        !!d &&
        typeof d.id === 'string' &&
        (((d.kind === 'hline' || d.kind === 'avwap') && isPoint(d.a)) ||
          ((d.kind === 'trend' || d.kind === 'rect') && isPoint(d.a) && isPoint(d.b)) ||
          ((d.kind === 'long' || d.kind === 'short') && isPoint(d.a) && isPoint(d.b) && typeof d.rr === 'number' && d.rr > 0)),
    );
    if (ok.length) out[sym] = ok.slice(-MAX_PER_SYMBOL);
  }
  return out;
}

let cache: Store | null = null;
const subs = new Set<() => void>();
const get = () => (cache ??= sanitize(readJSON<unknown>(KEY, {})));
const EMPTY: Drawing[] = [];

function save(next: Store) {
  cache = next;
  writeJSON(KEY, next);
  subs.forEach((f) => f());
}

export function drawingsFor(sym: string): Drawing[] {
  return get()[sym] ?? EMPTY;
}

export function addDrawing(sym: string, d: Drawing): void {
  const cur = get();
  save({ ...cur, [sym]: [...(cur[sym] ?? []), d].slice(-MAX_PER_SYMBOL) });
}

export function removeDrawing(sym: string, id: string): void {
  const cur = get();
  const list = (cur[sym] ?? []).filter((d) => d.id !== id);
  const next = { ...cur };
  if (list.length) next[sym] = list;
  else delete next[sym];
  save(next);
}

export function clearDrawings(sym: string): void {
  const next = { ...get() };
  delete next[sym];
  save(next);
}

export function useDrawings(sym: string): Drawing[] {
  return useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    () => drawingsFor(sym),
    () => drawingsFor(sym),
  );
}

/** Test hook. */
export function resetDrawingsCache(): void {
  cache = null;
}

let seq = 0;
export function newDrawingId(): string {
  seq += 1;
  return `d${Date.now().toString(36)}${seq}`;
}

/**
 * Two-click state machine for the active tool. Returns the finished drawing (or null) and the
 * pending first point of a trend line.
 */
export function clickTool(
  tool: DrawTool,
  pending: DrawPoint | null,
  p: DrawPoint,
  id: string = newDrawingId(),
): { done: Drawing | null; pending: DrawPoint | null } {
  if (tool === 'hline') return { done: { id, kind: 'hline', a: p }, pending: null };
  if (tool === 'avwap') return { done: { id, kind: 'avwap', a: p }, pending: null };
  if (tool === 'trend' || tool === 'rect') {
    if (!pending) return { done: null, pending: p };
    if (pending.time === p.time) return { done: null, pending: p };
    const [a, b] = pending.time < p.time ? [pending, p] : [p, pending];
    return { done: { id, kind: tool, a, b }, pending: null };
  }
  if (tool === 'long' || tool === 'short') {
    // Click 1 = entry, click 2 = stop (and the right edge of the box).
    if (!pending) return { done: null, pending: p };
    const wrongSide = tool === 'long' ? p.price >= pending.price : p.price <= pending.price;
    if (wrongSide || p.time <= pending.time) return { done: null, pending };
    return { done: { id, kind: tool, a: pending, b: p, rr: DEFAULT_RR }, pending: null };
  }
  return { done: null, pending: null };
}

/** Drawings -> chart levels / segments. */
export function drawingLayers(list: readonly Drawing[]): { levels: ChartLevel[]; segments: ChartSegment[] } {
  const levels: ChartLevel[] = [];
  const segments: ChartSegment[] = [];
  const color = tokenColor('draw');
  for (const d of list) {
    if (d.kind === 'hline') levels.push({ id: d.id, price: d.a.price, color, title: '' });
    else if (d.kind === 'trend')
      segments.push({
        id: d.id,
        pane: 'price',
        from: { time: d.a.time, value: d.a.price },
        to: { time: d.b.time, value: d.b.price },
        color,
        width: 2,
      });
  }
  return { levels, segments };
}
