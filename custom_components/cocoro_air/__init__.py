"""Cocoro Air: official web controls and cloud information."""
import logging
import voluptuous as vol
from homeassistant.const import Platform, CONF_EMAIL, CONF_PASSWORD
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from .const import DOMAIN
from .api import CocoroAir, CocoroAirAuthError, CocoroAirConnectionError, CocoroAirProtocolError
from .coordinator import CocoroAirCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR,Platform.FAN,Platform.SWITCH,Platform.BINARY_SENSOR,Platform.NUMBER,Platform.BUTTON]
CONFIG_SCHEMA = vol.Schema({},extra=vol.ALLOW_EXTRA)


async def async_setup(hass,config):
    hass.data.setdefault(DOMAIN,{})
    return True


async def async_setup_entry(hass,entry):
    hass.data.setdefault(DOMAIN,{})
    api = CocoroAir(entry.data[CONF_EMAIL],entry.data[CONF_PASSWORD])
    coordinators = {}
    async def close_failed_setup():
        for coordinator in coordinators.values():
            if hasattr(coordinator, 'async_shutdown'):
                await coordinator.async_shutdown()
        await hass.async_add_executor_job(api.close)
    try:
        await hass.async_add_executor_job(api.login)
        devices = await hass.async_add_executor_job(api.query_devices)
        selected = set(entry.options.get('devices',entry.data.get('devices',[])))
        device_map = {d['device_id']:d for d in devices}
        if not selected or selected - device_map.keys():
            raise ConfigEntryNotReady('Selected Sharp device is not available')
        for device_id in selected:
            c = CocoroAirCoordinator(hass,api,device_map[device_id],entry)
            coordinators[device_id] = c
            await c.async_config_entry_first_refresh()
    except CocoroAirAuthError as err:
        await close_failed_setup()
        raise ConfigEntryAuthFailed('Unable to authenticate with Sharp') from err
    except (CocoroAirConnectionError,CocoroAirProtocolError) as err:
        await close_failed_setup()
        raise ConfigEntryNotReady(str(err)) from err
    except Exception:
        await close_failed_setup()
        raise
    hass.data[DOMAIN][entry.entry_id] = {'api':api,'coordinators':coordinators}
    try:
        from .services import async_setup_services
        async_setup_services(hass)
        await hass.config_entries.async_forward_entry_setups(entry,PLATFORMS)
    except Exception:
        hass.data[DOMAIN].pop(entry.entry_id,None)
        await close_failed_setup()
        if not hass.data[DOMAIN]:
            from .services import SERVICE_NAMES
            for name in SERVICE_NAMES:
                hass.services.async_remove(DOMAIN, name)
        raise
    return True


async def async_unload_entry(hass,entry):
    if await hass.config_entries.async_unload_platforms(entry,PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        for coordinator in data['coordinators'].values():
            if hasattr(coordinator,'async_shutdown'):
                await coordinator.async_shutdown()
        await hass.async_add_executor_job(data['api'].close)
        if not hass.data[DOMAIN]:
            from .services import SERVICE_NAMES
            for name in SERVICE_NAMES:
                hass.services.async_remove(DOMAIN,name)
        return True
    return False
