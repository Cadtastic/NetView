# netview GeoTrace plugin: design

Date: 2026-11-12. Status: design written for planning. Anything marked **my call** was decided by Claude and not discussed with the user; the user can overturn it.

Mockup the user approved: `docs/superpowers/specs/2026-11-12-geotrace-mockup.html`. Open it in a browser. It is a working CesiumJS 1.144 globe with made-up hops, loaded from a CDN, and it uses Esri street tiles as a stand-in, because tile.openstreetmap.org blocked a browser on localhost. Neither the CDN nor Esri is part of this design. The user chose layout option A ("globe first") with an Azure-portal-style blade menu. Where this document and the mockup differ, this document wins.

## 1. Intent

The user wants to know how traffic from their home network reaches the places they care about, and how that changes over time. GeoTrace is a folder plugin (`plugins/geotrace/`) that:

- traces the route to an IP address or web address and shows each hop on a zoomable 3D globe. From space it looks like Google Earth, and it turns into a street map as you zoom in;
- **keeps every trace**, so a target builds up a history. The user's own words: "keeping traces and comparing routes over time … build trends over time, compare different traces through the same ip/site address";
- traces saved targets **on a schedule**, so trends are even and a route change at 3 a.m. gets caught;
- also does a quick one-off trace or ping of any address without saving it.

The home network is on Starlink (CGNAT, ground stations that change), which is a large part of why routes move. The design has to make that visible, not hide it.

## 2. Goals, non-goals, anti-goals

**Goals**

- Saved targets, each with a name, the address as typed, an interval and an on/off switch. Each one is traced on its schedule and on demand.
- Each run is a traceroute plus a short ping burst to the destination (loss and jitter).
- Show each trace on a CesiumJS globe: arcs between located hops, labels, a moving packet, fly-to-hop down to street level, and "fly along route".
- Compare any two traces of a target, on the globe and in a side-by-side hop table.
- Trend charts per target (time to destination, hop count, packet loss), with route changes marked.
- Route changes and slowdowns become NetView Events.
- Fetch and cache map tiles **on the NetView server**, so the browser only ever talks to NetView and the CSP stays as strict as it is today.
- Geolocate hops with **DB-IP City Lite** (and DB-IP ASN Lite for network names) by default.
- Add a core plugin permission, **`network:internet`**, that GeoTrace declares and the gallery and Admin page show.

**Non-goals (v1)**

- MaxMind GeoLite2 and RIPE IPmap. They come later as **options the administrator turns on with their own account details** (user decision). Section 8.4 leaves room for them.
- TCP or UDP traceroute modes, Paris-traceroute or MTR-style continuous probing.
- Traces from anywhere other than the machine NetView runs on (no remote probes or vantage points).
- 3D terrain or 3D buildings. Imagery on the ellipsoid is enough.
- Esri World Imagery as a base layer. It looked best in the mockup, but its terms haven't been checked. It is listed in §15.
- Notifications beyond NetView Events (email, push).
- Reading router hostnames for city codes such as `lax` or `dfw` to improve placement. Section 15.

**Anti-goals (a failure even if it works)**

- **Loosening NetView's CSP for every page.** If Cesium needs anything extra, it is allowed on GeoTrace's own responses only (§12, spike S2).
- **Breaking OpenStreetMap's tile policy:** prefetching or bulk downloading tiles, hiding who we are, or ignoring cache headers. OSM blocking the server would break the plugin for everyone.
- **Sending the user's traces or IP addresses to third parties without them opting in.** In v1 the only outbound traffic is the traces themselves, tile requests for what is on screen, the monthly DB-IP downloads, the one-time Cesium download and optional address search (§8.5).
- **NetView becomes a way to make the server fetch arbitrary URLs.** The tile endpoint only takes `{z}/{x}/{y}` for named, configured sources; it never takes a URL.
- **GeoTrace makes the network or NetView noisy:** overlapping traces, traces every few seconds, or a page that hammers the API. One trace at a time, a 5-minute minimum interval, light polling.
- **Shipping tens of MB of Cesium inside the repo**, so that every gallery install of every plugin downloads it (§4.2).
- Showing a location as fact when it is a guess. Hops placed by assumption or failing the speed-of-light check look different (§8.3).

