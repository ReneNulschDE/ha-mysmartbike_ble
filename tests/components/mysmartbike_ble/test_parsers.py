"""Test the MySmartBike BLE parsers with real message data."""
import pytest

from custom_components.mysmartbike_ble.parsers import (
    BikeDataParser,
    read16,
    read24,
    read32,
    read_unsigned_byte,
)


class TestReadFunctions:
    """Test byte reading functions (big-endian)."""

    def test_read16_big_endian(self):
        """Test 16-bit big-endian read."""
        # Big-endian: first byte is most significant
        data = bytes([0x12, 0x34])
        assert read16(data, 0) == 0x1234

    def test_read24_big_endian(self):
        """Test 24-bit big-endian read."""
        data = bytes([0x12, 0x34, 0x56])
        assert read24(data, 0) == 0x123456

    def test_read32_big_endian(self):
        """Test 32-bit big-endian read."""
        data = bytes([0x12, 0x34, 0x56, 0x78])
        assert read32(data, 0) == 0x12345678

    def test_read_unsigned_byte(self):
        """Test unsigned byte read."""
        assert read_unsigned_byte(0xFF) == 255
        assert read_unsigned_byte(0x00) == 0
        assert read_unsigned_byte(0x7F) == 127


class TestEbmParser:
    """Test EBM message parsing with real data."""

    # Real EBM message from log: 246a245a230056af68000bef6f00002340
    # Expected: Odometer ~568.1 km, Range ~78.2 km
    EBM_MESSAGE = bytes.fromhex("246a245a230056af68000bef6f00002340")

    def test_ebm_message_recognition(self):
        """Test that EBM message type is recognized."""
        parser = BikeDataParser()
        msg_type = parser.recognize_message_type(self.EBM_MESSAGE)
        assert msg_type == "ebm"

    def test_ebm_odometry_parsing(self):
        """Test odometry value parsing from real EBM message."""
        parser = BikeDataParser()
        result = parser.parse_ebm_message(self.EBM_MESSAGE)

        assert result is not None
        # Odometry: 0x0056af68 = 5681000 / 10000 = 568.1 km
        assert abs(result["odometry"] - 568.1) < 0.1

    def test_ebm_autonomy_parsing(self):
        """Test autonomy/range value parsing from real EBM message."""
        parser = BikeDataParser()
        result = parser.parse_ebm_message(self.EBM_MESSAGE)

        assert result is not None
        # Autonomy: 0x000bef6f = 782191 / 10000 = 78.2 km
        assert abs(result["autonomy"] - 78.2) < 0.1

    def test_ebm_light_status(self):
        """Test light status parsing from real EBM message."""
        parser = BikeDataParser()
        result = parser.parse_ebm_message(self.EBM_MESSAGE)

        assert result is not None
        # Byte 13 = 0x00, so light is off
        assert result["is_light_on"] is False

    def test_ebm_state_update(self):
        """Test that parser state is updated after parsing."""
        parser = BikeDataParser()
        parser.parse_ebm_message(self.EBM_MESSAGE)

        assert parser.state["ebm"] is not None
        assert "odometry" in parser.state["ebm"]
        assert "autonomy" in parser.state["ebm"]


class TestMotorParser:
    """Test motor message parsing with real data."""

    # Real motor message from log: 246d245a230117000000000000004f642340
    MOTOR_MESSAGE = bytes.fromhex("246d245a230117000000000000004f642340")

    def test_motor_message_recognition(self):
        """Test that motor message type is recognized."""
        parser = BikeDataParser()
        msg_type = parser.recognize_message_type(self.MOTOR_MESSAGE)
        assert msg_type == "motor"

    def test_motor_parsing(self):
        """Test motor value parsing from real message."""
        parser = BikeDataParser()
        result = parser.parse_motor_message(self.MOTOR_MESSAGE)

        assert result is not None
        # Assist level at byte 5 = 0x01
        assert result["assist_level"] == 1
        # Temperature at byte 6 = 0x17 = 23°C
        assert result["temperature_celsius"] == 23


class TestBatteryParser:
    """Test battery message parsing with real data."""

    # Real battery message from log: 2462245a230193541700000877071a27342340
    BATTERY_MESSAGE = bytes.fromhex("2462245a230193541700000877071a27342340")

    def test_battery_message_recognition(self):
        """Test that battery message type is recognized."""
        parser = BikeDataParser()
        msg_type = parser.recognize_message_type(self.BATTERY_MESSAGE)
        assert msg_type == "battery"

    def test_battery_voltage(self):
        """Test battery voltage parsing."""
        parser = BikeDataParser()
        result = parser.parse_battery_message(self.BATTERY_MESSAGE)

        assert result is not None
        # Voltage: 0x0193 = 403 / 10 = 40.3 V
        assert abs(result["voltage"] - 40.3) < 0.1

    def test_battery_soc(self):
        """Test battery state of charge parsing."""
        parser = BikeDataParser()
        result = parser.parse_battery_message(self.BATTERY_MESSAGE)

        assert result is not None
        # SoC at byte 7 = 0x54 = 84%
        assert result["soc"] == 84

    def test_battery_temperature(self):
        """Test battery temperature parsing."""
        parser = BikeDataParser()
        result = parser.parse_battery_message(self.BATTERY_MESSAGE)

        assert result is not None
        # Temperature at byte 8 = 0x17 = 23
        assert result["temperature"] == 23

    def test_battery_current(self):
        """Test battery current parsing."""
        parser = BikeDataParser()
        result = parser.parse_battery_message(self.BATTERY_MESSAGE)

        assert result is not None
        # Current: 0x0000 = 0 / 10 = 0.0 A
        assert result["current"] == 0.0

    def test_battery_capacity(self):
        """Test battery nominal capacity parsing."""
        parser = BikeDataParser()
        result = parser.parse_battery_message(self.BATTERY_MESSAGE)

        assert result is not None
        # Nominal capacity: 0x0877 = 2167 / 10 = 216.7 Wh
        assert abs(result["nominal_capacity"] - 216.7) < 0.1

    def test_battery_remaining(self):
        """Test battery remaining energy parsing."""
        parser = BikeDataParser()
        result = parser.parse_battery_message(self.BATTERY_MESSAGE)

        assert result is not None
        # Remaining Wh: 0x071a = 1818 / 10 = 181.8 Wh
        assert abs(result["remaining_wh"] - 181.8) < 0.1

    def test_battery_cycles(self):
        """Test battery cycles parsing."""
        parser = BikeDataParser()
        result = parser.parse_battery_message(self.BATTERY_MESSAGE)

        assert result is not None
        # Cycles: 0x2734 = 10036, cycles = 10036 % 10000 = 36
        assert result["cycles"] == 36

    def test_battery_number_detection(self):
        """Test primary/secondary battery detection."""
        parser = BikeDataParser()
        parser.parse_battery_message(self.BATTERY_MESSAGE)

        # Battery number = 10036 / 10000 = 1 (primary)
        assert parser.state["battery_primary"] is not None
        assert parser.state["battery_primary"]["cycles"] == 36


