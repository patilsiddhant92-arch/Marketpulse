/**
 * Event candles (HarkPro/09-tab-charts.md §5; deal colours from 08-tab-deals.md §5.5-5.6).
 * Pure; no chart imports. The whole candle takes the colour of the highest-priority event on
 * that bar, with its letter above or below. Ex-dates are a chip only (no colour change).
 *
 * Priority: 1 results (R) · 2 deal B/P/S/C/T · 3 Darvas box-top breakout on volume ≥ 1.5× (↑) ·
 * 4 box-bottom break on volume ≥ 1.5× (↓) · 5 gap ≥ 4% (G) · 6 volume ≥ 3× the 20-bar average (V) ·
 * 7 ex-date chip (E). ASM / GSM entry chips need security_risk_daily data (empty locally).
 */
import type { EndpointMap, StockEventRow } from '../api/types';
import { fmtCr, fmtNum } from '../lib/fmt';
import type { OHLCBar } from '../lib/indicators';
import { tokenColor, type TokenName } from '../lib/tokens';

export type DealCandleRow = EndpointMap['charts/{sym}/deal-candles']['row'];

export type EventGroup = 'results' | 'deals' | 'breakout' | 'breakdown' | 'gap' | 'volume' | 'chips';

export const EVENT_GROUPS: { id: EventGroup; label: string; letter: string }[] = [
  { id: 'results', label: 'Results day', letter: 'R' },
  { id: 'deals', label: 'Deals (B P S C T)', letter: 'B' },
  { id: 'breakout', label: 'Box-top breakout on volume', letter: '↑' },
  { id: 'breakdown', label: 'Box-bottom break on volume', letter: '↓' },
  { id: 'gap', label: 'Gap ≥ 4%', letter: 'G' },
  { id: 'volume', label: 'Volume ≥ 3× average', letter: 'V' },
  { id: 'chips', label: 'Ex-date chip', letter: 'E' },
];

export type EventKey =
  | 'results'
  | 'deal_B'
  | 'deal_P'
  | 'deal_S'
  | 'deal_C'
  | 'deal_T'
  | 'breakout'
  | 'breakdown'
  | 'gap_up'
  | 'gap_down'
  | 'volume'
  | 'ex_date';

/** Event palette as design tokens (styles/tokens.css, --c-ev-*). `fg` = the theme text colour (white body). */
export const EVENT_COLORS: Record<EventKey, TokenName> = {
  results: 'ev-results', // purple
  deal_B: 'ev-buy', // teal
  deal_P: 'ev-placement', // blue
  deal_S: 'ev-sell', // orange
  deal_C: 'ev-churn', // grey
  deal_T: 'ev-churn', // grey
  breakout: 'ev-breakout', // bright green
  breakdown: 'ev-breakdown', // red-orange
  gap_up: 'ev-gap', // gold
  gap_down: 'ev-gap',
  volume: 'fg',
  ex_date: 'ev-churn',
};

/** Canvas colour of an event key (resolved from the token at call time). */
export function eventColor(key: EventKey, alpha = 1): string {
  return tokenColor(EVENT_COLORS[key], alpha);
}

const PRIORITY: Record<EventKey, number> = {
  results: 1,
  deal_B: 2,
  deal_P: 2,
  deal_S: 2,
  deal_C: 2,
  deal_T: 2,
  breakout: 3,
  breakdown: 4,
  gap_up: 5,
  gap_down: 5,
  volume: 6,
  ex_date: 7,
};

const GROUP_OF: Record<EventKey, EventGroup> = {
  results: 'results',
  deal_B: 'deals',
  deal_P: 'deals',
  deal_S: 'deals',
  deal_C: 'deals',
  deal_T: 'deals',
  breakout: 'breakout',
  breakdown: 'breakdown',
  gap_up: 'gap',
  gap_down: 'gap',
  volume: 'volume',
  ex_date: 'chips',
};

export const BREAKOUT_VOLUME_X = 1.5;
export const VOLUME_SPIKE_X = 3;
export const GAP_PCT = 4;

export interface ChartEvent {
  /** Displayed bar time the event snaps to. */
  time: string;
  /** Session the event happened on (differs from `time` on W/M bars). */
  date: string;
  key: EventKey;
  letter: string;
  /** Palette token of the event (resolve with tokenColor / eventColor). */
  color: TokenName;
  /** Hover text, plain English. */
  text: string;
  /** Colours the candle (false = chip only). */
  paints: boolean;
}

export interface BarEvents {
  /** Winning event (paints the candle) or the top chip. */
  top: ChartEvent;
  all: ChartEvent[];
}

const nf = (v: number | null | undefined, d = 1) => (v == null ? '—' : fmtNum(v, d));

