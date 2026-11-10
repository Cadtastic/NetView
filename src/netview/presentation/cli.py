"""Process entry point (commands are added in a later task)."""

import typer

from netview import bootstrap  # noqa: F401  (the CLI is the one presentation module allowed here)

app = typer.Typer(help="netview LAN monitor")
