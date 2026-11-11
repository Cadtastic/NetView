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


def test_bundled_index_parses() -> None:
    path = ROOT / "src/netview/infrastructure/plugins/catalog.json"
    index = parse_index(json.loads(path.read_text(encoding="utf-8")))
    assert {"gsm7248", "starlink"} <= {e.plugin.id for e in index.plugins}
