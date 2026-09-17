"""Config flow for the Clack Ekodar integration."""
from __future__ import annotations

import re

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_MAC,
    CONF_PREFIX,
    CONF_SECTION_INTERVAL,
    CONF_SALT_BAG_KG,
    CONF_SALT_KG_PER_REGEN,
    CONF_SALT_REGENS_PER_BAG,
    CONF_SALT_TANK_KG,
    CONF_SALT_WARN_KG,
    CONF_SALT_WARN_REGENS,
    DEFAULT_PREFIX,
    DEFAULT_SECTION_INTERVAL_MIN,
    DOMAIN,
)

MAC_RE = re.compile(r"^[0-9A-Fa-f]{12}$")


class ClackConfigFlow(ConfigFlow, domain=DOMAIN):
    """Match the Ekodar Wi-Fi board by its MAC (used as MQTT client-id)."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> "ClackOptionsFlow":
        return ClackOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            mac = user_input[CONF_MAC].replace(":", "").upper()
            if not MAC_RE.match(mac):
                errors[CONF_MAC] = "invalid_mac"
            else:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Clack {mac[:4]}…{mac[-4:]}",
                    data={
                        CONF_MAC: mac,
                        CONF_PREFIX: user_input.get(CONF_PREFIX) or DEFAULT_PREFIX,
                        CONF_SECTION_INTERVAL: int(
                            user_input.get(CONF_SECTION_INTERVAL)
                            or DEFAULT_SECTION_INTERVAL_MIN
                        ),
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_MAC): str,
                vol.Optional(CONF_PREFIX, default=DEFAULT_PREFIX): str,
                vol.Optional(
                    CONF_SECTION_INTERVAL, default=DEFAULT_SECTION_INTERVAL_MIN
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


def _num(value, default: float) -> float:
    """options dicts may miss keys / hold None."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


class ClackOptionsFlow(OptionsFlow):
    """Options: section poll interval + salt accounting config."""

    async def async_step_init(self, user_input=None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        opts = self.config_entry.options

        def d(key, default):
            return _num(opts.get(key), default)

        num = vol.All(vol.Coerce(float), vol.Range(min=0, max=1000))
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SECTION_INTERVAL,
                        default=int(opts.get(
                            CONF_SECTION_INTERVAL,
                            self.config_entry.data.get(
                                CONF_SECTION_INTERVAL,
                                DEFAULT_SECTION_INTERVAL_MIN))),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
                    vol.Optional(CONF_SALT_BAG_KG,
                                 default=d(CONF_SALT_BAG_KG, 25.0)): num,
                    vol.Optional(CONF_SALT_REGENS_PER_BAG,
                                 default=d(CONF_SALT_REGENS_PER_BAG, 10.0)): num,
                    vol.Optional(CONF_SALT_KG_PER_REGEN,
                                 default=d(CONF_SALT_KG_PER_REGEN, 0.0)): num,
                    vol.Optional(CONF_SALT_TANK_KG,
                                 default=d(CONF_SALT_TANK_KG, 60.0)): num,
                    vol.Optional(CONF_SALT_WARN_KG,
                                 default=d(CONF_SALT_WARN_KG, 5.0)): num,
                    vol.Optional(CONF_SALT_WARN_REGENS,
                                 default=d(CONF_SALT_WARN_REGENS, 2.0)): num,
                }
            ),
        )
