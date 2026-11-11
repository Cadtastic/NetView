"""Build the plugin index from every ``plugins/*/plugin.json``.

Purpose:
    The app lists installable plugins from an index file. This script collects the ``plugin.json``
    of every plugin folder and writes that index twice: ``plugins/index.json`` (fetched from GitHub
    by the app) and a copy bundled in the package (used when GitHub cannot be reached).

Usage:
    uv run python scripts/build_plugin_index.py             # dry run: say what would change
    uv run python scripts/build_plugin_index.py --execute   # write both files
    uv run python scripts/build_plugin_index.py --check     # exit 1 when either file is out of date

Outputs:
    ``--out`` (default plugins/index.json) and ``--bundle`` (default
    src/netview/infrastructure/plugins/catalog.json), UTF-8, LF, schema ``netview.plugin-index/1``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from netview.application.plugins.plugin_json import (  # noqa: E402
    DEFAULT_ARCHIVE_URL,
    PluginJson,
    build_index,
    index_to_dict,
    parse_plugin_json,
)
from netview.domain.errors import ValidationError  # noqa: E402


def _read_plugins(plugins_dir: Path) -> list[PluginJson]:
    found: list[PluginJson] = []
    for path in sorted(plugins_dir.glob("*/plugin.json")):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        pj = parse_plugin_json(data)
        if path.parent.name != pj.id:
            raise ValidationError(f"{path}: folder name {path.parent.name!r} must equal id {pj.id!r}")
        found.append(pj)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build plugins/index.json and the bundled catalog copy.")
    parser.add_argument("--plugins-dir", type=Path, default=Path("plugins"))
    parser.add_argument("--ref", default="main", help="git ref the archive is taken from")
    parser.add_argument("--archive-url", default=DEFAULT_ARCHIVE_URL)
    parser.add_argument("--out", type=Path, default=Path("plugins/index.json"))
    parser.add_argument(
        "--bundle", type=Path, default=Path("src/netview/infrastructure/plugins/catalog.json")
    )
    parser.add_argument("--execute", action="store_true", help="write the files (default is a dry run)")
    parser.add_argument("--check", action="store_true", help="exit 1 when a file differs from a fresh build")
    args = parser.parse_args(argv)

    index = build_index(_read_plugins(args.plugins_dir), args.ref, args.archive_url)
    text = json.dumps(index_to_dict(index), indent=2, sort_keys=False, ensure_ascii=False) + "\n"
    stale: list[Path] = []
    for target in (args.out, args.bundle):
        # a Windows checkout (core.autocrlf) may turn the committed LF into CRLF; that is not a change
        current = target.read_bytes().replace(b"\r\n", b"\n") if target.is_file() else None
        if current != text.encode("utf-8"):
            stale.append(target)
            if args.execute and not args.check:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(text.encode("utf-8"))
    count = len(index.plugins)
    if args.check:
        print(f"{count} plugins; {len(stale)} file(s) out of date")
        return 1 if stale else 0
    verb = "wrote" if args.execute else "would write"
    names = ", ".join(str(p) for p in stale) or "nothing (already up to date)"
    print(f"{count} plugins; {verb}: {names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
