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
- `parsers.py` — `BikeDataParser` is a pure, stateful message decoder. It dispatches via `recognize_message_type` (sniffs the `$X$Y#...#@` framing) and accumulates into `state` (`battery_primary`, `battery_secondary`, `motor`, `assist`, `ebm`) plus `vin` / `protocol_version`. All multibyte reads are big-endian. Secondary-battery presence is inferred: a `battery_number == 2` packet sets it; 4 consecutive primary packets clear it.
- `config_flow.py` — Two entry paths: BLE auto-discovery (`async_step_bluetooth`) and manual user step that filters `async_discovered_service_info` for names starting with `iWoc` or `HUS`. Unique ID is the BLE address. Options flow exposes `CONF_LOG_BLE_MESSAGES` only.
- `binary_sensor.py` / `sensor.py` / `switch.py` — `CoordinatorEntity` subclasses. Sensors use a `MySmartBikeSensorEntityDescription` dataclass with a `value_fn` lambda that pulls from `coordinator.data` via the `safe_get` helper (data dicts can be `None` before first packet). All entities share one device (identified by `(DOMAIN, entry.entry_id)`); `serial_number` and `sw_version` come from the parser's `vin` / `protocol_version`, which `async_restore()` has already populated by construction time. Every entity overrides `available` to `True` — the values are last-known-good, and liveness is reported by `binary_sensor.connected` and the `last_seen` timestamp sensor instead.

**BLE protocol specifics (in `const.py`):**
- Write characteristic `0000FFE2-…`, notify characteristic `0000FFD1-…`.
- ASCII command framing: `$S$V#@` (request VIN), `$S$P#@` (request protocol), `$D$I#@` (close/disconnect). On connect, the coordinator sends VIN then protocol requests with a 200ms gap.
- `bleak_retry_connector.establish_connection` is used instead of raw `BleakClient` — it handles slot contention with proxies (EsphomeBT). Shelly proxies are unsupported (no active connections).

### Frame layouts — two variants per message type

Each broadcast message comes in two on-the-wire shapes; the parser dispatches by length. Older "ebikemotion" devices (X25 / X35+, names start with `iWoc*`) use the shorter frames; newer X20 devices (names start with `HUS*`, protocol version `102`+) use the 20-byte frames. All multi-byte fields are big-endian.

**Battery — `$b$Z#…#@`** (19 vs 20 bytes)

| Offset | ebikemotion (19 B) | X20 (20 B) |
|---|---|---|
| 5-6 | voltage `read16 / 10` | voltage `read16 / 100` |
| 7 | SOC unsigned byte | SOC: bit 7 = `is_charging`, bits 0-6 = SOC % |
| 8 | temperature byte | temperature **signed** byte |
| 9-10 | current `read16 / 10` | current **signed** `read16 / 10` |
| 11-12 | nominal_capacity `read16 / 10` | nominal_capacity `read16 / 10` |
| 13-14 | remaining_wh `read16 / 10` | remaining_wh `read16 / 10` |
| 15 | combined cycles MSB | **MOSFET temperature** signed byte |
| 16 (-17) | combined LSB → `(batt# * 10000) + cycles` at offset 15-16 | combined `(batt# * 10000) + cycles` at offset 16-17 |

The X20 parser's primary slot is also written when `battery_number == 0`, otherwise single-battery bikes whose firmware doesn't fill that field would have all sensors stuck on `unavailable`.

**Motor — `$m$Z#…#@`** (18 vs 20 bytes)

