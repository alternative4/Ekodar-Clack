# Clack Ekodar — Home Assistant integration (local MQTT)

Home Assistant custom integration for **Clack EM.S** control valves fitted with
the **Ekodar Wi-Fi board** (Avnet **AES-BCM4343W-M1-G** module, firmware
`Version 0.24 for EK`), reconfigured to talk to a **local MQTT broker** — no
`online.ekodar.ru` cloud, no internet required.

> ⚠️ Not affiliated with Clack Corporation or Ekodar/Ekodar. Reverse-engineered
> for interoperability; use at your own risk. **Never** send
> `{"command":113,"level":1}` (factory reset) — see
> [Safety](#safety-what-not-to-send).

---

## Why

The valve is fully autonomous — the Wi-Fi board only reports telemetry and
accepts remote commands through Ekodar's cloud. The cloud service
(`online.ekodar.ru`) was shut down, which leaves the board in a permanent
reconnect loop (visible as endless `wiced_mqtt_connect 7014` on the debug
console and roughly 130 MB/month of pointless retransmits). The firmware
**TLS-pins** the cloud CA, so a DNS-hijack / MITM approach fails by design: the
device validates the peer certificate against a root CA stored in its DCT flash
and aborts the handshake otherwise.

The board does, however, ship a **captive configuration portal** that lets you
point it at an arbitrary MQTT broker — including an unencrypted local one. This
integration is the Home Assistant side of that setup.

## How it works

Once pointed at your broker, the firmware behaves as a plain MQTT client:

* **publishes** status JSON to `<prefix>/<SN>` every ~30 s,
* **subscribes** to `<prefix>/<SN>/deviceControl` (QoS 2) and executes JSON
  commands received there.

The integration needs no custom protocol code beyond the standard Home Assistant
**MQTT** integration (pointed at the same broker): it subscribes to the status
topic, caches the payloads, and periodically polls configuration sections.

### Entities created per device

| Entity | Source |
|---|---|
| `flow` — water flow, л/мин (L/min) | status `command=100` |
| `capacity_remaining` (L), `capacity_percent`, `capacity_max` | status `command=100` |
| `days_to_regeneration` | status `command=100` |
| `wifi_signal` (dBm) | status `command=100` |
| `regenerating` (binary, `running`) | `command=110` |
| `regeneration_phase`, `regeneration_position`, `regeneration_time_left`, `regeneration_stage_time_left` | `command=110` |
| `water_hardness` (mg-экв/л), `scheduled_regen_time`, `regen_days`, `regen_stages`, `valve_clock` | settings sections (read-only) |
| `sync_time` (button) | `{"command":208,...}` |
| `reboot_module` (button) | `{"command":113,"level":0}` |

The "start regeneration" command (`{"command":111}`) is deliberately **not**
exposed as a UI button — trigger it from an automation if you want it.

## Reconfiguring the board (one-time)

The board enters setup mode when its stored configuration is empty — no
hardware button, no soldering, no firmware reading.

1. **Enter configuration mode** on the valve's control panel: press and hold
   **`TIME` + `DOWN`** together. The board drops off your Wi-Fi network and
   starts its own access point.
2. **Connect to that AP.** Its **SSID is the device's serial number**, which is
   the board's MAC address written as 12 uppercase hex digits (also printed on
   the sticker of the module). The AP password is the vendor default documented
   by Ekodar for this board family (`12345678`).
