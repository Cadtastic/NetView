# netview GS105E switch plugin: design

Date: 2026-11-11. Status: initial design, updated the same day with a capture of the real switch (4.1). The user asked for a plugin "like the GSM7248, but only with the features it supports" and chose to skip the design questions. Everything not listed in section 3 is **my call** and is marked that way. Read it as a starting point to correct.

## 1. Intent

The NETGEAR GS105E is a 5-port "Plus" (smart managed) switch. In the home lab it sits at 192.168.1.3 on the Starlink LAN and splices two cable runs: Starlink → GS105E → OptiPlex → GSM7248 (`HomeLab/docs/hardware/gsm7248.md`). It is temporary there, but it is a common switch, and netview is public, so the plugin is written for any GS105Ev2, not just this unit.

netview should see this switch the way it sees the GSM7248: its identity, each port's link and speed, traffic, VLANs and the rest of its configuration, with events when something changes. It gets the same page layout, built on the drawn faceplate `plugins/gs105e/static/faceplate.svg`.

**What the switch can do** (Netgear GS105E/GS108E data sheet, D-GS105E/GS108E-DS-30May24; Netgear GS105Ev2 product page):

| Area | GS105E |
|---|---|
| Ports | 5 × 10/100/1000 copper; per-port LEDs show link/activity and speed; Power LED |
| VLANs | 64; port-based, or 802.1Q with tagging and PVIDs |
| QoS | port-based or 802.1p/DSCP priority; WRR or strict priority; per-port ingress/egress rate limits; broadcast storm control |
| Multicast | IGMP snooping v1/v2/v3, block unknown multicast, 128 groups |
| Monitoring | port status, port statistics (bytes in, bytes out, CRC errors), cable tester, many-to-one port mirroring (up to 4 sources), loop detection |
| Other | DoS prevention, jumbo frames (9K), 2K MAC table entries, DHCP client, system password, a management access list (Access Control), power saving (Green Ethernet) |
| **Not supported** | **SNMP**, LAG/trunking, spanning tree, PoE, CLI or SSH, syslog or traps, MAC address table display (confirmed by the capture, 4.1) |

**The unit in the lab** (read from its login page on 2026-11-11, no login needed): hardware **GS105Ev2**, firmware **1.6.0.11**. The login page's `<title>` is "NETGEAR GS105Ev2".

## 2. Goals, non-goals, anti-goals

**Goals**

- See the switch as a netview device: model, name, firmware, serial, MAC, IP, reachability.
- See all 5 ports: link, negotiated speed and duplex, configured speed, flow control, description, and VLAN, QoS, rate-limit, storm-control, mirroring and loop-detection settings.
- Live and historical per-port traffic (bits per second in and out) and CRC error counts.
- The rest of the configuration on one page, read-only: VLANs, QoS, IGMP snooping, mirroring, loop detection.
- Events when something changes: link up or down, speed change, CRC errors rising, loop detected, the switch unreachable or rebooted, configuration changed.
- Later: configuration changes from netview, made safely (section 7).

**Non-goals**

- **Device-to-port mapping,** the GSM7248's headline feature. It depends on reading the switch's MAC address table, and the capture confirmed that this switch has no page that lists learned MACs.
- SNMP, NSDP and the Netgear PC utility protocol (section 5.1).
- LAG, spanning tree, PoE, a console or SSH, firmware upgrades.
- Other Plus models (GS105E v1, GS108E, GS305E and so on). See section 8.

**Anti-goals (a failure even if it works)**

- **netview locks the user out of the switch's web page.** The switch is believed to allow one admin session at a time (to be checked live). Polling must leave a way for the user to log in themselves (section 5.3).
- **netview locks itself out:** retrying a wrong password until the switch refuses logins.
- Polling so often that the switch's small web server slows down or drops its own management.
- The password leaking: shown in the UI, written to logs, or returned by an API.
- Plugin code reaching into core tables or another plugin's code.

## 3. Decided by the user

