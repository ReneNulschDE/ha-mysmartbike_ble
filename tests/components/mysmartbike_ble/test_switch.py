"""Test the MySmartBike BLE switch."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


def get_connection_switch_id(hass: HomeAssistant) -> str:
    """Get the connection switch entity ID."""
    entity_registry = er.async_get(hass)
    for entity in entity_registry.entities.values():
        if entity.unique_id.endswith("_connection"):
            return entity.entity_id
    raise ValueError("Connection switch not found")


async def test_switch_setup(hass: HomeAssistant, init_integration) -> None:
    """Test switch setup."""
    entity_id = get_connection_switch_id(hass)
    entity_registry = er.async_get(hass)

    # Check if the connection switch entity exists
    entry = entity_registry.async_get(entity_id)
    assert entry
    assert entry.unique_id.endswith("_connection")


async def test_switch_initial_state(hass: HomeAssistant, init_integration) -> None:
    """Test switch initial state is on (connected)."""
    entity_id = get_connection_switch_id(hass)
    state = hass.states.get(entity_id)
    assert state
    assert state.state == STATE_ON


async def test_switch_turn_off(hass: HomeAssistant, init_integration) -> None:
    """Test turning off the switch disconnects from bike."""
    entity_id = get_connection_switch_id(hass)
    coordinator = init_integration.runtime_data

    # Mock the disconnect method
    with patch.object(coordinator, "async_disconnect", new_callable=AsyncMock) as mock_disconnect:
        # Turn off the switch
        await hass.services.async_call(
            SWITCH_DOMAIN,
            "turn_off",
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Verify disconnect was called
        mock_disconnect.assert_called_once()


async def test_switch_turn_on(hass: HomeAssistant, init_integration) -> None:
    """Test turning on the switch requests a connection to the bike."""
    entity_id = get_connection_switch_id(hass)
    coordinator = init_integration.runtime_data

    with patch.object(coordinator, "async_request_connect") as mock_request:
        await hass.services.async_call(
            SWITCH_DOMAIN,
            "turn_on",
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await hass.async_block_till_done()

        mock_request.assert_called_once()


async def test_switch_icon(hass: HomeAssistant, init_integration) -> None:
    """Test switch icon is correct for connected state."""
    entity_id = get_connection_switch_id(hass)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes.get("icon") == "mdi:bluetooth-connect"


async def test_switch_turn_off_error_handling(
    hass: HomeAssistant, init_integration
) -> None:
    """Test error handling when turning off switch fails."""
    entity_id = get_connection_switch_id(hass)
    coordinator = init_integration.runtime_data

    # Mock disconnect to raise an exception
    with patch.object(
        coordinator, "async_disconnect", side_effect=Exception("Disconnect failed")
    ):
        # Turn off should not raise, but log error
        await hass.services.async_call(
            SWITCH_DOMAIN,
            "turn_off",
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

    # Entity should still exist
    state = hass.states.get(entity_id)
    assert state is not None


async def test_switch_turn_on_error_handling(
    hass: HomeAssistant, init_integration
) -> None:
    """A failing connect must not take the switch down with it."""
    entity_id = get_connection_switch_id(hass)
    coordinator = init_integration.runtime_data

    # Turn off first: that releases the BLE client, so the reconnect does not
    # sit in `_cleanup_client`'s slot-release sleep while we assert.
    await hass.services.async_call(
        SWITCH_DOMAIN, "turn_off", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done()

    with patch.object(
        coordinator, "_connect", side_effect=Exception("Connect failed")
    ):
        await hass.services.async_call(
            SWITCH_DOMAIN,
            "turn_on",
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state is not None
    # The wish survives the failure - the coordinator keeps retrying.
    assert state.state == STATE_ON
    assert coordinator._manual_disconnect is False
    # The claim is released, so the next attempt is not blocked.
    assert coordinator._connecting is False


async def test_switch_turn_on_is_immediate(
    hass: HomeAssistant, init_integration
) -> None:
    """The switch must report On without waiting for the connect attempt.

    Regression: `async_turn_on` used to await the whole reconnect before writing
    its state. On a bike no connectable adapter can reach, that is a full
    `establish_connection` retry cycle - measured at 47s on a real install - and
    the toggle looked broken for the entire time.
    """
    entity_id = get_connection_switch_id(hass)
    coordinator = init_integration.runtime_data

    # Turn off first so there is a wish to flip back on.
    await hass.services.async_call(
        SWITCH_DOMAIN, "turn_off", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_OFF

    connect_started = asyncio.Event()
    release_connect = asyncio.Event()

    async def hanging_connect() -> None:
        connect_started.set()
        await release_connect.wait()

    with patch.object(coordinator, "_connect", side_effect=hanging_connect):
        await hass.services.async_call(
            SWITCH_DOMAIN, "turn_on", {ATTR_ENTITY_ID: entity_id}, blocking=True
        )

        # The connect attempt is still hanging, but the switch already reports On.
        assert hass.states.get(entity_id).state == STATE_ON

        release_connect.set()
        await hass.async_block_till_done()


async def test_repeated_turn_on_does_not_stack_attempts(
    hass: HomeAssistant, init_integration
) -> None:
    """Impatient toggling must not queue several full retry cycles.

    Each queued attempt runs to completion behind `_connect_lock`, so stacking
    them made the wait longer rather than shorter.
    """
    entity_id = get_connection_switch_id(hass)
    coordinator = init_integration.runtime_data

    await hass.services.async_call(
        SWITCH_DOMAIN, "turn_off", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done()

    release_connect = asyncio.Event()
    calls = 0

    async def hanging_connect() -> None:
        nonlocal calls
        calls += 1
        await release_connect.wait()

    with patch.object(coordinator, "_connect", side_effect=hanging_connect):
        for _ in range(3):
            await hass.services.async_call(
                SWITCH_DOMAIN, "turn_on", {ATTR_ENTITY_ID: entity_id}, blocking=True
            )

        release_connect.set()
        await hass.async_block_till_done()

    assert calls == 1


async def test_no_auto_reconnect_when_manually_disconnected(
    hass: HomeAssistant, init_integration
) -> None:
    """Test that coordinator doesn't auto-reconnect after manual disconnect."""
    entity_id = get_connection_switch_id(hass)
    coordinator = init_integration.runtime_data

    # Turn off the switch (manual disconnect)
    with patch.object(coordinator, "async_disconnect", wraps=coordinator.async_disconnect) as mock_disconnect:
        await hass.services.async_call(
            SWITCH_DOMAIN,
            "turn_off",
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await hass.async_block_till_done()
        mock_disconnect.assert_called_once()

    # Verify manual disconnect flag is set
    assert coordinator._manual_disconnect is True

    # Trigger an update - should NOT attempt to reconnect
    with patch.object(coordinator, "_connect", new_callable=AsyncMock) as mock_connect:
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # _connect should NOT have been called
        mock_connect.assert_not_called()
