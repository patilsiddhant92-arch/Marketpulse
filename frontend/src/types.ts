export interface ExposureGate {
  band: string | null;
  band_low: number | null;
  band_high: number | null;
  recommended_pct: number | null;
  state: string | null;
  badge: string | null;
  guidance: string | null;
  is_actionable: boolean;
  execution_playbook?: string;
  action_bias?: string;
  max_position_size?: string;
  risk_per_trade?: string;
}

export interface VixData {
  current: number;
  change_1d_pct: number;
  tone: string;
}

export interface MarketTape {
  total_stocks: number;
  advancers: number;
  decliners: number;
  unchanged: number;
  net_advancers: number;
  advance_pct: number;
  advance_volume_pct: number;
  breadth_state: string;
}

export interface MarketBreadth {
  above_20_ema_pct: number;
  above_50_ema_pct: number;
  above_200_ema_pct: number;
  advancers_pct: number;
  highs_52w: number;
  lows_52w: number;
  net_highs: number;
  near_52w_highs?: number;
  above_50ema_5d_change?: number;
  above_200ema_20d_change?: number;
}

export interface LeadingTheme {
  name: string;
  rs_percentile: number;
  return_5d_pct: number;
  leaders: string[];
  state: string;
}

export interface MarketRegimeResponse {
  as_of: string;
  exposure_gate: ExposureGate;
  vix: VixData;
  tape?: MarketTape;
  breadth: MarketBreadth;
  leading_themes: LeadingTheme[];
  setups_summary?: {
    stage2_pool_count: number;
  };
}

export interface CandidateSetup {
  symbol: string;
  sector: string;
  queue: string;
  cmp: number;
  change_1d_pct: number;
  pattern_state: string;
  rvol: number;
  dist_to_pivot_pct: number;
  risk_pct: number;
  reward_to_risk: number;
  trigger_price: number;
  invalidation_price: number;
  mcap_cr: number;
  why_now: string;
  rs_percentile: number;
  delivery_pct: number;
  theme?: string;
  deal_flow?: string;
  squeeze_pct?: number;
}

export interface SectorLeaderSummary {
  sector: string;
  stock_count: number;
  avg_rs: number;
  symbols: string[];
  tv_str: string;
}

export interface IndustryLeaderSummary {
  industry: string;
  sector: string;
  stock_count: number;
  avg_rs: number;
  symbols: string[];
  tv_str: string;
}

export interface MomentumCandidate {
  symbol: string;
  sector: string;
  industry?: string;
  cmp: number;
  change_1d_pct: number;
  return_5d_pct: number;
  return_1m_pct: number;
  return_3m_pct: number;
  rs_percentile: number;
  away_10ema_pct: number;
  bucket: string;
  dist_52w_high_pct: number;
  dist_52w_low_pct: number;
  volume?: number;
  avg_volume_20d?: number;
  rvol: number;
  delivery_pct: number;
  mcap_cr: number;
  bullish_stack: boolean;
  delivery_spike?: boolean;
  coiling?: boolean;
  trigger_date?: string;
}

export interface VcpCandidate {
  symbol: string;
  cmp: number;
  wave_sequence: string;
  vdu_ratio: number;
  vdu_confirmed: boolean;
  pivot_entry: number;
  stop_loss: number;
  risk_pct: number;
  dist_to_pivot_pct: number;
  suggested_shares_for_10k_risk: number;
  suggested_shares_for_25k_risk: number;
  suggested_shares_for_50k_risk: number;
  rs_percentile?: number;
  sector?: string;
}

export interface TierDealRecord {
  symbol: string;
  deal_days: number;
  clientele: string;
  net_cr: number;
  buy_cr: number;
  sell_cr: number;
  transfer_cr?: number;
  n_houses?: number;
  size_vs_adv?: number | null;
  play_reason?: string;
  close_price: number;
  ema_200: number;
  trend: string;
  away_52w_high_pct: number;
  rs_percentile: number;
  market_cap_cr: number;
  sector: string;
}

export interface FundHolding {
  fund_house: string;
  symbol: string;
  buy_cr: number;
  sell_cr: number;
  net_cr: number;
  prints: number;
  last_date: string;
  last_side: string;
  last_price?: number | null;
  cmp?: number | null;
  ret_pct?: number | null;
  mcap_cr?: number | null;
  sector?: string;
}

