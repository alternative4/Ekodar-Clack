"""Sensors for the Clack Ekodar integration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE  # noqa: F401
from homeassistant.const import EntityCategory, UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SECTION_INSTALLER, SECTION_REGEN, SECTION_TIME
from .entity import ClackDeviceEntity


@dataclass(frozen=True)
class Spec:
    key: str
    name: str
    source: str  # "status" | "regen" | "fn"
    path: tuple  # keys inside the source dict (for status/regen)
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    category: EntityCategory | None = None


SPECS: tuple[Spec, ...] = (
    Spec("flow", "Water flow", "status", ("current-flow",), "л/мин",
         state_class=SensorStateClass.MEASUREMENT),
    Spec("capacity_remaining", "Capacity remaining", "status", ("cap-remain",),
         UnitOfVolume.LITERS, SensorDeviceClass.WATER, SensorStateClass.TOTAL),
    Spec("capacity_max", "Capacity max", "status", ("cap-max",),
         UnitOfVolume.LITERS, SensorDeviceClass.WATER,
         category=EntityCategory.DIAGNOSTIC),
    Spec("days_to_regeneration", "Days until regeneration", "status",
         ("day-remain",), UnitOfTime.DAYS, SensorDeviceClass.DURATION),
    Spec("wifi_signal", "Wi-Fi signal", "status", ("rssi",), "dBm",
         SensorDeviceClass.SIGNAL_STRENGTH, SensorStateClass.MEASUREMENT,
         EntityCategory.DIAGNOSTIC),
    Spec("regeneration_phase", "Regeneration phase", "regen", ("dissolve",)),
    Spec("regeneration_position", "Regeneration position", "regen",
         ("current-cycle",), category=EntityCategory.DIAGNOSTIC),
    Spec("regeneration_time_left", "Regeneration time left", "regen",
         ("total-remain",), UnitOfTime.SECONDS, SensorDeviceClass.DURATION,
         SensorStateClass.MEASUREMENT),
    Spec("regeneration_stage_time_left", "Current stage time left", "regen",
         ("cycle-time",), UnitOfTime.SECONDS, SensorDeviceClass.DURATION,
         SensorStateClass.MEASUREMENT, EntityCategory.DIAGNOSTIC),
    Spec("water_hardness", "Water hardness", "fn", ("hardness",),
         "mg-экв/л", category=EntityCategory.CONFIG),
    Spec("scheduled_regen_time", "Scheduled regen time", "fn", ("regen_time",),
         category=EntityCategory.CONFIG),
    Spec("valve_clock", "Valve clock", "fn", ("valve_clock",),
         category=EntityCategory.CONFIG),
    Spec("regen_days", "Regeneration days", "fn", ("regen_days",),
         category=EntityCategory.CONFIG),
    Spec("regen_stages", "Regeneration stages", "fn", ("regen_stages",),
         category=EntityCategory.CONFIG),
    Spec("capacity_percent", "Capacity remaining percent", "fn",
         ("capacity_percent",), "%", state_class=SensorStateClass.MEASUREMENT),
)


def _fn_getter(device, name: str):
    """Lambdas over sections / derived values."""
    if name == "hardness":
        raw = device.sections.get(SECTION_INSTALLER, {}).get("Water Hardness")
        return round(raw / 10, 1) if isinstance(raw, (int, float)) else None
    if name == "regen_time":
        s = device.sections.get(SECTION_INSTALLER)
        if not s:
            return None
        return "%02d:%02d" % (int(s.get("Regen Time-Hour", 0) or 0),
                              int(s.get("Regen Time-Minute", 0) or 0))
    if name == "valve_clock":
        s = device.sections.get(SECTION_TIME)
        if not s:
            return None
        return "%02d:%02d %s" % (int(s.get("Valve Hour", 0) or 0),
                                 int(s.get("Valve Minute", 0) or 0),
                                 str(s.get("Valve Day", "")))
    if name == "regen_days":
        days = device.sections.get(SECTION_INSTALLER, {}).get("Regen Day")
        if not isinstance(days, dict):
            return None
        order = ["Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday"]
        short = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        picks = [s for d, s in zip(order, short) if days.get(d)]
        return ", ".join(picks) or None
    if name == "regen_stages":
        cycles = device.sections.get(SECTION_REGEN, {}).get("Regen Cycles")
        if not cycles:
            return None
        active = [c for c in cycles
                  if c.get("Cycle") not in (None, "Open", "End")]
        return " → ".join(
            f"{c['Cycle']} {c['Time']:g}м" for c in active) or None
    if name == "capacity_percent":
        s = device.status
        try:
            return round(100 * s["cap-remain"] / s["cap-max"], 1)
        except (KeyError, TypeError, ZeroDivisionError):
            return None
    return None


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    device = hass.data[DOMAIN][entry.entry_id]

    def make_getter(spec: Spec) -> Callable:
        if spec.source == "fn":
            return lambda d: _fn_getter(d, spec.path[0])
        src = "status" if spec.source == "status" else None
        def getter(d):
            data: object = d.status if spec.source == "status" else d.regen
            if data is None:
                return None
            for k in spec.path:
                data = data.get(k) if isinstance(data, dict) else None
            return data
        return getter

    async_add_entities(
        ClackSensor(device, spec, make_getter(spec)) for spec in SPECS
    )


class ClackSensor(ClackDeviceEntity, SensorEntity):
    def __init__(self, device, spec: Spec, getter: Callable) -> None:
        desc = SensorEntityDescription(
            key=spec.key,
            translation_key=spec.key,
            entity_category=spec.category,
        )
        super().__init__(device, desc)
        self._getter = getter
        self._attr_native_unit_of_measurement = spec.unit
        if spec.device_class:
            self._attr_device_class = spec.device_class
        if spec.state_class:
            self._attr_state_class = spec.state_class

    @property
    def native_value(self):
        value = self._getter(self.device)
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
