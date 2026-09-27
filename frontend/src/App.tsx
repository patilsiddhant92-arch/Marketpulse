import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { RouterProvider, createBrowserRouter, type DataRouter } from 'react-router';
import { createQueryClient } from './api/query';
import { routes } from './routes';

export interface AppProps {
  /** Test seams. */
  router?: DataRouter;
  queryClient?: QueryClient;
}

export function App({ router, queryClient }: AppProps) {
  const [client] = useState(() => queryClient ?? createQueryClient());
  const [r] = useState(() => router ?? createBrowserRouter(routes));
  return (
    <QueryClientProvider client={client}>
      <RouterProvider router={r} />
    </QueryClientProvider>
  );
}

export default App;