- It is a netview plugin designed like the GSM7248 plugin, limited to what the GS105E supports.
- **It is an optional folder plugin, not built in:** `plugins/gs105e/`, with its own `tests/` folder, loaded through `--plugin-dir` or `<data dir>/plugins` like GSM7248 and Starlink.
- The faceplate is a head-on drawing made from the product photo: `plugins/gs105e/static/faceplate.svg`. Its overlay geometry is in its header comment.

## 4. Constraints

- Everything in the netview design spec (`2026-11-10-netview-design.md`):
  - the plugin SDK as the only netview import surface;
  - plugin tables prefixed `gs105e_`, created by the plugin's own Alembic branch;
  - settings in `plugin_state` that apply live, with `SecretStr` for the password;
  - settings tabs (SDK 1.3);
  - the no-build plain-JS UI with slots, CSP-compatible (no inline scripts);
  - theme tokens only, with two exceptions the GSM7248 plugin already makes: the drawn hardware colours of the faceplate, and the fixed VLAN palette (`gsm7248/static/port-grid.js`, eight colours that avoid green, red and amber), copied into this plugin *(my call)*.
- Folder-plugin layout as GSM7248 and Starlink have it today. Tests import the plugin as `netview_local_plugins.gs105e` through `plugins/conftest.py`.
- **No new dependencies.** HTTP goes through the standard library (`http.client`), as the Starlink plugin does. HTML is parsed with `html.parser` from the standard library.
- The address is a setting (default `192.168.1.3`), never a constant.
- Never write nicknames. The plugin claims a name, type and hints only through `ctx.core`.
- Python 3.11+, uv, ruff, mypy, pytest, `npm test`.
- **The repository is public.** Recorded pages used as test fixtures are scrubbed of the serial number, MAC addresses and anything else that identifies the unit before they are committed.

### 4.1 Facts about the web interface *(from the capture of the lab unit, 2026-11-11)*

The capture tool is `plugins/gs105e/tools/capture.py`. Scrubbed pages are in `plugins/gs105e/tests/fixtures/fw-1.6.0.11/`: the serial, MACs, private IPs, the form token and the login challenge are replaced with placeholders.

**Login and session**
- `GET /` and every page requested without a session answer **HTTP 200** with a small "Redirect to Login" page (`<title>Redirect to Login</title>`, `RedirectToLoginPage()`). There is no HTTP redirect or 401. The client recognises a lost session by that page (fixture `logged_out.html`).
- `GET /login.cgi` holds `<input type=hidden id='rand' value='…' disabled>`. **The value stayed the same across page loads** for the whole day, so it is not a per-request challenge. The page `<title>` is "NETGEAR GS105Ev2".
- `login.js` hashes the password as **`md5(merge(password, rand))`**: `merge` takes characters alternately from the two strings, then appends the rest of the longer one, and the MD5 is the standard one. The digest is posted as `password=<hex>` to `POST /login.cgi`. The password field allows at most 20 characters.
- A good login sets the cookie **`SID`**. A refused login sets no cookie. The client sends `SID` with every request and decodes gzip bodies.
- `GET /logout.cgi` ends the session.
- One page (`product_registration_popup.cgi`) answers with bare gzipped bytes, with no status line or headers. The plugin never reads that page, but the client treats a malformed reply as a page error, never as a crash.
- **Session behaviour** (measured with `capture.py --sessions-only --session-check 10`):
  - **Two sessions can be logged in at once.** A second login left the first one working, and both stayed valid. An earlier run that crashed without logging out did not block the next login either.
  - A session read every 30 s stayed valid for the full 10 minutes measured.
  - An idle session survived 1 minute and then 3 more minutes without a request.
  - Both logins came from the same PC. A login from a second device was not tested.

**Pages** (all `.cgi`; the `.htm` names that py-netgear-plus uses for other models return 404 here)

