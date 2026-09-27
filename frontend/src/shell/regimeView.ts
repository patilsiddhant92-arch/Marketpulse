/**
 * Pure view-model for the Market Environment (spec 6.1) built from
 * GET /api/v2/market/regime rows (newest first). Only derives wording from
 * served fields — never invents a status or value.
 */
import type { Direction, PillarKey, PillarStatus, RegimeRow, Verdict } from '../api/types';
import { fmtWeekday } from '../lib/fmt';

export const VERDICTS: readonly Verdict[] = ['Danger', 'Weak', 'Mixed', 'Constructive', 'Favourable'];

/** Question each pillar answers (spec 6.1.2 table). */
export const PILLAR_META: Record<PillarKey, { name: string; question: string }> = {
  trend: { name: 'Trend', question: 'Is the market going up?' },
  participation: { name: 'Participation', question: 'Are most stocks joining?' },
  leadership: { name: 'Leadership', question: 'Are strong stocks getting stronger?' },
  follow_through: { name: 'Follow-through', question: 'Are breakouts working now?' },
  stress: { name: 'Stress', question: 'Hidden selling or fear?' },
};
const PILLAR_ORDER: PillarKey[] = ['trend', 'participation', 'leadership', 'follow_through', 'stress'];

export interface PillarView {
  key: PillarKey;
  name: string;
  question: string;
  status: PillarStatus | null;
  sentence: string | null;
  dir1d: Direction | null;
  dir1w: Direction | null;
  dir1m: Direction | null;
  /** Numeric inputs keyed by metric-dictionary key. */
  metrics: { metric: string; value: number | null }[];
  /** Non-numeric inputs, shown as text. */
  notes: { key: string; value: string }[];
}

export interface ReadingView {
  id: string;
  title: string;
  text: string;
  tone: 'positive' | 'negative' | 'neutral';
}

export interface EnvironmentView {
  asOf: string | null;
  verdict: Verdict | null;
  previousVerdict: Verdict | null;
  changedOn: string | null;
  daysInState: number | null;
  /** e.g. "improved from Weak on Mon · 2nd day" (derived from served fields). */
  whatChanged: string | null;
  ruleId: string | null;
  pillars: PillarView[];
  readings: ReadingView[];
  /** Oldest -> newest verdicts for the trust strip. */
  history: { date: string; verdict: Verdict | null }[];
}

export function asVerdict(v: unknown): Verdict | null {
  if (typeof v !== 'string') return null;
  const hit = VERDICTS.find((x) => x.toLowerCase() === v.trim().toLowerCase());
  return hit ?? null;
}

function asStatus(v: unknown): PillarStatus | null {
  if (typeof v !== 'string') return null;
  const s = v.trim().toLowerCase();
  return s === 'healthy' ? 'Healthy' : s === 'neutral' ? 'Neutral' : s === 'weak' ? 'Weak' : null;
}

function asDirection(v: unknown): Direction | null {
  if (typeof v !== 'string') return null;
  const s = v.trim().toLowerCase();
  if (s === 'up' || s === 'rising' || s === 'improving') return 'up';
  if (s === 'down' || s === 'falling' || s === 'deteriorating') return 'down';
  if (s === 'flat' || s === 'steady' || s === 'unchanged') return 'flat';
  return null;
}

function ordinal(n: number): string {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
  return `${n}${({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th'}`;
}

export function describeChange(
  verdict: Verdict | null,
  previous: Verdict | null,
  changedOn: string | null,
  days: number | null,
): string | null {
  if (!verdict) return null;
  const dayPart = days != null && days > 0 ? `${ordinal(days)} day` : null;
  if (previous && previous !== verdict) {
    const improved = VERDICTS.indexOf(verdict) > VERDICTS.indexOf(previous);
    const when = changedOn ? ` on ${fmtWeekday(changedOn)}` : '';
    return [`${improved ? 'improved' : 'worsened'} from ${previous}${when}`, dayPart].filter(Boolean).join(' · ');
  }
  return dayPart ? `${dayPart} in this state` : null;
}

function readingsOf(raw: unknown): ReadingView[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item, i): ReadingView[] => {
    if (typeof item === 'string') return item.trim() ? [{ id: String(i), title: item, text: '', tone: 'neutral' }] : [];
    if (!item || typeof item !== 'object') return [];
    const o = item as Record<string, unknown>;
    const str = (...keys: string[]) => {
      for (const k of keys) if (typeof o[k] === 'string' && (o[k] as string).trim()) return o[k] as string;
      return '';
    };
    const title = str('title', 'name', 'rule', 'id');
    const text = str('text', 'sentence', 'detail', 'message');
    if (!title && !text) return [];
    const toneRaw = str('tone').toLowerCase();
    const tone =
      toneRaw === 'positive' || toneRaw === 'good' ? 'positive' : toneRaw === 'negative' || toneRaw === 'bad' ? 'negative' : 'neutral';
    return [{ id: str('id') || String(i), title: title || text, text: title ? text : '', tone }];
  });
}

export function toEnvironmentView(rows: readonly RegimeRow[]): EnvironmentView | null {
  const latest = rows[0];
  if (!latest) return null;
  const verdict = asVerdict(latest.verdict);
  const previousVerdict = asVerdict(latest.previous_verdict);
  const pillars: PillarView[] = PILLAR_ORDER.map((key) => {
    const p = latest.pillars?.[key] ?? {};
    const inputs = (p.inputs ?? {}) as Record<string, unknown>;
    const metrics: PillarView['metrics'] = [];
    const notes: PillarView['notes'] = [];
    for (const [k, v] of Object.entries(inputs)) {
      if (v === null || typeof v === 'number') metrics.push({ metric: k, value: typeof v === 'number' && Number.isFinite(v) ? v : null });
      else if (typeof v === 'string' || typeof v === 'boolean') notes.push({ key: k, value: String(v) });
    }
    return {
      key,
      ...PILLAR_META[key],
      status: asStatus(p.status),
      sentence: p.sentence ?? null,
      dir1d: asDirection(p.dir_1d),
      dir1w: asDirection(p.dir_1w),
      dir1m: asDirection(p.dir_1m),
      metrics,
      notes,
    };
  });
  return {
    asOf: latest.trade_date ?? null,
    verdict,
    previousVerdict,
    changedOn: latest.changed_on ?? null,
    daysInState: latest.days_in_state ?? null,
    whatChanged: describeChange(verdict, previousVerdict, latest.changed_on ?? null, latest.days_in_state ?? null),
    ruleId: latest.rule_id ?? null,
    pillars,
    readings: readingsOf(latest.readings),
    history: rows
      .filter((r) => !!r.trade_date)
      .map((r) => ({ date: r.trade_date as string, verdict: asVerdict(r.verdict) }))
      .reverse(),
  };
}
