import { FlaskConical } from 'lucide-react';
import { useShell } from '../shell/ShellContext';
import { EmptyState } from '../ui/EmptyState';

/** Research (lazy-loaded). No legacy workspace exists; the tab lands with spec 7.6. */
export default function ResearchRoute() {
  const shell = useShell();
  return (
    <div className="flex h-full items-center justify-center">
      <EmptyState
        icon={<FlaskConical className="h-6 w-6" />}
        title="Research lands with the evidence engine"
        detail="Market analogs, big movers with catalyst attribution, pre-move watch and group studies (spec 7.6). Until then, the 180-session breadth history is the only study in the app."
        action={
          <button
            type="button"
            onClick={() => shell.setBreadthOpen(true)}
            className="rounded border border-line bg-surface-2 px-2 py-1 text-xs text-fg-2 hover:bg-surface-3"
          >
            Open breadth history (legacy)
          </button>
        }
      />
    </div>
  );
}
