"""Allow ``python -m regguard`` (no generated .exe launcher needed)."""

from regguard.cli.main import app

app(prog_name="regguard")
