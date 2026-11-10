from pathlib import Path

import pytest

from netview.infrastructure.clock import SystemClock
from netview.infrastructure.settings import AppSettings, load_settings


def test_settings_env_beats_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "c.toml"
    cfg.write_text('port = 9000\nbind = "0.0.0.0"\n', encoding="utf-8")
    monkeypatch.setenv("NETVIEW_PORT", "9100")
    s = load_settings(cfg, data_dir=tmp_path)
    assert s.port == 9100
    assert s.bind == "0.0.0.0"


def test_init_args_beat_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETVIEW_PORT", "9100")
    assert load_settings(None, data_dir=tmp_path, port=9200).port == 9200


def test_settings_default_db_url_in_data_dir(tmp_path: Path) -> None:
    s = AppSettings(data_dir=tmp_path)
    assert s.db_url == f"sqlite:///{tmp_path / 'netview.db'}"
    assert AppSettings(data_dir=tmp_path, database_url="sqlite://").db_url == "sqlite://"


def test_load_settings_picks_up_toml_in_data_dir(tmp_path: Path) -> None:
    (tmp_path / "netview.toml").write_text(
        "port = 9300\n[plugins.starlink]\nenabled = false\n", encoding="utf-8"
    )
    s = load_settings(data_dir=tmp_path)
    assert s.port == 9300
    assert s.plugins == {"starlink": {"enabled": False}}


def test_nested_env_for_plugin_seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETVIEW_PLUGINS__STARLINK__ENABLED", "false")
    s = AppSettings(data_dir=tmp_path)
    assert s.plugins["starlink"]["enabled"] in (False, "false")


def test_system_clock_is_epoch_ms() -> None:
    import time

    assert abs(SystemClock().now_ms() - time.time() * 1000) < 1000
