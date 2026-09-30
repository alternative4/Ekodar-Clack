# Changelog

All notable changes to this integration are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
The version in `custom_components/clack_ekodar/manifest.json` is the source of
truth; every release is tagged `vX.Y.Z` in git.

## [0.3.0] - 2026-09-30

### Added
- `fetch_settings` button: on-demand re-read of all settings sections
  (`{"command":200,"section":N}`). The valve never pushes settings, so after
  an HA restart the settings sensors sat `unknown` until the next periodic
  poll (default 30 min); the button refreshes them in ~2 s.
- Auto-fetch settings on the first `command=100` frame after integration
  startup when no section data is cached yet — fixes the same post-restart
  `unknown` gap without user action (the setup-time fetch can run before the
  MQTT broker reconnects).

## [0.2.5] - 2026-09-30

### Fixed
- Settings sensors (`water_hardness`, `scheduled_regen_time`, `valve_clock`,
  `regeneration_days`, `regeneration_stages`) never populated: section answers
  arrive wrapped (`{"command":201,"Installer-Settings":{...}}`) but were stored
  verbatim, so getters read an empty top level. The wrapper is now unwrapped
  before storing (bug present since 0.1.0).

## [0.2.4] - 2026-09-30

### Fixed
- Home Assistant 2026.9 rejects `EntityCategory.CONFIG` on sensor entities
  (`cannot be added as the entity category is set to config`), which silently
  dropped the five settings sensors after a restart. They use `DIAGNOSTIC` now.

### Added
- README: computing the salt dose from valve capacity/hardness (worked example)
  and the additive behavior of the *Salt added* button.

## [0.2.3] - 2026-09-30

### Fixed
- "Configure" dialog returned HTTP 500 on HA ≥ 2026: `OptionsFlow` subclasses
  are no longer constructed with the config entry as an argument.

## [0.2.2] - 2026-09-30

### Fixed
- Platform import crash on HA 2026.9 (`SensorDeviceClass` has no `MASS`): the
  salt-level sensor uses `SensorDeviceClass.WEIGHT`. This crash had broken the
  whole integration setup, not just sensors.

## [0.2.1] - 2026-09-17

### Added
- `salt_status` enum sensor (`ok`/`low`/`no_data`/`incomplete`) with localized
  human recommendations and machine-readable attributes.
- Deferred warning (`incomplete`) when per-regeneration consumption cannot be
  derived, instead of a false "low" alarm.
- Example `persistent_notification` automation (`docs/salt-alert-automation.yaml`).

## [0.2.0] - 2026-09-17

### Added
- Salt usage tracking (tasks on the HA side of the Ekodar migration):
  `SaltModel` + `RegenTracker` (`salt.py`), *Salt added* button,
  `salt_level` / regenerations-left sensors, low-salt binary sensor,
  six salt options in the config-entry options flow, ru/en strings,
  unit tests, `docs/salt-usage.md` methodology.
- Salt entities stay available while the valve is offline; the button is
  visible on the device page.

## [0.1.2] - 2026-09-17

### Fixed
- Custom `EntityDescription` dataclass broke adding every sensor
  (`AttributeError: suggested_unit_of_measurement` on HA 2026.x) — replaced
  with built-in descriptions.
- `entry.async_on_unload` received a coroutine-returning lambda, breaking
  entry reload — registered an `async def` wrapper instead.

## [0.1.1] - 2026-09-17

### Added
- Russian and English localized entity/config strings via `translation_key`.

## [0.1.0] - 2026-09-17

### Added
- Initial release: Clack EM.S valve with the Ekodar Wi-Fi board (BCM4343W /
  WICED) on a **local MQTT** broker — no `online.ekodar.ru` cloud.
  Status/regeneration telemetry, settings-section read-only sensors,
  time-sync and Wi-Fi reboot buttons, section polling config flow,
  HACS-compatible repository layout.