| Page | What it holds |
|---|---|
| `switch_info.cgi` | product name, switch name (`input#switch_name`), serial, MAC, bootloader, firmware, DHCP mode (`select#dhcpMode`), IP, mask, gateway |
| `info.cgi` | a short version: MAC, IP, mask, gateway, firmware |
| `status.cgi` | one `tr.portID` row per port: port, description, status (Up/Down), configured speed (`Auto`, `Disable`, `10M Half`, `10M Full`, `100M Half`, `100M Full`, codes 1–6), linked speed (`1000M`, `100M`, `10M`, `No Speed`), flow control (`Enable`/`Disable`), max MTU. Each shown value is followed by a hidden input with the same value or its code. |
| `portStatistics.cgi` | one `tr.portID` row per port with three high/low 32-bit pairs as hidden inputs: bytes received, bytes sent, CRC error packets. The counter is high × 2³² + low. |
| `8021qBasic.cgi`, `8021qCf.cgi`, `portBasedBasic.cgi`, `portBasedAdvanced.cgi` | the four VLAN modes, each an Enable/Disable radio. At most one is on. **All four are off on the lab unit.** |
| `8021qMembe.cgi` | membership for **one** VLAN at a time: `select VLAN_ID` (only 1 when VLANs are off) and `hiddenMem`, one character per port (`11111` on the lab unit) |
| `portPVID.cgi` | one `tr.portID` row per port with its PVID |
| `qos.cgi` | QoS mode: port-based or 802.1p/DSCP (the lab unit uses 802.1p/DSCP) |
| `rateLimit.cgi` | per port ingress and egress limit: codes 1–12 = No Limit, 512 Kbit/s, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512 Mbit/s |
| `broadCastFilter.cgi` | broadcast filtering (storm control) on or off |
| `igmp.cgi` | snooping on/off, VLAN for snooping, validate IGMPv3 IP header, block unknown multicast, static router port |
| `mirror.cgi` | mirroring on/off (`select mirroring`: 0 = Enable, 1 = Disable), destination port, sources as `hiddenMem` (`00000`) |
| `loop_detection.cgi` | loop detection on or off |
| `green_ethernet.cgi` | power saving mode on or off |
| `plus_utility.cgi` | management mode (web only, or web and Plus Utility) and TFTP via Plus Utility. **The lab unit is "Web browser only", so NSDP is off on it anyway.** |
| `ip_source.cgi` | **Access Control**: a list of source IP and mask allowed to manage the switch (empty on the lab unit) |
| `getstatus.cgi` | the word `disable`; its meaning is unknown and the plugin ignores it |

- Every page carries the same `<input name="hash">` value, the form token that writes need (phase 2).
- **There is no page that lists learned MAC addresses.** Device-to-port mapping is out for good on this model (section 2).
- Pages not read, because their names suggest an action: `cableTester.cgi`, `device_reboot.cgi`, `factory_default.cgi`, `backup_conf.cgi`, `restore_conf.cgi`, `fwug.cgi` (opened only as a form) and the password pages.

**Not seen, because the feature is off on the lab unit.** The parsers for these are written from the disabled page plus the help text, and get a fixture when the feature is first turned on:
- the VLAN pages with a mode on, and how to read membership for VLANs other than the one shown (the page selects one VLAN at a time, probably by posting `VLAN_ID`; whether that post is safe to use for reading must be checked before the plugin uses it);
- per-port QoS priority (shown only in port-based mode);
- per-port storm-control rates, if broadcast filtering on shows any;
- per-port loop state, if loop detection on shows any.

### 4.2 Firmware

- The lab unit runs 1.6.0.11. Netgear's notes say firmware 1.6.0.15 removed NSDP, and 1.6.0.6 made the web browser the default management mode. The web interface is the only access path that works on both old and current 1.6.x firmware, which is why the plugin uses it.
- The plugin reads the firmware version and shows it. A firmware it has not been tested with is shown as a warning, not a failure, as long as the pages still parse.

## 5. Architecture *(my calls)*

### 5.1 Transport: the switch's own web pages

The plugin logs in to the web interface like a browser and reads its pages. No core changes are needed: SDK 1.3 already gives settings with secrets and tabs, jobs, storage, events, claims and the UI slots.

