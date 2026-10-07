"""Device refresh and cloud updates against real Home Assistant coordination."""
import asyncio
import copy
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo
try:
    from homeassistant.core import HomeAssistant
except ImportError:
    raise unittest.SkipTest('Requires Home Assistant test environment')
from custom_components.cocoro_air.coordinator import CocoroAirCoordinator
from custom_components.cocoro_air.services import async_setup_services


class Api:
    def __init__(self):
        self.notifications={'air_cleaner':True,'temperature':False,
                            'temperature_detail':{'temperature_lower':None,'temperature_upper':None}}
        self.power=True
    def get_status(self,device_id):
        return {'data':[{'0x80':'0x30' if self.power else '0x31'},
                        {'k1':{'s1':'1a','s2':'2b','s8':'0066','s9':'0066','s10':'00a0','s11':'a0','s4':'2b08','s5':'2b08'}},
                        {'k2':{'s11':'81','s7':'ff'}},
                        {'k3':{'s1':'10' if self.power else '00','s2':'80'}}]}
    def get_supplies(self,device_id):
        return {'data':[{'0x10':[{'0x00':'0x00','0x01':'TEST','0x02':'0x000A'}]}]}
    def history(self,*args):return {'data':[]}
    def get_pets(self,device_id):return {'data':[]}
    def get_tariff(self,device_id):return {'data':[]}
    def get_notifications(self,device_id):return copy.deepcopy(self.notifications)
    def set_notifications(self,device_id,data):self.notifications=copy.deepcopy(data);return {'ok':True}
    def control(self,device,commands):self.power=commands[0].get('edt')=='0x30';return {'ok':True}


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.hass=HomeAssistant(self.tmp.name)
        self.api=Api()
        self.c=CocoroAirCoordinator(self.hass,self.api,{'device_id':'fixture','device_name':'Test','model_name':'KIPX70',
             'spec':{'seriiesCode':6,'hasHumidFunc':True,'hasCloudService':True,'dustFilterLimit':3000}})
        self.hass.data['cocoro_air']={'entry':{'coordinators':{'fixture':self.c}}}
        await self.c.async_refresh()
    async def asyncTearDown(self):
        await self.c.async_shutdown()
        await self.hass.async_stop(force=True)
        self.tmp.cleanup()

    async def test_refresh_supplies_matches_vendor_percentage(self):
        self.assertEqual(self.c.data['supplies']['dust_filter']['remaining'],96)
        self.assertEqual(self.c.data['temperature'],26)
        await self.c.async_control('power',False)
        self.assertFalse(self.c.data['power'])
        self.assertIsNone(self.c.data['temperature'])

    async def test_costs_follow_official_daily_and_monthly_queries(self):
        calls = []
        def history(device_id, properties, start, end):
            calls.append((properties, start, end))
            monthly = properties[0]['code']['0x40']['0x00'] == '0x01'
            return {'data': [{'time': '2026-10-01T00:00:00+00:00', '0x40': {'0x00': '0x000186A0'}}]} if monthly else {'data': [{'time': '2026-10-07T00:00:00+00:00', '0x40': {'0x00': '0x00000534'}}]}
        self.api.history = history
        self.c._cloud_updated = 0
        with patch('custom_components.cocoro_air.coordinator.datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 7, 10, 45, tzinfo=ZoneInfo('Asia/Tokyo'))
            await self.c.async_refresh()
        self.assertTrue(self.c.last_update_success)
        self.assertEqual(self.c.data['cost_today'], 1.332)
        self.assertEqual(self.c.data['cost_month'], 100)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1:], ('2026-10-07T10:00:00.000Z', '2026-10-07T10:00:00.000Z'))
        self.assertEqual(calls[1][1:], ('2025-10-07T10:00:00.000Z', '2026-10-07T10:00:00.000Z'))

    async def test_concurrent_notifications_preserve_both_updates(self):
        await asyncio.gather(self.c.async_set_notifications({'air_cleaner':False}),
                             self.c.async_set_notifications({'temperature':True}))
        self.assertEqual(self.api.notifications['air_cleaner'],False)
        self.assertEqual(self.api.notifications['temperature'],True)

    async def test_services_return_real_ha_response(self):
        async_setup_services(self.hass)
        response=await self.hass.services.async_call('cocoro_air','get_cloud_info',{},blocking=True,return_response=True)
        self.assertEqual(response['model'],'KIPX70')
        await self.hass.services.async_call('cocoro_air','set_notifications',
                         {'preferences':{'temperature_upper':30}},blocking=True)
        self.assertEqual(self.api.notifications['temperature_detail']['temperature_upper'],30)

    async def test_optional_cloud_failure_recovers_without_disabling_device(self):
        from custom_components.cocoro_air.api import CocoroAirConnectionError
        original=self.api.get_supplies
        def fail(device_id):raise CocoroAirConnectionError('offline')
        self.api.get_supplies=fail
        self.c._cloud_updated=0
        await self.c.async_refresh()
        self.assertTrue(self.c.last_update_success)
        self.assertEqual(self.c.data['supplies'],{})
        self.api.get_supplies=original
        self.c._cloud_updated=0
        await self.c.async_refresh()
        self.assertEqual(self.c.data['supplies']['dust_filter']['remaining'],96)

    async def test_malformed_optional_weather_keeps_device_controls_available(self):
        self.c.device['zip_code'] = '1000001'
        self.api.get_weather = lambda *args: {'data': ['invalid']}
        self.c._cloud_updated = 0
        await self.c.async_refresh()
        self.assertTrue(self.c.last_update_success)
        self.assertTrue(self.c.data['power'])
