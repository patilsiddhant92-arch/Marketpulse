/** Small building blocks shared by the Deals views (chips, TV copy, deal-candle chart). */
import { Check, ClipboardCopy } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { copyText } from '../../lib/clipboard';
import { fmtNum } from '../../lib/fmt';
import { cn } from '../../lib/cn';
import { tokenColor } from '../../lib/tokens';
import { Chip } from '../../ui/Chip';
import { SignedNum } from '../../ui/SignedNum';
import type { Candle, Grade, Marker, Side, Verdict } from './api';
import { chipTone, gradeTone, SIDE_COLOR, SIDE_LABEL, statusTone, tvListText, tvSectionsText, VERDICT_META, type TvList } from './model';

export function VerdictChip({ verdict, title }: { verdict: Verdict; title: string }) {
  const m = VERDICT_META[verdict];
  return (
    <Chip tone={m.tone} title={m.label}>
      {title}
    </Chip>
  );
}

export function StatusChip({ status, days }: { status: string | null; days?: number }) {
  if (!status) return <span className="text-fg-3">–</span>;
  return (
    <Chip tone={statusTone(status)} variant="outline">
      {status}
      {days != null && <span className="num ml-1 text-fg-3">{days}d</span>}
    </Chip>
  );
}

export function GradeChip({ grade, cls }: { grade: Grade; cls: string }) {
  if (cls !== 'FII' && cls !== 'DII') return <span className="text-2xs text-fg-3">no grade</span>;
  return (
    <Chip tone={gradeTone(grade)} variant="outline">
      {grade}
    </Chip>
  );
}

export function Chips({ chips }: { chips: readonly string[] }) {
  if (!chips.length) return <span className="text-fg-3">–</span>;
  return (
    <span className="flex flex-wrap gap-0.5">
      {chips.map((c) => (
        <Chip key={c} tone={chipTone(c)}>
          {c}
        </Chip>
      ))}
    </span>
  );
}

/** Deals signed number: the shared ui/SignedNum (same colours and NULL "—" as every tab). */
export function Signed({ value, digits = 1, pct = false }: { value: number | null | undefined; digits?: number; pct?: boolean }) {
  return <SignedNum value={value} format={pct ? 'signedPct' : 'signed'} digits={digits} />;
}

function useFlash() {
  const [msg, setMsg] = useState<string | null>(null);
  const flash = (m: string) => {
    setMsg(m);
    window.setTimeout(() => setMsg(null), 3000);
  };
  return { msg, flash };
}

const BTN = 'inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-xs text-fg-2 hover:bg-surface-3 disabled:opacity-50';

/** "Copy N to TradingView": the rows on screen (current filters and sort) as ###Title,NSE:SYM,... */
export function TvCopy({ list }: { list: TvList }) {
  const { msg, flash } = useFlash();
  const n = new Set(list.symbols).size;
  return (
    <span className="inline-flex items-center gap-1.5">
      <button
        type="button"
        className={BTN}
        disabled={!n}
        title={`Copy in TradingView watchlist format (###${list.title},NSE:SYM,…). Paste into Add symbol, or save as .txt for Import list.`}
        onClick={async () => {
          const { text, count } = tvListText(list);
          flash((await copyText(text)) ? `Copied ${count} symbols` : 'Copy failed');
        }}
      >
        <ClipboardCopy className="h-3.5 w-3.5" /> Copy {n} to TradingView
      </button>
      {msg && (
        <span role="status" className="inline-flex items-center gap-0.5 text-2xs text-up">
          <Check className="h-3 w-3" /> {msg}
        </span>
      )}
    </span>
  );
}

/** "Copy every list (sections)": one ### section per list on the tab. */
export function TvCopyAll({ lists }: { lists: readonly TvList[] }) {
  const { msg, flash } = useFlash();
  const live = lists.filter((l) => l.symbols.length > 0);
  if (live.length < 2) return null;
  return (
    <span className="inline-flex items-center gap-1.5">
      <button
        type="button"
        className={BTN}
        onClick={async () => {
          const { text, lists: k } = tvSectionsText(live);
          flash((await copyText(text)) ? `Copied ${k} lists` : 'Copy failed');
        }}
      >
        <ClipboardCopy className="h-3.5 w-3.5" /> Copy every list (sections)
      </button>
      {msg && (
        <span role="status" className="text-2xs text-up">
          {msg}
        </span>
      )}
    </span>
  );
}

