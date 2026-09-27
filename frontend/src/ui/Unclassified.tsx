/** Shown where a stock has no sector / industry in stocks_master (source taxonomy missing). */
export function Unclassified() {
  return (
    <span className="truncate italic text-fg-3" title="No sector / industry for this symbol in stocks_master (source taxonomy missing)">
      Unclassified
    </span>
  );
}
