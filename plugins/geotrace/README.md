# GeoTrace

GeoTrace is a NetView plugin that traces the route to places you care about and draws the hops on a 3D globe.

## What it does

- You save targets (a host name or an IPv4 or IPv6 address).
- Each target is traced on a schedule, or once when you ask.
- The hops are placed on a globe, with the route drawn as arcs from your home location.
- Compare shows two traces of the same target side by side and marks the hops that changed.
- Trends shows how hop count and delay change over time.

Hops are listed even when no location is known for them. They just are not drawn.

## Permissions

The plugin asks for these permissions. They are listed in `plugin.json`.

| Permission | Why |
| --- | --- |
| `api` | The plugin serves its own routes. |
| `network:internet` | New in SDK 2.1. The plugin downloads files and map tiles from the internet (see the next section). |
| `network:probe` | It runs traceroute and ping against your targets. |
| `storage:own` | It keeps its own tables and a files folder. |
| `ui` | It adds the GeoTrace page and three Settings sections. |

It needs SDK 2.1 or newer.

## Outbound connections

GeoTrace contacts these hosts. Nothing is sent to any other host. The browser never contacts them directly. NetView's server makes every request, and the page loads everything from NetView's own address.

| Host | Why | Source | Can the administrator turn it off or replace it? |
| --- | --- | --- | --- |
| The targets themselves | Traceroute and ping probes (`network:probe`). | `runner.py` | Remove the target. |
| `tile.openstreetmap.org` | Street map tiles for the part of the globe on screen, fetched by NetView's tile proxy and cached on disk. | `tiles.py:61` | Yes. Settings > Map > Map tile source can be set to a custom tile server. |
| A custom tile server | Used instead of OpenStreetMap when you choose "Custom tile server". The address must be https:// and contain `{z}`, `{x}` and `{y}`. | `settings.py:27`, `settings.py:95`, `tiles.py` | Yes. It is your own setting. |
| `tiles.maps.eox.at` | Sentinel-2 cloudless imagery, only when Settings > Map > Globe imagery is set to Sentinel-2. | `tiles.py:69` | Yes. The default is Natural Earth, which is built in and makes no request. |
| `nominatim.openstreetmap.org` | Address search when you pick your home location. Your search text is sent only when you press Search. | `geocode.py:14` | No setting. It is used only when you search. |
| `download.db-ip.com` | The free DB-IP City Lite and ASN Lite files that place each hop. Checked once a day, downloaded once a month. | `geodata.py:24` | Yes. Turn off "Update location data automatically". Without the files, hops are listed but not placed. |
| The Cesium bundle URL (`BUNDLE_URL`) | One-time download of the globe library. | `bundle.py:23` | It is pinned in the plugin. It is empty today (see the bundle step). |

Requests carry the user agent `NetView-GeoTrace/0.1.0 (+https://github.com/Cadtastic/NetView)`. The OpenStreetMap tile and Nominatim servers have usage policies. Use a custom tile server if you need heavy use.

GeoTrace does not send your traces or hop addresses to any location service. Hops are placed from the local DB-IP files.

MaxMind GeoLite2 and RIPE IPmap are not built yet. They are planned as options the administrator turns on with their own account details. Settings > Location data shows them as "coming later".

## Attribution

The page and Settings show these credits. Keep them when you change the plugin.

- Street map: "© OpenStreetMap contributors" (tiles and address search).
- Locations: "IP geolocation by DB-IP", linked to https://db-ip.com. The DB-IP Lite files are licensed CC BY 4.0.
- Sentinel-2 imagery (when selected): "Sentinel-2 cloudless – https://s2maps.eu by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2020)". It is free for non-commercial use only.
- Built-in globe imagery: "Natural Earth".
- The globe is drawn with CesiumJS.

## The Cesium bundle

The globe needs CesiumJS. The library is not stored in the repository, because a plugin install copies the whole repo. The plugin downloads a trimmed copy on first use and checks its size and SHA-256. It keeps the copy in its files folder and serves it from NetView's own address, so the page's content security policy stays strict.

To build the bundle (a maintainer does this):

1. Download the official CesiumJS 1.144.0 release zip.
2. Run a dry run, then build it:

   ```
   uv run python plugins/geotrace/tools/build_cesium_bundle.py --release-zip Cesium-1.144.zip --out DIR
   uv run python plugins/geotrace/tools/build_cesium_bundle.py --release-zip Cesium-1.144.zip --out DIR --execute
   ```

   `--version` changes the version in the file name (the default is 1.144.0). `--json` prints a report.
3. The tool writes `geotrace-cesium-1.144.0.zip`. It keeps only the files the globe uses and applies two small patches to `Cesium.js` so it runs under NetView's content security policy. If Cesium's text is not what the patches expect, the tool fails and writes nothing.
4. Publish the zip as a release asset, then set `BUNDLE_URL`, `BUNDLE_SHA256` and `BUNDLE_BYTES` in `plugins/geotrace/bundle.py`.

Status today: the zip is not published, and those three values are still empty. Until they are set, Settings > Map shows the globe files as not published and the globe cannot load.

## Where data is kept

- The plugin's own tables in NetView's database: targets, traces and hops, and the plugin's state. Old traces are removed after the retention time you set.
- The plugin's files folder, `files_dir`: the DB-IP files, the cached map tiles (limited by the tile cache size setting) and the Cesium bundle.
- When you uninstall the plugin, NetView removes the files folder. Choose "delete data" in the uninstall dialog to remove the tables too.
