"""Process entry point: serve, scan, import-lanmon, plugins list, db upgrade."""

import ipaddress
import json
import re
import threading
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer
import uvicorn

from netview.bootstrap import Container, build_container, create_application, make_settings
from netview.domain.errors import NetviewError
from netview.presentation.api.schemas import PORTS_SPEC, InspectionReportOut, NetworkStateOut

STATE_SCHEMA = "netview/state@1"
INSPECTION_SCHEMA = "netview/inspection@1"

app = typer.Typer(help="netview LAN monitor", no_args_is_help=True)
plugins_app = typer.Typer(help="Inspect plugins", no_args_is_help=True)
db_app = typer.Typer(help="Database maintenance", no_args_is_help=True)
app.add_typer(plugins_app, name="plugins")
app.add_typer(db_app, name="db")

ConfigOption = Annotated[Path | None, typer.Option("--config", help="Settings file (TOML)")]
DataDirOption = Annotated[Path | None, typer.Option("--data-dir", help="Where netview keeps its data")]


def _overrides(data_dir: Path | None, **extra: Any) -> dict[str, Any]:
    values = {k: v for k, v in extra.items() if v is not None}
    if data_dir is not None:
        values["data_dir"] = data_dir
    return values


@contextmanager
def _container(config: Path | None, data_dir: Path | None) -> Iterator[Container]:
    """Build the container without a server; close the database when done."""
    try:
        container = build_container(make_settings(config, **_overrides(data_dir)))
    except NetviewError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    try:
        yield container
    finally:
        container.host.shutdown()
        container.engine.dispose()


@app.command()
def serve(
    config: ConfigOption = None,
    data_dir: DataDirOption = None,
    bind: Annotated[str | None, typer.Option("--bind", help="Address to listen on")] = None,
    port: Annotated[int | None, typer.Option("--port", help="Port to listen on")] = None,
    open_browser: Annotated[bool, typer.Option("--open", help="Open the web UI in a browser")] = False,
    subnet: Annotated[
        str | None, typer.Option("--subnet", help="Subnet to scan, such as 192.168.1.0/24")
    ] = None,
    interval: Annotated[float | None, typer.Option("--interval", help="Seconds between scans")] = None,
    fast: Annotated[float | None, typer.Option("--fast", help="Seconds between fast checks")] = None,
) -> None:
    """Run the web UI and API."""
    settings = make_settings(
        config,
        **_overrides(
            data_dir, bind=bind, port=port, subnet=subnet, scan_interval_s=interval, fast_interval_s=fast
        ),
    )
    if open_browser:
        host = settings.bind
        if host in ("0.0.0.0", "::"):  # a wildcard bind is opened through loopback
            host = "127.0.0.1"
        elif _is_ipv6(host):
            host = f"[{host}]"
        threading.Timer(1.0, webbrowser.open, args=(f"http://{host}:{settings.port}/",)).start()
    uvicorn.run(
        create_application(settings), host=settings.bind, port=settings.port, timeout_graceful_shutdown=3
    )


def _is_ipv6(host: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(host), ipaddress.IPv6Address)
    except ValueError:
        return False


@app.command()
def scan(
    once: Annotated[bool, typer.Option("--once", help="Run one sweep and exit")] = False,
    list_devices: Annotated[bool, typer.Option("--list", help="Print one line per device")] = False,
    out: Annotated[Path | None, typer.Option("--out", help="Write the network state as JSON")] = None,
    config: ConfigOption = None,
    data_dir: DataDirOption = None,
) -> None:
    """Run a single discovery sweep without starting the server."""
    if not once:
        typer.echo("error: only --once is supported", err=True)
        raise typer.Exit(2)
    with _container(config, data_dir) as container:
        try:
            summary = container.services.run_scan()
        except NetviewError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from exc
        state = container.services.state()
    seconds = summary.duration_ms / 1000
    typer.echo(
        f"{summary.seen} devices ({summary.replied} replied, {summary.quiet} ARP only) in {seconds:.1f}s"
    )
    if list_devices:
        for d in sorted(state.devices, key=lambda d: _ip_sort_key(d.ip)):
            typer.echo(f"{d.ip}  {d.mac or '-'}  {d.vendor or '-'}  {d.display_name}".rstrip())
    if out is not None:
        document = {"schema": STATE_SCHEMA, **NetworkStateOut.model_validate(state).model_dump(mode="json")}
        out.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")


