"""Device measurements and cloud care information."""
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTemperature, EntityCategory
from .entity import CocoroAirEntity, coordinators

# key: device class, unit; vendor pollution levels deliberately have no AQI class.
DESCRIPTIONS = {
    'temperature': (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    'humidity': (SensorDeviceClass.HUMIDITY, '%'),
    'pm25': (SensorDeviceClass.PM25, 'µg/m³'),
    'dust_level': (None, None), 'odor_level': (None, None),
    'air_quality': (None, None), 'brightness': (None, None),
    'operating_status': (None, None),
    'cost_today': (SensorDeviceClass.MONETARY,'JPY'),
    'cost_month': (SensorDeviceClass.MONETARY,'JPY'),
    'electricity_rate': (None,'JPY/kWh'),
    'outdoor_temperature': (SensorDeviceClass.TEMPERATURE,UnitOfTemperature.CELSIUS),
    'outdoor_humidity': (SensorDeviceClass.HUMIDITY,'%'),
    'pollen': (None,None), 'pm25_forecast': (None,None),
    'yellow_sand': (None,None), 'laundry': (None,None),
    'weather_code': (None,None),
}


async def async_setup_entry(hass, entry, async_add_entities):
    entities = []
    for c in coordinators(hass, entry):
        keys = ['temperature', 'humidity', 'odor_level', 'air_quality', 'operating_status',
                'cost_today','cost_month','electricity_rate']
        if c.device.get('zip_code'):
            keys.extend(['outdoor_temperature','outdoor_humidity','pollen','pm25_forecast','yellow_sand','laundry','weather_code'])
        if c.spec.get('hasPM25Sensor'):
            keys.append('pm25')
        if c.spec.get('hasDustSensor'):
            keys.append('dust_level')
        if c.spec.get('hasLightSensor'):
            keys.append('brightness')
        entities.extend(CocoroAirSensor(c, key) for key in keys)
        seen = set()
        def add_supplies(coordinator=c, registered=seen):
            new = []
            for name, supply in (coordinator.data or {}).get('supplies', {}).items():
                fields = ['last_cleaned']
                if supply.get('remaining') is not None:
                    fields.append('remaining')
                for field in fields:
                    key = (name, field)
                    if key not in registered:
                        registered.add(key)
                        new.append(CocoroAirSupplySensor(coordinator,name,field))
            if new:
                async_add_entities(new)
        add_supplies()
        entry.async_on_unload(c.async_add_listener(add_supplies))
    async_add_entities(entities)


class CocoroAirSensor(CocoroAirEntity, SensorEntity):
    def __init__(self, coordinator, key):
        # Names/unique IDs for Temperature and Humidity exactly match version 1.1.
        super().__init__(coordinator, key, key.replace('_',' ').title())
        self._attr_device_class, self._attr_native_unit_of_measurement = DESCRIPTIONS[key]
        if self._attr_native_unit_of_measurement and key not in ('cost_today','cost_month'):
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        key = 'current_mode' if self._key == 'operating_status' else self._key
        return self.coordinator.data.get(key)

    @property
    def extra_state_attributes(self):
        if self._key in ('temperature','humidity','pm25'):
            return {'measurement_status': self.coordinator.data.get(self._key+'_status')}
        return None


class CocoroAirSupplySensor(CocoroAirEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, name, field):
        super().__init__(coordinator, name+'_'+field, (name+' '+field).replace('_',' ').title())
        self._supply_name = name
        self._field = field
        if field == 'remaining':
            self._attr_native_unit_of_measurement = '%'
        else:
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        value = self.coordinator.data.get('supplies', {}).get(self._supply_name, {}).get(self._field)
        if self._field == 'last_cleaned' and value:
            from homeassistant.util.dt import parse_datetime
            return parse_datetime(value)
        return value

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data.get('supplies', {}).get(self._supply_name, {})
        return {'part_model': data.get('model'), 'cleaning_interval_hours': data.get('cleaning_interval_hours')}
