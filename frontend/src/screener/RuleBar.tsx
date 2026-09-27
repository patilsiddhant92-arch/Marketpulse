/**
 * Applied rules as editable chips (spec 7.3): click a chip to change its field /
 * operator / value, x to remove, "+ Rule" to add. Editing a preset turns the run
 * into a custom run; "Reset" restores the preset's rules.
 */
import { Plus, RotateCcw, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { cn } from '../lib/cn';
import { useEscapeLayer } from '../lib/layers';
import { useMetric } from '../metrics/dictionary';
import { MetricTooltipBody } from '../ui/MetricTooltip';
import { Tooltip } from '../ui/Tooltip';
import { NUM_OPS, OP_SYMBOL, isBoolOp, ruleComplete, ruleLabel, type NumOp, type Rule, type RuleField } from './model';

export interface RuleBarProps {
  rules: Rule[];
  fields: RuleField[];
  custom: boolean;
  disabled?: boolean;
  disabledNote?: string;
  onChange: (rules: Rule[]) => void;
  onReset: () => void;
}

export function RuleBar({ rules, fields, custom, disabled, disabledNote, onChange, onReset }: RuleBarProps) {
  const byKey = new Map(fields.map((f) => [f.field, f]));
  const [editing, setEditing] = useState<number | 'new' | null>(null);

  return (
    <div className="flex min-h-8 flex-wrap items-center gap-1.5 border-b border-line bg-surface px-3 py-1">
      <span className="text-2xs font-semibold uppercase tracking-wide text-fg-3">Rules</span>
      {disabled ? (
        <span className="min-w-0 flex-1 truncate text-xs text-fg-3" title={disabledNote}>
          {disabledNote}
        </span>
      ) : (
        <>
          {rules.length === 0 && <span className="text-xs text-fg-3">No rules — every stock passing the floors matches.</span>}
          {rules.map((r, i) => (
            <div key={`${i}-${r.field}`} className="relative">
              <RuleChip
                rule={r}
                label={ruleLabel(r, byKey)}
                field={byKey.get(r.field)}
                onEdit={() => setEditing(i)}
                onRemove={() => onChange(rules.filter((_, j) => j !== i))}
              />
              {editing === i && (
                <RuleEditor
                  initial={r}
                  fields={fields}
                  onCancel={() => setEditing(null)}
                  onApply={(next) => {
                    onChange(rules.map((x, j) => (j === i ? next : x)));
                    setEditing(null);
                  }}
                />
              )}
            </div>
          ))}
          <div className="relative">
            <button
              type="button"
              onClick={() => setEditing('new')}
              className="flex items-center gap-1 rounded border border-dashed border-line-strong px-1.5 py-0.5 text-xs text-fg-3 hover:border-accent hover:text-accent"
            >
              <Plus className="h-3 w-3" /> Rule
            </button>
            {editing === 'new' && (
              <RuleEditor
                initial={{ field: 'rs_percentile', op: 'gte', value: 70 }}
                fields={fields}
                onCancel={() => setEditing(null)}
                onApply={(next) => {
                  onChange([...rules, next]);
                  setEditing(null);
                }}
              />
            )}
          </div>
          {custom && (
            <>
              <span className="rounded bg-warn/10 px-1.5 py-px text-2xs font-semibold uppercase text-warn">Custom</span>
              <button type="button" onClick={onReset} className="flex items-center gap-1 text-xs text-fg-3 hover:text-fg">
                <RotateCcw className="h-3 w-3" /> Reset to preset
              </button>
            </>
          )}
          <span className="ml-auto text-2xs text-fg-3">Fail-closed: a missing input fails its rule.</span>
        </>
      )}
    </div>
  );
}

function RuleChip({
  rule,
  label,
  field,
  onEdit,
  onRemove,
}: {
  rule: Rule;
  label: string;
  field: RuleField | undefined;
  onEdit: () => void;
  onRemove: () => void;
}) {
  const { def } = useMetric(field?.metric_key ?? undefined);
  const body = (
    <button type="button" onClick={onEdit} className="px-1.5 py-0.5 text-xs text-fg hover:text-accent">
      {label}
    </button>
  );
  return (
    <span
      className={cn(
        'inline-flex items-center rounded border bg-surface-2',
        isBoolOp(rule.op) ? 'border-info/30' : 'border-accent/30',
      )}
    >
      {field?.metric_key ? (
        <Tooltip content={<MetricTooltipBody def={def} metricKey={field.metric_key} />}>{body}</Tooltip>
      ) : (
        body
      )}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove rule ${label}`}
        className="border-l border-line px-1 py-0.5 text-fg-3 hover:text-down"
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}

function RuleEditor({
  initial,
  fields,
  onApply,
  onCancel,
}: {
  initial: Rule;
  fields: RuleField[];
  onApply: (r: Rule) => void;
  onCancel: () => void;
}) {
  const [rule, setRule] = useState<Rule>(initial);
  const [rhsMode, setRhsMode] = useState<'value' | 'ref'>(initial.ref ? 'ref' : 'value');
  const ref = useRef<HTMLDivElement>(null);
  useEscapeLayer(true, onCancel);
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onCancel();
    };
    window.addEventListener('mousedown', onDown);
    return () => window.removeEventListener('mousedown', onDown);
  }, [onCancel]);

  const field = fields.find((f) => f.field === rule.field);
  const isBool = field?.kind === 'bool';
  const numFields = fields.filter((f) => f.kind === 'num');
  const finalRule: Rule = isBool
    ? { field: rule.field, op: isBoolOp(rule.op) ? rule.op : 'is_true' }
    : rhsMode === 'ref'
      ? { field: rule.field, op: isBoolOp(rule.op) ? 'gte' : rule.op, ref: rule.ref ?? 'ema_200' }
      : { field: rule.field, op: isBoolOp(rule.op) ? 'gte' : rule.op, value: rule.value ?? null };
  const valid = ruleComplete(finalRule);
  const input = 'rounded border border-line bg-surface-2 px-1.5 py-0.5 text-xs text-fg focus:border-accent focus:outline-none';

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label="Edit rule"
      className="absolute left-0 top-full z-40 mt-1 w-[300px] space-y-2 rounded-md border border-line-strong bg-surface-2 p-2 shadow-2xl"
      onKeyDown={(e) => {
        if (e.key === 'Enter' && valid) onApply(finalRule);
      }}
    >
      <label className="block text-2xs text-fg-3">
        Field
        <select className={cn(input, 'mt-0.5 w-full')} value={rule.field} onChange={(e) => setRule({ ...rule, field: e.target.value })}>
          <optgroup label="Numbers">
            {numFields.map((f) => (
              <option key={f.field} value={f.field}>
                {f.label}
              </option>
            ))}
          </optgroup>
          <optgroup label="Yes / no">
            {fields
              .filter((f) => f.kind === 'bool')
              .map((f) => (
                <option key={f.field} value={f.field}>
                  {f.label}
                </option>
              ))}
          </optgroup>
        </select>
      </label>
      {isBool ? (
        <div className="flex gap-1">
          {(['is_true', 'is_false'] as const).map((op) => (
            <button
              key={op}
              type="button"
              onClick={() => setRule({ ...rule, op })}
              className={cn(
                'flex-1 rounded border px-2 py-0.5 text-xs',
                (isBoolOp(rule.op) ? rule.op : 'is_true') === op ? 'border-accent bg-accent/10 text-accent' : 'border-line text-fg-2',
              )}
            >
              {op === 'is_true' ? 'is true' : 'is false'}
            </button>
          ))}
        </div>
      ) : (
        <div className="flex items-center gap-1">
          <select
            aria-label="Operator"
            className={input}
            value={isBoolOp(rule.op) ? 'gte' : rule.op}
            onChange={(e) => setRule({ ...rule, op: e.target.value as NumOp })}
          >
            {NUM_OPS.map((op) => (
              <option key={op} value={op}>
                {OP_SYMBOL[op]}
              </option>
            ))}
          </select>
          <select aria-label="Compare with" className={input} value={rhsMode} onChange={(e) => setRhsMode(e.target.value as 'value' | 'ref')}>
            <option value="value">number</option>
            <option value="ref">field</option>
          </select>
          {rhsMode === 'value' ? (
            <input
              aria-label="Value"
              type="number"
              step="any"
              autoFocus
              className={cn(input, 'num min-w-0 flex-1')}
              value={rule.value ?? ''}
              onChange={(e) => setRule({ ...rule, value: e.target.value === '' ? null : Number(e.target.value) })}
            />
          ) : (
            <select
              aria-label="Reference field"
              className={cn(input, 'min-w-0 flex-1')}
              value={rule.ref ?? 'ema_200'}
              onChange={(e) => setRule({ ...rule, ref: e.target.value })}
            >
              {numFields.map((f) => (
                <option key={f.field} value={f.field}>
                  {f.label}
                </option>
              ))}
            </select>
          )}
        </div>
      )}
      <div className="flex justify-end gap-1.5">
        <button type="button" onClick={onCancel} className="rounded px-2 py-0.5 text-xs text-fg-3 hover:text-fg">
          Cancel
        </button>
        <button
          type="button"
          disabled={!valid}
          onClick={() => onApply(finalRule)}
          className="rounded bg-accent/20 px-2 py-0.5 text-xs font-medium text-accent hover:bg-accent/30 disabled:opacity-40"
        >
          Apply
        </button>
      </div>
    </div>
  );
}
