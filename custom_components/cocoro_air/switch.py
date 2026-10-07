"""Device and notification toggles."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from .entity import CocoroAirEntity, coordinators


async def async_setup_entry(hass, entry, async_add_entities):
    entities = []
    for c in coordinators(hass, entry):
        if c.spec.get('hasHumidFunc') and not c.spec.get('cannotControlHumid'):
            entities.append(CocoroAirSwitch(c, 'humidification'))
        if c.spec.get('hasCloudService'):
            entities.append(CocoroAirSwitch(c, 'cloud'))
        for key in ('air_cleaner', 'temperature'):
            entities.append(CocoroAirSwitch(c, 'notify_' + key))
        if c.spec.get('hasHumanSensor'):
            entities.append(CocoroAirSwitch(c, 'notify_human'))
    async_add_entities(entities)


class CocoroAirSwitch(CocoroAirEntity, SwitchEntity):
    def __init__(self, coordinator, key):
        super().__init__(coordinator, key, {'humidification':'Humidification',
                                          'cloud':'Cloud home fit'}.get(key, key.replace('_',' ').title()))
        if key != 'humidification':
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self):
        if self._key.startswith('notify_'):
            return (self.coordinator.data.get('notifications') or {}).get(self._key[7:])
        return self.coordinator.data.get({'cloud':'cloud_enabled',
                                         'humidification':'humidification_enabled'}[self._key])

    async def _set(self, enabled):
        c = self.coordinator
        if self._key.startswith('notify_'):
            await c.async_set_notifications({self._key[7:]:enabled})
        else:
            await c.async_control(self._key, enabled)

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)