export interface FundLeaderboardRecord {
  fund_house: string;
  tier: string;
  catalyst_score: number;
  win_rate_20d: number;
  avg_runup: number;
  bets_count: number;
  names_count?: number;
  total_cr?: number;
  net_long_count?: number;
  holdings?: FundHolding[];
}

export interface TodayDealRecord {
  symbol: string;
  client_name: string;
  fund_house: string;
  side: string;
  price: number;
  deal_cr: number;
  clientele: string;
  is_prop: boolean;
  mcap_cr: number;
  sector: string;
  trade_date: string;
}

export interface StarRadarDeal {
  symbol: string;
  fund_house: string;
  tier: string;
  win_rate: number;
  deal_date: string;
  deal_price: number;
  cmp: number;
  gain_pct: number;
  peak_runup: number;
  holding_days: number;
  deal_cr: number;
}

export interface DealsDeskResponse {
  as_of: string;
  lookback_days: number;
  counts: {
    play?: number;
    conviction: number;
    fresh_radar: number;
    transfer?: number;
    four_plus_days: number;
    three_days: number;
    two_days: number;
    prop_only: number;
    quarantined: number;
    distribution: number;
    star_deals: number;
    funds: number;
    today?: number;
  };
  play?: TierDealRecord[];
  conviction: TierDealRecord[];
  fresh_radar: TierDealRecord[];
  transfer?: TierDealRecord[];
  prop_only: TierDealRecord[];
  quarantined: TierDealRecord[];
  distribution: TierDealRecord[];
  star_radar: StarRadarDeal[];
  fund_leaderboard: FundLeaderboardRecord[];
  today_deals?: TodayDealRecord[];
  tv_strings: Record<string, string>;
}

export interface SectorLeaderChip {
  symbol: string;
  rs_percentile: number;
  change_1d_pct: number;
}

export interface SectorRecord {
  sector: string;
  total_stocks?: number;
  stage2_count?: number;
  stage2_percentage?: number;
  median_rs?: number;
  return_5d_pct: number;
  return_20d_pct: number;
  return_63d_pct: number;
  horizon_return_pct?: number;
  rs_percentile: number;
  advancers_pct: number;
  above_10_ema_pct: number;
  above_50_ema_pct: number;
  above_200_ema_pct: number;
  near_52w_highs: number;
  rotation_state: string;
  rotation_rank: number;
  turnover_1d_cr: number;
  turnover_share_pct?: number;
  turnover_share_delta_1d?: number;
  turnover_share_delta_5d?: number;
  turnover_expansion: string;
  divergence_status: string;
  inflow_streak?: number;
  leaders: string[];
  leader_chips?: SectorLeaderChip[];
  tile_symbols?: string[];
  lookback_days?: number;
}

export interface HistoricalBreadthRecord {
  trade_date: string;
  stocks: number;
  advancers: number;
  decliners: number;
  advance_pct: number;
  advance_pct_5d_avg: number;
  above_20ema_pct: number;
  above_50ema_pct: number;
  above_200ema_pct: number;
  near_52w_highs: number;
  breadth_state: string;
  turnover_cr: number;
}

export interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ema10: number;
  ema20: number;
  ema50: number;
  ema200: number;
  sma50?: number;
  sma150?: number;
  sma200?: number;
  darvas_top: number;
  darvas_bottom: number;
}

export interface DealMarker {
  time: string;
  position: 'aboveBar' | 'belowBar';
  color: string;
  shape: 'circle' | 'arrowUp' | 'arrowDown';
  text: string;
  net_cr?: number;
  total_cr?: number;
  deal_count?: number;
}

export interface MinerviniTemplateCriteria {
  cmp_above_150_200_sma: boolean;
  sma_150_above_200: boolean;
  sma_200_rising: boolean;
  sma_50_above_150_200: boolean;
  cmp_above_50_sma: boolean;
  within_25pct_52w_high: boolean;
  above_30pct_52w_low: boolean;
  rs_above_70: boolean;
}

export interface MinerviniTemplate {
  score: number;
  total: number;
  passes_template: boolean;
  criteria: MinerviniTemplateCriteria;
}

