# netview GSM7248 switch plugin: design

Date: 2026-11-10. Status: initial design. The user asked for the initial plan now and will refine it in later iterations, so most of what follows is **my call** and is marked that way. Read it as a starting point to correct, not as settled agreement.

## 1. Intent

The NETGEAR GSM7248 is the core switch of the home lab. The R720/Proxmox host is on it today, and the OPNsense router and access points join it after the cutover. netview is meant to be the "god's eye view" of the internal network, and right now it is blind past the first hop: it knows a device exists and its IP, but not which switch port it is on, which VLAN it is in, whether its link is healthy, or how much traffic that port carries.

The user asked for a **full implementation of the switch's features** in a netview plugin. This design covers the whole feature set in phases. The first implementation plan covers phase 1.

Switch facts come from `HomeLab/docs/hardware/gsm7248.md`: model GSM7248 v1, software 6.3.3.7, MAC 00:1B:2F:C2:DC:75, interim static IP 192.168.1.4 on the Starlink LAN (10.27.10.2 on Mgmt VLAN 10 after the cutover). Its MIB list includes IF-MIB, BRIDGE-MIB, Q-BRIDGE-MIB, ENTITY-MIB, LAG-MIB, Etherlike-MIB, RMON-MIB, SNMPv3 and the NETGEAR private MIBs. **There is no LLDP-MIB and no PoE hardware**, so neighbour discovery and PoE are out of scope.

## 2. Goals, non-goals, anti-goals

**Goals**

- See the switch as a first-class part of the network: identity, uptime, CPU and memory, reachability.
- See every port: link state, speed, duplex, admin state, description, PVID, VLAN membership, spanning-tree role and state, LAG membership, error counters.
- Live and historical per-port traffic (bits per second in and out, errors, discards).
- **Device-to-port mapping:** for each netview device, which switch port and VLAN it is behind. This is the headline feature.
- Events for what changes: link up and down, a MAC that appears, moves port or disappears, spanning-tree changes, the switch going unreachable, memory running low.
- Later phases: make configuration changes from netview safely (ports, VLANs), back up and diff the configuration, and receive traps and syslog.

**Non-goals (for now)**

- Supporting other switch models. The standard-MIB code is written so it would work on other switches, but only the GSM7248 is tested.
- LLDP/CDP neighbour maps (the firmware has no LLDP-MIB) and PoE.
- Firmware upgrades from netview.
- Running anything on the switch itself.

**Anti-goals (a failure even if it works)**

- **netview cuts off its own access to the switch,** or to the Proxmox host, through a configuration change. Every write path must make that hard (section 7).
- Polling so hard that the switch suffers. It has only about 2 MB of free memory with the factory config, and a weak CPU.
- Credentials leaking: an SNMP community or v3 key shown in the UI, written to logs, or returned by an API.
- Plugin code reaching into core tables or other plugins, which breaks the plugin rules in the netview spec, sections 7.4 and 7.5.

## 3. Decided by the user

- It is a netview plugin. netview runs on the laptop and reaches the switch over the LAN, not over the serial console.
- The user wants the full feature set, delivered over several iterations, starting from this initial plan.
- The work happens on branch `feature/gsm7248-plugin`, in the worktree `HomeLab/netview-gsm7248`.

## 4. Constraints

- Everything in the netview design spec (`2026-11-10-netview-design.md`):
  - Clean Architecture layers and the import-linter contracts;
  - the plugin SDK as the only import surface for plugins;
  - plugin tables prefixed `gsm7248_`;
  - per-plugin Alembic branch;
  - settings in `plugin_state` that apply live;
  - the no-build plain-JS UI with slots;
  - CSP-compatible UI (no inline scripts);
  - theme tokens only, no hard-coded colours.
- The switch is at 192.168.1.4 today and moves to 10.27.10.2 later, so its address is a setting, never a constant.
- **Plan 2 (parity) is in progress** on `feature/netview-parity`. It adds:
  - core traffic, health and metrics use cases;
  - chart helpers in the UI;
  - the device report dialog;
  - the Events list;
  - a plugin independence contract.

  Phase 1 is split so the plugin's own work does not wait on plan 2. The pieces that use those core features come last and start after plan 2 is merged into `main` and this branch is rebased (section 9).
- Python 3.11+, the existing tooling (uv, ruff, mypy, pytest, `npm test`).
- Never write nicknames. The plugin claims names, types and hints only through `ctx.core`.

## 5. Architecture *(my calls)*

### 5.1 SNMP is a shared service, not plugin code

