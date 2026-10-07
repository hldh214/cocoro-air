"""Device identity shared by all platforms."""
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from .const import DOMAIN


class CocoroAirEntity(CoordinatorEntity):
    def __init__(self, coordinator, key, name):
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f'{DOMAIN}_{coordinator.device_id}_{key}'
        self._attr_name = name

    @property
    def device_info(self):
        return DeviceInfo(identifiers={(DOMAIN, self.coordinator.device_id)},
                          name=self.coordinator.device_name, manufacturer='Sharp',
                          model=self.coordinator.model_name,
                          configuration_url='https://cocoroplusapp.jp.sharp/air')


def coordinators(hass, entry):
    return hass.data[DOMAIN][entry.entry_id]['coordinators'].values()
