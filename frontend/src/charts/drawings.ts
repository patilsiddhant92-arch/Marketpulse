/**
 * Drawing tools (HarkPro/09-tab-charts.md §7.1): horizontal line and trend line, saved per
 * symbol in this browser (localStorage), shared by every chart of that symbol.
 */
import { useSyncExternalStore } from 'react';
import { readJSON, writeJSON } from '../lib/storage';
import type { ChartLevel, ChartSegment } from '../ui/Chart';

export type DrawTool = 'none' | 'hline' | 'trend';

export interface DrawPoint {
  time: string;
  price: number;
}

export type Drawing =
  | { id: string; kind: 'hline'; a: DrawPoint }
  | { id: string; kind: 'trend'; a: DrawPoint; b: DrawPoint };

type Store = Record<string, Drawing[]>;

const KEY = 'mp.chart.drawings.v1';
const MAX_PER_SYMBOL = 50;
export const DRAW_COLOR = '#38bdf8';

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
        ((d.kind === 'hline' && isPoint(d.a)) || (d.kind === 'trend' && isPoint(d.a) && isPoint(d.b))),
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
  if (tool === 'trend') {
    if (!pending) return { done: null, pending: p };
    if (pending.time === p.time) return { done: null, pending: p };
    const [a, b] = pending.time < p.time ? [pending, p] : [p, pending];
    return { done: { id, kind: 'trend', a, b }, pending: null };
  }
  return { done: null, pending: null };
}

/** Drawings -> chart levels / segments. */
export function drawingLayers(list: readonly Drawing[]): { levels: ChartLevel[]; segments: ChartSegment[] } {
  const levels: ChartLevel[] = [];
  const segments: ChartSegment[] = [];
  for (const d of list) {
    if (d.kind === 'hline') levels.push({ id: d.id, price: d.a.price, color: DRAW_COLOR, title: '' });
    else
      segments.push({
        id: d.id,
        pane: 'price',
        from: { time: d.a.time, value: d.a.price },
        to: { time: d.b.time, value: d.b.price },
        color: DRAW_COLOR,
        width: 2,
      });
  }
  return { levels, segments };
}
