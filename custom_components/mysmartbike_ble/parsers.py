"""Message parsers for MySmartBike BLE integration."""
import logging
from typing import Dict, Optional, Any

from .const import (
    BATTERY_MESSAGE_LENGTH,
    MOTOR_MESSAGE_LENGTH,
    EBM_MESSAGE_LENGTH,
)

_LOGGER = logging.getLogger(__name__)


def read16(data: bytes, offset: int) -> int:
    """Read 16-bit value from data at offset (big-endian, as per Mahle protocol)."""
    return ((data[offset] & 0xFF) << 8) | (data[offset + 1] & 0xFF)


def read24(data: bytes, offset: int) -> int:
    """Read 24-bit value from data at offset (big-endian, as per Mahle protocol)."""
    return (
        ((data[offset] & 0xFF) << 16)
        | ((data[offset + 1] & 0xFF) << 8)
        | (data[offset + 2] & 0xFF)
    )


def read32(data: bytes, offset: int) -> int:
    """Read 32-bit value from data at offset (big-endian, as per Mahle protocol)."""
    return (
        ((data[offset] & 0xFF) << 24)
        | ((data[offset + 1] & 0xFF) << 16)
        | ((data[offset + 2] & 0xFF) << 8)
        | (data[offset + 3] & 0xFF)
    )


def read_unsigned_byte(byte_val: int) -> int:
    """Read unsigned byte value."""
    return byte_val & 0xFF


