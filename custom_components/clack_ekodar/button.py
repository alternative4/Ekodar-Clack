"""Buttons for the Clack Ekodar integration."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CMD_REBOOT, CMD_SET_TIME, DAY_NAMES_EN, DOMAIN
from .entity import ClackDeviceEntity


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    device = hass.data[DOMAIN][entry.entry_id]
    entities = [SyncTimeButton(device), RebootButton(device)]
    async_add_entities(entities)


class SyncTimeButton(ClackDeviceEntity, ButtonEntity):
    """Write HA's current wall time into the valve ({"command":208})."""

    def __init__(self, device) -> None:
        super().__init__(device, ButtonEntityDescription(
            key="sync_time", name="Sync valve clock"))
        self._attr_translation_key = "sync_time"

    async def async_press(self) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(self.hass.config.time_zone)
        now = datetime.now(tz)
        await self.device.command({
            "command": CMD_SET_TIME,
            "Valve Hour": now.hour,
            "Valve Minute": now.minute,
            "Valve Day": DAY_NAMES_EN[now.weekday()],
        })


class RebootButton(ClackDeviceEntity, ButtonEntity):
    """Reboot the Wi-Fi module only (level:0). Never level:1 (factory reset)."""

    def __init__(self, device) -> None:
        super().__init__(device, ButtonEntityDescription(
            key="reboot", name="Reboot Wi-Fi module",
            entity_category=EntityCategory.CONFIG))
        self._attr_translation_key = "reboot"

    async def async_press(self) -> None:
        await self.device.command({"command": CMD_REBOOT, "level": 0})
