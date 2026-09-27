/**
 * Tab id -> component. Tab builders replace the legacy route component here
 * (or edit the route file in place). Charts and Research are code-split.
 */
import { lazy, type ComponentType, type LazyExoticComponent } from 'react';
import type { TabId } from '../shell/tabs';
import DealsRoute from './DealsRoute';
import DeskRoute from './DeskRoute';
import GroupsRoute from './GroupsRoute';
import ScreenerRoute from './ScreenerRoute';

export const TAB_COMPONENTS: Record<TabId, ComponentType | LazyExoticComponent<ComponentType>> = {
  desk: DeskRoute,
  screener: ScreenerRoute,
  groups: GroupsRoute,
  deals: DealsRoute,
  charts: lazy(() => import('./ChartsRoute')),
  research: lazy(() => import('./ResearchRoute')),
};

export const StockPage = lazy(() => import('./StockRoute'));
