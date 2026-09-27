import { describe, expect, it } from 'vitest';
import {
  MOMENTUM_DEFAULTS,
  bucketChartsHref,
  bucketsTvFromRows,
  isDefaultState,
  momentumQuery,
  parseFlags,
  presetPatch,
  toggleFlag,
  type MomentumState,
} from './momentumModel';

const S = (patch: Partial<MomentumState> = {}): MomentumState => ({ ...MOMENTUM_DEFAULTS, ...patch });

describe('momentum model', () => {
  it('defaults are the old workspace defaults', () => {
    const q = momentumQuery(S());
    expect(q).toMatchObject({
      lookback_days: 20,
      min_mcap_cr: 1000,
      min_volume: 1_000_000,
      min_avg_volume_20d: 0,
      max_52w_away_pct: 25,
      min_52w_low_pct: 50,
      cmp_gt_10: true,
      cmp_gt_200: true,
      ohlc_gt_10: false,
      ohlc_gt_20: false,
      ema10_gt_20: true,
      ema20_gt_50: true,
      ema50_gt_100: true,
      ema100_gt_200: true,
      sma50_gt_150: false,
      sma200_rising: false,
      delivery_thrust: false,
      coiling_nr7: false,
      weekly_rsi_60: false,
    });
    expect(isDefaultState(S())).toBe(true);
  });

  it('volume gate is day OR 20D average OR off, never both', () => {
    expect(momentumQuery(S({ mvg: 'avg20d', mvol: '2500000' }))).toMatchObject({ min_volume: 0, min_avg_volume_20d: 2_500_000 });
    expect(momentumQuery(S({ mvg: 'off' }))).toMatchObject({ min_volume: 0, min_avg_volume_20d: 0 });
  });

  it('EMA stack and SMA template exclude each other', () => {
    expect([...parseFlags(toggleFlag('c10,ema', 'sma', true))].sort()).toEqual(['c10', 'sma']);
    expect([...parseFlags(toggleFlag('sma', 'ema', true))]).toEqual(['ema']);
  });

  it('preset buttons keep the old semantics (untouched filters stay)', () => {
    const st = S({ mf: 'c10,c200,ema,rsi', mlb: '5' });
    expect(presetPatch(st, 'breakouts')).toEqual({ mf: 'c10,c200,rsi', mhigh: '5', mlow: '50', mmcap: '1000' });
    expect(presetPatch(st, 'sma_template').mf).toBe('c10,c200,sma,rsi');
    expect(presetPatch(st, 'stage2').mf).toBe('c10,c200,ema,rsi');
    expect(presetPatch(st, 'coiling')).toMatchObject({ mhigh: '15' });
    expect(presetPatch(st, 'clear')).toEqual({ mf: '', mhigh: '99', mlow: '0', mmcap: '0', mvg: 'off' });
    const cleared = momentumQuery(S({ ...presetPatch(st, 'clear'), mlb: '5' } as Partial<MomentumState>));
    expect(cleared).toMatchObject({ lookback_days: 5, min_mcap_cr: 0, min_volume: 0, cmp_gt_10: false, ema10_gt_20: false });
  });

  it('buckets TradingView text has ###sections and TV symbol rules', () => {
    const rows = [
      { symbol: 'AAA', bucket: '0_2%' },
      { symbol: 'M-M', bucket: '0_2%' },
      { symbol: 'CCC', bucket: '5_10%' },
      { symbol: 'DDD', bucket: 'Below 10EMA' },
    ];
    expect(bucketsTvFromRows(rows)).toBe('###0_2%,NSE:AAA,NSE:M_M,###5_10%,NSE:CCC');
  });

  it('bucket charts link carries source, symbols and as_of', () => {
    expect(bucketChartsHref('10%+', ['A', null, 'B'], '2026-09-25')).toBe('/charts?source=momentum%3A10%25%2B&syms=A%2CB&as_of=2026-09-25');
  });
});
