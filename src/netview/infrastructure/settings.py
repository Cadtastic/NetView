"""Application settings: init args > environment > TOML file."""

import os
from pathlib import Path
from typing import Any, Literal

import platformdirs
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NETVIEW_", env_nested_delimiter="__", extra="ignore")

    config_file: Path | None = None
    data_dir: Path = Path(platformdirs.user_data_dir("netview", appauthor=False))
    bind: str = "127.0.0.1"
    port: int = 8765
    subnet: str | None = None
    scan_interval_s: float = 30.0
    fast_interval_s: float = 5.0
    oui_file: Path | None = None
    plugin_dirs: list[Path] = []
    plugins: dict[str, dict[str, Any]] = {}
    """First-run settings per plugin, keyed by the plugin's guid."""
    database_url: str | None = None
    mode: Literal["enterprise", "home"] = "enterprise"
    plugin_catalog_url: str = "https://raw.githubusercontent.com/Cadtastic/NetView/main/plugins/index.json"

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'netview.db'}"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        init_kwargs: dict[str, Any] = getattr(init_settings, "init_kwargs", {})
        config_file = init_kwargs.get("config_file") or os.environ.get("NETVIEW_CONFIG_FILE")
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
        if config_file:
            sources.append(TomlConfigSettingsSource(settings_cls, toml_file=Path(config_file)))
        return tuple(sources)


def load_settings(config_file: Path | None = None, **overrides: Any) -> AppSettings:
    if config_file is None:
        candidate = AppSettings(**overrides).data_dir / "netview.toml"
        if candidate.is_file():
            config_file = candidate
    if config_file is not None:
        return AppSettings(config_file=config_file, **overrides)
    return AppSettings(**overrides)
