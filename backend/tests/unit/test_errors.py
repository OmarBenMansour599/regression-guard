from regguard.core.errors import (
    ComparisonError,
    ConfigError,
    DataValidationError,
    ProviderError,
    RegGuardError,
)


def test_all_errors_share_base() -> None:
    for exc in (ConfigError, DataValidationError, ProviderError, ComparisonError):
        assert issubclass(exc, RegGuardError)


def test_provider_error_defaults_to_non_retryable() -> None:
    err = ProviderError("bad request", status_code=400)
    assert err.retryable is False
    assert err.status_code == 400


def test_provider_error_carries_retry_info() -> None:
    err = ProviderError("rate limited", retryable=True, status_code=429, retry_after_s=2.5)
    assert err.retryable is True
    assert err.retry_after_s == 2.5
    assert str(err) == "rate limited"
