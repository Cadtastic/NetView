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

Inside it you will also find:

- `plugin-data/<guid>.db`: one file per plugin that stores data, named by the plugin's guid.
- `netview.db.bak-<YYYY-MM-DD>-before-plugin-identity`: a one-time backup of `netview.db`, taken on the
  first start of a version with plugin identity, before anything is migrated.

### Upgrading

The first start of this version backs up `netview.db`, re-keys saved plugin settings by guid and moves
each plugin's tables out of `netview.db` into `plugin-data/`. Things that change for you:

- Old `#/p/<name>/...` bookmarks stop working; plugin pages are addressed by number now.
- The device table's column preferences reset once.
- A plugin installed into `<data directory>/plugins` before this version (its old `plugin.json`) shows as
  invalid. Uninstall it and install it again.
- In `netview.toml`, `[plugins.<key>]` seed sections are keyed by the plugin's guid, not by its old id
  (see Built-in plugins).

## Built-in plugins

Each one can be turned off and configured under Settings, Plugins.

| Plugin | Type | Guid | What it does | Settings |
|---|---|---|---|---|
| LAN discovery | `software` | `4eddf684-deb5-41cf-9588-020746307ade` | Finds devices with a ping sweep and the ARP table | `ping_timeout_ms`, `workers` |
| Health | `software` | `9f4cd689-1a67-4c89-abff-ac9252568d97` | Pings the gateway, the internet and every online device, times DNS and checks watched hosts | `internet_target`, `dns_servers` (up to 2), `dns_names`, `ping_timeout_ms`, `internet_timeout_ms`, `port_timeout_s`, `max_devices` (up to 64) |
| Identity | `software` | `4b77e778-dc26-4ac0-8b2e-fe3995363df1` | Names devices from UPnP, NetBIOS, mDNS and reverse DNS, and guesses their type from the maker | `recheck_after_s`, `ssdp_timeout_s`, `mdns_timeout_s`, `netbios_timeout_s`, `rdns_timeout_s`, `workers` |
| This device | `software` | `0a505ba4-bbbd-40b8-a77d-8f5dbe1470a8` | This device's throughput, Wi-Fi link and TCP connections | `throughput_interval_s`, `connections_interval_s` |
| Inspection | `software` | `ac1dc07d-123c-4414-a4c8-72013d00f267` | Scans a device's TCP ports and reads its web pages, certificates and discovery answers | `workers`, `port_timeout_s`, `full_scan_timeout_s`, `max_analyzed` |

Built-in plugins never import each other; an import-linter independence contract enforces it.

A plugin's seed section in `netview.toml` is keyed by its guid. Quote the key, for example
`[plugins."3ae5ddcb-5e96-4dcc-b439-7b582a37b0f4"]`; it supplies the plugin's first-run settings, and
`enabled = false` in it starts the plugin turned off.

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

NetView creates that `plugins` folder the first time it runs. The folder name
does not matter: a plugin is identified by the `guid` in its `plugin.json`,
not by where it sits (see "Writing a plugin"). Each plugin folder carries its
own `tests` folder; it is not needed to run the plugin.