/** One deal-candle row -> event (null for an unknown letter). */
export function dealEvent(r: DealCandleRow): Omit<ChartEvent, 'time'> | null {
  const letter = r.letter ?? '';
  const key = `deal_${letter}` as EventKey;
  if (!r.trade_date || !(key in EVENT_COLORS)) return null;
  const who = (name: string | null | undefined, cls: string | null | undefined) =>
    name ? `${name}${cls ? ` (${cls})` : ''}` : null;
  const buyer = who(r.top_buyer, r.top_buyer_class);
  const seller = who(r.top_seller, r.top_seller_class);
  const price = r.deal_price != null ? `deal price ₹${nf(r.deal_price, 1)}` : null;
  let head: string;
  switch (letter) {
    case 'B':
      head = `Net buy ${fmtCr(r.net_cr ?? null, 1)}${buyer ? ` by ${buyer}` : ''}`;
      break;
    case 'S':
      head = `Net sell ${fmtCr(r.net_cr == null ? null : Math.abs(r.net_cr), 1)}${seller ? ` by ${seller}` : ''}`;
      break;
    case 'P':
      head = `Placement ${fmtCr(r.buy_cr ?? null, 1)}${seller ? ` from ${seller}` : ''}${buyer ? ` to ${buyer}` : ''}`;
      break;
    case 'T':
      head = `Transfer ${fmtCr(r.buy_cr ?? null, 1)}${seller ? ` from ${seller}` : ''}${buyer ? ` to ${buyer}` : ''}`;
      break;
    default:
      head = `Churn ${fmtCr(r.gross_cr ?? null, 1)} gross (round trips or prop desks)`;
  }
  const status = r.show_line && r.status ? ` · now ${r.status}` : '';
  return {
    date: r.trade_date,
    key,
    letter,
    color: EVENT_COLORS[key],
    text: [head, price].filter(Boolean).join(', ') + status,
    paints: true,
  };
}

/** Results / ex-date events from the served events list (security_events + corporate_actions). */
export function calendarEvents(rows: readonly StockEventRow[]): Omit<ChartEvent, 'time'>[] {
  const out: Omit<ChartEvent, 'time'>[] = [];
  for (const e of rows) {
    if (!e.event_date || !e.event_type || e.upcoming) continue;
    const t = e.event_type.toLowerCase();
    if (t.includes('result') || t.includes('board')) {
      out.push({ date: e.event_date, key: 'results', letter: 'R', color: EVENT_COLORS.results, text: e.headline || 'Results', paints: true });
    } else if (t.includes('dividend') || t.startsWith('ex') || t.includes('bonus') || t.includes('split')) {
      out.push({ date: e.event_date, key: 'ex_date', letter: 'E', color: EVENT_COLORS.ex_date, text: `Ex-date: ${e.headline || e.event_type}`, paints: false });
    }
  }
  return out;
}

export interface BoxRow {
  trade_date?: string | null;
  top?: number | null;
  bottom?: number | null;
  projected?: boolean | null;
}

/** Price/volume events computed on the displayed bars (breakout, breakdown, gap, volume spike). */
export function priceEvents(bars: readonly OHLCBar[], boxes: readonly BoxRow[] | null | undefined): Omit<ChartEvent, 'time'>[] {
  const top = new Map<string, number>();
  const bottom = new Map<string, number>();
  for (const r of boxes ?? []) {
    if (!r.trade_date || r.projected) continue;
    if (r.top != null) top.set(r.trade_date, r.top);
    if (r.bottom != null) bottom.set(r.trade_date, r.bottom);
  }
  const out: Omit<ChartEvent, 'time'>[] = [];
  let volSum = 0;
  let volN = 0;
  const vols: (number | null)[] = bars.map((b) => (b.volume != null && b.volume > 0 ? b.volume : null));
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    // Average of the 20 bars BEFORE this one (today's spike must not dilute its own baseline).
    const avg = volN === 20 ? volSum / 20 : null;
    const v = vols[i];
    const volX = avg && v != null ? v / avg : null;
    if (i > 0) {
      const p = bars[i - 1];
      const t = top.get(p.time);
      const bt = bottom.get(p.time);
      if (t != null && b.close > t && p.close <= t && volX != null && volX >= BREAKOUT_VOLUME_X) {
        out.push({
          date: b.time,
          key: 'breakout',
          letter: '↑',
          color: EVENT_COLORS.breakout,
          text: `Closed above the Darvas box top ${nf(t, 2)} on ${nf(volX, 1)}× average volume`,
          paints: true,
        });
      }
      if (bt != null && b.close < bt && p.close >= bt && volX != null && volX >= BREAKOUT_VOLUME_X) {
        out.push({
          date: b.time,
          key: 'breakdown',
          letter: '↓',
          color: EVENT_COLORS.breakdown,
          text: `Closed below the Darvas box bottom ${nf(bt, 2)} on ${nf(volX, 1)}× average volume`,
          paints: true,
        });
      }
      if (p.close > 0) {
        const gap = (b.open / p.close - 1) * 100;
        if (Math.abs(gap) >= GAP_PCT) {
          out.push({
            date: b.time,
            key: gap > 0 ? 'gap_up' : 'gap_down',
            letter: 'G',
            color: EVENT_COLORS.gap_up,
            text: `Gap ${gap > 0 ? 'up' : 'down'} ${nf(Math.abs(gap), 1)}% at the open`,
            paints: true,
          });
        }
      }
    }
    if (volX != null && volX >= VOLUME_SPIKE_X) {
      out.push({ date: b.time, key: 'volume', letter: 'V', color: EVENT_COLORS.volume, text: `Volume ${nf(volX, 1)}× the 20-bar average`, paints: true });
    }
    // Slide the 20-bar window (a missing volume breaks it).
    if (v == null) {
      volSum = 0;
      volN = 0;
    } else {
      volSum += v;
      volN++;
      if (volN > 20) {
        volSum -= vols[i - 20] as number;
        volN = 20;
      }
    }
  }
  return out;
}