3. Open **`http://192.168.0.1/config/device_settings.html`** — plain HTTP on the
   AP's gateway address. The page asks for a **service password**; it is
   `Ekodar` (capital `E`, hardcoded client-side check in the page's JS).
4. Fill the broker form:
   * **Selected Broker Type:** `MQTT Broker` (not `AWS IoT`)
   * **Broker:** your MQTT broker's IP or hostname
   * **Port Number:** `1883`
   * **Topic:** `OE/171` (the prefix; the device appends `/<SN>` itself)
   * **User Name / User Password:** **leave empty** (see gotcha below)
   * **Use Secure Connection:** **unchecked**
   * Store / Customer e-mail fields may stay empty
   Press **Save Settings**.
5. **Leave configuration mode** (page's Wi-Fi Setup/exit, or simply power-cycle
   the valve). The board joins your Wi-Fi and connects to the broker.

You can verify the wiring without touching Home Assistant: `mosquitto_sub -t
'<prefix>/#' -v` should show a `command:100` JSON within ~30 seconds.

### Gotchas (read before wasting an evening)

1. **The MQTT password is sent as `MD5(password)`** — not verbatim.
   Verified on the wire: the CONNECT packet carried `15dc050d…` (32 hex chars)
   while the portal stored the plaintext value, and
   `md5(<plaintext>)` matched byte for byte. Consequences:
   * An **authenticated** client can only connect if the broker stores the
     **MD5 hex string as the literal password** (e.g.
     `mosquitto_passwd -b pwfile <user> <md5-of-portal-password>`), **or**
   * you leave **username and password empty** in the portal, and the device
     connects **anonymously** — this is the recommended path for a trusted LAN
     and the one this integration assumes.
   With a broker that has `allow_anonymous true` **and** a non-empty
   `password_file`, an authenticated-but-unknown user is rejected with
   `not authorised`, while anonymous clients sail through — easy to mistake for
   a wrong password.
2. **Plain MQTT only.** `Use Secure Connection` requires uploading your own CA
   through the portal's third upload control; the factory-pinned Ekodar CA will
   not validate your broker. Anonymity on a trusted LAN is simpler.
3. **TLS/CA pinning kills MITM attempts.** Do not try to intercept the original
   cloud traffic — the device aborts right after `Certificate` even for a valid
   public chain.
4. **Commands are slow.** The board answers section reads within ~1 s, but the
   portal disables buttons for 30 s after a command — the firmware is not built
   for bursts. Do not poll sections more often than once a few minutes.
5. **Settings reset on reboot?** No — the portal config lives in DCT flash and
   survives power cycles. But a reboot does re-join Wi-Fi, so expect a ~20–30 s
   gap in telemetry after power loss.
6. **The debug console is your friend.** Solder two wires to the `DEBUG` header
   (rows `TX / GND / RX`, **115200 8N1**, listen-only, common ground) and the
   board prints its whole boot/connect sequence, including `Thing Name`,
   `Topic`, resolved broker IP and TLS errors. `COMM` is the board↔valve line
   (binary protocol, not text — don't expect logs there).

## Protocol reference

All payloads are JSON on `<prefix>/<SN>` (uplink) and `<prefix>/<SN>/deviceControl`
(downlink). Codes recovered from the archived Ekodar cabinet bundle
(`mqttapp.js`, Wayback snapshot of `online.ekodar.ru`, 2022) and confirmed
against a live device.

### Uplink (device → broker)

| `command` | meaning | fields |
|---|---|---|
| `100` | idle status (~every 30 s) | `current-flow`, `cap-max`, `cap-remain`, `rssi`, `day-remain` |
| `110` | regeneration status (emitted alternately with `100` while a cycle runs) | `cycles`, `total-time`, `total-remain`, `current-cycle`, `cycle-time`, `repeat-num`, `dissolve` |
| `2NN` | answer to a section request | section payload, see below |

Notes on `110`: `total-time`/`total-remain`/`cycle-time` are **seconds**;
`current-cycle` is the **piston position code** (values seen: 1, 3, 7, 9, 13,
14), **not** an index into the stage list; `dissolve` carries the current stage
name (observed `Softening` for every cycle).

### Section read (downlink → answer)

Request `{"command":200,"section":N}`; device answers with `command=N`.

| section | key | contents |
|---|---|---|
| `201` | `Installer-Settings` | `Water Hardness` (×10), `Day Override`, `Regen Time-Hour/Minute`, `Regen Day{Mon..Sun}`, `Service Alarm*`, `Contact Name/Number`, `Valve Family`, `System Units`, `Language` |
| `202` | `Service-Settings` | `Type`, `Grains Capacity`, `Capacity`, `Day Override Type` |
| `203` | `Configuration-Settings` | `Valve Type`, `Meter 1 Size`, `Proportional Mode`, `Regen Type`, `Hardness Units`, `Relay 1/2 Mode/Setpoint/Duration`, auxiliary/MAV modes |
| `206` | `Regen-Settings` | `Regen Cycles[]` — ordered stages `{Cycle, Time(min)}`, `Open` = unused slot |
| `208` | `Time-Settings` | `Valve Hour`, `Valve Minute`, `Valve Day` |

### Commands (downlink)

| `command` | payload | effect |
|---|---|---|
| `111` | — | start regeneration / advance to next stage |
| `112` | `Interval_100`, `Count_100` | change how often status `100` is published |
| `113` | `level:0` | reboot **Wi-Fi board only** |
| `114` | `Service Alarm: 0|1` | clear the time/volume service reminder |
| `201` | e.g. `Water Hardness` (×10), `Day Override`, `Regen Time-Hour/Minute`, `Regen Day{}` | write installer settings |
| `202` | `Grains Capacity` | write exchange capacity |
| `203` | `Relay N Mode/Setpoint/Duration` | write relay outputs |
| `206` | `Regen Cycles[]` | rewrite the regeneration stage sequence |
| `208` | `Valve Hour`, `Valve Minute`, `Valve Day` | set the valve clock |
| `210` | `Lock: 0|1` | lock / unlock the front-panel buttons |

### Safety: what **not** to send

* `{"command":113,"level":1}` — **factory reset** of the valve (this is what the
  cabinet's "reset to factory" button does). Not exposed anywhere in this
  integration.
* `{"command":206,...}` with a wrong `Regen Cycles` array — the valve will run a
  malformed regeneration: no backwash, no brine, or brine at the wrong time.
  Read-only in this integration.
* `{"command":202,"Grains Capacity":...}` / `201` `Water Hardness` — changes when
  the valve decides to regenerate; a wrong value can leave you with hard water or
  waste salt. Read-only in this integration.
* `{"command":111}` — starts a real regeneration: ~2–4 h, water softening is
  offline, and it consumes salt. Not wired to the UI.

## Installation

### HACS

1. HACS → Integrations → **⋮** → *Custom repositories*.
2. Add this repository URL, category **Integration**.
3. Install **"Clack Ekodar (local MQTT)"**, restart Home Assistant.

### Manual

Copy `custom_components/clack_ekodar/` into `<config>/custom_components/`,
restart Home Assistant.

### Add the device

Settings → Devices & Services → Add Integration → **Clack Ekodar (local MQTT)**:

* **MAC** — the board's serial: 12 hex characters, no separators (same value as
  the AP SSID). Also on the module's barcode sticker.
* **Prefix** — topic prefix, default `OE/171`.
* **Section poll interval** — minutes, default 60.

The Home Assistant core **MQTT** integration must already be configured against
the same broker.

## Requirements

* Home Assistant ≥ 2024.1 (uses `hass.data`/config-entry options and MQTT
  `async_publish`; tested on 2026.9).
* MQTT integration configured, broker reachable from Home Assistant.
* Board reconfigured to that broker, anonymous access (see above).

## Development notes

* Status handling lives in `__init__.py::ClackDevice._on_message`; entities
  subscribe to per-device change callbacks, so there is no polling per entity.
* Device availability = "status seen within 120 s" (two missed reports).
* `translation_key` fields map into `strings.json` / `translations/` for
  localized entity names.
* Verified end-to-end against a real EM.S valve through a full 8-stage
  regeneration cycle (log: `command=110` positions 1 → 13 → 7 → 3 → 9 → 14,
  `total-remain` counting 13066 → 0, `cap-remain` restored after completion).

## License

MIT
