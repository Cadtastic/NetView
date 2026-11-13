import netview.sdk as sdk

NEW_NAMES = [
    "CertInfo",
    "DnsRecord",
    "HealthTargets",
    "HostInfo",
    "HttpProbe",
    "NAME_RANKS",
    "NetbiosInfo",
    "NetbiosName",
    "ServiceProbes",
    "SsdpEntry",
    "SystemInfo",
    "TcpSocket",
    "TrafficTotals",
    "TrafficView",
    "TYPE_RANKS",
    "WatchProbe",
    "WatchState",
    "WatchStatus",
    "Watch",
    "WifiInfo",
    "UserPermission",
    "Principal",
    "counter_rate",
    "os_hint",
    "vendor_type",
]


def test_sdk_version_is_2() -> None:
    assert sdk.SDK_VERSION == "2.0"


def test_network_control_permission() -> None:
    assert sdk.Permission.NETWORK_CONTROL.value == "network:control"


def test_new_public_types_are_exported() -> None:
    for name in NEW_NAMES:
        assert name in sdk.__all__, name
        assert hasattr(sdk, name), name


def test_every_exported_name_resolves() -> None:
    for name in sdk.__all__:
        assert hasattr(sdk, name), name
