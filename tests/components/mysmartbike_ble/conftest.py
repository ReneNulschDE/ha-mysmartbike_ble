"""Fixtures for MySmartBike BLE tests."""
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_ADDRESS

from custom_components.mysmartbike_ble.const import (
    CONF_DEVICE_ADDRESS,
    CONF_DEVICE_NAME,
    DOMAIN,
)

from pytest_homeassistant_custom_component.common import MockConfigEntry


def _get_bluetooth_service_info() -> MagicMock:
    """Return a mock BluetoothServiceInfoBleak."""
    service_info = MagicMock()
    service_info.name = "iWoc1A36"
    service_info.address = "AA:BB:CC:DD:EE:FF"
    service_info.rssi = -60
    service_info.manufacturer_data = {}
    service_info.service_data = {}
    service_info.service_uuids = []
    service_info.source = "local"
    return service_info


@pytest.fixture
def mock_bluetooth_service_info() -> MagicMock:
    """Return mock Bluetooth service info."""
    return _get_bluetooth_service_info()


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return default mocked config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="iWoc1A36",
        data={
            CONF_DEVICE_NAME: "iWoc1A36",
            CONF_DEVICE_ADDRESS: "AA:BB:CC:DD:EE:FF",
        },
        unique_id="AA:BB:CC:DD:EE:FF",
    )


@pytest.fixture
def mock_bleak_client() -> Generator[MagicMock]:
    """Return a mocked BleakClient."""
    with patch(
        "custom_components.mysmartbike_ble.coordinator.establish_connection",
        autospec=True,
    ) as mock_client:
        client = AsyncMock()
        client.is_connected = True
        client.write_gatt_char = AsyncMock()
        client.start_notify = AsyncMock()
        client.stop_notify = AsyncMock()
        client.disconnect = AsyncMock()
        mock_client.return_value = client
        yield mock_client


@pytest.fixture
def mock_ble_device() -> Generator[MagicMock]:
    """Return a mocked BLE device."""
    with patch(
        "custom_components.mysmartbike_ble.config_flow.async_discovered_service_info",
        autospec=True,
    ) as mock_devices:
        mock_devices.return_value = [_get_bluetooth_service_info()]
        yield mock_devices


@pytest.fixture
async def init_integration(
    hass,
    mock_config_entry: MockConfigEntry,
    mock_bleak_client: MagicMock,
) -> MockConfigEntry:
    """Set up the MySmartBike BLE integration for testing."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.bluetooth.async_ble_device_from_address"
    ) as mock_ble_device_from_address:
        mock_ble_device_from_address.return_value = _get_bluetooth_service_info()

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    return mock_config_entry
