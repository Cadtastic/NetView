"""A contract check plugin authors call from their own test suite."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

from netview.application.plugins.validation import (
    validate_manifest,
    validate_providers,
    validate_storage,
)
from netview.domain.events import DomainEvent
from netview.sdk import SDK_VERSION, Plugin
from netview.sdk.testing.fakes import (
    FakeClock,
    FakeNetworkTools,
    FakeServiceProbes,
    FakeSnmpClient,
    FakeSystemInfo,
    FakeVendors,
    InMemoryMetrics,
)


class _FakeUnitOfWork:
    def __init__(self) -> None:
        self.session: Any = MagicMock()

    def commit(self) -> None:
        return None

    def __enter__(self) -> _FakeUnitOfWork:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


class _FakeContext:
    def __init__(
        self,
        display_name: str,
        settings: Any,
        guid: str = "00000000-0000-4000-8000-000000000000",
        source_id: int = 1,
    ) -> None:
        self.guid = guid
        self.source_id = source_id
        self.display_name = display_name
        self.settings = settings
        self.log = logging.getLogger(f"netview.plugin.p{source_id}")
        self.clock = FakeClock()
        self.net = FakeNetworkTools()
        self.probes = FakeServiceProbes()
        self.system = FakeSystemInfo()
        self.vendors = FakeVendors()
        self.metrics = InMemoryMetrics()
        self.snmp = FakeSnmpClient([])
        self.core: Any = MagicMock()

    def unit_of_work(self) -> _FakeUnitOfWork:
        return _FakeUnitOfWork()

    def subscribe(self, handler: Callable[[DomainEvent], None]) -> Callable[[], None]:
        return lambda: None


def check_plugin(cls: type[Plugin]) -> None:
    """Raise ``AssertionError`` when ``cls`` would not load cleanly in netview."""
    errors = validate_manifest(cls.manifest, SDK_VERSION, set())
    assert not errors, f"invalid manifest: {'; '.join(errors)}"

    settings: Any = None
    if cls.settings_model is not None:
        try:
            settings = cls.settings_model.model_validate({})
        except Exception as exc:
            raise AssertionError(f"default settings do not validate: {exc}") from exc

    plugin = cls()
    plugin.settings = settings
    errors = validate_providers(plugin)
    storage = plugin.storage()
    if storage is not None:
        errors += validate_storage(cls.manifest.id, storage.metadata)
        assert storage.versions_dir.is_dir(), f"storage versions_dir {storage.versions_dir} is missing"
    assert not errors, f"provider/storage problems: {'; '.join(errors)}"

    try:
        plugin.setup(_FakeContext(cls.manifest.display_name, settings, cls.manifest.guid))  # type: ignore[arg-type]
    except Exception as exc:
        raise AssertionError(f"setup() raised {type(exc).__name__}: {exc}") from exc

    errors = validate_providers(plugin)
    assert not errors, f"provider problems after setup: {'; '.join(errors)}"

    ui = plugin.ui()
    if ui is not None:
        assert ui.static_dir.is_dir(), f"ui static_dir {ui.static_dir} is missing"
        assert (ui.static_dir / ui.module).is_file(), f"ui module {ui.module} is missing in {ui.static_dir}"
