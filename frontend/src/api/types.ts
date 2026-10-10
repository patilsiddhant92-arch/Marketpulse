/**
 * THE switch point for API types. All app code imports API types from here,
 * never from types.gen.ts directly.
 *
 * types.gen.ts is generated from frontend/openapi.json by `npm run gen:api`
 * (openapi-typescript). Re-run it whenever the API agent re-exports the
 * schema; this file maps the generated shapes onto stable app-facing names
 * and derives the endpoint map automatically from `paths`, so new endpoints
 * appear here with no hand typing.
 */
import type { components, paths } from './types.gen';

type Schemas = components['schemas'];

// ------------------------------------------------------------------ envelope

export type ISODate = string; // YYYY-MM-DD

export type Freshness = Schemas['Freshness'];
/** 'unknown' is client-side only (no health source answered). */
export type FreshnessStatus = Freshness['status'] | 'unknown';
export type EnvelopeMeta = Schemas['Meta'];
export type MetaStatus = NonNullable<EnvelopeMeta['status']>;

/** The v2 response envelope: {as_of, freshness, total, returned, rows, meta}. */
export interface Envelope<Row, Meta extends EnvelopeMeta = EnvelopeMeta> {
  as_of: ISODate | null;
  freshness: Freshness | null;
  /** Rows matching before paging (no silent caps). NULL when unknown. */
  total: number | null;
  returned: number;
  rows: Row[];
  meta: Meta;
}

// ------------------------------------------------------------------ rows (stable names)

export type RegimeRow = Schemas['RegimeRow'];
export type Pillar = Schemas['Pillar'];
export type Pillars = Schemas['Pillars'];
export type PillarKey = keyof Pillars;
export type MarketHealthRow = Schemas['MarketHealthRow'];
export type HealthResponse = Schemas['HealthResponse'];
export type HealthCheck = Schemas['HealthCheck'];
export type MetricDef = Schemas['MetricEntry'];
export type MetricZone = Schemas['MetricZone'];
export type QueueSummaryRow = Schemas['QueueSummaryRow'];
export type QueueRow = Schemas['QueueRow'];
export type DiffRow = Schemas['DiffRow'];
export type DeskWatchRow = Schemas['DeskWatchRow'];
export type PresetRow = Schemas['PresetRow'];
export type ScreenerRule = Schemas['Rule'];
export type ScreenerRow = Schemas['ScreenerRow'];
export type DebugRow = Schemas['DebugRow'];
export type MomentumRow = Schemas['MomentumRow'];
export type MomentumEvidenceRow = Schemas['MomentumEvidenceRow'];
export type GroupRow = Schemas['GroupRow'];
export type RrgRow = Schemas['RrgRow'];
export type MemberRow = Schemas['MemberRow'];
export type GroupIndexRow = Schemas['GroupIndexRow'];
export type GroupTreeRow = Schemas['GroupTreeRow'];
export type DealSessionRow = Schemas['DealSessionRow'];
export type HousePrintRow = Schemas['HousePrintRow'];
export type HouseRow = Schemas['HouseRow'];
export type DealPrintRow = Schemas['DealPrintRow'];
export type DealWindowRow = Schemas['DealWindowRow'];
export type DealLeaderRow = Schemas['DealLeaderRow'];
export type DealHolding = Schemas['DealHolding'];
export type DealStarRow = Schemas['DealStarRow'];
export type FollowThroughRow = Schemas['FollowThroughRow'];
export type StockHeaderRow = Schemas['StockHeaderRow'];
export type StockAdjustment = Schemas['Adjustment'];
export type BarRow = Schemas['BarRow'];
export type RsRow = Schemas['RsRow'];
export type DarvasRow = Schemas['DarvasRow'];
export type StockEventRow = Schemas['EventRow'];
export type StockDealRow = Schemas['StockDealRow'];
export type StockProfileRow = Schemas['StockProfileRow'];
export type PeerRow = Schemas['PeerRow'];
export type AccumulatorRow = Schemas['AccumulatorRow'];
export type StockAnalogRow = Schemas['StockAnalogRow'];
export type EvidenceRow = Schemas['EvidenceRow'];
export type MarketAnalogRow = Schemas['MarketAnalogRow'];
export type BigMoveRow = Schemas['BigMoveRow'];
export type PreMoveRow = Schemas['PreMoveRow'];
export type WatchlistItem = Schemas['WatchlistItem'];
export type WatchlistPut = Schemas['WatchlistPut'];
export type Note = Schemas['Note'];
export type NotePut = Schemas['NotePut'];
export type TodayMarketRow = Schemas['TodayMarketRow'];
export type TodayIndex = Schemas['TodayIndex'];
/** Columns shared by movers and breakouts. */
export type TodayStockRow = Omit<Schemas['TodayMoverRow'], 'side' | 'rank'>;
export type TodayMoverRow = Schemas['TodayMoverRow'];
export type TodayBreakoutRow = Schemas['TodayBreakoutRow'];
export type TodayGroupRow = Schemas['TodayGroupRow'];
export type TodayContributor = Schemas['TodayContributor'];
export type TodayEvent = Schemas['TodayEvent'];
export type GroupContext = Schemas['GroupContext'];
export type StockContextRow = Schemas['StockContextRow'];
export type ContextSetup = Schemas['ContextSetup'];
export type WhyBullet = Schemas['WhyBullet'];
export type CompareRow = Schemas['CompareRow'];
export type RotationRow = Schemas['RotationRow'];
export type RotationCell = Schemas['RotationCell'];
// Setups tab (/api/v2/setups/*)
export type SetupBoardRow = Schemas['SetupBoardRow'];
export type SetupNearMissRow = Schemas['SetupNearMissRow'];
export type DivergenceRow = Schemas['DivergenceRow'];
export type DivergenceScanRow = Schemas['DivergenceScanRow'];
export type SetupDroppedRow = Schemas['SetupDroppedRow'];

