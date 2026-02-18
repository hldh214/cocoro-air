"""Sensor platform for Cocoro Air."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Cocoro Air sensor platform."""
    cocoro_air_api = hass.data[DOMAIN][entry.entry_id]["cocoro_air_api"]

    entities = [
        CocoroAirTemperatureSensor(cocoro_air_api),
        CocoroAirHumiditySensor(cocoro_air_api),
        CocoroAirWaterTankSensor(cocoro_air_api),
        CocoroAirPM25Sensor(cocoro_air_api),
        CocoroAirCleanedAirVolumeSensor(cocoro_air_api),
        CocoroAirOdorLevelSensor(cocoro_air_api),
        CocoroAirDustLevelSensor(cocoro_air_api),
        CocoroAirCleanlinessLevelSensor(cocoro_air_api),
    ]
    async_add_entities(entities)


class CocoroAirTemperatureSensor(SensorEntity):
    """Representation of a Cocoro Air Temperature Sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True
    _attr_name = "Temperature"
    _attr_icon = "mdi:thermometer"

    def __init__(self, api):
        """Initialize the sensor."""
        self._api = api
        self._attr_unique_id = f"{api.device_id}_temperature"
        self._attr_device_info = api.device_info
        self._attr_native_value = None

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            raw_data = await self._api.update()
            data = self._api.get_sensor_data(raw_data)
            self._attr_native_value = data['temperature']
        except Exception as e:
            _LOGGER.warning("Failed to update sensor data: %s", e)

class CocoroAirHumiditySensor(SensorEntity):
    """Representation of a Cocoro Air Humidity Sensor."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True
    _attr_name = "Humidity"
    _attr_icon = "mdi:water-percent"

    def __init__(self, api):
        """Initialize the sensor."""
        self._api = api
        self._attr_unique_id = f"{api.device_id}_humidity"
        self._attr_device_info = api.device_info
        self._attr_native_value = None

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            raw_data = await self._api.update()
            data = self._api.get_sensor_data(raw_data)
            self._attr_native_value = data['humidity']
        except Exception as e:
            _LOGGER.warning("Failed to update sensor data: %s", e)


class CocoroAirWaterTankSensor(BinarySensorEntity):
    """Representation of a Cocoro Air Water Tank Sensor."""

    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_has_entity_name = True
    _attr_name = "Water tank"
    _attr_icon = "mdi:water"

    def __init__(self, api):
        """Initialize the sensor."""
        self._api = api
        self._attr_unique_id = f"{api.device_id}_water_tank"
        self._attr_device_info = api.device_info
        self._attr_is_on = None

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            raw_data = await self._api.update()
            data = self._api.get_sensor_data(raw_data)
            self._attr_is_on = data['water_tank']
        except Exception as e:
            _LOGGER.warning("Failed to update sensor data: %s", e)


class CocoroAirPM25Sensor(SensorEntity):
    """Representation of a Cocoro Air PM2.5 Sensor."""

    _attr_device_class = SensorDeviceClass.PM25
    _attr_native_unit_of_measurement = CONCENTRATION_MICROGRAMS_PER_CUBIC_METER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True
    _attr_name = "PM2.5"
    _attr_icon = "mdi:air-filter"

    def __init__(self, api):
        """Initialize the sensor."""
        self._api = api
        self._attr_unique_id = f"{api.device_id}_pm25"
        self._attr_device_info = api.device_info
        self._attr_native_value = None

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            raw_data = await self._api.update()
            data = self._api.get_sensor_data(raw_data)
            self._attr_native_value = data['pm25']
        except Exception as e:
            _LOGGER.warning("Failed to update sensor data: %s", e)


class CocoroAirCleanedAirVolumeSensor(SensorEntity):
    """Representation of a Cocoro Air Cleaned Air Volume Sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True
    _attr_name = "Cleaned air volume"
    _attr_icon = "mdi:air-purifier"

    def __init__(self, api):
        """Initialize the sensor."""
        self._api = api
        self._attr_unique_id = f"{api.device_id}_cleaned_air_volume"
        self._attr_device_info = api.device_info
        self._attr_native_value = None

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            raw_data = await self._api.update()
            data = self._api.get_sensor_data(raw_data)
            self._attr_native_value = data['cleaned_air_volume']
        except Exception as e:
            _LOGGER.warning("Failed to update sensor data: %s", e)


class CocoroAirOdorLevelSensor(SensorEntity):
    """Representation of a Cocoro Air Odor Level Sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True
    _attr_name = "Odor level"
    _attr_icon = "mdi:scent"

    def __init__(self, api):
        """Initialize the sensor."""
        self._api = api
        self._attr_unique_id = f"{api.device_id}_odor_level"
        self._attr_device_info = api.device_info
        self._attr_native_value = None

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            raw_data = await self._api.update()
            data = self._api.get_sensor_data(raw_data)
            raw_value = data['odor_level']
            if raw_value is not None:
                self._attr_native_value = round(raw_value / 33)
            else:
                self._attr_native_value = None
        except Exception as e:
            _LOGGER.warning("Failed to update sensor data: %s", e)


class CocoroAirDustLevelSensor(SensorEntity):
    """Representation of a Cocoro Air Dust Level Sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True
    _attr_name = "Dust level"
    _attr_icon = "mdi:blur"

    def __init__(self, api):
        """Initialize the sensor."""
        self._api = api
        self._attr_unique_id = f"{api.device_id}_dust_level"
        self._attr_device_info = api.device_info
        self._attr_native_value = None

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            raw_data = await self._api.update()
            data = self._api.get_sensor_data(raw_data)
            raw_value = data['dust_level']
            if raw_value is not None:
                self._attr_native_value = round(raw_value / 25)
            else:
                self._attr_native_value = None
        except Exception as e:
            _LOGGER.warning("Failed to update sensor data: %s", e)


class CocoroAirCleanlinessLevelSensor(SensorEntity):
    """Representation of a Cocoro Air Cleanliness Level Sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True
    _attr_name = "Cleanliness level"
    _attr_icon = "mdi:air-purifier"

    def __init__(self, api):
        """Initialize the sensor."""
        self._api = api
        self._attr_unique_id = f"{api.device_id}_cleanliness_level"
        self._attr_device_info = api.device_info
        self._attr_native_value = None

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            raw_data = await self._api.update()
            data = self._api.get_sensor_data(raw_data)
            raw_value = data['cleanliness_level']
            if raw_value is not None:
                self._attr_native_value = round(raw_value / 25)
            else:
                self._attr_native_value = None
        except Exception as e:
            _LOGGER.warning("Failed to update sensor data: %s", e)
