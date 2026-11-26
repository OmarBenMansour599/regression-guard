import { Check, Copy, ServerCrash, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 pb-6">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

/** Explains a failed request in plain words, with a retry. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  const offline = error instanceof ApiError && error.status === 0;
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-3 rounded-xl border border-dashed p-6 text-sm"
    >
      <div className="flex items-center gap-2 font-medium">
        <ServerCrash className="size-4 text-error" aria-hidden />
        {offline ? "Server not reachable" : "Could not load this page"}
      </div>
      <p className="text-muted-foreground">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  children,
}: {
  icon: LucideIcon;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed px-6 py-12 text-center">
      <Icon className="size-6 text-muted-foreground" aria-hidden />
      <p className="font-medium">{title}</p>
      {children && <div className="max-w-md text-sm text-muted-foreground">{children}</div>}
    </div>
  );
}

export function LoadingBlock({ className }: { className?: string }) {
  return <Skeleton className={cn("h-24 w-full rounded-xl", className)} />;
}

/** The dashboard is read-only: changes happen in the CLI. Shows the command, copyable. */
export function CliHint({ command, children }: { command: string; children?: React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: the command stays selectable */
    }
  };
  return (
    <div className="rounded-lg bg-muted/60 p-3 text-xs">
      {children && <p className="mb-2 text-muted-foreground">{children}</p>}
      <div className="flex items-center gap-2">
        <code className="min-w-0 flex-1 truncate font-mono text-foreground">{command}</code>
        <Button
          variant="ghost"
          size="icon"
          className="size-7 shrink-0"
          onClick={copy}
          aria-label={copied ? "Copied" : "Copy command"}
        >
          {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
        </Button>
      </div>
    </div>
  );
}