To remove a plugin, use **Uninstall** on its card in the Plugins gallery
(open the card's settings). Only plugins that live directly in
`<data directory>/plugins` can be uninstalled; built-in plugins and plugins
loaded through `--plugin-dir` cannot, and the server refuses the request for
them. Uninstall deletes the plugin's folder and stops the plugin now, and it is
fully gone after NetView restarts (its web addresses answer 404 until then). If
Windows holds a file open and the folder cannot be removed straight away, the
card says so and the next start finishes the job. A box, unchecked by default,
offers "Also delete its saved settings and data"; leave it off and a later
reinstall picks up the old settings and history. The box appears only on the
card of the plugin that owns the guid's data, so uninstalling a stray copy can
never wipe the working plugin's data.

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
from netview.sdk import Capability, Permission, Plugin, PluginContext, PluginManifest, PluginType


class MyPlugin(Plugin):
    manifest = PluginManifest(
        name="My plugin",
        version="0.1.0",
        description="What it does",
        guid="d7c1f2a4-5b6e-4c8d-9a0b-1e2f3a4b5c6d",  # permanent: pick one, never change it
        display_name="My plugin",
        plugin_type=PluginType.OTHER,
        sdk_version=">=2.0,<3",  # PEP 440 specifier against SDK_VERSION
        capabilities=frozenset({Capability.DISCOVERY}),
        permissions=frozenset({Permission.DEVICES_READ}),
    )

    def setup(self, ctx: PluginContext) -> None: ...
```

Optional hooks: `providers()`, `jobs()`, `router()` (mounted at
`/api/v1/plugins/<source_id>/`), `ui()` (static files at `/plugins/<source_id>/static/`),
`storage()` (see below), `settings_model` and `on_settings_changed()`.

There are two ways to make NetView load it. As a **folder plugin**, put the
code in a folder whose `__init__.py` sets `plugin_class = MyPlugin`, and copy
that folder into `<data directory>/plugins` (see Optional plugins). Use
relative imports inside the folder, since NetView loads it as
`netview_local_plugins.p<source_id>`. As an **installed package**, register it
through the `netview.plugins` entry-point group in your `pyproject.toml`:

```toml
[project.entry-points."netview.plugins"]
my_plugin = "my_package.plugin:MyPlugin"
```

### Identity: `guid`, `display_name`, `plugin_type`

Three manifest fields are required. A plugin missing one does not load; it
shows a failed card with the reason.

- `guid`: a UUID in lower case, 8-4-4-4-12 form. It is the plugin's permanent
  identity: it keys the plugin's saved settings, names its data file and its
  permissions, and matches Installed against Available. Generate one once and
  never change it across versions. There is no author-written `id`.
- `display_name`: a short label used for the plugin's tab in the top bar and as
  the name of the device the plugin represents, such as `GSM7248` or `Roku`.
  `name` stays the full name on the gallery card.
- `plugin_type`: one `PluginType` value: `router`, `switch`, `access_point`,
  `firewall`, `modem`, `server`, `nas`, `computer`, `tv` (TVs and streaming
  boxes), `printer`, `camera`, `ups`, `iot` (smart-home devices), `software`
  (a plugin not tied to one piece of hardware) or `other` (when nothing else
  fits). An unknown value is an error.

NetView gives every guid it registers a number, the `source_id`, the first
time it sees it. That number is stable: it is kept even after an uninstall, so
a reinstall gets the same one. It appears in the plugin's addresses, so code
must not hard-code them:

| What | Address |
|---|---|
| Plugin API (`router()`) | `/api/v1/plugins/<source_id>/...` |
| Static files (`ui()`) | `/plugins/<source_id>/static/...` |
| A plugin page in the UI | `#/p/<source_id>/<page>` |

Read the values from the host instead: `ctx.source_id`, `ctx.guid` and
`ctx.display_name` in Python, and `pluginId`, `pluginGuid` and `apiBase` in the
browser. Anything saved long term, such as a plugin's settings, its data file
or a role's permissions, uses the guid, because a `source_id` only means
something on one install.

Folder names do not matter. NetView reads `plugin.json` first, then loads the
folder as `netview_local_plugins.p<source_id>`. Each guid loads at most once.
If two plugins share a guid, exactly one loads, chosen in this order: the
built-in one; then the one in the folder the guid last loaded from, so a
working plugin is never displaced by a new copy; then a `--plugin-dir` folder
before `<data directory>/plugins`; then folder path, as a last tie-break. Each
loser shows a failed card in Installed, such as "Same guid as Roku (loaded from
...)", and NetView starts normally. A copy of a plugin with a renamed folder
therefore never replaces the original. Built-in plugins take their guid from
their manifest and have no `plugin.json`.

### Storage

A plugin that declares `storage()` gets its own SQLite database file at
`<data directory>/plugin-data/<guid>.db`, created on first load. Name tables
plainly (`tvs`, `port_samples`); no prefix is needed because the file is the
plugin's alone. Its Alembic version table is the standard `alembic_version`.
The plugin's connection denies `ATTACH` and `DETACH`, so it cannot reach
`netview.db` or another plugin's file. Core data is reached through the
context, not through SQL.

### The plugin.json file

A folder plugin also ships a `plugin.json` next to its `__init__.py`. It
mirrors the Python manifest so NetView can describe the plugin without
importing it, and a plugin needs one to be listed in Available (and to show in
Installed before its first load). Required fields: `schema`
(`netview.plugin/2`), `name`, `version`, `description`, `guid`, `display_name`,
`plugin_type`, `sdk_version`, `capabilities`, `permissions`. There is no `id`: the `guid`
is the identity, and an `id` key is refused. Optional: `author`, `homepage`, `license`,
`requires` (distribution names). Any other key is refused, so adding a field
means a new schema id. A folder plugin must have a valid `plugin.json`, and NetView
checks it against the Python manifest when the plugin loads: a mismatch, a
missing field or an unknown `plugin_type` makes the plugin fail to load, with a
card that names the fields that differ.

To list a plugin in Available, add its folder and `plugin.json` under
`plugins/`, run `uv run python scripts/build_plugin_index.py --execute`, and
commit the folder (its name is the install folder) together with the regenerated `plugins/index.json` and
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

A test that drives the plugin's routes through a running test app needs its
`source_id`, which the app assigns. `netview.sdk.testing.addresses` finds it:
`plugin_key(services, guid)` returns the runtime key, `api_base(services, guid)`
returns `/api/v1/plugins/<source_id>` and `static_base(services, guid)` returns
`/plugins/<source_id>/static`.

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

SDK 1.1 added the following. Two provider
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

### SDK 2.0

`SDK_VERSION` is `2.0`. Plugins declare `sdk_version=">=2.0,<3"`; a plugin written for 1.x does not
load. What changed:

- The author-written `id` is gone from `PluginManifest` and `plugin.json` (schemas `netview.plugin/2`
  and `netview.plugin-index/2`). `guid`, `display_name` and `plugin_type` are required.
- Plugin addresses and `#/p/` routes use the database-assigned `source_id`; saved settings and
  permissions use the guid.
- Storage moves to one file per plugin with unprefixed tables, and `ATTACH`/`DETACH` are denied.
- Permission ids are `<guid>.<permission>` (see [plugin permissions](docs/plugin-permissions.md)).
- `ctx.source_id`, `ctx.guid` and `ctx.display_name` are available, and the page slot's `title` is
  optional (the tab shows `display_name`).

An index entry's `path` must match `^plugins/[a-z0-9][a-z0-9_-]*$`. Its last segment is the install
folder, with `-2`, `-3` added when the name is taken by a different guid. The Available gallery
matches installed plugins by guid, a guid that is already installed is refused, and an index with the
same guid twice is refused.
