"""Test that the integration survives a restart with the bike out of range."""
import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mysmartbike_ble.const import (
    CONF_DEVICE_ADDRESS,
    CONF_DEVICE_NAME,
    DOMAIN,
    STORAGE_VERSION,
)

ENTRY_ID = "restoretestentry"
STORE_KEY = f"{DOMAIN}.{ENTRY_ID}"

STORED_STATE = {
    "battery_primary": {
        "voltage": 36.4,
        "soc": 73,
        "temperature": 21,
        "temperature_mos": 24,
        "current": -4.2,
        "nominal_capacity": 248.0,
        "remaining_wh": 181.0,
        "cycles": 42,
        "is_charging": True,
    },
    "battery_secondary": None,
    "ebm": {
        "odometry": 1234.5,
        "autonomy": 61.0,
        "trip_odometry": 12.3,
        "trip_autonomy": 58.0,
        "is_light_on": True,
        "status": 3,
        "accel_y": -5,
        "accel_z": 61,
    },
    "vin": "WBS0000000RESTORE",
    "protocol_version": "102",
    "manual_disconnect": False,
    "last_seen": "2026-08-26T18:30:00+00:00",
}


@pytest.fixture
def restore_config_entry() -> MockConfigEntry:
    """Config entry with a fixed entry_id so the storage key is predictable."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="iWoc1A36",
        entry_id=ENTRY_ID,
        data={
            CONF_DEVICE_NAME: "iWoc1A36",
            CONF_DEVICE_ADDRESS: "AA:BB:CC:DD:EE:FF",
        },
        unique_id="AA:BB:CC:DD:EE:FF",
    )


def seed_storage(hass_storage, data: dict) -> None:
    """Pre-populate .storage as if a previous run had written it."""
    hass_storage[STORE_KEY] = {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": STORE_KEY,
        "data": data,
    }


def entity_id_for(hass: HomeAssistant, suffix: str) -> str:
    """Look up an entity id by the tail of its unique id."""
    registry = er.async_get(hass)
    for entity in registry.entities.values():
        if entity.unique_id.endswith(suffix):
            return entity.entity_id
    raise ValueError(f"No entity with unique_id ending in {suffix}")


async def setup_offline(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up the entry with the bike unreachable."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_succeeds_without_device(
    hass: HomeAssistant,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_out_of_range,
) -> None:
    """The entry loads even when the bike is switched off or out of range."""
    await setup_offline(hass, restore_config_entry)

    assert restore_config_entry.state is ConfigEntryState.LOADED
    # Entities exist rather than the whole entry being retried
    assert hass.states.get(entity_id_for(hass, "_odometer")) is not None


async def test_restored_values_shown_while_offline(
    hass: HomeAssistant,
    hass_storage,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_out_of_range,
) -> None:
    """Persisted counters and battery values come back without a connection."""
    seed_storage(hass_storage, STORED_STATE)
    await setup_offline(hass, restore_config_entry)

    assert hass.states.get(entity_id_for(hass, "_odometer")).state == "1234.5"
    assert hass.states.get(entity_id_for(hass, "_trip_distance")).state == "12.3"
    assert hass.states.get(entity_id_for(hass, "_range")).state == "61.0"
    assert hass.states.get(entity_id_for(hass, "_battery_primary_soc")).state == "73"
    assert (
        hass.states.get(entity_id_for(hass, "_battery_primary_remaining_wh")).state
        == "181.0"
    )
    assert hass.states.get(entity_id_for(hass, "_light")).state == "On"


async def test_restored_sensors_are_available_not_unavailable(
    hass: HomeAssistant,
    hass_storage,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_out_of_range,
) -> None:
    """An unreachable bike must not blank the sensors."""
    seed_storage(hass_storage, STORED_STATE)
    await setup_offline(hass, restore_config_entry)

    for suffix in ("_odometer", "_battery_primary_soc", "_motor_speed"):
        assert hass.states.get(entity_id_for(hass, suffix)).state != STATE_UNAVAILABLE

    # ...but the connectivity sensor honestly reports "not connected"
    assert hass.states.get(entity_id_for(hass, "_connected")).state == STATE_OFF


async def test_volatile_values_are_not_restored(
    hass: HomeAssistant,
    hass_storage,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_out_of_range,
) -> None:
    """Momentary readings would look like live data from a parked bike."""
    seed_storage(hass_storage, STORED_STATE)
    await setup_offline(hass, restore_config_entry)

    # "motor" is not in RESTORE_STATE_KEYS at all
    assert hass.states.get(entity_id_for(hass, "_motor_speed")).state == STATE_UNKNOWN
    assert (
        hass.states.get(entity_id_for(hass, "_motor_temperature")).state
        == STATE_UNKNOWN
    )
    # ebm.status is restored as None
    assert hass.states.get(entity_id_for(hass, "_ebm_status")).state == STATE_UNKNOWN

    # battery current / charging flag are dropped from the restored dict
    coordinator = restore_config_entry.runtime_data
    assert coordinator.data["battery_primary"]["current"] is None
    assert coordinator.data["battery_primary"]["is_charging"] is None
    assert coordinator.data["battery_primary"]["soc"] == 73


async def test_restored_vin_populates_device_info(
    hass: HomeAssistant,
    hass_storage,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_out_of_range,
) -> None:
    """Serial number and protocol version survive a restart."""
    seed_storage(hass_storage, STORED_STATE)
    await setup_offline(hass, restore_config_entry)

    coordinator = restore_config_entry.runtime_data
    assert coordinator.vin == "WBS0000000RESTORE"
    assert coordinator.protocol_version == "102"

    from homeassistant.helpers import device_registry as dr

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, ENTRY_ID)})
    assert device is not None
    assert device.serial_number == "WBS0000000RESTORE"
    assert device.sw_version == "102"


async def test_restored_protocol_selects_the_frame_layout(
    hass: HomeAssistant,
    hass_storage,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_out_of_range,
) -> None:
    """The very first packet after a restart must not be decoded with a guess.

    Several protocols share a frame length but not a layout, so the parser has
    to know the version before the first notification arrives - which is why
    `async_restore` runs before the platforms are forwarded.
    """
    seed_storage(hass_storage, {**STORED_STATE, "protocol_version": "200"})
    await setup_offline(hass, restore_config_entry)

    coordinator = restore_config_entry.runtime_data
    assert coordinator._parser.protocol == "200"

    # A v200 battery frame whose battery number is 0 is an auxiliary reading and
    # must not overwrite the restored pack.
    coordinator._notification_handler(
        0, bytearray.fromhex("2462245a230ec20c1600000dc807d31800052340")
    )

    assert coordinator.data["battery_primary"]["soc"] == 73


async def test_manual_disconnect_survives_restart(
    hass: HomeAssistant,
    hass_storage,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_in_range,
) -> None:
    """A bike the user disconnected must not be woken by a restart."""
    seed_storage(hass_storage, {**STORED_STATE, "manual_disconnect": True})

    restore_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.mysmartbike_ble.coordinator.MySmartBikeCoordinator._connect",
        new_callable=AsyncMock,
    ) as mock_connect:
        await hass.config_entries.async_setup(restore_config_entry.entry_id)
        await hass.async_block_till_done()
        mock_connect.assert_not_called()

    assert restore_config_entry.runtime_data._manual_disconnect is True
    assert hass.states.get(entity_id_for(hass, "_connection")).state == STATE_OFF


async def test_connection_switch_on_by_default(
    hass: HomeAssistant,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_out_of_range,
) -> None:
    """Without a stored preference the connection stays enabled."""
    await setup_offline(hass, restore_config_entry)
    assert hass.states.get(entity_id_for(hass, "_connection")).state == STATE_ON


async def test_state_is_persisted_on_unload(
    hass: HomeAssistant,
    hass_storage,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_in_range,
) -> None:
    """Parsed data reaches .storage, volatile keys excluded."""
    restore_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(restore_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = restore_config_entry.runtime_data
    # A real 20-byte X20 EBM lifetime frame
    coordinator._notification_handler(
        0, bytearray.fromhex("246a245a2300008402e1000001f50148494a2340")
    )
    await hass.async_block_till_done()

    await hass.config_entries.async_unload(restore_config_entry.entry_id)
    await hass.async_block_till_done()

    stored = hass_storage[STORE_KEY]["data"]
    assert stored["ebm"]["odometry"] == pytest.approx(13.2, rel=1e-3)
    assert stored["last_seen"] is not None
    assert "motor" not in stored
    assert "rssi" not in stored


async def test_empty_notifications_are_filtered(
    hass: HomeAssistant,
    hass_storage,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_in_range,
) -> None:
    """Zero-length notifications must not reach the parser or wake entities.

    Some links deliver them several times a second. Each one used to log three
    lines, queue a file write and push a coordinator update through every
    entity - all for a payload that carries nothing.
    """
    restore_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(restore_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = restore_config_entry.runtime_data
    coordinator._last_seen = None

    with patch.object(coordinator, "async_set_updated_data") as mock_update:
        for _ in range(5):
            coordinator._notification_handler(0, bytearray())
        await hass.async_block_till_done()

        mock_update.assert_not_called()

    assert coordinator._empty_notifications == 5
    # An empty payload says nothing about the bike, so it is not a sighting.
    assert coordinator._last_seen is None
    assert coordinator.data["ebm"] is None

    # A real frame still goes through.
    coordinator._notification_handler(
        0, bytearray.fromhex("246a245a2300008402e1000001f50148494a2340")
    )
    await hass.async_block_till_done()

    assert coordinator._last_seen is not None
    assert coordinator.data["ebm"]["odometry"] == pytest.approx(13.2, rel=1e-3)


async def test_reconnects_when_bike_appears(
    hass: HomeAssistant,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_in_range,
    mock_bluetooth_service_info,
) -> None:
    """An advertisement triggers a connect instead of waiting for the poll."""
    await setup_offline(hass, restore_config_entry)
    coordinator = restore_config_entry.runtime_data
    await wait_connected(hass, coordinator)

    # Drop the link the way bleak reports one
    coordinator._async_client_disconnected(coordinator._client)
    await hass.async_block_till_done()
    assert coordinator.is_connected is False

    with patch.object(
        coordinator, "_connect", new_callable=AsyncMock
    ) as mock_connect:
        coordinator._async_device_appeared(mock_bluetooth_service_info, None)
        await hass.async_block_till_done()
        mock_connect.assert_called_once()


async def test_no_reconnect_on_advertisement_when_disconnected_manually(
    hass: HomeAssistant,
    hass_storage,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_in_range,
    mock_bluetooth_service_info,
) -> None:
    """The advertisement watch must respect the user's disconnect."""
    seed_storage(hass_storage, {**STORED_STATE, "manual_disconnect": True})
    await setup_offline(hass, restore_config_entry)
    coordinator = restore_config_entry.runtime_data

    with patch.object(
        coordinator, "_connect", new_callable=AsyncMock
    ) as mock_connect:
        coordinator._async_device_appeared(mock_bluetooth_service_info, None)
        await hass.async_block_till_done()
        mock_connect.assert_not_called()


