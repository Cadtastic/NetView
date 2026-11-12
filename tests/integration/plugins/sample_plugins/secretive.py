from pydantic import BaseModel, SecretStr

from netview.sdk import Plugin, PluginContext, PluginManifest, PluginType


class SecretiveSettings(BaseModel):
    key: SecretStr | None = None
    level: int = 1


class SecretivePlugin(Plugin):
    manifest = PluginManifest(
        id="secretive",
        name="Secretive",
        version="1.0.0",
        description="A sample plugin with a secret setting",
        guid="716a639a-9159-4b5d-822f-1f05d60c97e3",
        display_name="Secretive",
        plugin_type=PluginType.OTHER,
        sdk_version=">=1.0,<2",
        capabilities=frozenset(),
        permissions=frozenset(),
    )
    settings_model = SecretiveSettings

    def __init__(self) -> None:
        self.ctx: PluginContext | None = None

    def setup(self, ctx: PluginContext) -> None:
        self.ctx = ctx
        self.settings = ctx.settings
