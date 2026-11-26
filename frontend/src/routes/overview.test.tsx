import { screen, within } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { drift, overview, runPage, runSummary } from "@/test/fixtures";
import { mockApi, renderPage } from "@/test/render";
import { Overview } from "./overview";

describe("Overview page", () => {
  test("shows the latest verdict, baseline, drift and recent runs", async () => {
    mockApi({
      "/api/overview": overview,
      "/api/runs": runPage([runSummary()]),
      "/api/drift": drift,
    });
    renderPage(<Overview />);

    const summary = await screen.findByRole("region", { name: "Summary" });
    expect(await within(summary).findByText("Fail")).toBeTruthy(); // latest verdict
    expect(within(summary).getByText("100.0%")).toBeTruthy(); // baseline pass rate
    expect(within(summary).getByText("Not enough data")).toBeTruthy(); // drift
    expect(screen.getAllByText("20261118T112155Z-edd66e").length).toBeGreaterThan(0);
  });

  test("a run in ERROR never shows its partial score as a real one", async () => {
    mockApi({
      "/api/overview": overview,
      "/api/runs": runPage([runSummary({ status: "error", verdict: null, metrics: { pass_rate: 1 } })]),
      "/api/drift": drift,
    });
    renderPage(<Overview />);
    const scores = await screen.findAllByTitle(/Not a quality score/);
    expect(scores.length).toBeGreaterThan(0);
    expect(scores[0]?.className).toContain("line-through");
  });

  test("explains how to fill an empty history", async () => {
    mockApi({ "/api/overview": overview, "/api/runs": runPage([]), "/api/drift": drift });
    renderPage(<Overview />);
    expect(await screen.findByText("No runs recorded yet")).toBeTruthy();
    expect(screen.getByText("uv run python -m regguard history import")).toBeTruthy();
  });

  test("shows the server's error message with a retry", async () => {
    mockApi({}, 503);
    renderPage(<Overview />);
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("boom")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });
});