## 3. Constraints found in the code

- **CSP** (`src/netview/presentation/api/security.py`): `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'`. No CDN scripts, no external images, no external fetches from the page.
- **Plugin SDK is 2.0** (`application/plugins/manifest.py`). A plugin gets a `PluginContext` with `net`, `core`, `clock`, `unit_of_work()` (its own SQLite file at `<data dir>/plugin-data/<guid>.db`), `require()`, `principal()` and `audit()`. Jobs are `JobSpec(name, interval_s, run, timeout_s=60, initial_delay_s)`.
- **There is no plugin folder for large files.** A plugin gets a database file but nowhere to put a 130 MB mmdb, a tile cache or the Cesium bundle.
- **`NetworkTools` has `ping` but no traceroute.** Ping wraps the OS command (`infrastructure/net/windows.py`, `linux.py`).
- **Events:** `ctx.core.add_event(EventKind.PLUGIN, text, ip=None)`.
- **User permissions** (`application/auth/catalog.py`): a plugin gets automatic *view* if it has the `api` or `web_ui` capability, *use* if it has `api`, and *configure* if it has a settings model. GeoTrace has all three. Plugins may add more with `user_permissions` (SDK 1.5).
- **Plugin UI runs inside the core shell.** A plugin's `ui.js` registers a page slot that is mounted in the single core document at `/`. The CSP that governs the page is that document's, not the CSP of the plugin's own responses, and `frame-ancestors 'none'` rules out an iframe.
- **The plugin catalog parser rejects unknown permissions** (`plugin_json.py`, `parse_index` → `parse_plugin_json`). One entry that names a permission an install doesn't know makes that install's whole gallery fail to load (§5.1).
- **Plugin installs download the whole repo** (`plugin_json.DEFAULT_ARCHIVE_URL` is the codeload zip of `main`). Anything large committed anywhere in the repo is downloaded by every gallery install.
- **Folder plugins cannot install Python packages.** Any third-party library GeoTrace needs must be a NetView core dependency.
- **Plugin rules** (NetView spec §7): import only `netview.sdk`; own tables only; a CSP-compatible, no-build ES-module UI; theme tokens for colour; plugin CSS scoped (GS105E lesson: use a prefix, here `gt-`).

## 4. Approaches considered

### 4.1 Globe library (user picked CesiumJS)

| Option | Trade-off |
|---|---|
| **CesiumJS** (Apache-2.0) | **Chosen.** The closest to Google Earth: real 3D globe, imagery level-of-detail, smooth camera flights, polylines and labels, and offline Natural Earth II imagery. Works without a Cesium ion token. Downside: large (about 20 MB once trimmed). |
| MapLibre GL JS v5+ globe (BSD-3) | Lighter, and its globe blends into a flat map as you zoom. Less like Google Earth, and under v6 it needs `setWorkerUrl` for a strict CSP. Kept as the fallback if spike S2 fails. |
| globe.gl / three-globe (MIT) | Prettiest arcs, but weak at street level. Rejected. |

### 4.2 How Cesium reaches the browser (**my call**)

| Option | Trade-off |
|---|---|
| Commit Cesium into `plugins/geotrace/static/vendor/` | Simplest, but adds about 20 MB to the repo forever, and every gallery install of *any* plugin downloads it (§3). |
| **Download a pinned, trimmed Cesium bundle on first use** into the plugin's files folder, checked against a SHA-256 in the plugin, and served by the plugin from NetView's origin | **Chosen.** The repo stays small and the CSP stays `'self'`. The bundle is a NetView GitHub release asset (`geotrace-cesium-<version>.zip`) built by a script in the plugin's `tools/`. Until it is downloaded, the page shows a "Preparing the globe (one-time download, ~8 MB)" state. |
| Load from a CDN | Breaks the CSP. Rejected (anti-goal). |

