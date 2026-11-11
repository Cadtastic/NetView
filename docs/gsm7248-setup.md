# GSM7248 switch setup for netview

This sets up read-only SNMP on the NETGEAR GSM7248 (software 6.3.3.7) so the netview `gsm7248` plugin can poll it.

## Source of the commands

The commands come from the 6.x FASTPATH CLI syntax. They were **not** checked against a copy of NETGEAR's *GSM7248 CLI Command Reference* (software 6.x) when this was written, because it could not be reached. Every command marked **(check against the CLI reference)** must be confirmed in that document, or with `?` help on the switch, before you rely on it. Where a command is rejected, type the first words followed by `?` to see the real syntax.

## Before you start

- Console access is over serial from Proxmox: `screen /dev/ttyS0 38400`. See `HomeLab/docs/hardware/gsm7248.md`.
- Commands are typed at the `#` prompt. Use `enable` first if the prompt is `>`. Use `configure` for the config commands, and `exit` to leave config mode.
- The iDRAC HTML5 console drops `\` and `;`. The commands below avoid both. Do not paste passphrases that contain them.
- Replace every `<placeholder>` with your own value. Never write a real passphrase or community into this file.

## 1. See the defaults

```
show snmpcommunity
```

Note each community name, its access (read-only or read/write) and its status. The defaults usually include `public` (read-only) and `private` (read/write). (check against the CLI reference)

## 2. Remove or disable the read/write `private` community

In config mode, try these in order and stop at the first that works:

```
no snmp-server community private
```

(check against the CLI reference)

If the community cannot be removed, turn it off:

```
no snmp-server community mode private
```

(check against the CLI reference)

Run `show snmpcommunity` again and confirm `private` is gone or disabled. netview only reads, so it never needs read/write access.

## 3. SNMPv3 (recommended)

Create a read-only user `netview` with SHA authentication and DES privacy. The exact keywords vary by release, so ask the switch for them:

```
snmp-server user ?
```

(check against the CLI reference)

The usual shape in FASTPATH 6.x is a user, a group and an authentication/privacy setting. A sketch, to be corrected from the `?` output and the reference:

```
snmp-server user netview
snmp-server user netview auth sha <your-auth-passphrase>
snmp-server user netview priv des <your-priv-passphrase>
```

(check against the CLI reference)

Notes:

- If 6.3.3.7 does not support SHA or DES, use the strongest pair it lists. netview supports the SHA and MD5 authentication protocols and DES and AES privacy.
- Passphrases are usually at least 8 characters.
- Make sure the user is read-only. If the release asks for a group or view, pick a read-only one. (check against the CLI reference)

## 4. SNMPv2c alternative

Use this only if v3 is not workable. Create a read-only community restricted to the laptop's IP:

```
snmp-server community <your-community> ro
snmp-server community ipaddr <laptop-ip> <your-community>
snmp-server community mode <your-community>
```

(check against the CLI reference)

The laptop's IP is assigned by DHCP today. A restriction to that address breaks when the lease changes, so either add a DHCP reservation for the laptop first, or use v3.

## 5. Save the configuration

```
copy system:running-config nvram:startup-config
```

Answer the confirmation prompt with `y`. Without this, the changes are lost at the next reboot. (check against the CLI reference)

## 6. Check from the laptop

1. Open netview, then Settings, then Switch.
2. Set the host (default `192.168.1.4`) and choose the SNMP version.
3. Enter the secrets: for v3, the user `netview`, the authentication passphrase and the privacy passphrase. For v2c, the community.
4. Press **Test connection**. It should report the switch name and that it answered.

## Where secrets go

SNMP secrets go **only** into netview's Settings dialog. Never put them in a `[plugins.gsm7248]` section of `netview.toml`. That file is a plain-text seed file, so anything in it can leak into backups, screenshots and the repository.
