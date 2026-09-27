import { useEffect, useRef } from 'react';

/**
 * Escape closes the innermost layer only (spec 7.1).
 *
 * Every drawer / popover / palette registers itself while open; one capturing
 * window keydown listener calls the most recently opened layer's onClose.
 */
type Layer = { id: number; close: () => void; modal: boolean };

const stack: Layer[] = [];
let nextId = 1;
let listening = false;

function onKeyDown(e: KeyboardEvent) {
  if (e.key !== 'Escape' || stack.length === 0) return;
  const top = stack[stack.length - 1];
  if (top.modal) {
    e.preventDefault();
    e.stopPropagation();
  }
  // Non-modal layers (sidecar) let the event continue so legacy views that
  // listen for Escape themselves still receive it.
  top.close();
}

function ensureListener() {
  if (listening || typeof window === 'undefined') return;
  window.addEventListener('keydown', onKeyDown, true);
  listening = true;
}

/** Number of open MODAL layers — the shell skips global shortcuts while > 0. */
export function openLayerCount(): number {
  return stack.filter((l) => l.modal).length;
}

/**
 * Register an Escape-closable layer while `open` is true. Non-modal layers
 * (the docked sidecar) close on Escape but do not block global shortcuts.
 */
export function useEscapeLayer(open: boolean, onClose: () => void, opts: { modal?: boolean } = {}): void {
  const modal = opts.modal ?? true;
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });
  useEffect(() => {
    if (!open) return;
    ensureListener();
    const layer: Layer = { id: nextId++, close: () => closeRef.current(), modal };
    stack.push(layer);
    return () => {
      const i = stack.findIndex((l) => l.id === layer.id);
      if (i >= 0) stack.splice(i, 1);
    };
  }, [open, modal]);
}
