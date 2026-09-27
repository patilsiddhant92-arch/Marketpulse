/**
 * Route table. Tab paths render through the shell's keep-alive TabPanels
 * (their `element` is null); non-tab pages render through <Outlet />.
 */
import { Navigate, useLocation, type RouteObject } from 'react-router';
import { Shell } from '../shell/Shell';
import { TABS } from '../shell/tabs';
import { StockPage } from './registry';

function RedirectToDesk() {
  const { search } = useLocation();
  return <Navigate to={{ pathname: '/desk', search }} replace />;
}

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <Shell />,
    children: [
      { index: true, element: <RedirectToDesk /> },
      ...TABS.map((t) => ({ path: t.path.slice(1), element: null })),
      { path: 'stock/:sym', element: <StockPage /> },
      { path: '*', element: <RedirectToDesk /> },
    ],
  },
];
