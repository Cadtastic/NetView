# GSM7248 switch setup for NetView

This sets up read-only SNMP on the NETGEAR GSM7248 (software 6.3.3.7) so the NetView `gsm7248` plugin can poll it.

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

Run `show snmpcommunity` again and confirm `private` is gone or disabled. NetView only reads, so it never needs read/write access.

## 3. SNMPv3 (recommended)

Create a read-only user `netview` with SHA authentication and DES privacy. On NETGEAR GSM72xx FASTPATH 6.x/7.x firmware, SNMPv3 users are usually local user accounts, so try this sequence first:

```
users name NetView
users passwd NetView
users snmpv3 accessmode NetView readonly
users snmpv3 authentication NetView sha
users snmpv3 encryption NetView des <your-priv-passphrase>
```

(check against the CLI reference)

Notes:

- `users passwd NetView` prompts for the account's login password. On this family that password may double as the SNMPv3 authentication key, so make it 8 or more characters and use it as the authentication passphrase in netview.
- The `readonly` access mode step is what keeps the user read-only. Do not skip it.
- Ask the switch for the real keywords: `users ?` and `users snmpv3 ?` show what this release accepts. (check against the CLI reference)
- If `users snmpv3 ...` is rejected, the release may be a later one that uses the `snmp-server user` family instead. Run `snmp-server user ?` and build the user from that output. A sketch, to be corrected from the `?` output and the reference:

```
snmp-server user NetView
snmp-server user NetView auth sha <your-auth-passphrase>
snmp-server user NetView priv des <your-priv-passphrase>
```

(check against the CLI reference)

- If 6.3.3.7 does not support SHA or DES, use the strongest pair it lists. NetView supports the SHA and MD5 authentication protocols and DES and AES privacy. Remember which pair you used, because step 6 needs the same values.
- Passphrases are usually at least 8 characters.

## 4. SNMPv2c alternative

Use this only if v3 is not workable. Create a read-only community restricted to the laptop's IP:

```
snmp-server community <your-community>
snmp-server community accessmode ro <your-community>
snmp-server community ipaddr <laptop-ip> <your-community>
snmp-server community ipmask 255.255.255.255 <your-community>
snmp-server community mode <your-community>
```

(check against the CLI reference)

The `ipaddr` line alone does not restrict anything: the default mask is 0.0.0.0, which matches any address. The `ipmask 255.255.255.255` line is what limits the community to the single laptop. Confirm with `show snmpcommunity` that the mask is 255.255.255.255 and the access mode is Read Only.

The laptop's IP is assigned by DHCP today. A restriction to that address breaks when the lease changes, so either add a DHCP reservation for the laptop first, or use v3.

## 5. Save the configuration

```
copy system:running-config nvram:startup-config
```

Answer the confirmation prompt with `y`. Without this, the changes are lost at the next reboot. (check against the CLI reference)

## 6. Check from the laptop

1. Open NetView, then Settings, then the **NETGEAR GSM7248** tab.
2. Set the host (default `192.168.1.4`) and the SNMP version. For v3, set the user (`netview`), the auth protocol, the auth passphrase, the privacy protocol and the privacy passphrase to match what you configured on the switch (set `v3_auth_protocol` and `v3_priv_protocol` to the pair you used, especially if you fell back to MD5 or AES). For v2c, enter the community.
3. Press **Save** and wait for "Settings saved". The test uses the saved settings only.
4. Under Connection, press **Test connection**. It should report "Connected: " followed by the switch's sysDescr.

## Where secrets go

SNMP secrets go **only** into NetView's Settings dialog. Never put them in a `[plugins."3ae5ddcb-5e96-4dcc-b439-7b582a37b0f4"]` section (seed sections are keyed by guid) of `netview.toml`. That file is a plain-text seed file, so anything in it can leak into backups, screenshots and the repository.
