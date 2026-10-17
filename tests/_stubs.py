"""Minimal stand-ins for Home Assistant and bleak, so the unit tests need no
dependencies at all (they run with the standard library only).

The tests cover the logic of the integration (parsing, commands, cover state),
not Home Assistant itself. The stubs are installed once, on first import.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

INTEGRATION = Path(__file__).parent.parent / "custom_components" / "girea_system_3000"

# Timers requested through async_call_later: [delay, callback, cancelled]
timers: list[list] = []


def _module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module
    return module


class _Base:
    def __init__(self, *args, **kwargs) -> None:
        self.notified = 0

    def __class_getitem__(cls, item):
        return cls

    async def async_will_remove_from_hass(self) -> None:
        return None

    def _async_handle_bluetooth_event(self, *args) -> None:
        self.notified += 1

    def _async_handle_unavailable(self, *args) -> None:
        return None


class CoverEntity(_Base):
    @property
    def is_opening(self):
        return self._attr_is_opening

    @property
    def is_closing(self):
        return self._attr_is_closing


class CoordinatorEntity:
    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator

    def __class_getitem__(cls, item):
        return cls


class HomeAssistantError(Exception):
    def __init__(self, *args, translation_domain=None, translation_key=None,
                 translation_placeholders=None) -> None:
        super().__init__(*args)
        self.translation_domain = translation_domain
        self.translation_key = translation_key
        self.translation_placeholders = translation_placeholders


def _format_mac(mac: str) -> str:
    cleaned = mac.lower().replace(":", "").replace("-", "").replace(".", "")
    return ":".join(cleaned[i : i + 2] for i in range(0, 12, 2))


def _async_call_later(hass, delay, callback):
    timer = [delay, callback, False]
    timers.append(timer)

    def cancel() -> None:
        timer[2] = True

    return cancel


def _install() -> None:
    for name in (
        "homeassistant",
        "homeassistant.components",
        "homeassistant.config_entries",
        "homeassistant.helpers",
        "homeassistant.helpers.entity_platform",
        "homeassistant.components.bluetooth.passive_update_coordinator",
        "bleak_retry_connector",
    ):
        _module(name)
    bluetooth = _module(
        "homeassistant.components.bluetooth",
        BluetoothServiceInfoBleak=object,
        BluetoothChange=object,
        BluetoothScanningMode=types.SimpleNamespace(PASSIVE=1),
    )
    sys.modules["homeassistant.components"].bluetooth = bluetooth
    sys.modules[
        "homeassistant.components.bluetooth.passive_update_coordinator"
    ].PassiveBluetoothDataUpdateCoordinator = _Base
    _module(
        "homeassistant.components.cover",
        CoverEntity=CoverEntity,
        CoverEntityFeature=types.SimpleNamespace(OPEN=1, CLOSE=2, STOP=4, SET_POSITION=8),
    )
    sys.modules["homeassistant.config_entries"].ConfigEntry = object
    _module(
        "homeassistant.core",
        CALLBACK_TYPE=object,
        HomeAssistant=object,
        callback=lambda func: func,
    )
    _module(
        "homeassistant.helpers.device_registry",
        CONNECTION_BLUETOOTH="bluetooth",
        DeviceInfo=dict,
        format_mac=_format_mac,
    )
    sys.modules["homeassistant.helpers.entity_platform"].AddEntitiesCallback = object
    _module(
        "homeassistant.helpers.update_coordinator", CoordinatorEntity=CoordinatorEntity
    )
    _module("homeassistant.helpers.event", async_call_later=_async_call_later)
    _module("homeassistant.exceptions", HomeAssistantError=HomeAssistantError)
    _module("bleak", BleakClient=object, BleakError=Exception)
    sys.modules["bleak_retry_connector"].establish_connection = None


def load(name: str) -> types.ModuleType:
    """Import custom_components/girea_system_3000/<name>.py with the stubs."""
    if "homeassistant" not in sys.modules or not hasattr(
        sys.modules["homeassistant.core"], "CALLBACK_TYPE"
    ):
        _install()
    if "girea" not in sys.modules:
        package = types.ModuleType("girea")
        package.__path__ = [str(INTEGRATION)]
        sys.modules["girea"] = package
    full_name = f"girea.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, INTEGRATION / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module
