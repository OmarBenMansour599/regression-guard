import { describe, expect, test } from "vitest";
import { ago, fixedEven, num, pct, shortHash } from "./format";
import { formatDelta, formatMetric, metricInfo, sortMetrics } from "./metrics";

describe("metrics", () => {
  test("labels and formats by metric", () => {
    expect(metricInfo("schema_valid").label).toBe("Valid format");
    expect(metricInfo("label_exact/billing").label).toBe("Correct: billing");
    expect(formatMetric("schema_valid", 2 / 3)).toBe("66.7%");
    expect(formatMetric("summary_judge", 4.583)).toBe("4.58");
    expect(formatMetric("latency_ms_p95", 1530)).toBe("1.53 s");
    expect(formatMetric("tokens_total", 4097)).toBe("4,097");
    expect(formatMetric("anything", null)).toBe("–");
  });

  test("deltas print like the CLI", () => {
    expect(formatDelta(-1 / 3, "absolute")).toBe("-33.3 pts");
    expect(formatDelta(-0.66, "relative")).toBe("-66%");
    expect(formatDelta(null, "relative")).toBe("n/a");
  });

  test("main metrics first, slices after", () => {
    expect(sortMetrics(["label_exact/billing", "schema_valid", "pass_rate"])).toEqual([
      "pass_rate",
      "schema_valid",
      "label_exact/billing",
    ]);
  });
});

describe("format", () => {
  test("percentages and numbers, with a dash for missing values", () => {
    expect(pct(2 / 3)).toBe("66.7%");
    expect(pct(1, 0)).toBe("100%");
    expect(pct(undefined)).toBe("–");
    expect(num(4.5833)).toBe("4.58");
    expect(num(null)).toBe("–");
  });

  test("relative time", () => {
    const now = new Date("2026-11-26T12:00:00Z");
    expect(ago("2026-11-26T11:59:40Z", now)).toBe("just now");
    expect(ago("2026-11-26T09:00:00Z", now)).toBe("3 hours ago");
    expect(ago("2026-11-25T12:00:00Z", now)).toBe("yesterday");
    expect(ago("2026-11-12T12:00:00Z", now)).toBe("2 weeks ago");
  });

  test("half-to-even rounding matches Python (CLI and PR comment)", () => {
    expect(fixedEven(0.0625, 3)).toBe("0.062"); // Python: f"{0.0625:.3f}" == "0.062"
    expect(fixedEven(0.0635, 3)).toBe("0.064");
    expect(fixedEven(0.5, 0)).toBe("0");
    expect(fixedEven(1.5, 0)).toBe("2");
    expect(fixedEven(0.1234, 3)).toBe("0.123");
  });

  test("short hash drops the algorithm prefix", () => {
    expect(shortHash("sha256:1b01bf65347781466283")).toBe("1b01bf653477");
  });
});
