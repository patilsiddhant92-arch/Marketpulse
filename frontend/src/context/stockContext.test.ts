import { describe, expect, it } from 'vitest';
import type { StockContextRow } from '../api/types';
import { contextChips, contextChunks, dealsHref, noteShort } from './stockContext';

const ctx = (o: Partial<StockContextRow> = {}): StockContextRow =>
  ({
    symbol: 'AAA',
    in_session: true,
    industry: 'Heavy Electrical',
    group: {
      id: 'industry:Heavy Electrical',
      group_name: 'Heavy Electrical',
      level: 'industry',
      thin: false,
      health: 71.4,
      health_zone: 'Healthy',
      health_rank: 3,
      rrg_quadrant: 'Leading',
      quadrant_note: 'Leading but falling',
      health_spark_21: [60, 65, 71.4],
    },
    deal_net_10s_cr: 12.34,
    deal_prints_10s: 2,
    setups: [{ queue: 'vcp', label: 'VCP', distance_to_trigger_pct: 2.46, trigger_price: 110, setup_age_sessions: 4 }],
    data_warning: null,
    next_results: { event_type: 'financial_results', event_date: '2026-09-30' },
    next_corp_action: null,
    ...o,
  }) as StockContextRow;

describe('stock context', () => {
  it('chunks unique upper-cased symbols into ≤ 200 per request, sorted for stable keys', () => {
    const syms = ['b', 'A', 'a', null, '', ...Array.from({ length: 450 }, (_, i) => `S${i}`)];
    const chunks = contextChunks(syms);
    expect(chunks.map((c) => c.length)).toEqual([200, 200, 52]);
    expect(chunks.flat()).toContain('A');
    expect(chunks.flat().filter((s) => s === 'A')).toHaveLength(1);
    expect(contextChunks(['Z', 'Y'])).toEqual([['Y', 'Z']]);
  });

  it('builds group, setup, deals and event chips with links, falling note as ↓', () => {
    const chips = contextChips(ctx(), { asOf: '2026-09-25' });
    expect(chips.map((c) => c.label)).toEqual(['H71 Lead ↓', 'VCP 2.5%', 'Deals +12.3', 'Res 5d']);
    expect(chips[0].tone).toBe('positive');
    expect(chips[0].href).toBe('/groups?group=industry%3AHeavy%20Electrical');
    expect(chips[1].href).toBe('/setups?sq=vcp');
    expect(chips[2].href).toBe(dealsHref('AAA'));
    expect(chips[0].title).toContain('falling');
  });

  it('omits parts the table already shows and the current queue', () => {
    const chips = contextChips(ctx({ data_warning: 'gap on 2026-09-01' }), { omit: ['deals', 'events'], skipQueue: 'vcp' });
    expect(chips.map((c) => c.part)).toEqual(['group', 'warning']);
    expect(contextChips(undefined)).toEqual([]);
    expect(contextChips(ctx({ group: null, setups: [], deal_prints_10s: 0, next_results: null }))).toEqual([]);
  });

  it('shortens quadrant notes', () => {
    expect(noteShort('Leading but falling')).toBe('falling');
    expect(noteShort('Improving on narrow breadth')).toBe('narrow');
    expect(noteShort(null)).toBeNull();
  });
});
