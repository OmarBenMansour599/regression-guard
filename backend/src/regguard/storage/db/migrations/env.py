"""Alembic environment. Always driven from Python (``regguard db upgrade`` or automatic
upgrade of the local SQLite file), which passes an open connection in ``config.attributes``.
"""

from alembic import context

from regguard.storage.db.models import Base

connection = context.config.attributes.get("connection")
if connection is None:  # pragma: no cover - we never run alembic without a connection
    raise RuntimeError("Run migrations through `regguard db upgrade`")

context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    render_as_batch=True,  # SQLite cannot ALTER most things: rebuild tables in batch mode
    compare_type=True,
)
with context.begin_transaction():
    context.run_migrations()