Why not the alternatives:
- **SNMP:** the switch has none.
- **NSDP:** it works on the lab unit's 1.6.0.11, but Netgear removed it in 1.6.0.15, so a firmware update would break the plugin. Some fields need the password over NSDP anyway.
- **py-netgear-plus as a dependency:** it only reads switch info, port status and statistics, it pulls in `lxml` and `requests`, and it is built for many models. The plugin writes its own small client, using py-netgear-plus as a reference for the login and page layouts. It is credited in the module docstring.

### 5.2 Inside the plugin

`plugins/gs105e/` follows the GSM7248 layering:

| Module | Job | Imports |
|---|---|---|
| `model/` | Pure value types: `SwitchInfo`, `PortStatus`, `PortCounters`, `PortRates`, `VlanConfig`, `QosConfig`, `IgmpConfig`, `MirrorConfig`, `LoopConfig`, `Snapshot` | stdlib only |
| `auth.py` | `merge` and the login hash | stdlib only |
| `pages.py` | Page paths, and parsers from HTML to model types, one per page | model, stdlib `html.parser` |
| `analysis.py` | Pure rules: 64-bit counter deltas into rates, reset detection, snapshot diffs into change events, configuration diffs into readable summaries | model |
| `client.py` | The HTTP session: login, cookie, re-login on expiry, logout, gzip, timeouts, one request at a time, typed errors (`Unreachable`, `AuthFailed`, `UnsupportedSwitch`, `PageChanged`) | auth, pages, stdlib `http.client` |
| `collector.py` | Reads the pages for each poll group through `client` and builds a partial `Snapshot` | client, pages |
| `storage.py` and `migrations/` | The `gs105e_*` tables and repositories | SDK, sqlalchemy |
| `service.py` | Joins collector, analysis, storage and `ctx.core`. One method per job. Holds the pause state (5.3). | all of the above |
| `routes.py` | FastAPI router under `/api/v1/plugins/gs105e/` | service |
| `settings.py` | Pydantic settings model with tabs | SDK, pydantic |
| `plugin.py` | Manifest, setup and wiring | everything |
| `static/` | `faceplate.svg`, `ui.js`, the page, port-grid and report modules, a CSS file | — |

- `model`, `auth`, `pages` and `analysis` carry most of the unit tests and need no switch and no database.
- `client.py` takes an injectable transport, a callable like the Starlink plugin's `Post`, so tests run against recorded pages without a network.
- **Manifest:** id `gs105e`, name "NETGEAR GS105E", `sdk_version=">=1.3,<2"`, capabilities API, WEB_UI, STORAGE and JOBS. Permissions: DEVICES_READ, NAMES_WRITE, TYPES_WRITE, STORAGE_OWN, API, UI and NETWORK_PROBE. Like the GSM7248, it does **not** provide `Capability.TRAFFIC`, for the same reason: the core keeps one traffic entry per IP.

### 5.3 The admin session

- The plugin logs in once and keeps the session cookie for its polls.
- **A lost session** *(my call, from the first anti-goal, revised after the capture)*. When a page answers with the "Redirect to Login" page, the plugin logs in again once and carries on; on this firmware that most likely means the switch rebooted. If the new session is lost again within 10 minutes, that is the pattern of two logins pushing each other out, which a single-session firmware or a second device could cause. The plugin then does **not** log in again. It pauses itself for the pause length, with the event "GS105E: paused, another login keeps ending netview's session", and the page shows "Paused: another login". A failed re-login fails the poll and follows the wrong-password rule below.
- **A wrong password stops the polling.** After an authentication failure the plugin does not try again until the password or host setting changes, or the user presses Test connection. The switch shows as **login failed** with one event. This keeps netview from being the reason the switch locks out logins.
- **Pause polling.** The page has a "Pause for 15 minutes" button (the length is a setting, which the lost-session rule above also uses). It logs the plugin out at once and stops all polls until the time runs out or the user presses Resume. That frees the session so the user can use the switch's own web page. The page shows the pause and a countdown.
- On shutdown and when the host or password changes, the plugin logs out. **Disabling the plugin takes effect at the next netview restart** (core spec: on/off applies at restart), so the logout happens then. Until the restart, Pause is the way to free the session at once, and the settings page says so.
- **What the capture showed (4.1):** the switch allows two sessions at once, and a polled session lasts at least 10 minutes. So netview keeps one long session, and the user's browser can log in beside it. The lost-session rule stays as a safeguard for other firmware and for a login from another device, which was not tested. Pause stays too, but it is no longer the only way to use the switch's own page.

