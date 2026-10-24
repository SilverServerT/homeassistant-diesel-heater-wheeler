"""Select platform for Vevor Diesel Heater."""
from __future__ import annotations

PARALLEL_UPDATES = 1

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VevorHeaterConfigEntry
from .const import (
    BACKLIGHT_OPTIONS,
    DOMAIN,
    HIGH_ALTITUDE_MODE_OPTIONS,
    LANGUAGE_OPTIONS,
    PUMP_TYPE_OPTIONS,
    WARM_DRIVE_PUMP_SIZE_OPTIONS,
    RUNNING_MODE_CLEANING,
    RUNNING_MODE_LEVEL,
    RUNNING_MODE_TEMPERATURE,
    RUNNING_MODE_VENTILATION,
    RUNNING_MODE_NAMES,
    RUNNING_STEP_CLEANING,
    RUNNING_STEP_STANDBY,
    RUNNING_STEP_VENTILATION,
    TANK_VOLUME_OPTIONS,
    WARM_DRIVE_OIL_TYPE_OPTIONS,
    WARM_DRIVE_TANK_VOLUME_OPTIONS,
)
from .coordinator import VevorHeaterCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VevorHeaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vevor Heater select from config entry.

    Entities are created conditionally based on the detected BLE protocol.
    Mode 0 (unknown) creates all entities as safe fallback.
    """
    coordinator = entry.runtime_data
    mode = coordinator.protocol_mode

    if mode == 9:
        # ThermoConnect makes the four-mode control editable only for air.
        # Water mode is exposed as read-only telemetry instead.
        entities: list[SelectEntity] = (
            [CronusModeSelect(coordinator)]
            if coordinator.data.get("cronus_controller_type") == "air"
            else []
        )
    else:
        entities = [VevorHeaterModeSelect(coordinator)]

    # Config selects (AA66Encrypted + CBFF: language, pump_type, tank_volume)
    if mode in (0, 4, 6):
        entities.extend([
            VevorHeaterLanguageSelect(coordinator),
            VevorHeaterPumpTypeSelect(coordinator),
            VevorHeaterTankVolumeSelect(coordinator),
        ])

    # Backlight select (encrypted + CBFF protocols)
    if mode in (0, 2, 4, 6):
        entities.append(VevorBacklightSelect(coordinator))

    # High Altitude Mode (Hcalory MVP2 only - 3 modes: Disabled, Mode 1, Mode 2)
    # @Xev: Hcalory needs selector instead of binary switch (issue #34)
    if mode == 7:
        entities.append(VevorHighAltitudeModeSelect(coordinator))

    if mode == 0 or coordinator.is_warm_drive_controller is True:
        entities.append(VevorWarmDriveOilTypeSelect(coordinator))

    async_add_entities(entities)


class CronusModeSelect(SelectEntity):
    """ThermoConnect controller mode selector."""

    _attr_has_entity_name = True
    _attr_name = "Mode"
    _attr_icon = "mdi:hvac"
    _attr_options = ["Heating", "Ventilation", "Boost", "Eco"]

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the ThermoConnect mode selector."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.address}_cronus_mode"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Webasto Cronus",
            "manufacturer": "Webasto",
            "model": "Cronus Smart",
        }

    @property
    def available(self) -> bool:
        """Return whether ThermoConnect has identified this controller."""
        return (
            self.coordinator.data.get("connected", False)
            and self.coordinator.data.get("cronus_controller_type") == "air"
        )

    @property
    def current_option(self) -> str | None:
        """Return the mode name supplied by ThermoConnect."""
        mode = self.coordinator.data.get("cronus_mode")
        return mode.capitalize() if mode else None

    async def async_select_option(self, option: str) -> None:
        """Write the app's corresponding controller-mode record."""
        await self.coordinator.async_set_cronus_mode(option.lower())

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator state changes."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Refresh the entity after the record cache changes."""
        self.async_write_ha_state()

