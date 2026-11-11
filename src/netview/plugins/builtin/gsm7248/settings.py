"""GSM7248 plugin settings."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SecretStr

from netview.sdk import SnmpTarget, SnmpV2c, SnmpV3


def _secret(value: SecretStr | None) -> str | None:
    text = value.get_secret_value() if value is not None else ""
    return text or None


class Gsm7248Settings(BaseModel):
    host: str = Field("192.168.1.4", description="IP address or host name of the switch")
    snmp_version: Literal["2c", "3"] = Field(
        "3",
        title="SNMP version",
        description="SNMP version. v3 with authentication and privacy is recommended",
    )
    community: SecretStr | None = Field(None, title="Community (v2c)", description="SNMP v2c read community")
    v3_user: str = Field("", title="v3 user", description="SNMP v3 user name")
    v3_auth_protocol: Literal["none", "md5", "sha"] = Field(
        "sha", title="v3 auth protocol", description="SNMP v3 authentication protocol"
    )
    v3_auth_key: SecretStr | None = Field(
        None, title="v3 auth key", description="SNMP v3 authentication passphrase"
    )
    v3_priv_protocol: Literal["none", "des", "aes128"] = Field(
        "des", title="v3 privacy protocol", description="SNMP v3 privacy (encryption) protocol"
    )
    v3_priv_key: SecretStr | None = Field(
        None, title="v3 privacy key", description="SNMP v3 privacy passphrase"
    )
    timeout_s: float = Field(2.0, ge=0.5, le=10, description="Seconds to wait for one SNMP answer")
    retries: int = Field(1, ge=0, le=3, description="Times to repeat an SNMP request that got no answer")
    counters_interval_s: int = Field(
        15, ge=5, le=300, description="Seconds between port traffic counter polls"
    )
    status_interval_s: int = Field(
        30, ge=10, le=600, description="Seconds between port status, CPU and memory polls"
    )
    bridge_interval_s: int = Field(60, ge=15, le=900, description="Seconds between MAC address table polls")
    topology_interval_s: int = Field(
        300, ge=60, le=3600, description="Seconds between VLAN, spanning tree, LAG and inventory polls"
    )
    uplink_ports: list[str] = Field(
        default_factory=list,
        title="Uplink ports",
        description="Ports that lead to the rest of the network, for example 0/11",
    )
    uplink_mac_threshold: int = Field(
        8,
        title="Uplink MAC threshold",
        ge=2,
        le=1000,
        description="A port that has learned more MAC addresses than this counts as an uplink",
    )
    raw_retention_h: int = Field(
        24, title="Keep raw samples (h)", ge=1, le=168, description="Hours to keep every traffic sample"
    )
    rollup_retention_d: int = Field(
        30,
        title="Keep 5-minute averages (days)",
        ge=1,
        le=365,
        description="Days to keep the 5-minute traffic averages",
    )
    low_memory_kb: int = Field(
        1024,
        title="Low memory alert (KB)",
        ge=0,
        description="Raise an event when the free memory of the switch drops below this many KB",
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
