import { createBrowserRouter } from "react-router";
import { Layout } from "@/components/layout";
import { RouteError } from "@/routes/route-error";

/** Each page is its own chunk: the first screen loads only what it needs. */
export const routes = [
  {
    path: "/",
    Component: Layout,
    ErrorBoundary: RouteError,
    HydrateFallback: () => null, // client-only app: nothing to show before the first route loads
    children: [
      { index: true, lazy: async () => ({ Component: (await import("@/routes/overview")).Overview }) },
      { path: "runs", lazy: async () => ({ Component: (await import("@/routes/runs")).Runs }) },
      { path: "runs/:runId", lazy: async () => ({ Component: (await import("@/routes/run")).Run }) },
      { path: "compare", lazy: async () => ({ Component: (await import("@/routes/compare")).Compare }) },
      { path: "trends", lazy: async () => ({ Component: (await import("@/routes/trends")).Trends }) },
      {
        path: "baselines",
        lazy: async () => ({ Component: (await import("@/routes/baselines")).Baselines }),
      },
      { path: "*", lazy: async () => ({ Component: (await import("@/routes/not-found")).NotFound }) },
    ],
  },
];

export const createRouter = () => createBrowserRouter(routes);
