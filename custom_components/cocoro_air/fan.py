"""Power and exact Sharp operating presets."""
from homeassistant.components.fan import FanEntity, FanEntityFeature
from .entity import CocoroAirEntity, coordinators


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CocoroAirFan(c) for c in coordinators(hass, entry)])


class CocoroAirFan(CocoroAirEntity, FanEntity):
    _attr_supported_features = FanEntityFeature.PRESET_MODE

    def __init__(self, coordinator):
        super().__init__(coordinator, 'fan', 'Air purifier')
        # These feature flags were added after HA 2024.2.
        for feature in ('TURN_ON', 'TURN_OFF'):
            self._attr_supported_features |= getattr(FanEntityFeature, feature, 0)

    @property
    def is_on(self):
        return self.coordinator.data.get('power')

    @property
    def preset_modes(self):
        return self.coordinator.modes

    @property
    def preset_mode(self):
        mode = self.coordinator.data.get('current_mode')
        return mode if mode in self.preset_modes else None

    @property
    def extra_state_attributes(self):
        return {'operating_status': self.coordinator.data.get('current_mode')}

    async def async_set_preset_mode(self, preset_mode):
        if preset_mode not in self.preset_modes:
            raise ValueError('Unsupported preset')
        await self.coordinator.async_control('mode', preset_mode)

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs):
        if percentage is not None:
            raise ValueError('Use a supported Sharp preset instead of percentage')
        if preset_mode is not None and preset_mode not in self.preset_modes:
            raise ValueError('Unsupported preset')
        await self.coordinator.async_control('power', True)
        if preset_mode:
            await self.async_set_preset_mode(preset_mode)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_control('power', False)