| Offset | ebikemotion (18 B) | X20 (20 B) |
|---|---|---|
| 5 | assist_level | assist_level (signed byte) |
| 6 | temperature_celsius | temperature_celsius **signed**; `0xD8` = -40 °C is the "no sensor data" sentinel during the first packets after connect |
| 7-8 | power_amp `read16 / 10` | motor_power_watts `read16 / 100` |
| 9-10 | speed_kmh `read16 / 10` | speed_kmh `read16 / 10` |
| 11 | wheel_speed_rpm | wheel_speed_rpm — only valid when `max_torque != 0` |
| 12 | torque_motor_pct | — (start of rider_power_watts) |
| 12-13 | — | rider_power_watts `read16 / 10` |
| 13-14 | power_max `read16 / 10` | — |
| 14-15 | — | power_max_amp `read16 / 10` |
| 15 | max_torque_motor_pct (byte) | — |
| 16-17 | — | max_torque raw `read16` (also acts as the wheel-speed validity flag) |

X20 frames don't carry `power_amp` or `torque_motor_pct`. Conversely the ebikemotion frame doesn't carry `motor_power_watts` / `rider_power_watts`. Each layout fills the missing keys with `None` so `safe_get` paths in `sensor.py` keep working.

**EBM — `$j$Z#…#@`** (17 vs 20 bytes)

| Offset | ebikemotion (17 B) | X20 (20 B) |
|---|---|---|
| 5-7 | (part of odometer) | odometer `read24 / 10` (km) |
| 5-8 | odometer `read32 / 10000` (km) | — |
| 8-9 | (part of autonomy) | autonomy `read16 / 10` (km) |
| 9-12 | autonomy `read32 / 10000` (km) | — |
| 10 | — | lights `byte == 1` |
| 11 | — | status (unsigned byte) |
| 12 | — | accelerometer Z (signed byte) |
| 13 | lights `byte == 1` | accelerometer Y (signed byte) |
| 14 | status (unsigned byte) | **slot indicator**: `1` = lifetime values, `2` = trip A values; pair-alternates between consecutive frames |
| 15-17 | — | fixed `HIJ` (`0x48 0x49 0x4A`) marker before `#@` |

The X20 frame multiplexes lifetime and trip A onto the same odometer/autonomy bytes. The parser keeps both: `state["ebm"]["odometry"]` / `["autonomy"]` reflect the lifetime values (slot 1 frames), `["trip_odometry"]` / `["trip_autonomy"]` mirror trip A (slot 2 frames). When the bike has not had trip A reset since manufacture they happen to coincide.

Devices speaking protocol v200 use the same length but a different layout in bytes 11-17 (an MPlatform error code at 11-12, slot moves to 15, remote-SOC at 16-17). Not yet supported — detect by absence of the `HIJ` marker if it ever shows up in a capture.

### Restore across restarts

`helpers.storage.Store` (key `mysmartbike_ble.<entry_id>`, `STORAGE_VERSION`) persists the parser state so a bike that is off or out of range still shows its last values. `_schedule_save()` uses `Store.async_delay_save(..., STORAGE_SAVE_DELAY)` — BLE notifications arrive far too often for eager writes; `Store` flushes on HA shutdown, and `async_shutdown` does an explicit `async_save` so an unload can't lose state.

`coordinator.data` **is** `self._parser.state` (same object identity, see `_async_update_data` and `_notification_handler`), so restoring means seeding the parser dict — every `value_fn` then works unchanged with no per-entity restore code. It also seeds the `prev` lookup in `_parse_ebm_x20`, which carries lifetime/trip values across the slot alternation.

What is restored is a deliberate whitelist in `const.py`:
- `RESTORE_STATE_KEYS` = `battery_primary`, `battery_secondary`, `ebm`. **`motor` and `assist` are excluded on purpose** — a restored speed or motor power reading is indistinguishable from live data on a parked bike, which is worse than `unknown`.
- `VOLATILE_FIELDS` nulls individual fields inside the restored dicts: battery `current` / `is_charging`, and `ebm` `status` / `accel_y` / `accel_z`.
- `vin`, `protocol_version`, `last_seen` and `manual_disconnect` are stored alongside. Restoring `manual_disconnect` is what stops a Home Assistant restart from waking a bike the user deliberately disconnected.

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
