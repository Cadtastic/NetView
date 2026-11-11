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
    "os_hint",
    "vendor_type",
]


def test_sdk_version_is_1_1() -> None:
    assert sdk.SDK_VERSION == "1.1"


def test_new_public_types_are_exported() -> None:
    for name in NEW_NAMES:
        assert name in sdk.__all__, name
        assert hasattr(sdk, name), name


def test_every_exported_name_resolves() -> None:
    for name in sdk.__all__:
        assert hasattr(sdk, name), name