class BikeDataParser:
    """Parser for bike BLE messages."""

    def __init__(self):
        """Initialize parser."""
        self.state: Dict[str, Optional[Dict[str, Any]]] = {
            "battery_primary": None,
            "battery_secondary": None,
            "motor": None,
            "assist": None,
            "ebm": None,
        }
        self.battery_packet_counter = 0
        self.vin: Optional[str] = None
        self.protocol_version: Optional[str] = None

    def parse_battery_message(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse battery message and update state."""
        if len(message) < BATTERY_MESSAGE_LENGTH:
            return None

        # Read values
        voltage = read16(message, 5) / 10.0
        soc = read_unsigned_byte(message[7])
        temp_status = message[8]
        current = read16(message, 9) / 10.0
        nominal_capacity = read16(message, 11) / 10.0
        remaining_wh = read16(message, 13) / 10.0

        # Get battery number and cycles from combined field at offset 15
        # Format: value = (battery_number * 10000) + cycles
        # e.g., 10036 means battery 1, 36 cycles
        combined_raw = read16(message, 15) if len(message) >= 19 else None
        battery_number = (combined_raw // 10000) if combined_raw else 1
        cycles = (combined_raw % 10000) if combined_raw else None

        # Construct battery data dictionary
        data = {
            "voltage": voltage,
            "soc": soc,
            "temperature": temp_status,
            "current": current,
            "nominal_capacity": nominal_capacity,
            "remaining_wh": remaining_wh,
            "cycles": cycles,
        }

        # Handle secondary vs primary battery
        if battery_number == 2:
            # Secondary battery detected
            self.battery_packet_counter = 0
            self.state["battery_secondary"] = data
        elif battery_number == 1:
            # Primary battery
            self.battery_packet_counter += 1
            self.state["battery_primary"] = data

            # After 4 consecutive primary battery packets, reset secondary battery
            if self.battery_packet_counter >= 4:
                self.state["battery_secondary"] = {
                    "voltage": 0.0,
                    "soc": 0.0,
                    "temperature": 0,
                    "current": 0.0,
                    "nominal_capacity": 0.0,
                    "remaining_wh": 0.0,
                    "cycles": None,
                }

        return data

    def parse_motor_message(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse motor message and update state."""
        if len(message) < MOTOR_MESSAGE_LENGTH:
            return None

        # Extract values from message
        assist_level = message[5]
        temperature_celsius = message[6]
        power_amp = float(read16(message, 7)) / 10.0
        speed_kmh = float(read16(message, 9)) / 10.0

        # Additional values
        wheel_speed = read_unsigned_byte(message[11])
        torque_pct = message[12]
        power_max = float(read16(message, 13)) / 10.0
        max_torque_pct = message[15]

        # Update state with motor data
        data = {
            "assist_level": assist_level,
            "temperature_celsius": temperature_celsius,
            "power_amp": power_amp,
            "speed_kmh": speed_kmh,
            "wheel_speed_rpm": wheel_speed,
            "torque_motor_pct": torque_pct,
            "power_max_amp": power_max,
            "max_torque_motor_pct": max_torque_pct,
        }

        self.state["motor"] = data
        return data

    def parse_assist_level_message(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse assist level message and update state."""
        if len(message) == 10:
            data = {
                "min": int(chr(message[5])),
                "max": int(chr(message[6])),
                "current": int(chr(message[7])),
            }
            self.state["assist"] = data
            return data
        elif len(message) == 9:
            result = message.decode("utf-8", errors="ignore")[5:7]
            data = {
                "sync_result": result,
                "success": result == "OK",
            }
            self.state["assist"] = data
            return data
        return None

    def parse_vin_message(self, message: bytes) -> Optional[str]:
        """Parse VIN/serial number message.

        Formats:
        - $s$V#<serial>#@ - standard format with 17 char serial
        - R0<serial>@ - alternative format (20 chars total)
        """
        text = message.decode("utf-8", errors="ignore")

        # Standard format: $s$V#<serial>#@
        if text.startswith("$s$V#") and text.endswith("#@"):
            vin = text[5:-2]  # Extract between $s$V# and #@
            if len(vin) == 17:
                self.vin = vin
                _LOGGER.info("Parsed VIN/serial number: %s", vin)
                return vin

        # Alternative format: R0<serial>@ (20 chars total)
        if len(text) == 20 and text.endswith("@") and text.startswith("R0"):
            vin = text[2:-1]  # Extract between R0 and @
            if len(vin) == 17:
                self.vin = vin
                _LOGGER.info("Parsed VIN/serial number (R0 format): %s", vin)
                return vin

        _LOGGER.debug("Could not parse VIN from message: %s", text)
        return None

    def parse_protocol_message(self, message: bytes) -> Optional[str]:
        """Parse protocol version message.

        Format: $s$P#<version>#@ - e.g., $s$P#1.02#@
        Error: $s$P#ER#@ indicates error
        """
        text = message.decode("utf-8", errors="ignore")

        # Standard format: $s$P#<version>#@
        if text.startswith("$s$P#") and text.endswith("#@"):
            version = text[5:-2]  # Extract between $s$P# and #@
            if version and version != "ER":
                self.protocol_version = version
                _LOGGER.info("Parsed protocol version: %s", version)
                return version
            elif version == "ER":
                _LOGGER.warning("Protocol version request returned error")
                return None

        _LOGGER.debug("Could not parse protocol from message: %s", text)
        return None

    def parse_ebm_message(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse EBM (E-Bike Management) message."""
        if len(message) < EBM_MESSAGE_LENGTH:
            return None

        # EbmParserEbm format: 32-bit reads directly from message (big-endian)
        # Raw values are in decimeters, divide by 10000 to get km
        # (Mahle code divides by 10 to get meters, then displays as km by /1000)
        if len(message) < 15:
            return None

        odometry_km = read32(message, 5) / 10000.0
        autonomy_km = read32(message, 9) / 10000.0
        is_light_on = message[13] == 1
        status = read_unsigned_byte(message[14])

        # EbmParserEbm only parses bytes 5-14, bytes 15-16 are suffix #@
        data = {
            "odometry": odometry_km,
            "autonomy": autonomy_km,
            "is_light_on": is_light_on,
            "status": status,
        }

        self.state["ebm"] = data
        return data

    def recognize_message_type(self, message: bytes) -> str:
        """Recognize message type from message content."""
        text = message.decode("ascii", errors="ignore")

        # Handle standard format messages ($..#@)
        if text.startswith("$") and text.endswith("#@"):
            main_type = text[1]
            sub_type = text[3] if len(text) > 3 else None

            if main_type == "b":
                return "battery"
            elif main_type == "d":
                if sub_type == "I":
                    return "diagnosis_init"
                elif sub_type == "R":
                    return "diagnosis_read"
                elif sub_type == "E":
                    return "diagnosis_end"
                elif sub_type == "Z":
                    return "security_session"
                elif sub_type == "C":
                    return "coding_device"
                elif sub_type == "V":
                    return "write_vin"
                elif sub_type == "T":
                    return "status"
            elif main_type == "j" and sub_type == "Z":
                return "ebm"
            elif main_type == "m":
                if sub_type == "A":
                    return "assist"
                elif sub_type == "Z":
                    return "motor"
                elif sub_type == "M":
                    return "engine_maps"
                elif sub_type == "R":
                    return "reset_trip"
            elif main_type == "s":
                if sub_type == "V":
                    return "vin"
                elif sub_type == "P":
                    return "protocol"
            elif main_type == "M" and sub_type == "M":
                return "engine_maps"
            elif main_type == "i" and sub_type == "C":
                return "calibrate"

        # Handle special format messages (ending with @)
        elif text.endswith("@"):
            main_type = text[0]
            if main_type == "T":
                return "status"
            elif main_type == "C":
                return "coding_device"
            elif main_type == "R":
                return "vin"
            elif main_type == "Z":
                return "security_challenge"

        return "unknown"

    def handle_message(self, data: bytes) -> None:
        """Handle received message data and update state."""
        msg_type = self.recognize_message_type(data)

        # Handle different message types
        if msg_type == "battery":
            self.parse_battery_message(data)
        elif msg_type == "motor":
            self.parse_motor_message(data)
        elif msg_type == "assist":
            self.parse_assist_level_message(data)
        elif msg_type == "ebm":
            self.parse_ebm_message(data)
        elif msg_type == "vin":
            self.parse_vin_message(data)
        elif msg_type == "protocol":
            self.parse_protocol_message(data)
        elif msg_type in [
            "diagnosis_init",
            "diagnosis_read",
            "diagnosis_end",
            "security_session",
            "coding_device",
            "write_vin",
            "status",
            "engine_maps",
            "reset_trip",
            "calibrate",
            "security_challenge",
        ]:
            _LOGGER.debug("Received message of type: %s", msg_type)
        else:
            # Enhanced logging for unknown messages
            prefix = " ".join([f"{b:02x}" for b in data[:5]])
            _LOGGER.debug(
                "Unknown message: type=%s, prefix=[%s], length=%d",
                msg_type,
                prefix,
                len(data),
            )
