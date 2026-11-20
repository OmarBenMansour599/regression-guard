"""Engine creation and schema migrations (Alembic, driven from Python: no launcher needed).

- Local SQLite: the schema is created/upgraded automatically on first use.
- Any other database (PostgreSQL): upgrades are explicit (``regguard db upgrade``), and a
  database whose schema is behind the code is refused instead of silently migrated.
"""

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url

from regguard.core.errors import ConfigError

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")  # SQLite ignores ON DELETE CASCADE without it
    cursor.close()


def make_engine(url: str) -> Engine:
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database not in (None, "", ":memory:"):
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def head_revision() -> str:
    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    if head is None:  # pragma: no cover - the package always ships migrations
        raise ConfigError("No database migrations found")
    return head


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def upgrade(engine: Engine, revision: str = "head") -> None:
    config = _alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def downgrade(engine: Engine, revision: str) -> None:
    config = _alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, revision)


def open_history(url: str, *, auto_upgrade_sqlite: bool = True) -> Engine:
    """An engine on an up-to-date history database."""
    engine = make_engine(url)
    if current_revision(engine) == head_revision():
        return engine
    if engine.dialect.name == "sqlite" and auto_upgrade_sqlite:
        upgrade(engine)
        return engine
    engine.dispose()
    raise ConfigError(
        f"The history database schema is not up to date ({engine.url.render_as_string()}). "
        "Run: regguard db upgrade"
    )
