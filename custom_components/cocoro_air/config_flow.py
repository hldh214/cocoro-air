import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import config_validation as cv
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from .const import DOMAIN
from .api import CocoroAir, CocoroAirAuthError, CocoroAirConnectionError, CocoroAirProtocolError

_LOGGER = logging.getLogger(__name__)

class CocoroAirConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Cocoro Air."""
    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self.email = None
        self.password = None
        self.discovered_devices = []

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            self.email = user_input[CONF_EMAIL]
            self.password = user_input[CONF_PASSWORD]

            client = CocoroAir(self.email, self.password)
            try:
                await self.hass.async_add_executor_job(client.login)
                self.discovered_devices = await self.hass.async_add_executor_job(client.query_devices)

                if not self.discovered_devices:
                    errors["base"] = "no_devices_found"
                else:
                    return await self.async_step_device()

            except CocoroAirAuthError:
                errors["base"] = "invalid_auth"
            except (CocoroAirConnectionError, CocoroAirProtocolError):
                errors["base"] = "cannot_connect"
            except Exception:
                # A library exception may contain private session URLs or data.
                _LOGGER.error("Unexpected failure during Cocoro Air authentication")
                errors["base"] = "cannot_connect"
            finally:
                await self.hass.async_add_executor_job(client.close)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
            }),
            errors=errors
        )

    async def async_step_reauth(self, entry_data):
        """Request updated credentials for the same registered account."""
        self.email = entry_data[CONF_EMAIL]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Authenticate before updating the existing entry and reloading it."""
        errors = {}
        if user_input is not None:
            entry = self.hass.config_entries.async_get_entry(self.context['entry_id'])
            if entry is None:
                return self.async_abort(reason='reauth_entry_missing')
            client = CocoroAir(entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])
            try:
                await self.hass.async_add_executor_job(client.login)
                await self.hass.async_add_executor_job(client.query_devices)
            except CocoroAirAuthError:
                errors['base'] = 'invalid_auth'
            except (CocoroAirConnectionError, CocoroAirProtocolError):
                errors['base'] = 'cannot_connect'
            except Exception:
                _LOGGER.error('Unexpected failure during Cocoro Air reauthentication')
                errors['base'] = 'cannot_connect'
            finally:
                await self.hass.async_add_executor_job(client.close)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                    reason='reauth_successful',
                )
        return self.async_show_form(
            step_id='reauth_confirm',
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    async def async_step_device(self, user_input=None):
        """Handle the device selection step."""
        if user_input is not None:
            selected_devices = user_input["devices"]

            await self.async_set_unique_id(self.email)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=self.email,
                data={
                    CONF_EMAIL: self.email,
                    CONF_PASSWORD: self.password,
                    "devices": selected_devices,
                }
            )

        device_options = {d['device_id']: d['label'] for d in self.discovered_devices}

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema({
                vol.Required("devices", default=list(device_options.keys())): cv.multi_select(device_options)
            })
        )
