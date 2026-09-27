/** The six tabs (spec D4 / 7.1). Order = keyboard shortcut 1-6. */
export const TABS = [
  { id: 'desk', label: 'Desk', path: '/desk', key: '1', hint: 'Environment, queues, sizer' },
  { id: 'screener', label: 'Screener', path: '/screener', key: '2', hint: 'Presets, Momentum + VCP' },
  { id: 'groups', label: 'Groups', path: '/groups', key: '3', hint: 'Sectors, industries, flow' },
  { id: 'deals', label: 'Deals', path: '/deals', key: '4', hint: 'Bulk / block deal plays' },
  { id: 'charts', label: 'Charts', path: '/charts', key: '5', hint: 'Multi-chart grid' },
  { id: 'research', label: 'Research', path: '/research', key: '6', hint: 'Analogs, big movers' },
] as const;

export type TabId = (typeof TABS)[number]['id'];

export function tabFromPath(pathname: string): TabId | null {
  const seg = pathname.split('/')[1] ?? '';
  return (TABS.find((t) => t.id === seg)?.id ?? null) as TabId | null;
}