/** Index of the first time >= iso in sorted times; -1 if none. */
function firstAtOrAfter(times: readonly string[], iso: string): number {
  let lo = 0;
  let hi = times.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] >= iso) {
      ans = mid;
      hi = mid - 1;
    } else lo = mid + 1;
  }
  return ans;
}

/**
 * Snap events onto displayed bars and resolve the priority per bar. Disabled groups are dropped.
 * The volume-only event (V) paints only when no other event landed on the bar (spec: "no other event").
 */
export function resolveEvents(
  barTimes: readonly string[],
  events: readonly Omit<ChartEvent, 'time'>[],
  enabled: Partial<Record<EventGroup, boolean>> = {},
): Map<string, BarEvents> {
  const byBar = new Map<string, ChartEvent[]>();
  for (const e of events) {
    if (enabled[GROUP_OF[e.key]] === false) continue;
    const i = firstAtOrAfter(barTimes, e.date);
    if (i < 0) continue;
    // An event after the bar's period (e.g. a stale date far before the first bar) is fine; one
    // before the first displayed bar snaps to it only when it is inside that bar's period.
    if (i === 0 && barTimes.length > 1 && e.date < barTimes[0]) {
      // Daily bars: anything before the first bar is outside the window.
      continue;
    }
    const t = barTimes[i];
    const list = byBar.get(t) ?? [];
    list.push({ ...e, time: t });
    byBar.set(t, list);
  }
  const out = new Map<string, BarEvents>();
  for (const [t, list] of byBar) {
    list.sort((a, b) => PRIORITY[a.key] - PRIORITY[b.key] || a.date.localeCompare(b.date));
    const painters = list.filter((e) => e.paints && (e.key !== 'volume' || list.every((x) => x.key === 'volume' || !x.paints)));
    const top = painters[0] ?? list[0];
    out.set(t, { top: painters[0] ? top : { ...top, paints: false }, all: list });
  }
  return out;
}

// ====================================================================== Chart v2 (Info mode)
/**
 * Info-mode event layer (HarkPro/12-sprint2-plan.md): deals (B P S C T), results and Darvas box
 * breaks colour the whole candle (in the Events colour mode) with their letter / arrow. Gaps and
 * volume spikes never colour a candle: they are small dots only.
 */
export interface InfoMarker {
  time: string;
  text: string;
  color: string;
  position: 'aboveBar' | 'belowBar';
  shape: 'circle' | 'square' | 'arrowUp' | 'arrowDown';
  /** Marker size (lightweight-charts units, 1 = default). */
  size: number;
}

export interface InfoEventLayer {
  /** Candle colour per bar time (empty in the Normal colour mode). */
  paint: Map<string, string>;
  markers: InfoMarker[];
  byBar: Map<string, BarEvents>;
}

const PAINTS: ReadonlySet<EventKey> = new Set(['results', 'deal_B', 'deal_P', 'deal_S', 'deal_C', 'deal_T', 'breakout', 'breakdown']);
const DOTS: ReadonlySet<EventKey> = new Set(['gap_up', 'gap_down', 'volume']);
const BELOW_KEYS: ReadonlySet<EventKey> = new Set(['breakdown', 'deal_S', 'gap_down', 'ex_date']);

export function infoEventLayer(
  barTimes: readonly string[],
  events: readonly Omit<ChartEvent, 'time'>[],
  opts: { colours: 'events' | 'normal'; groups?: Partial<Record<EventGroup, boolean>> },
): InfoEventLayer {
  const byBar = resolveEvents(barTimes, events, opts.groups ?? {});
  const paint = new Map<string, string>();
  const markers: InfoMarker[] = [];
  for (const [time, be] of byBar) {
    const main = be.all.find((e) => PAINTS.has(e.key));
    if (main) {
      if (opts.colours === 'events') paint.set(time, eventColor(main.key));
      markers.push({
        time,
        text: main.letter,
        color: eventColor(main.key),
        position: BELOW_KEYS.has(main.key) ? 'belowBar' : 'aboveBar',
        shape: 'circle',
        size: 0,
      });
    }
    const dot = be.all.find((e) => DOTS.has(e.key));
    if (dot) {
      markers.push({
        time,
        text: '',
        color: dot.key === 'volume' ? tokenColor('fg', 0.85) : eventColor(dot.key),
        position: BELOW_KEYS.has(dot.key) ? 'belowBar' : 'aboveBar',
        shape: 'circle',
        size: 0.5,
      });
    }
  }
  markers.sort((a, b) => a.time.localeCompare(b.time));
  return { paint, markers, byBar };
}
