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
| `netview inspect IP [--ports SPEC] [--out FILE]` | Inspect one device without starting the server and print the report. `SPEC` is `top` (default), `all`, `common`, or a list such as `22,80,8000-8100`. `--out` writes the report as JSON (schema `netview/inspection@1`). Exits 2 on a bad address or port list, 1 when the inspection fails |
| `netview plugins ...` | Inspect discovered plugins |
| `netview db ...` | Database maintenance |

All commands accept `--config FILE` (TOML) and `--data-dir DIR`.

## Data directory

Everything netview keeps lives in one folder: the SQLite database
(`netview.db`) and an optional `netview.toml` settings file. The default is the
per-user data folder from `platformdirs` (`netview`). Override it with
`--data-dir`, the `NETVIEW_DATA_DIR` environment variable, or the settings file.
Other settings use the `NETVIEW_` prefix, with `__` for nesting.

## Built-in plugins

Each one can be turned off and configured under Settings, Plugins.

| Id | What it does | Settings |
|---|---|---|
| `lan_discovery` | Finds devices with a ping sweep and the ARP table | `ping_timeout_ms`, `workers` |
| `health` | Pings the gateway, the internet and every online device, times DNS and checks watched hosts | `internet_target`, `dns_servers` (up to 2), `dns_names`, `ping_timeout_ms`, `internet_timeout_ms`, `port_timeout_s`, `max_devices` (up to 64) |
| `identity` | Names devices from UPnP, NetBIOS, mDNS and reverse DNS, and guesses their type from the maker | `recheck_after_s`, `ssdp_timeout_s`, `mdns_timeout_s`, `netbios_timeout_s`, `rdns_timeout_s`, `workers` |
| `local_host` | This device's throughput, Wi-Fi link and TCP connections | `throughput_interval_s`, `connections_interval_s` |
| `inspection` | Scans a device's TCP ports and reads its web pages, certificates and discovery answers | `workers`, `port_timeout_s`, `full_scan_timeout_s`, `max_analyzed` |
| `starlink` | Per-device traffic, signal and names from a Starlink router's local API, read-only | `router` (blank means the gateway), `port`, `timeout_s` |

Built-in plugins never import each other; an import-linter independence contract enforces it.

## Metrics

`GET /api/v1/metrics?since_ms=<epoch ms>&prefix=<name>` returns the in-memory time series (repeat
`prefix` for several; `since_ms` returns only newer points, so the UI fetches deltas). Values are
milliseconds for latency and bits per second for rates; a `null` value means a failed or unknown
sample.

| Series | Kept | Meaning |
|---|---|---|
| `health.gateway`, `health.internet` | 720 | Ping round trip |
| `health.dns.<server>` | 720 | DNS lookup time |
| `health.device.<key>` | 120 | Ping round trip per device |
| `local.down_bps`, `local.up_bps` | 720 | This device's throughput |
| `traffic.down.<ip>`, `traffic.up.<ip>` | 120 | Per-device traffic from the router |

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

### Required settings

A plugin states which settings it needs in its settings schema. The host and the settings form
both read the schema. Fields without a default are required, and `settings_requirements` adds
more, including rules that depend on other fields:

```python
from pydantic import BaseModel, ConfigDict
from netview.sdk import fixed_when, required_when, settings_requirements

class MySettings(BaseModel):
    model_config = ConfigDict(json_schema_extra=settings_requirements(
        required=["host"],
        rules=[required_when({"auth": ["md5", "sha"]}, ["password"])],
    ))
```

The settings form marks these fields with an asterisk and checks them before it saves. The host
refuses a save that leaves one unmet, and the 422 response names each field. A plugin that is
running but misses a requirement reports `configured: false` and `config_errors` in
`/api/v1/plugins`. Until it is configured, its page tabs in the top bar are disabled.

### SDK 1.1

`SDK_VERSION` is `1.1`. Plugins that declare `sdk_version=">=1.0,<2"` still load. Two provider
signatures changed because no 1.0 plugin ever implemented them:

- `HealthProvider.probe(targets: HealthTargets)` now receives what to measure (gateway, subnet,
  online devices and watches) and returns `LatencySample` and `WatchProbe` items.
- `IdentityProvider.identify(devices: Sequence[DeviceView])` now receives a batch of devices. The core
  schedules it (`poll.identity`) and skips devices checked within `recheck_after_s`.

The context also gains `ctx.probes` (reverse DNS, NetBIOS, mDNS, SSDP and UPnP, HTTP and TLS, TCP
banners) and `ctx.system` (this device's byte counters, Wi-Fi link and TCP sockets). The test fakes
`FakeServiceProbes` and `FakeSystemInfo` take canned answers and return empty values for anything
else. `counter_rate(prev, down_bytes, up_bytes, t_ms)` turns two byte-counter readings into bits
per second, or `None` when a counter went backwards.

The core polls the providers of three capabilities itself, one job per plugin, so a failing plugin
backs off on its own: `poll.health` and `poll.traffic` (every `fast_interval_s`, 5 s by default)
and `poll.identity` (60 s). The
core turns their answers into metrics, watch status, name claims, traffic rates and events. Job
names starting with `poll.` are reserved, and a plugin job with such a name is refused.

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check .
uv run mypy src
uv run lint-imports
node --test "tests/js/*.test.mjs"
```
