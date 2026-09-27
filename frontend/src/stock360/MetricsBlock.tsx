import type { StockHeaderRow } from '../api/types';
import { cn } from '../lib/cn';
import { fmtNum, fmtRatio, fmtSignedPct, isNum } from '../lib/fmt';
import { Chip } from '../ui/Chip';
import { Metric } from '../ui/Metric';
import { Panel } from '../ui/Panel';
import { Spark } from '../ui/Spark';
import { Tooltip } from '../ui/Tooltip';

function Plain({ label, value, title, tone }: { label: string; value: string; title?: string; tone?: 'up' | 'down' | 'muted' }) {
  const body = (
    <span className="inline-flex flex-col gap-0.5" tabIndex={title ? 0 : undefined}>
      <span className="text-2xs uppercase tracking-wide text-fg-3">{label}</span>
      <span className={cn('num text-xs font-medium', tone === 'up' ? 'text-up' : tone === 'down' ? 'text-down' : tone === 'muted' ? 'text-fg-3' : 'text-fg')}>
        {value}
      </span>
    </span>
  );
  return title ? <Tooltip content={title}>{body}</Tooltip> : body;
}

const signTone = (v: number | null | undefined) => (!isNum(v) ? 'muted' : v >= 0 ? 'up' : 'down');

/** Close vs each EMA: above/below chips (NULL EMA = no chip). */
function EmaStack({ s }: { s: StockHeaderRow }) {
  const emas: [string, number | null | undefined][] = [
    ['10', s.ema_10],
    ['20', s.ema_20],
    ['50', s.ema_50],
    ['200', s.ema_200],
  ];
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="text-2xs uppercase tracking-wide text-fg-3">Close vs EMA</span>
      {emas.map(([p, v]) =>
        v == null || s.close == null ? (
          <Chip key={p} title="EMA not available">
            {p} —
          </Chip>
        ) : (
          <Chip key={p} tone={s.close >= v ? 'positive' : 'negative'} title={`EMA ${p} = ${fmtNum(v)} (${fmtSignedPct((s.close / v - 1) * 100, 1)})`}>
            {s.close >= v ? '▲' : '▼'} {p}
          </Chip>
        ),
      )}
    </div>
  );
}

export function StrengthBlock({ s, className }: { s: StockHeaderRow; className?: string }) {
  const hist = [s.rs_rank_t30, s.rs_rank_t15, s.rs_rank_t5, s.rs_percentile];
  return (
    <Panel title="Strength" meta="rank vs all stocks · excess return vs benchmarks" className={className} bodyClassName="space-y-2 p-3">
      <div className="flex flex-wrap items-end gap-x-5 gap-y-2">
        <Metric metricKey="rs_percentile" label="Strength rank" value={s.rs_percentile} format="num" digits={0} size="lg" delta={s.rs_delta_5} deltaFormat="signed" />
        <Tooltip content="Strength rank 30, 15 and 5 sessions ago, then today">
          <span className="inline-flex flex-col gap-0.5" tabIndex={0}>
            <span className="text-2xs uppercase tracking-wide text-fg-3">T-30 → today</span>
            <span className="flex items-center gap-2">
              <Spark values={hist} label="Strength rank T-30, T-15, T-5, today" width={64} height={18} />
              <span className="num text-2xs text-fg-2">{hist.map((v) => fmtNum(v, 0)).join(' → ')}</span>
            </span>
          </span>
        </Tooltip>
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-2">
        <Metric metricKey="excess_vs_midsml400_63d" label="vs MidSml400 63d" value={s.excess_vs_midsml400_63d} format="signedPct" size="sm" />
        <Metric metricKey="excess_vs_nifty50_63d" label="vs Nifty 63d" value={s.excess_vs_nifty50_63d} format="signedPct" size="sm" />
        <Metric metricKey="excess_vs_nifty50_21d" label="vs Nifty 21d" value={s.excess_vs_nifty50_21d} format="signedPct" size="sm" />
        <Metric
          metricKey="rs_vs_sector_index_63d"
          value={s.rs_vs_sector_index_63d}
          format="signedPct"
          size="sm"
          label={s.sector_index_name ? `vs ${s.sector_index_name} 63d` : undefined}
        />
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-2">
        <Plain label="1M" value={fmtSignedPct(s.return_1m_pct, 1)} tone={signTone(s.return_1m_pct)} title="Price return, 1 month" />
        <Plain label="3M" value={fmtSignedPct(s.return_3m_pct, 1)} tone={signTone(s.return_3m_pct)} title="Price return, 3 months" />
        <Plain label="6M" value={fmtSignedPct(s.return_6m_pct, 1)} tone={signTone(s.return_6m_pct)} title="Price return, 6 months" />
      </div>
    </Panel>
  );
}

export function TrendBlock({ s, className }: { s: StockHeaderRow; className?: string }) {
  return (
    <Panel title="Trend & activity" className={className} bodyClassName="space-y-2 p-3">
      <div className="flex flex-wrap gap-x-5 gap-y-2">
        <Metric metricKey="trend_template_pass_n" value={s.trend_template_pass_n} format="int" size="sm" label="Trend template /8" />
        <Metric metricKey="away_52w_high_pct" label="Below 52W high" value={s.away_52w_high_pct == null ? null : Math.abs(s.away_52w_high_pct)} format="pct" size="sm" />
        <Metric metricKey="away_52w_low_pct" label="Above 52W low" value={s.away_52w_low_pct} format="pct" size="sm" />
        <Metric metricKey="adr_20_pct" label="ADR 20d" value={s.adr_20_pct} format="pct" digits={2} size="sm" />
      </div>
      <EmaStack s={s} />
      <div className="flex flex-wrap gap-x-5 gap-y-2">
        <Metric metricKey="rvol" label="RVOL" value={s.rvol} format="ratio" size="sm" />
        <Metric metricKey="delivery_pct" label="Delivery" value={s.delivery_pct} format="pct" size="sm" />
        <Plain
          label="Delivery vs 20d"
          value={s.delivery_vs_20d == null ? '—' : fmtRatio(s.delivery_vs_20d)}
          title="Today's delivery % divided by its 20-day average (1.00× = usual)."
          tone={s.delivery_vs_20d == null ? 'muted' : undefined}
        />
        <Metric metricKey="adv_cr_20d" label="Avg traded value 20d" value={s.adv_cr_20d} format="cr" size="sm" />
      </div>
    </Panel>
  );
}

export function DeliveryBlock({ values, className }: { values: readonly (number | null)[]; className?: string }) {
  const nums = values.filter(isNum);
  const avg = nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null;
  const last = values.length ? values[values.length - 1] : null;
  return (
    <Panel title="Delivery %" meta={`${values.length} sessions`} className={className} bodyClassName="flex items-center gap-4 px-3 py-2">
      {nums.length > 1 ? (
        <>
          <Spark values={values} label={`Delivery %, last ${values.length} sessions`} width={200} height={36} tone="accent" baseline={avg ?? undefined} />
          <div className="num space-y-0.5 text-2xs text-fg-3">
            <div>
              last <span className="text-fg">{fmtNum(last, 1)}%</span>
            </div>
            <div>
              avg <span className="text-fg">{fmtNum(avg, 1)}%</span>
            </div>
          </div>
        </>
      ) : (
        <span className="text-2xs text-fg-3">No delivery history (BE/BZ series or new listing).</span>
      )}
    </Panel>
  );
}
