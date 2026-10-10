/** §7 Money in the market: turnover chart + headline, sector treemap, rotation bars. All stocks. */
import { useState } from 'react';
import { DataWarningChip } from '../../ui/DataWarningChip';
import { Panel } from '../../ui/Panel';
import { Segmented } from '../groups/kit';
import type { PulseResult } from './data';
import { TREEMAP_SCALE, fixed, intIN, isNum, returnFill, shortDate, signed, squarify, toneClass, type TreemapPeriod } from './model';
import { Legend, Note, SectionBody } from './parts';
import type { FlowContext, FlowRow, SectorFlow } from './types';

function TurnoverBars({ rows }: { rows: FlowRow[] }) {
  const w = 560;
  const h = 200;
  const pl = 36;
  const pb = 18;
  const n = rows.length;
  const max = Math.max(...rows.map((r) => r.turnover_cr ?? 0), 1) * 1.08;
  const bw = (w - pl - 6) / Math.max(n, 1);
  const Y = (v: number) => h - pb - (v * (h - pb - 6)) / max;
  let avg = '';
  rows.forEach((r, i) => {
    if (isNum(r.turnover_avg20_cr)) avg += `${avg ? 'L' : 'M'}${(pl + i * bw + bw / 2).toFixed(1)},${Y(r.turnover_avg20_cr).toFixed(1)}`;
  });
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" role="img" aria-label="Market turnover and delivered value per session">
      {[0, 0.5, 1].map((f) => (
        <g key={f}>
          <line x1={pl} x2={w} y1={Y(max * f)} y2={Y(max * f)} className="stroke-line" />
          <text x={0} y={Y(max * f) + 3} fontSize={10} className="fill-fg-3">
            {Math.round((max * f) / 1000)}k
          </text>
        </g>
      ))}
      {rows.map((r, i) => {
        const x = pl + i * bw;
        const last = i === n - 1;
        return (
          <g key={r.trade_date}>
            <rect x={x + 1} y={Y(r.turnover_cr ?? 0)} width={Math.max(1, bw - 2)} height={h - pb - Y(r.turnover_cr ?? 0)} rx={2} className={last ? 'fill-info' : 'fill-surface-3'}>
              <title>{`${r.trade_date}: turnover ₹${intIN(r.turnover_cr)} Cr, delivered ₹${intIN(r.delivered_cr)} Cr${r.gap_before ? ' (after a data gap)' : ''}`}</title>
            </rect>
            <rect x={x + 1} y={Y(r.delivered_cr ?? 0)} width={Math.max(1, bw - 2)} height={h - pb - Y(r.delivered_cr ?? 0)} rx={2} className={last ? 'fill-info' : 'fill-line-strong'} fillOpacity={last ? 0.55 : 1} />
          </g>
        );
      })}
      <path d={avg} fill="none" stroke="rgb(var(--c-warn))" strokeWidth={1.5} strokeDasharray="4 3" />
      {[0, Math.floor(n / 2), n - 1].filter((i, k, a) => i >= 0 && a.indexOf(i) === k).map((i) => (
        <text key={i} x={Math.min(pl + i * bw - 8, w - 40)} y={h - 4} fontSize={10} className="fill-fg-3">
          {rows[i] ? shortDate(rows[i].trade_date) : ''}
        </text>
      ))}
    </svg>
  );
}

export function TurnoverPanel({ q }: { q: PulseResult<FlowRow, FlowContext> }) {
  const h = q.ctx?.headline;
  return (
    <Panel title="Money in the market" meta="NSE cash turnover, all stocks" actions={<DataWarningChip warning={q.ctx?.data_warning} />}>
      <SectionBody q={q} rows={4}>
        {h && (
          <div className="flex flex-wrap gap-6 px-3 pt-2">
            <div>
              <div className="mp-label">Turnover today</div>
              <div className="font-mono text-lg tabular-nums text-fg">₹{intIN(h.turnover_cr)} Cr</div>
              <div className={`text-2xs ${toneClass(h.turnover_vs20_pct)}`}>{signed(h.turnover_vs20_pct, 0)}% vs 20D avg</div>
            </div>
            <div>
              <div className="mp-label">Delivered value</div>
              <div className="font-mono text-lg tabular-nums text-fg">₹{intIN(h.delivered_cr)} Cr</div>
              <div className="text-2xs text-fg-3">
                {fixed(h.delivery_share_pct, 0)}% of turnover · 20D avg {fixed(h.delivery_share_avg20_pct, 0)}%
              </div>
            </div>
          </div>
        )}
        <div className="px-2 pt-1">
          <TurnoverBars rows={q.rows ?? []} />
        </div>
        <Legend
          items={[
            { name: 'turnover', colour: 'rgb(var(--c-surface-3))' },
            { name: 'delivered', colour: 'rgb(var(--c-line-strong))' },
            { name: '20-day average', colour: 'rgb(var(--c-warn))', dashed: true },
          ]}
        />
      </SectionBody>
    </Panel>
  );
}

