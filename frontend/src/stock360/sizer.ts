/**
 * Position sizer (spec 7.2 / K13): uses only what the user types — ₹ risk per
 * trade and, optionally, capital. No implied account equity, no defaults.
 */
import { readJSON, writeJSON } from '../lib/storage';

export interface SizerInput {
  riskRupees: number | null;
  capital: number | null;
  /** Warn when one position exceeds this % of capital. */
  capPct: number;
}

export interface SizerResult {
  /** ₹ at risk per share (trigger − stop). */
  perShareRisk: number;
  shares: number;
  positionValue: number;
  /** Actual ₹ lost if stopped (shares × per-share risk). */
  actualRisk: number;
  pctOfCapital: number | null;
  overCap: boolean;
}

export type SizerOutcome = { ok: true; result: SizerResult } | { ok: false; reason: string };

/** Shares = floor(risk ₹ / (trigger − stop)). Explains itself when it cannot size. */
export function sizePosition(trigger: number | null | undefined, stop: number | null | undefined, input: SizerInput): SizerOutcome {
  if (input.riskRupees == null || !(input.riskRupees > 0)) return { ok: false, reason: 'Type your ₹ risk per trade to size.' };
  if (trigger == null || stop == null) return { ok: false, reason: 'No trigger/stop for this setup.' };
  const perShareRisk = trigger - stop;
  if (!(perShareRisk > 0)) return { ok: false, reason: 'Stop is not below trigger.' };
  const shares = Math.floor(input.riskRupees / perShareRisk);
  if (shares < 1) return { ok: false, reason: `₹ risk is below one share's risk (₹${perShareRisk.toFixed(2)}).` };
  const positionValue = shares * trigger;
  const pctOfCapital = input.capital != null && input.capital > 0 ? (positionValue / input.capital) * 100 : null;
  return {
    ok: true,
    result: {
      perShareRisk,
      shares,
      positionValue,
      actualRisk: shares * perShareRisk,
      pctOfCapital,
      overCap: pctOfCapital != null && pctOfCapital > input.capPct,
    },
  };
}

/** Parse a typed rupee amount ("25,000", "25000", "2.5e4"); blank/invalid -> null. */
export function parseRupees(raw: string): number | null {
  const s = raw.replace(/[,₹\s]/g, '');
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) && n > 0 ? n : null;
}

const KEY = 'mp.sizer.v1';

/** Per-viewer convenience: the typed values persist in this browser only. */
export function loadSizer(): SizerInput {
  const v = readJSON<Partial<SizerInput>>(KEY, {});
  return {
    riskRupees: typeof v.riskRupees === 'number' && v.riskRupees > 0 ? v.riskRupees : null,
    capital: typeof v.capital === 'number' && v.capital > 0 ? v.capital : null,
    capPct: typeof v.capPct === 'number' && v.capPct > 0 ? v.capPct : 25,
  };
}

export function saveSizer(v: SizerInput): void {
  writeJSON(KEY, v);
}
