"""Constants for the MySmartBike BLE integration."""
from typing import Final

DOMAIN: Final = "mysmartbike_ble"

# BLE UUIDs
WRITE_UUID: Final = "0000FFE2-0000-1000-8000-00805F9B34FB"
NOTIFY_UUID: Final = "0000FFD1-0000-1000-8000-00805F9B34FB"

# BLE Messages
VIN_REQUEST_MESSAGE: Final = bytearray([0x24, 0x53, 0x24, 0x56, 0x23, 0x40])  # $S$V#@
PROTOCOL_REQUEST_MESSAGE: Final = bytearray([0x24, 0x53, 0x24, 0x50, 0x23, 0x40])  # $S$P#@
CLOSE_MESSAGE: Final = bytearray([0x24, 0x44, 0x24, 0x49, 0x23, 0x40])  # $D$I#@

# Legacy alias
WAKEUP_MESSAGE: Final = VIN_REQUEST_MESSAGE

# Message lengths
BATTERY_MESSAGE_LENGTH: Final = 17
MOTOR_MESSAGE_LENGTH: Final = 18
EBM_MESSAGE_LENGTH: Final = 17

# Connection settings
MAX_CONNECT_ATTEMPTS: Final = 3
BLACKLIST_DURATION: Final = 300  # 5 minutes in seconds
CONNECTION_TIMEOUT: Final = 120  # seconds
SCAN_INTERVAL: Final = 30  # seconds

# Device info
MANUFACTURER: Final = "Mahle"
MODEL: Final = "iWoc BLE"

# Config entry keys
CONF_DEVICE_NAME: Final = "device_name"
CONF_DEVICE_ADDRESS: Final = "device_address"

# Options
CONF_LOG_BLE_MESSAGES: Final = "log_ble_messages"
