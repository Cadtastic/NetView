from netview.domain.device import Device, DeviceStatus


def test_status_values():
    assert [s.value for s in DeviceStatus] == ["online", "quiet", "offline"]


def test_device_defaults():
    d = Device("ip:10.0.0.2", "10.0.0.2", None, "", 1, 2, DeviceStatus.ONLINE)
    assert d.rtt_ms is None and d.ttl is None
    assert d.is_self is False and d.missed == 0 and d.is_new is False
