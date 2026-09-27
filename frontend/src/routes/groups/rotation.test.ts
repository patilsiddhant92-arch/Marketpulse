import { describe, expect, it } from 'vitest';
import type { RotationRow } from '../../api/types';
import { deltaTone } from '../../desk/CompareStrip';
import { healthHeat, sortRotation } from './RotationGrid';

const row = (name: string, now: number | null, change: number | null): RotationRow => ({ id: `industry:${name}`, group_name: name, level: 'industry', health_now: now, health_change: change, cells: [] });

describe('rotation + compare helpers', () => {
  it('maps Health around 50 to a heat tint', () => {
    expect(healthHeat(50)).toBe(0);
    expect(healthHeat(90)).toBe(1);
    expect(healthHeat(10)).toBe(-1);
    expect(healthHeat(null)).toBeNull();
  });
  it('sorts by Health now or 12-week change and filters by name; NULL last', () => {
    const rows = [row('Banks', 40, 20), row('Pharma', 80, -5), row('Autos', null, null)];
    expect(sortRotation(rows, 'now', '').map((r) => r.group_name)).toEqual(['Pharma', 'Banks', 'Autos']);
    expect(sortRotation(rows, 'change', '').map((r) => r.group_name)).toEqual(['Banks', 'Pharma', 'Autos']);
    expect(sortRotation(rows, 'now', 'pha').map((r) => r.group_name)).toEqual(['Pharma']);
  });
  it('colours a change by which direction is better; queues stay neutral', () => {
    expect(deltaTone({ delta: 2, better: 'up' })).toBe('text-up');
    expect(deltaTone({ delta: -2, better: 'up' })).toBe('text-down');
    expect(deltaTone({ delta: 5, better: null })).toBe('text-fg-2');
    expect(deltaTone({ delta: 0, better: 'up' })).toBe('text-fg-3');
  });
});