SNMP is a general tool. The iDRAC, Proxmox and the access points could all be read the same way later. So the core gets an **`SnmpClient` port** in `application/ports/snmp.py`. Its adapter lives in `infrastructure/net/snmp.py`, and plugins reach it through `ctx.snmp`. This adds to the SDK, so `SDK_VERSION` becomes 1.1, and existing plugins with `>=1.0,<2` keep loading.

- **Port shape** (indicative): `get(target, oids)`, `walk(target, oid_prefix, max_rows)` using GETBULK, and `set(target, varbinds)` for phase 2.
- `SnmpTarget` is a frozen value object: host, port, version (2c or 3), timeouts and retries, and credentials.
- Values come back as plain Python types: int, bytes, str, OID tuple, IP string or timeticks.
- Errors are typed: `SnmpTimeout`, `SnmpAuthError`, `SnmpNoSuchName`, `SnmpError`.
- **Library:** `pysnmp` (the maintained lextudio line, 7.x) with its asyncio high-level API. It is the standard pure-Python SNMP stack and supports v3 USM: MD5/SHA auth, DES/AES privacy. The adapter is the only module that imports it.
- **Testing:**
  - `sdk.testing` gets a `FakeSnmpClient` that serves a recorded walk, so plugins test without a switch.
  - The adapter is tested against a pysnmp command responder started in-process on 127.0.0.1.
- The adapter caps concurrent requests to one target, by default to 1, to protect the switch.

### 5.2 Secret settings

SNMP communities and v3 passphrases are secrets, and today's plugin settings have no notion of secrets. The core gains a small, general rule:

- A settings field typed `pydantic.SecretStr` is marked `writeOnly` / `format: password` in the JSON schema.
- It is **masked** in every API response, in logs, and in the Settings dialog.
- A PATCH that sends the mask value, or omits the field, keeps the stored value.
- The generated settings form shows it as a password input with "set" or "not set".
- **Storage:** plain text in the local SQLite `plugin_state`, as today. Moving to the OS keyring (Windows Credential Manager) goes in `deferred.md`.

### 5.3 Inside the plugin

`src/netview/plugins/builtin/gsm7248/` follows the same layering in small:

| Module | Job | Imports |
|---|---|---|
| `model/` | Pure value types: `SwitchInfo`, `Port`, `PortCounters`, `PortRates`, `MacEntry`, `Vlan`, `StpPort`, `LagGroup`, `Snapshot` | stdlib only |
| `mibs.py` | OID constants, and decoders from SNMP rows to model types (IF-MIB, BRIDGE-MIB, Q-BRIDGE-MIB, ENTITY-MIB, LAG-MIB, Etherlike-MIB, NETGEAR CPU and memory) | model |
| `analysis.py` | Pure rules: counter deltas into rates (64-bit counters, 32-bit wrap fallback, reset detection), snapshot diffs into change events, uplink detection, device-to-port attribution | model |
| `collector.py` | Polls through `ctx.snmp`, using the right walk for each poll group, and builds a `Snapshot` | SDK, mibs |
| `storage.py` and `migrations/` | The `gsm7248_*` tables and repositories | SDK, sqlalchemy |
| `service.py` | Joins collector, analysis, storage and `ctx.core`. One method per job. | all of the above |
| `routes.py` | FastAPI router under `/api/v1/plugins/gsm7248/` | service |
| `settings.py` | Pydantic settings model | pydantic |
| `plugin.py` | Manifest, setup and wiring | everything |
| `static/` | `ui.js`, plus page and port-detail modules and a CSS file | — |

`model` and `analysis` get the bulk of the unit tests. They need no SNMP and no database.

### 5.4 Polling *(defaults; all are settings)*

| Group | What it reads | Default interval |
|---|---|---|
| Counters | ifHC in/out octets, unicast/multicast/broadcast packets, errors, discards, for linked ports only | 15 s |
| Status | ifOper and ifAdmin status, speed, last change, CPU and memory | 30 s |
| Bridge | MAC address table (Q-BRIDGE `dot1qTpFdbTable`, falling back to BRIDGE-MIB), bridge port to ifIndex | 60 s |
| Topology | VLANs and membership, PVIDs, STP port states and roles, LAG groups, ENTITY inventory, sysName/sysDescr/sysUpTime | 300 s |

- Each group is a netview job with its own timeout.
- An unreachable switch backs off: the next poll is delayed, up to 5 min. The switch shows as **unreachable** with an event the first time it fails.
- Requests to the switch are serialised, never in parallel.

## 6. Phase 1 features: read-only monitoring

### 6.1 Switch identity and health

- **The switch is a netview device.** lan_discovery already sees it at its IP. The plugin claims:
  - a **name**: sysName when set, otherwise "GSM7248", with source `snmp` and rank 8, between UPnP and hostname. The rank is my call.
  - a **type**: "switch".
  - a **hint**: model, firmware and serial number.

  `NameClaim` carries its own rank, so `domain/naming.py` doesn't change. That keeps this branch clear of plan 2's edits to that file.
