'use client';

/**
 * App-wide providers: TanStack Query for caching/retry/dedupe of the five
 * fetch calls that were previously scattered raw across page.tsx,
 * EvidencePanel.tsx and CoChangeGraph.tsx, plus an error boundary so a
 * backend failure renders a message instead of a blank client-component
 * crash.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError } from '@/lib/api';
import ErrorBoundary from './ErrorBoundary';

export default function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: (failureCount, error) => {
              // Retry a transient/offline failure a couple of times; a real
              // 404/422 from the backend retrying would just repeat the
              // same wrong request.
              if (error instanceof ApiError && !error.isRetryable) return false;
              return failureCount < 2;
            },
            staleTime: 30_000,
            refetchOnWindowFocus: false,
          },
          mutations: {
            retry: false,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={client}>
      <ErrorBoundary>{children}</ErrorBoundary>
    </QueryClientProvider>
  );
}