export interface VcpContraction {
  label: string;
  start_date: string;
  end_date: string;
  depth_pct: number;
  peak_price: number;
  trough_price: number;
}

export interface VcpGeometry {
  pivot: number | null;
  stop: number | null;
  contractions: VcpContraction[];
}

export interface DarvasFutureBar {
  time: string;
  top: number;
  bottom: number;
  ema10?: number;
}

export interface PeerInfo {
  target_rank: number;
  total_peers: number;
  industry: string;
  sector: string;
  rs_percentile: number;
  is_leader: boolean;
}

export interface InstitutionalFootprint {
  turnover_cr: number;
  avg_turnover_20d_cr: number;
  avg_turnover_50d_cr: number;
  turnover_expansion_pct: number;
  delivery_pct: number;
  avg_delivery_pct_20d: number;
  delivery_ratio: number;
  delivery_spike: boolean;
  price_up_delivery_up: boolean;
  is_nr7: boolean;
  ticket_ratio: number;
  is_whale_ticket: boolean;
  rvol_trail_5d: number[];
  deliv_trail_5d: number[];
  day_pct_trail_5d: number[];
}

export interface ChartResponse {
  symbol: string;
  latest_darvas_top: number;
  latest_darvas_bottom: number;
  latest_ema10?: number;
  is_darvas_squeeze: boolean;
  squeeze_pct: number;
  minervini_template: MinerviniTemplate;
  vcp_geometry: VcpGeometry;
  candles: Candle[];
  deal_markers: DealMarker[];
  darvas_future?: DarvasFutureBar[];
  peer_info?: PeerInfo;
  institutional_footprint?: InstitutionalFootprint;
}

export interface PeerStock {
  symbol: string;
  security_name: string;
  industry: string;
  sector: string;
  market_cap_cr: number;
  close_price: number;
  day_pct: number;
  rs_percentile: number;
  away_10ema_pct: number;
  away_52w_pct: number;
  rvol: number;
  delivery_pct: number;
  vcp_state: string;
  rs_rank: number;
}

export interface BetterOption {
  symbol: string;
  security_name: string;
  rs_percentile: number;
  away_10ema_pct: number;
  away_52w_pct: number;
  rvol: number;
  day_pct: number;
  close_price: number;
  rank: number;
  reason: string;
}

export interface PeerComparisonResponse {
  target: PeerStock;
  group_type: 'Industry' | 'Sector';
  group_name: string;
  sector: string;
  industry: string;
  target_rank: number;
  total_peers: number;
  is_leader: boolean;
  better_options: BetterOption[];
  peers: PeerStock[];
  tv_copy_str: string;
}

export interface SectorRotationResponse {
  total_count: number;
  filtered_count: number;
  state_counts: Record<string, number>;
  sectors: SectorRecord[];
}

export interface CapitalFlowGroup {
  group_name: string;
  level: string;
  turnover_cr: number;
  turnover_share_pct: number;
  turnover_share_delta_1d: number;
  turnover_share_delta_5d: number;
  turnover_share_delta_21d?: number;
  return_5d_pct: number;
  return_1m_pct: number;
  return_3m_pct: number;
  above_200_ema_pct: number;
  rotation_state: string;
  deal_net_cr?: number;
  leaders: string[];
  liquid_names?: number;
}

export interface StockAccumulator {
  symbol: string;
  security_name: string;
  sector: string;
  industry: string;
  cmp: number;
  mcap_cr?: number;
  day_pct: number;
  turnover_cr: number;
  turnover_expansion_pct: number;
  delivery_ratio: number;
  delivery_pct: number;
  rs_percentile: number;
  ticket_ratio: number;
  is_whale: boolean;
  deliv_spike: boolean;
  acc_vol: boolean;
}

export interface CapitalFlowResponse {
  as_of: string;
  universe?: {
    min_mcap_cr: number;
    min_adv_cr: number;
    min_price: number;
    stock_count: number;
  };
  top_inflows_1d: CapitalFlowGroup[];
  top_outflows_1d: CapitalFlowGroup[];
  top_inflows_5d: CapitalFlowGroup[];
  top_outflows_5d: CapitalFlowGroup[];
  top_inflows_1m: CapitalFlowGroup[];
  top_outflows_1m: CapitalFlowGroup[];
  stock_accumulators: StockAccumulator[];
}

