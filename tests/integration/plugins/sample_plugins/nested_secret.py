from pydantic import BaseModel, SecretStr

from netview.sdk import Plugin, PluginContext, PluginManifest, PluginType


class Credentials(BaseModel):
    password: SecretStr


class NestedSecretSettings(BaseModel):
    login: Credentials | None = None


class NestedSecretPlugin(Plugin):
    """A secret inside a sub-model: the host cannot mask it, so it must refuse to load."""

    manifest = PluginManifest(
        name="Nested secret",
        version="1.0.0",
        description="A sample plugin whose secret is nested in a sub-model",
        guid="8210dc52-b2c3-4895-88d1-a1a3791cf04a",
        display_name="Nested secret",
        plugin_type=PluginType.OTHER,
        sdk_version=">=2.0,<3",
        capabilities=frozenset(),
        permissions=frozenset(),
    )
    settings_model = NestedSecretSettings

    def setup(self, ctx: PluginContext) -> None:
        self.settings = ctx.settings
