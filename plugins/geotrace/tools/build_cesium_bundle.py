"""Build GeoTrace's trimmed, patched Cesium bundle from an official CesiumJS release zip.

Purpose:
    NetView's CSP (``script-src 'self'``, no ``unsafe-eval``, no blob workers, no wasm) means Cesium needs two
    text patches, and a plugin install downloads the whole repo, so the bundle is not committed. This tool
    makes the zip that the owner publishes as a release asset and that ``bundle.py`` downloads on first use.

    Kept from ``Build/Cesium/``: ``Cesium.js``, ``Workers/``, ``ThirdParty/``, ``Widgets/`` and, from
    ``Assets/``, only ``Textures/NaturalEarthII/``, ``Textures/SkyBox/``, ``Textures/moonSmall.jpg``,
    ``Images/`` and ``approximateTerrainHeights.json``. ``index.js`` and ``index.cjs`` are dropped.

    Exactly two patches are applied to ``Cesium.js``, each with an exact-count check; a different count
    means the Cesium version changed and the tool fails without writing anything:
      eval-global         ``var t=this||(0,eval)("this")``  ->  ``var t=this||globalThis``        (1 time)
      webassembly-guard   ``if(typeof WebAssembly!="object")return{supported:!1}``
                          ->  ``return{supported:!1}`` (turns off eager meshopt WebAssembly)         (5 times)

Usage:
    python build_cesium_bundle.py --release-zip Cesium-1.144.zip --out DIR            # dry run
    python build_cesium_bundle.py --release-zip Cesium-1.144.zip --out DIR --execute  # write the zip
    add --json for the machine-readable report

Inputs:
    --release-zip PATH   the official CesiumJS release zip (entries under ``Build/Cesium/``).
    --out DIR            the folder that receives ``cesium-bundle.zip`` (created on --execute).

Outputs:
    One line (kept files, bytes, output size and SHA-256), or with --json a report with schema id
    ``netview.geotrace/cesium-bundle@1``: executed, source, output_file, kept_files, total_bytes,
    output_bytes, sha256 and patches [{name, count, expected}]. The zip holds the kept files at its root
    and is reproducible (fixed timestamps and order), so the SHA-256 is the same on every run.
    Exit code 0 on success, 1 on any failure; a failure writes nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

SCHEMA = "netview.geotrace/cesium-bundle@1"
OUTPUT_NAME = "cesium-bundle.zip"
SOURCE_ROOT = "Build/Cesium/"
ENTRY = "Cesium.js"
KEEP_DIRS = ("Workers/", "ThirdParty/", "Widgets/")
KEEP_ASSETS = (
    "Assets/Textures/NaturalEarthII/",
    "Assets/Textures/SkyBox/",
    "Assets/Images/",
    "Assets/Textures/moonSmall.jpg",
    "Assets/approximateTerrainHeights.json",
)
PATCHES: tuple[tuple[str, bytes, bytes, int], ...] = (
    ("eval-global", b'var t=this||(0,eval)("this")', b"var t=this||globalThis", 1),
    (
        "webassembly-guard",
        b'if(typeof WebAssembly!="object")return{supported:!1}',
        b"return{supported:!1}",
        5,
    ),
)
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


class ToolError(Exception):
    """A failure the user should read; the tool exits 1 and writes nothing."""


def _kept(rel: str) -> bool:
    if rel == ENTRY or rel.startswith(KEEP_DIRS):
        return True
    return rel.startswith(KEEP_ASSETS)


def _patch(js: bytes) -> tuple[bytes, list[dict[str, Any]]]:
    report: list[dict[str, Any]] = []
    bad: list[str] = []
    for name, old, new, expected in PATCHES:
        count = js.count(old)
        report.append({"name": name, "count": count, "expected": expected})
        if count != expected:
            bad.append(f"patch {name}: found {count}, expected {expected}")
        else:
            js = js.replace(old, new)
    if bad:
        raise ToolError("; ".join(bad) + " (is this the Cesium version the patches were made for?)")
    return js, report


def build(release_zip: Path) -> tuple[bytes, dict[str, Any]]:
    """The bundle zip's bytes and the report, or ToolError. Reads only; writes nothing."""
    if not release_zip.is_file():
        raise ToolError(f"release zip not found: {release_zip}")
    try:
        source = zipfile.ZipFile(release_zip)
    except zipfile.BadZipFile as exc:
        raise ToolError(f"not a zip file: {release_zip}") from exc
    files: dict[str, bytes] = {}
    with source:
        for info in source.infolist():
            if info.is_dir() or not info.filename.startswith(SOURCE_ROOT):
                continue
            rel = info.filename[len(SOURCE_ROOT) :]
            if ".." in rel.split("/") or not _kept(rel):
                continue
            files[rel] = source.read(info)
    if ENTRY not in files:
        raise ToolError(f"{SOURCE_ROOT}{ENTRY} is not in the release zip")
    files[ENTRY], patches = _patch(files[ENTRY])
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in sorted(files):
            entry = zipfile.ZipInfo(rel, FIXED_TIME)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            z.writestr(entry, files[rel])
    data = out.getvalue()
    report = {
        "schema": SCHEMA,
        "executed": False,
        "source": str(release_zip),
        "output_file": OUTPUT_NAME,
        "kept_files": len(files),
        "total_bytes": sum(len(v) for v in files.values()),
        "output_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "patches": patches,
    }
    return data, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build GeoTrace's trimmed, patched Cesium bundle (dry run unless --execute).",
        epilog=f"JSON report schema id: {SCHEMA}. The file header lists the kept paths and patches.",
    )
    parser.add_argument("--release-zip", type=Path, required=True, help="the official CesiumJS release zip")
    parser.add_argument("--out", type=Path, required=True, help=f"folder that receives {OUTPUT_NAME}")
    parser.add_argument("--execute", action="store_true", help="write the zip (default: dry run)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    try:
        data, report = build(args.release_zip)
        if args.execute:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / OUTPUT_NAME).write_bytes(data)
            report["executed"] = True
            report["output_file"] = OUTPUT_NAME
    except (ToolError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        mode = "wrote" if args.execute else "dry run, would write"
        print(
            f"{mode} {args.out / OUTPUT_NAME}: {report['kept_files']} files, {report['total_bytes']} bytes, "
            f"zip {report['output_bytes']} bytes, sha256 {report['sha256']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