class TestVinParser:
    """Test VIN/serial number message parsing."""

    # Example VIN message: $s$V#SB000000002207203#@
    # Hex: 24 73 24 56 23 + serial + 23 40
    VIN_SERIAL = "SB000000002207203"
    VIN_MESSAGE = f"$s$V#{VIN_SERIAL}#@".encode("utf-8")

    def test_vin_message_recognition(self):
        """Test that VIN message type is recognized."""
        parser = BikeDataParser()
        msg_type = parser.recognize_message_type(self.VIN_MESSAGE)
        assert msg_type == "vin"

    def test_vin_parsing_standard_format(self):
        """Test VIN parsing from standard format $s$V#<serial>#@."""
        parser = BikeDataParser()
        result = parser.parse_vin_message(self.VIN_MESSAGE)

        assert result == self.VIN_SERIAL
        assert parser.vin == self.VIN_SERIAL

    def test_vin_parsing_r0_format(self):
        """Test VIN parsing from R0 format (20 chars ending with @)."""
        parser = BikeDataParser()
        # R0 format: R0<17 char serial>@
        serial = "AB123456789012345"
        message = f"R0{serial}@".encode("utf-8")

        result = parser.parse_vin_message(message)

        assert result == serial
        assert parser.vin == serial

    def test_vin_handle_message_updates_state(self):
        """Test that handle_message updates VIN state."""
        parser = BikeDataParser()
        parser.handle_message(self.VIN_MESSAGE)

        assert parser.vin == self.VIN_SERIAL


class TestAssistParser:
    """Test assist level message parsing with real data."""

    # Real assist message from log: 246d2441233033312340
    ASSIST_MESSAGE = bytes.fromhex("246d2441233033312340")

    def test_assist_message_recognition(self):
        """Test that assist message type is recognized."""
        parser = BikeDataParser()
        msg_type = parser.recognize_message_type(self.ASSIST_MESSAGE)
        assert msg_type == "assist"

    def test_assist_parsing(self):
        """Test assist level parsing from real message."""
        parser = BikeDataParser()
        result = parser.parse_assist_level_message(self.ASSIST_MESSAGE)

        assert result is not None
        # Message is "031" which means min=0, max=3, current=1
        assert result["min"] == 0
        assert result["max"] == 3
        assert result["current"] == 1


class TestProtocolParser:
    """Test protocol version message parsing."""

    # Protocol message format: $s$P#<version>#@
    PROTOCOL_MESSAGE_V102 = b"$s$P#1.02#@"
    PROTOCOL_MESSAGE_V100 = b"$s$P#1.00#@"
    PROTOCOL_MESSAGE_V300 = b"$s$P#3.00#@"
    PROTOCOL_MESSAGE_ERROR = b"$s$P#ER#@"

    def test_protocol_message_recognition(self):
        """Test that protocol message type is recognized."""
        parser = BikeDataParser()
        msg_type = parser.recognize_message_type(self.PROTOCOL_MESSAGE_V102)
        assert msg_type == "protocol"

    def test_protocol_parsing_v102(self):
        """Test protocol version 1.02 parsing."""
        parser = BikeDataParser()
        result = parser.parse_protocol_message(self.PROTOCOL_MESSAGE_V102)

        assert result == "1.02"
        assert parser.protocol_version == "1.02"

    def test_protocol_parsing_v100(self):
        """Test protocol version 1.00 parsing."""
        parser = BikeDataParser()
        result = parser.parse_protocol_message(self.PROTOCOL_MESSAGE_V100)

        assert result == "1.00"
        assert parser.protocol_version == "1.00"

    def test_protocol_parsing_v300(self):
        """Test protocol version 3.00 parsing."""
        parser = BikeDataParser()
        result = parser.parse_protocol_message(self.PROTOCOL_MESSAGE_V300)

        assert result == "3.00"
        assert parser.protocol_version == "3.00"

    def test_protocol_parsing_error(self):
        """Test protocol error response handling."""
        parser = BikeDataParser()
        result = parser.parse_protocol_message(self.PROTOCOL_MESSAGE_ERROR)

        assert result is None
        assert parser.protocol_version is None

    def test_protocol_handle_message_updates_state(self):
        """Test that handle_message updates protocol version."""
        parser = BikeDataParser()
        parser.handle_message(self.PROTOCOL_MESSAGE_V102)

        assert parser.protocol_version == "1.02"