### 5.4 Polling *(defaults; all are settings)*

| Group | Pages | Default interval |
|---|---|---|
| Counters | port statistics | 15 s |
| Status | port status | 30 s |
| Config | switch info, VLAN, QoS, rate limits, storm control, IGMP, mirroring, loop detection | 300 s |

- Each group is a netview job. Requests to the switch go one at a time, never in parallel, with a short gap between pages (setting, default 200 ms).
- An unreachable switch backs off, delaying the next poll by up to 5 minutes. It shows as **unreachable**, with an event on the first failure only.
- A page whose layout no longer matches the parser raises `PageChanged`. The page shows which page failed, and the other groups keep running.

## 6. Phase 1 features: read-only monitoring

### 6.1 Switch identity and health

- **The switch is a netview device.** lan_discovery already sees it by IP. The plugin finds that device by the host setting's IP (or, failing that, by the MAC from switch info) and claims:
  - a **name**: the switch name when one is set, otherwise "GS105E", with source `gs105e` and rank 8, the same rank as the GSM7248 plugin;
  - a **type**: "switch";
  - a **hint**: model, hardware version, firmware and serial number.
- **Health:** reachability, login state (ok, login failed, paused), last poll result per group, and firmware. The switch reports no CPU, memory or uptime.
- **Reboot detection:** when every port's counters go backwards at once, the plugin records "counters reset (switch rebooted or statistics cleared)". The switch has no uptime value, so it cannot tell the two apart.

### 6.2 Ports

For each of ports 1 to 5:

- number and description;
- link state, negotiated speed and duplex, configured speed (Auto, 10M half, …, or Disable), flow control;
- in and out rates in bits per second, utilisation as a percent of link speed, and CRC errors (total and per interval);
- PVID and VLAN membership (tagged or untagged), or the port-based VLAN group;
- ingress and egress rate limits; QoS priority when the switch is in port-based QoS mode;
- max MTU;
- mirroring role (source, destination or none);
- loop detection state, if the switch reports one per port (not seen yet, 4.1).

**Counters:** each counter is a 64-bit value built from the page's high and low 32-bit inputs. A counter that goes backwards is a reset: that interval gives no rate rather than a negative or huge one. Netgear notes that some Plus firmware reset byte counters to zero at 4 GB. If the pages show only the low 32 bits, the plugin falls back to 32-bit wrap handling.

### 6.3 The faceplate

The Switch page shows `faceplate.svg` with an HTML button over each jack, placed by percentages from the geometry in the SVG's header comment, the same way `gsm7248/static/port-grid.js` places them.

- **Status view:** each jack is coloured by link state in theme tokens, with a text cue for speed (1G, 100M, 10M or a dash), never colour alone. The two LED dots on each jack copy the real switch: both lit for 1000M, left only for 100M, right only for 10M, and none when the link is down. They draw on top of the SVG's LED rectangles. The Power LED shows reachability.
- **VLAN view:** jacks are coloured by PVID (802.1Q) or by group (port-based) from the GSM7248's VLAN palette, which avoids green, red and amber, with a legend.
- **Mirror and loop markers:** a small badge on a jack that is a mirror source or destination, or where a loop was detected.
- Clicking a jack opens the **port detail panel**: everything in 6.2, plus a traffic chart (the core chart helpers) over the last hour, day or week.
- The faceplate scales to the page width and scrolls inside its own container at 375 px, never the page.

### 6.4 Configuration sections

