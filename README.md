# NetView

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

NetView binds to `127.0.0.1:8765` by default. Only the `localhost`,
`127.0.0.1`, `[::1]` and configured bind-address `Host` names are accepted, and
every non-GET request needs the header `X-Netview: 1`. Interactive API docs are
served at `/docs`.

## CLI

| Command | What it does |
|---|---|
| `netview serve [--bind] [--port] [--open] [--plugin-dir DIR]` | Start the web UI and background jobs. `--plugin-dir` adds a folder of plugin folders to load and can be given more than once |
| `netview scan --once [--list] [--out FILE]` | Run one sweep and exit; print devices or write the network state as JSON |
| `netview import-lanmon FILE [--dry-run] [--prefer-source]` | Import a `lan_store.json`. The source file is never modified; existing nicknames are kept unless `--prefer-source` is given |
| `netview inspect IP [--ports SPEC] [--out FILE]` | Inspect one device without starting the server and print the report. `SPEC` is `top` (default), `all`, `common`, or a list such as `22,80,8000-8100`. `--out` writes the report as JSON (schema `netview/inspection@1`). Exits 2 on a bad address or port list, 1 when the inspection fails |
| `netview plugins ...` | Inspect discovered plugins |
| `netview db ...` | Database maintenance |

All commands accept `--config FILE` (TOML) and `--data-dir DIR`.

## Data directory

Everything NetView keeps lives in one folder: the SQLite database
(`netview.db`), an optional `netview.toml` settings file, your own themes
(`themes/`) and the plugins you have installed (`plugins/`). The default is the
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

Built-in plugins never import each other; an import-linter independence contract enforces it.

## Optional plugins

Plugins for particular hardware are not part of the app. They live in the
[`plugins/`](plugins) folder of this repository, one folder each:

| Folder | What it does |
|---|---|
| `plugins/gsm7248` | NETGEAR GSM7248 switch over SNMP: a drawn front panel with port status and VLANs, the MAC table, spanning tree, traffic and device-to-port mapping, plus its serial console over SSH |
| `plugins/starlink` | Per-device traffic, signal and names from a Starlink router's local API, read-only |

To install one, copy its folder into the `plugins` folder of your data
directory and restart netview:

```text
<data directory>/plugins/gsm7248/
<data directory>/plugins/starlink/
```

NetView creates that `plugins` folder the first time it runs. To remove a
plugin, delete its folder and restart; the data it stored stays in the
database. Each plugin folder carries its own `tests` folder; it is not needed
to run the plugin.

To load plugins from somewhere else as well, such as this repository while you
work on them, start NetView with `--plugin-dir`, or list the folders under
`plugin_dirs` in `netview.toml`:

```bash
netview serve --plugin-dir plugins
```

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
        id="my_plugin",  # ^[a-z][a-z0-9_]*$
        name="My plugin",
        version="0.1.0",
        description="What it does",
        sdk_version=">=1.0,<2",  # PEP 440 specifier against SDK_VERSION
        capabilities=frozenset({Capability.DISCOVERY}),
        permissions=frozenset({Permission.DEVICES_READ}),
    )

    def setup(self, ctx: PluginContext) -> None: ...
```

Optional hooks: `providers()`, `jobs()`, `router()` (mounted at
`/api/v1/plugins/<id>/`), `ui()` (static files at `/plugins/<id>/static/`),
`storage()` (tables must be named `<plugin_id>_<name>`), `settings_model` and
`on_settings_changed()`.

There are two ways to make NetView load it. As a **folder plugin**, put the
code in a folder whose `__init__.py` sets `plugin_class = MyPlugin`, and copy
that folder into `<data directory>/plugins` (see Optional plugins). Use
relative imports inside the folder, since NetView loads it as
`netview_local_plugins.<folder>`. As an **installed package**, register it
through the `netview.plugins` entry-point group in your `pyproject.toml`:

```toml
[project.entry-points."netview.plugins"]
my_plugin = "my_package.plugin:MyPlugin"
```

A folder plugin also ships a `plugin.json` next to its `__init__.py`. It
mirrors the Python manifest so NetView can describe the plugin without
importing it, and a plugin needs one to be listed in Available (and to show in
Installed before its first load). Required fields: `schema`
(`netview.plugin/1`), `id`, `name`, `version`, `description`, `sdk_version`,
`capabilities`, `permissions`. Optional: `author`, `homepage`, `license`,
`requires` (distribution names). A core test fails when the file disagrees with
the Python manifest. Plugins without one still load as before. (The GS105E plugin
adds its own when its branch lands.)

To list a plugin in Available, add its folder and `plugin.json` under
`plugins/`, run `uv run python scripts/build_plugin_index.py --execute`, and
commit the folder together with the regenerated `plugins/index.json` and
`src/netview/infrastructure/plugins/catalog.json` (the copy bundled with each
release). To try the Available page before pushing, run
`uv run python scripts/serve_fake_plugin_repo.py --execute` and start NetView
with `NETVIEW_PLUGIN_CATALOG_URL` set to the URL it prints.

Check it in your own tests with the SDK contract helper:

```python
from netview.sdk.testing.contract import check_plugin


def test_plugin_contract() -> None:
    check_plugin(MyPlugin)
```

`netview/plugins/builtin/lan_discovery` is a complete working example of a
built-in plugin, and `plugins/starlink` of a folder plugin with its own tests.

### Required settings

A plugin states which settings it needs in its settings schema. The host and the settings form
both read the schema. Fields without a default are required, and `settings_requirements` adds
more, including rules that depend on other fields:

```python
from pydantic import BaseModel, ConfigDict
from netview.sdk import fixed_when, required_when, settings_requirements


class MySettings(BaseModel):
    model_config = ConfigDict(
        json_schema_extra=settings_requirements(
            required=["host"],
            rules=[required_when({"auth": ["md5", "sha"]}, ["password"])],
        )
    )
```

The settings form marks these fields with an asterisk and checks them before it saves. The host
refuses a save that leaves one unmet, and the 422 response names each field. A plugin that is
running but misses a requirement reports `configured: false` and `config_errors` in
`/api/v1/plugins`. Until it is configured, its page tabs in the top bar are disabled.

To split a long form into sections, give each field a group. A field can also appear only while other
fields hold given values, such as credentials for the chosen protocol version:

```python
from netview.sdk import setting_group

user: str = Field("", json_schema_extra=setting_group("SNMP v3", show_when={"version": "3"}))
```

Sections appear in the order of their first field, and a hidden field keeps its value.

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
uv run mypy src plugins
uv run lint-imports
npm test
```
