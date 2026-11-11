# Plugin gallery: Installed and Available, and status dots

Date: 2026-11-11. Status: draft for the user's review. Branch `feature/plugin-gallery` (worktree
`R:\source\claude projects\HomeLab\netview-plugin-gallery`), cut from main at `ab5498e`.

Mockup: [2026-11-11-plugin-gallery-mockup.html](2026-11-11-plugin-gallery-mockup.html) (v10; open it in a browser,
hover the dots). The plugins on its Available page are examples.

## Why

The Settings dialog lists every plugin as its own entry in the left menu (Health, Identity, This device,
NETGEAR GSM7248, …). That list grows with every plugin and there is no way to find or add a plugin that is not
on disk. The user wants plugins to be browsed like an app store: a gallery of what is installed, and a gallery of
what can be installed from the public repository (`github.com/Cadtastic/NetView`, folder `plugins/`). All plugins
there are open-source freeware; anyone may install any of them.

The user also wants the new status dots used elsewhere in the core app where they make sense.

## Goals

- Settings menu: **Plugins** becomes a collapsible group with two items, **Installed** and **Available**.
- **Installed** shows every installed plugin (built-in and folder) as a card. Clicking a card opens that plugin's
  settings in an overlay.
- **Available** shows every plugin in the repository's `plugins/` folder that is not installed here, as a card with
  its info and an **Install** button.
- Install shows a progress bar (downloading, then installing). When done, the card disappears from Available and
  appears in Installed with a flashing red **Awaiting restart** dot.
- A plugin's status is a coloured dot in the top-right corner of its card; the status text is its tooltip.
- The same dots replace status labels elsewhere in the core app where that makes sense (see "Dots elsewhere").
- Custom plugins still work the way they do today: a folder dropped into `<data dir>/plugins` is loaded at the next
  start. Before that restart it also shows in Installed as Awaiting restart.

## Non-goals

- No hot loading. A new plugin loads when netview restarts, as turning one on or off already does.
- No restart button. (netview runs under `uv run netview serve`; restarting itself is a separate feature.)
- No uninstall and no update in this change. Both go in `deferred.md` (see "Later").
- No plugin icons. Cards show a monogram tile (first letter of the name). Icons can come later via `plugin.json`.
- No signatures, approvals or allow-list. The user chose: anyone can install anything in the folder.
- No changes to external plugins (GSM7248, Starlink, GS105E, Roku). Their pages keep their own status styling.
  The only thing they gain is a `plugin.json` file (see below).
- No installing Python packages. A plugin that needs a package netview does not ship cannot be installed (its card
  says why).

## Anti-goals

- Installing must never write outside `<data dir>/plugins/<id>`. A crafted archive (`../`, absolute paths,
  symlinks) must not escape it.
- A failed or interrupted install must not leave a half-copied folder that the loader would try to import.
- Opening Settings must never block on the network. Available renders from the cache at once and refreshes in the
  background.
- The per-plugin entries must not survive anywhere in the menu; the gallery is the only way to a plugin's settings.
- Moving status dots must not hurt readability: the tooltip is always fully opaque, and a reduced-motion setting
  stops every animation.

## Decisions the user made

- `plugin.json` per plugin folder, plus an index the app fetches and caches: "perfect".
- Install = copy into `<data dir>/plugins`, then restart: "this is fine".
- Remove the per-plugin menu entries; gallery access only.
- Build in its own worktree and branch. This is part of the core app, **not** a plugin.
- Install flow: progress bar while downloading and installing; then the card leaves Available and shows in
  Installed with an Awaiting restart label (now a red dot).
- Anyone can install anything from the folder.
- Status labels become a coloured dot in the card's top-right corner, 16px, with the text in a tooltip.
- Every dot has a soft glow in its own colour. Green (Active) pulses outward. Amber (Needs configuring) slowly
  fades in and out. Red flashes on and off.
- The tooltip stays fully visible while the dot fades or flashes. The cursor over a dot is the normal one (no `?`).
- Capability chips stay as labels: solid fill, bold white text, single line, padding left and right, text centred.
- Reuse the dots elsewhere in the app where it makes sense; leave external plugins alone.
- Testing: a local fake of GitHub before merge; one real install from GitHub after the user merges and pushes.

## Settings menu

```
Appearance
▾ Plugins
    Installed   8
    Available   2
```

