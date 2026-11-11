#!/usr/bin/env python3
"""Find Roku devices on the local network.

Purpose:  Lists every Roku (TV, streaming stick or box) that answers the Roku
          External Control Protocol (ECP) on port 8060, with its name, model,
          location, power state and ECP access setting. Read-only: it sends
          SSDP searches and HTTP GET /query/device-info requests, nothing else.

Usage:    python find_rokus.py [--subnet 192.168.1.0/24] [--timeout 2]
                               [--workers 128] [--no-sweep] [--no-ssdp]
                               [--out rokus.json]

          It also runs when pasted into a terminal:
            macOS / Linux:       python3 - <<'EOF'  ...script...  EOF
            Windows PowerShell:  @'  ...script...  '@ | python -

Inputs:   None required. The subnet defaults to this computer's IPv4 address
          as a /24.

Outputs:  JSON on stdout, schema ketiv.network-tools/roku-scan@1:
            {"schema": "...", "subnet": "192.168.1.0/24",
             "devices": [{"ip", "name", "model", "location", "tv",
                          "mode", "power", "found_by"}]}
          devices are sorted by IP. "mode" is the ECP Network access setting
          (default, permissive, limited, disabled) or "" when unknown.
          A one-line summary goes to stderr. Writes a file only with --out.

How:      Sends an SSDP M-SEARCH for roku:ecp out the LAN adapter and, at the
          same time, requests http://<ip>:8060/query/device-info from every
          address in the subnet. Python 3.9+, standard library only.
"""
import argparse
import concurrent.futures
import ipaddress
import json
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True

SCHEMA = "ketiv.network-tools/roku-scan@1"
PORT = 8060
SSDP_ADDR = ("239.255.255.250", 1900)
MAX_SWEEP = 1024

# Talk to LAN addresses directly, never through an HTTP proxy from the environment.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def local_ip():
    """This computer's IPv4 address on the default route (sends no packets)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def blank(ip):
    return {"ip": ip, "name": "", "model": "", "location": "", "tv": False, "mode": "", "power": ""}


def fetch_info(ip, timeout):
    """Return a device dict if ip answers like a Roku on port 8060, else None."""
    url = "http://%s:%d/query/device-info" % (ip, PORT)
    try:
        with OPENER.open(url, timeout=timeout) as resp:
            body = resp.read(262144)
    except urllib.error.HTTPError as e:
        # ECP answered but refused device-info: still a Roku if it says so.
        if "roku" in (e.headers.get("Server") or "").lower():
            return blank(ip)
        return None
    except Exception:
        return None
    upper = body[:4096].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        return None
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    if root.tag != "device-info":
        return None

    def field(tag):
        el = root.find(tag)
        return (el.text or "").strip() if el is not None else ""

    name = field("user-device-name") or field("friendly-device-name") or field("default-device-name")
    return {
        "ip": ip,
        "name": name,
        "model": field("model-name"),
        "location": field("user-device-location"),
        "tv": field("is-tv") == "true",
        "mode": field("ecp-setting-mode").lower(),
        "power": field("power-mode"),
    }


def ssdp_search(iface_ip, wait):
    """Return the set of IPs that answer an SSDP search for roku:ecp."""
    found = set()
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 2\r\n"
        "ST: roku:ecp\r\n\r\n"
    ).encode("ascii")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        if iface_ip:
            # Send out the LAN adapter, not a VPN or virtual (Hyper-V, WSL, Docker) one.
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface_ip))
                s.bind((iface_ip, 0))
            except OSError:
                pass
        for _ in range(2):
            s.sendto(msg, SSDP_ADDR)
        end = time.monotonic() + wait
        while True:
            left = end - time.monotonic()
            if left <= 0:
                break
            s.settimeout(left)
            try:
                data, _ = s.recvfrom(65535)
            except (socket.timeout, OSError):
                break
            m = re.search(rb"(?im)^location:\s*http://([0-9.]+):8060", data)
            if m:
                found.add(m.group(1).decode("ascii"))
    except OSError:
        pass
    finally:
        s.close()
    return found


def sweep(net, timeout, workers):
    hosts = [str(h) for h in net.hosts()]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return [d for d in pool.map(lambda ip: fetch_info(ip, timeout), hosts) if d]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Find Roku devices on the local network (read-only).",
        epilog="Prints JSON (schema %s) on stdout and a summary on stderr." % SCHEMA,
    )
    ap.add_argument("--subnet", help="IPv4 network to check, e.g. 192.168.1.0/24 (default: this computer's address as a /24)")
    ap.add_argument("--timeout", type=float, default=2.0, help="seconds to wait per address and for SSDP replies (default 2)")
    ap.add_argument("--workers", type=int, default=128, help="addresses checked at once (default 128)")
    ap.add_argument("--no-sweep", action="store_true", help="use SSDP only; don't check each address")
    ap.add_argument("--no-ssdp", action="store_true", help="check each address only; don't send SSDP")
    ap.add_argument("--out", help="also write the JSON to this file")
    args = ap.parse_args(argv)

    me = local_ip()
    net = None
    if args.subnet:
        try:
            net = ipaddress.IPv4Network(args.subnet, strict=False)
        except ValueError as e:
            ap.error("--subnet: %s" % e)
    elif me:
        net = ipaddress.IPv4Network(me + "/24", strict=False)
    if net is not None and not args.no_sweep and net.num_addresses > MAX_SWEEP:
        ap.error("--subnet %s has %d addresses; use a /22 or smaller, or --no-sweep" % (net, net.num_addresses))

    ssdp_result = {"ips": set()}
    ssdp_thread = None
    if not args.no_ssdp:
        ssdp_thread = threading.Thread(
            target=lambda: ssdp_result.update(ips=ssdp_search(me, args.timeout)), daemon=True
        )
        ssdp_thread.start()

    devices = {}
    if net is not None and not args.no_sweep:
        for d in sweep(net, args.timeout, args.workers):
            d["found_by"] = "sweep"
            devices[d["ip"]] = d
    if ssdp_thread is not None:
        ssdp_thread.join()
    ssdp_ips = ssdp_result["ips"]
    for ip in ssdp_ips:
        if ip in devices:
            devices[ip]["found_by"] = "ssdp+sweep"
        else:
            d = fetch_info(ip, args.timeout) or blank(ip)
            d["found_by"] = "ssdp"
            devices[ip] = d

    result = {
        "schema": SCHEMA,
        "subnet": str(net) if net is not None else None,
        "devices": sorted(devices.values(), key=lambda d: ipaddress.IPv4Address(d["ip"])),
    }
    text = json.dumps(result)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    n = len(result["devices"])
    swept = sum(1 for d in devices.values() if "sweep" in d["found_by"])
    print(
        "Found %d Roku device%s (subnet %s; %d by address check, %d by SSDP)."
        % (n, "" if n == 1 else "s", result["subnet"] or "none", swept, len(ssdp_ips)),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
