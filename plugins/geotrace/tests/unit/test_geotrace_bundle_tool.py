"""The tool that trims and patches a Cesium release into GeoTrace's bundle."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest
from netview_local_plugins.geotrace import bundle

TOOL = Path(__file__).resolve().parents[2] / "tools" / "build_cesium_bundle.py"
EVAL_OLD = b'var t=this||(0,eval)("this")'
EVAL_NEW = b"var t=this||globalThis"
WASM_OLD = b'if(typeof WebAssembly!="object")return{supported:!1}'
WASM_NEW = b"return{supported:!1}"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_cesium_bundle", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cesium_js(evals: int = 1, wasms: int = 5) -> bytes:
    return b"/*c*/" + b";".join([EVAL_OLD] * evals + [WASM_OLD] * wasms) + b";end"


def release(path: Path, js: bytes | None = None) -> Path:
    files = {
        "Build/Cesium/Cesium.js": js if js is not None else cesium_js(),
        "Build/Cesium/index.js": b"x",
        "Build/Cesium/index.cjs": b"x",
        "Build/Cesium/Workers/a.js": b"w",
        "Build/Cesium/ThirdParty/b.js": b"t",
        "Build/Cesium/Widgets/widgets.css": b"c",
        "Build/Cesium/Assets/Textures/NaturalEarthII/0/0/0.jpg": b"j",
        "Build/Cesium/Assets/Textures/SkyBox/px.jpg": b"s",
        "Build/Cesium/Assets/Textures/moonSmall.jpg": b"m",
        "Build/Cesium/Assets/Textures/maki/x.png": b"no",
        "Build/Cesium/Assets/Images/i.png": b"i",
        "Build/Cesium/Assets/approximateTerrainHeights.json": b"{}",
        "Build/Cesium/Assets/IAU2006_XYS/x.json": b"no",
        "Build/CesiumUnminified/Cesium.js": b"no",
        "Build/Documentation/a.html": b"no",
        "Apps/Sandcastle/x.html": b"no",
        "package.json": b"{}",
    }
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


KEPT = {
    "Cesium.js",
    "Workers/a.js",
    "ThirdParty/b.js",
    "Widgets/widgets.css",
    "Assets/Textures/NaturalEarthII/0/0/0.jpg",
    "Assets/Textures/SkyBox/px.jpg",
    "Assets/Textures/moonSmall.jpg",
    "Assets/Images/i.png",
    "Assets/approximateTerrainHeights.json",
}


def test_dry_run_reports_and_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src, out = release(tmp_path / "r.zip"), tmp_path / "out"
    assert load().main(["--release-zip", str(src), "--out", str(out), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schema"] == "netview.geotrace/cesium-bundle@1"
    assert report["executed"] is False
    assert report["kept_files"] == len(KEPT)
    assert report["patches"] == [
        {"name": "eval-global", "count": 1, "expected": 1},
        {"name": "webassembly-guard", "count": 5, "expected": 5},
    ]
    assert not out.exists()


def test_execute_writes_a_zip_with_only_the_kept_paths_patched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src, out = release(tmp_path / "r.zip"), tmp_path / "out"
    assert load().main(["--release-zip", str(src), "--out", str(out), "--execute", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["output_file"] == f"geotrace-cesium-{bundle.CESIUM_VERSION}.zip"
    written = out / report["output_file"]
    data = written.read_bytes()
    assert report["executed"] is True
    assert report["output_bytes"] == len(data) and report["sha256"] == hashlib.sha256(data).hexdigest()
    with zipfile.ZipFile(written) as z:
        assert set(z.namelist()) == KEPT
        assert report["total_bytes"] == sum(i.file_size for i in z.infolist())
        js = z.read("Cesium.js")
    assert EVAL_OLD not in js and js.count(EVAL_NEW) == 1
    assert WASM_OLD not in js and js.count(WASM_NEW) == 5
    assert [p.name for p in out.iterdir()] == [report["output_file"]]


def test_the_output_is_reproducible(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = release(tmp_path / "r.zip")
    shas = []
    for name in ("a", "b"):
        load().main(["--release-zip", str(src), "--out", str(tmp_path / name), "--json"])
        shas.append(json.loads(capsys.readouterr().out)["sha256"])
    assert shas[0] == shas[1]


@pytest.mark.parametrize("evals,wasms", [(0, 5), (2, 5), (1, 4), (1, 6)])
def test_a_wrong_patch_count_fails_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], evals: int, wasms: int
) -> None:
    src, out = release(tmp_path / "r.zip", cesium_js(evals, wasms)), tmp_path / "out"
    assert load().main(["--release-zip", str(src), "--out", str(out), "--execute"]) != 0
    assert "expected" in capsys.readouterr().err
    assert not out.exists()


def test_a_release_without_cesium_js_fails(tmp_path: Path) -> None:
    src = tmp_path / "r.zip"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("Build/Cesium/Workers/a.js", b"w")
    assert load().main(["--release-zip", str(src), "--out", str(tmp_path / "o"), "--execute"]) != 0


def test_a_missing_release_zip_fails(tmp_path: Path) -> None:
    assert load().main(["--release-zip", str(tmp_path / "no.zip"), "--out", str(tmp_path / "o")]) != 0


def test_one_line_summary_without_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = release(tmp_path / "r.zip")
    assert load().main(["--release-zip", str(src), "--out", str(tmp_path / "o")]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1 and "dry run" in lines[0] and "sha256" in lines[0]


def test_version_argument_names_the_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = release(tmp_path / "r.zip")
    assert (
        load().main(["--release-zip", str(src), "--out", str(tmp_path / "o"), "--version", "2.0.1", "--json"])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["output_file"] == "geotrace-cesium-2.0.1.zip"


def test_the_tools_default_version_is_the_plugins() -> None:
    assert load().DEFAULT_VERSION == bundle.CESIUM_VERSION


NAMES = [
    "Cesium.js", "Workers/a.js", "Assets/Images/i.png", "", ".", "..", "../x", "a/../b", "/abs",
    "C:/x", "C:x",
    "a\\b", "a\x00b", "a//b", "./a",
]  # fmt: skip


def test_the_tool_and_the_manager_agree_on_unsafe_names() -> None:
    assert [load().unsafe_name(n) for n in NAMES] == [bundle.unsafe_name(n) for n in NAMES]


def test_an_unsafe_kept_entry_fails_and_writes_nothing(tmp_path: Path) -> None:
    src, out = tmp_path / "r.zip", tmp_path / "out"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("Build/Cesium/Cesium.js", cesium_js())
        info = zipfile.ZipInfo("x")
        info.filename = "Build/Cesium/Workers/..\\evil.js"
        z.writestr(info, b"e")
    assert load().main(["--release-zip", str(src), "--out", str(out), "--execute"]) != 0
    assert not out.exists()


def test_help_has_the_header() -> None:
    done = subprocess.run(
        [sys.executable, "-I", str(TOOL), "--help"], capture_output=True, text=True, check=True
    )
    assert "--release-zip" in done.stdout and "netview.geotrace/cesium-bundle@1" in done.stdout
