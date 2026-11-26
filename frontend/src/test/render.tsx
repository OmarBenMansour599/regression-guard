import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";

/** Answers `fetch` from a map of API paths (query string ignored); unknown paths -> 404. */
export function mockApi(routes: Record<string, unknown>, status = 200): void {
  vi.stubGlobal("fetch", async (url: string) => {
    const path = url.split("?")[0] ?? url;
    if (status !== 200) return Response.json({ detail: "boom" }, { status });
    return path in routes
      ? Response.json(routes[path])
      : Response.json({ detail: `no mock for ${path}` }, { status: 404 });
  });
}

export function renderPage(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}
