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
        ClackSaltLowBinarySensor(device),
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


class ClackSaltLowBinarySensor(ClackDeviceEntity, BinarySensorEntity):
    """Salt model warning: tracked level below kg or N-regenerations threshold.

    is_on mirrors SaltModel.is_low; None (level unknown — salt was never
    added, state not restored) reports as `unknown`, not a false alarm.
    Clears automatically once the Salt-added button raises the level.
    """

    def __init__(self, device) -> None:
        super().__init__(
            device,
            BinarySensorEntityDescription(
                key="needs_salt",
                translation_key="needs_salt",
                device_class=BinarySensorDeviceClass.PROBLEM,
            ),
        )

    @property
    def available(self) -> bool:
        # known as soon as the model has any level, device offline or not
        return (super().available
                or self.device.salt.level_kg is not None)

    @property
    def is_on(self) -> bool | None:
        return self.device.salt.is_low
