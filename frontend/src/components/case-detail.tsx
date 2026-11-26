import { Ban, Check, Gavel, X } from "lucide-react";
import type { Schemas } from "@/api/client";
import { metricInfo } from "@/lib/metrics";
import { cn } from "@/lib/utils";

type CaseResult = Schemas["CaseResult"];

function Section({
  title,
  children,
  className,
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0 space-y-1.5", className)}>
      <h4 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{title}</h4>
      {children}
    </div>
  );
}

/** Email text is shown as plain text (React escapes it): an email cannot inject markup. */
export function EmailText({ text }: { text: string | undefined }) {
  if (text === undefined) {
    return (
      <p className="text-sm text-muted-foreground italic">
        Not shown: the dataset changed since this run.
      </p>
    );
  }
  // Focusable so a long email can be scrolled with the keyboard (axe: scrollable-region).
  return (
    <p
      tabIndex={0}
      role="region"
      aria-label="Email text"
      className="max-h-64 overflow-auto rounded-lg bg-muted/50 p-3 text-sm whitespace-pre-wrap outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
    >
      {text}
    </p>
  );
}

function Field({ name, value }: { name: string; value: unknown }) {
  return (
    <div className="text-sm">
      <span className="text-muted-foreground">{name}: </span>
      <span className={cn(name === "category" && "font-medium")}>{String(value)}</span>
    </div>
  );
}

/** The model's answer: fields when readable, the raw text when not, the error otherwise. */
export function Answer({ result }: { result: CaseResult | undefined }) {
  if (!result) return <p className="text-sm text-muted-foreground">Not in this run.</p>;
  if (result.error) {
    return (
      <div className="flex gap-2 rounded-lg border border-dashed p-3 text-sm">
        <Ban className="mt-0.5 size-4 shrink-0 text-error" aria-hidden />
        <div className="min-w-0">
          <p className="font-medium">No answer ({result.error.type})</p>
          <p className="break-words text-muted-foreground">{result.error.message}</p>
        </div>
      </div>
    );
  }
  if (result.parsed_output) {
    return (
      <div className="space-y-1">
        {Object.entries(result.parsed_output).map(([k, v]) => (
          <Field key={k} name={k} value={v} />
        ))}
      </div>
    );
  }
  return (
    <div className="space-y-1.5">
      <p className="flex items-center gap-1.5 text-xs font-medium">
        <X className="size-3.5 text-fail" aria-hidden />
        Unreadable answer: a program could not use it
      </p>
      <pre
        tabIndex={0}
        aria-label="Raw model output"
        className="max-h-48 overflow-auto rounded-lg bg-muted/50 p-3 font-mono text-xs whitespace-pre-wrap outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
      >
        {result.raw_output ?? ""}
      </pre>
    </div>
  );
}

export function Checks({ result }: { result: CaseResult }) {
  if (result.scores.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {result.scores.map((s) => {
        const info = metricInfo(s.name);
        const icon =
          s.passed === true ? (
            <Check className="size-3 text-pass" aria-label="passed" />
          ) : s.passed === false ? (
            <X className="size-3 text-fail" aria-label="failed" />
          ) : null;
        return (
          <li
            key={s.name}
            title={info.help}
            className="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs"
          >
            {icon}
            {info.label}
            {s.passed === null && (
              <span className="tabular text-muted-foreground">{s.value.toFixed(2)}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function Judge({ result }: { result: CaseResult }) {
  const judge = result.judge;
  if (!judge) return null;
  return (
    <div className="flex gap-2 text-sm">
      <Gavel className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
      {judge.score === null ? (
        <span className="text-muted-foreground">Judge could not grade this summary.</span>
      ) : (
        <span>
          <span className="tabular font-medium">{judge.score}/5</span>
          {judge.reason && <span className="text-muted-foreground"> · {judge.reason}</span>}
        </span>
      )}
    </div>
  );
}

function Meta({ result }: { result: CaseResult }) {
  const parts = [
    result.latency_ms !== null ? `${Math.round(result.latency_ms)} ms` : null,
    result.usage ? `${result.usage.prompt_tokens + result.usage.completion_tokens} tokens` : null,
    result.cached ? "from cache" : "fresh call",
  ].filter(Boolean);
  return <p className="text-xs text-muted-foreground">{parts.join(" · ")}</p>;
}

/** Everything about one case of one run. */
export function CaseDetail({
  result,
  input,
  expected,
}: {
  result: CaseResult;
  input: string | undefined;
  expected: Record<string, unknown> | undefined;
}) {
  return (
    <div className="grid gap-5 p-4 md:grid-cols-2">
      <Section title="Email">
        <EmailText text={input} />
      </Section>
      <div className="grid content-start gap-5">
        <Section title="Expected">
          {expected ? (
            Object.entries(expected).map(([k, v]) => <Field key={k} name={k} value={v} />)
          ) : (
            <p className="text-sm text-muted-foreground italic">Not available.</p>
          )}
        </Section>
        <Section title="Model answer">
          <Answer result={result} />
        </Section>
        <Section title="Checks">
          <Checks result={result} />
          <Judge result={result} />
          <Meta result={result} />
        </Section>
      </div>
    </div>
  );
}

export { Section };