/** Verdict words (spec 6.1.1). The schema types verdict as string; UI narrows. */
export type Verdict = 'Favourable' | 'Constructive' | 'Mixed' | 'Weak' | 'Danger';
export type PillarStatus = 'Healthy' | 'Neutral' | 'Weak';
export type Direction = 'up' | 'down' | 'flat';
/** Dictionary zone tones as served (metric_dictionary.yaml). */
export type ZoneTone = 'good' | 'neutral' | 'caution' | 'bad';
/** UI tone vocabulary. */
export type Tone = 'positive' | 'negative' | 'neutral' | 'warn' | 'info';

// ------------------------------------------------------------------ endpoint map (derived)

type JsonOf<R> = R extends { content: { 'application/json': infer J } } ? J : never;
type GetOp<P extends keyof paths> = paths[P] extends { get: infer G } ? G : never;
type Ok<P extends keyof paths> = GetOp<P> extends { responses: { 200: infer R } } ? JsonOf<R> : never;
type QueryOf<P extends keyof paths> =
  GetOp<P> extends { parameters: { query?: infer Q } }
    ? Q extends undefined
      ? Record<string, never>
      : NonNullable<Q>
    : Record<string, never>;

/** '/api/v2/stock/{sym}/bars' -> 'stock/{sym}/bars', envelope endpoints only. */
type EnvelopePaths = {
  [P in keyof paths]: P extends `/api/v2/${infer K}` ? (Ok<P> extends { rows: unknown[] } ? K : never) : never;
}[keyof paths];

type FullPath<K extends string> = `/api/v2/${K}` & keyof paths;

/** Path template -> query params, row type and meta type (generated). */
export type EndpointMap = {
  [K in EnvelopePaths]: {
    query: QueryOf<FullPath<K>>;
    row: Ok<FullPath<K>> extends { rows: (infer R)[] } ? R : never;
    meta: EnvelopeMeta;
  };
};

export type EndpointPath = keyof EndpointMap;
