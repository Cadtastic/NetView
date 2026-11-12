"""Serve a fake copy of the GitHub plugin repo, for trying the Available gallery without pushing.

Purpose:
    netview reads its plugin list from ``plugins/index.json`` on GitHub and installs from the repo's zip
    archive. Before a branch is merged and pushed, neither has the branch's plugins. This script builds
    both from a local ``plugins`` folder and serves them on 127.0.0.1, so a netview started with
    ``NETVIEW_PLUGIN_CATALOG_URL`` pointing here lists and installs them.

Usage:
    uv run python scripts/serve_fake_plugin_repo.py              # dry run: list what it would serve
    uv run python scripts/serve_fake_plugin_repo.py --execute    # serve until Ctrl+C
    uv run python scripts/serve_fake_plugin_repo.py --execute --throttle-kbps 64   # watch the progress bar

Outputs:
    Nothing on disk outside a temporary folder that is removed on exit. Serves
    ``/plugins/index.json`` (schema ``netview.plugin-index/2``) and ``/netview.zip`` (top folder
    ``NetView-main/``, like a GitHub archive). Prints the catalog URL to use.
"""

from __future__ import annotations

import argparse
import functools
import json
import sys
import tempfile
import time
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_plugin_index import _read_plugins  # noqa: E402

from netview.application.plugins.plugin_json import build_index, index_to_dict  # noqa: E402

TOP = "NetView-main"
SKIP_PARTS = {"__pycache__"}


def build_site(plugins_dir: Path, site: Path, port: int) -> int:
    """Write ``site/plugins/index.json`` and ``site/netview.zip``; return the number of plugins."""
    plugins = _read_plugins(plugins_dir)
    archive = site / "netview.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in plugins:
            folder = plugins_dir / entry.path.rsplit("/", 1)[-1]
            for path in sorted(folder.rglob("*")):
                rel = path.relative_to(plugins_dir)
                if path.is_file() and not SKIP_PARTS.intersection(rel.parts):
                    zf.write(path, f"{TOP}/plugins/{rel.as_posix()}")
    index = build_index(plugins, "main", f"http://127.0.0.1:{port}/netview.zip")
    out = site / "plugins" / "index.json"
    out.parent.mkdir(parents=True)
    out.write_text(json.dumps(index_to_dict(index), indent=2) + "\n", encoding="utf-8")
    return len(plugins)


class _Handler(SimpleHTTPRequestHandler):
    throttle_bps: int = 0

    def copyfile(self, source, outputfile) -> None:  # type: ignore[no-untyped-def]
        if not self.throttle_bps or not self.path.endswith(".zip"):
            super().copyfile(source, outputfile)
            return
        chunk = max(1024, self.throttle_bps // 10)
        while data := source.read(chunk):
            outputfile.write(data)
            outputfile.flush()
            time.sleep(len(data) / self.throttle_bps)

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write(f"{self.address_string()} {format % args}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve a fake GitHub plugin repo on 127.0.0.1.")
    parser.add_argument("--plugins-dir", type=Path, default=Path("plugins"))
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--throttle-kbps", type=int, default=0, help="slow the zip download (0 = full speed)")
    parser.add_argument("--execute", action="store_true", help="start serving (default is a dry run)")
    args = parser.parse_args(argv)

    url = f"http://127.0.0.1:{args.port}/plugins/index.json"
    if not args.execute:
        names = ", ".join(e.plugin.display_name for e in _read_plugins(args.plugins_dir))
        print(f"would serve {names} at {url}")
        return 0
    with tempfile.TemporaryDirectory(prefix="netview-fake-repo-") as tmp:
        count = build_site(args.plugins_dir, Path(tmp), args.port)
        handler = functools.partial(_Handler, directory=tmp)
        _Handler.throttle_bps = args.throttle_kbps * 1024
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
        print(f"serving {count} plugins; set NETVIEW_PLUGIN_CATALOG_URL={url}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
