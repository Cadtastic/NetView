# Plugin identity, types and uninstall: design

Date: 2026-11-12. Branch `feature/plugin-identity`. Status: draft for the user's approval.

Items marked **(my call)** were decided by Claude and not discussed with the user. Everything else was agreed in conversation.

## 1. Why

Three things the user wants:

1. **Uninstall.** A plugin the user installed should be removable from the Plugins gallery. Today you can only switch plugins on and off.
2. **Grouping.** Every plugin says what kind of hardware (or software) it is for, from a fixed list, so later features can group and categorise plugins.
3. **Identity that can't be faked by renaming a folder.** Today a plugin is known by its short author-written `id` (`gsm7248`), which is also its folder name, web address, table prefix and settings key. Folder plugins load in alphabetical folder order. A copy of `roku` renamed `aaa_roku` therefore loads first, and the real Roku plugin fails as a "duplicate". The user wants a plugin's identity to be a guid. Two plugins with the same name must never be confused, and a renamed copy must never break startup or replace the original.

## 2. Goals, non-goals, anti-goals

**Goals**
- Uninstall for plugins that live in `<data dir>/plugins`, and only those.
- New required plugin fields: `guid`, `display_name`, `plugin_type`.
- The author-written `id` goes away. NetView assigns each registered plugin a numeric `source_id`, which is used in links and web addresses.
- Each plugin keeps its tables in its own SQLite database file, so table names need no prefix.
- Duplicate or conflicting plugin folders never stop NetView from starting, and never displace the plugin that was already working.
- The existing `netview-dev` data (settings, Roku TV list, GSM7248/GS105E history, Starlink counters) moves over with nothing lost.

**Non-goals**
- Grouping or filtering the UI by `plugin_type`. This change only adds the field; using it is a future feature. The gallery card may show the type as a chip **(my call)**.
- Unloading a plugin's Python code without a restart (Python can't do that cleanly).
- Uninstalling built-in plugins or plugins loaded from `--plugin-dir` / `plugin_dirs`.
- Updating or upgrading plugins in place.

