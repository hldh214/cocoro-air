"""Device and maintenance status."""
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.const import EntityCategory
from .entity import CocoroAirEntity, coordinators


async def async_setup_entry(hass, entry, async_add_entities):
    entities = []
    for c in coordinators(hass, entry):
        keys = ['plasma_enabled','care_error','unit_date_error','unit_out_error']
        if c.spec.get('hasHumidFunc'):
            keys.extend(['humidifying','water_empty'])
        if c.spec.get('hasChildLock') or c.spec.get('hasPetMode'):
            keys.append('child_lock')
        if c.spec.get('hasLightSensor'):
            keys.append('light_sensor_bright')
        entities.extend(CocoroAirBinarySensor(c,key) for key in keys)
        seen = set()
        def add_supplies(coordinator=c, registered=seen):
            new=[]
            for name in (coordinator.data or {}).get('supplies',{}):
                if name not in registered:
                    registered.add(name)
                    new.append(CocoroAirBinarySensor(coordinator,'care_'+name))
            if new:
                async_add_entities(new)
        add_supplies()
        entry.async_on_unload(c.async_add_listener(add_supplies))
    async_add_entities(entities)


class CocoroAirBinarySensor(CocoroAirEntity, BinarySensorEntity):
    def __init__(self, coordinator, key):
        super().__init__(coordinator,key,key.replace('_',' ').title())
        if key.startswith('care_') or key in ('water_empty','unit_date_error','unit_out_error'):
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self):
        if self._key.startswith('care_') and self._key != 'care_error':
            return self.coordinator.data.get('supplies',{}).get(self._key[5:],{}).get('needs_cleaning')
        return self.coordinator.data.get(self._key)
