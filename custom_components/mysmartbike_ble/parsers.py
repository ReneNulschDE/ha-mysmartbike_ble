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
    """Read 16-bit big-endian value from data at offset."""
    return ((data[offset] & 0xFF) << 8) | (data[offset + 1] & 0xFF)


def read16_signed(data: bytes, offset: int) -> int:
    """Read 16-bit big-endian value as signed int."""
    value = read16(data, offset)
    if value & 0x8000:
        value -= 0x10000
    return value


def read_signed_byte(byte_val: int) -> int:
    """Read byte as signed int."""
    return byte_val - 256 if byte_val & 0x80 else byte_val


def read24(data: bytes, offset: int) -> int:
    """Read 24-bit big-endian value from data at offset."""
    return (
        ((data[offset] & 0xFF) << 16)
        | ((data[offset + 1] & 0xFF) << 8)
        | (data[offset + 2] & 0xFF)
    )


def read32(data: bytes, offset: int) -> int:
    """Read 32-bit big-endian value from data at offset."""
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
        """Parse battery frame; dispatch by length to the right layout."""
        if len(message) == 20:
            return self._parse_battery_x20(message)
        if len(message) >= BATTERY_MESSAGE_LENGTH:
            return self._parse_battery_ebm(message)
        return None

    def _parse_battery_ebm(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse 19-byte battery frame (X25 / X35+ / ebikemotion)."""
        voltage = read16(message, 5) / 10.0
        soc = read_unsigned_byte(message[7])
        temp_status = message[8]
        current = read16(message, 9) / 10.0
        nominal_capacity = read16(message, 11) / 10.0
        remaining_wh = read16(message, 13) / 10.0

        combined_raw = read16(message, 15) if len(message) >= 19 else None
        battery_number = (combined_raw // 10000) if combined_raw else 1
        cycles = (combined_raw % 10000) if combined_raw else None

        data = {
            "voltage": voltage,
            "soc": soc,
            "temperature": temp_status,
            "temperature_mos": None,
            "current": current,
            "nominal_capacity": nominal_capacity,
            "remaining_wh": remaining_wh,
            "cycles": cycles,
            "is_charging": False,
        }
        self._store_battery(data, battery_number)
        return data

    def _parse_battery_x20(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse 20-byte battery frame (X20 / HUS-prefixed devices)."""
        voltage = read16(message, 5) / 100.0
        soc_raw = read_unsigned_byte(message[7])
        # Bit 7 of the SOC byte signals charging on the newer firmware variant;
        # safe to read unconditionally — real SOC is always ≤ 100, so the bit
        # would never be set by accident on older firmwares.
        is_charging = bool(soc_raw & 0x80)
        soc = soc_raw & 0x7F
        temp_status = read_signed_byte(message[8])
        current = read16_signed(message, 9) / 10.0
        nominal_capacity = read16(message, 11) / 10.0
        remaining_wh = read16(message, 13) / 10.0
        temperature_mos = read_signed_byte(message[15])

        combined_raw = read16(message, 16)
        battery_number = combined_raw // 10000
        cycles = combined_raw % 10000

        data = {
            "voltage": voltage,
            "soc": soc,
            "temperature": temp_status,
            "temperature_mos": temperature_mos,
            "current": current,
            "nominal_capacity": nominal_capacity,
            "remaining_wh": remaining_wh,
            "cycles": cycles,
            "is_charging": is_charging,
        }
        self._store_battery(data, battery_number)
        return data

    def _store_battery(self, data: Dict[str, Any], battery_number: int) -> None:
        """Update primary/secondary battery slots and the consecutive-primary counter."""
        if battery_number == 2:
            self.battery_packet_counter = 0
            self.state["battery_secondary"] = data
            return

        # Anything that isn't an explicit secondary battery (number == 2) is
        # treated as primary — a missing/zero battery_number on a single-battery
        # bike would otherwise leave all sensors unavailable.
        self.battery_packet_counter += 1
        self.state["battery_primary"] = data

        if self.battery_packet_counter >= 4:
            self.state["battery_secondary"] = {
                "voltage": 0.0,
                "soc": 0.0,
                "temperature": 0,
                "temperature_mos": None,
                "current": 0.0,
                "nominal_capacity": 0.0,
                "remaining_wh": 0.0,
                "cycles": None,
                "is_charging": False,
            }

    def parse_motor_message(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse motor frame; dispatch by length to the right layout."""
        if len(message) >= 20:
            return self._parse_motor_x20(message)
        if len(message) >= MOTOR_MESSAGE_LENGTH:
            return self._parse_motor_ebm(message)
        return None

    def _parse_motor_ebm(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse 18-byte motor frame (X25 / X35+ / ebikemotion)."""
        assist_level = message[5]
        temperature_celsius = message[6]
        power_amp = float(read16(message, 7)) / 10.0
        speed_kmh = float(read16(message, 9)) / 10.0
        wheel_speed = read_unsigned_byte(message[11])
        torque_pct = message[12]
        power_max = float(read16(message, 13)) / 10.0
        max_torque_pct = message[15]

        data = {
            "assist_level": assist_level,
            "temperature_celsius": temperature_celsius,
            "power_amp": power_amp,
            "speed_kmh": speed_kmh,
            "wheel_speed_rpm": wheel_speed,
            "torque_motor_pct": torque_pct,
            "power_max_amp": power_max,
            "max_torque_motor_pct": max_torque_pct,
            "motor_power_watts": None,
            "rider_power_watts": None,
        }
        self.state["motor"] = data
        return data

    def _parse_motor_x20(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse 20-byte motor frame (X20 / HUS-prefixed devices)."""
        assist_level = read_signed_byte(message[5])
        # Temperature is signed: 0xD8 (= -40 °C) is the "no sensor data" sentinel
        # the bike reports during the first packets after connect.
        temperature_celsius = read_signed_byte(message[6])
        motor_power_watts = read16(message, 7) / 100.0
        speed_kmh = read16(message, 9) / 10.0
        wheel_speed_raw = read_unsigned_byte(message[11])
        rider_power_watts = read16(message, 12) / 10.0
        power_max_amp = read16(message, 14) / 10.0
        # max_torque doubles as a validity flag for wheel_speed (0 → no data).
        max_torque = read16(message, 16)

        data = {
            "assist_level": assist_level,
            "temperature_celsius": temperature_celsius,
            "power_amp": None,
            "speed_kmh": speed_kmh,
            "wheel_speed_rpm": wheel_speed_raw if max_torque != 0 else None,
            "torque_motor_pct": None,
            "power_max_amp": power_max_amp,
            "max_torque_motor_pct": max_torque,
            "motor_power_watts": motor_power_watts,
            "rider_power_watts": rider_power_watts,
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
        """Parse EBM (E-Bike Management) frame; dispatch by length."""
        if len(message) >= 20:
            return self._parse_ebm_x20(message)
        if len(message) >= EBM_MESSAGE_LENGTH:
            return self._parse_ebm_ebm(message)
        return None

    def _parse_ebm_ebm(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse 17-byte EBM frame (X25 / X35+ / ebikemotion)."""
        odometry_km = read32(message, 5) / 10000.0
        autonomy_km = read32(message, 9) / 10000.0
        is_light_on = message[13] == 1
        status = read_unsigned_byte(message[14])

        data = {
            "odometry": odometry_km,
            "autonomy": autonomy_km,
            "is_light_on": is_light_on,
            "status": status,
        }
        self.state["ebm"] = data
        return data

    def _parse_ebm_x20(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse 20-byte EBM frame (X20 / HUS-prefixed devices).

        Autonomy is a 16-bit field at offset 9 (a 32-bit decode there yields
        implausible six-digit km values). Bytes 15-17 are a fixed `HIJ` marker.
        Byte 13 light flag is observed as 0x00 / 0x01 / 0xFF — only 0x01 means on.
        """
        odometry_km = read32(message, 5) / 10000.0
        autonomy_km = read16(message, 9) / 1000.0
        is_light_on = message[13] == 1
        status = read_unsigned_byte(message[14])

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
