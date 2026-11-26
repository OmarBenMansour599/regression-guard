import { isRouteErrorResponse, useRouteError } from "react-router";
import { ErrorState } from "@/components/page";

export function RouteError() {
  const error = useRouteError();
  const message = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : "Unexpected error";
  return (
    <div className="p-8">
      <ErrorState error={new Error(message)} onRetry={() => window.location.reload()} />
    </div>
  );
}
