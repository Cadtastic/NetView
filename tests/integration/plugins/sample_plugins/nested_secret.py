from pydantic import BaseModel, SecretStr

from netview.sdk import Plugin, PluginContext, PluginManifest


class Credentials(BaseModel):
    password: SecretStr


class NestedSecretSettings(BaseModel):
    login: Credentials | None = None


class NestedSecretPlugin(Plugin):
    """A secret inside a sub-model: the host cannot mask it, so it must refuse to load."""

    manifest = PluginManifest(
        id="nestedsecret",
        name="Nested secret",
        version="1.0.0",
        description="A sample plugin whose secret is nested in a sub-model",
        sdk_version=">=1.0,<2",
        capabilities=frozenset(),
        permissions=frozenset(),
    )
    settings_model = NestedSecretSettings

    def setup(self, ctx: PluginContext) -> None:
        self.settings = ctx.settings
