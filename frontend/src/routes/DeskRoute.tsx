/**
 * Pulse tab (id 'desk', path /desk kept so links keep working): HarkPro/02-tab1-pulse.md, routes/pulse/.
 *
 * The legacy Today / Setups views were removed in sprint 2 (the Setups tab owns the queues). Old links
 * still land somewhere sensible: /desk?view=setups[&queue=vcp] -> /setups[?sq=vcp], /desk?view=today -> Pulse.
 */
import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { PulseView } from './pulse/PulseView';

/** Where an old /desk?view=… link should go now (null = stay on Pulse with the URL as is). Pure. */
export function legacyDeskRedirect(search: string): { pathname: string; search: string } | null {
  const p = new URLSearchParams(search);
  const view = p.get('view');
  if (view !== 'setups' && view !== 'today') return null;
  const queue = p.get('queue');
  p.delete('view');
  p.delete('queue');
  p.delete('tf');
  if (view === 'today') return { pathname: '/desk', search: p.toString() ? `?${p}` : '' };
  if (queue) p.set('sq', queue);
  return { pathname: '/setups', search: p.toString() ? `?${p}` : '' };
}

export default function DeskRoute() {
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    if (location.pathname !== '/desk') return;
    const to = legacyDeskRedirect(location.search);
    if (to) navigate(to, { replace: true });
  }, [location.pathname, location.search, navigate]);
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden p-2">
      <PulseView />
    </div>
  );
}
