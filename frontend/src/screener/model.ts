/**
 * Screener tab model (spec 7.3): rules as data, URL-held filters, and the
 * query sent to /api/v2/screener/run and /screener/debug. Pure — no React.
 */
import type { PresetRow, ScreenerRule } from '../api/types';
import { readJSON, writeJSON } from '../lib/storage';

export type RuleOp = ScreenerRule['op'];
export type NumOp = Exclude<RuleOp, 'is_true' | 'is_false'>;

/** A rule as sent to the server (label is display-only and never sent). */
export interface Rule {
  field: string;
  op: RuleOp;
  value?: number | null;
  ref?: string | null;
}

/** Rule field catalog served in /screener/presets meta.context.fields. */
export interface RuleField {
  field: string;
  label: string;
  kind: 'num' | 'bool';
  metric_key?: string | null;
}

export const OP_SYMBOL: Record<NumOp, string> = { gt: '>', gte: '≥', lt: '<', lte: '≤', eq: '=' };
export const NUM_OPS: NumOp[] = ['gte', 'gt', 'lte', 'lt', 'eq'];

export function isBoolOp(op: RuleOp): op is 'is_true' | 'is_false' {
  return op === 'is_true' || op === 'is_false';
}

/** Human label: "Strength rank ≥ 70", "Close > 200 EMA", "not NR7". */
export function ruleLabel(rule: Rule, fields: ReadonlyMap<string, RuleField>): string {
  const name = fields.get(rule.field)?.label ?? rule.field;
  if (rule.op === 'is_true') return name;
  if (rule.op === 'is_false') return `not ${name}`;
  const rhs = rule.ref ? (fields.get(rule.ref)?.label ?? rule.ref) : rule.value == null ? '?' : trimNum(rule.value);
  return `${name} ${OP_SYMBOL[rule.op]} ${rhs}`;
}

function trimNum(v: number): string {
  return Number.isInteger(v) ? String(v) : String(Number(v.toFixed(4)));
}

/** Strip display-only keys; the server contract is {field, op, value|ref}. */
export function cleanRule(rule: Rule): Rule {
  if (isBoolOp(rule.op)) return { field: rule.field, op: rule.op };
  if (rule.ref) return { field: rule.field, op: rule.op, ref: rule.ref };
  return { field: rule.field, op: rule.op, value: rule.value ?? null };
}

export function encodeRules(rules: readonly Rule[]): string {
  return JSON.stringify(rules.map(cleanRule));
}

/** Parse a URL rules param; invalid input -> null (fall back to the preset's rules). */
export function decodeRules(raw: string | null | undefined): Rule[] | null {
  if (!raw) return null;
  try {
    const data: unknown = JSON.parse(raw);
    if (!Array.isArray(data) || data.length > 40) return null;
    const out: Rule[] = [];
    for (const r of data) {
      if (!r || typeof r !== 'object') return null;
      const { field, op, value, ref } = r as Record<string, unknown>;
      if (typeof field !== 'string' || typeof op !== 'string') return null;
      if (!['gt', 'gte', 'lt', 'lte', 'eq', 'is_true', 'is_false'].includes(op)) return null;
      out.push(
        cleanRule({
          field,
          op: op as RuleOp,
          value: typeof value === 'number' ? value : null,
          ref: typeof ref === 'string' ? ref : null,
        }),
      );
    }
    return out;
  } catch {
    return null;
  }
}

export function sameRules(a: readonly Rule[], b: readonly Rule[]): boolean {
  return encodeRules(a) === encodeRules(b);
}

/** A numeric rule needs a value or a ref before it can run. */
export function ruleComplete(rule: Rule): boolean {
  if (isBoolOp(rule.op)) return true;
  return !!rule.ref || (typeof rule.value === 'number' && Number.isFinite(rule.value));
}

export function presetRules(preset: PresetRow | undefined): Rule[] {
  return (preset?.rules ?? []).map((r) => cleanRule({ field: r.field, op: r.op, value: r.value, ref: r.ref }));
}

// ------------------------------------------------------------------ URL state

export const SCREENER_DEFAULTS = {
  preset: 'minervini_8of8',
  rules: '',
  mcap: '1000',
  price: '15',
  vol: '',
  avgvol: '',
  lb: '1',
  ipo: '0',
  level: '',
  group: '',
};
export type ScreenerState = typeof SCREENER_DEFAULTS;

function numOrNull(s: string): number | null {
  if (s.trim() === '') return null;
  const n = Number(s);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

/** Filters shared by run and debug. Empty inputs are omitted (server defaults) or sent as "no floor". */
export function filterQuery(s: ScreenerState) {
  const mcap = numOrNull(s.mcap);
  const price = numOrNull(s.price);
  const vol = numOrNull(s.vol);
  const avgvol = numOrNull(s.avgvol);
  return {
    min_mcap_cr: mcap ?? 0,
    // Empty price box = no price floor (server default would be 15).
    ...(price !== null ? { min_price: price } : { min_price: 0 }),
    ...(vol !== null ? { min_day_volume: vol } : {}),
    ...(avgvol !== null ? { min_avg_volume_20d: avgvol } : {}),
    ...(s.ipo === '1' ? { include_ipos: true } : {}),
    ...(s.level && s.group ? { level: s.level, group: s.group } : {}),
  };
}

export function lookbackDays(s: ScreenerState): number {
  const n = Math.round(Number(s.lb));
  return Number.isFinite(n) ? Math.min(60, Math.max(1, n)) : 1;
}

/** Query for /screener/run: preset id, plus rules only when edited (custom). */
export function runQuery(s: ScreenerState, limit = 5000) {
  const custom = decodeRules(s.rules);
  return {
    preset: s.preset,
    ...(custom ? { rules: encodeRules(custom) } : {}),
    ...filterQuery(s),
    lookback_days: lookbackDays(s),
    limit,
  };
}

/** Human summary of the active floors, for the header line. */
export function describeFloors(s: ScreenerState, queuePreset: boolean): string[] {
  if (queuePreset) return s.level && s.group ? [`${s.group}`] : [];
  const out: string[] = [];
  const mcap = numOrNull(s.mcap);
  if (mcap) out.push(`mcap ≥ ₹${mcap.toLocaleString('en-IN')} Cr`);
  const price = numOrNull(s.price);
  if (price) out.push(`price ≥ ₹${price}`);
  const vol = numOrNull(s.vol);
  if (vol) out.push(`day vol ≥ ${vol.toLocaleString('en-IN')}`);
  const avgvol = numOrNull(s.avgvol);
  if (avgvol) out.push(`20D avg vol ≥ ${avgvol.toLocaleString('en-IN')}`);
  const lb = lookbackDays(s);
  if (lb > 1) out.push(`rules held on any of last ${lb} sessions`);
  if (s.ipo === '1') out.push('IPOs ranked separately');
  if (s.level && s.group) out.push(s.group);
  return out;
}

// ------------------------------------------------------------------ last custom run (Charts source)

export const LAST_RUN_KEY = 'mp.screener.lastRun.v1';

export interface LastRun {
  label: string;
  query: ReturnType<typeof runQuery>;
}

export function saveLastRun(run: LastRun): void {
  writeJSON(LAST_RUN_KEY, run);
}

export function loadLastRun(): LastRun | null {
  const r = readJSON<LastRun | null>(LAST_RUN_KEY, null);
  return r && typeof r === 'object' && r.query && typeof r.query.preset === 'string' ? r : null;
}
