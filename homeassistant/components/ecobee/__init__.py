"""Support for ecobee."""
import asyncio
from datetime import timedelta
import voluptuous as vol

from pyecobee import Ecobee, ECOBEE_API_KEY, ECOBEE_REFRESH_TOKEN, ExpiredTokenError

from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import CONF_API_KEY
from homeassistant.helpers import config_validation as cv
from homeassistant.util import Throttle

from .const import (
    CONF_REFRESH_TOKEN,
    DATA_ECOBEE_CONFIG,
    DOMAIN,
    ECOBEE_PLATFORMS,
    _LOGGER,
)

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=180)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({vol.Optional(CONF_API_KEY): cv.string})}, extra=vol.ALLOW_EXTRA
)


async def async_setup(hass, config):
    """
    Ecobee uses config flow for configuration.

    But, an "ecobee:" entry in configuration.yaml will trigger an import flow
    if a config entry doesn't already exist. If ecobee.conf exists, the import
    flow will attempt to import it and create a config entry, to assist users
    migrating from the old ecobee component. Otherwise, the user will have to
    continue setting up the integration via the config flow.
    """
    hass.data[DATA_ECOBEE_CONFIG] = config.get(DOMAIN, {})

    if not hass.config_entries.async_entries(DOMAIN) and hass.data[DATA_ECOBEE_CONFIG]:
        # No config entry exists and configuration.yaml config exists, trigger the import flow.
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}
            )
        )

    return True


async def async_setup_entry(hass, entry):
    """Set up ecobee via a config entry."""
    api_key = entry.data[CONF_API_KEY]
    refresh_token = entry.data[CONF_REFRESH_TOKEN]

    data = EcobeeData(hass, entry, api_key=api_key, refresh_token=refresh_token)

    if not await data.refresh():
        return False

    await data.update()

    if data.ecobee.thermostats is None:
        _LOGGER.error("No ecobee devices found to set up")
        return False

    hass.data[DOMAIN] = data

    for component in ECOBEE_PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, component)
        )

    return True


class EcobeeData:
    """
    Handle getting the latest data from ecobee.com so platforms can use it.

    Also handle refreshing tokens and updating config entry with refreshed tokens.
    """

    def __init__(self, hass, entry, api_key, refresh_token):
        """Initialize the Ecobee data object."""
        self._hass = hass
        self._entry = entry
        self.ecobee = Ecobee(
            config={ECOBEE_API_KEY: api_key, ECOBEE_REFRESH_TOKEN: refresh_token}
        )

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def update(self):
        """Get the latest data from ecobee.com."""
        try:
            await self._hass.async_add_executor_job(self.ecobee.update)
            _LOGGER.debug("Updating ecobee")
        except ExpiredTokenError:
            _LOGGER.warning(
                "Ecobee update failed; attempting to refresh expired tokens"
            )
            await self.refresh()

    async def refresh(self) -> bool:
        """Refresh ecobee tokens and update config entry."""
        _LOGGER.debug("Refreshing ecobee tokens and updating config entry")
        if await self._hass.async_add_executor_job(self.ecobee.refresh_tokens):
            self._hass.config_entries.async_update_entry(
                self._entry,
                data={
                    CONF_API_KEY: self.ecobee.config[ECOBEE_API_KEY],
                    CONF_REFRESH_TOKEN: self.ecobee.config[ECOBEE_REFRESH_TOKEN],
                },
            )
            return True
        _LOGGER.error("Error updating ecobee tokens")
        return False


async def async_unload_entry(hass, config_entry):
    """Unload the config entry and platforms."""
    hass.data.pop(DOMAIN)

    tasks = []
    for platform in ECOBEE_PLATFORMS:
        tasks.append(
            hass.config_entries.async_forward_entry_unload(config_entry, platform)
        )

    return all(await asyncio.gather(*tasks))
