"""Authentication flows using HA's actual flow implementation."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from homeassistant import config_entries
except ImportError:
    raise unittest.SkipTest('Requires Home Assistant test environment')

from custom_components.cocoro_air.api import CocoroAirAuthError
from custom_components.cocoro_air.config_flow import CocoroAirConfigFlow


class FakeApi:
    failed = False
    instances = []
    def __init__(self, email, password):
        self.email = email
        self.closed = False
        self.instances.append(self)
    def login(self):
        if self.failed:
            raise CocoroAirAuthError('PRIVATE_PASSWORD')
    def query_devices(self):
        return [{'device_id': 'selected', 'label': 'Purifier'}]
    def close(self):
        self.closed = True


class FakeEntries:
    def __init__(self, entry):
        self.entry = entry
        self.reloaded = []
        self.flow = SimpleNamespace(async_progress_by_handler=lambda *args, **kwargs: [{'flow_id': 'other'}])
    def async_get_entry(self, entry_id):
        return self.entry if entry_id == self.entry.entry_id else None
    def async_get_known_entry(self, entry_id):
        return self.async_get_entry(entry_id)
    def async_update_entry(self, entry, **kwargs):
        for key, value in kwargs.items():
            if key in ('data', 'options', 'title', 'unique_id') and not isinstance(value, config_entries.UndefinedType):
                setattr(entry, key, value)
        return True
    def async_schedule_reload(self, entry_id):
        self.reloaded.append(entry_id)
    async def async_reload(self, entry_id):
        self.reloaded.append(entry_id)


class ConfigFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeApi.failed = False
        FakeApi.instances = []
        self.entry = SimpleNamespace(entry_id='entry', domain='cocoro_air', title='Account', unique_id='user@example.com',
                                     data={'email': 'user@example.com', 'password': 'old', 'devices': ['selected'], 'future_key': 42},
                                     options={'devices': ['selected'], 'future_option': True}, update_listeners=[])
        self.entries = FakeEntries(self.entry)
        async def executor(method, *args):
            return method(*args)
        self.hass = SimpleNamespace(config_entries=self.entries, async_add_executor_job=executor,
                                    async_create_task=lambda coro, *args: asyncio.create_task(coro))
        self.flow = CocoroAirConfigFlow()
        self.flow.hass = self.hass
        self.flow.context = {'entry_id': 'entry', 'source': 'reauth'}
        self.flow.handler = 'cocoro_air'
        self.flow.flow_id = 'test-flow'

    async def test_reauth_preserves_device_selection_options_and_other_data(self):
        with patch('custom_components.cocoro_air.config_flow.CocoroAir', FakeApi):
            form = await self.flow.async_step_reauth(self.entry.data)
            self.assertEqual(form['step_id'], 'reauth_confirm')
            result = await self.flow.async_step_reauth_confirm({'password': 'new'})
        await asyncio.sleep(0)
        self.assertEqual(result['reason'], 'reauth_successful')
        self.assertEqual(self.entry.data, {'email': 'user@example.com', 'password': 'new', 'devices': ['selected'], 'future_key': 42})
        self.assertEqual(self.entry.options, {'devices': ['selected'], 'future_option': True})
        self.assertEqual(self.entries.reloaded, ['entry'])
        self.assertTrue(FakeApi.instances[0].closed)

    async def test_reauth_wrong_credentials_return_sanitized_form(self):
        FakeApi.failed = True
        with patch('custom_components.cocoro_air.config_flow.CocoroAir', FakeApi):
            await self.flow.async_step_reauth(self.entry.data)
            result = await self.flow.async_step_reauth_confirm({'password': 'bad'})
        self.assertEqual(result['errors'], {'base': 'invalid_auth'})
        self.assertNotIn('PRIVATE_PASSWORD', str(result))
        self.assertEqual(self.entry.data['password'], 'old')
        self.assertTrue(FakeApi.instances[0].closed)

    async def test_initial_wrong_credentials_have_auth_error(self):
        FakeApi.failed = True
        with patch('custom_components.cocoro_air.config_flow.CocoroAir', FakeApi):
            result = await self.flow.async_step_user({'email': 'user@example.com', 'password': 'bad'})
        self.assertEqual(result['errors'], {'base': 'invalid_auth'})
        self.assertNotIn('PRIVATE_PASSWORD', str(result))
        self.assertTrue(FakeApi.instances[0].closed)
