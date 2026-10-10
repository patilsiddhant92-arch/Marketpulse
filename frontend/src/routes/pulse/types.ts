/** Row shapes served by /api/v2/pulse/* (App/services/pulse.py). The OpenAPI rows are untyped dicts. */

export type Lookback = 5 | 10 | 20 | 60 | 250;
export type Units = 'pct' | 'count';
export type EmaKey = 'e10' | 'e20' | 'e50' | 'e100' | 'e200';
export type N = number | null;

export interface CommentaryLine {
  kind: 'flag' | 'short' | 'medium' | 'ad' | 'turnover';
  lead: string | null;
  text: string;
}

export interface BreadthFlag {
  key: EmaKey;
  dir: 1 | -1;
  from: N;
  to: N;
  rel_pct: N;
  n_history?: number;
}

export interface SummaryRow {
  trade_date: string;
  lookback: number;
  ref_date: string;
  mood: number;
  mood_label: string;
  mood_tone: 'up' | 'warn' | 'down';
  qualifier: 'cooling' | 'improving' | null;
  qualifier_text: string | null;
  mood_change: N;
  mood_prev: N;
  mood_parts: { key: string; label: string; value: N; pctl: N }[];
  mood_parts_known: number;
  mood_series: { trade_date: string; mood: N }[];
  commentary: CommentaryLine[];
  action_rule: string | null;
  action: string | null;
  history_line: string | null;
  analogs_n: number;
  analogs_up_20d: number;
  e10_change: N;
  flags: BreadthFlag[];
  sessions_in_archive: number;
  archive_start: string;
  data_warning: string | null;
}

export interface BreadthCell {
  pct: N;
  count: N;
  chg: N;
  chg_count: N;
  rel_pct: N;
  sd60: N;
  z: N;
  unusual: boolean;
  intensity: number;
  flag: -1 | 0 | 1;
  pctl: N;
}

export type BreadthRow = { trade_date: string; stocks: N; gap_before: boolean } & Record<EmaKey, BreadthCell>;

export interface BreadthStat {
  key: EmaKey;
  label: string;
  min: N;
  max: N;
  p10: N;
  p90: N;
  today: N;
  today_count: N;
  lb_value: N;
  lb_count: N;
  delta: N;
  delta_count: N;
  pctl: N;
  xp_lo_pct: N;
  xp_hi_pct: N;
}

export interface BreadthContext {
  lookback: number;
  lb_date: string;
  archive_start: string;
  sessions_in_archive: number;
  stats: BreadthStat[];
  data_warning: string | null;
}

export interface InternalRow {
  key: string;
  label: string;
  unit: 'pct' | 'count' | 'index';
  good_direction: 1 | -1;
  meaning: string;
  value: N;
  lb_avg: N;
  change: N;
  pctl: N;
  history_sessions: number;
  series: { trade_date: string; value: N }[];
  data_warning: string | null;
}

export interface ExpansionRow {
  trade_date: string;
  is_today: boolean;
  dir: 1 | -1;
  signal: string;
  keys: EmaKey[];
  shown_key: EmaKey;
  from: N;
  to: N;
  rel_pct: N;
  fwd_10d_pct: N;
  fwd_20d_pct: N;
}

export interface ExpansionStat {
  key: EmaKey;
  label: string;
  expansions: { n: number; n_with_fwd: number; median_fwd_20d_pct: N; up_20d: number };
  contractions: { n: number; n_with_fwd: number; median_fwd_20d_pct: N; up_20d: number };
}

export interface FlowRow {
  trade_date: string;
  turnover_cr: N;
  delivered_cr: N;
  turnover_avg20_cr: N;
  delivery_share_pct: N;
  gap_before: boolean;
}

export interface SectorFlow {
  name: string;
  members: N;
  turnover_cr: N;
  share_pct: N;
  share_avg20_pct: N;
  share_delta: N;
  ret_1d_pct: N;
  ret_1w_pct: N;
  ret_1m_pct: N;
  ret_3m_pct: N;
}

export interface FlowContext {
  headline: {
    turnover_cr: N;
    turnover_avg20_cr: N;
    turnover_vs20_pct: N;
    delivered_cr: N;
    delivery_share_pct: N;
    delivery_share_avg20_pct: N;
  };
  sectors: SectorFlow[];
  data_warning: string | null;
}

export interface GroupRow {
  name: string;
  members: N;
  ret_1d_pct: N;
  ret_1w_pct: N;
  ret_1m_pct: N;
  ret_3m_pct: N;
  turnover_cr: N;
  share_pct: N;
  share_delta: N;
  delivered_cr: N;
  pct_above_50ema: N;
  rank: N;
  rank_n: N;
  rank_gain_1w: N;
  rrg_quadrant: string | null;
  days_in_quadrant: N;
  deal_net_10s_cr: N;
  share_history: N[];
}

export interface IndexRow {
  name: string;
  category: string;
  close: N;
  ret_1d_pct: N;
  ret_1w_pct: N;
  ret_1m_pct: N;
  ret_3m_pct: N;
  vs_20ema_pct: N;
  vs_50ema_pct: N;
  trend_state: string | null;
  new_52w_high: boolean;
  close_history: N[];
}

export type MoverKind = 'gainers' | 'losers' | 'turnover' | 'delivered' | 'rvol';
export type ChipCode = 'DEAL' | '52W' | 'IPO' | 'BAND' | 'EXT' | 'RES' | 'NEWS';

export interface MoverRow {
  symbol: string;
  name: string | null;
  sector: string | null;
  industry: string | null;
  close: N;
  chg_1d_pct: N;
  ret_1w_pct: N;
  ret_1m_pct: N;
  turnover_cr: N;
  rvol: N;
  delivered_cr: N;
  delivery_pct: N;
  delivery_vs_20d: N;
  rs_percentile: N;
  mcap_cr: N;
  mcap_basis: 'as_of' | 'latest';
  chips: ChipCode[];
  band_remark: string | null;
}

export interface AnalogRow {
  trade_date: string;
  e50: N;
  e50c5: N;
  e10: N;
  fwd_10d_pct: N;
  fwd_20d_pct: N;
}

export interface AnalogContext {
  today: { trade_date: string; e50: N; e50c5: N; e10: N };
  median_fwd_10d_pct: N;
  median_fwd_20d_pct: N;
  up_20d: number;
  k: number;
}
