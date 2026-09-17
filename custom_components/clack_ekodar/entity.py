"""Base entity for the Clack Ekodar integration."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.core import callback

from .const import DOMAIN, ONLINE_TIMEOUT_S


@dataclass(frozen=True, kw_only=True)
class ClackEntityDescription(EntityDescription):
    """Description carrying which status dict the value comes from."""

    source: str = "status"  # "status" (cmd=100), "regen" (cmd=110), section code
    device_class: object | None = None


class ClackDeviceEntity(Entity):
    """Common device info / availability for all Clack entities."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    entity_description: ClackEntityDescription

    def __init__(self, device, description: ClackEntityDescription) -> None:
        self.device = device
        self.entity_description = description
        self._attr_unique_id = f"{device.mac}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.mac)},
            name="Clack Water Softener",
            manufacturer="Clack Corporation",
            model="EM.S (Ekodar Wi-Fi)",
            sw_version="0.24 for EK",
        )

    @property
    def available(self) -> bool:
        import time
        status = self.device.status
        if not status:
            return False
        return (time.time() - status.get("_seen", 0)) < ONLINE_TIMEOUT_S

    @property
    def _data(self) -> dict:
        src = self.entity_description.source
        if src == "status":
            return self.device.status
        if src == "regen":
            return self.device.regen or {}
        return self.device.sections.get(int(src), {})

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.device.subscribe_update(self.async_write_ha_state))
