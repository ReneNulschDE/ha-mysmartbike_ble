"""Test the MySmartBike BLE switch."""
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
    """Test turning on the switch reconnects to bike."""
    entity_id = get_connection_switch_id(hass)
    coordinator = init_integration.runtime_data

    # Mock the reconnect method
    with patch.object(coordinator, "async_reconnect", new_callable=AsyncMock) as mock_reconnect:
        # Turn on the switch
        await hass.services.async_call(
            SWITCH_DOMAIN,
            "turn_on",
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Verify reconnect was called
        mock_reconnect.assert_called_once()


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
    """Test error handling when turning on switch fails."""
    entity_id = get_connection_switch_id(hass)
    coordinator = init_integration.runtime_data

    # Mock reconnect to raise an exception
    with patch.object(
        coordinator, "async_reconnect", side_effect=Exception("Reconnect failed")
    ):
        # Turn on should not raise, but log error
        await hass.services.async_call(
            SWITCH_DOMAIN,
            "turn_on",
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

    # Entity should still exist
    state = hass.states.get(entity_id)
    assert state is not None


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
