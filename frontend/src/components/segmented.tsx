import { cn } from "@/lib/utils";

/**
 * A row of toggle buttons for filtering a list. Not tabs: tabs promise tab panels, and
 * screen readers announce them as such (axe: aria-valid-attr-value). Each button reports
 * its state with aria-pressed.
 */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-lg bg-muted p-[3px]">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={cn(
              "rounded-md px-2.5 py-1 text-sm font-medium transition-colors outline-none",
              "focus-visible:ring-[3px] focus-visible:ring-ring/50",
              active
                ? "bg-background text-foreground shadow-sm dark:bg-input/30"
                : // muted-foreground on bg-muted is ~4.3:1, under the 4.5:1 minimum (axe)
                  "text-foreground/75 hover:text-foreground",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
