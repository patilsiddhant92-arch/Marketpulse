import React, { useState } from 'react';
import { Star, Copy, Check, Trash2, X } from 'lucide-react';

interface Props {
  basket: string[];
  onRemove: (symbol: string) => void;
  onClear: () => void;
}

export const StagingBasketDrawer: React.FC<Props> = ({ basket, onRemove, onClear }) => {
  const [copiedTv, setCopiedTv] = useState<boolean>(false);
  const [copiedRaw, setCopiedRaw] = useState<boolean>(false);

  if (basket.length === 0) return null;

  const handleCopyTv = () => {
    const list = basket.map((s) => `NSE:${s}`).join(', ');
    navigator.clipboard.writeText(list);
    setCopiedTv(true);
    setTimeout(() => setCopiedTv(false), 2000);
  };

  const handleCopyRaw = () => {
    const list = basket.join(', ');
    navigator.clipboard.writeText(list);
    setCopiedRaw(true);
    setTimeout(() => setCopiedRaw(false), 2000);
  };

  return (
    <div className="fixed bottom-0 left-0 right-[400px] bg-[#0e1522] border-t border-[#1f2b3c] px-4 py-2.5 flex items-center justify-between gap-3 z-30 shadow-2xl">
      <div className="flex items-center gap-3 overflow-hidden">
        <div className="flex items-center gap-1.5 text-xs font-bold text-[#f0be58] uppercase tracking-wider shrink-0">
          <Star className="w-4 h-4 fill-[#f0be58]" />
          <span>Active Watchlist ({basket.length})</span>
        </div>

        <div className="flex items-center gap-1.5 overflow-x-auto py-1">
          {basket.map((sym) => (
            <span
              key={sym}
              className="px-2 py-0.5 rounded bg-[#151f2b] border border-[#263447] text-xs font-mono text-[#f1f4f8] flex items-center gap-1 shrink-0"
            >
              {sym}
              <button
                onClick={() => onRemove(sym)}
                className="text-[#98a7ba] hover:text-[#f43f5e] transition"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={handleCopyTv}
          className="flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-semibold bg-[#182b46] text-[#74a9ff] border border-[#2b4c7e] hover:border-[#74a9ff] transition"
          title="Copy as TradingView Watchlist"
        >
          {copiedTv ? <Check className="w-3 h-3 text-[#45d483]" /> : <Copy className="w-3 h-3" />}
          {copiedTv ? 'Copied TV!' : 'Copy for TradingView'}
        </button>

        <button
          onClick={handleCopyRaw}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-[#151f2b] text-[#f1f4f8] border border-[#263447] hover:border-[#f0be58] transition"
          title="Copy comma separated symbols"
        >
          {copiedRaw ? <Check className="w-3 h-3 text-[#45d483]" /> : <Copy className="w-3 h-3" />}
          CSV
        </button>

        <button
          onClick={onClear}
          className="p-1 rounded bg-[#101721] text-[#98a7ba] hover:text-[#f43f5e] border border-[#263447] transition"
          title="Clear watchlist"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
};
