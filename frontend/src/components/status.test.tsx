import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { VerdictBadge } from "./status";

test.each([
  ["pass", "Pass"],
  ["warn", "Warn"],
  ["fail", "Fail"],
  ["error", "Error"],
] as const)("verdict %s has a text label and an explanation, not colour alone", (verdict, label) => {
  render(<VerdictBadge verdict={verdict} />);
  const text = screen.getByText(label);
  const badge = text.closest("span[title]");
  expect(badge?.getAttribute("title")).toBeTruthy();
  expect(badge?.querySelector("svg")).toBeTruthy(); // the icon
  expect(text.className).toContain("text-foreground"); // label in normal ink
});
