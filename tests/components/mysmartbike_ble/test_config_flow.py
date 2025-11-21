"""Test the MySmartBike BLE config flow."""
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.mysmartbike_ble.const import CONF_DEVICE_ADDRESS, CONF_DEVICE_NAME, DOMAIN

from .conftest import _get_bluetooth_service_info


async def test_bluetooth_discovery(hass: HomeAssistant) -> None:
    """Test discovery via Bluetooth."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_BLUETOOTH},
        data=_get_bluetooth_service_info(),
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"

    with patch(
        "homeassistant.components.bluetooth.async_ble_device_from_address"
    ) as mock_ble_device:
        mock_ble_device.return_value = _get_bluetooth_service_info()

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )

        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["title"] == "iWoc1A36"
        assert result2["data"] == {
            CONF_DEVICE_NAME: "iWoc1A36",
            CONF_DEVICE_ADDRESS: "AA:BB:CC:DD:EE:FF",
        }


async def test_bluetooth_discovery_already_configured(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """Test discovery aborts if already configured."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_BLUETOOTH},
        data=_get_bluetooth_service_info(),
    )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_success(hass: HomeAssistant, mock_ble_device) -> None:
    """Test user flow - successful flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch(
        "homeassistant.components.bluetooth.async_ble_device_from_address"
    ) as mock_ble_device_from_address:
        mock_ble_device_from_address.return_value = _get_bluetooth_service_info()

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_ADDRESS: "AA:BB:CC:DD:EE:FF"},
        )

        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["title"] == "iWoc1A36"
        assert result2["data"] == {
            CONF_DEVICE_NAME: "iWoc1A36",
            CONF_DEVICE_ADDRESS: "AA:BB:CC:DD:EE:FF",
        }


async def test_user_flow_no_devices_found(hass: HomeAssistant) -> None:
    """Test user flow - no devices found."""
    with patch(
        "custom_components.mysmartbike_ble.config_flow.async_discovered_service_info",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "no_devices_found"


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_config_entry, mock_ble_device
) -> None:
    """Test user flow - device already configured.

    When the only discovered device is already configured,
    it should abort immediately with no_devices_found.
    """
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_user_flow_device_not_found_after_selection(
    hass: HomeAssistant, mock_ble_device
) -> None:
    """Test user flow - device not found after selection."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    # Device disappears after selection (returns None)
    with patch(
        "homeassistant.components.bluetooth.async_ble_device_from_address",
        return_value=None,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_ADDRESS: "AA:BB:CC:DD:EE:FF"},
        )

        # This should trigger ConfigEntryNotReady in the actual setup,
        # but in config_flow it just proceeds to create the entry
        assert result2["type"] == FlowResultType.CREATE_ENTRY
