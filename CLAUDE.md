# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Home Assistant custom integration for E-Bikes using the Mahle SmartBike BLE protocol (X25, X35+, ebikemotion — Schindelhauer, Orbea, Bianchi, Pinarello, Scott, etc.). Distributed via HACS. Device names start with `iWoc*` or `HUS*`. Domain: `mysmartbike_ble`.

## Commands

Tests use `pytest_homeassistant_custom_component`, which requires a real Home Assistant install:

```bash
pip install -r requirements_test.txt
pytest                                                    # all tests
pytest tests/components/mysmartbike_ble/test_parsers.py   # one file
pytest tests/components/mysmartbike_ble/test_parsers.py::test_parse_battery_message_primary  # one test
pytest --cov=custom_components.mysmartbike_ble            # coverage
```

There is no lint/build step. CI runs HACS validation and `hassfest` (`.github/workflows/`).

`manifest.json` `version` is rewritten at release time from the git tag by `.github/workflows/publish.yaml`, which then zips `custom_components/mysmartbike_ble/` and attaches it to the GitHub release. Don't bump the version by hand for releases — create a tag.

## Architecture

Single-device integration. One config entry == one bike. The `DataUpdateCoordinator` owns the BLE client and a stateful parser; entities are thin views over `coordinator.data`.

