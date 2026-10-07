"""Temperature notification limits in Sharp cloud."""
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature, EntityCategory
from .entity import CocoroAirEntity, coordinators


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CocoroAirNotificationNumber(c,key) for c in coordinators(hass,entry)
                        for key in ('temperature_lower','temperature_upper')])


class CocoroAirNotificationNumber(CocoroAirEntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 40
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self,coordinator,key):
        super().__init__(coordinator,'notify_'+key,key.replace('_',' ').title()+' notification')
        self._field = key

    @property
    def native_value(self):
        return ((self.coordinator.data.get('notifications') or {}).get('temperature_detail') or {}).get(self._field)

    async def async_set_native_value(self,value):
        if not float(value).is_integer():
            raise ValueError('Temperature must be a whole number')
        c = self.coordinator
        await c.async_set_notifications({self._field:int(value)})