Under the faceplate, in this order:
- VLANs: mode, VLAN list with member ports and tagging, PVIDs.
- QoS: mode, scheduler, port priorities, rate limits, storm control.
- Multicast: IGMP snooping state, version, block unknown multicast, router port.
- Mirroring: on or off, destination, sources.
- Storm control: broadcast filtering on or off.
- Loop detection: on or off, and the state per port if the switch reports one.
- Management: management mode (web only, or web and Plus Utility), TFTP via Plus Utility, the Access Control list, power saving.
- Switch: name, model, serial, MAC, firmware, bootloader, IP settings (DHCP or static, mask, gateway).

A VLAN mode that is off is shown as "VLANs off" with the one default VLAN, which is the lab unit's state today.

Each section shows what the switch reports, and nothing that the switch did not answer.

### 6.5 Events

Through `ctx.core.add_event(kind, text, ip)`. It has no source parameter, so, like the GSM7248 plugin, events use `EventKind.PLUGIN` (or the closest existing kind) and the text starts with "GS105E: ". The switch's IP goes in `ip`.

- port link up and link down;
- port speed changed (for example, 1000M to 100M, often a cable fault);
- CRC errors rising on a port: more than N new errors in one counters interval (setting, default 10). At most one event per port per hour;
- loop detected and loop cleared, if the switch reports loop state (4.1);
- Access Control list changed so that it no longer includes netview's own address: a warning, because the next login may be refused;
- switch unreachable and reachable again; login failed;
- counters reset (reboot or cleared statistics);
- firmware changed;
- configuration changed, with a one-line summary of what differs (for example, "port 3 PVID 1 → 20", "mirroring turned on").

Change detection compares consecutive snapshots in `analysis.py`, as the GSM7248 plugin does: each poll group replaces only its own fields, the first poll of each group is a baseline and raises nothing, and the merged snapshot is stored so restarts don't raise events again.

### 6.6 Storage

All tables are prefixed `gs105e_`, created by the plugin's own Alembic branch, and have a `switch_id` column (the constant `gs105e` in phase 1).

| Table | Contents |
|---|---|
| `gs105e_port_samples` | per port per counters poll: time, in and out bytes, rates, CRC errors. Raw for 24 h, then 5-minute rollups for 30 days (both settings). A pruning job enforces this. |
| `gs105e_snapshots` | the latest merged snapshot as JSON, for change detection across restarts and for API reads |

### 6.7 API (`/api/v1/plugins/gs105e/`)

| Method | Path | What it returns or does |
|---|---|---|
| GET | `/summary` | identity, reachability, login and pause state, ports up out of 5, total throughput, firmware warning |
| GET | `/ports` | every port with the fields in 6.2 |
| GET | `/ports/{n}` | one port |
| GET | `/ports/{n}/samples?from&to&step` | traffic series for charts |
| GET | `/config` | VLAN, QoS, IGMP, mirroring and loop detection settings |
| POST | `/poll` | run every poll group now. 409 if a poll is running, or if polling is paused. |
| POST | `/pause` | log out and pause polling for the configured time; `DELETE /pause` resumes |
| POST | `/test` | log in with the stored settings, read switch info, log out; returns the model and firmware or the typed error. It also clears a login-failed stop. |

Every unsafe method needs the `X-Netview` header. The password never appears in a response or a log.

### 6.8 Web UI

- **Dashboard tile:** "GS105E": ports up out of 5, total throughput, and the state when it is not OK (unreachable, login failed, paused), shown with an icon and a label in the `--bad` or `--warn` token colour, never colour alone.
- **Switch page** (the `page` slot, with a nav entry): the faceplate with Status and VLAN views, the pause button, the port detail panel, and the configuration sections. Polls publish a state change so the page refreshes through the SSE stream.
- **Device report section:** on the switch's own device, a short summary (model, firmware, ports up, throughput) with a link to the Switch page.
- **No Devices column.** Without a MAC table the plugin cannot say which port a device is on.
- **Settings tabs:**
  - **General:** poll intervals, page gap, pause length, traffic history retention, the CRC alert threshold.
  - **Connection:** host (default `192.168.1.3`), password (masked, "set" or "not set"), and the **Test connection** section.

## 7. Phase 2: configuration changes (later plan, outline)

**Writes are off by default** behind a setting, "Allow changes".