- **Health:** uptime, CPU percent, free and total memory, reachability and the last poll result. A warning event fires when free memory drops below a threshold (setting, default 1 MB).

### 6.2 Ports

For each of the 48 ports, plus the SFP combo ports and LAGs:

- name (`0/1`, …), ifIndex, description (ifAlias);
- admin and oper state, speed, duplex (Etherlike-MIB), last change;
- PVID and tagged/untagged VLAN membership;
- STP state. The role (Designated or Backup) needs the NETGEAR MSTP private MIB and comes later;
- LAG membership;
- in/out rates, utilisation percent of link speed, error and discard rates;
- the devices learned on the port, and an **uplink** flag.

### 6.3 Device-to-port mapping *(my rules)*

- Each MAC in the forwarding table maps to a bridge port, then to an ifIndex, then to a port name.
- **Uplink detection:** a port is an uplink if any of these hold:
  - the user marks it as one in settings (default: none);
  - more than N MACs are learned on it (setting, default 8);
  - it is where the gateway's MAC is learned.

  Devices behind an uplink are shown as "via uplink 0/11", not as directly attached.
- **netview devices are matched by MAC.** For each match the plugin:
  - claims a **hint**, "on GSM7248 port 0/5, VLAN 1";
  - shows it in a **Switch port** column in the Devices table (`devices.column` slot).
- MACs on the switch that netview has no device for, because they have no IP or haven't been seen, are listed on the plugin page as "unknown MACs" with the vendor from the OUI lookup. That is useful for finding Proxmox guests.
- **Per-device traffic** *(after plan 2)*:
  - When an edge port has **exactly one** device MAC, the port's traffic is reported for that device through the Traffic capability: down is the port's out octets, up is its in octets.
  - Ports with several MACs, like Proxmox with its guests, report port traffic only.

### 6.4 Events

Through `ctx.core.add_event`:

- link up and link down;
- port admin state changed;
- new MAC learned: the first time a MAC is ever seen on a non-uplink port, so idle guests whose table entries age out and return don't repeat it;
- MAC moved port, ignoring moves onto or off an uplink;
- MAC aged out: only for MACs that belong to a known netview device, so guest churn doesn't spam;
- STP state changed;
- switch unreachable and reachable again;
- low memory;
- switch rebooted, detected when sysUpTime goes backwards.

Change detection compares consecutive snapshots in `analysis.py`:
- Each poll group (status, bridge, topology) only replaces its own fields.
- A group is compared only once both snapshots hold it, so the first poll of each group is a baseline, not news.
- It is idempotent across restarts because the merged snapshot is stored.
- Every claim and event uses the source `GSM7248`.

### 6.5 Storage

All tables are prefixed `gsm7248_`, created by the plugin's own Alembic branch.

| Table | Contents |
|---|---|
| `gsm7248_port_samples` | per port per poll: t, in/out octets, rates, errors, discards. Raw for 24 h, then 5-minute rollups for 30 days (both are settings). A pruning job enforces this. |
| `gsm7248_mac_locations` | MAC, VLAN, port, first seen, last seen. It records movement history. |
| `gsm7248_snapshots` | the latest topology and status snapshot as JSON, for change detection across restarts and for API reads |

### 6.6 API (`/api/v1/plugins/gsm7248/`)

| Method | Path | What it returns or does |
|---|---|---|
| GET | `/summary` | switch identity, health, reachability, port up/down counts, total throughput |
| GET | `/ports` | every port with state, VLANs, STP, LAG, rates and attached devices |
| GET | `/ports/{name}` | one port, plus its MAC history |
| GET | `/ports/{name}/samples?from&to&step` | traffic series for charts |
| GET | `/macs` | the forwarding table, joined to netview devices and OUI vendors |
| GET | `/vlans` | VLANs with member ports |
| POST | `/poll` | run every poll group now. 409 if a poll is running. Needs the `X-Netview` header like every unsafe method. |

Secrets never appear in any response.

### 6.7 Web UI

- **Dashboard tile:** "Switch". It shows ports up out of 48, total throughput and CPU. When the switch is unreachable it shows that in the `--bad` token colour, with an icon and a label, never colour alone.
- **Switch page** (the `page` slot, with a nav entry):
  - a **front-panel port grid** laid out like the GSM7248 faceplate: two rows, odd ports on top, plus the combo/SFP ports. Each port cell shows link state and speed through token colours plus a text or icon cue, and a small utilisation bar.
  - Clicking a port opens a **port detail panel**: its settings and state, the devices on it, MAC history, and *(after plan 2)* a traffic chart.
  - Tabs or sections under the grid: VLANs, the MAC table (searchable, with unknown MACs highlighted), spanning tree, LAGs and inventory.
  - Live updates: polls publish a state change so the page refreshes through the existing SSE stream.
