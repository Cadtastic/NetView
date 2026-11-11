# netview Roku plugin: design

Date: 2026-11-11. Status: approved mockup, design written for planning. Anything marked **my call** was decided by Claude and not discussed with the user; the user can overturn it.

Mockup the user approved: `HomeLab/mockups/roku-plugin-mockup.html` (open it in a browser; it inlines netview's real CSS and uses sample data). Where this document and the mockup differ, this document wins, and each difference is called out.

## 1. Intent

The user has Roku TVs on the home network and a public "Roku ECP Cheat Sheet" page (https://claude.ai/artifact/Ht7ryUfS2ZhvqDkErYRbhp) built around the shared-library script `R:\source\scripts\network-tools\scripts\find_rokus.py`. They want that in netview as a plugin, so the "god's eye view" app can also **find and drive the TVs**:

- a **Roku page** with one tab per TV that works as a **remote control** sending commands straight to the TV;
- the same page can switch to a **Commands** view that is the cheat sheet, with every command filled in for the selected TV;
- **finding TVs is built in**, and Settings shows how to run the scan by hand and lets the user view and edit the saved TV list as JSON;
- with no TVs found, the Roku page can't be opened.

## 2. Goals, non-goals, anti-goals

**Goals**

- Discover Rokus on the LAN from inside netview, the same way `find_rokus.py` does (SSDP `roku:ecp` search plus a GET of `/query/device-info` on port 8060 across the subnet).
- Keep a saved TV list that the user can see and edit as JSON in Settings, and that a scan updates without throwing away the user's edits.
- Control each TV from the browser: power, navigation, playback, volume, inputs, launching installed apps, typing text.
- Show each TV's live state (power, Network access setting, app on screen, reachable or not) and draw the TV on or off to match.
- Give the cheat sheet a home in netview: copyable commands for PowerShell, Command Prompt and macOS/Linux, aimed at the selected TV.

**Non-goals**

- Wake-on-LAN or waking a TV that is fully powered down (not in standby). ECP can't reach it; the UI says so.
- Changing the TV's Network access setting. ECP can't; the UI tells the user where it is on the TV.
- Deep links into content (`/launch/{id}?contentId=`), `/input`, `/search/browse`, media-player position control from the Control view. They stay in the Commands view as copyable commands only.
- Naming or typing devices in the core device list from Roku data. A possible later addition (section 11).
- Screen mirroring, casting or anything other than ECP.

**Anti-goals (a failure even if it works)**

- **netview becomes a way to send HTTP requests to arbitrary hosts.** The API takes a saved TV's id, never an address, and only sends allow-listed ECP paths (section 6.1).
- **A scan overwrites what the user typed.** A tab name the user set must survive every scan (section 5.2).
- The remote feels laggy or unreliable: a press that silently does nothing. Every press gets visible feedback, success or the TV's error in plain words.
- Hammering the TVs. Status polling is light (section 5.4).
- Breaking netview's plugin rules (netview spec §7): the plugin imports only `netview.sdk`, owns only `roku_` tables, ships a CSP-compatible no-build UI, and uses theme tokens for all UI colour.

## 3. Decided by the user

- It is a netview plugin, built from the cheat sheet and `find_rokus.py`.
- **Page layout:** a tab control with one tab per discovered TV, and a **Control | Commands** toggle right-justified on the same line as the tabs. **Control is the default.**
- **Control** acts as a remote for the selected TV. **Commands** shows the cheat sheet (quick-copy commands and the rest of the reference) using the selected tab's TV address.
- **An SVG drawing of a Roku TV** on the Control view: a lit screen when the TV is on, a blank screen when it is off.
- **Scanning for TVs is built in.** **Settings** shows how to run the scripts manually and shows the saved TV list as JSON, viewable and editable there.
- **If no TVs are detected, the Roku tab is disabled.**
- The user saw and approved the mockup (Control view, Commands view, disabled tab, Settings › Roku) with all the guesses it carried.

## 4. Constraints

- Everything in `docs/superpowers/specs/2026-11-10-netview-design.md`: Clean Architecture layers and import-linter contracts, `netview.sdk` as the only import surface, `roku_` table prefix, own Alembic branch, settings in `plugin_state` applied live, the slot-based plain-JS UI, no inline scripts (CSP), theme tokens only (app.css rule), Settings dialog with one tab per plugin (§13.1).
- Current SDK is 1.3 (after the GSM7248 plugin and settings tabs). This plugin needs small core additions (section 8), so SDK goes to **1.4**.
- ECP facts (from the cheat sheet, tested on the user's TVs): plain HTTP on port 8060, no authentication. Reads are GET, commands are POST with an empty body. A GET to a command path is 404. The TV's **Network access** setting is the only access control:
  - **Default:** reads and commands allowed from private LAN addresses;
  - **Permissive:** same, from any address;
  - **Limited:** `device-info` and `active-app` work, `apps` and `media-player` return 403, every POST returns 403;
  - **Disabled:** nothing answers.
  `power-mode` in `device-info` is `PowerOn` when on and `DisplayOff` (or `Ready`/`Headless`) in standby. `PowerOn` / `PowerOff` / `Power` keys work on Roku TVs only. A fully powered-down TV doesn't answer at all.
- netview runs on the user's laptop on the same LAN as the TVs (Starlink LAN 192.168.1.0/24 today; it moves to OPNsense VLANs later, so nothing about the subnet is hard-coded).
- Shared scripts library rules (`R:\source\scripts\README.md`): a project copy of a library script lives in the project's repo; using the script from a new project means adding that project to the script's `projects` list in `scripts.json`.

## 5. Architecture

### 5.1 Plugin shape *(my call; mirrors Starlink and GSM7248)*

A **local plugin folder** `plugins/roku/` at the netview repo root, a sibling of `src/` (user's instruction, see section 13). It is not a built-in: no entry point, not in the wheel, loaded through `plugin_dirs`. Contents:

- `plugin.py`: the `Plugin` subclass. id `roku`, name "Roku". Permissions: `storage:own`, `api`, `ui`, `network:probe`, and a new `network:control` (section 8.2).
- `ecp.py`: a small ECP client. GETs and POSTs with a proxy-less urllib opener (as `find_rokus.py` does, so an HTTP proxy in the environment is never used), 2 s timeout by default, response size cap, XML parsed with the same DOCTYPE/ENTITY refusal as `find_rokus.py`. Parses `device-info`, `active-app`, `apps`.
- `discovery.py`: the built-in scan. SSDP via `ctx.probes.ssdp_search(st="roku:ecp")` (a new parameter, section 8.3; today the probe always sends `ST: ssdp:all` and its `target` argument is a unicast IP), keeping replies whose `LOCATION` is `http://<ip>:8060/`, plus a parallel `/query/device-info` sweep of the subnet (bounded thread pool; a /22 or smaller is swept, as in the script). Same result fields as `find_rokus.py`, plus `serial` (`serial-number` from device-info).
- `storage.py`, `migrations/`: the saved list (section 5.2).
- `service.py`: owns the saved list, the live status cache, the scan lock, command sending.
- `routes.py`: the plugin API (section 6).
- `settings.py`: the settings model (section 5.5).
- `static/`: `ui.js` (registers slots), `page.js`, `control.js`, `commands.js`, `settings.js`, `tv.js` (the drawing), `roku.css`, and the two manual scripts (section 7.3).

### 5.2 The saved TV list

**Stored in the plugin's own table** `roku_tvs`, one row per TV *(my call; the mockup said `netview-dev/roku/tvs.json`, but plugins have no data-dir access and keep their data in their own tables. The user still sees and edits it as JSON, and can download it as `tvs.json`.)*

Fields per TV:

| Field | From | Notes |
|---|---|---|
| `id` | netview | Stable short id used in API paths. Never shown as editable. |
| `serial` | scan | `serial-number` from device-info. The identity used to match a TV across scans. May be empty for entries pasted from the manual script. |
| `ip` | scan or user | Updated by every scan that finds the TV. |
| `name` | scan | The TV's own name (user-device-name, else friendly, else default). Updated by scans. |
| `label` | **user only** | Optional tab name. A scan never writes it. Tab shows `label` or else `name` or else `ip`. |
| `model`, `location`, `tv` | scan | `tv` is `is-tv`. |
| `found_by` | scan | `ssdp`, `sweep` or `ssdp+sweep`. |
| `first_seen`, `last_seen` | netview | ISO timestamps. |

Order in the list is tab order. New TVs are appended.

*(my call, differs from the mockup's JSON)*: power state and Network access mode are **live** state, not saved data, so they are not stored in this list. The mockup's JSON showed them because it reused the script's output.

**Merging a scan** into the list:

1. Match by `serial` when both sides have one, otherwise by `ip`.
2. Matched: update `ip`, `name`, `model`, `location`, `tv`, `found_by`, `last_seen`. Never touch `label` or order.
3. Not matched: append.
4. **Nothing is ever removed by a scan.** A TV that a scan didn't find stays, and shows as not answering. The user removes TVs by editing the JSON.
5. If a scan finds a TV at an address another saved entry holds (DHCP reshuffle), the TV with the matching serial gets the address and the other entry keeps its old `ip`. The identity check in 5.4 stops that stale entry from showing or controlling the TV that now holds the address. *(my call)*

**Allowed addresses** *(my call, from the builder check)*: a saved `ip` must be a private IPv4 address (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16), the same range a TV on Default network access accepts commands from. It is not limited to netview's own subnet, because the TVs may sit on another VLAN after the OPNsense cutover and the manual scan exists for other subnets. Loopback, link-local, multicast and public addresses are refused with a message naming the entry. The same rule applies to every address in a pasted list before netview fetches anything from it.

**JSON document** shown in Settings *(my call)*:

```json
{
  "schema": "netview.roku/tvs@1",
  "tvs": [
    {"id": "a1b2c3", "serial": "X01234567890", "ip": "192.168.1.60", "name": "Living Room TV",
     "label": "", "model": "TCL 55S455", "location": "Living Room", "tv": true,
     "found_by": "ssdp+sweep", "first_seen": "2026-11-11T14:41:00Z", "last_seen": "2026-11-11T14:41:00Z"}
  ]
}
```

**Saving from the editor** decides by what was pasted:

- A `netview.roku/tvs@1` document **replaces** the list (that is how the user removes, reorders and relabels). `id` may be omitted for new entries; netview assigns one. Unknown fields are rejected with a message naming them.
- Output of `find_rokus.py` (schema `ketiv.network-tools/roku-scan@1` or the public page's `roku-scan@1`), the PowerShell script's array, or a plain list of IP addresses one per line is **merged** exactly like a scan. For a bare IP list, netview fetches device-info for each address before merging; addresses that don't answer as a Roku are reported and skipped.
- Validation errors show inline under the editor and nothing is saved. A save reports what happened ("Saved: 3 TVs" / "Merged: 1 added, 2 updated").

### 5.3 Discovery *(my calls)*

- **Scan now** in Settings runs a scan in the background; one scan at a time (a second request gets 409 "scan already running").
- **Automatic scans** setting, default **on startup and every 6 hours** (shown in the mockup). Options: never, on startup, on startup and every N hours.
- Subnet: netview's own subnet setting (the LAN discovery subnet). A /22 or smaller is swept; anything larger is refused for the sweep, as in the script, and SSDP still runs.
- The last scan's time, duration and counts are kept in memory and shown in Settings ("3 found: 2 by SSDP and address check, 1 by address check only. Took 4.6 s").

### 5.4 Live status *(my calls)*

- A job polls every saved TV every **10 s** (setting, 5 to 300 s): GET `/query/device-info` and, when that answers and the TV is on, `/query/active-app`. In memory only; no history.
- After any command, that TV's status is re-read about 1 s later so the drawing and facts catch up.
- **Identity check** *(my call, from the builder check)*: every status read compares device-info's `serial-number` with the saved `serial`. An entry with no serial (pasted from the manual script) adopts the first serial it sees, and that is saved. On a mismatch the status is `wrong_device` ("A different Roku, *name*, now answers at this address. Run a scan in Settings."), the tab shows it as not answering, and its controls are disabled. The command endpoints refuse (409, same message) unless the TV's identity was confirmed within the last 2 status intervals; when it is older than that, the server re-reads device-info first and sends only on a match. So a stale tab can never power off another TV.
- Installed apps (`/query/apps`) are read when the TV first answers, then at most once an hour, and on demand when the Control view opens. A 403 (Limited mode) is remembered and the Control view falls back as described in 7.1.
- Per TV status: `reachable` (bool), `power` (`on` / `standby` / `unknown`), `mode` (`default` / `permissive` / `limited` / `disabled` / `""`), `active_app` (name and id, or Home, or screensaver), `apps` (list or `null` if refused), `checked_at`, `error` (plain words, e.g. "Not answering on port 8060").

### 5.5 Settings model

| Setting | Default | Notes |
|---|---|---|
| `auto_scan` | `startup_and_every` | `never`, `startup`, `startup_and_every` |
| `scan_every_h` | 6 | 1 to 168, used with `startup_and_every` |
| `scan_timeout_s` | 2 | per address and for SSDP replies |
| `status_interval_s` | 10 | 5 to 300 |
| `request_timeout_s` | 2 | ECP calls |

No setting is required, so the plugin is always "configured"; the page gating comes from the saved list (section 8.1), not from the settings schema.

## 6. API (`/api/v1/plugins/roku/`)

All under the core's existing API protections (localhost, the core's CSRF header rule for writes).

| Method and path | Does |
|---|---|
| `GET tvs` | Saved list with each TV's live status. Drives the page and the nav gating. |
| `GET tvs/document` | The JSON document for the Settings editor. |
| `PUT tvs/document` | Save the editor's text: replace or merge per 5.2. Body is the raw text. |
| `POST scan` | Start a scan. 202, or 409 if one is running. |
| `GET scan` | Last and running scan: state, started, finished, counts, error. |
| `POST tvs/{id}/key/{key}` | Keypress. Optional `?action=down|up` for keydown/keyup. |
| `POST tvs/{id}/launch/{app}` | Launch an app id, or `tvinput.hdmi1`..`hdmi4`, `dtv`, `cvbs`. |
| `POST tvs/{id}/text` | JSON `{"text": "..."}`, up to 100 characters; sent as `Lit_` keypresses in order. |
| `POST tvs/{id}/refresh` | Re-read status and apps now. |
| `GET tvs/{id}/icon/{app}` | The app icon, proxied from the TV and cached in memory. |
| `GET scripts/find_rokus.py`, `GET scripts/find_rokus.ps1` | The manual scripts (7.3), as text. |

### 6.1 Safety rules for commands

- The address always comes from the saved list by `id`. No endpoint accepts a host or URL.
- `key` must be in the allow-list: the cheat sheet's keys (Home, Back, Up, Down, Left, Right, Select, Info, InstantReplay, Search, Play, Rev, Fwd, VolumeUp, VolumeDown, VolumeMute, PowerOff, PowerOn, Power, InputTuner, InputHDMI1..4, InputAV1, ChannelUp, ChannelDown, Backspace, Enter, FindRemote) or `Lit_` plus exactly one character, URL-encoded by the server.
- `app` must match `^[0-9]{1,10}$` or `^tvinput\.(hdmi[1-4]|dtv|cvbs)$`.
- Command results map to plain words returned as JSON and shown in a toast: 200 → ok; 403 → "This TV's Network access setting (Limited) refuses commands"; 404 → "The TV doesn't know that key or app"; timeout/refused → "The TV isn't answering. It may be fully powered off or have a new address."

## 7. Web UI

### 7.1 Roku page, Control view (default)

Layout as in the mockup:

- **Tab row:** page-level `.tabs`, one tab per saved TV, label per 5.2. A dot before the name: green = on, grey = standby or not answering, amber = Limited. Tooltip: address, state, mode. The **Control | Commands** segmented control (`.seg`) sits **right-justified on the same line** as the tabs. The selected tab and view are remembered in the browser (localStorage, wrapped in try/catch) *(my call)*.
- **TV card (left):** the TV drawing (7.4), then name, model, location, address, and fact pills: Power (On / Standby / Not answering), Network access (Default / Limited / ...), On screen (app name; only when on), Updated (how long ago).
- **Remote card (right):** Power (shows "Off" when on and sends PowerOff; shows "On" when off and sends PowerOn), Back, Home; a round direction pad with OK; Instant replay, Options (Info), Search; Rewind, Play/Pause, Fast forward; Vol −, Mute, Vol +; inputs HDMI 1–4, Antenna, AV.
  - Click sends a keypress. **Holding** an arrow, Rewind or Fast forward sends keydown, then keyup on release (also on pointer leave and window blur, so a key is never left held) *(my call)*.
  - **Keyboard** while the page has focus and no text field does: arrows, Enter = OK, Backspace = Back, Escape = Back, H = Home, Space = Play/Pause *(my call; the mockup's hint listed arrows, Enter, Backspace, Esc)*.
  - Each press shows a short toast; errors use the wording in 6.1.
- **Apps card:** a grid of the TV's installed apps with their real icons (via the icon proxy), the running app outlined. Click launches. If the TV refuses `/query/apps` (Limited), the card says so and shows the cheat sheet's common-apps list without icons (still disabled, since Limited refuses launches too).
- **Type text card:** a text box, Send, and a ⌫ button (Backspace). Note: "Open the app's search box first."
- **Limited mode:** a callout at the top ("This TV refuses commands...", with the path `Settings › System › Advanced system settings › Control by mobile apps › Network access › Default`) and every control disabled. Reads still update.
- **Not answering:** facts say "Not answering", the drawing is off, the controls are disabled with a note: "netview can't reach this TV. It may be fully powered off (standby still answers) or have a new address: run a scan in Settings." *(my call)*
- **Non-TV Rokus** (sticks and boxes, `tv: false`): they get a tab too and the same drawing (it is the TV the stick drives); TV-only controls (power, inputs, antenna) are hidden *(my call)*.

### 7.2 Roku page, Commands view

The cheat sheet, rebuilt from the artifact's content, with every command filled in for the **selected tab's** address:

- A bar with **Commands for** PowerShell / Command Prompt / macOS-Linux (default from the browser's platform, remembered), "Every command targets *name* at *ip*:8060", and section links.
- Sections and their content as in the cheat sheet: **Recipes**, **Read state**, **Control**, **Remote keys** (click a key to show its command; the "type text" builder), **App IDs** (this TV's installed apps when known, else the common list, each with a launch command), **Network access settings** table, **What the responses mean**.
- Every command has a Copy button. Clipboard failure selects the text and says to press Ctrl+C, as the cheat sheet does.
- The cheat sheet's **Find TVs** and **Discovery** sections move to Settings (7.3); its own theme picker is dropped (netview's themes apply).
- Limited mode shows a one-line callout that POST commands will return 403.

### 7.3 Settings › Roku

The plugin's Settings tab (§13.1 of the netview spec) shows the generated settings form and, through the `settings.section` slot, three sections as in the mockup:

1. **Scan:** last scan summary, **Scan for TVs now** (disabled while one runs, then refreshes the list and the nav), and the automatic-scan choice (the generated form's `auto_scan`/`scan_every_h` fields; placement within the tab is left to the builder).
2. **Saved TVs:** a monospace textarea with the JSON document, **Save**, **Revert**, **Download** (`tvs.json`), and an inline validation/result line. One sentence explains the replace-versus-merge rule from 5.2 and that scans never remove or rename.
3. **Run the scan yourself:** for another computer or subnet.
   - Windows / macOS-Linux switch.
   - The command to run the library script: `python R:\source\scripts\network-tools\scripts\find_rokus.py --out rokus.json` on Windows, `python3 find_rokus.py --out rokus.json` on macOS/Linux, with its options.
   - **Paste-into-a-terminal versions** for a computer without the file: the whole Python script wrapped in a PowerShell here-string piped to `python -` (Windows) or a bash heredoc into `python3 -` (macOS/Linux), and the **PowerShell-only** version for PCs without Python. Each with Copy.
   - "Paste what it prints into Saved TVs above and press Save."

The scripts are **copies kept in the plugin** (`static/find_rokus.py`, `static/find_rokus.ps1`), served by `GET scripts/...` and fetched by the settings section. `find_rokus.py` is a byte-identical copy of the library version (schema id `ketiv.network-tools/roku-scan@1`), ASCII only, with no line that is exactly `EOF` or `'@` (they would end the paste wrappers). The `.ps1` is the cheat sheet's PowerShell script. **Source for both, and for the cheat sheet's exact command strings, key list, app list and recipes:** `docs/superpowers/reference/roku-ecp-cheat-sheet.html`, a saved copy of the user's published cheat sheet (the `src-ps` and `src-py` script blocks, and the `READ`, `CONTROL`, `KEYS`, `APPS`, `RECIPES`, `build` and `readField` code). The `.ps1` prints a JSON array of `{ip, name, model, location, tv, mode, power}`; the merge accepts that shape. A test checks both rules. Add "HomeLab netview - Roku plugin manual scan (2026-11-11)" to the script's `projects` in `scripts.json` and follow README §4.5.

### 7.4 The TV drawing

An inline SVG built by `tv.js` (`tvSvg({on})`), as in the mockup:

- A thin black bezel with a small "ROKU TV" wordmark (plain text, not Roku's logo) centred on the bottom bezel, two angled feet, a soft floor shadow.
- **On:** a generic home screen: purple gradient, "HOME" and a clock top corners, a left menu column, a 3×3 grid of coloured tiles with the first one outlined. No real Roku UI artwork, logos or channel artwork. The status light is dark.
- **Off (standby or not answering):** a blank near-black screen with a faint diagonal reflection, and a **red standby light** on the bottom bezel.
- `role="img"` with an aria-label ("Living Room TV is on").
- **Colour exception** *(my call)*: the drawing is a picture of a physical object, so its fills are fixed colours rather than theme tokens, like the GSM7248 faceplate. The feet must stay visible on dark themes (the mockup lightened them to `#3c3f46`).

### 7.5 Disabled tab

With **no saved TVs**, the Roku nav tab is shown greyed and can't be opened, styled like a plugin that needs setup. Tooltip: "No Roku TVs found yet. Click to open Roku settings and scan." Clicking it opens **Settings › Roku**. A saved list with TVs that are all off or not answering keeps the tab enabled *(my call: "detected" means "in the saved list")*. The tab becomes enabled as soon as a scan or a save puts the first TV in the list, without a page reload. This needs the core change in 8.1.

## 8. Core changes (SDK 1.4)

### 8.1 A page can declare itself unavailable

Today a nav tab is disabled only when the plugin's settings are incomplete (`needsSetup` in `nav.js`). Add an optional `unavailable()` to the `page` slot spec: it returns `null` when the page can open, or the tooltip text when it can't. `navItems` disables the tab when either `needsSetup` or `unavailable()` says so; clicking a disabled tab still opens that plugin's settings (the existing `data-setup` behaviour). Today `requestRender()` only redraws the current page; change the shell so it also re-renders the nav, so the Roku plugin can enable or disable its tab without a reload. `pickRoute` already falls back from a disabled route. The Roku plugin answers `unavailable()` from its cached `GET tvs` result, fetched at registration, after its own scans and saves, and **every 30 s while the list is empty** so an automatic scan that finds the first TV turns the tab on *(my call; plugins have no server push today, and polling only while empty costs nothing once TVs exist)*. It calls `requestRender()` when the result changes. Covered by the nav unit tests.

### 8.2 New permission `network:control`

Add `NETWORK_CONTROL = "network:control"` to `Permission`, with the plain-language chip "Sends commands to devices on your network". Recorded and shown, not enforced, like the others.

### 8.3 SSDP search target

Add an optional `st: str = "ssdp:all"` parameter to `ServiceProbes.ssdp_search` and its adapter in `infrastructure/net/probes.py`, sent as the `ST:` header. Existing callers keep today's behaviour. Add a test for a custom ST. *(my call, from the builder check: it keeps the plugin on the shared SSDP adapter instead of opening its own socket.)*

Bump `SDK_VERSION` to "1.4"; the Roku plugin requires ≥ 1.4.

## 9. Testing

- **Python (pytest):** ECP parsing (device-info, active-app, apps, XML with DOCTYPE refused); merge rules in 5.2 (serial match, IP match, label kept, nothing removed, address reshuffle, private-address rule); the identity check in 5.4 (serial adopted, mismatch blocks status and commands, stale confirmation re-read before a command); document validation and the replace/merge decision for each accepted input; command allow-lists (keys, `Lit_` encoding, app ids, rejecting anything else); status mapping of 200/403/404/timeout. A fake ECP server (local `http.server` on 127.0.0.1) serves fixture XML for device-info, active-app, apps, and records POSTs, with switchable Limited mode and power state. Discovery tested with a fake `ssdp_search` and the fake server.
- **JS (`tests/js/*.test.mjs`, existing pattern):** nav `unavailable()` gating; command string builders for all three shells (match the cheat sheet's output); tab label choice; TV SVG on/off markup.
- **Static checks:** the script-copy rules in 7.3; ruff, mypy, import-linter as today.
- **Browser check by Claude** before calling it done (netview memory: a mechanical-only gate missed visual bugs): the four mockup screens against the fake ECP server, both a dark and a light theme, a narrow window, keyboard control, and hold-to-scroll. A **live check against the user's real TVs** at the end, with the user's OK before sending commands to them.

## 10. Delivery order *(my call)*

1. Core: `unavailable()` page gating with nav re-render, `network:control`, the SSDP `st` parameter, SDK 1.4.
2. Plugin skeleton, ECP client, storage and migration, saved-list document with replace/merge, API for list and document.
3. Discovery (scan now, automatic scans) and Settings › Roku (scan, JSON editor, manual scripts).
4. Live status job; Roku page with tabs, toggle, TV drawing and Control view.
5. Commands view (cheat sheet port).
6. Browser pass, live check on the real TVs, `scripts.json` entry.

Work on a feature branch (`feature/roku-plugin`), per the user's usual flow.

## 11. Later (not in this plan)

- Claim device names and type "Roku TV" for the matching core devices (an `IdentityProvider`).
- Show the running app's icon on the drawn TV screen instead of the generic home screen.
- Events when a TV turns on or off or changes address.
- Media-player bar (position, duration) on the Control view.

## 12. Left to the builder

- Exact module split inside the plugin and the JS file split.
- How the scan's parallel sweep is pooled and bounded, within the /22 and timeout rules.
- `id` format for saved TVs.
- Icon cache size and lifetime.
- Placement of the generated settings fields relative to the three custom sections in Settings › Roku.
- Responsive breakpoints, as long as the Control view stacks to one column on narrow windows and nothing scrolls sideways.

## 13. Amendment (2026-11-11): not a built-in plugin

The user asked that the Roku plugin **not be a built-in** and that it live in a **`plugins` folder that is a sibling of `src`**. This overrides every earlier mention of `netview/plugins/builtin/roku/` and of an entry point.

- **Location:** `netview/plugins/roku/` (repo root `plugins/`, next to `src/`). Code, `static/`, `migrations/` and the plugin's own tests (`plugins/roku/tests/`) all live there.
- **Loading:** netview's existing folder discovery (`AppSettings.plugin_dirs`, `discover_plugin_classes(extra_dirs=...)`). `plugins/roku/__init__.py` exposes `plugin_class`; at runtime the package is `netview_local_plugins.roku`. No `pyproject.toml` entry point; the wheel does not include it.
- **Running it** *(my call)*: `netview serve` gains a repeatable `--plugin-dir PATH` option, and the user's `netview` launch configuration adds `--plugin-dir R:/source/claude projects/HomeLab/netview/plugins` after the merge. `plugin_dirs` in `netview.toml` or `NETVIEW_PLUGIN_DIRS` keep working as before.
- **Plugin rules still hold:** the plugin imports the core only through `netview.sdk`. import-linter does not cover code outside `src/`, so an AST test in the plugin's tests enforces it.
- **Checks:** pytest's `testpaths` and the `npm test` glob include `plugins/`; ruff and mypy run over `plugins/roku` too.
