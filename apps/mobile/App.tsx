import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "./src/auth/AuthProvider";
import { TodoApiError } from "./src/todos/todoApi";

export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Infinity,
        gcTime: 300_000,
        refetchOnMount: true,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
        retry: (failureCount, error) =>
          failureCount < 1 &&
          error instanceof TodoApiError &&
          error.kind === "unavailable",
        retryDelay: 500,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

export default function App() {
  const [queryClient] = useState(createAppQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider />
    </QueryClientProvider>
  );
}
