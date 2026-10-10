/** Pulse data hooks: thin typed wrappers over useApiQuery for /api/v2/pulse/*. */
import { useApiQuery } from '../../api/query';
import type { EnvelopeMeta } from '../../api/types';
import type {
  AnalogContext,
  AnalogRow,
  BreadthContext,
  BreadthRow,
  ExpansionRow,
  ExpansionStat,
  FlowContext,
  FlowRow,
  GroupRow,
  IndexRow,
  InternalRow,
  Lookback,
  MoverKind,
  MoverRow,
  SummaryRow,
} from './types';

export interface PulseResult<Row, Ctx> {
  rows: Row[] | undefined;
  ctx: Ctx | undefined;
  meta: EnvelopeMeta | undefined;
  asOf: string | null;
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
  unavailable: boolean;
}

function wrap<Row, Ctx>(q: {
  data?: { rows: unknown[]; meta: EnvelopeMeta; as_of?: string | null } | undefined;
  isLoading: boolean;
  error: unknown;
  refetch: () => unknown;
}): PulseResult<Row, Ctx> {
  const meta = q.data?.meta;
  return {
    rows: q.data?.rows as Row[] | undefined,
    ctx: (meta?.context ?? undefined) as Ctx | undefined,
    meta,
    asOf: (q.data?.as_of as string | null | undefined) ?? null,
    isLoading: q.isLoading,
    error: q.error,
    refetch: () => void q.refetch(),
    unavailable: meta?.status === 'unavailable',
  };
}

const KEEP = { keepPrevious: true } as const;

export const useSummary = (lookback: Lookback) =>
  wrap<SummaryRow, { lookbacks: number[] }>(useApiQuery('pulse/summary', { query: { lookback } }, KEEP));

export const useBreadth = (lookback: Lookback) =>
  wrap<BreadthRow, BreadthContext>(useApiQuery('pulse/breadth', { query: { lookback } }, KEEP));

export const useInternals = (lookback: Lookback) =>
  wrap<InternalRow, { lookback: number }>(useApiQuery('pulse/internals', { query: { lookback } }, KEEP));

export const useExpansions = () =>
  wrap<ExpansionRow, { stats: ExpansionStat[]; total_days: number }>(useApiQuery('pulse/expansions', { query: { limit: 8 } }, KEEP));

export const useFlow = (lookback: Lookback) =>
  wrap<FlowRow, FlowContext>(useApiQuery('pulse/flow', { query: { lookback } }, KEEP));

export type GroupLevel = 'sector' | 'industry' | 'sectoral' | 'thematic';

export const useGroups = (level: GroupLevel) =>
  wrap<GroupRow | IndexRow, { level: string; data_warning?: string | null }>(useApiQuery('pulse/groups', { query: { level } }, KEEP));

export const useMovers = (kind: MoverKind) =>
  wrap<MoverRow, { universe_all: number; universe_floor: number; min_mcap_cr: number; chip_rules: Record<string, string> }>(
    useApiQuery('pulse/movers', { query: { kind } }, KEEP),
  );

export const useAnalogs = () => wrap<AnalogRow, AnalogContext>(useApiQuery('pulse/analogs', { query: { k: 8 } }, KEEP));
