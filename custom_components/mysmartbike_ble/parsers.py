"""Message parsers for MySmartBike BLE integration."""
import logging
from typing import Dict, Optional, Any

from .const import (
    BATTERY_MESSAGE_LENGTH,
    MOTOR_MESSAGE_LENGTH,
    EBM_MESSAGE_LENGTH,
    EBM_MAHLE_MARKER,
    MPLATFORM_DEVICE_BASE_CODES,
    NUMERIC_PROTOCOL_VERSIONS,
    PROTOCOL_EBM,
    PROTOCOL_V100,
    PROTOCOL_V200,
)

_LOGGER = logging.getLogger(__name__)


def normalize_protocol_version(version: Optional[str]) -> Optional[str]:
    """Fold a reported protocol string onto the id the Mahle SDK uses.

    The SDK compares the payload of `$s$P#...#@` against a fixed set of ids
    ("100", "102", "200", "300", "EBM"). Firmwares in the field also report the
    dotted spelling, so the separator is dropped before matching - "1.02" and
    "102" are the same protocol. Anything unrecognised returns None, and the
    parser then falls back to its length-based behaviour rather than guessing a
    layout.
    """
    if not version:
        return None

    candidate = version.strip().upper()
    if candidate == PROTOCOL_EBM:
        return PROTOCOL_EBM

    digits = candidate.replace(".", "")
    if digits in NUMERIC_PROTOCOL_VERSIONS:
        return digits

    _LOGGER.debug("Unrecognised protocol version %r - using default layouts", version)
    return None


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
    """Parser for bike BLE messages.

    Frame *length* alone does not identify a layout: protocols 100, 102, 200 and
    300 all broadcast 20-byte battery, motor and EBM frames, and each family
    reads some of those bytes differently. The protocol version the bike reports
    in answer to `$S$P#@` therefore selects the layout, with the length only
    separating the short ebikemotion (X25 / X35+) frames from the 20-byte ones.

    Until that answer arrives - the first notifications can beat it by a few
    hundred milliseconds on a fresh pairing - the 100/102/300 layouts are
    assumed, which is what this parser did unconditionally before. EBM frames
    are the exception: those carry a marker that identifies the layout on the
    wire, so they are decoded correctly from the very first packet.
    """

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
        self._protocol_version: Optional[str] = None
        self._protocol: Optional[str] = None

    @property
    def protocol_version(self) -> Optional[str]:
        """Return the version string exactly as the bike reported it.

        Kept verbatim because it is surfaced as the device's `sw_version`; use
        `protocol` for anything that has to make a decision.
        """
        return self._protocol_version

    @protocol_version.setter
    def protocol_version(self, value: Optional[str]) -> None:
        """Store the reported version and derive the layout id from it.

        A setter rather than a plain attribute so that restoring the persisted
        value - the coordinator assigns straight to this attribute before the
        first packet arrives - selects the right layouts too.
        """
        self._protocol_version = value
        self._protocol = normalize_protocol_version(value)

    @property
    def protocol(self) -> Optional[str]:
        """Return the normalized protocol id, or None while it is unknown."""
        return self._protocol

    def parse_battery_message(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse a battery frame with the layout the protocol version calls for."""
        if len(message) == 20:
            if self._protocol == PROTOCOL_V200:
                return self._parse_battery_v200(message)
            return self._parse_battery_mahle(message)
        if len(message) >= BATTERY_MESSAGE_LENGTH:
            return self._parse_battery_ebm(message)
        return None

    def _parse_battery_ebm(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse 19-byte battery frame (X25 / X35+ / ebikemotion).

        The current is the one field this layout reads *unsigned* - the newer
        protocols sign it, this one does not.
        """
        voltage = read16(message, 5) / 10.0
        soc = read_unsigned_byte(message[7])
        temp_status = read_signed_byte(message[8])
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

    def _read_battery_20b(self, message: bytes) -> Dict[str, Any]:
        """Read the fields every 20-byte battery frame shares (protocols 100-300).

        Only the SOC byte and what `battery_number == 0` means differ between
        the families, so the callers fill `soc` / `is_charging` in themselves.
        """
        return {
            "voltage": read16(message, 5) / 100.0,
            "soc": None,
            "temperature": read_signed_byte(message[8]),
            "temperature_mos": read_signed_byte(message[15]),
            "current": read16_signed(message, 9) / 10.0,
            "nominal_capacity": read16(message, 11) / 10.0,
            "remaining_wh": read16(message, 13) / 10.0,
            "cycles": read16(message, 16) % 10000,
            "is_charging": False,
        }

    @staticmethod
    def _battery_number(message: bytes) -> int:
        """Return which pack a 20-byte battery frame describes."""
        return read16(message, 16) // 10000

    def _parse_battery_mahle(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse the 20-byte battery frame of protocols 100 / 102 / 300.

        These read the SOC byte whole: charging is not reported at all here, the
        SDK hardcodes it false. Bit 7 therefore stays part of the value, which is
        harmless because a real state of charge never exceeds 100.
        """
        data = self._read_battery_20b(message)
        data["soc"] = read_unsigned_byte(message[7])
        self._store_battery(data, self._battery_number(message))
        return data

    def _parse_battery_v200(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse the 20-byte battery frame of protocol 200.

        Two things are unique to v200. Bit 7 of the SOC byte is a charging flag,
        and only for the primary pack - the SDK forces it false for a secondary
        one. And `battery_number == 0` is not a battery at all: the SDK logs it
        as "BP_aux_current info" and drops it. Letting those auxiliary readings
        through would have them overwrite the real pack, because everything that
        is not an explicit secondary battery counts as primary.
        """
        data = self._read_battery_20b(message)
        soc_raw = read_unsigned_byte(message[7])
        data["soc"] = soc_raw & 0x7F

        battery_number = self._battery_number(message)
        if battery_number == 0:
            _LOGGER.debug(
                "Ignoring v200 auxiliary current frame (V=%s, I=%s)",
                data["voltage"],
                data["current"],
            )
            return None

        data["is_charging"] = bool(soc_raw & 0x80) and battery_number == 1
        self._store_battery(data, battery_number)
        return data

    def _store_battery(self, data: Dict[str, Any], battery_number: int) -> None:
        """Update primary/secondary battery slots and the consecutive-primary counter.

        Callers filter out any frame that does not describe a pack first - only
        v200 has such frames - so anything arriving here is a real battery.
        """
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
        """Parse a motor frame with the layout the protocol version calls for."""
        if len(message) >= 20:
            if self._protocol == PROTOCOL_V100:
                return self._parse_motor_v100(message)
            return self._parse_motor_mahle(message)
        if len(message) >= MOTOR_MESSAGE_LENGTH:
            return self._parse_motor_ebm(message)
        return None

    def _parse_motor_ebm(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse 18-byte motor frame (X25 / X35+ / ebikemotion).

        Every byte-sized field here is signed, the temperature most visibly so:
        the bike reports 0xD8 = -40 °C while its sensor has no reading yet.
        """
        assist_level = read_signed_byte(message[5])
        temperature_celsius = read_signed_byte(message[6])
        power_amp = float(read16(message, 7)) / 10.0
        speed_kmh = float(read16(message, 9)) / 10.0
        wheel_speed = read_unsigned_byte(message[11])
        torque_pct = read_signed_byte(message[12])
        power_max = float(read16(message, 13)) / 10.0
        max_torque_pct = read_signed_byte(message[15])

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

    def _parse_motor_v100(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse the 20-byte motor frame of protocol 100.

        Same length as the 102/200/300 frame, different reading of bytes 7-13:
        7-8 is a current in amps rather than a motor power, 12-13 is a signed
        torque percentage rather than the rider's power, and the wheel speed is
        always valid here - the newer protocols gate it on `max_torque != 0`.
        """
        assist_level = read_signed_byte(message[5])
        temperature_celsius = read_signed_byte(message[6])
        power_amp = read16(message, 7) / 10.0
        speed_kmh = read16(message, 9) / 10.0
        wheel_speed = read_unsigned_byte(message[11])
        # Truncates towards zero, matching the SDK's integer division.
        torque_pct = int(read16_signed(message, 12) / 100)
        power_max_amp = read16(message, 14) / 10.0
        max_torque = read16(message, 16)

        data = {
            "assist_level": assist_level,
            "temperature_celsius": temperature_celsius,
            "power_amp": power_amp,
            "speed_kmh": speed_kmh,
            "wheel_speed_rpm": wheel_speed,
            "torque_motor_pct": torque_pct,
            "power_max_amp": power_max_amp,
            "max_torque_motor_pct": max_torque,
            "motor_power_watts": None,
            "rider_power_watts": None,
        }
        self.state["motor"] = data
        return data

    def _parse_motor_mahle(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse the 20-byte motor frame of protocols 102 / 200 / 300."""
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
        """Parse an EBM (E-Bike Management) frame with the right layout."""
        if len(message) >= 20:
            if self._ebm_frame_is_v200(message):
                return self._parse_ebm_v200(message)
            return self._parse_ebm_mahle(message)
        if len(message) >= EBM_MESSAGE_LENGTH:
            return self._parse_ebm_ebm(message)
        return None

    def _ebm_frame_is_v200(self, message: bytes) -> bool:
        """Decide which 20-byte EBM layout a frame uses.

        The reported protocol version settles it whenever we have one. Before the
        answer to `$S$P#@` arrives, fall back to the fixed `HIJ` marker that
        100/102/300 put in bytes 15-17: v200 spends those bytes on the slot
        indicator and the remote's state of charge, so the marker cannot be
        there. Guessing wrong would silently swap the odometer and trip readings,
        which is worth one byte comparison to avoid.
        """
        if self._protocol is not None:
            return self._protocol == PROTOCOL_V200
        return message[15:18] != EBM_MAHLE_MARKER

    def _ebm_slot_values(
        self, odometry_km: float, autonomy_km: float, slot: int
    ) -> Dict[str, Any]:
        """Split the multiplexed odometer/range onto the lifetime or trip A slot.

        Consecutive frames alternate: slot 2 carries trip A, anything else the
        lifetime totals. Whichever set this frame does not carry is taken from
        the previous one, so both stay populated.
        """
        prev = self.state.get("ebm") or {}

        if slot == 2:
            return {
                "odometry": prev.get("odometry"),
                "autonomy": prev.get("autonomy"),
                "trip_odometry": odometry_km,
                "trip_autonomy": autonomy_km,
            }
        return {
            "odometry": odometry_km,
            "autonomy": autonomy_km,
            "trip_odometry": prev.get("trip_odometry"),
            "trip_autonomy": prev.get("trip_autonomy"),
        }

    def _parse_ebm_ebm(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse 17-byte EBM frame (X25 / X35+ / ebikemotion)."""
        odometry_km = read32(message, 5) / 10000.0
        autonomy_km = read32(message, 9) / 10000.0
        is_light_on = message[13] == 1
        status = read_unsigned_byte(message[14])

        data = {
            "odometry": odometry_km,
            "autonomy": autonomy_km,
            "trip_odometry": None,
            "trip_autonomy": None,
            "is_light_on": is_light_on,
            "status": status,
            "error_code": status,
            "accel_y": None,
            "accel_z": None,
            "remote_connected": None,
            "remote_soc": None,
        }
        self.state["ebm"] = data
        return data

    def _parse_ebm_v200(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse the 20-byte EBM frame of protocol 200.

        v200 spends bytes 11-17 differently from every other protocol. An
        M-Platform error id and device id sit where 100/102/300 keep a plain
        error byte and the accelerometer, which pushes the accelerometer and the
        slot indicator one byte to the right and leaves room for the remote's
        state of charge at the end. Reading this frame with the other layout puts
        the slot indicator on an accelerometer axis, which shuffles lifetime and
        trip readings into each other.

        `error_code` is the number the app shows: the device's base offset plus
        the error id, so 204 is fault 4 on the internal battery.
        """
        odometry_km = read24(message, 5) / 10.0
        autonomy_km = read16(message, 8) / 10.0
        is_light_on = message[10] == 1
        error_id = read_unsigned_byte(message[11]) & 0x1F
        device_byte = read_unsigned_byte(message[12])
        accel_z = read_signed_byte(message[13])
        accel_y = read_signed_byte(message[14])
        slot = read_unsigned_byte(message[15])

        # 0xFFFF means no remote is paired; otherwise the second byte is its SOC.
        remote_connected = message[16] != 0xFF or message[17] != 0xFF

        data = self._ebm_slot_values(odometry_km, autonomy_km, slot)
        data.update(
            {
                "is_light_on": is_light_on,
                "status": error_id,
                "error_code": MPLATFORM_DEVICE_BASE_CODES.get(device_byte & 0x0F, 0)
                + error_id,
                "accel_y": accel_y,
                "accel_z": accel_z,
                "remote_connected": remote_connected,
                "remote_soc": read_unsigned_byte(message[17])
                if remote_connected
                else None,
            }
        )
        self.state["ebm"] = data
        return data

    def _parse_ebm_mahle(self, message: bytes) -> Optional[Dict[str, Any]]:
        """Parse the 20-byte EBM frame of protocols 100 / 102 / 300.

        The bike alternates between two slot indicators in byte 14:
        - slot == 1 → bytes 5-9 carry the LIFETIME odometer & range
        - slot == 2 → same bytes carry the current TRIP A distance & range

        Bytes 15-17 are a fixed `HIJ` (`0x48 0x49 0x4A`) marker before `#@`.
        These protocols report a bare error byte with no device attached, so the
        full error code is the error id itself.
        """
        odometry_km = read24(message, 5) / 10.0
        autonomy_km = read16(message, 8) / 10.0
        is_light_on = message[10] == 1
        status = read_unsigned_byte(message[11])
        accel_z = read_signed_byte(message[12])
        accel_y = read_signed_byte(message[13])
        slot = read_unsigned_byte(message[14])

        data = self._ebm_slot_values(odometry_km, autonomy_km, slot)
        data.update(
            {
                "is_light_on": is_light_on,
                "status": status,
                "error_code": status,
                "accel_y": accel_y,
                "accel_z": accel_z,
                "remote_connected": None,
                "remote_soc": None,
            }
        )
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
                # `$b$P` / `$b$R` are the power-source query and its ack on v102;
                # every other `$b$` frame is a battery broadcast.
                if sub_type == "P":
                    return "power_source"
                elif sub_type == "R":
                    return "power_source_set"
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
            elif main_type == "f":
                # Trio remote pairing, v102 and up.
                if sub_type == "C":
                    return "trio_connect"
                elif sub_type == "D":
                    return "trio_disconnect"
            elif main_type == "j" and sub_type == "Z":
                return "ebm"
            elif main_type == "m":
                if sub_type == "A":
                    return "assist"
                elif sub_type == "Z":
                    return "motor"
                elif sub_type == "G":
                    return "map_global"  # traction control / auto hold, v200
                elif sub_type == "M":
                    return "engine_maps"
                elif sub_type == "R":
                    return "reset_trip"
            elif main_type == "s":
                if sub_type == "V":
                    return "vin"
                elif sub_type == "P":
                    return "protocol"
                elif sub_type == "L":
                    return "blinking_lights"
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
            "map_global",
            "reset_trip",
            "calibrate",
            "security_challenge",
            "power_source",
            "power_source_set",
            "blinking_lights",
            "trio_connect",
            "trio_disconnect",
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
