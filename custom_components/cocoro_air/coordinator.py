"""Share one device refresh across all Cocoro Air platforms."""
from datetime import timedelta, datetime, timezone
from zoneinfo import ZoneInfo
import asyncio
import logging
import time
import inspect

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CocoroAirAuthError, CocoroAirConnectionError, CocoroAirProtocolError
from .protocol import parse_status, build_command, supported_modes
from .cloud import parse_supplies, notification_payload, parse_weather, decode_cost_records, decode_tariff

_LOGGER = logging.getLogger(__name__)


class CocoroAirCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, api, device, entry=None):
        kwargs = {'config_entry': entry} if 'config_entry' in inspect.signature(DataUpdateCoordinator).parameters else {}
        super().__init__(hass, _LOGGER, name='Cocoro Air', update_interval=timedelta(seconds=60), **kwargs)
        self.api = api
        self.device = device
        self.device_id = device['device_id']
        self.device_name = device.get('device_name', 'Cocoro Air')
        self.model_name = device.get('model_name', 'Cocoro Air')
        self.spec = {**device.get('spec', {}), 'model_name': self.model_name}
        self._lock = asyncio.Lock()
        self._cloud_updated = 0
        self._cloud_data = {}

    async def async_api(self, method, *args):
        try:
            return await self.hass.async_add_executor_job(method, *args)
        except CocoroAirAuthError as err:
            raise ConfigEntryAuthFailed('Sharp session expired') from err
        except (CocoroAirConnectionError, CocoroAirProtocolError, ValueError) as err:
            raise HomeAssistantError(str(err)) from err

    async def _async_update_data(self):
        async with self._lock:
            try:
                body = await self.async_api(self.api.get_status, self.device_id)
                data = parse_status(body, self.spec)
                if not data['properties'].get('k3'):
                    raise UpdateFailed('Sharp returned no device operating state')
                if time.monotonic() - self._cloud_updated >= 900:
                    cloud = {}
                    for key, method in [('supplies_raw', self.api.get_supplies),
                                        ('pets', self.api.get_pets),
                                        ('notifications', self.api.get_notifications),
                                        ('tariff', self.api.get_tariff)]:
                        try:
                            result = await self.async_api(method, self.device_id)
                            cloud[key] = result.get('data', []) if key == 'pets' else result
                        except ConfigEntryAuthFailed:
                            raise
                        except HomeAssistantError:
                            # Optional cloud information must not disable device controls.
                            _LOGGER.warning('Unable to refresh Cocoro Air %s', key)
                            cloud[key] = None
                    if self.device.get('zip_code'):
                        try:
                            weather = await self.async_api(self.api.get_weather,self.device)
                            cloud.update(parse_weather(weather,datetime.now(ZoneInfo('Asia/Tokyo')).hour))
                        except ConfigEntryAuthFailed:
                            raise
                        except (HomeAssistantError,ValueError):
                            _LOGGER.warning('Unable to refresh Cocoro Air weather')
                    try:
                        now = datetime.now(ZoneInfo('Asia/Tokyo')).replace(minute=0, second=0, microsecond=0)
                        # The website sends JST wall-calendar values labeled as UTC.
                        stamp = now.replace(tzinfo=timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
                        previous_year = now.replace(year=now.year - 1, day=min(now.day, 28) if now.month == 2 else now.day)
                        start = previous_year.replace(tzinfo=timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
                        daily_properties = [{'apg': '0x01', 'apc': ['0x40'], 'code': {'0x40': {'0x00': '0x00', '0x01': '0x00'}}}]
                        monthly_properties = [{'apg': '0x01', 'apc': ['0x40'], 'code': {'0x40': {'0x00': '0x01', '0x01': '0x00'}}}]
                        daily = decode_cost_records(await self.async_api(self.api.history, self.device_id, daily_properties, stamp, stamp))
                        monthly = decode_cost_records(await self.async_api(self.api.history, self.device_id, monthly_properties, start, stamp))
                        cloud['cost_today'] = next((row['cost'] for row in daily if row['time'][:10] == now.strftime('%Y-%m-%d')), None)
                        cloud['cost_month'] = next((row['cost'] for row in monthly if row['time'][:7] == now.strftime('%Y-%m')), None)
                    except ConfigEntryAuthFailed:
                        raise
                    except (HomeAssistantError,ValueError):
                        _LOGGER.warning('Unable to refresh Cocoro Air electricity costs')
                    self._cloud_data = cloud
                    self._cloud_updated = time.monotonic()
                data.update(self._cloud_data)
                data['pets'] = data.get('pets') or []
                tariff_rows = (data.get('tariff') or {}).get('data') or []
                prices = decode_tariff(tariff_rows[0] if tariff_rows else {})
                data['electricity_rate'] = prices[datetime.now(ZoneInfo('Asia/Tokyo')).hour] if prices else None
                supplies = data.get('supplies_raw')
                record = (supplies or {}).get('data', [{}])
                data['supplies'] = parse_supplies(record[0] if record else {}, {**data, **data["properties"]}, self.spec)
                return data
            except ConfigEntryAuthFailed:
                raise
            except (HomeAssistantError, ValueError, TypeError) as err:
                raise UpdateFailed(str(err)) from err

    @property
    def modes(self):
        return supported_modes(self.spec, (self.data or {}).get('pets'), self.data)

    async def async_control(self, action, value):
        if action == 'mode' and value not in self.modes:
            raise ValueError('Mode is not supported by this device')
        async with self._lock:
            commands = build_command(action, value, self.data or {}, self.spec)
            await self.async_api(self.api.control, self.device, commands)
        await self.async_request_refresh()

    async def async_cloud_write(self, method, *args):
        async with self._lock:
            result = await self.async_api(method, *args)
            self._cloud_updated = 0
        await self.async_request_refresh()
        return result

    async def async_set_notifications(self, patch):
        async with self._lock:
            current = await self.async_api(self.api.get_notifications, self.device_id)
            payload = notification_payload(self.device_id, current, patch)
            result = await self.async_api(self.api.set_notifications, self.device_id, payload['data'])
            self._cloud_updated = 0
        await self.async_request_refresh()
        return result
