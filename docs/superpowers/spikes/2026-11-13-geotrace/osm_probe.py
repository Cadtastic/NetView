"""Spike S1 for the GeoTrace plugin: can NetView's server fetch OpenStreetMap tiles?

Fetches a few tiles from a slippy-map tile server the way GeoTrace's server-side
proxy would (stdlib urllib, an identifying User-Agent, no Referer), and prints
per tile: HTTP status, Content-Type, Cache-Control, Expires, ETag, size and
SHA-256. Optionally saves the tile bytes so they can be looked at.

Usage:
    python osm_probe.py [--base URL] [--user-agent UA] [--save-dir DIR] [--json]

Outputs: one line per tile on stdout, or with --json one JSON document
(schema netview.geotrace/osm-probe@1). Writes files only to --save-dir.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True

TILES = [(3, 1, 3), (8, 53, 97), (14, 3372, 6261), (17, 26987, 50097)]
DEFAULT_UA = "NetView-GeoTrace/0.1.0 (+https://github.com/Cadtastic/NetView)"


def fetch(base: str, z: int, x: int, y: int, ua: str) -> dict[str, object]:
    url = f"{base.rstrip('/')}/{z}/{x}/{y}.png"
    request = urllib.request.Request(url, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read()
            status, headers = response.status, response.headers
    except urllib.error.HTTPError as exc:
        body, status, headers = exc.read(), exc.code, exc.headers
    except OSError as exc:
        return {"url": url, "error": str(exc)}
    return {
        "url": url,
        "status": status,
        "content_type": headers.get("Content-Type"),
        "cache_control": headers.get("Cache-Control"),
        "expires": headers.get("Expires"),
        "etag": headers.get("ETag"),
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "_body": body,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="https://tile.openstreetmap.org/")
    parser.add_argument("--user-agent", default=DEFAULT_UA)
    parser.add_argument("--save-dir", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    results = []
    for z, x, y in TILES:
        result = fetch(args.base, z, x, y, args.user_agent)
        body = result.pop("_body", None)
        if args.save_dir and isinstance(body, bytes):
            args.save_dir.mkdir(parents=True, exist_ok=True)
            (args.save_dir / f"tile_{z}_{x}_{y}.png").write_bytes(body)
        results.append(result)
    if args.json:
        print(json.dumps({"schema": "netview.geotrace/osm-probe@1", "tiles": results}, indent=2))
    else:
        for r in results:
            print(r)
    ok = sum(1 for r in results if r.get("status") == 200)
    print(f"SUMMARY: {ok}/{len(results)} tiles answered 200", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
