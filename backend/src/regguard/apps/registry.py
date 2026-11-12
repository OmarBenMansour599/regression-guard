from regguard.apps import support_email
from regguard.apps.base import AppSpec
from regguard.core.errors import ConfigError

_APPS: dict[str, AppSpec] = {support_email.SPEC.name: support_email.SPEC}


def get_app(name: str) -> AppSpec:
    try:
        return _APPS[name]
    except KeyError:
        raise ConfigError(f"Unknown app '{name}'. Available: {', '.join(sorted(_APPS))}") from None
