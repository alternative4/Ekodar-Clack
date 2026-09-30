"""The Clack Ekodar (local MQTT) integration.

Works with a Clack EM.S softener valve carrying the Ekodar Wi-Fi board
(Broadcom BCM4343W / WICED) reconfigured to publish to a local MQTT broker.

Protocol (reverse-engineered from the archived online.ekodar.ru cabinet,
mqttapp.js, and live captures; reference also in const.py):
  device -> broker  {prefix}/{mac}  (~every 30s)
      command=100 idle: current-flow, cap-max, cap-remain, rssi, day-remain
      command=110 during regeneration: cycles, total-time, total-remain,
          current-cycle, cycle-time, repeat-num, dissolve
      command=2NN answers to section requests
  broker -> device  {prefix}/{mac}/deviceControl  (QoS1 JSON)
      {"command":200,"section":N}   read settings section
      {"command":208,...}           set valve time / day
      {"command":201,...}           set installer settings
      {"command":111}               start regeneration (DANGER, hidden default)
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import timedelta

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import Platform
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import (
    CONF_MAC,
    CONF_PREFIX,
    CONF_SECTION_INTERVAL,
    CONTROL_TOPIC_SUFFIX,
    DEFAULT_PREFIX,
    DEFAULT_SECTION_INTERVAL_MIN,
    DOMAIN,
    SECTION_CODES,
)
from .salt import RegenTracker, SaltConfig, SaltModel

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]


class ClackDevice:
    """State + MQTT plumbing for one Clack valve."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.mac: str = entry.data[CONF_MAC].upper()
        prefix = entry.data.get(CONF_PREFIX) or DEFAULT_PREFIX
        self.status_topic = f"{prefix}/{self.mac}"
        self.control_topic = self.status_topic + CONTROL_TOPIC_SUFFIX
        self.section_interval = int(
            entry.options.get(CONF_SECTION_INTERVAL,
                              entry.data.get(CONF_SECTION_INTERVAL,
                                             DEFAULT_SECTION_INTERVAL_MIN))
        )
        self.status: dict = {}
        self.regen: dict | None = None
        self.sections: dict[int, dict] = {}
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        # salt accounting
        self.salt_config = SaltConfig.from_mapping(entry.options)
        self.salt = SaltModel(self.salt_config)
        self.regen_tracker = RegenTracker()
        self._salt_store = Store(hass, 1, f"{DOMAIN}_salt_{self.mac}")
        self._salt_dirty = False

    # ----- salt -----

    async def load_salt(self) -> None:
        data = await self._salt_store.async_load()
        self.salt.load_state(data)
        if isinstance(data, dict):
            _LOGGER.debug("clack %s: salt state restored (%s kg)",
                          self.mac, self.salt.level_kg)

    async def save_salt(self) -> None:
        """Persist salt state if dirty (debounced by caller cadence)."""
        if not self._salt_dirty:
            return
        self._salt_dirty = False
        await self._salt_store.async_save(self.salt.to_dict())

    async def salt_changed(self) -> None:
        """Public hook after any salt-state mutation: persist + refresh."""
        self._salt_dirty = True
        await self.save_salt()
        self._notify()

    # ----- pub/sub -----

    def subscribe_update(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def _unsub() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _unsub

    def _notify(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("clack listener failed")

    async def start(self) -> None:
        self._unsubs.append(
            await mqtt.async_subscribe(self.hass, self.status_topic,
                                       self._on_message, qos=0)
        )
        self._unsubs.append(
            await mqtt.async_subscribe(self.hass, self.control_topic,
                                       self._on_message, qos=0)
        )

    async def stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()

    @callback
    def _on_message(self, msg: mqtt.Message) -> None:
        raw = msg.payload
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict):
            return
        code = data.get("command")
        if not isinstance(code, int):
            return
        import time
        ts = time.time()
        data["_seen"] = ts
        # completed-regeneration edge for salt accounting
        if self.regen_tracker.on_message(code, ts):
            if self.salt.on_regeneration(ts):
                self._salt_dirty = True
                self.hass.async_create_task(self.save_salt())
            self._notify()
        changed = True
        if code == 100:
            self.status = data
            self.regen = None
        elif code == 110:
            self.regen = data
        elif 200 <= code < 300:
            # section answers wrap the payload under a name, e.g.
            # {"command":201,"Installer-Settings":{...}} — getters read the
            # inner dict, so unwrap it (keep the frame if no dict value)
            inner = next((v for k, v in data.items()
                          if k not in ("command", "_seen")
                          and isinstance(v, dict)), None)
            self.sections[code] = inner if inner is not None else data
        else:
            changed = False
        if changed:
            self._notify()

    async def command(self, payload: dict) -> None:
        await mqtt.async_publish(
            self.hass, self.control_topic,
            json.dumps(payload, separators=(",", ":")), qos=1)

    async def fetch_sections(self, *_now) -> None:
        for section in SECTION_CODES:
            await self.command({"command": 200, "section": section})
            await asyncio.sleep(0.4)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    device = ClackDevice(hass, entry)
    await device.load_salt()
    await device.start()

    entry.async_on_unload(
        async_track_time_interval(
            hass, device.fetch_sections,
            timedelta(minutes=max(1, device.section_interval)))
    )
    entry.async_on_unload(
        async_track_time_interval(hass, lambda *_: hass.async_create_task(
            device.save_salt()), timedelta(minutes=10))
    )

    async def _stop() -> None:
        await device.save_salt()
        await device.stop()

    entry.async_on_unload(_stop)
    entry.async_on_unload(entry.add_update_listener(_reload))

    hass.async_create_task(device.fetch_sections())

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = device
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    device = hass.data[DOMAIN].pop(entry.entry_id, None)
    if device:
        await device.stop()
    return True
