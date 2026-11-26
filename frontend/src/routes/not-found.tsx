import { Compass } from "lucide-react";
import { Link } from "react-router";
import { EmptyState } from "@/components/page";

export function NotFound() {
  return (
    <EmptyState icon={Compass} title="Page not found">
      <Link to="/" className="underline underline-offset-4">
        Back to the overview
      </Link>
    </EmptyState>
  );
}
