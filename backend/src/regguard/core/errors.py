"""Error hierarchy. Infrastructure errors must never be reported as quality regressions."""


class RegGuardError(Exception):
    """Base class for all RegressionGuard errors."""


class ConfigError(RegGuardError):
    """Invalid or missing configuration."""


class DataValidationError(RegGuardError):
    """Invalid prompt, dataset, or model output structure."""


class ProviderError(RegGuardError):
    """An LLM provider call failed.

    ``retryable`` tells the executor whether a retry can help (429, 5xx, timeouts)
    or not (bad request, auth failure).
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after_s = retry_after_s


class ComparisonError(RegGuardError):
    """Runs cannot be compared (e.g. incompatible dataset versions)."""
