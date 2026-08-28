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

# Persistence
STORAGE_VERSION: Final = 1
STORAGE_SAVE_DELAY: Final = 60  # seconds; BLE notifications arrive far too often to save eagerly

# Top-level parser state keys that survive a restart. "motor" and "assist" are
# deliberately absent: a restored speed or power reading would look like live
# data from a bike that is actually parked.
RESTORE_STATE_KEYS: Final = ("battery_primary", "battery_secondary", "ebm")

# Fields inside the restored dicts that describe an instantaneous condition and
# are therefore dropped (set to None) when reading the state back.
VOLATILE_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "battery_primary": ("current", "is_charging"),
    "battery_secondary": ("current", "is_charging"),
    "ebm": ("status", "accel_y", "accel_z"),
}

# A link that survived at least this long is worth reconnecting immediately when
# it drops; anything shorter is left to the regular poll so a bike that cannot
# hold a connection does not spin in a reconnect loop.
MIN_LINK_SECONDS_FOR_FAST_RECONNECT: Final = 5.0

# Granularity of the "Last Seen" entity. Notifications arrive about once a
# second; publishing each one made this timestamp the single biggest recorder
# writer in a real installation. Its job - telling you how fresh the values are
# - needs nothing near that resolution. The precise value is still persisted.
LAST_SEEN_RESOLUTION: Final = 30  # seconds