class VevorHeaterModeSelect(SelectEntity):
    """Select entity for Vevor Heater running mode.

    For ABBA/HeaterCC devices, includes a "Ventilation" option when the heater
    is in standby or already ventilating. This allows fan-only operation.
    """

    _attr_has_entity_name = True
    _attr_name = "Running Mode"
    _attr_icon = "mdi:cog"

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the select entity."""
        self.coordinator = coordinator
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }
        self._attr_unique_id = f"{coordinator.address}_running_mode"

    @property
    def options(self) -> list[str]:
        """Return available running mode options.

        For ABBA and Warm Drive, include Ventilation when the heater is off
        or already ventilating. Warm Drive also offers Cleaning while off.
        """
        base_options = [
            RUNNING_MODE_NAMES[RUNNING_MODE_LEVEL],
            RUNNING_MODE_NAMES[RUNNING_MODE_TEMPERATURE],
        ]

        running_step = self.coordinator.data.get("running_step")
        warm_drive = self.coordinator.is_warm_drive_controller is True
        if (self.coordinator.protocol_mode == 5 or warm_drive) and running_step in (
            RUNNING_STEP_STANDBY,
            RUNNING_STEP_VENTILATION,
        ):
            base_options.append(RUNNING_MODE_NAMES[RUNNING_MODE_VENTILATION])
        if warm_drive and running_step in (
            RUNNING_STEP_STANDBY,
            RUNNING_STEP_CLEANING,
        ):
            base_options.append(RUNNING_MODE_NAMES[RUNNING_MODE_CLEANING])

        return base_options

    @property
    def available(self) -> bool:
        """Return if entity is available.

        Locked while burn-off is active: running mode is snapshotted at start
        and restored afterwards.
        """
        if self.coordinator.burnoff_active:
            return False
        return self.coordinator.data.get("connected", False)

    @property
    def current_option(self) -> str | None:
        """Return the current running mode."""
        running_step = self.coordinator.data.get("running_step")
        if running_step == RUNNING_STEP_VENTILATION:
            return RUNNING_MODE_NAMES[RUNNING_MODE_VENTILATION]
        if running_step == RUNNING_STEP_CLEANING:
            return RUNNING_MODE_NAMES[RUNNING_MODE_CLEANING]

        mode = self.coordinator.data.get("running_mode")
        if mode is not None:
            return RUNNING_MODE_NAMES.get(mode)
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the running mode."""
        # Find the mode value for the selected option
        mode_value = None
        for mode, name in RUNNING_MODE_NAMES.items():
            if name == option:
                mode_value = mode
                break

        if mode_value is not None:
            _LOGGER.info("Changing running mode to: %s (value: %d)", option, mode_value)
            await self.coordinator.async_set_mode(mode_value)
        else:
            _LOGGER.error("Unknown running mode: %s", option)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorHeaterLanguageSelect(SelectEntity):
    """Select entity for Vevor Heater voice notification language."""

    _attr_has_entity_name = True
    _attr_name = "Language"
    _attr_icon = "mdi:translate"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(LANGUAGE_OPTIONS.values())

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the select entity."""
        self.coordinator = coordinator
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }
        self._attr_unique_id = f"{coordinator.address}_language"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.data.get("connected", False)

    @property
    def current_option(self) -> str | None:
        """Return the current language."""
        language_code = self.coordinator.data.get("language")
        if language_code is not None:
            return LANGUAGE_OPTIONS.get(language_code, f"Unknown ({language_code})")
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the language."""
        # Find the language code for the selected option
        language_code = None
        for code, name in LANGUAGE_OPTIONS.items():
            if name == option:
                language_code = code
                break

        if language_code is not None:
            _LOGGER.info("Changing language to: %s (code: %d)", option, language_code)
            await self.coordinator.async_set_language(language_code)
        else:
            _LOGGER.error("Unknown language: %s", option)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorHeaterPumpTypeSelect(SelectEntity):
    """Select entity for Vevor Heater oil pump type."""

    _attr_has_entity_name = True
    _attr_name = "Pump Type"
    _attr_icon = "mdi:pump"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(PUMP_TYPE_OPTIONS.values())

    def _pump_options(self) -> dict[int, str]:
        """Return the pump table for the active controller."""
        if getattr(self.coordinator, "is_warm_drive_controller", False) is True:
            return WARM_DRIVE_PUMP_SIZE_OPTIONS
        return PUMP_TYPE_OPTIONS

    @property
    def name(self) -> str:
        """Return Pump Size on Warm Drive and Pump Type on legacy controllers."""
        if getattr(self.coordinator, "is_warm_drive_controller", False) is True:
            return "Pump Size"
        return "Pump Type"

    @property
    def options(self) -> list[str]:
        """Return pump sizes the active controller accepts."""
        return list(self._pump_options().values())

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the select entity."""
        self.coordinator = coordinator
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }
        self._attr_unique_id = f"{coordinator.address}_pump_type"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Not available if RF433 mode is active (pump_type will be None)
        return (
            self.coordinator.data.get("connected", False)
            and self.coordinator.data.get("pump_type") is not None
        )

    @property
    def current_option(self) -> str | None:
        """Return the current pump type."""
        pump_type = self.coordinator.data.get("pump_type")
        if pump_type is not None:
            return self._pump_options().get(pump_type, f"Type {pump_type}")
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the pump type."""
        # Find the pump type code for the selected option
        pump_code = None
        for code, name in self._pump_options().items():
            if name == option:
                pump_code = code
                break

        if pump_code is not None:
            _LOGGER.info("Changing pump type to: %s (code: %d)", option, pump_code)
            await self.coordinator.async_set_pump_type(pump_code)
        else:
            _LOGGER.error("Unknown pump type: %s", option)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorHeaterTankVolumeSelect(SelectEntity):
    """Select entity for Vevor Heater tank volume."""

    _attr_has_entity_name = True
    _attr_name = "Tank Volume"
    _attr_icon = "mdi:gas-station"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(TANK_VOLUME_OPTIONS.values())

    def _volume_options(self) -> dict[int, str]:
        """Return the tank table for the active controller."""
        if getattr(self.coordinator, "is_warm_drive_controller", False) is True:
            return WARM_DRIVE_TANK_VOLUME_OPTIONS
        return TANK_VOLUME_OPTIONS

    @property
    def options(self) -> list[str]:
        """Return tank sizes the active controller accepts."""
        return list(self._volume_options().values())

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the select entity."""
        self.coordinator = coordinator
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }
        self._attr_unique_id = f"{coordinator.address}_tank_volume_select"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.data.get("connected", False)

    @property
    def current_option(self) -> str | None:
        """Return the current tank volume."""
        tank_volume = self.coordinator.data.get("tank_volume")
        options = self._volume_options()
        if tank_volume is not None:
            # Return exact match or closest option
            if tank_volume in options:
                return options[tank_volume]
            # If not an exact match, show the raw value
            return f"{tank_volume} L"
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the tank volume."""
        # Find the volume value for the selected option
        volume = None
        for vol, name in self._volume_options().items():
            if name == option:
                volume = vol
                break

        if volume is not None:
            _LOGGER.info("Changing tank volume to: %s (value: %d)", option, volume)
            await self.coordinator.async_set_tank_volume(volume)
        else:
            _LOGGER.error("Unknown tank volume: %s", option)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorBacklightSelect(SelectEntity):
    """Select entity for display backlight brightness (cmd 21).

    Discrete brightness values matching the Vevor app:
    Off, 1-10, 20, 30, ..., 100.
    Replaces the old 0-100 number slider which was hard to use.
    """

    _attr_has_entity_name = True
    _attr_name = "Backlight"
    _attr_icon = "mdi:brightness-6"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(BACKLIGHT_OPTIONS.values())

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the select entity."""
        self.coordinator = coordinator
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }
        self._attr_unique_id = f"{coordinator.address}_backlight_select"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.data.get("backlight") is not None

    @property
    def current_option(self) -> str | None:
        """Return the current backlight level."""
        backlight = self.coordinator.data.get("backlight")
        if backlight is not None:
            if backlight in BACKLIGHT_OPTIONS:
                return BACKLIGHT_OPTIONS[backlight]
            return str(backlight)
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the backlight brightness."""
        for value, name in BACKLIGHT_OPTIONS.items():
            if name == option:
                _LOGGER.info("Setting backlight to: %s (value: %d)", option, value)
                await self.coordinator.async_set_backlight(value)
                return
        _LOGGER.error("Unknown backlight option: %s", option)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorHighAltitudeModeSelect(SelectEntity):
    """High Altitude Mode select entity (Hcalory MVP2 only).

    Hcalory has 3 altitude modes instead of binary on/off:
    - Disabled (0): Normal operation
    - Mode 1 (1): High altitude compensation level 1
    - Mode 2 (2): High altitude compensation level 2

    Per @Xev analysis (issue #34): Cannot switch directly from Disabled to Mode 2
    with a binary switch, so selector is needed.
    """

    _attr_has_entity_name = True
    _attr_name = "High Altitude Mode"
    _attr_icon = "mdi:mountain"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the select entity."""
        self.coordinator = coordinator
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
        }
        self._attr_unique_id = f"{coordinator.address}_high_altitude_mode"
        self._attr_options = list(HIGH_ALTITUDE_MODE_OPTIONS.values())

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.data.get("high_altitude") is not None

    @property
    def current_option(self) -> str | None:
        """Return the current high altitude mode."""
        altitude = self.coordinator.data.get("high_altitude")
        if altitude is not None:
            if altitude in HIGH_ALTITUDE_MODE_OPTIONS:
                return HIGH_ALTITUDE_MODE_OPTIONS[altitude]
            return str(altitude)
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the high altitude mode."""
        for value, name in HIGH_ALTITUDE_MODE_OPTIONS.items():
            if name == option:
                _LOGGER.info("Setting high altitude mode to: %s (value: %d)", option, value)
                await self.coordinator.async_set_altitude_mode(value)
                return
        _LOGGER.error("Unknown high altitude mode option: %s", option)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorWarmDriveOilTypeSelect(SelectEntity):
    """Warm Drive pamphlet oil type (0x26 byte 3)."""

    _attr_has_entity_name = True
    _attr_name = "Oil Type"
    _attr_icon = "mdi:barrel"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(WARM_DRIVE_OIL_TYPE_OPTIONS.values())

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the select entity."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.address}_oil_type"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Diesel Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }

    @property
    def available(self) -> bool:
        """Return true when Warm Drive has reported oil type."""
        return (
            self.coordinator.data.get("connected", False)
            and self.coordinator.is_warm_drive_controller is True
            and self.coordinator.data.get("oil_type") is not None
        )

    @property
    def current_option(self) -> str | None:
        """Return the current oil type."""
        oil_type = self.coordinator.data.get("oil_type")
        if oil_type is None:
            return None
        return WARM_DRIVE_OIL_TYPE_OPTIONS.get(oil_type, f"Type {oil_type}")

    async def async_select_option(self, option: str) -> None:
        """Change the oil type."""
        for code, name in WARM_DRIVE_OIL_TYPE_OPTIONS.items():
            if name == option:
                await self.coordinator.async_set_warm_drive_oil_type(code)
                return
        _LOGGER.error("Unknown oil type: %s", option)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
