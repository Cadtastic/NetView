"""What a device probably is, from its vendor and the TTL of its replies (identity and inspection)."""

_VENDOR_TYPES: tuple[tuple[str, str], ...] = (
    ("starlink", "Starlink router"),
    ("roku", "Roku device"),
    ("amazon", "Amazon device"),
    ("altobeam", "Smart-home gadget"),
    ("tpv display", "TV or monitor"),
    ("gaoshengda", "TV"),
    ("raspberry", "Raspberry Pi"),
    ("proxmox", "Proxmox VM"),
    ("hyper-v", "Hyper-V VM"),
    ("vmware", "VMware VM"),
    ("virtualbox", "VirtualBox VM"),
    ("netgear", "NETGEAR device"),
    ("ubiquiti", "Ubiquiti device"),
    ("dell", "Dell device"),
)


def _windows_ttl(ttl: int | None) -> bool:
    return bool(ttl and 64 < ttl <= 128)


def vendor_type(vendor: str, ttl: int | None, private_mac: bool) -> str:
    """A short type label from the vendor name, else from a private MAC or a Windows-like TTL, else ''."""
    v = (vendor or "").lower()
    for key, kind in _VENDOR_TYPES:
        if key in v:
            return kind
    if "intel" in v:
        return "Windows PC" if _windows_ttl(ttl) else "PC or laptop"
    if private_mac:
        return "Phone, tablet or laptop"
    if _windows_ttl(ttl):
        return "Windows PC"
    return ""


def os_hint(ttl: int | None) -> str:
    """A rough operating system guess from the TTL of a ping reply."""
    if not ttl:
        return ""
    if ttl <= 64:
        return "Linux/Apple/Android/embedded"
    if ttl <= 128:
        return "Windows"
    return "Network device"