**Anti-goals (failure even if it "works")**
- Uninstall deleting anything outside `<data dir>/plugins/<folder>` (and the plugin's own data file, when asked). In particular it must never delete from the repo folder: the dev server loads the GSM7248, Starlink, Roku and GS105E plugins from `netview-main/plugins` through `--plugin-dir`.
- Any plugin folder (broken, duplicate, renamed copy, bad `plugin.json`) making NetView fail to start.
- Losing the user's existing plugin settings or history in the move.

## 3. The new plugin fields

These go in `PluginManifest` (Python) and in `plugin.json`. All three fields are **required**: a plugin missing one does not load and shows a failed card with the reason.

**New rule, enforced at load time:** a folder plugin must have a valid `plugin.json`, and it must agree with the manifest on every field they share. A mismatch makes the plugin fail to load. Today this is only checked by a test, `tests/integration/plugins/test_plugin_json_agreement.py`, for the repo's own plugins. The loader imports any folder that has an `__init__.py` and never reads `plugin.json`.

| Field | Written by | Meaning |
|---|---|---|
| `guid` | author | A UUID, written in lower case in the standard 8-4-4-4-12 form. The plugin's permanent identity: it registers the plugin, keys its saved state and settings, names its data file, matches Installed against Available, and drives uninstall. It never changes across versions. |
| `display_name` | author | Short label, used for the plugin's nav tab and as the name for the device it represents, e.g. `GSM7248`, `GS105E`, `Roku`, `Starlink`. |
| `plugin_type` | author | One value from the list in §3.1. |
| `name` | author (existing) | Kept. It is the full name shown as the gallery card heading, e.g. "NETGEAR GSM7248" **(my call: keep `name` for cards and use `display_name` for tabs and devices)**. |
| `id` | — | **Removed** from the manifest and from `plugin.json`. |
| `source_id` | NetView | A positive integer the core database assigns the first time a guid is registered (§4). Never written by the author. |

### 3.1 `plugin_type` values

`router`, `switch`, `access_point`, `firewall`, `modem`, `server`, `nas`, `computer`, `tv`, `printer`, `camera`, `ups`, `iot`, `software`, `other`.

- `tv` covers TVs and streaming boxes.
- `iot` covers smart-home devices.
- `software` is for plugins that are not tied to one piece of hardware.
- `other` is the catch-all when none of the others fits.

The list is a closed enum in the SDK (a `PluginType` StrEnum). An unknown value is an error, both in the manifest and in `plugin.json`.

### 3.2 Values for the existing plugins

| Plugin | display_name | plugin_type |
|---|---|---|
| gsm7248 | GSM7248 | switch |
| gs105e | GS105E | switch |
| starlink | Starlink | router (it reads the Starlink router) |
| roku | Roku | tv |
| health, identity, inspection, lan_discovery, local_host (built-ins) | their current `name` | software |

The builder generates one fresh guid per plugin.

### 3.3 SDK version

The SDK version goes to **2.0** **(my call)**. The change breaks existing plugins: there is no `id`, the new fields are required, and storage moves to an unprefixed file of the plugin's own. Every plugin in the repo moves to `sdk_version ">=2.0,<3"`. The `plugin.json` schema id becomes `netview.plugin/2` and the index schema becomes `netview.plugin-index/2`.

## 4. Registration and `source_id`

- A new core table holds one row per guid ever registered: `guid` (unique), `source_id` (integer, assigned automatically), plus whatever bookkeeping the builder needs, such as the folder it last loaded from.
- **The row is never deleted, including on uninstall** **(my call)**, so a reinstall gets the same `source_id` and saved links keep working.
- `plugin_state` (the enabled flag, settings and installed version) is keyed by **guid**.
- **Runtime keys use `source_id`.** This covers web addresses (`/api/v1/plugins/<source_id>/…`, `/plugins/<source_id>/static/…`), UI routes (`#/p/<source_id>/<page>`), scheduler owners, the capability registry and Python module names (`netview_local_plugins.p<source_id>`).
- **Persisted references use guid.** A persisted `source_id` would only be meaningful on one install. The builder audits every current use of `plugin_id` and sorts each one into persisted or runtime. The known persisted one is `inspection_reports.sections_json` (`plugin_id` per section, `repositories.py:295`).
- **Claim source labels are not identities and stay as they are (my call).** The `source` on name claims, type claims and hints (`"GSM7248"`, `"GS105E"`, `"DHCP"`, `"inspection"`, …) is a display and ranking label (`domain/naming.py`), not a plugin key. It is not re-keyed and its schema does not change. Folder plugins that name a device take that label from `ctx.display_name` instead of hard-coding it, which gives the same text for the existing plugins (`service.py` `SWITCH_ID`/source constants).
- Plugin code must not hard-code its own address. It gets its `source_id` and API base from the host: `ctx` on the Python side, `pluginId`/`apiBase` on the JS side. The one hard-coded link today is `plugins/gs105e/static/report.js` (`#/p/gs105e/switch`), and it must change. The JS side also needs the plugin's **guid**: `report/dialog.js:19` matches a saved section's `plugin_id` (now a guid) against the live slot spec, so slot specs gain `pluginGuid` and the match uses it.
- The config-file plugin seeds (`AppSettings.plugins`, today keyed by plugin id) become keyed by guid, so `plugins/conftest.py` changes to match.

## 5. Loading, folders and conflicts

- **Folder names stop mattering.** For a folder plugin, NetView reads `plugin.json` first (for the guid), looks up or assigns the `source_id`, then imports the folder as `netview_local_plugins.p<source_id>`. A friendly folder name like `plugins/gsm7248/` stays in the repo.
- **Every guid loads at most once.** When two or more found plugins share a guid, exactly one loads, picked in this order (never alphabetically):
  1. the built-in one;
  2. then the one in the folder the guid last loaded from successfully (so a working plugin is never displaced by a new copy);
  3. then plugins from `--plugin-dir` / `plugin_dirs` before `<data dir>/plugins`;
  4. then by folder path, as a last stable tie-break.
- **Each one that doesn't load** shows in the Installed gallery as a failed card (red dot) with a reason such as "Same guid as Roku (loaded from …)". If that card's folder is in `<data dir>/plugins`, it has an Uninstall button.
- Every existing failure path stays non-fatal: an unreadable `plugin.json`, a manifest and `plugin.json` that disagree, a missing field, an unknown `plugin_type`, an import error or a setup timeout all produce a failed card, and NetView starts normally.
- Built-in (entry-point) plugins take their guid from their manifest. They have no `plugin.json`.

## 6. Storage: one database file per plugin

- A plugin with storage gets its own SQLite file at `<data dir>/plugin-data/<guid>.db` **(my call on the folder name)**. The file is created on first load. Its Alembic version table is plain `alembic_version` inside that file.
- **Table names have no prefix.** For example, `gsm7248_port_samples` becomes `port_samples`. The prefix check (`validate_storage`) and the per-table write fence go away. The plugin's engine instead denies `ATTACH` (and `DETACH`), so it can't reach `netview.db` or another plugin's file.
- If a plugin today reads core tables through its own session, that read becomes a core-facade call, because core tables aren't in its file. The builder checks; none is expected.
- The four plugins with storage (gsm7248, gs105e, roku, starlink) get their table names and their migration files rewritten to the unprefixed names. Revision ids stay the same, so the moved version row still matches (§7).
- The PluginContext's `close()` disposes the plugin's engine, as it does today, so that uninstall can delete the file on Windows.

## 7. Moving the existing data (one time)

The dev database (`network/netview-dev/netview.db`) holds plugin data under the old ids. On the first start of the new version, before plugins load:

1. **Back up `netview.db` first,** next to it, as `netview.db.bak-<date>-before-plugin-identity`. The name follows the hand-made `…-before-0003` backup; no backup code exists yet, so this step is new code. It runs only when the move has work to do, and is skipped if the backup file already exists. Use SQLite's backup API, not a file copy, because the database is in WAL mode.
2. A core migration creates the registration table and re-keys `plugin_state` from the old ids to guids. It uses a fixed map of the nine known legacy ids to their new guids, which lives in core code. Rows for unknown ids are left alone and logged; they belong to no current plugin.
3. For each of the four storage plugins whose `<legacy id>_*` tables exist in `netview.db` while its new data file does not exist yet:
   - create `<data dir>/plugin-data/<guid>.db`;
   - copy each table into it with the prefix removed, keeping its schema and indexes;
   - copy the `alembic_version_<legacy id>` revision into the file's `alembic_version`;
   - only after every copy has succeeded, drop the old tables from `netview.db`.
   A failure at any step leaves `netview.db` untouched for that plugin and logs the error.
4. It runs once and is safe to repeat: a plugin whose file already exists is skipped.
5. The persisted plugin references from §4 (the `plugin_id` of each `inspection_reports.sections_json` section) are re-keyed from legacy id to guid in the same migration. Claim source labels are not touched (§4).

**Coordination with `feature/auth-stage1`:** another session is building that branch (14 commits, not merged). It adds core migration `0004_auth.py` and stores per-plugin permission ids `<plugin_id>.view/.use/.configure` in `role_permissions.permission_id`. Its middleware parses `/plugins/<id>/static`, and `PluginContext.require` prefixes the plugin id. Under this design, stored permission ids must use the **guid**, and the middleware must map a `source_id` in a URL back to the guid.

**Decided by the user: auth merges first, and this branch adapts.** Concretely:
- Before implementation starts, this branch is rebased onto main, after auth has merged. If auth isn't merged by then, the plan's auth-touching tasks wait for it.
- This branch's core migration is numbered after auth's `0004`.
- The one-time move (step 5 above) also re-keys `role_permissions.permission_id` from `<legacy id>.<action>` to `<guid>.<action>`.
- `PluginContext.require` uses the guid.
- The auth middleware maps `/plugins/<source_id>/…` and `/api/v1/plugins/<source_id>/…` back to the guid before checking a permission.

## 8. Uninstall

**Who gets the button.** A card shows **Uninstall** only when its folder is inside `<data dir>/plugins`:
- active, disabled or failed plugins;
- duplicate/conflict cards (§5);
- "Just installed" pending ones.

Built-in cards and repo-folder (`--plugin-dir`) cards never show it, and the server refuses the request for them too. The button sits on the card's settings overlay, not the card face, so it can't be clicked by accident **(my call)**.

**Confirm dialog** **(my call on the wording and the checkbox)**:
- "Uninstall Roku? Its folder is deleted. It stops now and is fully gone after netview restarts."
- An "Also delete its saved settings and data" checkbox, unchecked by default.
- Cancel / Uninstall (danger style).

**Uninstall is addressed by folder, not by `source_id` (my call).** Duplicates share a guid and so a `source_id`. A failed card may have no guid at all, and a pending folder may not be registered yet. Every Installed card therefore gets a stable card key (the folder path for folder plugins, the guid or entry point for built-ins), and the gallery keys cards by it instead of by `id` (`gallery.js:75` today).

**Saved data belongs to the guid's owner (my call).** The owner is the folder the guid is loaded from, or last loaded from (§5). Only the owner's card offers "Also delete its saved settings and data". For a duplicate, failed-without-guid or pending card the checkbox is hidden and the server refuses `delete_data`. Uninstalling a renamed copy can then never wipe the working plugin's settings or history.

**What the server does** (`POST /api/v1/plugins/uninstall` with `{folder, delete_data}`, where `folder` is the folder's name under `<data dir>/plugins`):
1. It refuses (409) unless the folder resolves to a direct child of `<data dir>/plugins`. The resolved-path check also blocks symlinks and junctions, `..`, and names starting with `.`.
2. If the folder's plugin is running, it stops it: removes its scheduler jobs, unregisters its providers, calls `shutdown()` and closes its context (which disposes its engine).
3. It moves the folder to `<data dir>/plugins/.trash/<folder>-<timestamp>`, then deletes it **(my call)**. A half-deleted plugin can then never load. Anything left in `.trash` is cleared at the next start, the same way `.staging` is.
   - **If the move itself fails** (Windows refuses to rename a folder with an open file), the folder's path is recorded as "uninstall pending" in the core database **(my call)**. At the next start, before discovery, pending folders are moved to `.trash` and deleted and are never loaded. The plugin stays stopped until then.
4. If `delete_data` is set (owner only), it deletes the plugin's data file (and its `-wal` and `-shm` files) and its `plugin_state` row. Otherwise both are kept, so a reinstall picks up the old settings and history.
5. It drops the plugin from the list. The registration row stays (§4).
6. After this, its API routes and static files answer **404 until restart**. FastAPI can't unmount a router, so a guard on `/api/v1/plugins/<source_id>` and `/plugins/<source_id>/static` checks whether the plugin is still present.

**What the user sees:**
- The card leaves Installed and the plugin's nav tab disappears without a reload.
- If the catalog (remote, or the bundled copy) lists the guid, the plugin shows in Available again, installable as usual.
- A toast confirms, e.g. "Roku uninstalled".
- If deletion fails partway (for example a locked file on Windows), the plugin stays stopped. The card says "Uninstall didn't finish: <reason>. It will be removed when netview restarts", and the next start finishes the job: it clears `.trash` and removes any folder marked "uninstall pending".

## 9. Catalog and install

- The Available gallery matches installed plugins by **guid**, no longer by id.
- In index entries, `path` no longer has to equal `plugins/<id>`. It must be a safe relative path under `plugins/`.
- Install puts the plugin in `<data dir>/plugins/<last segment of path>`. If a folder with that name already exists for a different guid, it adds `-2`, `-3` and so on **(my call)**. Installing a guid that is already installed or loaded is refused.
- `scripts/build_plugin_index.py` and its `--check` mode handle the new fields. The bundled `catalog.json` and `plugins/index.json` are regenerated.
- The public GitHub index changes schema when main is pushed. Older NetView builds can't read the new index and will fall back to their bundled list. That is acceptable, because the only installs are the user's.

## 10. UI details

- **Nav label:** the plugin's `display_name`. If a plugin ever registers more than one page, the label is "display_name · page title" **(my call)**. The page slot's own `title` becomes optional.
- **Gallery card:** `name` as the heading, then "version · source" as today, and a `plugin_type` chip **(my call)**.
- **Enable/disable:** the existing On/Off switch, unchanged.

## 11. Tests and checks the builder must keep green

- The existing gates: pytest, npm tests, ruff, mypy on `src` and `plugins`, lint-imports, and `build_plugin_index.py --check`.
- New tests:
  - the guid conflict order (including the renamed-copy case);
  - a missing or invalid field for each new field;
  - an unknown `plugin_type`;
  - a manifest and `plugin.json` that disagree;
  - uninstall refused for built-in and `--plugin-dir` plugins and for paths that escape the plugins folder;
  - uninstall with and without `delete_data`;
  - `delete_data` refused for a duplicate, failed or pending card, with the owner's data file and settings left untouched;
  - a failed move to `.trash` leaving the folder marked "uninstall pending", and the next start removing it without loading it;
  - the 404 guard after uninstall;
  - the legacy data move, against a copy of a database with prefixed tables, including being safe to re-run;
  - a reinstall getting the same `source_id`.
- **Browser check** (done by Claude, not the user):
  - install a plugin from a fake repo into a scratch data dir, then uninstall it and see it return to Available;
  - drop a renamed copy into the data folder, restart, and see the original still active and the copy flagged;
  - confirm the dev data (`netview-dev`) survives the move: the Roku TV list, GSM7248 settings and Starlink history are still there. Run this against a **copy** of `netview-dev`, never the real one, until the user approves.

## 12. Left to the builder

- The schema of the registration table and the exact migration mechanics within §7's rules.
- How the 404 guard is implemented.
- How `ctx` exposes `source_id`, `guid` and `display_name`.
- Error message wording, apart from the dialog text above.
- How `plugins/conftest.py` imports plugins for tests, as long as plugin tests still run from their own `tests/` folders.

## 13. Decisions log

- 2026-11-12: auth (`feature/auth-stage1`) merges first, and this branch adapts (§7, Coordination).
