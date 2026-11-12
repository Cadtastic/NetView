import json
import subprocess
import sys
from pathlib import Path

from netview.application.plugins.plugin_json import parse_index

ROOT = Path(__file__).resolve().parents[2]


def test_committed_index_is_fresh() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/build_plugin_index.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_ignores_crlf_line_endings(tmp_path: Path) -> None:
    """A Windows checkout (core.autocrlf=true) turns the committed LF files into CRLF; that is not stale."""
    out, bundle = tmp_path / "index.json", tmp_path / "catalog.json"
    paths = ["--out", str(out), "--bundle", str(bundle)]
    script = [sys.executable, "scripts/build_plugin_index.py"]
    subprocess.run([*script, "--execute", *paths], cwd=ROOT, check=True, capture_output=True)
    for path in (out, bundle):
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    result = subprocess.run(
        [*script, "--check", *paths], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_bundled_index_parses() -> None:
    path = ROOT / "src/netview/infrastructure/plugins/catalog.json"
    index = parse_index(json.loads(path.read_text(encoding="utf-8")))
    assert {"gs105e", "gsm7248", "roku", "starlink"} <= {e.path.rsplit("/", 1)[-1] for e in index.plugins}