**Layers:**
- `__init__.py` — `async_setup_entry` **never** depends on the bike being reachable. It constructs the coordinator from the address alone, `await`s `coordinator.async_restore()` *before* forwarding the platforms (so entities' first state write already carries restored values and the VIN), registers the advertisement watch via `entry.async_on_unload`, and kicks off the first connect as a background task. There is no `ConfigEntryNotReady` and no `hass.data[DOMAIN][entry_id]`. `async_remove_entry` deletes the `Store`.
- `coordinator.py` — `MySmartBikeCoordinator` is built from an *address*, not a `BLEDevice`; `_resolve_device()` re-resolves per connect attempt so a stale device object from an old adapter/proxy can't linger. It polls every `SCAN_INTERVAL` (30s), auto-reconnecting unless `_manual_disconnect` is set, and returns the parser's accumulated `state` plus a fresh `rssi` and `last_seen`. `_async_update_data` deliberately never raises: an unreachable bike must not flip `last_update_success`, which would mark every entity `unavailable` and throw the restored state away. Real data flow is push-based: `_notification_handler` runs on every BLE notification, parses, stamps `last_seen`, queues a debounced save, and calls `async_set_updated_data` to wake entities immediately. `_connect` is serialised by `_connect_lock` because both the poll tick and the Bluetooth callback can enter it, and it holds the client in a *local* through the 200ms VIN/protocol handshake — a concurrent teardown clearing `self._client` mid-handshake would otherwise crash it. `establish_connection` gets a `disconnected_callback` so a dropped link flips `_is_connected` immediately; without it the coordinator would believe it was still connected and never retry.
- `parsers.py` — `BikeDataParser` is a pure, stateful message decoder. It dispatches via `recognize_message_type` (sniffs the `$X$Y#...#@` framing) and accumulates into `state` (`battery_primary`, `battery_secondary`, `motor`, `assist`, `ebm`) plus `vin` / `protocol_version`. Broadcast frames are decoded with the layout the bike's protocol version calls for (see below). `protocol_version` is a property whose setter re-derives `protocol`, so restoring the persisted string picks the right layouts before the first packet arrives. All multibyte reads are big-endian. Secondary-battery presence is inferred: a `battery_number == 2` packet sets it; 4 consecutive primary packets clear it.
- `config_flow.py` — Two entry paths: BLE auto-discovery (`async_step_bluetooth`) and manual user step that filters `async_discovered_service_info` for names starting with `iWoc` or `HUS`. Unique ID is the BLE address. Options flow exposes `CONF_LOG_BLE_MESSAGES` only.
- `binary_sensor.py` / `sensor.py` / `switch.py` — `CoordinatorEntity` subclasses. Sensors use a `MySmartBikeSensorEntityDescription` dataclass with a `value_fn` lambda that pulls from `coordinator.data` via the `safe_get` helper (data dicts can be `None` before first packet). All entities share one device (identified by `(DOMAIN, entry.entry_id)`); `serial_number` and `sw_version` come from the parser's `vin` / `protocol_version`, which `async_restore()` has already populated by construction time. Every entity overrides `available` to `True` — the values are last-known-good, and liveness is reported by `binary_sensor.connected` and the `last_seen` timestamp sensor instead.

**BLE protocol specifics (in `const.py`):**
- Write characteristic `0000FFE2-…`, notify characteristic `0000FFD1-…`.
- ASCII command framing: `$S$V#@` (request VIN), `$S$P#@` (request protocol), `$D$I#@` (sent as `CLOSE_MESSAGE`). On connect, the coordinator sends VIN then protocol requests with a 200ms gap. Note that `$D$I#@` is `DiagnosisInitRequestCmd` in the Mahle SDK — it *starts* a diagnosis session, and the SDK's counterpart is `$D$E#@`. The bike powering off ~5 min after a disconnect is most likely its idle timeout rather than an effect of this write; unverified.
- `recognize_message_type` also knows frames the newer protocols added, so they are logged instead of being fed to a broadcast parser: `$b$P` / `$b$R` (power source, v102 — they share the `b` type with the battery broadcast), `$f$C` / `$f$D` (Trio remote pairing), `$m$G` (traction control / auto hold, v200), `$s$L` (blinking lights, v102).
- `bleak_retry_connector.establish_connection` is used instead of raw `BleakClient` — it handles slot contention with proxies (EsphomeBT). Shelly proxies are unsupported (no active connections).

### Frame layouts — selected by protocol version, not by length

The bike answers `$S$P#@` with one of `EBM`, `100`, `102`, `200`, `300` (some firmwares dot it: `1.02`). `normalize_protocol_version` folds both spellings onto the bare id and `BikeDataParser.protocol` exposes it; `protocol_version` keeps the raw string because that is the device's `sw_version`.

**Length does not identify a layout.** Protocols 100, 102, 200 and 300 all broadcast 20-byte battery, motor and EBM frames and read some of those bytes differently, so the version picks the layout and the length only separates the short ebikemotion frames (X25 / X35+, `iWoc*`) from the 20-byte ones. Where the version is unknown — the first notifications can beat the `$S$P#@` answer by a few hundred ms — the 100/102/300 layouts apply. Verified against the decompiled Mahle SDK (`com/mahle/protocol/{ebm,mahle/v1xx,mahle/v2xx,mahle/v3xx}/parser/broadcast/`). All multi-byte fields are big-endian.

**v300 is byte-for-byte identical to v102** for all three broadcast frames — `BatteryParserV300`, `MotorParserV300` and `EbmParserV300` are line-for-line copies of their v102 counterparts. There is no separate v300 code path here, and adding one would be dead weight.

**Battery — `$b$Z#…#@`** (`_parse_battery_ebm` / `_parse_battery_mahle` / `_parse_battery_v200`)

| Offset | EBM / X35 (≥17 B) | 100 / 102 / 300 (20 B) | 200 (20 B) |
|---|---|---|---|
| 5-6 | voltage `read16 / 10` | voltage `read16 / 100` | same as 102 |
| 7 | SOC unsigned byte | SOC unsigned byte, **read whole** | bit 7 = `is_charging`, bits 0-6 = SOC % |
| 8 | temperature **signed** byte | temperature signed byte | same as 102 |
| 9-10 | current `read16 / 10` — the one layout that reads it **unsigned** | current **signed** `read16 / 10` | same as 102 |
| 11-12 | nominal_capacity `read16 / 10` | same | same |
| 13-14 | remaining_wh `read16 / 10` | same | same |
| 15 | combined cycles MSB | **MOSFET temperature** signed byte | same as 102 |
| 16 (-17) | combined `(batt# * 10000) + cycles` at 15-16 | combined at 16-17 | same as 102 |

`is_charging` exists **only on v200**, and only for the primary pack — the SDK hardcodes it false everywhere else, including v300. Do not mask bit 7 out of the SOC byte on the other protocols.

`battery_number == 0` means different things per protocol. On v200 it is an auxiliary/DCDC current reading (`BP_aux_current`), not a pack: `_parse_battery_v200` drops it, because `_store_battery` treats anything that is not an explicit `2` as primary and those frames would otherwise overwrite the real battery. Everywhere else `0` keeps falling through to the primary slot on purpose — single-battery bikes whose firmware leaves the field at zero would otherwise have every battery sensor stuck on `unknown`. (The SDK discards `0` on every protocol; this leniency is a deliberate deviation.)

**Motor — `$m$Z#…#@`** (`_parse_motor_ebm` / `_parse_motor_v100` / `_parse_motor_mahle`)

| Offset | EBM / X35 (≥18 B) | 100 (20 B) | 102 / 200 / 300 (20 B) |
|---|---|---|---|
| 5 | assist_level (signed byte) | signed byte | signed byte |
| 6 | temperature_celsius **signed**; `0xD8` = -40 °C is the "no sensor data" sentinel during the first packets after connect | signed | signed, same sentinel |
| 7-8 | power_amp `read16 / 10` | **power_amp `read16 / 10`** | motor_power_watts `read16 / 100` |
| 9-10 | speed_kmh `read16 / 10` | same | same |
| 11 | wheel_speed_rpm, always valid | wheel_speed_rpm, **always valid** | only valid when `max_torque != 0` |
| 12 | torque_motor_pct (signed byte) | — | — |
| 12-13 | — | **torque_motor_pct** = signed `read16 / 100`, truncated toward zero | rider_power_watts `read16 / 10` |
| 13-14 | power_max `read16 / 10` | — | — |
| 14-15 | — | power_max_amp `read16 / 10` | power_max_amp `read16 / 10` |
| 15 | max_torque_motor_pct (signed byte) | — | — |
| 16-17 | — | max_torque raw `read16` | max_torque raw `read16` (also the wheel-speed validity flag) |

Every byte-sized field in the ebikemotion frame is signed in the SDK. The v100 frame shares its length with 102/200/300 but not its meaning: read with the newer layout, 15 A of motor current becomes 1.5 W of motor power. Each layout fills the keys it does not carry with `None` so the `safe_get` paths in `sensor.py` keep working.

**EBM — `$j$Z#…#@`** (`_parse_ebm_ebm` / `_parse_ebm_mahle` / `_parse_ebm_v200`)

| Offset | EBM / X35 (≥17 B) | 100 / 102 / 300 (20 B) | 200 (20 B) |
|---|---|---|---|
| 5-7 | (part of odometer) | odometer `read24 / 10` (km) | odometer `read24 / 10` (km) |
| 5-8 | odometer `read32 / 10000` (km) | — | — |
| 8-9 | (part of autonomy) | autonomy `read16 / 10` (km) | autonomy `read16 / 10` (km) |
| 9-12 | autonomy `read32 / 10000` (km) | — | — |
| 10 | — | lights `byte == 1` | lights `byte == 1` |
| 11 | — | status = error id (unsigned byte) | **error id = `byte & 0x1F`** |
| 12 | — | accelerometer Z (signed byte) | **device id = `byte & 0x0F`, flags = `byte >> 4`** |
| 13 | lights `byte == 1` | accelerometer Y (signed byte) | accelerometer **Z** (signed byte) |
| 14 | status (unsigned byte) | **slot indicator** | accelerometer **Y** (signed byte) |
| 15 | — | `'H'` | **slot indicator** |
| 16-17 | — | `'I' 'J'` | remote: `0xFFFF` = none, else SOC = byte 17 |

The slot indicator alternates between consecutive frames: `2` = trip A, anything else = lifetime. Both sets are kept — `state["ebm"]["odometry"]` / `["autonomy"]` hold the lifetime values, `["trip_odometry"]` / `["trip_autonomy"]` mirror trip A. When the bike has not had trip A reset since manufacture they coincide.

`_ebm_frame_is_v200` prefers the reported version and falls back to the fixed `HIJ` (`0x48 0x49 0x4A`) marker at bytes 15-17, which v200 cannot have because it spends those bytes on the slot and remote SOC. Guessing wrong reads the slot off an accelerometer axis and shuffles lifetime and trip readings into each other, so the sniff is worth its one byte comparison on the packets that arrive before the handshake completes.

`error_code` is the number the app shows: the device's base offset plus the error id (`MPLATFORM_DEVICE_BASE_CODES` — drive unit 0, head unit 100, internal battery 200, external battery 300, charger 400, bike radar 500), so `204` is fault 4 on the internal battery. Only v200 attaches a device; elsewhere `error_code == status`.

### Restore across restarts

`helpers.storage.Store` (key `mysmartbike_ble.<entry_id>`, `STORAGE_VERSION`) persists the parser state so a bike that is off or out of range still shows its last values. `_schedule_save()` uses `Store.async_delay_save(..., STORAGE_SAVE_DELAY)` — BLE notifications arrive far too often for eager writes; `Store` flushes on HA shutdown, and `async_shutdown` does an explicit `async_save` so an unload can't lose state.

`coordinator.data` **is** `self._parser.state` (same object identity, see `_async_update_data` and `_notification_handler`), so restoring means seeding the parser dict — every `value_fn` then works unchanged with no per-entity restore code. It also seeds the `prev` lookup in `_ebm_slot_values`, which carries lifetime/trip values across the slot alternation.

What is restored is a deliberate whitelist in `const.py`:
- `RESTORE_STATE_KEYS` = `battery_primary`, `battery_secondary`, `ebm`. **`motor` and `assist` are excluded on purpose** — a restored speed or motor power reading is indistinguishable from live data on a parked bike, which is worse than `unknown`.
- `VOLATILE_FIELDS` nulls individual fields inside the restored dicts: battery `current` / `is_charging`, and `ebm` `status` / `error_code` / `accel_y` / `accel_z` / `remote_connected` / `remote_soc`.
- `vin`, `protocol_version`, `last_seen` and `manual_disconnect` are stored alongside. Restoring `protocol_version` is what lets the parser decode the first packet after a restart with the right layout instead of the default one; restoring `manual_disconnect` is what stops a Home Assistant restart from waking a bike the user deliberately disconnected.

When adding a sensor, decide which bucket its source field belongs to before wiring the `value_fn`.

**Instant reconnect:** `async_start_bluetooth_watch()` registers a `bluetooth.async_register_callback` on the address, so the coordinator connects the moment the bike advertises rather than up to 30s later. The callback must keep honouring `_manual_disconnect`.

**Disconnect semantics matter:** turning the connection switch off sends `CLOSE_MESSAGE` and the bike powers itself off ~5 minutes later. `_manual_disconnect` gates auto-reconnect so the coordinator doesn't wake the bike again. Reconnecting requires the user to physically power the bike on first. Preserve this gating when touching the coordinator.

**Optional BLE message logging:** when the `log_ble_messages` option is set, every notification is appended to `custom_components/mysmartbike_ble/messages/<device>_<YYYYMMDD>_ble_messages.log` via an executor job (file I/O off the event loop). The `messages/` directory is gitignored implicitly via standard patterns; do not commit captures.

## Tests

`tests/conftest.py` enables custom integrations globally. `tests/components/mysmartbike_ble/conftest.py` provides:
- `mock_config_entry` — `MockConfigEntry` with a fixed address `AA:BB:CC:DD:EE:FF`.
- `mock_bleak_client` — patches `establish_connection` in the coordinator module (not `bleak` itself).
- `mock_bluetooth_helpers` (autouse) — stubs `async_register_callback` / `async_last_service_info` in the coordinator module.
- `mock_device_in_range` / `mock_device_out_of_range` — control what `async_ble_device_from_address` returns in both `coordinator` and `__init__`.
- `init_integration` / `init_integration_offline` — full setup with the bike reachable or not.

`test_restore.py` seeds `.storage` through the `hass_storage` fixture (key `mysmartbike_ble.<entry_id>`) and covers the offline-setup, whitelist, device-info and manual-disconnect paths.

Parser tests in `test_parsers.py` exercise raw byte sequences directly — the cleanest place to add coverage for new message types.
