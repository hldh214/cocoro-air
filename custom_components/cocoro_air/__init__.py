import logging

import httpx
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

DOMAIN = "cocoro_air"
PLATFORMS = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema({}, extra=vol.ALLOW_EXTRA)


async def async_setup(hass: HomeAssistant, _config: dict):
    """Set up the Cocoro Air component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Cocoro Air from a config entry."""
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    # device_id is now in entry.data['devices'] (list) or entry.options

    cocoro_air_api = CocoroAir(email, password)

    try:
        await hass.async_add_executor_job(cocoro_air_api.login)
    except Exception as e:
        _LOGGER.error(f"Failed to login: {e}")
        return False

    hass.data[DOMAIN][entry.entry_id] = cocoro_air_api

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class CocoroAir:
    def __init__(self, email, password):
        self._opener = None
        self.email = email
        self.password = password

    @property
    def opener(self):
        if self._opener is None:
            self._opener = httpx.Client(headers={
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
                'Accept': 'application/json'
            }, timeout=10)
        return self._opener

    def login(self):
        _LOGGER.debug(f"Starting login for {self.email}")
        try:
            res = self.opener.get('https://cocoroplusapp.jp.sharp/v1/cocoro-air/login')
            res.raise_for_status()

            redirect_url = res.json()['redirectUrl']
            _LOGGER.debug(f"Redirect URL: {redirect_url}")

            res = self.opener.get(redirect_url, follow_redirects=True)
            res.raise_for_status()

            if '/sic-front/sso/ExLoginViewAction.do' not in res.url.path:
                _LOGGER.warning(f"Unexpected redirect path: {res.url.path}")

            res = self.opener.post('https://cocoromembers.jp.sharp/sic-front/sso/A050101ExLoginAction.do', data={
                'memberId': self.email,
                'password': self.password,
                'captchaText': '1',
                'autoLogin': 'on',
                'exsiteId': '50130',
            }, follow_redirects=True)

            res.raise_for_status()

            _LOGGER.debug(f"Login response URL: {res.url}")

            if b'login=success' not in res.url.query:
                _LOGGER.error(f"Login failed? URL: {res.url}")
                # Don't assert, let it fail downstream or throw error here
                raise Exception("Login failed: 'login=success' not found in URL")

            _LOGGER.info('Login success')
            _LOGGER.debug(f"Cookies after login: {dict(self.opener.cookies)}")

        except Exception as e:
            _LOGGER.error(f"Exception during login: {e}")
            raise

    def query_devices(self):
        """Query for available devices."""
        url = 'https://cocoroplusapp.jp.sharp/v1/cocoro-air/deviceinfos'
        _LOGGER.debug(f"Querying devices from: {url}")

        try:
            res = self.opener.get(url)
            _LOGGER.debug(f"Device query status: {res.status_code}")
            res.raise_for_status()

            try:
                data = res.json()
            except Exception as e:
                _LOGGER.error(f"Failed to decode JSON from {url}: {e}")
                _LOGGER.debug(f"Response content that failed JSON decode: {res.text}")
                raise

            devices = []
            # Structure: {"device_infos_...": {"body": {"devices": [...]}}}
            for key, val in data.items():
                if isinstance(val, dict) and 'body' in val and 'devices' in val['body']:
                    for d in val['body']['devices']:
                        name = d.get('device_name', d.get('device_id', 'Unknown'))
                        model = d.get('model_name', '')
                        place = d.get('place', '')

                        label = f"{name}"
                        if model:
                            label += f" ({model})"
                        if place:
                            label += f" - {place}"

                        devices.append({
                            'label': label,
                            'device_id': d['device_id'],
                            'device_name': name,
                            'model_name': model
                        })

            if not devices:
                _LOGGER.warning(f"No devices found in response: {data.keys()}")

            return devices
        except Exception as e:
            _LOGGER.error(f"Error querying devices: {e}")
            raise

    def _fetch_opc(self, device_id, opc):
        """Fetch a single opc block (k1, k2, etc.) from the sensor API."""
        url = 'https://cocoroplusapp.jp.sharp/v1/cocoro-air/sensors-conceal/air-cleaner'
        params = {
            'device_id': device_id,
            'event_key': 'echonet_property',
            'opc': opc,
        }

        res = self.opener.get(url, params=params)

        if res.status_code == 401:
            _LOGGER.info('Session expired, re-login')
            self.login()
            res = self.opener.get(url, params=params)

        data = res.json().get('sensors_aircleaner_021', {}).get('body', {}).get('data', [{}])[0]
        return data.get(opc)

    def get_sensor_data(self, device_id):
        if not device_id:
            _LOGGER.error("Device ID not provided")
            return None

        try:
            k1 = self._fetch_opc(device_id, 'k1')
        except Exception as e:
            _LOGGER.error(f'Failed to fetch k1: {e}')
            return None

        if not k1:
            _LOGGER.error('k1 data is empty')
            return None

        _LOGGER.debug(f'k1 raw: {k1}')

        try:
            temperature = int(k1['s1'], 16)
            humidity = int(k1['s2'], 16)
        except (KeyError, ValueError) as e:
            _LOGGER.error(f'Failed to parse sensor values: {e}, data: {k1}')
            return None

        result = {
            'temperature': temperature,
            'humidity': humidity,
        }

        # PM2.5 from k1.s8 (µg/m³)
        try:
            if 's8' in k1:
                result['pm25'] = int(k1['s8'], 16)
        except (ValueError, TypeError) as e:
            _LOGGER.warning(f'Failed to parse PM2.5 from k1.s8: {e}')

        # k2 contains dust and odor levels (only available when device is actively running)
        try:
            k2 = self._fetch_opc(device_id, 'k2')
            if k2:
                _LOGGER.debug(f'k2 raw: {k2}')
                if 's16' in k2:
                    result['odor'] = int(k2['s16'], 16)
                if 's17' in k2:
                    result['dust'] = int(k2['s17'], 16)
            else:
                _LOGGER.debug('k2 empty (device may be in standby)')
        except Exception as e:
            _LOGGER.debug(f'k2 fetch failed: {e}')

        return result
