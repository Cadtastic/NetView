# netview

A plugin-based LAN monitor with a local web UI, built with Clean Architecture
(domain, application, infrastructure, presentation, plus a public plugin SDK).
It replaces the single-file `lan_monitor.py`.

## Install

Requires Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Run

```bash
uv run netview serve            # http://127.0.0.1:8765
uv run netview serve --port 8766 --data-dir ./dev-data --open
```

netview binds to `127.0.0.1:8765` by default. Only the `localhost`,
`127.0.0.1`, `[::1]` and configured bind-address `Host` names are accepted, and
every non-GET request needs the header `X-Netview: 1`. Interactive API docs are
served at `/docs`.

## CLI

| Command | What it does |
|---|---|
| `netview serve [--bind] [--port] [--open]` | Start the web UI and background jobs |
| `netview scan --once [--list] [--out FILE]` | Run one sweep and exit; print devices or write the network state as JSON |
| `netview import-lanmon FILE [--dry-run] [--prefer-source]` | Import a `lan_store.json`. The source file is never modified; existing nicknames are kept unless `--prefer-source` is given |
| `netview plugins ...` | Inspect discovered plugins |
| `netview db ...` | Database maintenance |

All commands accept `--config FILE` (TOML) and `--data-dir DIR`.

## Data directory

Everything netview keeps lives in one folder: the SQLite database
(`netview.db`) and an optional `netview.toml` settings file. The default is the
per-user data folder from `platformdirs` (`netview`). Override it with
`--data-dir`, the `NETVIEW_DATA_DIR` environment variable, or the settings file.
Other settings use the `NETVIEW_` prefix, with `__` for nesting.

## Writing a plugin

A plugin is a class that subclasses `netview.sdk.Plugin` and imports only from
`netview.sdk`.

```python
from netview.sdk import Capability, Permission, Plugin, PluginContext, PluginManifest


class MyPlugin(Plugin):
    manifest = PluginManifest(
        id="my_plugin",                 # ^[a-z][a-z0-9_]*$
        name="My plugin",
        version="0.1.0",
        description="What it does",
        sdk_version=">=1.0,<2",         # PEP 440 specifier against SDK_VERSION
        capabilities=frozenset({Capability.DISCOVERY}),
        permissions=frozenset({Permission.DEVICES_READ}),
    )

    def setup(self, ctx: PluginContext) -> None: ...
```

Optional hooks: `providers()`, `jobs()`, `router()` (mounted at
`/api/v1/plugins/<id>/`), `ui()` (static files at `/plugins/<id>/static/`),
`storage()` (tables must be named `<plugin_id>_<name>`), `settings_model` and
`on_settings_changed()`.

Register it through the `netview.plugins` entry-point group in your
`pyproject.toml`:

```toml
[project.entry-points."netview.plugins"]
my_plugin = "my_package.plugin:MyPlugin"
```

Check it in your own tests with the SDK contract helper:

```python
from netview.sdk.testing.contract import check_plugin

def test_plugin_contract() -> None:
    check_plugin(MyPlugin)
```

`netview/plugins/builtin/lan_discovery` is a complete working example.

### SDK 1.1

`SDK_VERSION` is `1.1`. Plugins that declare `sdk_version=">=1.0,<2"` still load. Two provider
signatures changed because no 1.0 plugin ever implemented them:

- `HealthProvider.probe(targets: HealthTargets)` now receives what to measure (gateway, subnet,
  online devices and watches) and returns `LatencySample` and `WatchProbe` items.
- `IdentityProvider.identify(devices: Sequence[DeviceView])` now receives a batch of devices. The core
  schedules it (`poll.identity`) and skips devices checked within `recheck_after_s`.

The context also gains `ctx.probes` (reverse DNS, NetBIOS, mDNS, SSDP and UPnP, HTTP and TLS, TCP
banners) and `ctx.system` (this device's byte counters, Wi-Fi link and TCP sockets). The test fakes
`FakeServiceProbes` and `FakeSystemInfo` take canned answers and return empty values for anything else.

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check .
uv run mypy src
uv run lint-imports
node --test "tests/js/*.test.mjs"
```
