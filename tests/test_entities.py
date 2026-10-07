"""Exercise entity capabilities with the real Home Assistant entity classes."""
import asyncio
import unittest
from types import SimpleNamespace

try:
    import homeassistant
except ImportError:
    raise unittest.SkipTest('Requires Home Assistant test environment')

from custom_components.cocoro_air.coordinator import CocoroAirCoordinator
from custom_components.cocoro_air.fan import CocoroAirFan
from custom_components.cocoro_air.sensor import CocoroAirSensor
from custom_components.cocoro_air.switch import CocoroAirSwitch


class FakeCoordinator:
    device_id = 'fixture'
    device_name = 'Purifier'
    model_name = 'KIPX70'
    spec = {'hasHumidFunc': True, 'hasCloudService': True, 'hasSplashParticle': True,
            'seriiesCode': 6, 'model_name': 'KIPX70'}
    data = {'power': True, 'current_mode': 'auto', 'temperature': 26,
            'humidity': 43, 'pets': [], 'cloud_enabled': True,
            'humidification_enabled': True}
    last_update_success = True
    config_entry = None
    def __init__(self):
        self.calls = []
    async def async_control(self, action, value):
        self.calls.append((action, value))
    @property
    def modes(self):
        return ['ai_auto', 'auto', 'quiet', 'medium', 'strong']


class EntityTests(unittest.IsolatedAsyncioTestCase):
    async def test_sensor_preserves_existing_identity(self):
        c = FakeCoordinator()
        sensor = CocoroAirSensor(c, 'temperature')
        self.assertEqual(sensor.unique_id, 'cocoro_air_fixture_temperature')
        self.assertEqual(sensor.native_value, 26)
        self.assertEqual(sensor.device_info['identifiers'], {('cocoro_air','fixture')})

    async def test_fan_only_exposes_supported_presets(self):
        c = FakeCoordinator()
        fan = CocoroAirFan(c)
        self.assertEqual(fan.preset_modes, c.modes)
        await fan.async_set_preset_mode('quiet')
        self.assertEqual(c.calls, [('mode','quiet')])
        with self.assertRaises(ValueError):
            await fan.async_set_preset_mode('dog')

    async def test_fan_turn_on_honors_preset_and_off(self):
        c = FakeCoordinator()
        fan = CocoroAirFan(c)
        await fan.async_turn_on(preset_mode='strong')
        await fan.async_turn_off()
        self.assertEqual(c.calls, [('power',True),('mode','strong'),('power',False)])

    async def test_switch_uses_confirmed_control(self):
        c = FakeCoordinator()
        switch = CocoroAirSwitch(c, 'humidification')
        self.assertTrue(switch.is_on)
        await switch.async_turn_off()
        self.assertEqual(c.calls,[('humidification',False)])

    async def test_pet_capable_device_has_child_lock_status_entity(self):
        from custom_components.cocoro_air.binary_sensor import async_setup_entry
        c = FakeCoordinator()
        c.spec = {**c.spec, 'hasChildLock': False, 'hasPetMode': True}
        c.async_add_listener = lambda listener: lambda: None
        entry = SimpleNamespace(entry_id='entry', async_on_unload=lambda cancel: None)
        hass = SimpleNamespace(data={'cocoro_air': {'entry': {'coordinators': {'fixture': c}}}})
        entities = []
        await async_setup_entry(hass, entry, entities.extend)
        self.assertIn('child_lock', [entity._key for entity in entities])

    async def test_supplies_entities_appear_after_initial_cloud_failure_once(self):
        from custom_components.cocoro_air.sensor import async_setup_entry
        c = FakeCoordinator()
        c.device = {}
        c.data = {**c.data, 'supplies': {}}
        listeners = []
        cancelled = []
        def listen(callback):
            listeners.append(callback)
            return lambda: cancelled.append(callback)
        c.async_add_listener = listen
        cleanup = []
        entry = SimpleNamespace(entry_id='entry', async_on_unload=cleanup.append)
        hass = SimpleNamespace(data={'cocoro_air': {'entry': {'coordinators': {'fixture': c}}}})
        entities = []
        await async_setup_entry(hass, entry, entities.extend)
        self.assertFalse(any(entity._key.startswith('dust_filter_') for entity in entities))
        c.data['supplies'] = {'dust_filter': {'remaining': 96, 'last_cleaned': None}}
        listeners[0]()
        listeners[0]()
        self.assertEqual(sum(entity._key == 'dust_filter_remaining' for entity in entities), 1)
        self.assertEqual(sum(entity._key == 'dust_filter_last_cleaned' for entity in entities), 1)
        cleanup[0]()
        self.assertEqual(cancelled, listeners)

    async def test_notification_number_accepts_null_cloud_detail(self):
        from custom_components.cocoro_air.number import CocoroAirNotificationNumber
        c = FakeCoordinator()
        c.data = {**c.data, 'notifications': {'temperature_detail': None}}
        self.assertIsNone(CocoroAirNotificationNumber(c, 'temperature_upper').native_value)
