"""Refresh button without destructive maintenance shortcuts."""
from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from .entity import CocoroAirEntity, coordinators


async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities([CocoroAirRefreshButton(c) for c in coordinators(hass,entry)])


class CocoroAirRefreshButton(CocoroAirEntity,ButtonEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    def __init__(self,coordinator):
        super().__init__(coordinator,'refresh','Refresh cloud data')
    async def async_press(self):
        self.coordinator._cloud_updated = 0
        await self.coordinator.async_request_refresh()
