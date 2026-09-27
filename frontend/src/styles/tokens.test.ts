/** WCAG AA guard for the token palette: text tokens >= 4.5:1 on every surface. */
import { describe, expect, it } from 'vitest';
import css from './tokens.css?raw';

function token(name: string): [number, number, number] {
  const m = new RegExp(`--c-${name}:\\s*(\\d+)\\s+(\\d+)\\s+(\\d+);`).exec(css);
  if (!m) throw new Error(`token --c-${name} missing`);
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

function luminance([r, g, b]: [number, number, number]): number {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function contrast(a: [number, number, number], b: [number, number, number]): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const SURFACES = ['bg', 'surface', 'surface-2', 'surface-3'];
const TEXT = ['fg', 'fg-2', 'fg-3', 'accent', 'up', 'down', 'warn', 'info', 'violet', 'v-constructive', 'v-weak'];

describe('token contrast (WCAG AA)', () => {
  for (const t of TEXT) {
    for (const s of SURFACES) {
      it(`${t} on ${s} >= 4.5:1`, () => {
        expect(contrast(token(t), token(s))).toBeGreaterThanOrEqual(4.5);
      });
    }
  }
});
