"""Service safety, device scoping and response contracts."""
import unittest
from types import SimpleNamespace
try:
    import homeassistant
except ImportError:
    raise unittest.SkipTest('Requires Home Assistant test environment')
from homeassistant.exceptions import HomeAssistantError
from custom_components.cocoro_air.services import resolve_coordinator, format_api_datetime, history_properties


class ServiceTests(unittest.TestCase):
    def test_resolves_only_configured_selected_device(self):
        c=SimpleNamespace(device_id='fixture')
        hass=SimpleNamespace(data={'cocoro_air':{'entry':{'coordinators':{'fixture':c}}}})
        self.assertIs(resolve_coordinator(hass,{'device_id':'fixture'}),c)
        with self.assertRaises(HomeAssistantError):
            resolve_coordinator(hass,{'device_id':'other'})

    def test_ambiguous_devices_require_explicit_selection(self):
        a,b=SimpleNamespace(device_id='a'),SimpleNamespace(device_id='b')
        hass=SimpleNamespace(data={'cocoro_air':{'entry':{'coordinators':{'a':a,'b':b}}}})
        with self.assertRaises(HomeAssistantError):
            resolve_coordinator(hass,{})

    def test_history_requires_timezone_and_milliseconds(self):
        self.assertEqual(format_api_datetime('2026-10-07T00:00:00+09:00'),'2026-10-06T15:00:00.000Z')
        with self.assertRaises(ValueError):
            format_api_datetime('2026-10-07')

    def test_cost_history_uses_japanese_wall_calendar_dates(self):
        self.assertEqual(format_api_datetime('2026-10-07T00:00:00+09:00', wall_calendar=True),
                         '2026-10-07T00:00:00.000Z')
        self.assertEqual(format_api_datetime('2026-10-06T15:00:00Z', wall_calendar=True),
                         '2026-10-07T00:00:00.000Z')

    def test_air_history_is_bounded_known_protocol(self):
        self.assertEqual(history_properties('air'),[{'apg':'0x01','apc':['0x20'],
                          'epc_ext':[{'opc':'k1'},{'opc':'k2'},{'opc':'k3'}]}])
        with self.assertRaises(ValueError):
            history_properties('anything')
