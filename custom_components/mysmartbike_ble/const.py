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

# Protocol ids as the Mahle SDK knows them. The bike answers `$S$P#@` with one
# of these; the SDK matches the payload as an exact string and picks a whole set
# of frame parsers from it. Several 20-byte frames share a length but not a
# layout, so the version - not the length - has to decide.
PROTOCOL_EBM: Final = "EBM"  # X25 / X35+ (iWoc*); also the fallback when `$S$P#@` times out
PROTOCOL_V100: Final = "100"
PROTOCOL_V102: Final = "102"
PROTOCOL_V200: Final = "200"
PROTOCOL_V300: Final = "300"

# Numeric ids only; `normalize_protocol_version` matches against this set after
# stripping the dot some firmwares report ("1.02" -> "102").
NUMERIC_PROTOCOL_VERSIONS: Final = frozenset(
    {PROTOCOL_V100, PROTOCOL_V102, PROTOCOL_V200, PROTOCOL_V300}
)

# Bytes 15-17 of a v100/v102/v300 EBM frame are this fixed marker. v200 puts the
# slot indicator and the remote's state of charge there instead, which makes the
# marker a reliable way to tell the two layouts apart before the bike has told us
# its protocol version.
EBM_MAHLE_MARKER: Final = b"HIJ"

# Base offsets of the M-Platform device ids a v200 EBM frame reports alongside
# its error id. The full error code the app shows is base + error id.
MPLATFORM_DEVICE_BASE_CODES: Final[dict[int, int]] = {
    0: 0,  # drive unit
    1: 100,  # head unit
    2: 200,  # internal battery
    3: 300,  # external battery
    4: 400,  # charger
    5: 500,  # bike radar
    15: 0,  # none
}

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
    "ebm": (
        "status",
        "error_code",
        "accel_y",
        "accel_z",
        "remote_connected",
        "remote_soc",
    ),
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