const PERIODS = [
  { value: 'ret_1d_pct', label: '1D' },
  { value: 'ret_1w_pct', label: '1W' },
  { value: 'ret_1m_pct', label: '1M' },
  { value: 'ret_3m_pct', label: '3M' },
] as const;
const PERIOD_WORDS: Record<TreemapPeriod, string> = { ret_1d_pct: '1 day', ret_1w_pct: '1 week', ret_1m_pct: '1 month', ret_3m_pct: '3 months' };

export function SectorTreemap({ q }: { q: PulseResult<FlowRow, FlowContext> }) {
  const [period, setPeriod] = useState<TreemapPeriod>('ret_1d_pct');
  const sectors = [...(q.ctx?.sectors ?? [])].filter((s) => isNum(s.turnover_cr) && s.turnover_cr > 0).sort((a, b) => (b.turnover_cr ?? 0) - (a.turnover_cr ?? 0));
  const W = 600;
  const H = 300;
  const rects = squarify(sectors, (s) => s.turnover_cr ?? 0, W, H);
  const scale = TREEMAP_SCALE[period];
  return (
    <Panel
      title="Where turnover went"
      meta={`Box size = today's turnover · colour = return over ${PERIOD_WORDS[period]}`}
      actions={<Segmented label="Treemap period" size="xs" options={PERIODS} value={period} onChange={setPeriod} />}
    >
      <SectionBody q={q} rows={4} emptyTitle="No sector rows for this session">
        <div className="p-2">
          <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Sector turnover treemap">
            {rects.map(({ item, x, y, w, h }) => (
              <g key={item.name}>
                <rect x={x + 1} y={y + 1} width={Math.max(0, w - 2)} height={Math.max(0, h - 2)} rx={3} fill={returnFill(item[period], scale)}>
                  <title>{`${item.name}: ₹${intIN(item.turnover_cr)} Cr, ${signed(item[period], 1)}%`}</title>
                </rect>
                {w > 70 && h > 30 && (
                  <text x={x + 6} y={y + 16} fontSize={11} className="fill-fg">
                    <tspan fontWeight={600}>{item.name.length > w / 7 ? `${item.name.slice(0, Math.floor(w / 7) - 1)}…` : item.name}</tspan>
                    <tspan x={x + 6} dy={14} fontSize={10}>
                      {signed(item[period], 1)}% · ₹{intIN(item.turnover_cr)}
                    </tspan>
                  </text>
                )}
              </g>
            ))}
          </svg>
        </div>
      </SectionBody>
    </Panel>
  );
}

export function RotationBars({ q }: { q: PulseResult<FlowRow, FlowContext> }) {
  const rows: SectorFlow[] = (q.ctx?.sectors ?? []).filter((s) => isNum(s.share_delta));
  const max = Math.max(...rows.map((s) => Math.abs(s.share_delta ?? 0)), 0.01);
  return (
    <Panel title="Rotation" meta="Share of market turnover today minus its 20-day average share (points)">
      <SectionBody q={q} rows={6} emptyTitle="No sector rows for this session">
        <table className="w-full text-xs tabular-nums" aria-label="Sector rotation">
          <tbody>
            {rows.map((s) => {
              const pct = (Math.abs(s.share_delta ?? 0) / max) * 100;
              const pos = (s.share_delta ?? 0) > 0;
              return (
                <tr key={s.name} className="border-t border-line/40">
                  <td className="w-[34%] truncate px-2 py-0.5 text-fg-2">{s.name}</td>
                  <td className="w-[42%] px-1">
                    <div className="flex items-center">
                      <div className="flex w-1/2 justify-end">{!pos && <span className="h-2.5 rounded-l bg-down" style={{ width: `${pct}%` }} />}</div>
                      <div className="h-3.5 w-px bg-line-strong" />
                      <div className="w-1/2">{pos && <span className="block h-2.5 rounded-r bg-up" style={{ width: `${pct}%` }} />}</div>
                    </div>
                  </td>
                  <td className={`px-1 text-right ${toneClass(s.share_delta)}`}>{signed(s.share_delta, 2)} pts</td>
                  <td className="px-2 text-right text-fg-3">{fixed(s.share_pct, 1)}%</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <Note>Green = money moving in (share above its 20-day average). Red = money moving out. Last column: today&apos;s share.</Note>
      </SectionBody>
    </Panel>
  );
}
