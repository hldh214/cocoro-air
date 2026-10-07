"""Load and unload all real HA platforms with a local cloud fixture."""
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from homeassistant.core import HomeAssistant
except ImportError:
    raise unittest.SkipTest('Requires Home Assistant test environment')

from homeassistant import loader
from homeassistant.config_entries import ConfigEntry, ConfigEntries, ConfigEntryState
from homeassistant.helpers import area_registry, device_registry, entity_registry, restore_state
from homeassistant.exceptions import ConfigEntryNotReady
from custom_components.cocoro_air import async_setup_entry
from custom_components.cocoro_air.coordinator import CocoroAirCoordinator
from test_coordinator import Api


class LifecycleApi(Api):
    def __init__(self):
        super().__init__()
        self.closed = False
    def login(self):
        pass
    def query_devices(self):
        return [{'device_id': 'fixture', 'device_name': 'Purifier', 'model_name': 'KIPX70',
                 'spec': {'seriiesCode': 6, 'hasHumidFunc': True, 'hasCloudService': True,
                          'hasPetMode': True, 'hasDustSensor': True, 'hasPM25Sensor': True,
                          'dustFilterLimit': 3000}}]
    def close(self):
        self.closed = True


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='cocoro-lifecycle-')
        Path(self.tmp.name, 'custom_components').symlink_to(
            Path(__file__).parents[1] / 'custom_components', target_is_directory=True)
        self.hass = HomeAssistant(self.tmp.name)
        self.hass.config.skip_pip = True
        self.hass.data['entity_info'] = {}
        loader.async_setup(self.hass)
        await restore_state.async_load(self.hass)
        self.hass.config_entries = ConfigEntries(self.hass, {})
        if hasattr(device_registry, 'async_setup'):
            device_registry.async_setup(self.hass)
        await area_registry.async_load(self.hass)
        await device_registry.async_load(self.hass)
        await entity_registry.async_load(self.hass)
        kwargs = {'version': 1, 'minor_version': 1, 'domain': 'cocoro_air', 'title': 'Fixture',
                  'data': {'email': 'fixture', 'password': 'fixture', 'devices': ['fixture']},
                  'options': {}, 'source': 'user', 'unique_id': 'fixture',
                  'discovery_keys': {}, 'subentries_data': []}
        accepted = inspect.signature(ConfigEntry).parameters
        self.entry = ConfigEntry(**{key: value for key, value in kwargs.items() if key in accepted})
        self.api = LifecycleApi()

    async def asyncTearDown(self):
        if self.entry.entry_id in self.hass.data.get('cocoro_air', {}):
            await self.hass.config_entries.async_unload(self.entry.entry_id)
        await self.hass.async_stop(force=True)
        self.tmp.cleanup()

    async def test_all_platforms_service_response_and_unload_close_client(self):
        with patch('custom_components.cocoro_air.CocoroAir', return_value=self.api):
            added = self.hass.config_entries.async_add(self.entry)
            if inspect.isawaitable(added):
                await added
            else:
                await self.hass.config_entries.async_setup(self.entry.entry_id)
            await self.hass.async_block_till_done()
            domains = {state.domain for state in self.hass.states.async_all()}
            self.assertTrue({'sensor', 'fan', 'switch', 'binary_sensor', 'number', 'button'} <= domains)
            response = await self.hass.services.async_call('cocoro_air', 'get_cloud_info', {},
                                                          blocking=True, return_response=True)
            self.assertEqual(response['model'], 'KIPX70')
            self.assertIn('dust_filter', response['supplies'])
            coordinators = list(self.hass.data['cocoro_air'][self.entry.entry_id]['coordinators'].values())
            self.assertTrue(await self.hass.config_entries.async_unload(self.entry.entry_id))
            await self.hass.async_block_till_done()
        self.assertTrue(self.api.closed)
        self.assertNotIn(self.entry.entry_id, self.hass.data['cocoro_air'])
        self.assertFalse(self.hass.services.has_service('cocoro_air', 'get_cloud_info'))
        self.assertTrue(all(not c._listeners and c._unsub_refresh is None for c in coordinators))

    async def test_failed_first_refresh_closes_client_and_coordinator(self):
        self.api.get_status = lambda device_id: {'data': []}
        state_kwargs = {'reason': None} if 'reason' in inspect.signature(self.entry._async_set_state).parameters else {}
        self.entry._async_set_state(self.hass, ConfigEntryState.SETUP_IN_PROGRESS, **state_kwargs)
        created = []
        def make_coordinator(*args, **kwargs):
            result = CocoroAirCoordinator(*args, **kwargs)
            created.append(result)
            return result
        with patch('custom_components.cocoro_air.CocoroAir', return_value=self.api), \
             patch('custom_components.cocoro_air.CocoroAirCoordinator', side_effect=make_coordinator):
            with self.assertRaises(ConfigEntryNotReady):
                await async_setup_entry(self.hass, self.entry)
        self.assertTrue(self.api.closed)
        self.assertNotIn(self.entry.entry_id, self.hass.data.get('cocoro_air', {}))
        self.assertTrue(created[0]._shutdown_requested)
