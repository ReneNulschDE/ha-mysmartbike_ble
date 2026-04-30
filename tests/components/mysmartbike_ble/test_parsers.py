"""Test the MySmartBike BLE parsers with real message data."""
import pytest

from custom_components.mysmartbike_ble.parsers import (
    BikeDataParser,
    read16,
    read16_signed,
    read24,
    read32,
    read_signed_byte,
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

    def test_read_signed_byte(self):
        """Test signed byte read."""
        assert read_signed_byte(0x00) == 0
        assert read_signed_byte(0x7F) == 127
        assert read_signed_byte(0x80) == -128
        assert read_signed_byte(0xFF) == -1

    def test_read16_signed(self):
        """Test 16-bit signed read (big-endian)."""
        # Positive: 0x0001 → 1
        assert read16_signed(bytes([0x00, 0x01]), 0) == 1
        # Boundary: 0x7FFF → 32767
        assert read16_signed(bytes([0x7F, 0xFF]), 0) == 32767
        # Negative: 0x8000 → -32768
        assert read16_signed(bytes([0x80, 0x00]), 0) == -32768
        # -1: 0xFFFF
        assert read16_signed(bytes([0xFF, 0xFF]), 0) == -1


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


class TestMotorParserX20:
    """20-byte motor frame parsing (X20 / HUS-prefixed devices)."""

    # Real frame at rest: assist 1, 22 °C, zero power/speed, max_torque 0x03FF
    # (the bike's idle sentinel), power_max_amp 9.0 A.
    MOTOR_MESSAGE = bytes.fromhex("246d245a23011600000000000000005a03ff2340")

    # First packet after connect: temp byte 0xD8 = -40 signed (no-sensor sentinel).
    MOTOR_MESSAGE_BOOT = bytes.fromhex("246d245a2301d800000000000000005a03ff2340")

    def test_recognition(self):
        parser = BikeDataParser()
        assert parser.recognize_message_type(self.MOTOR_MESSAGE) == "motor"

    def test_assist_level_and_temperature(self):
        parser = BikeDataParser()
        result = parser.parse_motor_message(self.MOTOR_MESSAGE)

        assert result["assist_level"] == 1
        assert result["temperature_celsius"] == 22

    def test_signed_temperature_handles_no_sensor_sentinel(self):
        """0xD8 must decode as -40 °C (signed), not 216 °C (unsigned)."""
        parser = BikeDataParser()
        result = parser.parse_motor_message(self.MOTOR_MESSAGE_BOOT)

        assert result["temperature_celsius"] == -40

    def test_speed_and_power(self):
        parser = BikeDataParser()
        result = parser.parse_motor_message(self.MOTOR_MESSAGE)

        assert result["speed_kmh"] == 0.0
        assert result["motor_power_watts"] == 0.0
        assert result["rider_power_watts"] == 0.0
        # power_max_amp = 0x005A / 10 = 9.0 A
        assert abs(result["power_max_amp"] - 9.0) < 0.01

    def test_max_torque_uses_offset_16(self):
        """max_torque is a 16-bit raw value at offset 16-17 (= 0x03FF)."""
        parser = BikeDataParser()
        result = parser.parse_motor_message(self.MOTOR_MESSAGE)

        assert result["max_torque_motor_pct"] == 0x03FF

    def test_wheel_speed_returned_when_max_torque_nonzero(self):
        parser = BikeDataParser()
        result = parser.parse_motor_message(self.MOTOR_MESSAGE)

        # max_torque = 0x03FF != 0 → wheel_speed byte (0x00) is returned
        assert result["wheel_speed_rpm"] == 0

    def test_wheel_speed_nulled_when_max_torque_zero(self):
        """When max_torque == 0, wheel_speed must be None."""
        msg = bytearray(self.MOTOR_MESSAGE)
        msg[16] = 0x00
        msg[17] = 0x00

        parser = BikeDataParser()
        result = parser.parse_motor_message(bytes(msg))

        assert result["wheel_speed_rpm"] is None

    def test_x20_specific_fields_replace_legacy(self):
        """The X20 frame doesn't carry power_amp / torque_motor_pct."""
        parser = BikeDataParser()
        result = parser.parse_motor_message(self.MOTOR_MESSAGE)

        assert result["power_amp"] is None
        assert result["torque_motor_pct"] is None
        assert "motor_power_watts" in result
        assert "rider_power_watts" in result


class TestEbmParserX20:
    """20-byte EBM frame parsing (X20 / HUS-prefixed devices).

    Field offsets verified against an app-confirmed capture:
    - Odometer 0x000084 / 10 = 13.2 km  (app shows 8.08 mi = 13.005 km)
    - Range    0x02E1   / 10 = 73.7 km  (app shows 45 mi   = 72.42 km)
    """

    # Slot 1 frame = lifetime values
    EBM_LIFETIME = bytes.fromhex("246a245a2300008402e1000001f50148494a2340")
    # Slot 2 frame = trip values; same bike, same odometer/autonomy bytes →
    # trip A == lifetime (no reset since first ride).
    EBM_TRIP = bytes.fromhex("246a245a2300008402e1000001f50248494a2340")

    def test_message_length(self):
        assert len(self.EBM_LIFETIME) == 20

    def test_recognition(self):
        parser = BikeDataParser()
        assert parser.recognize_message_type(self.EBM_LIFETIME) == "ebm"

    def test_lifetime_odometer(self):
        """Odometer is a 24-bit field at offset 5 with /10 km scaling."""
        parser = BikeDataParser()
        result = parser.parse_ebm_message(self.EBM_LIFETIME)

        # 0x000084 / 10 = 13.2 km (app: 8.08 mi = 13.005 km)
        assert abs(result["odometry"] - 13.2) < 0.05

    def test_lifetime_autonomy(self):
        """Range is a 16-bit field at offset 8 with /10 km scaling."""
        parser = BikeDataParser()
        result = parser.parse_ebm_message(self.EBM_LIFETIME)

        # 0x02E1 / 10 = 73.7 km (app: 45 mi = 72.42 km)
        assert abs(result["autonomy"] - 73.7) < 0.05

    def test_lights_off_at_offset_10(self):
        """Lights flag moved from offset 13 to offset 10 in the X20 layout."""
        parser = BikeDataParser()
        result = parser.parse_ebm_message(self.EBM_LIFETIME)

        # message[10] = 0x00 → off
        assert result["is_light_on"] is False

    def test_lights_on(self):
        msg = bytearray(self.EBM_LIFETIME)
        msg[10] = 0x01

        parser = BikeDataParser()
        result = parser.parse_ebm_message(bytes(msg))

        assert result["is_light_on"] is True

    def test_status_byte(self):
        """Status moved from offset 14 to offset 11."""
        parser = BikeDataParser()
        result = parser.parse_ebm_message(self.EBM_LIFETIME)

        # message[11] = 0x00
        assert result["status"] == 0

    def test_accelerometer_axes(self):
        """Bytes 12-13 carry accelerometer Z/Y as signed bytes."""
        parser = BikeDataParser()
        result = parser.parse_ebm_message(self.EBM_LIFETIME)

        # message[12] = 0x01, message[13] = 0xF5 (signed = -11)
        assert result["accel_z"] == 1
        assert result["accel_y"] == -11

    def test_slot_2_updates_trip_only(self):
        """Slot 2 frames carry trip A values; lifetime fields stay at previous."""
        parser = BikeDataParser()
        # First ingest a slot 1 frame so we have a previous lifetime
        parser.parse_ebm_message(self.EBM_LIFETIME)
        prev_odo = parser.state["ebm"]["odometry"]

        # Now a slot 2 frame with different bytes (mock a real trip distance)
        msg = bytearray(self.EBM_TRIP)
        # Set trip odometer to 0x000050 = 80 → 8.0 km
        msg[5], msg[6], msg[7] = 0x00, 0x00, 0x50
        result = parser.parse_ebm_message(bytes(msg))

        assert result["trip_odometry"] == 8.0
        assert result["odometry"] == prev_odo  # lifetime preserved

    def test_slot_1_updates_lifetime_preserves_trip(self):
        """A slot 1 frame must not clobber the previously seen trip values."""
        parser = BikeDataParser()
        # First a slot 2 frame to populate trip_*
        msg2 = bytearray(self.EBM_TRIP)
        msg2[5], msg2[6], msg2[7] = 0x00, 0x00, 0x50  # trip = 8.0 km
        parser.parse_ebm_message(bytes(msg2))
        assert parser.state["ebm"]["trip_odometry"] == 8.0

        # Now a slot 1 frame
        result = parser.parse_ebm_message(self.EBM_LIFETIME)

        assert result["trip_odometry"] == 8.0  # preserved
        assert abs(result["odometry"] - 13.2) < 0.05


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


class TestBatteryParserX20:
    """20-byte battery frame parsing (X20 / HUS-prefixed devices)."""

    # Real frame from a HUS device: voltage 37.78 V, SOC 57 %, temp 22 °C,
    # current 0 A, nominal 352.8 Wh, remaining 200.3 Wh, MOSFET temp 24 °C,
    # combined cycles 0x2715 = 10005 → battery 1, 5 cycles.
    BATTERY_MESSAGE = bytes.fromhex("2462245a230ec2391600000dc807d31827152340")

    def test_message_length(self):
        assert len(self.BATTERY_MESSAGE) == 20

    def test_recognition(self):
        parser = BikeDataParser()
        assert parser.recognize_message_type(self.BATTERY_MESSAGE) == "battery"

    def test_voltage_uses_centi_volt_scaling(self):
        """Voltage on the 20-byte frame is encoded as raw / 100 (vs raw / 10 on 19-byte)."""
        parser = BikeDataParser()
        result = parser.parse_battery_message(self.BATTERY_MESSAGE)

        assert result is not None
        assert abs(result["voltage"] - 37.78) < 0.01

    def test_soc(self):
        """SOC is the unsigned byte at offset 7 with bit 7 masked off."""
        parser = BikeDataParser()
        result = parser.parse_battery_message(self.BATTERY_MESSAGE)

        assert result["soc"] == 57
        assert result["is_charging"] is False

    def test_temperature(self):
        parser = BikeDataParser()
        result = parser.parse_battery_message(self.BATTERY_MESSAGE)

        assert result["temperature"] == 22

    def test_current_is_zero_at_rest(self):
        """Current is signed read16 / 10."""
        parser = BikeDataParser()
        result = parser.parse_battery_message(self.BATTERY_MESSAGE)

        assert result["current"] == 0.0

    def test_capacity_and_remaining(self):
        parser = BikeDataParser()
        result = parser.parse_battery_message(self.BATTERY_MESSAGE)

        assert abs(result["nominal_capacity"] - 352.8) < 0.1
        assert abs(result["remaining_wh"] - 200.3) < 0.1

    def test_temperature_mos(self):
        """A BMS MOSFET temperature byte sits at offset 15."""
        parser = BikeDataParser()
        result = parser.parse_battery_message(self.BATTERY_MESSAGE)

        # 0x18 = 24°C
        assert result["temperature_mos"] == 24

    def test_cycles_at_offset_16(self):
        """(battery_number * 10000 + cycles) is read at offset 16-17, not 15-16."""
        parser = BikeDataParser()
        result = parser.parse_battery_message(self.BATTERY_MESSAGE)

        # 0x2715 = 10005 → battery 1, 5 cycles
        assert result["cycles"] == 5

    def test_primary_state_is_set(self):
        """Regression: reading the combined field at offset 15 would compute
        battery_number == 0 here and silently drop the update."""
        parser = BikeDataParser()
        parser.parse_battery_message(self.BATTERY_MESSAGE)

        assert parser.state["battery_primary"] is not None
        assert parser.state["battery_primary"]["soc"] == 57

    def test_signed_current_when_charging(self):
        """A negative raw current value should decode as negative amps."""
        # Replace bytes 9-10 with 0xFFEC (= -20 raw → -2.0 A)
        msg = bytearray(self.BATTERY_MESSAGE)
        msg[9] = 0xFF
        msg[10] = 0xEC

        parser = BikeDataParser()
        result = parser.parse_battery_message(bytes(msg))

        assert abs(result["current"] - (-2.0)) < 0.001

    def test_charging_bit_in_soc_byte(self):
        """When the SOC byte's bit 7 is set, is_charging is True and SOC is masked."""
        msg = bytearray(self.BATTERY_MESSAGE)
        msg[7] = 0x80 | 57  # charging flag + 57% SOC

        parser = BikeDataParser()
        result = parser.parse_battery_message(bytes(msg))

        assert result["is_charging"] is True
        assert result["soc"] == 57


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
