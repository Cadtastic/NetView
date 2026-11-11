# GSM7248 serial console: probe and open a terminal

Date: 2026-11-11. Status: approved in chat by the user, built on `feature/gsm7248-console`.

## Why

The switch's console port is cabled to the rear serial port of the R720 (Proxmox host, `/dev/ttyS0`, 38400 8N1).
The user wants the Switch page to show whether the switch answers on that line, and to open a terminal on it
from the console port drawn on the faceplate.

## Goals

- Show on the faceplate whether the switch answers on the serial line.
- Open a Windows Terminal window on the console with a double-click or right-click on the console port.

## Non-goals

- No terminal inside the web page.
- NetView never logs in to the switch and never sends anything but one carriage return.
- No background polling of the serial line.

## Anti-goals

- A web request must never be able to choose the command that runs on this computer or on the SSH host.
- The probe must not type into a console session somebody has open.

## Decisions the user made

- The terminal is a Windows Terminal window, not an in-page terminal.
- Authentication is the user's own SSH keys. NetView stores no SSH secret.
- The probe runs when the Switch page opens and on "Probe now" only.

## How it works

- **Settings**, section "Serial console": `console_enabled` (off by default), `console_ssh_host`,
  `console_ssh_user`, `console_device`, `console_baud`. Every value is pattern-checked so it can be placed in a
  command line.
- **Probe**: `ssh -o BatchMode=yes -o ConnectTimeout=5 user@host <script>`. The script reports `IN_USE` when the
  NetView `screen` session exists or `fuser` finds a process on the device, and `NO_DEVICE` when the device is
  missing. Otherwise it sets the line with `stty`, sends one carriage return and reads for two seconds.
- **States**: `connected` (the switch sent text), `silent` (nothing came back), `in_use`, `no_device`,
  `unreachable` (ssh failed). `connected` means the switch answered; the link has no cable-detect signal.
- **Open**: `wt.exe -w 0 new-tab --title "GSM7248 console" ssh -t user@host "screen -D -R -S netview-gsm7248
  <device> <baud>"`. Windows only; `can_open` is false elsewhere and the UI hides the button.
- **API**: `GET /console`, `POST /console/probe`, `POST /console/open`. No request body is read. The core's
  existing guard (allowed hosts and the `X-Netview` header) covers cross-site requests.
- **UI**: the console port on the faceplate is a button with a state ring. Click opens a panel with the last
  result, "Probe now" and "Open terminal". Double-click and right-click open the terminal.

## Calls made by the builder

- Commands are argument lists, never a shell string on this computer.
- The last probe result is kept in memory only and cleared when settings change.
- This spec was not sent to a separate reviewer; the design was agreed in chat first.
