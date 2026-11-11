"""GSM7248 plugin settings."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from netview.sdk import (
    SnmpTarget,
    SnmpV2c,
    SnmpV3,
    fixed_when,
    required_when,
    setting_group,
    settings_requirements,
    settings_tabs,
)

from .console import DEVICE_PATTERN, HOST_PATTERN, USER_PATTERN, ConsoleTarget

_V3 = {"snmp_version": "3"}

# settings form tabs, in this order, and the sections on them (each section starts at its first field)
GENERAL_TAB = "General"
SNMP_TAB = "SNMP"
SSH_TAB = "SSH"
CONNECTION = setting_group("Connection", tab=SNMP_TAB)
V2C = setting_group("SNMP v2c credentials", show_when={"snmp_version": "2c"}, tab=SNMP_TAB)
V3 = setting_group("SNMP v3 credentials", show_when=_V3, tab=SNMP_TAB)
POLLING = setting_group("Polling intervals", tab=GENERAL_TAB)
UPLINKS = setting_group("Uplinks", tab=GENERAL_TAB)
RETENTION = setting_group("Traffic history", tab=GENERAL_TAB)
ALERTS = setting_group("Alerts", tab=GENERAL_TAB)
CONSOLE = setting_group("Serial console", tab=SSH_TAB)

# What target() needs, stated in the settings schema so the host and the settings form agree on it.
REQUIREMENTS = settings_requirements(
    required=["host"],
    rules=[
        required_when({"snmp_version": "2c"}, ["community"]),
        required_when(_V3, ["v3_user"]),
        required_when({**_V3, "v3_auth_protocol": ["md5", "sha"]}, ["v3_auth_key"]),
        required_when({**_V3, "v3_priv_protocol": ["des", "aes128"]}, ["v3_priv_key"]),
        fixed_when(
            {**_V3, "v3_auth_protocol": "none"},
            "v3_priv_protocol",
            "none",
            "Privacy needs authentication: set an auth protocol or choose none here",
        ),
    ],
)


def _secret(value: SecretStr | None) -> str | None:
    text = value.get_secret_value() if value is not None else ""
    return text or None


class Gsm7248Settings(BaseModel):
    model_config = ConfigDict(
        json_schema_extra=settings_tabs([GENERAL_TAB, SNMP_TAB, SSH_TAB], then=REQUIREMENTS)
    )

    host: str = Field(
        "192.168.1.4", description="IP address or host name of the switch", json_schema_extra=CONNECTION
    )
    snmp_version: Literal["2c", "3"] = Field(
        "3",
        title="SNMP version",
        description="SNMP version. v3 with authentication and privacy is recommended",
        json_schema_extra=CONNECTION,
    )
    community: SecretStr | None = Field(
        None, title="Community", description="SNMP v2c read community", json_schema_extra=V2C
    )
    v3_user: str = Field("", title="User", description="SNMP v3 user name", json_schema_extra=V3)
    v3_auth_protocol: Literal["none", "md5", "sha"] = Field(
        "sha",
        title="Authentication protocol",
        description="SNMP v3 authentication protocol",
        json_schema_extra=V3,
    )
    v3_auth_key: SecretStr | None = Field(
        None,
        title="Authentication key",
        description="SNMP v3 authentication passphrase",
        json_schema_extra=V3,
    )
    v3_priv_protocol: Literal["none", "des", "aes128"] = Field(
        "des",
        title="Privacy protocol",
        description="SNMP v3 privacy (encryption) protocol",
        json_schema_extra=V3,
    )
    v3_priv_key: SecretStr | None = Field(
        None, title="Privacy key", description="SNMP v3 privacy passphrase", json_schema_extra=V3
    )
    timeout_s: float = Field(
        2.0, ge=0.5, le=10, description="Seconds to wait for one SNMP answer", json_schema_extra=CONNECTION
    )
    retries: int = Field(
        1,
        ge=0,
        le=3,
        description="Times to repeat an SNMP request that got no answer",
        json_schema_extra=CONNECTION,
    )
    counters_interval_s: int = Field(
        15,
        title="Port traffic (s)",
        ge=5,
        le=300,
        description="Seconds between port traffic counter polls",
        json_schema_extra=POLLING,
    )
    status_interval_s: int = Field(
        30,
        title="Port status, CPU and memory (s)",
        ge=10,
        le=600,
        description="Seconds between port status, CPU and memory polls",
        json_schema_extra=POLLING,
    )
    bridge_interval_s: int = Field(
        60,
        title="MAC address table (s)",
        ge=15,
        le=900,
        description="Seconds between MAC address table polls",
        json_schema_extra=POLLING,
    )
    topology_interval_s: int = Field(
        300,
        title="VLANs, spanning tree and inventory (s)",
        ge=60,
        le=3600,
        description="Seconds between VLAN, spanning tree, LAG and inventory polls",
        json_schema_extra=POLLING,
    )
    uplink_ports: list[str] = Field(
        default_factory=list,
        title="Uplink ports",
        description="Ports that lead to the rest of the network, for example 0/11",
        json_schema_extra=UPLINKS,
    )
    uplink_mac_threshold: int = Field(
        8,
        title="Uplink MAC threshold",
        ge=2,
        le=1000,
        description="A port that has learned more MAC addresses than this counts as an uplink",
        json_schema_extra=UPLINKS,
    )
    raw_retention_h: int = Field(
        24,
        title="Keep raw samples (h)",
        ge=1,
        le=168,
        description="Hours to keep every traffic sample",
        json_schema_extra=RETENTION,
    )
    rollup_retention_d: int = Field(
        30,
        title="Keep 5-minute averages (days)",
        ge=1,
        le=365,
        description="Days to keep the 5-minute traffic averages",
        json_schema_extra=RETENTION,
    )
    low_memory_kb: int = Field(
        1024,
        title="Low memory alert (KB)",
        ge=0,
        description="Raise an event when the free memory of the switch drops below this many KB",
        json_schema_extra=ALERTS,
    )
    console_enabled: bool = Field(
        False,
        title="Use the serial console",
        description="Probe the switch's serial console and open a terminal on it from the Switch page",
        json_schema_extra=CONSOLE,
    )
    console_ssh_host: str = Field(
        "192.168.1.36",
        title="SSH host",
        pattern=HOST_PATTERN,
        description="Host that has the serial cable to the switch, reached with your own SSH keys",
        json_schema_extra=CONSOLE,
    )
    console_ssh_user: str = Field(
        "root",
        title="SSH user",
        pattern=USER_PATTERN,
        description="User on the SSH host",
        json_schema_extra=CONSOLE,
    )
    console_device: str = Field(
        "/dev/ttyS0",
        title="Serial device",
        pattern=DEVICE_PATTERN,
        description="Serial device on the SSH host, for example /dev/ttyS0",
        json_schema_extra=CONSOLE,
    )
    console_baud: Literal["9600", "19200", "38400", "57600", "115200"] = Field(
        "38400",
        title="Speed (baud)",
        description="Speed of the switch's console port",
        json_schema_extra=CONSOLE,
    )

    def console_target(self) -> ConsoleTarget | None:
        """Where the serial console is, or None when it is turned off."""
        if not self.console_enabled:
            return None
        return ConsoleTarget(
            self.console_ssh_host, self.console_ssh_user, self.console_device, int(self.console_baud)
        )

    def target(self) -> SnmpTarget | None:
        """The SNMP target, or None when the credentials for the chosen version are incomplete."""
        if not self.host:
            return None
        if self.snmp_version == "2c":
            community = _secret(self.community)
            if community is None:
                return None
            return SnmpTarget(self.host, SnmpV2c(community), timeout_s=self.timeout_s, retries=self.retries)
        if not self.v3_user:
            return None
        auth_key = _secret(self.v3_auth_key)
        priv_key = _secret(self.v3_priv_key)
        if self.v3_auth_protocol == "none":
            if self.v3_priv_protocol != "none":
                return None  # SNMP v3 cannot encrypt without authenticating
            auth_key = priv_key = None
        elif auth_key is None:
            return None
        if self.v3_priv_protocol == "none":
            priv_key = None
        elif priv_key is None:
            return None
        credentials = SnmpV3(self.v3_user, self.v3_auth_protocol, auth_key, self.v3_priv_protocol, priv_key)
        return SnmpTarget(self.host, credentials, timeout_s=self.timeout_s, retries=self.retries)