- Clicking **Plugins** (or Enter/Space on it) collapses or expands the group. It starts expanded. The open/closed
  state is remembered per browser (localStorage, wrapped in try/catch).
- Installed and Available are tabs in the existing vertical tab list. Arrow keys move through visible tabs only.
- Each item shows a count. **Installed** also carries a small (10px) still dot when something needs attention:
  red if any plugin failed or awaits a restart, else amber if any needs configuring; no dot otherwise.
- The old per-plugin entries and their `Failed` / `Set up` badges are removed.
- Tab ids: `appearance`, `plugins:installed`, `plugins:available`. `openSettings("plugins")` keeps working and
  opens Installed. `openSettings("plugin:<id>")` (used by a disabled top-bar page) opens Installed with that
  plugin's overlay open.

## Installed gallery

A responsive grid of cards (three columns at the dialog's width, fewer when narrow), with a filter box that
matches name and description. Order: plugins needing attention first (failed, awaiting restart, needs
configuring), then by name.

Each card:

- Monogram tile, name, version and source: `Built in`, `Folder`, or `Just installed` for one awaiting its first
  load.
- Status dot in the top-right corner (see "Status dot").
- Description.
- Capability chips (solid labels, see "Chips").
- Footer: the on/off switch (as on the current overview). A plugin awaiting its first load shows
  "Loads the next time netview starts" instead of a switch. A failed plugin's switch is disabled, as today.
- The whole card is a button; Enter/Space opens the overlay. The switch does not open it.

Plugins awaiting their first load are folders under any plugin folder whose `plugin.json` id is not among the
loaded plugins. Their card is built from `plugin.json`. This also covers a custom folder the user copied in by hand.
A folder without `plugin.json` that is not loaded is not shown (it may be a work-in-progress folder like today's
`plugins/gs105e`).

A folder plugin that failed to import (my call): today the host records it under the id `folder:<absolute path>`
with the path as its name (`infrastructure/plugins/host.py`, `load_all`). When that folder has a `plugin.json`, the
record takes the `plugin.json` id, name and version instead, so it shows **once**, as Failed, and is not also
counted as awaiting first load. Its overlay shows the import error and no form; toggling is disabled. Without a
`plugin.json` it keeps today's path-based record. The pending rule is therefore: a folder whose `plugin.json` id
matches neither a loaded plugin nor a failed record.

`PluginInfo.state` and the API's `PluginOut.state` are `Literal` types; they gain `"pending"`. Every JS consumer of
`/api/v1/plugins` (top-bar nav, `needsSetup`, plugin UI loading) must ignore pending entries.

## Plugin settings overlay

- A second modal `<dialog>` on top of the Settings dialog (nested `showModal` is supported). It is about 720px
  wide, scrolls inside itself, and dims the gallery behind it.
- Content is what the per-plugin tab shows today, unchanged in behaviour: header (monogram, name, version,
  status dot, Enabled switch, close button), description, error lines, the needs-configuring note, "What it can
  do", "Access it asks for", the settings form with its tabs, and the plugin's own `settings.section` contributions.
  `renderPlugin` is reused, with one change: today it redraws itself after a toggle or save by calling
  `ctx.select("plugin:<id>")` (`settings/plugins-tab.js`), and `select()` sends unknown tab ids to Appearance. Once
  the per-plugin tabs are gone that would jump the dialog away, so the overlay passes its own redraw hook through
  `ctx` (for example `ctx.redraw()`), and the gallery redraws the card when the overlay closes.
- Close button, Esc, or a click on the dim area closes the overlay only. Focus returns to the card. The gallery
  keeps its scroll position and redraws the card (a save may change its status).
- A plugin awaiting its first load opens an overlay with its `plugin.json` info and the note "This plugin loads the
  next time netview starts. Its settings appear after that." and no form.

## Available gallery

- Header: "Available plugins", a line "From github.com/Cadtastic/NetView · checked 4 min ago" (or the error, see
  below), a filter box, and a **Refresh** button.
- Cards like Installed, without a status dot: monogram, name, version, "by <author>", description, capability
  chips, and a footer with **Install**.
- A plugin is listed when its id is neither loaded nor awaiting its first load.
- When a plugin cannot be installed here, the Install button is disabled and the footer says why:
  - its `sdk_version` is not met by this netview's `SDK_VERSION` → "Needs a newer netview";
  - a package in its `requires` is missing → "Needs <package>, which this netview does not have".
- While installing, the footer becomes a progress bar plus a line: "Downloading… 62%", then "Installing…".
  Other cards stay usable; one install runs at a time (a second Install click waits with "Queued").
- On success the card leaves Available, the Installed count goes up, and a toast says
  "<name> installed. Restart netview to load it." The new card in Installed has the red Awaiting restart dot.
- On failure the card stays, the footer shows the error in red, and Install is enabled again.
- Empty states: "Every available plugin is installed." / "No plugins found." and, if the catalog could not be
  read and nothing is cached, "Couldn't reach GitHub. Check the connection and press Refresh."

## Status dot

One CSS component in `app.css`, class `sdot` (the name `.st` is already taken by the device status text).

| State | Colour token | Motion | Tooltip text |
|---|---|---|---|
| Active | `--ok` | ring pulses outward, ~2s loop | Active |
| Needs configuring | `--warn` | fades slowly in and out, ~3s loop | Needs configuring |
| Awaiting restart | `--bad` | flashes on/off, 1s | Awaiting restart |
| Failed | `--bad` | flashes on/off, 1s | Failed: <first line of error> |
| Off | `--border-strong` | none | Off |

Precedence on a plugin card: failed → awaiting restart (first load, or `restart_required`) → off → needs
configuring → active.

Rules:

- Size 16px on cards and in the overlay header; a 10px variant (`sdot sm`) for rails, menus and tables.
- Every dot has a soft glow ring in its own colour (about 4px, ~30% opacity), made with
  `color-mix(in srgb, var(--x) 30%, transparent)`. `app.css` stays free of hex and `rgb()` literals; all colours
  come from theme tokens, so all four themes (Graphite, Harbor, Daylight, Contrast) work.
- The element is a still container. The coloured disc is its `::before`, and only that animates. The tooltip is a
  separate layer that never animates, so it stays fully opaque while the dot fades or flashes.
- Tooltip: a CSS tooltip shown on hover of the dot and while its card has keyboard focus; text from `data-tip`.
  The dot also has `role="img"` and `aria-label` with the same text, and the card's accessible name includes it.
- Cursor: the normal cursor (the card's own pointer on cards). Never `cursor: help`.
- Reduced motion: `@media (prefers-reduced-motion: reduce)` sets `animation: none` on the disc explicitly. The
  existing global rule only shortens durations, and an infinite animation at 0.01ms would flicker.
- A `still` modifier turns motion off where many dots sit together (tables).
- Because each state also moves differently (pulse, fade, flash, still), the state is not carried by colour alone
  when motion is on. With reduced motion, the tooltip and accessible name carry it.

## Chips

The capability chips on the plugin cards and in the overlay use the user's label style: solid fill, bold white
text, one line (`white-space: nowrap`), 12px padding left and right, text centred both ways, fixed height ~20px.
New class `chip solid` so the existing `.chip` used elsewhere does not change.

Colours (my call): two new optional theme tokens, `--chip-bg` and `--chip-fg`, read in `app.css` as
`var(--chip-bg, var(--border-strong))` and `var(--chip-fg, var(--text))`, so user themes in `<data dir>/themes`
without them still work. Graphite and Harbor can rely on the fallback (white on a mid grey). Daylight and High
contrast must set them, because the fallback there is dark text on grey (Daylight) and white on `#cfcfcf` (High
contrast, about 1.6:1). Every built-in theme pair must reach at least 4.5:1. The themes README documents the two
tokens as optional.

## Dots elsewhere in the core app

My calls, for the user to check:

1. **Settings rail:** the Installed item's attention dot (above).
2. **Watches card** (`cards/watches.js`, `statusChip`): each watch's status chip becomes a 16px dot at the top
   right of its row, with motion: up = green pulse; degraded and present ("On the network only") = amber fade;
   down and absent ("Not on the network") = red flash; pending = grey still. Tooltip and `aria-label` carry the
   existing label text. There are only a handful of watches, so motion is not noisy. `tests/js/cards.test.mjs`
   covers `statusChip` and changes with it.
3. **Top-bar navigation:** a plugin page that needs configuring (today greyed out with a tooltip) gets a 10px
   amber fading dot after its name. Its existing tooltip stays.
4. **Devices table, Status column:** the 8px `dot-s` becomes a 10px `sdot sm still` with the glow and no motion.
   With 40+ rows, pulsing or flashing would be noise, and offline phones are normal. The word next to it (Online,
   Quiet, Offline) stays, since the column is sorted and read. Online = `--ok`, Quiet = `--warn`,
   Offline = `--bad`, unknown = `--idle`.
5. **Left alone:** the top-bar live indicator (its single ring per data update already means something specific),
   the device `New` / `Watched` badges (they are tags, not statuses), and everything inside external plugins.

## plugin.json

Every folder plugin carries a `plugin.json` next to its `__init__.py`. It mirrors the Python manifest so the app can
describe a plugin without importing it.

```json
{
  "schema": "netview.plugin/1",
  "id": "gsm7248",
  "name": "NETGEAR GSM7248",
  "version": "0.1.0",
  "description": "Ports, VLANs, spanning tree, traffic and device-to-port mapping for the GSM7248 switch over SNMP",
  "author": "Cadtastic",
  "homepage": "https://github.com/Cadtastic/NetView/tree/main/plugins/gsm7248",
  "license": "MIT",
  "sdk_version": ">=1.3,<2",
  "capabilities": ["api", "web_ui", "storage", "jobs"],
  "permissions": ["api", "devices:read", "names:write", "network:probe", "storage:own", "types:write", "ui"],
  "requires": []
}
```

- Required: `schema`, `id`, `name`, `version`, `description`, `sdk_version`, `capabilities`, `permissions`.
  Optional: `author`, `homepage`, `license`, `requires` (distribution names, checked with
  `importlib.metadata`).
- The repository has no LICENSE file yet (checked 2026-11-11). Until the user adds one, `license` is left out of
  the plugin.json files; the example's "MIT" is only an example. The card shows the license when present.
- A test in the core suite walks `plugins/*/plugin.json` and fails when a file disagrees with its plugin's Python
  manifest (id, name, version, description, sdk_version, capabilities, permissions), so the two cannot drift.
- `gsm7248` and `starlink` get their `plugin.json` in this change. The GS105E and Roku branches add theirs when they
  land (note this in the plugin authoring docs).
- The loader does not require `plugin.json`; a folder without one still loads as today. It is only needed to be
  listed in Available, and to show in Installed before the first load.

## The catalog: index, cache and bundled copy

- **Index file:** `plugins/index.json` in the repository, built by a project script
  (`scripts/build_plugin_index.py`, Python stdlib, `--help`, dry run unless `--execute`) from every
  `plugins/*/plugin.json`. It holds `{"schema": "netview.plugin-index/1", "generated": <iso time>, "ref": "main",
  "plugins": [<plugin.json objects plus "path": "plugins/<id>">]}`. A test fails if the committed index is out of
  date with the `plugin.json` files.
- **Where netview reads it:** `AppSettings.plugin_catalog_url`, default
  `https://raw.githubusercontent.com/Cadtastic/NetView/main/plugins/index.json`. A fork can point it elsewhere.
- **Cache:** a new core table `plugin_catalog` (Alembic migration) with one row per plugin (the plugin.json fields,
  `path`, `ref`) and a one-row `plugin_catalog_meta` (source URL, fetched_at, last error). The builder may merge
  these if a single table reads better.
- **Bundled copy:** each release ships `src/netview/infrastructure/plugins/catalog.json`, a copy of
  `plugins/index.json` made by the same script. When the cache is empty (first start, or offline), it is loaded
  from the bundled copy. This is the "pre-cached table per release" the user offered.
- **Refresh:** when Available is opened and the cache is older than one hour, the server refreshes it in the
  background and the page updates when done. **Refresh** forces it. A failed refresh keeps the old cache and shows
  "Couldn't reach GitHub · showing the list from <date>". An HTTP error (for example 404 because the index is not
  on `main` yet) shows the same way with the status code: "Couldn't read the plugin list (404) · showing the list
  from <date>" (my call).
- The request sends nothing about the user or the network: a plain GET with a generic `User-Agent: netview/<ver>`.
  Timeout 10s. Response size cap 1 MB.

## Install

- `POST /api/v1/plugins/install` `{ "id": "<plugin id>" }` → `202 { "job": "<id>" }`, or 409 if it is already
  installed or awaiting load, 404 if not in the catalog, 422 if it cannot be installed here (with the reason).
- `GET /api/v1/plugins/install/<job>` → `{ "state": "queued|downloading|installing|done|failed", "percent": 0-100,
  "error": null }`. The page polls it every ~300ms while a job runs. Jobs live in memory; one runs at a time.
- Download: the GitHub archive of the catalog's `ref`
  (`https://codeload.github.com/Cadtastic/NetView/zip/refs/heads/<ref>`, derived from the catalog URL's owner and
  repo), streamed to a temp file under `<data dir>/plugins/.staging/`, with percent from `Content-Length` (when it is
  missing, the bar is indeterminate). Size cap 50 MB. Timeout per read 30s.
- Extract only entries under `<top>/plugins/<id>/`, skipping `tests/` and `__pycache__/`. Reject any entry that
  would land outside the staging folder, any absolute path, and any symlink. Stop at 20 MB unpacked.
- Check the staged folder: `__init__.py` and `plugin.json` exist, and `plugin.json` id equals the requested id.
- Move it into place with one rename to `<data dir>/plugins/<id>`. If that folder appeared meanwhile, fail with 409
  and delete the staged copy. Always delete the temp archive and staging folder, on success or failure.
- On startup, delete a leftover `.staging` folder. The loader already skips folders without `__init__.py`; it must
  also skip names starting with `.`.
- Whether the archive download or per-file raw downloads (tree API + raw.githubusercontent) is used is the
  builder's call, as long as the progress bar and the checks above hold. The archive is one request and is not
  rate limited; it grows with the repo.

## Server-side shape

Follows the project's Clean Architecture layout; exact names are the builder's call.

- `PluginInfo` gains `source: "builtin" | "folder"` and `pending: bool` (awaiting first load). `GET
  /api/v1/plugins` also returns pending folders (built from their `plugin.json`, state `"pending"`, `enabled` true,
  no settings).
- Application ports: a catalog reader (fetch index), a catalog store (the cache), an installer. Infrastructure:
  HTTP fetch with `urllib`, the zip installer, the SQL store. Presentation: `GET /api/v1/plugins/catalog`
  (`{fetched_at, source, error, plugins: [...] }` with each entry marked `installable` and `reason`),
  `POST /api/v1/plugins/catalog/refresh`, and the install endpoints above.
- No new runtime dependencies.

## Tests

- Unit: index builder; plugin.json ↔ manifest agreement; catalog parse and validation (bad schema, missing fields,
  oversized); installability rules (sdk, requires, already installed, pending); installer path checks with crafted
  zips (`../`, absolute, symlink, wrong id, missing `__init__.py`, over size); atomic move and clean-up on failure;
  pending-folder detection; loader skips dot folders.
- API: catalog endpoint with a fake fetcher; install job happy path and failure with a local zip served by a fake.
- JS (the repo's existing `node --test` setup): rail grouping and collapse, tab ids and `openSettings` mapping,
  card status precedence, filter, dot markup and tooltip text.
- Browser pass (done by the agent, not only mechanical gates): all four themes, reduced motion, keyboard path
  through rail → card → overlay → Esc, and the dots on the Watches card, top bar and Devices table. Installs in
  this pass use a **local fake of GitHub** (a small server that serves an `index.json` and a zip built from this
  branch's `plugins/`, with `plugin_catalog_url` pointed at it) into a throwaway data dir. The user chose this
  over pushing the branch.
- **After the user merges and pushes:** one real install from `github.com/Cadtastic/NetView` `main` into a throwaway
  data dir, to confirm the live catalog and archive download. Nothing is pushed by the agent before that.

## Later (goes into docs/superpowers/deferred.md)

- Uninstall a folder plugin (remove folder on next start; decide what happens to its tables and settings).
- Update: show "Update available" on an Installed card when the catalog has a newer version.
- Plugin icons from `plugin.json`.
- A restart button.
- Pin the catalog `ref` to a release tag once releases exist (the repo has no tags or releases yet).

## Left to the builder

- Exact component split in JS (new `settings/gallery.js`, `settings/overlay.js`, etc.).
- Table layout for the cache, migration naming, job store details.
- Archive versus per-file download (see Install).
- Daylight-theme token for white chip text, with contrast checked.
