# GS105E switch setup for netview

This sets up the netview `gs105e` plugin for the NETGEAR GS105Ev2 (a five-port Plus switch). netview reads the switch's own web pages. In phase 1 it only reads. It never changes a switch setting.

## What the switch has and does not have

- The switch has a web interface on port 80. There is no SNMP, no CLI and no SSH.
- It shows no MAC address table. netview therefore cannot say which device is plugged into which port.
- It shows no CPU, memory or uptime. netview does not show per-port loop state: the switch's help text says loops show only on the port LEDs.

## 1. Install the plugin

The plugin is a folder plugin. Use either way:

- Copy the folder `plugins/gs105e` into `<data dir>/plugins`, so you have `<data dir>/plugins/gs105e`. Then restart netview.
- Or run netview with `--plugin-dir <folder>`, where `<folder>` holds the `gs105e` folder. You can repeat the option.

## 2. Set the switch's password and address

On the switch's own web page, set or change the admin password.

- The factory default password is `password`. Change it.
- The default address is `192.168.1.3`, port 80. If you changed it, use your own address.
- A DHCP reservation or a fixed address keeps the address from changing under netview.

## 3. Enter the connection in netview

1. Open netview, then Settings, then the **NETGEAR GS105E** tab.
2. Open the **Connection** tab. Set the host (default `192.168.1.3`), the port (default `80`) and the password.
3. Press **Save**.
4. Press **Test connection**. It uses the saved settings.

Until you enter a password, the plugin does nothing on the network.

The password is stored in netview's local database. Do not put it in `netview.toml`. That file is plain text.

## 4. What netview reads

netview logs in once and polls three groups of pages. It asks for one page at a time, with a short gap between pages (default 200 ms), because the switch is slow and fragile. You can change every interval on the **General** tab.

| Group | What | Default |
|---|---|---|
| Port traffic | port statistics (counters) | every 15 s |
| Port status | link, linked speed, speed setting, flow control, MTU, description | every 30 s |
| Configuration | switch info, VLAN, QoS, rate limits, storm control, IGMP, mirroring, loop detection, management | every 300 s |

The Switch page shows a faceplate, a panel for each port with a traffic chart, and the configuration sections. netview also names the switch's device and gives it the type "switch".

## 5. How netview treats the switch's login

- netview keeps one login open. On the tested firmware your browser can log in to the switch at the same time.
- **Pause** frees the login at once. Press it on the Switch page when you want the switch's own page to yourself. Polling stops for the pause length (default 15 minutes) or until you press **Resume**.
- If netview's login is lost, it logs in again once. If it is lost again within 10 minutes, another login is probably pushing it out. netview then pauses itself and says so, and does not log in again until the pause time runs out or you press **Resume**.
- A **wrong password stops polling**. netview does not try again until you change the host, port or password, or a **Test connection** succeeds. This keeps netview from being the reason the switch locks out logins. Each Test connection with a wrong password is still one attempt, so check the password before you press it. The switch shows as "login failed".
- Disabling the plugin takes effect after a netview restart. Until then, use Pause.

## For developers

### Record pages for a newly enabled feature

Some features are off on the lab switch, so there is no fixture for them yet. Turn the feature on, then record the pages with `tools/capture.py`:

```
uv run python -I plugins/gs105e/tools/capture.py --host <switch-ip>
uv run python -I plugins/gs105e/tools/capture.py --host <switch-ip> --out <folder> --execute --keep-raw
```

- The first command is a dry run. It reads only the login page.
- With `--execute` the script asks for the password at a prompt. Type it yourself. It is never taken from the command line, printed or saved.
- It saves each page under `<folder>/pages`, scrubbed: the serial number, MAC addresses and IP addresses are replaced with placeholders.
- Use an `--out` folder outside the repository. `--keep-raw` also saves the unscrubbed pages under `<folder>/raw`, and `raw/` is not git-ignored. **Never commit `raw/`.**
- The password prompt is the safe way to give the password. A password typed into a command or set in the shell stays in shell history, so do not do that.
- If the scrub rules change, rebuild the scrubbed pages from `raw/` with:

  ```
  uv run python -I plugins/gs105e/tools/capture.py --host <switch-ip> --rescrub --out <folder>
  ```

  `--host` is required by the script, but in this mode the host is not contacted.
- Close any browser tab logged in to the switch first. The session checks may log it out.

Copy the new pages into a folder per firmware, such as `plugins/gs105e/tests/fixtures/fw-<version>/`, and write the parser test.

### Run a fake switch for UI work

```
uv run python -I plugins/gs105e/tools/fake_switch.py --port 8105
```

The fake serves the saved fixture pages on `127.0.0.1`. By default it serves `fw-1.6.0.11`. Its password is `secret`. Start netview, then in Settings set host `127.0.0.1`, port `8105` and password `secret`. Use `--fixtures <folder>` to serve another set of pages and `--password <text>` to change the password.
