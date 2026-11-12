"""Turn an inspection result into report sections, each with the plain text ``netview inspect`` prints.

The result dict is shaped like the old LAN monitor's ``inspect_host`` result (see ``hints.py``) plus ``ip``,
``ports_spec``, ``rtt``, ``mac``, ``os_hint``, ``hints``, ``device_name``, ``name_source``, ``type`` and
``duration``.
"""

from typing import Any

from netview.sdk import ReportSection

PLUGIN_GUID = "ac1dc07d-123c-4414-a4c8-72013d00f267"  # sections are saved under the guid
NO_NAMES = "none found (reverse DNS, NetBIOS, mDNS, UPnP)"
NO_DISCOVERY = "No answer to mDNS, UPnP/SSDP or NetBIOS."


def _section(section_id: str, title: str, data: dict[str, Any]) -> ReportSection:
    return ReportSection(PLUGIN_GUID, section_id, title, data)


def cert_line(cert: dict[str, Any] | None, tls: str | None) -> str:
    """One line about a TLS certificate; every value came from the device."""
    if not cert or cert.get("subject") is None:
        return f"TLS {tls}" if tls else ""
    org = f" ({cert['subject_org']})" if cert.get("subject_org") else ""
    parts = [
        f"TLS {tls or ''}".strip(),
        f"certificate {cert.get('subject') or '(no name)'}{org}",
        f"issued by {cert.get('issuer_org') or cert.get('issuer') or '?'}",
    ]
    if cert.get("self_signed"):
        parts.append("self-signed")
    parts.append(f"expires {cert.get('not_after') or '?'}")
    if cert.get("san"):
        parts.append(f"also {', '.join(cert['san'])}")
    return ", ".join(parts)


def _ping_text(r: dict[str, Any]) -> str:
    if r.get("rtt") is None:
        return "ping no reply"
    ttl = f", TTL {r['ttl']} ({r['os_hint']})" if r.get("ttl") else ""
    return f"ping {r['rtt']} ms{ttl}"


def summary_section(r: dict[str, Any]) -> ReportSection:
    text: list[str] = []
    if r["type"]:
        text.append(f"Looks like: {r['type']}")
    if r["device_name"]:
        text.append(f"Name: {r['device_name']} (from {r['name_source']})")
    text += [f"* {h}" for h in r["hints"]] or ["No clear match."]
    data = {
        "hints": r["hints"],
        "type": r["type"],
        "device_name": r["device_name"],
        "name_source": r["name_source"],
        "text": text,
    }
    return _section("summary", "What it probably is", data)


def identity_section(r: dict[str, Any]) -> ReportSection:
    nb = r.get("netbios")
    text = [
        f"MAC {r['mac'] or '-'}{' ' + r['vendor'] if r['vendor'] else ''}; {_ping_text(r)}",
        f"Names: {', '.join(r['names']) or NO_NAMES}",
    ]
    if nb:
        text.append(f"NetBIOS {nb['name']}{' workgroup ' + nb['workgroup'] if nb.get('workgroup') else ''}")
    data = {
        "mac": r["mac"],
        "vendor": r["vendor"],
        "private_mac": r["private_mac"],
        "rtt_ms": r["rtt"],
        "ttl": r["ttl"],
        "os_hint": r["os_hint"],
        "names": r["names"],
        "netbios": nb,
        "text": text,
    }
    return _section("identity", "Identity", data)