### 4.3 Map tiles (user picked: the server fetches and caches, OpenStreetMap)

The server proxies tiles with a disk cache. The alternative, letting plugins add origins to the CSP, was rejected by the user's choice. It also exposes the viewer's IP and needs a core CSP mechanism.

### 4.4 Geolocation (user picked DB-IP City Lite default)

DB-IP City Lite (CC BY 4.0, monthly, no account) is the default. MaxMind GeoLite2 and RIPE IPmap come later as admin-configured options (§8.4).

### 4.5 Traceroute (**my call**)

Wrap the OS tool (`tracert` on Windows, `traceroute` on Linux) behind a new `NetworkTools.traceroute` port, the same way `ping` already works. Neither needs admin rights. `icmplib` was rejected because it seems to need admin rights on Windows and is LGPL. A raw-socket tracer was rejected because it needs root or admin. If parsing `tracert` proves fragile (localized output), Windows can switch to `IcmpSendEcho2` through `ctypes` (TTL set per probe, no admin) behind the same port. That is a builder decision after the parser fixtures exist.

## 5. Core changes (SDK 2.0 → 2.1)

GeoTrace needs five small core additions. They land first and on their own. The plugin's `sdk_version` is `>=2.1,<3`.

1. **`Permission.NETWORK_INTERNET = "network:internet"`.** Declared like the others and shown in the plugin gallery card, the install confirmation and the Admin page's plugin details, with a plain label such as "Connects to the internet". Like the other manifest permissions it is a disclosure, not a sandbox.
   **Older installs (user decision, 2026-11-13): they may break.** Once GeoTrace's entry is in `plugins/index.json` on `main`, an SDK 2.0 install's gallery fails to read the list until that install is upgraded. No second catalog file and no holding back. The 2.1 core merges before (or with) the GeoTrace entry. As part of this change the parser becomes tolerant: an entry with a permission or SDK range the install doesn't support is listed as "Needs a newer NetView" instead of failing the whole list. That way the next new permission won't break 2.1+ installs.
2. **`ctx.files_dir: Path`**, the plugin's own folder for large files: `<data dir>/plugin-data/<guid>/`, created on first access. Uninstall removes it together with the plugin's `.db` file. **The builder must align this with the uninstall code from the plugin-identity work.**
3. **`NetworkTools.traceroute(target_ip, max_hops=30, probe_timeout_ms=1000, on_hop=None) -> TraceResult`.** It returns each hop with its number, IP (or none for `* * *`) and up to three RTTs. `on_hop` is called as each hop is parsed, so the UI can show progress. Windows: `tracert -d -h N -w T`, with `-4`/`-6` from the address family. Linux: `traceroute -n -m N -w S`, falling back to `tracepath -n`. The port reports "traceroute is not installed" as a clear error, not a crash. Parsing reads numbers only (hop number, `<1`/`N` ms, `*`, IP), so localized words don't matter. It is tested against fixture captures from both systems, including a silent destination and an unreachable target.
4. **`maxminddb` becomes a core dependency** (Apache-2.0, pure-Python fallback), re-exported by `netview.sdk` as a small `GeoDatabase` reader port so the plugin still imports only `netview.sdk`. **My call.** The alternative was copying a reader into the plugin.

5. **IPv6 ping** (user decision 2026-11-13: both families, chosen per target). `NetworkTools.ping` accepts IPv6 as well as IPv4 (today it returns `None` for anything that fails `valid_ipv4`). Windows: `ping -6`; Linux: `ping -6` (falling back to `ping6`). The parser must not depend on a TTL field, because Windows IPv6 replies have none. It is tested with captured fixtures for both families. Existing IPv4 behaviour and its callers (health, lan_discovery) must not change.

The ping burst (§6.2) calls `ctx.net.ping` repeatedly.

