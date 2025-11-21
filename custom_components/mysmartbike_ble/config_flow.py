"""Config flow for MySmartBike BLE integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_DEVICE_ADDRESS, CONF_DEVICE_NAME, CONF_LOG_BLE_MESSAGES

_LOGGER = logging.getLogger(__name__)


class MySmartBikeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MySmartBike BLE."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return MySmartBikeOptionsFlowHandler()

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle the bluetooth discovery step."""
        _LOGGER.debug("Discovered BLE device: %s", discovery_info)

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm discovery."""
        assert self._discovery_info is not None

        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_info.name,
                data={
                    CONF_DEVICE_NAME: self._discovery_info.name,
                    CONF_DEVICE_ADDRESS: self._discovery_info.address,
                },
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": self._discovery_info.name,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the user step to pick discovered device."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()

            discovery_info = self._discovered_devices[address]

            return self.async_create_entry(
                title=discovery_info.name,
                data={
                    CONF_DEVICE_NAME: discovery_info.name,
                    CONF_DEVICE_ADDRESS: discovery_info.address,
                },
            )

        current_addresses = self._async_current_ids()
        for discovery_info in async_discovered_service_info(self.hass, False):
            if (
                discovery_info.address in current_addresses
                or discovery_info.address in self._discovered_devices
            ):
                continue

            # Check if device name starts with "iWoc"
            if discovery_info.name and discovery_info.name.startswith("iWoc"):
                self._discovered_devices[discovery_info.address] = discovery_info

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            address: f"{info.name} ({info.address})"
                            for address, info in self._discovered_devices.items()
                        }
                    )
                }
            ),
        )


class MySmartBikeOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for MySmartBike BLE."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            _LOGGER.debug("Options flow: User input received: %s", user_input)
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_LOG_BLE_MESSAGES,
                        default=self.config_entry.options.get(CONF_LOG_BLE_MESSAGES, False),
                    ): bool,
                }
            ),
        )
