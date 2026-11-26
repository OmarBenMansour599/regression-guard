import { Ban, CircleCheck, CircleX, TriangleAlert, type LucideIcon } from "lucide-react";
import type { Verdict } from "@/api/client";
import { cn } from "@/lib/utils";

/**
 * Status colours are reserved for verdicts and always come with an icon and a label
 * (never colour alone). Text stays in normal ink; only the icon and tint carry the hue.
 */
const VERDICTS: Record<Verdict, { label: string; icon: LucideIcon; tone: string; help: string }> =
  {
    pass: {
      label: "Pass",
      icon: CircleCheck,
      tone: "text-pass bg-pass/10 ring-pass/25",
      help: "No metric got significantly worse.",
    },
    warn: {
      label: "Warn",
      icon: TriangleAlert,
      tone: "text-warn bg-warn/12 ring-warn/30",
      help: "A drop worth a look, not enough to block.",
    },
    fail: {
      label: "Fail",
      icon: CircleX,
      tone: "text-fail bg-fail/10 ring-fail/25",
      help: "A significant regression: the gate blocks this change.",
    },
    error: {
      label: "Error",
      icon: Ban,
      tone: "text-error bg-error/10 ring-error/25",
      help: "No verdict: the run failed for technical reasons.",
    },
  };

export function VerdictBadge({
  verdict,
  size = "sm",
  className,
}: {
  verdict: Verdict;
  size?: "sm" | "lg";
  className?: string;
}) {
  const v = VERDICTS[verdict];
  const Icon = v.icon;
  return (
    <span
      title={v.help}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full font-medium ring-1 ring-inset",
        size === "sm" ? "px-2 py-0.5 text-xs" : "px-3 py-1 text-sm",
        v.tone,
        className,
      )}
    >
      <Icon className={size === "sm" ? "size-3.5" : "size-4"} aria-hidden />
      <span className="text-foreground">{v.label}</span>
    </span>
  );
}

/** A run's own status (did it complete?), distinct from a comparison verdict. */
export function RunStatus({ status }: { status: string }) {
  const failed = status === "error";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        aria-hidden
        className={cn("size-1.5 rounded-full", failed ? "bg-error" : "bg-muted-foreground/60")}
      />
      <span className={failed ? "text-foreground" : "text-muted-foreground"}>
        {failed ? "Error" : "Completed"}
      </span>
    </span>
  );
}
