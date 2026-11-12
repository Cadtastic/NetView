from pathlib import Path

import sqlalchemy as sa

from netview.sdk import Capability, Plugin, PluginContext, PluginManifest, PluginType, StorageSpec

metadata = sa.MetaData()
sa.Table("items", metadata, sa.Column("id", sa.Integer, primary_key=True))


class BadPrefixPlugin(Plugin):
    manifest = PluginManifest(
        id="bad_prefix",
        name="Bad prefix",
        version="1.0.0",
        description="Its table lacks the plugin prefix",
        guid="c6ac3d0a-6c70-449f-9719-9280e1519da0",
        display_name="Bad prefix",
        plugin_type=PluginType.OTHER,
        sdk_version=">=1.0,<2",
        capabilities=frozenset({Capability.STORAGE}),
        permissions=frozenset(),
    )

    def setup(self, ctx: PluginContext) -> None:
        return None

    def storage(self) -> StorageSpec:
        return StorageSpec(metadata=metadata, versions_dir=Path(__file__).parent / "good_versions")