## 6. Tracing

### 6.1 Targets

Fields: name; address as typed (IP or host name); **address family, IPv4 or IPv6, chosen per target** (user decision; default IPv4, **my call**; an IP literal fixes the family itself); interval (5, 15, 30 or 60 minutes, default 15; **my call** on the choices); enabled; created/updated times. History is grouped **by the target, not by IP**: a site that answers from a different server is part of the trend, not a new target. Each trace records which IP it reached.

### 6.2 One run

1. Resolve the address for the target's family only (A records for IPv4, AAAA for IPv6). Record the IP. A resolve failure, including "this site has no IPv6 address", is saved as a failed trace with the reason in plain words. Trace once has the same IPv4/IPv6 choice.
2. Traceroute (§5.3), max 30 hops, 1 s per probe.
3. Ping burst: 10 pings, 200 ms apart, to the destination IP. Record min/avg/max, loss % and jitter (mean absolute difference of consecutive RTTs).
4. Geolocate every hop (§8) and save the trace, hops and summary in one transaction.
5. Compare with the previous saved trace of the same target (§9) and raise Events if needed.

"Ping only" (from Trace once) skips step 2 and shows only the destination on the globe.

### 6.3 Scheduling (**my call** on the mechanism)

- A plugin-owned **worker thread** runs one trace at a time from a queue. It starts in `setup` and stops in `shutdown`. A 30-second `JobSpec` tick enqueues targets that are due. Traces can take a minute and must never overlap, so they don't fit inside the job runner's 60 s timeout.
- Due times are spread out: a target's first run is offset by a hash of its id across its interval, so ten 15-minute targets don't all fire at :00.
- "Trace now" and "Trace once" go to the front of the queue. A target already queued or running is not queued twice.
- At most 50 saved targets and a 5-minute minimum interval (**my call**; anti-goal "noisy").
- After a restart, overdue targets run once, not once per missed slot.

### 6.4 Live progress

`POST /api/v1/plugins/<plugin id>/traces` returns a trace id at once. The UI polls `GET …/traces/{id}` every second while it is `queued` or `running`. Hops appear as `on_hop` reports them, and the globe draws arcs as hops arrive. Polling stops when the trace is `done` or `failed`. NetView's only push channel is the core server-sent events stream at `/api/v1/stream`, which carries no plugin frames, so polling is the practical choice and matches the other plugins.

## 7. Storage (plugin's own SQLite, `geotrace_` tables)

