import { describe, expect, it } from 'vitest';
import type { SetupBoardRow } from '../../api/types';
import { boardQuery, filterRows, momentumBucket, parseList, rowHighlight, SETUPS_DEFAULTS, toggleInList, tvSections, tvText } from './model';

const row = (p: Partial<SetupBoardRow>): SetupBoardRow =>
  ({
    symbol: 'X',
    tags: [],
    screeners: [],
    status: 'active',
    group_state: 'Neutral',
    group_reason: 'r',
    delivery_streak: 0,
    delivery_5d: [],
    blue_sky: false,
    breakouts_held_6m: 0,
    breakouts_failed_6m: 0,
    chips: [],
    results_soon: false,
    ...p,
  }) as SetupBoardRow;

const rows = [
  row({ symbol: 'AAA', tags: ['SQZ', 'MOM 0–2%'], screeners: ['darvas_squeeze', 'momentum'], group_state: 'Favour', sector: 'Metals', industry: 'Steel' }),
  row({ symbol: 'BBB', tags: ['VCP'], screeners: ['vcp'], group_state: 'Caution', sector: 'Pharma', industry: 'Drugs', name: 'Bee Pharma' }),
  row({ symbol: 'CCC-RE', tags: ['MOM 2–5%'], screeners: ['momentum'], group_state: 'Neutral', sector: 'Metals', industry: 'Steel' }),
];

describe('setups model', () => {
  it('filters by screener (any of), group state and search', () => {
    expect(filterRows(rows, ['momentum'], []).map((r) => r.symbol)).toEqual(['AAA', 'CCC-RE']);
    expect(filterRows(rows, [], ['Favour', 'Caution']).map((r) => r.symbol)).toEqual(['AAA', 'BBB']);
    expect(filterRows(rows, [], [], 'bee').map((r) => r.symbol)).toEqual(['BBB']);
    expect(filterRows(rows, ['vcp'], ['Favour'])).toEqual([]);
  });

  it('parses and toggles list params', () => {
    expect(parseList('vcp,bogus,momentum', ['vcp', 'momentum'] as const)).toEqual(['vcp', 'momentum']);
    expect(toggleInList('vcp', 'momentum')).toBe('vcp,momentum');
    expect(toggleInList('vcp,momentum', 'vcp')).toBe('momentum');
  });

  it('builds TradingView sections by screener, sector and momentum bucket', () => {
    expect(tvSections(rows, 'screener').map((s) => s.title)).toEqual(['Darvas Squeeze', 'VCP', 'Momentum']);
    expect(tvSections(rows, 'sector')).toEqual([
      { title: 'Metals', symbols: ['AAA', 'CCC-RE'] },
      { title: 'Pharma', symbols: ['BBB'] },
    ]);
    expect(tvSections(rows, 'bucket').map((s) => s.title)).toEqual(['MOM 0–2%', 'MOM 2–5%']);
    const { text, count } = tvText(rows, 'sector');
    expect(text).toBe('###Metals,NSE:AAA,NSE:CCC_RE,###Pharma,NSE:BBB');
    expect(count).toBe(3);
    expect(momentumBucket(rows[0])).toBe('0–2%');
  });

  it('maps URL state to the board query', () => {
    expect(boardQuery(SETUPS_DEFAULTS)).toEqual({ template: 'ema', volume_mode: 'day', results_n: 10, limit: 5000 });
    expect(boardQuery({ ...SETUPS_DEFAULTS, tpl: 'sma', vg: 'avg20d', rn: '99' })).toMatchObject({ template: 'sma', volume_mode: 'avg20d', results_n: 10 });
  });

  it('highlights the whole row only when results fall within N sessions', () => {
    expect(rowHighlight(row({ results_soon: true }))).toBeTruthy();
    expect(rowHighlight(row({}))).toBeUndefined();
  });
});
