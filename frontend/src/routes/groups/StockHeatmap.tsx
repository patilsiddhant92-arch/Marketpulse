/**
 * TradingView-style stock heatmap (07 §3d, mockups/stock-heatmap.html): tiles = stocks grouped by taxonomy,
 * Size and Colour dropdowns, "% change" vs "vs market", ≥ ₹1,000 Cr / All, header click zooms, tile opens TradingView.
 */
import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { tradingViewChartUrl } from '../../lib/tradingview';
import { EmptyState } from '../../ui/EmptyState';
import { ErrorState } from '../../ui/ErrorState';
import { Skeleton } from '../../ui/Skeleton';
import { Segmented } from '../../ui/Segmented';
import { SourceNote } from '../../ui/SourceNote';
import { useSectors, type HeatRow } from './sectorApi';
import {
  HEAT_COLOURS,
  HEAT_SCALE,
  HEAT_SIZES,
  fmtHeat,
  heatColour,
  heatGroups,
  heatPosition,
  sizeOf,
  squarify,
  type HeatColour,
  type HeatGroup,
  type HeatSize,
} from './sectorModel';

const HEADER = 16;

function fmtCr(v: number | null | undefined): string {
  if (v == null) return '–';
  if (v >= 1e5) return `${(v / 1e5).toFixed(2)} L Cr`;
  if (v >= 100) return `${Math.round(v).toLocaleString('en-IN')} Cr`;
  return `${v.toFixed(1)} Cr`;
}
const pct = (v: number | null | undefined) => (v == null ? '–' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`);

function useSize(): [React.RefObject<HTMLDivElement | null>, { w: number; h: number }] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const read = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size];
}

export function StockHeatmap() {
  const q = useSectors<HeatRow>('heatmap', { limit: 5000 });
  const [group, setGroup] = useState<HeatGroup>('sector');
  const [size, setSizeKey] = useState<HeatSize>('t');
  const [colour, setColour] = useState<HeatColour>('r1');
  const [rel, setRel] = useState<'abs' | 'rel'>('abs');
  const [floor, setFloor] = useState<'1000' | 'all'>('1000');
  const [focus, setFocus] = useState<string | null>(null);
  const [tip, setTip] = useState<{ s: HeatRow; x: number; y: number } | null>(null);
  const [ref, box] = useSize();
  const rows = useMemo(() => q.data?.rows ?? [], [q.data]);
  const relOn = rel === 'rel' && !HEAT_SCALE[colour].norel;
  const view = useMemo(
    () => heatGroups(rows, { group, size, colour, rel: rel === 'rel', floor: floor === '1000', focus }),
    [rows, group, size, colour, rel, floor, focus],
  );
  const layout = useMemo(() => {
    const W = Math.max(0, box.w);
    const H = Math.max(0, box.h);
    return squarify(view.groups, 0, 0, W, H).map((g) => {
      const hd = g.h > 26 && g.w > 40;
      const tiles = squarify(
        g.stocks.map((s) => ({ s, v: sizeOf(s, size) })).sort((a, b) => b.v - a.v),
        0,
        hd ? HEADER : 0,
        Math.max(0, g.w - 2),
        Math.max(0, g.h - (hd ? HEADER + 2 : 2)),
      );
      return { g, hd, tiles };
    });
  }, [view, box, size]);
  const val = (s: HeatRow) => {
    const v = s[colour];
    return v == null ? null : relOn && view.market != null ? v - view.market : v;
  };
  const up = view.shown.filter((s) => (s[colour] ?? 0) > 0).length;
  const dn = view.shown.filter((s) => (s[colour] ?? 0) < 0).length;
  const tt = view.shown.reduce((a, s) => a + (s.t ?? 0), 0);
  const m = HEAT_SCALE[colour];
  const c0 = relOn ? 0 : m.c;
  const legend = [-1, -2 / 3, -1 / 3, 0, 1 / 3, 2 / 3, 1].map((k) => c0 + k * m.s * (m.inv ? -1 : 1));

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line px-3 py-1.5 text-xs text-fg-3">
        <Segmented
          label="Heatmap grouping"
          options={[
            { value: 'sector', label: 'Sector' },
            { value: 'broad_industry', label: 'Broad Industry' },
            { value: 'industry', label: 'Industry' },
          ]}
          value={group}
          onChange={(v) => {
            setGroup(v);
            setFocus(null);
          }}
        />
        <label className="flex items-center gap-1">
          Size
          <select
            aria-label="Tile size"
            value={size}
            onChange={(e) => setSizeKey(e.target.value as HeatSize)}
            className="h-6 rounded border border-line bg-surface-2 px-1 text-xs text-fg"
          >
            {HEAT_SIZES.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1">
          Colour
          <select
            aria-label="Tile colour"
            value={colour}
            onChange={(e) => setColour(e.target.value as HeatColour)}
            className="h-6 rounded border border-line bg-surface-2 px-1 text-xs text-fg"
          >
            {HEAT_COLOURS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <Segmented
          label="Colour mode"
          options={[
            { value: 'abs', label: '% change' },
            { value: 'rel', label: 'vs market', title: 'Minus the median stock (return metrics only): fixes the everything-green day' },
          ]}
          value={rel}
          onChange={setRel}
        />
        <Segmented
          label="Universe"
          options={[
            { value: '1000', label: '≥ ₹1,000 Cr' },
            { value: 'all', label: 'All' },
          ]}
          value={floor}
          onChange={setFloor}
        />
        {focus && (
          <button type="button" className="text-accent hover:underline" onClick={() => setFocus(null)}>
            ← All groups
          </button>
        )}
        <div className="ml-auto flex items-center">
          {legend.map((v, i) => (
            <span
              key={i}
              className="w-10 py-0.5 text-center text-2xs text-white"
              style={{ background: heatColour(heatPosition(colour, v, relOn)) }}
            >
              {fmtHeat(colour, v, relOn)}
            </span>
          ))}
        </div>
        <SourceNote meta={q.data?.meta} />
      </div>
      <div className="shrink-0 px-3 py-1 text-2xs text-fg-3">
        {q.data?.as_of} · {view.shown.length} stocks · {up} up, {dn} down · turnover ₹{fmtCr(tt)} · median stock{' '}
        {fmtHeat(colour, view.market)} · size = {HEAT_SIZES.find((s) => s.value === size)?.label.toLowerCase()}
        {focus ? ` · zoomed: ${focus}` : ''} · click a tile for its TradingView chart, a header to zoom
      </div>
      <div ref={ref} className="relative mx-3 mb-2 min-h-[480px] flex-1" onMouseLeave={() => setTip(null)}>
        {q.error ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : q.isLoading ? (
          <Skeleton className="h-full w-full" />
        ) : !view.shown.length ? (
          <EmptyState title="No stocks to draw" detail={q.data?.meta.reason ?? 'No stock has a value for this size metric.'} />
        ) : (
          layout.map(({ g, hd, tiles }) => (
            <div
              key={g.key}
              className="absolute overflow-hidden border border-black"
              style={{ left: g.x, top: g.y, width: g.w, height: g.h }}
            >
              {hd && (
                <button
                  type="button"
                  className="absolute inset-x-0 top-0 h-4 truncate bg-surface-3 px-1 text-left text-2xs font-semibold text-fg hover:bg-surface-2"
                  title={`Zoom into ${g.key}`}
                  onClick={() => setFocus(focus ? null : g.key)}
                >
                  {g.key} {fmtHeat(colour, g.move, relOn)}
                </button>
              )}
              {tiles.map((t) => {
                const fs = Math.max(8, Math.min(22, Math.sqrt(t.w * t.h) / 5));
                return (
                  <a
                    key={t.s.symbol}
                    href={tradingViewChartUrl(t.s.symbol)}
                    target="_blank"
                    rel="noreferrer"
                    aria-label={`${t.s.symbol} ${fmtHeat(colour, t.s[colour])}`}
                    className="absolute flex flex-col items-center justify-center overflow-hidden border border-black/50 text-center leading-tight text-white hover:z-10 hover:outline hover:outline-2 hover:outline-white"
                    style={{
                      left: t.x,
                      top: t.y,
                      width: t.w,
                      height: t.h,
                      background: heatColour(heatPosition(colour, val(t.s), relOn)),
                      fontSize: fs,
                    }}
                    onMouseMove={(e) => setTip({ s: t.s, x: e.clientX, y: e.clientY })}
                  >
                    {t.w > 30 && t.h > 16 && <b>{t.s.symbol}</b>}
                    {t.w > 30 && t.h > fs * 2.6 && <span className="opacity-90">{fmtHeat(colour, t.s[colour])}</span>}
                  </a>
                );
              })}
            </div>
          ))
        )}
      </div>
      {tip && (
        <div
          role="tooltip"
          className="pointer-events-none fixed z-50 min-w-[210px] rounded border border-line bg-surface-2 px-2 py-1.5 text-2xs text-fg-2 shadow"
          style={{ left: Math.min(tip.x + 14, window.innerWidth - 240), top: Math.min(tip.y + 14, window.innerHeight - 180) }}
        >
          <b className="text-fg">{tip.s.symbol}</b> · ₹{tip.s.c?.toLocaleString('en-IN')}
          <div className="text-fg-3">
            {tip.s.sector} › {tip.s.broad_industry ?? ''} › {tip.s.industry ?? ''}
          </div>
          <div>
            1D {pct(tip.s.r1)} · 1W {pct(tip.s.r5)} · 1M {pct(tip.s.r21)}
          </div>
          {!HEAT_SCALE[colour].norel && view.market != null && tip.s[colour] != null && (
            <div>vs median stock: {pct((tip.s[colour] as number) - view.market)}</div>
          )}
          <div>
            Turnover ₹{fmtCr(tip.s.t)} (20D avg ₹{fmtCr(tip.s.t20)}, {tip.s.t && tip.s.t20 ? `${(tip.s.t / tip.s.t20).toFixed(1)}×` : '–'})
          </div>
          <div>
            Volume {tip.s.v?.toLocaleString('en-IN') ?? '–'} · RVOL {tip.s.rvol ?? '–'} · Deliv {tip.s.dp ?? '–'}%
          </div>
          <div>
            Gap {pct(tip.s.gap)} · From open {pct(tip.s.co)} · 3M {pct(tip.s.r63)}
          </div>
          <div>
            From 52W high {pct(tip.s.a52)} · RS {tip.s.rs ?? '–'} · ATR {tip.s.vol ?? '–'}%
          </div>
          <div>Mcap ₹{fmtCr(tip.s.mc)}</div>
        </div>
      )}
    </div>
  );
}