export function Panel({ title, sub, actions, children }: { title: string; sub?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-card border border-line bg-surface shadow-card" aria-label={title}>
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-line px-3 py-2">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-fg">{title}</h2>
          {sub && <div className="mt-0.5 text-2xs text-fg-3">{sub}</div>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      <div className="min-h-0">{children}</div>
    </section>
  );
}

export function DoLine({ children }: { children: ReactNode }) {
  return <div className="rounded border border-line bg-surface-2 px-2 py-1.5 text-xs text-fg-2">{children}</div>;
}

export function NotesLine({ notes }: { notes: readonly string[] | null | undefined }) {
  if (!notes?.length) return null;
  return (
    <ul className="space-y-0.5 text-2xs text-fg-3" aria-label="Data notes">
      {notes.map((n) => (
        <li key={n}>{n}</li>
      ))}
    </ul>
  );
}

/** History cells: one square per deal session, oldest first, coloured by side. */
export function SessionCells({ cells, dates }: { cells: readonly (Side | null)[]; dates: readonly string[] }) {
  const narrow = cells.length > 10;
  return (
    <span className="inline-flex gap-0.5" aria-label="Deal sessions, oldest first">
      {cells.map((c, i) => (
        <span
          key={i}
          title={`${dates[i] ?? ''}${c ? ` · ${SIDE_LABEL[c]}` : ' · no deal'}`}
          className={cn('inline-block rounded-sm text-center font-bold leading-4 text-bg', narrow ? 'h-4 w-2.5 text-[8px]' : 'h-4 w-3.5 text-[9px]', !c && 'bg-surface-3')}
          style={c ? { background: SIDE_COLOR[c] } : undefined}
        >
          {c ?? ''}
        </span>
      ))}
    </span>
  );
}

/**
 * Deal-candle chart (mockup v1.1): the deal-day candle takes the deal's one colour plus its letter
 * (S below the bar, others above); dashed deal-price lines for the 3 latest buy / sell / placement deals.
 */
export function DealCandles({ candles, markers, lines, width = 460, height = 200 }: { candles: readonly Candle[]; markers: readonly Marker[]; lines: readonly Marker[]; width?: number; height?: number }) {
  const px = candles.filter((c) => c.open != null && c.high != null && c.low != null && c.close != null) as { date: string; open: number; high: number; low: number; close: number }[];
  if (!px.length) return <div className="p-3 text-2xs text-fg-3">No price history for this window.</div>;
  const levels = lines.map((l) => l.price).filter((v): v is number => v != null);
  const lo = Math.min(...px.map((p) => p.low), ...levels) * 0.99;
  const hi = Math.max(...px.map((p) => p.high), ...levels) * 1.01;
  const bw = (width - 44) / px.length;
  const Y = (v: number) => 12 + (height - 30) * (1 - (v - lo) / (hi - lo || 1));
  const mk = new Map(markers.map((m) => [m.date, m]));
  const used: number[] = [];
  return (
    <svg role="img" aria-label="Price with deal candles" viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ fontSize: 10 }}>
      {px.map((p, i) => {
        const X = 4 + i * bw + bw / 2;
        const m = mk.get(p.date);
        const tag = m?.side ?? null;
        const col = tag ? SIDE_COLOR[tag] : tokenColor(p.close >= p.open ? 'up' : 'down');
        const top = Math.min(Y(p.open), Y(p.close));
        return (
          <g key={p.date} data-deal={tag ?? undefined}>
            <line x1={X} x2={X} y1={Y(p.high)} y2={Y(p.low)} stroke={col} strokeWidth={1} />
            <rect x={X - bw * 0.35} y={top} width={bw * 0.7} height={Math.max(1, Math.abs(Y(p.open) - Y(p.close)))} fill={col} />
            {tag && (
              <text x={X} y={tag === 'S' ? Y(p.low) + 12 : Y(p.high) - 4} textAnchor="middle" fill={col} fontWeight={800}>
                {tag}
              </text>
            )}
          </g>
        );
      })}
      {lines.map((l) => {
        const i = px.findIndex((p) => p.date === l.date);
        if (i < 0 || l.price == null || !l.side) return null;
        const yy = Y(l.price);
        const label = used.every((u) => Math.abs(u - yy) > 10);
        if (label) used.push(yy);
        return (
          <g key={`${l.date}-${l.side}`}>
            <line x1={4 + i * bw} x2={width - 40} y1={yy} y2={yy} stroke={SIDE_COLOR[l.side]} strokeDasharray="4 3" strokeWidth={1.2} />
            {label && (
              <text x={width - 38} y={yy + 3} fill={SIDE_COLOR[l.side]}>
                {fmtNum(l.price, 1)}
              </text>
            )}
          </g>
        );
      })}
      <text x={4} y={height - 3} fill="currentColor" opacity={0.6}>
        {px[0].date}
      </text>
      <text x={width - 90} y={height - 3} fill="currentColor" opacity={0.6}>
        {px[px.length - 1].date}
      </text>
    </svg>
  );
}

export function CandleLegend() {
  return (
    <div className="flex flex-wrap gap-x-2 text-2xs text-fg-3">
      {(Object.keys(SIDE_LABEL) as Side[]).map((s) => (
        <span key={s}>
          <b style={{ color: SIDE_COLOR[s] }}>{s}</b> {SIDE_LABEL[s]}
        </span>
      ))}
      <span>· dashed line = deal price</span>
    </div>
  );
}
