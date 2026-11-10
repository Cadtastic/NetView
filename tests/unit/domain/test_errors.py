from netview.domain.errors import CapabilityUnavailableError, NetviewError


def test_capability_unavailable_message():
    e = CapabilityUnavailableError("inspection.tls")
    assert isinstance(e, NetviewError)
    assert e.capability == "inspection.tls"
    assert str(e) == "no enabled plugin provides inspection.tls"
