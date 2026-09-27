import { describe, expect, it } from 'vitest';
import type { GroupTreeRow } from '../../api/types';
import { healthZone, marketContextLine, setupsByQueue, squarify, topMovers } from './groupsModel';
import { noteShort } from './health';
import { blocksFor, tileTone } from './Treemap';

describe('groups health helpers', () => {
  it('maps Health to the dictionary zones', () => {
    expect(healthZone(65)).toBe('Healthy');
    expect(healthZone(64.9)).toBe('Mixed');
    expect(healthZone(45)).toBe('Mixed');
    expect(healthZone(44.9)).toBe('Weak');
    expect(healthZone(null)).toBeNull();
  });

  it('writes the Desk-tied context line', () => {
    const line = marketContextLine({
      verdict: 'Mixed',
      midsml400_ret_21d: -3.61,
      quadrants: { Leading: 14 },
      leading_falling: 1,
      groups: 55,
      falling_21d: 36,
    });
    expect(line).toBe("Market Mixed — MidSml400 −3.6% (21d). 'Leading' = strongest vs peers; 1 of 14 is falling in absolute terms. 36 of 55 groups are down over 21 sessions.");
    expect(marketContextLine(null)).toBeNull();
    expect(marketContextLine({ quadrants: { Leading: 0 } })).toContain("No group is 'Leading'");
  });

  it('picks top movers and Desk queues null-safely', () => {
    const rows = [
      { symbol: 'A', change_1d_pct: 3, active_setups: ['vcp'] },
      { symbol: 'B', change_1d_pct: -2, active_setups: ['vcp', 'darvas_10ema'] },
      { symbol: 'C', change_1d_pct: null, active_setups: [] },
      { symbol: 'D', change_1d_pct: 1, active_setups: null },
    ];
    const m = topMovers(rows, 'change_1d_pct', 5);
    expect(m.up.map((r) => r.symbol)).toEqual(['A', 'D']);
    expect(m.down.map((r) => r.symbol)).toEqual(['B']);
    expect(setupsByQueue(rows)).toEqual([
      { queue: 'darvas_10ema', symbols: ['B'] },
      { queue: 'vcp', symbols: ['A', 'B'] },
    ]);
    expect(noteShort('Leading but falling')).toBe('falling');
  });

  it('squarifies into the rectangle, areas proportional to size', () => {
    const tiles = squarify([6, 6, 4, 3, 2, 2, 1], (v) => v, 0, 0, 6, 4);
    expect(tiles).toHaveLength(7);
    const area = tiles.reduce((s, t) => s + t.w * t.h, 0);
    expect(area).toBeCloseTo(24, 6);
    for (const t of tiles) {
      expect(t.w * t.h).toBeCloseTo(t.item, 6);
      expect(t.x).toBeGreaterThanOrEqual(-1e-9);
      expect(t.x + t.w).toBeLessThanOrEqual(6 + 1e-9);
      expect(t.y + t.h).toBeLessThanOrEqual(4 + 1e-9);
    }
    expect(squarify([0, -1], (v) => v, 0, 0, 10, 10)).toEqual([]);
  });

  it('groups treemap leaves under their Broad Sector and colours them', () => {
    const row = (id: string, level: string, parent: string | null, to: number | null, health: number | null = null): GroupTreeRow =>
      ({ id, level, group_name: id.split(':')[1], parent_id: parent, turnover_20d_cr: to, health, return_ew_21d: -2 }) as GroupTreeRow;
    const rows = [
      row('broad_sector:Fin', 'broad_sector', null, 100),
      row('sector:Banks', 'sector', 'broad_sector:Fin', 60),
      row('broad_industry:PSU Banks', 'broad_industry', 'sector:Banks', 40, 70),
      row('broad_industry:Pvt Banks', 'broad_industry', 'sector:Banks', 20, 30),
      row('broad_industry:Orphan', 'broad_industry', null, 10),
    ];
    const blocks = blocksFor(rows, 'broad_industry');
    expect(blocks).toHaveLength(1);
    expect(blocks[0].sector.id).toBe('broad_sector:Fin');
    expect(blocks[0].size).toBe(60);
    expect(tileTone(rows[2], 'health').tone).toBe('up');
    expect(tileTone(rows[3], 'health').tone).toBe('down');
    expect(tileTone(rows[3], 'ret21').tone).toBe('down');
    expect(tileTone({ health: 50, return_ew_21d: null }, 'health').tone).toBe('warn');
  });
});
