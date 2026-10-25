"""ESPHome-held BLE transport: Home Assistant must not open GATT."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from . import conftest  # noqa: F401

from custom_components.diesel_heater.const import (
    CONF_ESPHOME_DEVICE,
    CONF_ESPHOME_HOLD_CONNECTION,
    CONF_NEO_CONTROLLER_TYPE,
    DEFAULT_ESPHOME_DEVICE,
    EVENT_ESPHOME_NOTIFY,
    esphome_holds_gatt,
)
from custom_components.diesel_heater.coordinator import VevorHeaterCoordinator

from .test_dz06_neo import FFF2, coordinator_for_layout, neo_config_response


def _hold_coordinator(**overrides: object) -> VevorHeaterCoordinator:
    coordinator = coordinator_for_layout(True)
    coordinator.config_entry = SimpleNamespace(
        data={
            CONF_NEO_CONTROLLER_TYPE: "air",
            CONF_ESPHOME_DEVICE: DEFAULT_ESPHOME_DEVICE,
            **overrides,
        }
    )
    coordinator.address = "C8:17:F5:28:E7:9D"
    coordinator.hass = MagicMock()
    coordinator.hass.services.async_call = AsyncMock()
    coordinator.hass.bus.async_listen = MagicMock(return_value=MagicMock())
    coordinator._esphome_last_notify = 0.0
    coordinator._esphome_unsub = None
    coordinator._esphome_unsub_state = None
    coordinator._esphome_write_missing_logged = False
    coordinator._client = None
    coordinator.async_set_updated_data = MagicMock()
    coordinator._logger = MagicMock()
    return coordinator


def test_hold_mode_is_dz06_without_gatt_discovery() -> None:
    coordinator = _hold_coordinator()
    coordinator._characteristic = None
    coordinator._abba_write_char = None
    coordinator._is_abba_device = False

    assert coordinator.esphome_holds_connection is True
    assert coordinator.is_dz06_neo is True
    assert coordinator.is_warm_drive_controller is True
    assert coordinator._esphome_write_service() == "blproxyesp_mudiro_write"


def test_mudiro_5kw_uses_esphome_gatt_without_hold_flag() -> None:
    assert esphome_holds_gatt({CONF_NEO_CONTROLLER_TYPE: "air"}) is True
    assert esphome_holds_gatt({CONF_NEO_CONTROLLER_TYPE: "water"}) is True
    assert esphome_holds_gatt({}) is False
    assert (
        esphome_holds_gatt(
            {
                CONF_NEO_CONTROLLER_TYPE: "air",
                CONF_ESPHOME_HOLD_CONNECTION: False,
            }
        )
        is False
    )


def test_hold_write_service_uses_blproxy_by_default() -> None:
    assert DEFAULT_ESPHOME_DEVICE == "blproxyesp"
    coordinator = _hold_coordinator()
    del coordinator.config_entry.data[CONF_ESPHOME_DEVICE]
    assert coordinator._esphome_write_service() == "blproxyesp_mudiro_write"


def test_hold_write_service_discovers_registered_mudiro_write() -> None:
    coordinator = _hold_coordinator()
    coordinator.hass.services.async_services_for_domain = MagicMock(
        return_value={"mudiro_ble_test_mudiro_write": {}}
    )
    assert coordinator._esphome_write_service() == "mudiro_ble_test_mudiro_write"


@pytest.mark.asyncio
async def test_hold_mode_does_not_open_bleak() -> None:
    coordinator = _hold_coordinator()
    with patch(
        "custom_components.diesel_heater.coordinator.establish_connection",
        AsyncMock(side_effect=AssertionError("must not connect")),
    ):
        await VevorHeaterCoordinator._ensure_connected(coordinator)


@pytest.mark.asyncio
async def test_hold_mode_writes_go_to_esphome_service() -> None:
    coordinator = _hold_coordinator()
    await coordinator._write_gatt(bytearray((0xA5, 0x09, 0x01, 0x00)))

    coordinator.hass.services.async_call.assert_awaited_once_with(
        "esphome",
        "blproxyesp_mudiro_write",
        {"hex": "a5090100"},
        blocking=True,
    )
    assert coordinator._client is None


def test_hold_mode_notify_event_parses_5c16() -> None:
    coordinator = _hold_coordinator()
    frame = neo_config_response(device_type=1, oil_type=1)
    event = SimpleNamespace(
        data={"address": "c8:17:f5:28:e7:9d", "payload": frame.hex()}
    )

    coordinator._handle_esphome_notify(event)

    assert coordinator.data["oil_type"] == 1
    assert coordinator.data["connected"] is True
    assert coordinator._esphome_last_notify > 0
    coordinator.async_set_updated_data.assert_called()


def test_hold_mode_ignores_other_mac() -> None:
    coordinator = _hold_coordinator()
    event = SimpleNamespace(
        data={"address": "AA:BB:CC:DD:EE:FF", "payload": "5c16"}
    )

    coordinator._handle_esphome_notify(event)

    coordinator.async_set_updated_data.assert_not_called()
    assert coordinator._esphome_last_notify == 0.0


def test_hold_mode_reads_mudiro_last_hex_sensor() -> None:
    coordinator = _hold_coordinator()
    frame = neo_config_response(device_type=1, oil_type=1)
    coordinator.hass.states.async_all = MagicMock(
        return_value=[
            SimpleNamespace(
                entity_id="sensor.blproxyesp_mudiro_last_hex",
                state=frame.hex(),
            )
        ]
    )

    coordinator._ingest_esphome_hex_states()

    assert coordinator.data["oil_type"] == 1
    assert coordinator.data["connected"] is True
    assert coordinator._esphome_last_notify > 0


@pytest.mark.asyncio
async def test_hold_mode_setup_listens_for_notify_events() -> None:
    coordinator = _hold_coordinator()
    coordinator._send_dz06_neo_configuration = AsyncMock(return_value=True)
    coordinator._send_dz06_neo_run_settings = AsyncMock(return_value=True)
    coordinator._send_dz06_neo_board_info = AsyncMock()
    await coordinator.async_setup_esphome_bridge()

    listened = [call.args[0] for call in coordinator.hass.bus.async_listen.call_args_list]
    assert EVENT_ESPHOME_NOTIFY in listened
    notify = [
        call.args[1]
        for call in coordinator.hass.bus.async_listen.call_args_list
        if call.args[0] == EVENT_ESPHOME_NOTIFY
    ]
    assert notify == [coordinator._handle_esphome_notify]


@pytest.mark.asyncio
async def test_hold_setup_does_not_block_on_session_reread() -> None:
    coordinator = _hold_coordinator()
    coordinator._neo_config_received = False
    coordinator._send_dz06_neo_configuration = AsyncMock(return_value=True)
    coordinator._send_dz06_neo_run_settings = AsyncMock(return_value=True)
    coordinator._send_dz06_neo_board_info = AsyncMock()

    await coordinator.async_setup_esphome_bridge()

    coordinator._send_dz06_neo_configuration.assert_not_called()
    coordinator._send_dz06_neo_board_info.assert_not_called()
