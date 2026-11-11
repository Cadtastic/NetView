"""Port tables and the ports-spec parser, copied from the old LAN monitor (LM 100-106 and 415-463)."""

COMMON_PORTS = [
    (22, "SSH"),
    (23, "Telnet"),
    (53, "DNS"),
    (80, "HTTP"),
    (139, "NetBIOS"),
    (443, "HTTPS"),
    (445, "SMB"),
    (554, "RTSP"),
    (631, "IPP"),
    (1883, "MQTT"),
    (3389, "RDP"),
    (5000, "UPnP/NAS"),
    (5900, "VNC"),
    (8006, "Proxmox"),
    (8008, "Cast"),
    (8060, "Roku"),
    (8080, "HTTP-alt"),
    (8443, "HTTPS-alt"),
    (9100, "Printer"),
]

DEEP_PORTS = {
    1080: "SOCKS",
    1194: "OpenVPN",
    1433: "MS SQL",
    1521: "Oracle",
    1723: "PPTP",
    1883: "MQTT",
    2049: "NFS",
    2375: "Docker API",
    2376: "Docker TLS",
    3000: "Web app (Grafana/Node)",
    3001: "Web app",
    3128: "HTTP proxy",
    3306: "MySQL",
    3389: "RDP",
    3478: "STUN",
    4000: "Web app",
    4040: "Web app",
    4443: "HTTPS-alt",
    4567: "Web app",
    5000: "UPnP/NAS/Flask",
    5001: "Synology HTTPS",
    5060: "SIP",
    5222: "XMPP",
    5357: "WSD (Windows)",
    5432: "PostgreSQL",
    5555: "Android ADB",
    5900: "VNC",
    5901: "VNC",
    6000: "X11",
    6379: "Redis",
    6443: "Kubernetes API",
    6668: "Tuya",
    7000: "AirPlay",
    7001: "Web app",
    7070: "Web app",
    7100: "AirPlay",
    7443: "HTTPS-alt",
    8000: "HTTP-alt",
    8001: "HTTP-alt",
    8006: "Proxmox",
    8008: "Chromecast",
    8009: "Chromecast",
    8060: "Roku ECP",
    8080: "HTTP-alt",
    8081: "HTTP-alt",
    8083: "HTTP-alt",
    8086: "InfluxDB",
    8088: "HTTP-alt",
    8090: "HTTP-alt",
    8096: "Jellyfin/Emby",
    8123: "Home Assistant",
    8181: "HTTP-alt",
    8200: "Vault/DLNA",
    8291: "MikroTik Winbox",
    8333: "Bitcoin",
    8384: "Syncthing",
    8443: "HTTPS-alt",
    8500: "Consul",
    8834: "Nessus",
    8843: "UniFi HTTPS",
    8880: "UniFi HTTP",
    8888: "HTTP-alt",
    8920: "Jellyfin HTTPS",
    9000: "HTTP-alt/gRPC",
    9001: "HTTP-alt",
    9002: "HTTPS-alt/gRPC",
    9003: "HTTP-alt/gRPC",
    9004: "HTTP-alt",
    9005: "HTTPS-alt/gRPC",
    9006: "HTTP-alt",
    9080: "HTTP-alt",
    9090: "Cockpit/Prometheus",
    9091: "Transmission",
    9100: "Printer (JetDirect)",
    9200: "Elasticsearch",
    9443: "Portainer HTTPS",
    9999: "HTTP-alt",
    10000: "Webmin",
    10001: "UniFi discovery",
    10443: "HTTPS-alt",
    11211: "Memcached",
    16992: "Intel AMT",
    16993: "Intel AMT TLS",
    17500: "Dropbox LAN sync",
    20000: "Webmin/DNP3",
    27017: "MongoDB",
    32400: "Plex",
    49152: "UPnP",
    49153: "UPnP",
    49154: "UPnP",
    62078: "Apple lockdown (iPhone/iPad)",
}
LOW_NAMES = {
    21: "FTP",
    22: "SSH",
    23: "Telnet",
    25: "SMTP",
    53: "DNS",
    80: "HTTP",
    81: "HTTP-alt",
    88: "Kerberos",
    110: "POP3",
    111: "RPC",
    135: "MS RPC",
    139: "NetBIOS",
    143: "IMAP",
    389: "LDAP",
    443: "HTTPS",
    445: "SMB",
    465: "SMTPS",
    515: "LPD printer",
    548: "AFP",
    554: "RTSP",
    587: "SMTP submission",
    623: "IPMI",
    631: "IPP printer",
    636: "LDAPS",
    873: "rsync",
    902: "VMware",
    993: "IMAPS",
    995: "POP3S",
}
ALL_PORT_NAMES = {**LOW_NAMES, **DEEP_PORTS}
TLS_FIRST = {443, 465, 636, 993, 995, 4443, 5001, 6443, 7443, 8006, 8443, 8843, 8920, 9443, 10443, 16993}


def parse_ports(spec: str | None) -> list[int]:
    """Ports for a spec: ``top``, ``all``, ``common`` or a comma list such as ``22,80,8000-8100``."""
    spec = (spec or "top").strip().lower()
    if spec == "top":
        return sorted(set(range(1, 1025)) | set(DEEP_PORTS))
    if spec == "all":
        return list(range(1, 65536))
    if spec == "common":
        return [port for port, _ in COMMON_PORTS]
    ports: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        lo, hi = int(a), int(b or a)
        if not (1 <= lo <= hi <= 65535):
            raise ValueError(f"bad port range {part!r}")
        ports.update(range(lo, hi + 1))
    if not ports:
        raise ValueError("no ports")
    return sorted(ports)