- **Devices column:** "Switch port", sortable, working with grouping and show/hide.
- **Device report section** *(after plan 2)*: switch port, VLAN, link speed, port traffic chart and MAC history.
- **Settings tab:** generated from the settings model:
  - host;
  - SNMP version;
  - community or v3 user, auth and privacy protocols and passphrases, shown masked;
  - poll intervals;
  - uplink ports and the MAC threshold;
  - retention;
  - the low-memory threshold.

  A **Test connection** button calls a `POST /test` route and shows sysDescr or the typed error.
- It is accessible at 375 px: the port grid scrolls horizontally inside its own container, never the page.

### 6.8 Switch-side setup (a runbook, done by the user)

- **Recommended:** a read-only SNMPv3 user with authPriv (SHA plus DES or AES, whichever 6.3.3.7 offers). Alternatively, a v2c community restricted to the laptop's IP.
- Remove or change the default `private` read-write community.
- `docs/gsm7248-setup.md` gives the console commands, checked against the 6.3.3.7 CLI reference. netview never changes switch settings in phase 1.

## 7. Phase 2: configuration changes (later plan, outline)

**Read-write credentials are separate from read-only ones,** and off by default.

**What changes:** port admin up/down, port description, PVID, and VLAN create/rename/delete and membership (Q-BRIDGE `dot1qVlanStaticTable` and the IF-MIB writable objects), through SNMP SET.

**Safety design:**

- **Preview:** every change is shown as the exact SET operations, with before and after values, before it is applied.
- **Self-protection:**
  - Netview refuses changes to the port it reaches the switch through, to the management VLAN, and to the port behind which the netview host or the Proxmox host is learned, unless the user types the port name to confirm.
  - It refuses to remove the last untagged VLAN from a port.
- **Commit-confirmed:**
  - Changes go to the running configuration only.
  - Netview re-polls, and if it can't reach the switch within N seconds, it reverts the change automatically.
  - Saving to the startup config is a separate, explicit "Save configuration" action. That means a bad change is also undone by rebooting the switch.
- **Audit log:** a `gsm7248_changes` table records who, when, what and the result. It is shown on the page.

**Configuration backup and diff:**

- This reads `show running-config` over the CLI.
- It uses a small Telnet client written for netview, because Python 3.13 removed `telnetlib`. SSH can replace it once keys are set up on the switch.
- Each backup is stored with a timestamp, and the page shows diffs between versions.

## 8. Phase 3: later (outline)

- An SNMP trap receiver (UDP 162) and a syslog receiver (UDP 514) for instant link events instead of waiting for the next poll. Both need the switch configured to send to the laptop.
- RMON statistics.
- 802.1X and port-security views.
- LAG configuration.
- QoS and ACL views.
- Following the switch's address move to 10.27.10.2 at cutover. That is a settings change and needs no code.

## 9. Delivery order for phase 1 *(my call)*

1. Core: the `SnmpClient` port, its pysnmp adapter, `ctx.snmp`, `FakeSnmpClient`, SDK 1.1, and secret settings in the API and settings form.
2. Plugin domain: model, MIB decoders and analysis, all pure and fully unit tested. Recorded walk fixtures.
3. Plugin storage, collector, service and jobs; identity, hint and event integration; API.
4. UI: tile, Switch page with port grid and detail panel, Devices column, settings test button.
5. Switch setup runbook, then a live check against the real switch.
6. **After plan 2 is merged and this branch is rebased:** Traffic capability for single-device ports, port traffic charts, the device report section, and events in the core Events list.

## 10. Open items for later iterations

- Whether to support more than one switch. Every table has a `switch_id` column, which is the constant `gsm7248` in phase 1, so it can be added later.
- Stale hints: the core replaces a source's hints only when new ones arrive, so a device that leaves the switch keeps its last port hint until the core can clear them.
- Whether the plugin should become a generic `snmp_switch` plugin with a NETGEAR profile.
- The exact NETGEAR private OIDs for CPU and memory, and for saving the config in phase 2. These must be checked against the MIB files and the live switch, not guessed.
- Storing secrets in the OS keyring instead of SQLite.
- Recording a real `snmpwalk` of the switch as the test fixture, scrubbing the serial number and MACs before the repository is ever published, as `deferred.md` already notes for network fixtures.

## 11. Left to the builder

- Exact table columns and indexes, the rollup mechanics, and pysnmp API details.
- How the port grid is drawn, within the netview visual rules (spec §13.3) and theme tokens.
- Module splits inside `model/` and `static/`.
