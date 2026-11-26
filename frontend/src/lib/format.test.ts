import { describe, expect, test } from "vitest";
import { ago, num, pct, shortHash } from "./format";

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

  test("short hash drops the algorithm prefix", () => {
    expect(shortHash("sha256:1b01bf65347781466283")).toBe("1b01bf653477");
  });
});