def web_items(open_ports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ports that answered HTTP, as the Web interfaces section lists them."""
    items = []
    for p in open_ports:
        h = p.get("http")
        if h and h.get("url") and h.get("status") is not None:
            items.append(
                {
                    "port": p["port"],
                    "url": h["url"],
                    "status": h["status"],
                    "reason": h.get("reason", ""),
                    "title": h.get("title", ""),
                    "server": h.get("server", ""),
                    "powered_by": h.get("powered_by", ""),
                    "generator": h.get("generator", ""),
                    "realm": h.get("realm", ""),
                    "location": h.get("location", ""),
                    "tls": h.get("tls"),
                    "cert": h.get("cert"),
                }
            )
    return items


def web_section(items: list[dict[str, Any]]) -> ReportSection:
    text: list[str] = []
    for w in items:
        line = f"{w['url']} {w['status']}"
        if w["title"]:
            line += f" {w['title']}"
        if w["server"]:
            line += f" [server: {w['server']}]"
        if w["location"]:
            line += f" -> {w['location']}"
        if w["realm"]:
            line += f" (login: {w['realm']})"
        text.append(line)
        if w["cert"]:
            text.append(f"  {cert_line(w['cert'], w['tls'])}")
    return _section("web", "Web interfaces", {"items": items, "text": text})


def _port_line(p: dict[str, Any]) -> list[str]:
    line = f"{p['port']:>5}/tcp {p['name'] or '?':<14}"
    h = p.get("http")
    if p.get("banner"):
        return [f"{line} banner: {p['banner']}"]
    if p.get("skipped"):
        return [f"{line} (open; not analyzed)"]
    if not h:
        return [f"{line} (open; sends no greeting and doesn't speak HTTP)"]
    line += f" {h.get('url') or h['scheme']} {h.get('status') or ''} {h.get('title') or ''}".rstrip()
    if h.get("server"):
        line += f" [server: {h['server']}]"
    if h.get("location"):
        line += f" -> {h['location']}"
    if h.get("realm"):
        line += f" (login: {h['realm']})"
    out = [line]
    if h.get("cert"):
        out.append(f"{'':>14}{cert_line(h['cert'], h.get('tls'))}")
    return out


def ports_section(r: dict[str, Any], states: list[dict[str, Any]] | None = None) -> ReportSection:
    p = r["ports"]
    text = [
        f"{p['scanned']} TCP ports in {r['duration']} s: {len(p['open'])} open, {p['refused']} refused, "
        f"{p['no_answer']} no answer"
    ]
    for o in p["open"]:
        text += _port_line(o)
    data: dict[str, Any] = {
        "ports_spec": r["ports_spec"],
        "scanned": p["scanned"],
        "open": p["open"],
        "refused": p["refused"],
        "no_answer": p["no_answer"],
        "duration_s": r["duration"],
    }
    if states is not None:
        data["states"] = states
    data["text"] = text
    return _section("ports", "Open TCP ports", data)


def mdns_section(mdns: dict[str, Any]) -> ReportSection:
    text = [f"mDNS host name: {mdns['hostname']}"] if mdns.get("hostname") else []
    for s in mdns.get("services", []):
        line = f"mDNS {s['type']}: {', '.join(s['instances']) or '-'}"
        if s["txt"]:
            line += " " + " ".join(f"{k}={v}" for k, v in s["txt"].items())
        text.append(line)
    return _section("mdns", "mDNS and Bonjour", {**mdns, "text": text})


def upnp_section(entries: list[dict[str, Any]]) -> ReportSection:
    text = []
    for u in entries:
        who = " ".join(x for x in (u.get("friendlyName"), u.get("manufacturer"), u.get("modelName")) if x)
        text.append(f"UPnP {who or 'device'} [{u.get('server', '')}]")
    return _section("upnp", "UPnP and SSDP", {"entries": entries, "text": text})


def discovery_section() -> ReportSection:
    return _section("discovery", "Discovery protocols", {"text": [NO_DISCOVERY]})


def build_sections(r: dict[str, Any]) -> list[ReportSection]:
    """The sections of a full inspection, in order; Web, mDNS, UPnP and discovery only if non-empty."""
    out = [summary_section(r), identity_section(r)]
    items = web_items(r["ports"]["open"])
    if items:
        out.append(web_section(items))
    out.append(ports_section(r))
    if r.get("mdns"):
        out.append(mdns_section(r["mdns"]))
    if r.get("upnp"):
        out.append(upnp_section(r["upnp"]))
    if not r.get("mdns") and not r.get("upnp") and not r.get("netbios"):
        out.append(discovery_section())
    return out