def _ip_sort_key(ip: str) -> tuple[int, int]:
    try:
        return (0, int(ipaddress.ip_address(ip)))
    except ValueError:
        return (1, 0)


@app.command("import-lanmon")
def import_lanmon(
    path: Annotated[Path, typer.Argument(help="A lan_monitor lan_store.json (never modified)")],
    prefer_source: Annotated[
        bool, typer.Option("--prefer-source", help="Let the file's nicknames replace existing ones")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Report what would change; write nothing")
    ] = False,
    config: ConfigOption = None,
    data_dir: DataDirOption = None,
) -> None:
    """Import devices, nicknames, name claims and watches from a lan_monitor store."""
    with _container(config, data_dir) as container:
        try:
            report = container.importer.run(path, prefer_source=prefer_source, dry_run=dry_run)
        except NetviewError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(2) from exc
    if dry_run:
        typer.echo("dry run: nothing was written")
    typer.echo(f"devices added: {report.devices_added}")
    typer.echo(f"devices updated: {report.devices_updated}")
    typer.echo(f"nicknames added: {report.nicknames_added}")
    typer.echo(f"history added: {report.history_added}")
    typer.echo(f"watches added: {report.watches_added}")
    for c in report.conflicts:
        typer.echo(f'{c.key}: netview="{c.netview}" source="{c.source}"')
    if report.conflicts and not prefer_source:
        typer.echo(
            f"{len(report.conflicts)} nickname conflict(s); use --prefer-source to take the file's values"
        )
        raise typer.Exit(1)


@app.command()
def inspect(
    ip: Annotated[str, typer.Argument(help="IPv4 address of the device to inspect")],
    ports: Annotated[
        str, typer.Option("--ports", help="top, all, common, or a list such as 22,80,8000-8100")
    ] = "top",
    out: Annotated[Path | None, typer.Option("--out", help="Write the report as JSON")] = None,
    config: ConfigOption = None,
    data_dir: DataDirOption = None,
) -> None:
    """Inspect one device with every enabled inspection plugin, without starting the server."""
    try:
        ipaddress.IPv4Address(ip)
    except ValueError:
        typer.echo(f"error: {ip!r} is not an IPv4 address", err=True)
        raise typer.Exit(2) from None
    if not re.fullmatch(PORTS_SPEC, ports):
        typer.echo(f"error: invalid --ports {ports!r}", err=True)
        raise typer.Exit(2)
    with _container(config, data_dir) as container:
        try:
            report = container.services.run_inspection(ip, ports)
        except NetviewError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from exc
    body = InspectionReportOut.model_validate(report).model_dump(mode="json")
    for section in body["sections"]:
        typer.echo(section["title"])
        data = section["data"]
        text = data.get("text")
        if isinstance(text, str):
            text = text.splitlines()
        if isinstance(text, list):
            for line in text:
                typer.echo(f"  {line}")
        else:
            typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
        if section["error"]:
            typer.echo(f"  error: {section['error']}")
    if out is not None:
        document = {"schema": INSPECTION_SCHEMA, **body}
        out.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")


@plugins_app.command("list")
def plugins_list(config: ConfigOption = None, data_dir: DataDirOption = None) -> None:
    """Show every discovered plugin and its state."""
    with _container(config, data_dir) as container:
        rows = [(p.id, p.state, p.version, p.error or "") for p in container.services.plugins.list()]
    header = ("id", "state", "version", "error")
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) if rows else len(header[i]) for i in range(4)]
    for row in (header, *rows):
        typer.echo("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())


@db_app.command("upgrade")
def db_upgrade(config: ConfigOption = None, data_dir: DataDirOption = None) -> None:
    """Bring the core schema and every enabled plugin's schema up to date."""
    with _container(config, data_dir) as container:  # building the container runs both migrations
        loaded = [p.id for p in container.services.plugins.list() if p.state == "active"]
    typer.echo(f"core schema up to date; plugins: {', '.join(loaded) if loaded else 'none'}")
