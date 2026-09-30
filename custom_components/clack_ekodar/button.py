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
    entities = [SyncTimeButton(device), RebootButton(device),
                SaltAddedButton(device), FetchSettingsButton(device)]
    async_add_entities(entities)


class FetchSettingsButton(ClackDeviceEntity, ButtonEntity):
    """On-demand read of all settings sections ({"command":200,"section":N}).

    The valve only answers section requests — it never pushes settings — so
    after an HA restart the settings sensors stay unknown until the periodic
    poll. This button runs the same fetch immediately.
    """

    def __init__(self, device) -> None:
        super().__init__(device, ButtonEntityDescription(
            key="fetch_settings", name="Refresh valve settings",
            icon="mdi:refresh"))
        # no entity_category: daily-use action, must show on the device card
        self._attr_translation_key = "fetch_settings"

    async def async_press(self) -> None:
        await self.device.fetch_sections()


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


class SaltAddedButton(ClackDeviceEntity, ButtonEntity):
    """'Salt added': +1 bag of salt to the tracked brine-tank level.

    Purely local bookkeeping (no valve command): records the event, raises
    level by salt_bag_kg (clamped to tank capacity) and persists state.
    """

    def __init__(self, device) -> None:
        super().__init__(device, ButtonEntityDescription(
            key="salt_added", name="Salt added"))
        # no entity_category: it is a daily-use action, must show on the
        # device card (CONFIG/DIAGNOSTIC hides it under a settings tab)
        self._attr_translation_key = "salt_added"

    async def async_press(self) -> None:
        self.device.salt.add_bags(1)
        await self.device.salt_changed()
