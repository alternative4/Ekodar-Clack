"""Binary sensors for the Clack Ekodar integration."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import ClackDeviceEntity


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    device = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        ClackRegeneratingBinarySensor(device),
        ClackNeedsSaltBinarySensor(device),
    ])


class ClackRegeneratingBinarySensor(ClackDeviceEntity, BinarySensorEntity):
    """On while the valve is in a regeneration cycle (command=110 seen)."""

    def __init__(self, device) -> None:
        super().__init__(
            device,
            BinarySensorEntityDescription(
                key="regenerating",
                translation_key="regenerating",
            ),
        )
        self._attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool:
        return bool(self.device.regen)


class ClackNeedsSaltBinarySensor(ClackDeviceEntity, BinarySensorEntity):
    """Low-salt heuristic: service alarm text from the installer section."""

    def __init__(self, device) -> None:
        super().__init__(
            device,
            BinarySensorEntityDescription(
                key="service_alarm",
                translation_key="service_alarm",
                device_class=BinarySensorDeviceClass.PROBLEM,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )

    @property
    def is_on(self) -> bool:
        from .const import SECTION_INSTALLER
        s = self.device.sections.get(SECTION_INSTALLER, {})
        alarm = s.get("Service Alarm")
        # "Time" / "Volume" are normal scheduling modes, not alarms;
        # numeric/other values indicate the alarm flag from the cabinet.
        if isinstance(alarm, (int, float)):
            return bool(alarm)
        return str(alarm) in ("1", "true", "True", "Alarm")
