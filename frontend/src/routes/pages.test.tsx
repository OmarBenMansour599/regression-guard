import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { describe, expect, test } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { drift, overview, runPage, runSummary } from "@/test/fixtures";
import { comparison, runDetail, trendPoint } from "@/test/fixtures-detail";
import { mockApi } from "@/test/render";
import { Baselines } from "./baselines";
import { Compare } from "./compare";
import { Run } from "./run";
import { Runs } from "./runs";
import { Trends } from "./trends";

function Location() {
  const { pathname, search } = useLocation();
  return <output data-testid="location">{pathname + search}</output>;
}

/** Renders a page at a URL, inside the same providers as the app. */
function renderAt(url: string, path: string, page: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter initialEntries={[url]}>
          <Routes>
            <Route path={path} element={page} />
            <Route path="*" element={<p>other page</p>} />
          </Routes>
          <Location />
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("Runs page", () => {
  test("lists runs, strikes the scores of runs in ERROR, links each run", async () => {
    mockApi({
      "/api/overview": overview,
      "/api/runs": runPage([
        runSummary(),
        runSummary({ run_id: "r-err", status: "error", verdict: null, metrics: { pass_rate: 1, schema_valid: 1 } }),
      ]),
    });
    renderAt("/runs", "/runs", <Runs />);
    expect(await screen.findByText("2 runs")).toBeTruthy();
    const errRow = screen.getByText("r-err").closest("tr") as HTMLElement;
    const struck = within(errRow).getAllByTitle(/Not a quality score/);
    expect(struck).toHaveLength(2); // pass rate and valid format
    fireEvent.click(errRow);
    expect(screen.getByTestId("location").textContent).toBe("/runs/r-err");
  });

  test("an empty filtered result says so (not 'no runs yet')", async () => {
    mockApi({ "/api/overview": overview, "/api/runs": runPage([]) });
    renderAt("/runs?status=error", "/runs", <Runs />);
    expect(await screen.findByText("No run matches these filters")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeTruthy();
  });
});

describe("Run page", () => {
  test("opens a case: the email as plain text, the unreadable raw answer, the checks", async () => {
    mockApi({ "/api/runs/20261118T112155Z-edd66e": runDetail() });
    renderAt("/runs/20261118T112155Z-edd66e", "/runs/:runId", <Run />);
    const row = (await screen.findByText("email-0012")).closest("tr") as HTMLElement;
    fireEvent.click(row);
    expect(await screen.findByText("Partnership opportunity")).toBeTruthy();
    expect(screen.getByText(/Unreadable answer/)).toBeTruthy();
    expect(screen.getByText(/\[\{"category": "general"/)).toBeTruthy();
  });

  test("email text with markup is shown as text, never run", async () => {
    mockApi({ "/api/runs/20261118T112155Z-edd66e": runDetail() });
    const { container } = renderAt("/runs/20261118T112155Z-edd66e", "/runs/:runId", <Run />);
    fireEvent.click((await screen.findByText("email-0001")).closest("tr") as HTMLElement);
    expect(await screen.findByText(/I was charged twice <script>/)).toBeTruthy();
    expect(container.querySelector("script")).toBeNull();
  });

  test("hides email text when the dataset changed since the run", async () => {
    mockApi({ "/api/runs/20261118T112155Z-edd66e": runDetail({}, false) });
    renderAt("/runs/20261118T112155Z-edd66e", "/runs/:runId", <Run />);
    fireEvent.click((await screen.findByText("email-0012")).closest("tr") as HTMLElement);
    expect(await screen.findByText(/Not shown: the dataset changed/)).toBeTruthy();
  });

  test("a run in ERROR says there is no verdict and strikes its scores", async () => {
    mockApi({
      "/api/runs/x": runDetail({ status: "error", error: "error rate 17% exceeds the 10% limit" }),
    });
    renderAt("/runs/x", "/runs/:runId", <Run />);
    expect(await screen.findByText(/no quality verdict/)).toBeTruthy();
    expect(screen.getByText("error rate 17% exceeds the 10% limit")).toBeTruthy();
    expect(screen.getAllByText("50.0%")[0]?.className).toContain("line-through");
  });

  test("an unknown run explains how to import history", async () => {
    mockApi({});
    renderAt("/runs/nope", "/runs/:runId", <Run />);
    expect(await screen.findByText("Run not found")).toBeTruthy();
    expect(screen.getByText("uv run python -m regguard history import")).toBeTruthy();
  });
});

describe("Compare page", () => {
  test("verdict, reasons, p rounded like the CLI, and the regressed case side by side", async () => {
    mockApi({
      "/api/overview": overview,
      "/api/runs": runPage([runSummary()]),
      "/api/compare": comparison,
      "/api/runs/20261118T112155Z-edd66e": runDetail(),
    });
    renderAt("/compare?candidate=20261118T112155Z-edd66e", "/compare", <Compare />);
    expect(await screen.findByText(/significant regression/)).toBeTruthy();
    expect(screen.getByText("critical_regression")).toBeTruthy();
    expect(screen.getByText("0.062")).toBeTruthy(); // 0.0625 rounds half-to-even, as in Python
    expect(screen.getByText("Critical")).toBeTruthy();
    expect(screen.getByText("Changed 1")).toBeTruthy();
    expect(await screen.findByText("Candidate answer")).toBeTruthy();
    expect(screen.getByText(/Run not in the history database/)).toBeTruthy(); // baseline run missing
  });

  test("without a candidate it asks for one", async () => {
    mockApi({ "/api/overview": overview, "/api/runs": runPage([]) });
    renderAt("/compare", "/compare", <Compare />);
    expect(await screen.findByText("Choose a run to check")).toBeTruthy();
  });
});

describe("Trends page", () => {
  test("leaves runs in ERROR and empty runs out of the line, and says so", async () => {
    mockApi({
      "/api/overview": overview,
      "/api/drift": drift,
      "/api/trends": [
        trendPoint(1),
        trendPoint(2, { status: "error" }),
        trendPoint(3, { n: 0, value: 0 }),
        trendPoint(4, { fresh: true }),
      ],
    });
    renderAt("/trends", "/trends", <Trends />);
    expect(await screen.findByText(/2 runs not shown/)).toBeTruthy();
    expect(screen.getByText(/at least a few fresh runs/)).toBeTruthy(); // drift insufficient
  });

  test("defaults to the baseline's prompt version", async () => {
    mockApi({ "/api/overview": overview, "/api/drift": drift, "/api/trends": [] });
    renderAt("/trends", "/trends", <Trends />);
    expect(await screen.findByText("Prompt v1")).toBeTruthy();
    expect(await screen.findByText("Not enough runs to draw a trend")).toBeTruthy();
  });
});

describe("Baselines page", () => {
  test("marks the prompt version pinned by a baseline", async () => {
    mockApi({
      "/api/overview": {
        ...overview,
        prompts: [{ ...overview.prompts[0]!, content_hash: "sha256:1b01bf653477aaaa" }, overview.prompts[1]!],
      },
    });
    renderAt("/baselines", "/baselines", <Baselines />);
    const v1 = (await screen.findAllByText("v1")).map((el) => el.closest("tr")).find(Boolean) as HTMLElement;
    expect(within(v1).getByText("main")).toBeTruthy();
    expect(screen.getByText("Golden dataset v1")).toBeTruthy();
  });
});
