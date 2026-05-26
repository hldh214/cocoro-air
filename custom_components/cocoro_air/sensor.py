"""Platform for sensor integration."""

import logging
from datetime import timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity

from . import DOMAIN, CocoroAir

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensor platform from a config entry."""
    _LOGGER.debug("Setting up sensor platform entry.")

    cocoro_air_api = hass.data[DOMAIN][entry.entry_id]

    devices = entry.data.get("devices", [])
    entities = []

    try:
        all_devices_info = await hass.async_add_executor_job(cocoro_air_api.query_devices)
        device_map = {d['device_id']: d for d in all_devices_info}
    except Exception as e:
        _LOGGER.error(f"Error querying devices during setup: {e}")
        device_map = {}

    for device_id in devices:
        device_info = device_map.get(device_id, {})
        device_name = device_info.get('device_name', f"Cocoro Air {device_id}")
        model_name = device_info.get('model_name', "Cocoro Air")

        coordinator = MyCoordinator(hass, cocoro_air_api, device_id, device_name, model_name)
        await coordinator.async_config_entry_first_refresh()

        entities.append(CocoroAirTemperatureSensor(coordinator))
        entities.append(CocoroAirHumiditySensor(coordinator))
        entities.append(CocoroAirPM25Sensor(coordinator))
        entities.append(CocoroAirDustSensor(coordinator))
        entities.append(CocoroAirOdorSensor(coordinator))

    async_add_entities(entities)


class MyCoordinator(DataUpdateCoordinator):
    """My custom coordinator."""

    def __init__(self, hass, my_api: CocoroAir, device_id: str, device_name: str, model_name: str):
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name=f"Cocoro Air update {device_id}",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=60),
        )
        self.my_api = my_api
        self.device_id = device_id
        self.device_name = device_name
        self.model_name = model_name

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        try:
            return await self.hass.async_add_executor_job(self.my_api.get_sensor_data, self.device_id)
        except Exception as e:
            _LOGGER.error(f"Error fetching data for {self.device_id}: {e}")
            raise


class CocoroAirSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Cocoro Air sensor."""

    _data_key: str = ""

    def __init__(self, coordinator: DataUpdateCoordinator, name: str,
                 device_class: SensorDeviceClass | None, state_class: str,
                 unit_of_measurement: str | None):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{coordinator.device_id}_{name.lower().replace(' ', '_')}"
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit_of_measurement

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.coordinator.data.get(self._data_key)
        return None

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device information about this entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.device_id)},
            name=self.coordinator.device_name,
            manufacturer="Sharp",
            model=self.coordinator.model_name,
        )


class CocoroAirTemperatureSensor(CocoroAirSensorBase):
    _data_key = "temperature"

    def __init__(self, coordinator: DataUpdateCoordinator):
        super().__init__(
            coordinator,
            "Temperature",
            SensorDeviceClass.TEMPERATURE,
            SensorStateClass.MEASUREMENT,
            UnitOfTemperature.CELSIUS,
        )
        self._attr_icon = "mdi:thermometer"


class CocoroAirHumiditySensor(CocoroAirSensorBase):
    _data_key = "humidity"

    def __init__(self, coordinator: DataUpdateCoordinator):
        super().__init__(
            coordinator,
            "Humidity",
            SensorDeviceClass.HUMIDITY,
            SensorStateClass.MEASUREMENT,
            "%",
        )
        self._attr_icon = "mdi:water-percent"


class CocoroAirPM25Sensor(CocoroAirSensorBase):
    _data_key = "pm25"

    def __init__(self, coordinator: DataUpdateCoordinator):
        super().__init__(
            coordinator,
            "PM2.5",
            SensorDeviceClass.PM25,
            SensorStateClass.MEASUREMENT,
            CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        )
        self._attr_icon = "mdi:blur"


class CocoroAirDustSensor(CocoroAirSensorBase):
    _data_key = "dust"

    def __init__(self, coordinator: DataUpdateCoordinator):
        super().__init__(
            coordinator,
            "Dust",
            None,
            SensorStateClass.MEASUREMENT,
            None,
        )
        self._attr_icon = "mdi:blur"


class CocoroAirOdorSensor(CocoroAirSensorBase):
    _data_key = "odor"

    def __init__(self, coordinator: DataUpdateCoordinator):
        super().__init__(
            coordinator,
            "Odor",
            None,
            SensorStateClass.MEASUREMENT,
            None,
        )
        self._attr_icon = "mdi:scent"
