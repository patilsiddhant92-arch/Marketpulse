/** The six tabs (spec D4 / 7.1). Order = keyboard shortcut 1-6. */
export const TABS = [
  { id: 'desk', label: 'Pulse', path: '/desk', key: '1', hint: 'Market mood vs history, breadth, money flow' },
  { id: 'setups', label: 'Setups', path: '/setups', key: '2', hint: 'Darvas Squeeze, Darvas 10 EMA, VCP and Momentum on one board; rule presets' },
  { id: 'groups', label: 'Sector Intel', path: '/groups', key: '3', hint: 'Sectors, industries, indices, heatmap' },
  { id: 'deals', label: 'Deals', path: '/deals', key: '4', hint: 'Bulk / block deal plays' },
  { id: 'charts', label: 'Charts', path: '/charts', key: '5', hint: 'Multi-chart grid' },
  { id: 'research', label: 'Research', path: '/research', key: '6', hint: 'Analogs, big movers' },
] as const;

export type TabId = (typeof TABS)[number]['id'];

export function tabFromPath(pathname: string): TabId | null {
  const seg = pathname.split('/')[1] ?? '';
  return (TABS.find((t) => t.id === seg)?.id ?? null) as TabId | null;
}
