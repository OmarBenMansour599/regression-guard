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
    or not (bad request, auth failure). ``fatal`` means every further call would fail the
    same way (e.g. an unusable API key): the executor aborts the run instead of trying more.
    Messages must never contain secrets: they are saved in run files and reports.
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        retry_after_s: float | None = None,
        fatal: bool = False,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after_s = retry_after_s
        self.fatal = fatal


class ComparisonError(RegGuardError):
    """Runs cannot be compared (e.g. incompatible dataset versions)."""