**What changes:** port enable or disable and speed, flow control, port description, VLAN membership and PVIDs, QoS priority, rate limits, storm control, IGMP snooping, mirroring, loop detection, switch name, a reboot, and running the cable tester. Each write posts the page's form with its `hash` value, then reads the page back to confirm.

**Safety design:**

- **The switch saves every change at once.** As far as is known, Plus switches have no running versus startup configuration, so a reboot does not undo a bad change, and the only way back is the reset button and setting it up again. The UI says this on every change.
- **netview cannot tell which port it reaches the switch through** (no MAC table). A setting, **management port**, names that port. It has no default, and until it is set every change that can cut a link (disabling a port, changing its speed, changing its VLAN or PVID) needs the user to type the port number to confirm. On the management port that confirmation is always needed.
- It refuses to leave a port with no untagged VLAN, and it refuses to delete the VLAN the management port is in.
- It refuses an Access Control list that leaves out netview's own address, and refuses to change the switch's IP settings without a typed confirmation.
- **Configuration backup:** the switch has `backup_conf.cgi` and `restore_conf.cgi`. A backup before every change, kept in the plugin's storage, is the natural rollback. How those pages work is checked before phase 2 is planned.
- **Preview:** every change is shown as before and after values before it is applied.
- **Cable test:** it can drop the link on that port briefly (to be checked). It is confirmed like a disabling change.
- **Audit log:** a `gs105e_changes` table records when, what, and the result, shown on the page.

## 8. Phase 3: later (outline)

- Other Plus models (GS108Ev3, GS305E, GS308E, GS105E v1 with web firmware) through per-model page profiles, starting from the login page's title.
- NSDP as a second path for older firmware, only if the web pages turn out not to have something useful.
- Linking the GS105E to the GSM7248 port it is cabled to (0/11 today), through a core topology feature rather than plugin-to-plugin code.
- More than one GS105E (the `switch_id` column already allows it).

## 9. Delivery order for phase 1 *(my call)*

1. **Capture the real pages.** A small developer script, `plugins/gs105e/tools/capture.py` (`--help`, a dry run unless `--execute`, password from an environment variable or a prompt, never from the command line), logs in, finds every page in the switch's menu, saves each one, and logs out. It also records the session behaviour from 5.3. **Decided by the user (2026-11-11): one supervised run, early.** The user types the password at the script's prompt in their own terminal, so it never passes through the assistant. The capture happens before the implementation plan is written, so the plan is built on the real pages and stays a single plan. The saved pages are scrubbed and committed as fixtures under `plugins/gs105e/tests/fixtures/`. **Done 2026-11-11:** see 4.1.
2. **Pure layer:** model, `auth`, page parsers and analysis, fully unit tested against the fixtures.
3. **Client and service:** the session (login, re-login, logout, pause, the stop after a failed login), collector, storage and migrations, jobs, claims, events and API, with integration tests over a fake transport that serves the fixtures.
4. **UI:** tile, Switch page with faceplate overlays, port detail panel with chart, configuration sections, settings tabs and the Test connection section, the device report section. JS tests like the GSM7248 ones, plus a browser check against the fake-transport server and then the real switch.
5. **Live check** against 192.168.1.3, and a short `docs/gs105e-setup.md`: setting a password, the address, and using pause when you need the switch's own web page.

## 10. Open items

- Fixtures for the features that are off on the lab unit (4.1, "Not seen"). Each gets one when it is first turned on, with the capture tool.
- Port descriptions are empty on the lab unit; the panel shows none until one is set on the switch.
- Stale hints after the switch is removed from the network: as with the GSM7248, the core keeps a source's last hints.
- The switch is temporary in the lab. When it comes out, the plugin stays as an optional plugin and simply shows the switch as unreachable until it is disabled.

## 11. Left to the builder

- Exact model fields, table columns and indexes, and rollup mechanics, following the GSM7248 plugin where it fits.
- How much of the GSM7248's `static/` code to copy and adapt. **No imports between the two plugins.** Shared needs go into the core UI helpers only if the core already has a place for them.
- Module splits inside `model/`, `pages.py` and `static/`.