- `geotrace_target`: id, name, address, family (`ipv4`/`ipv6`), interval_min, enabled, created_ms, updated_ms.
- `geotrace_trace`: id, target_id (null for an unsaved one-off), trigger (`scheduled`/`manual`/`once`), mode (`trace`/`ping`), status, error, started_ms, finished_ms, resolved_ip, family, reached (bool), hop_count, rtt_ms (destination avg), loss_pct, jitter_ms, ping_min/max, route_signature.
- `geotrace_hop`: trace_id, n, ip (nullable), rtt1/rtt2/rtt3 (nullable), city, region, country, lat, lon, asn, as_org, placement (`located`/`home`/`assumed`/`none`), plausible (bool).
- `geotrace_settings_state`: home location, last DB download month and hashes, Cesium bundle status (or keep these in settings; builder's choice).

A `files_dir` layout: `geo/dbip-city-lite-YYYY-MM.mmdb`, `geo/dbip-asn-lite-YYYY-MM.mmdb`, `cesium/<version>/…`, `tiles/<source>/<z>/<x>/<y>.<ext>` plus a small index for expiry and LRU.

**Retention:** a daily job deletes traces (and their hops) older than the configured days. The default is 90 and the administrator can change it (user-approved). One-off traces are kept for 7 days (**my call**). Size: about 30 hops × ~100 bytes, so roughly 96 traces a day per target is about 300 KB a day. Fine.

## 8. Placing hops on the map

### 8.1 Data

- **DB-IP City Lite** and **DB-IP ASN Lite** (both CC BY 4.0, mmdb, monthly, no account) are downloaded from `download.db-ip.com/free/` into `files_dir/geo/`. The download happens on first use, then a monthly job checks for the new month's files (gzip; verify that the file opens and has a sane record count before swapping it in atomically; keep the previous month until the new one works).
- The required attribution link, "IP geolocation by DB-IP" pointing to https://db-ip.com, is visible on the GeoTrace page (the globe credits area) and in Settings.
- The ASN database supplies network names ("SpaceX Starlink", "Level 3", "Netflix") for the hop list and lets GeoTrace recognise Starlink (AS14593).

### 8.2 Special addresses

- Private, loopback and link-local hops (RFC 1918, 127/8, 169.254/16, fc00::/7, fe80::/10) are **placed at home** (`placement=home`).
- CGNAT 100.64.0.0/10 hops have no lookup. They are placed at the next located hop (`placement=assumed`), with the note "placed at the ground station". This is the Starlink gateway in the mockup.
- Silent hops (`* * *`) are listed and not drawn (`placement=none`). The arc skips over them.

### 8.3 Plausibility

For each located hop, the speed-of-light check: light in fibre covers about 100 km per ms of round-trip time. If the hop is farther from home than `min(RTT) × 100 km` plus a 200 km slack, mark it `plausible=false`. Draw it hollow with a dashed arc and the tooltip "location from the database doesn't fit the response time". Constants are **my call**, and the builder may tune the slack with real traces.

### 8.4 Later sources (non-goal for v1, but the shape is fixed now)

Geolocation sits behind a small `HopLocator` interface in the plugin (`locate(ip) -> Location | None`), with DB-IP as the only v1 implementation. Later: MaxMind GeoLite2 (admin enters account ID and license key; replaces or backs up DB-IP) and RIPE IPmap (opt-in, since it sends hop IPs to RIPE). Settings have a "Location data" section that lists sources in priority order. In v1 it shows DB-IP and "coming later" rows, as in the mockup.

### 8.5 Home location

Settings → Home location. The administrator sets it by dropping a pin on the globe, typing coordinates, or searching an address. Address search uses OSM Nominatim through the server (at most 1 request a second, same User-Agent as tiles, results cached). It can't come from the public IP: on Starlink that geolocates to the ground station. With no home location set, the first private hops sit at the first located hop and the page shows a "Set your home location" hint.

## 9. Comparing and route changes

- **Route signature:** the ordered list of `(ASN, city)` for located hops, collapsing runs of the same pair. Silent and private hops are ignored. City/ASN level is used on purpose: load balancing changes individual router IPs from trace to trace, and per-IP signatures would report a "change" every run.
- **Route change Event:** when the signature differs from the last saved trace's **and** the next trace agrees with the new one (two in a row, to avoid flapping). Text like: `GeoTrace · netflix.com: route changed at hop 4 (Salt Lake City → Dallas), +14 ms`.
- **Slowdown Event:** when the median destination RTT of the last hour is over 40% above the median of the previous 24 hours, and at least 10 ms more. At most one per target per 6 hours. Thresholds are **my call**.
- **Unreachable Event:** when a target fails 3 runs in a row. **Back** is reported when it recovers.
- **Compare blade:** pick any two traces of a target (defaults: newest, and the last one with a different signature). Both are drawn (newest solid teal, older dashed amber, both from theme tokens). The hop table aligns rows by hop number and highlights rows where the city or ASN differ. It shows "They split after hop N".

## 10. The page (blade layout, as approved)

Globe-first page: the Cesium globe fills the page under NetView's top bar. On the left is an **icon rail**: Targets, Compare, Trends, Trace once, with Settings at the bottom. Rail buttons open **blades**, translucent panels that stack left to right over the globe. When a third blade opens, the oldest shrinks to a vertical strip with its title, and clicking the strip expands it again. Each blade has minimise and close. This follows the mockup.

- **Targets blade:** "+ Add target", "Trace now" (selected target), and a list with a status dot (worst of reachability, loss and slowdown), name, "every N min · last change note" and the latest RTT or loss. Selecting a target opens the Route blade.
- **Route blade:** target name, "N hops · traced X ago · RTT · loss", buttons Fit route / Fly along route / Compare… / Trends, and the hop list (number, place, network name, IP, note, RTT). Clicking a hop flies the camera to it at about 9 km. A trace picker (newest by default) lets the user step back through history.
- **Compare blade** (§9) and **Trends blade:** ranges 24 h / 7 d / 30 d / 90 d. Charts for time to destination, hop count and packet loss, with route-change markers. Charts use NetView's existing chart helper, not a new library.
- **Trace once blade:** address field, Trace, Ping only, Save as target. The result is drawn like any trace and can be saved as a target afterwards.
- **Globe:** Natural Earth II base imagery (from the Cesium bundle, offline) blending into OSM street tiles from about 4,000 km down to about 600 km. There is a top-right HUD with the altitude, the blend meter, the base imagery picker and zoom buttons. Arcs are lifted great-circle polylines. The first hop on a Starlink route (detected by AS14593) is drawn up to a satellite marker at about 550 km and back down to the ground station. A moving dot shows the live or selected trace. Labels fade out beyond about 12,000 km. Home is green, the destination red, and other hops use the route colour. Credits show "© OpenStreetMap contributors", the DB-IP link and any base imagery credit.
- **Settings** (NetView settings tabs, SDK 1.3 `settings_tabs`): *General* (home location, retention days, default interval); *Map* (street tile source, base imagery, tile cache size cap); *Location data* (DB-IP status and last update, "Update now", MaxMind/RIPE rows marked as later).
- **Empty and failed states:** no targets yet; globe bundle still downloading; DB-IP not downloaded yet (hops listed but not placed); traceroute missing on Linux; tile fetch blocked (§11).

The UI follows NetView's rules: no-build ES modules in `plugins/geotrace/static/`, theme tokens only, all CSS under a `gt-` prefix, no inline scripts.

## 11. Tile proxy

- Route: `GET /api/v1/plugins/<plugin id>/tiles/{source}/{z}/{x}/{y}`. `source` is from a fixed list in the plugin: `osm` (street map, default) and `eox-s2` (Sentinel-2 cloudless, off by default), plus an administrator-defined `custom` URL template (see "Blocked detection" below). z, x and y are range-checked integers. The server builds the upstream URL itself and never takes a URL from the client.
- Upstream requests use `User-Agent: NetView-GeoTrace/<version> (+https://github.com/Cadtastic/NetView)`. That is unique and identifiable, as OSM requires.
- **Cache:** disk under `files_dir/tiles/`. Each tile is kept as long as its `Cache-Control`/`Expires` allows (minimum 7 days for OSM if the headers are shorter, as the policy allows). After that, the cache revalidates with `If-None-Match`/`If-Modified-Since`. Size cap default 500 MB (admin setting), with least-recently-used eviction. Tiles are fetched only when a viewer asks: **no prefetching, ever** (anti-goal).
- At most 2 upstream requests in flight per source. Identical in-flight requests are joined.
- Validation: the response must be a PNG or JPEG by magic bytes and under 1 MB, else the server returns 502 and caches nothing. This follows the Roku icon proxy's `_icon_type` check.
- **Blocked detection:** if OSM answers with its "blocked" tile (an image at 200 OK), the server can't easily tell it apart from a real tile. Spike S1 decides whether we can detect it (for example by a known hash or a header). If OSM blocks NetView, the administrator switches *Map → Street tile source* to the **custom URL template** (for example a self-hosted tile server or a provider with their own API key) without a code change.
- The page's attribution follows whichever source is active.

## 12. Serving Cesium

- Settings → Map shows the bundle state: *not downloaded*, *downloading*, *ready (version)*. It downloads automatically on first visit to the GeoTrace page. An administrator can also trigger it.
- The plugin knows one pinned bundle: version, URL (NetView GitHub release asset), size and SHA-256. A mismatch deletes the download and shows an error.
- `plugins/geotrace/tools/build_cesium_bundle.py` (dry run by default; `--execute`) takes an official Cesium release zip, keeps `Build/Cesium/{Cesium.js, Workers/, ThirdParty/, Widgets/, Assets/}`, drops the unused assets (keeping `Assets/Textures/NaturalEarthII`, the sky box and the moon), and writes the zip and its SHA-256. Publishing the release asset is a manual step for the user.
- The existing `/plugins/<id>/static` mount only serves the plugin's packaged `static_dir`, so the downloaded bundle needs its own route: `GET /api/v1/plugins/<plugin id>/cesium/{path}` serving files from `files_dir/cesium/<version>/` (path-traversal guarded, correct content types, long cache headers, *view* permission). **My call.** Same origin, so `script-src 'self'` holds. Cesium's base URL is set to that route before `Cesium.js` loads, through a small external module, because inline scripts aren't allowed.
- **Spike S2** loads the bundle in NetView's shell under the real CSP and records exactly what (if anything) it blocks: workers from `blob:`, `'unsafe-eval'`, `'wasm-unsafe-eval'`. The page's CSP is the core document's (§3), so loosening it on GeoTrace's own responses would not help the page. **My call** on how to handle the outcome:
  - Nothing blocked: carry on.
  - Only Cesium's **workers** need something (for example wasm): workers loaded from a URL follow the CSP of their own response, so the bundle route may send that one extra directive on worker scripts only. The page's policy does not change.
  - Anything the **page itself** needs: **stop the build and bring it back to the user** with the options: a core feature for plugin-owned full pages with their own CSP, an iframe allowed by `frame-ancestors 'self'` on one route, a global CSP change (an anti-goal), or switching to MapLibre. Each is a different plan, so it is not pre-decided here.

## 13. Permissions

- **Manifest:** `api`, `ui`, `storage:own`, `network:probe` (traces and pings) and the new `network:internet` (tiles, DB-IP, Cesium download, Nominatim).
- **User permissions** (automatic ones only, no custom ones):
  - *view*: open GeoTrace and see targets, traces, comparisons and trends;
  - *use*: add, edit or delete targets, run Trace now / Trace once / Ping only;
  - *configure*: settings (home location, retention, tile source, cache cap, data updates).
- **Audit:** adding, editing or deleting a target, Trace once and settings changes are recorded with `ctx.audit`. Scheduled traces are not audited.
- Tile and bundle routes need *view*.

## 14. Spikes before building (in this order)

- **S1 — OSM through the server.** From NetView's server, with the §11 User-Agent, fetch a handful of OSM tiles at a few zooms. Record whether they are real tiles or the "Access blocked" image, what headers come back, and whether a blocked tile can be recognised. If OSM refuses, settle the default source with the user before building §11.
- **S2 — Cesium under the CSP** (§12).
- **S3 — Traceroute parsing.** Capture `tracert` output on this PC (English Windows) to a reachable host, an unreachable one and one with silent hops, and `traceroute`/`tracepath` output on a Linux box (the Proxmox host is available). These become the parser fixtures.

## 15. Left to the builder, and later work

**Left to the builder:** module layout inside the plugin; the exact API shapes beyond those named here; chart details; how the moving packet is animated; how the blade stack is implemented; whether settings state lives in settings or its own table (§7); test strategy (follow the other plugins: Python tests in `plugins/geotrace/tests/`, JS helper tests in `tests/js/`).

**Later (not v1):** MaxMind GeoLite2 and RIPE IPmap sources (§8.4); Esri World Imagery as a base layer once its terms are checked; reading city or airport codes from router host names; comparing a site's IPv4 route with its IPv6 route side by side; export of a trace (KML/GeoJSON); notifications beyond Events.
