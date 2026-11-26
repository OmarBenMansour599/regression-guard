import { Hammer } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/page";

// Placeholders for the pages built in step 8d.
function Soon({ title, what }: { title: string; what: string }) {
  return (
    <>
      <PageHeader title={title} />
      <EmptyState icon={Hammer} title="Coming in the next step">
        {what}
      </EmptyState>
    </>
  );
}

export const RunsSoon = () => (
  <Soon title="Runs" what="Every recorded run, filterable by prompt version and status." />
);
export const RunSoon = () => (
  <Soon title="Run" what="Metrics and every case, with the email, expected and actual answers." />
);
export const CompareSoon = () => (
  <Soon title="Compare" what="Any run against the baseline or another run, side by side." />
);
export const TrendsSoon = () => (
  <Soon title="Trends & drift" what="Each metric over time, and the drift status." />
);
export const BaselinesSoon = () => (
  <Soon title="Baselines & prompts" what="Baselines, prompt versions and the golden dataset." />
);
