from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from netview.sdk import (
    Plugin,
    PluginContext,
    PluginManifest,
    PluginType,
    required_when,
    settings_requirements,
)


class NeedySettings(BaseModel):
    """Needs a host, and a token while auth is on: the defaults leave it unconfigured."""

    model_config = ConfigDict(
        json_schema_extra=settings_requirements(
            required=["host"], rules=[required_when({"auth": "token"}, ["token"])]
        )
    )

    host: str = ""
    auth: Literal["none", "token"] = "token"
    token: SecretStr | None = None
    level: int = Field(1, ge=0, le=9)


class NeedyPlugin(Plugin):
    manifest = PluginManifest(
        name="Needy",
        version="1.0.0",
        description="A sample plugin that must be configured before it works",
        guid="e568cec5-9188-4c09-a8bc-5850795b1d2c",
        display_name="Needy",
        plugin_type=PluginType.OTHER,
        sdk_version=">=2.0,<3",
        capabilities=frozenset(),
        permissions=frozenset(),
    )
    settings_model = NeedySettings

    def setup(self, ctx: PluginContext) -> None:
        self.settings = ctx.settings