async def wait_connected(hass: HomeAssistant, coordinator) -> None:
    """Wait out the 200 ms VIN/protocol handshake in _connect()."""
    for _ in range(20):
        await asyncio.sleep(0.05)
        await hass.async_block_till_done()
        if coordinator.is_connected:
            return
    raise AssertionError("coordinator never reported a connection")


async def test_unexpected_disconnect_is_noticed(
    hass: HomeAssistant,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_in_range,
) -> None:
    """A dropped link flips the connectivity sensor and re-enables reconnect."""
    await setup_offline(hass, restore_config_entry)
    coordinator = restore_config_entry.runtime_data
    await wait_connected(hass, coordinator)
    assert hass.states.get(entity_id_for(hass, "_connected")).state == STATE_ON

    # bleak invokes the disconnected_callback with the client it handed out
    coordinator._async_client_disconnected(coordinator._client)
    await hass.async_block_till_done()

    assert coordinator.is_connected is False
    assert hass.states.get(entity_id_for(hass, "_connected")).state == STATE_OFF
    # Restored/last-known values stay visible
    assert (
        hass.states.get(entity_id_for(hass, "_odometer")).state != STATE_UNAVAILABLE
    )


async def test_writes_are_throttled_not_debounced(
    hass: HomeAssistant,
    hass_storage,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_in_range,
    freezer,
) -> None:
    """A continuous notification stream must not postpone the write forever.

    `Store.async_delay_save` debounces: re-arming on every notification would
    keep pushing the write out for as long as the bike stays connected.
    """
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    from custom_components.mysmartbike_ble.const import STORAGE_SAVE_DELAY

    await setup_offline(hass, restore_config_entry)
    coordinator = restore_config_entry.runtime_data

    frame = bytearray.fromhex("246a245a2300008402e1000001f50148494a2340")
    # Keep notifying across more than one save window, as a connected bike does
    for _ in range(4):
        coordinator._notification_handler(0, frame)
        freezer.tick(timedelta(seconds=STORAGE_SAVE_DELAY // 2))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()

    # Written without ever unloading or shutting Home Assistant down
    assert STORE_KEY in hass_storage
    assert hass_storage[STORE_KEY]["data"]["ebm"]["odometry"] == pytest.approx(13.2)


async def test_entity_names_come_from_translations(
    hass: HomeAssistant,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_out_of_range,
) -> None:
    """The switch is the connection *wish*, the binary sensor the status.

    Both used to read "Connection"/"Connected" side by side, and the binary
    sensor hardcoded its English name, defeating its translation key.
    """
    await setup_offline(hass, restore_config_entry)

    switch = hass.states.get(entity_id_for(hass, "_connection"))
    connected = hass.states.get(entity_id_for(hass, "_connected"))

    assert switch.attributes["friendly_name"] == "iWoc1A36 Auto-connect"
    assert connected.attributes["friendly_name"] == "iWoc1A36 Connected"


async def test_unreachable_reason_distinguishes_passive_only_proxy(
    hass: HomeAssistant,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_out_of_range,
    caplog,
) -> None:
    """A bike seen only by a passive proxy must not read as "switched off"."""
    with patch(
        "custom_components.mysmartbike_ble.coordinator.bluetooth.async_address_present",
        return_value=True,
    ):
        await setup_offline(hass, restore_config_entry)

    assert "no Bluetooth adapter or proxy that supports active connections" in caplog.text
    assert "turn on the bike" not in caplog.text


async def test_unreachable_reason_when_bike_is_off(
    hass: HomeAssistant,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_out_of_range,
    caplog,
) -> None:
    """Nothing advertising at all still reads as "turn on the bike"."""
    with patch(
        "custom_components.mysmartbike_ble.coordinator.bluetooth.async_address_present",
        return_value=False,
    ):
        await setup_offline(hass, restore_config_entry)

    assert "turn on the bike" in caplog.text


async def test_unreachable_warning_is_not_repeated(
    hass: HomeAssistant,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_out_of_range,
    caplog,
) -> None:
    """The 30s poll must not spam a warning for a parked bike."""
    import logging

    with patch(
        "custom_components.mysmartbike_ble.coordinator.bluetooth.async_address_present",
        return_value=False,
    ):
        await setup_offline(hass, restore_config_entry)
        coordinator = restore_config_entry.runtime_data
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                await coordinator.async_refresh()
                await hass.async_block_till_done()

    assert "turn on the bike" not in caplog.text


async def test_advertisement_storm_starts_one_connect_attempt(
    hass: HomeAssistant,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_in_range,
    mock_bluetooth_service_info,
) -> None:
    """Home Assistant fires the callback on every advertisement.

    These bikes advertise several times a second, so an unguarded callback
    would queue a connect task per advertisement, all serialising behind
    _connect_lock and each hammering the proxy with a full retry cycle.
    """
    await setup_offline(hass, restore_config_entry)
    coordinator = restore_config_entry.runtime_data
    await wait_connected(hass, coordinator)
    coordinator._async_client_disconnected(coordinator._client)
    await hass.async_block_till_done()

    started = 0
    release = asyncio.Event()

    async def slow_connect() -> None:
        nonlocal started
        started += 1
        await release.wait()

    with patch.object(coordinator, "_connect", side_effect=slow_connect):
        for _ in range(50):
            coordinator._async_device_appeared(mock_bluetooth_service_info, None)
        await asyncio.sleep(0)
        await hass.async_block_till_done()

        assert started == 1, f"{started} connect attempts for 50 advertisements"

        release.set()
        await hass.async_block_till_done()

    # ...and the claim is released, so a later advertisement can still connect
    assert coordinator._connecting is False


async def test_fast_reconnect_after_established_link_drops(
    hass: HomeAssistant,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_in_range,
) -> None:
    """A dropped link reconnects at once instead of waiting out the poll.

    These bikes stop advertising after an unexpected disconnect, so the
    advertisement watch never fires, and every notification has just pushed the
    poll timer another SCAN_INTERVAL out.
    """
    await setup_offline(hass, restore_config_entry)
    coordinator = restore_config_entry.runtime_data
    await wait_connected(hass, coordinator)

    # Pretend the link had been up comfortably longer than the spin guard
    coordinator._connected_since = hass.loop.time() - 120

    with patch.object(coordinator, "_connect", new_callable=AsyncMock) as mock_connect:
        coordinator._async_client_disconnected(coordinator._client)
        await hass.async_block_till_done()
        mock_connect.assert_called_once()


async def test_no_fast_reconnect_when_link_died_immediately(
    hass: HomeAssistant,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_in_range,
) -> None:
    """A link that collapses at once must not spin; the poll retries instead."""
    await setup_offline(hass, restore_config_entry)
    coordinator = restore_config_entry.runtime_data
    await wait_connected(hass, coordinator)

    coordinator._connected_since = hass.loop.time()  # just connected

    with patch.object(coordinator, "_connect", new_callable=AsyncMock) as mock_connect:
        coordinator._async_client_disconnected(coordinator._client)
        await hass.async_block_till_done()
        mock_connect.assert_not_called()


async def test_last_seen_is_throttled(
    hass: HomeAssistant,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_in_range,
    freezer,
) -> None:
    """A timestamp that moves on every packet floods the recorder.

    Notifications arrive about once a second; the entity only needs to say how
    fresh the values are, so it moves at LAST_SEEN_RESOLUTION granularity while
    the exact time is still what gets persisted.
    """
    from custom_components.mysmartbike_ble.const import LAST_SEEN_RESOLUTION

    await setup_offline(hass, restore_config_entry)
    coordinator = restore_config_entry.runtime_data
    frame = bytearray.fromhex("246a245a2300008402e1000001f50148494a2340")

    coordinator._notification_handler(0, frame)
    first = coordinator.data["last_seen"]
    assert first is not None

    # A burst of notifications inside the window must not move the entity
    for _ in range(10):
        freezer.tick(timedelta(seconds=1))
        coordinator._notification_handler(0, frame)
    assert coordinator.data["last_seen"] == first
    # ...while the persisted timestamp keeps tracking reality
    assert coordinator.last_seen > first

    # Past the window it moves again
    freezer.tick(timedelta(seconds=LAST_SEEN_RESOLUTION))
    coordinator._notification_handler(0, frame)
    assert coordinator.data["last_seen"] > first


async def test_distances_are_rounded_to_100m(
    hass: HomeAssistant,
    hass_storage,
    restore_config_entry: MockConfigEntry,
    mock_bleak_client,
    mock_device_out_of_range,
) -> None:
    """Four decimals of false precision would be a database row each."""
    seed_storage(
        hass_storage,
        {
            **STORED_STATE,
            "ebm": {
                **STORED_STATE["ebm"],
                "odometry": 806.1488,
                "autonomy": 14.6065,
                "trip_odometry": 12.3456,
                "trip_autonomy": 58.9876,
            },
        },
    )
    await setup_offline(hass, restore_config_entry)

    assert hass.states.get(entity_id_for(hass, "_odometer")).state == "806.1"
    assert hass.states.get(entity_id_for(hass, "_range")).state == "14.6"
    assert hass.states.get(entity_id_for(hass, "_trip_distance")).state == "12.3"
