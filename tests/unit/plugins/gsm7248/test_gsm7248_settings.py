from __future__ import annotations

import pytest

from netview.plugins.builtin.gsm7248.settings import Gsm7248Settings
from netview.sdk import SnmpV2c, SnmpV3


def test_defaults() -> None:
    s = Gsm7248Settings()
    assert s.host == "192.168.1.4"
    assert s.snmp_version == "3"
    assert s.community is None
    assert (s.counters_interval_s, s.status_interval_s, s.bridge_interval_s, s.topology_interval_s) == (
        15,
        30,
        60,
        300,
    )
    assert s.uplink_ports == []
    assert s.low_memory_kb == 1024


def test_every_field_has_a_description() -> None:
    missing = [n for n, f in Gsm7248Settings.model_fields.items() if not f.description]
    assert missing == []


def test_default_target_is_none_without_credentials() -> None:
    assert Gsm7248Settings().target() is None


def test_v2c_target() -> None:
    s = Gsm7248Settings(snmp_version="2c", community="public", timeout_s=3.0, retries=2)
    target = s.target()
    assert target is not None
    assert target.host == "192.168.1.4"
    assert target.credentials == SnmpV2c("public")
    assert (target.timeout_s, target.retries) == (3.0, 2)


def test_v2c_without_community_is_none() -> None:
    assert Gsm7248Settings(snmp_version="2c", community="").target() is None


def test_v3_target() -> None:
    s = Gsm7248Settings(v3_user="netview", v3_auth_key="authkey123", v3_priv_key="privkey123")
    target = s.target()
    assert target is not None
    assert target.credentials == SnmpV3("netview", "sha", "authkey123", "des", "privkey123")


@pytest.mark.parametrize(
    "values",
    [
        {"v3_user": ""},
        {"v3_user": "u", "v3_auth_key": None, "v3_priv_key": "k"},
        {"v3_user": "u", "v3_auth_key": "k", "v3_priv_key": None},
    ],
)
def test_v3_incomplete_is_none(values: dict[str, object]) -> None:
    base: dict[str, object] = {"v3_user": "u", "v3_auth_key": "k", "v3_priv_key": "k"}
    assert Gsm7248Settings(**{**base, **values}).target() is None  # type: ignore[arg-type]


def test_v3_no_auth_no_priv_needs_only_user() -> None:
    s = Gsm7248Settings(v3_user="u", v3_auth_protocol="none", v3_priv_protocol="none")
    target = s.target()
    assert target is not None
    assert target.credentials == SnmpV3("u", "none", None, "none", None)


def test_priv_without_auth_is_incomplete() -> None:
    s = Gsm7248Settings(v3_user="u", v3_auth_protocol="none", v3_priv_protocol="des", v3_priv_key="k")
    assert s.target() is None


def test_secrets_are_not_in_repr() -> None:
    s = Gsm7248Settings(snmp_version="2c", community="s3cr3t")
    assert "s3cr3t" not in repr(s)
    assert "s3cr3t" not in str(s.model_dump())


@pytest.mark.parametrize("field,value", [("timeout_s", 0.1), ("retries", 4), ("counters_interval_s", 1)])
def test_bounds(field: str, value: float) -> None:
    with pytest.raises(ValueError):
        Gsm7248Settings(**{field: value})
