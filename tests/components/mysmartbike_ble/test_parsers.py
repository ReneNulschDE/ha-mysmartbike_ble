"""Test the MySmartBike BLE parsers with real message data."""
import pytest

from custom_components.mysmartbike_ble.parsers import (
    BikeDataParser,
    normalize_protocol_version,
    read16,
    read16_signed,
    read24,
    read32,
    read_signed_byte,
    read_unsigned_byte,
)


def parser_for(protocol: str | None) -> BikeDataParser:
    """Return a parser that has already learned the bike's protocol version."""
    parser = BikeDataParser()
    parser.protocol_version = protocol
    return parser


class TestProtocolVersionNormalization:
    """The version string decides which frame layouts are used."""

    def test_bare_ids_pass_through(self):
        for value in ("100", "102", "200", "300"):
            assert normalize_protocol_version(value) == value

    def test_dotted_spelling_folds_onto_the_bare_id(self):
        """Firmwares report either "1.02" or "102" for the same protocol."""
        assert normalize_protocol_version("1.02") == "102"
        assert normalize_protocol_version("1.00") == "100"
        assert normalize_protocol_version("2.00") == "200"
        assert normalize_protocol_version("3.00") == "300"

    def test_ebm_is_recognised_case_insensitively(self):
        assert normalize_protocol_version("EBM") == "EBM"
        assert normalize_protocol_version("ebm") == "EBM"

    def test_unknown_and_empty_values_yield_none(self):
        """An unusable version must not pick a layout - the default applies."""
        assert normalize_protocol_version(None) is None
        assert normalize_protocol_version("") is None
        assert normalize_protocol_version("CONF") is None
        assert normalize_protocol_version("9.99") is None

    def test_assignment_derives_the_layout_id(self):
        """Restoring the persisted string must select layouts too."""
        parser = BikeDataParser()
        assert parser.protocol is None

        parser.protocol_version = "1.02"

        # The raw string is kept verbatim - it is the device's sw_version.
        assert parser.protocol_version == "1.02"
        assert parser.protocol == "102"

    def test_parsed_protocol_message_sets_the_layout_id(self):
        parser = BikeDataParser()
        parser.handle_message(b"$s$P#200#@")

        assert parser.protocol_version == "200"
        assert parser.protocol == "200"


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

    def test_signed_temperature(self):
        """Byte 6 is signed here too: 0xD8 is -40 °C, not 216 °C."""
        msg = bytearray(self.MOTOR_MESSAGE)
        msg[6] = 0xD8

        parser = BikeDataParser()
        result = parser.parse_motor_message(bytes(msg))

        assert result["temperature_celsius"] == -40

    def test_signed_torque_and_max_torque(self):
        """Bytes 12 and 15 are signed bytes in the SDK."""
        msg = bytearray(self.MOTOR_MESSAGE)
        msg[12] = 0xFF
        msg[15] = 0xFB

        parser = BikeDataParser()
        result = parser.parse_motor_message(bytes(msg))

        assert result["torque_motor_pct"] == -1
        assert result["max_torque_motor_pct"] == -5


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

    def test_v200_and_v300_share_this_layout(self):
        """Protocols 102, 200 and 300 read the motor frame identically."""
        results = [
            parser_for(version).parse_motor_message(self.MOTOR_MESSAGE)
            for version in ("102", "200", "300")
        ]

        assert results[0] == results[1] == results[2]


class TestMotorParserV100:
    """20-byte motor frame parsing under protocol 100.

    Same length as the 102/200/300 frame, but bytes 7-8 and 12-13 mean something
    else entirely - reading them with the newer layout turns 15 A of motor
    current into 1.5 W of motor power.
    """

    # assist 1, 22 °C, bytes 7-8 = 0x0096, bytes 12-13 = 0xFF38 (= -200),
    # power_max 9.0 A, max_torque 0x03FF.
    MOTOR_MESSAGE = bytes.fromhex("246d245a2301160096000000ff38005a03ff2340")

    def test_bytes_7_8_are_a_current(self):
        result = parser_for("100").parse_motor_message(self.MOTOR_MESSAGE)

        # 0x0096 = 150 / 10 = 15.0 A
        assert abs(result["power_amp"] - 15.0) < 0.01
        assert result["motor_power_watts"] is None

    def test_bytes_12_13_are_a_signed_torque_percentage(self):
        result = parser_for("100").parse_motor_message(self.MOTOR_MESSAGE)

        # 0xFF38 = -200 signed, / 100 truncated towards zero = -2
        assert result["torque_motor_pct"] == -2
        assert result["rider_power_watts"] is None

    def test_shared_fields_are_read_the_same_way(self):
        result = parser_for("100").parse_motor_message(self.MOTOR_MESSAGE)

        assert result["assist_level"] == 1
        assert result["temperature_celsius"] == 22
        assert result["speed_kmh"] == 0.0
        assert abs(result["power_max_amp"] - 9.0) < 0.01
        assert result["max_torque_motor_pct"] == 0x03FF

    def test_wheel_speed_is_not_gated_on_max_torque(self):
        """The newer protocols null the wheel speed when max_torque is 0; v100 doesn't."""
        msg = bytearray(self.MOTOR_MESSAGE)
        msg[11] = 0x2A
        msg[16], msg[17] = 0x00, 0x00

        v100 = parser_for("100").parse_motor_message(bytes(msg))
        v102 = parser_for("102").parse_motor_message(bytes(msg))

        assert v100["wheel_speed_rpm"] == 42
        assert v102["wheel_speed_rpm"] is None

    def test_newer_protocols_read_the_same_bytes_differently(self):
        """Regression: without the version, v100 frames were decoded as v102."""
        v102 = parser_for("102").parse_motor_message(self.MOTOR_MESSAGE)

        # 0x0096 / 100 as a motor power, 0xFF38 / 10 as the rider's power
        assert abs(v102["motor_power_watts"] - 1.5) < 0.01
        assert abs(v102["rider_power_watts"] - 6533.6) < 0.1


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

    def test_error_code_equals_the_status_byte(self):
        """No device id is attached on these protocols, so the code is the id."""
        msg = bytearray(self.EBM_LIFETIME)
        msg[11] = 0x2C

        parser = parser_for("102")
        result = parser.parse_ebm_message(bytes(msg))

        assert result["status"] == 0x2C
        assert result["error_code"] == 0x2C

    def test_no_remote_fields(self):
        """The remote's state of charge is a v200 addition."""
        result = parser_for("102").parse_ebm_message(self.EBM_LIFETIME)

        assert result["remote_connected"] is None
        assert result["remote_soc"] is None

    def test_v300_matches_v102(self):
        v102 = parser_for("102").parse_ebm_message(self.EBM_LIFETIME)
        v300 = parser_for("300").parse_ebm_message(self.EBM_LIFETIME)

        assert v102 == v300


class TestEbmParserV200:
    """20-byte EBM frame parsing under protocol 200.

    Bytes 11-17 carry an M-Platform error id and device id where 100/102/300
    keep a plain error byte and the accelerometer, which shifts the accelerometer
    and the slot indicator one byte right and leaves room for the remote's SOC.
    """

    # Odometer 13.2 km, range 73.7 km, lights off, error id 4 on the internal
    # battery, accel Z 1 / Y -11, slot 1 (lifetime), no remote paired.
    EBM_LIFETIME = bytes.fromhex("246a245a2300008402e100242201f501ffff2340")
    # Same frame with slot 2 (trip A).
    EBM_TRIP = bytes.fromhex("246a245a2300008402e100242201f502ffff2340")

    def test_message_length(self):
        assert len(self.EBM_LIFETIME) == 20

    def test_distances_are_read_like_the_other_protocols(self):
        result = parser_for("200").parse_ebm_message(self.EBM_LIFETIME)

        assert abs(result["odometry"] - 13.2) < 0.05
        assert abs(result["autonomy"] - 73.7) < 0.05

    def test_lights_flag(self):
        result = parser_for("200").parse_ebm_message(self.EBM_LIFETIME)
        assert result["is_light_on"] is False

        msg = bytearray(self.EBM_LIFETIME)
        msg[10] = 0x01
        assert parser_for("200").parse_ebm_message(bytes(msg))["is_light_on"] is True

    def test_error_id_is_masked_out_of_byte_11(self):
        """Only the low five bits of byte 11 are the error id."""
        result = parser_for("200").parse_ebm_message(self.EBM_LIFETIME)

        # 0x24 & 0x1F = 4
        assert result["status"] == 4

    def test_error_code_adds_the_device_base_offset(self):
        """Byte 12's low nibble names the device; the app shows base + id."""
        result = parser_for("200").parse_ebm_message(self.EBM_LIFETIME)

        # device 2 = internal battery (base 200) + error 4
        assert result["error_code"] == 204

    def test_error_code_for_the_drive_unit_is_the_bare_id(self):
        msg = bytearray(self.EBM_LIFETIME)
        msg[12] = 0x20  # device 0 = drive unit (base 0)

        result = parser_for("200").parse_ebm_message(bytes(msg))

        assert result["error_code"] == 4

    def test_accelerometer_axes_are_one_byte_right(self):
        result = parser_for("200").parse_ebm_message(self.EBM_LIFETIME)

        # message[13] = 0x01, message[14] = 0xF5 (signed = -11)
        assert result["accel_z"] == 1
        assert result["accel_y"] == -11

    def test_slot_indicator_is_at_offset_15(self):
        """Reading the slot from offset 14 would find an accelerometer axis."""
        parser = parser_for("200")
        parser.parse_ebm_message(self.EBM_LIFETIME)
        prev_odo = parser.state["ebm"]["odometry"]

        msg = bytearray(self.EBM_TRIP)
        msg[5], msg[6], msg[7] = 0x00, 0x00, 0x50  # trip = 8.0 km
        result = parser.parse_ebm_message(bytes(msg))

        assert result["trip_odometry"] == 8.0
        assert result["odometry"] == prev_odo

    def test_no_remote_paired(self):
        """0xFFFF in bytes 16-17 means no remote is connected."""
        result = parser_for("200").parse_ebm_message(self.EBM_LIFETIME)

        assert result["remote_connected"] is False
        assert result["remote_soc"] is None

    def test_remote_state_of_charge(self):
        msg = bytearray(self.EBM_LIFETIME)
        msg[16], msg[17] = 0x00, 0x2A

        result = parser_for("200").parse_ebm_message(bytes(msg))

        assert result["remote_connected"] is True
        assert result["remote_soc"] == 42

    def test_wrong_layout_would_shuffle_lifetime_and_trip(self):
        """Regression: the v102 layout reads this frame's slot off an accel axis."""
        wrong = parser_for("102").parse_ebm_message(self.EBM_LIFETIME)

        # byte 14 = 0xF5 != 2, so the v102 layout calls this a lifetime frame,
        # and it takes byte 11 whole (0x24 = 36) instead of masking it to 4.
        assert wrong["status"] == 36
        assert wrong["accel_z"] == 34  # byte 12, the v200 device/flags byte


class TestEbmLayoutDetection:
    """Which 20-byte EBM layout applies before the bike reports its protocol."""

    MAHLE_FRAME = bytes.fromhex("246a245a2300008402e1000001f50148494a2340")
    V200_FRAME = bytes.fromhex("246a245a2300008402e100242201f501ffff2340")

    def test_hij_marker_selects_the_mahle_layout(self):
        """Bytes 15-17 are a fixed `HIJ` on 100/102/300 and never on v200."""
        result = BikeDataParser().parse_ebm_message(self.MAHLE_FRAME)

        assert result["status"] == 0  # byte 11, the v102 error byte
        assert result["remote_connected"] is None

    def test_missing_marker_selects_the_v200_layout(self):
        result = BikeDataParser().parse_ebm_message(self.V200_FRAME)

        assert result["error_code"] == 204
        assert result["remote_connected"] is False

    def test_known_protocol_overrides_the_marker(self):
        """Once the bike has told us, the version wins over the sniff."""
        result = parser_for("102").parse_ebm_message(self.MAHLE_FRAME)

        assert result["remote_connected"] is None


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

    def test_battery_temperature_is_signed(self):
        """Byte 8 is signed: a pack below freezing must not read as 246 °C."""
        msg = bytearray(self.BATTERY_MESSAGE)
        msg[8] = 0xF6

        parser = BikeDataParser()
        result = parser.parse_battery_message(bytes(msg))

        assert result["temperature"] == -10

    def test_battery_current_is_unsigned(self):
        """The ebikemotion frame is the one layout that does not sign the current."""
        msg = bytearray(self.BATTERY_MESSAGE)
        msg[9], msg[10] = 0xFF, 0xEC

        parser = BikeDataParser()
        result = parser.parse_battery_message(bytes(msg))

        # 0xFFEC = 65516 / 10; the newer layouts would read this as -2.0 A
        assert abs(result["current"] - 6551.6) < 0.1

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

    def test_soc_byte_is_read_whole(self):
        """Only v200 puts a charging flag in bit 7; 100/102/300 read the byte whole.

        The SDK hardcodes `is_charging` to false for these protocols, so masking
        bit 7 off here would silently halve an out-of-range reading instead of
        surfacing it.
        """
        msg = bytearray(self.BATTERY_MESSAGE)
        msg[7] = 0x80 | 57

        parser = parser_for("102")
        result = parser.parse_battery_message(bytes(msg))

        assert result["soc"] == 0xB9
        assert result["is_charging"] is False

    def test_v300_uses_the_same_layout_as_v102(self):
        """v300 is byte-for-byte identical to v102 for every broadcast frame."""
        v102 = parser_for("102").parse_battery_message(self.BATTERY_MESSAGE)
        v300 = parser_for("300").parse_battery_message(self.BATTERY_MESSAGE)

        assert v102 == v300


class TestBatteryParserV200:
    """20-byte battery frame parsing under protocol 200."""

    # Same wire bytes as the v102 frame: voltage 37.78 V, SOC 57 %, temp 22 °C,
    # nominal 352.8 Wh, remaining 200.3 Wh, MOSFET temp 24 °C, battery 1 / 5 cycles.
    BATTERY_MESSAGE = bytes.fromhex("2462245a230ec2391600000dc807d31827152340")

    def test_shared_fields_match_the_other_protocols(self):
        """Everything except the SOC byte is read identically."""
        result = parser_for("200").parse_battery_message(self.BATTERY_MESSAGE)

        assert abs(result["voltage"] - 37.78) < 0.01
        assert result["temperature"] == 22
        assert result["temperature_mos"] == 24
        assert abs(result["nominal_capacity"] - 352.8) < 0.1
        assert abs(result["remaining_wh"] - 200.3) < 0.1
        assert result["cycles"] == 5

    def test_charging_bit_in_soc_byte(self):
        """Bit 7 of the SOC byte is a charging flag, and SOC is masked out of it."""
        msg = bytearray(self.BATTERY_MESSAGE)
        msg[7] = 0x80 | 57  # charging flag + 57 % SOC

        result = parser_for("200").parse_battery_message(bytes(msg))

        assert result["is_charging"] is True
        assert result["soc"] == 57

    def test_not_charging_when_bit_clear(self):
        result = parser_for("200").parse_battery_message(self.BATTERY_MESSAGE)

        assert result["is_charging"] is False
        assert result["soc"] == 57

    def test_secondary_battery_never_reports_charging(self):
        """The SDK forces the flag false for the secondary pack."""
        msg = bytearray(self.BATTERY_MESSAGE)
        msg[7] = 0x80 | 57
        msg[16], msg[17] = 0x4E, 0x25  # 20005 → battery 2, 5 cycles

        parser = parser_for("200")
        parser.parse_battery_message(bytes(msg))

        assert parser.state["battery_secondary"]["is_charging"] is False

    def test_auxiliary_frame_is_discarded(self):
        """`battery_number == 0` is an auxiliary current reading, not a pack.

        Storing it would let it overwrite the real primary battery, because
        anything that is not an explicit secondary battery counts as primary.
        """
        primary = bytearray(self.BATTERY_MESSAGE)
        aux = bytearray(self.BATTERY_MESSAGE)
        aux[7] = 12  # a wildly different SOC we must not see
        aux[16], aux[17] = 0x00, 0x05  # 5 → battery number 0

        parser = parser_for("200")
        parser.parse_battery_message(bytes(primary))
        result = parser.parse_battery_message(bytes(aux))

        assert result is None
        assert parser.state["battery_primary"]["soc"] == 57

    def test_auxiliary_frame_is_a_battery_for_the_other_protocols(self):
        """Only v200 sends auxiliary frames; elsewhere 0 stays the lenient default.

        Single-battery bikes whose firmware leaves the number at zero would
        otherwise have every battery sensor stuck on unknown.
        """
        msg = bytearray(self.BATTERY_MESSAGE)
        msg[16], msg[17] = 0x00, 0x05

        parser = parser_for("102")
        result = parser.parse_battery_message(bytes(msg))

        assert result is not None
        assert parser.state["battery_primary"]["soc"] == 57


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


class TestMessageTypeRecognition:
    """Frames the newer protocols added must not be mistaken for broadcasts."""

    def test_power_source_frames_are_not_batteries(self):
        """`$b$P` / `$b$R` share the `b` type with the battery broadcast."""
        parser = BikeDataParser()

        assert parser.recognize_message_type(b"$b$P#1#@") == "power_source"
        assert parser.recognize_message_type(b"$b$R#1#@") == "power_source_set"

    def test_battery_broadcast_still_recognised(self):
        parser = BikeDataParser()

        assert parser.recognize_message_type(b"$b$Z#0123456789abc#@") == "battery"

    def test_trio_remote_frames(self):
        parser = BikeDataParser()

        assert parser.recognize_message_type(b"$f$C#OK#@") == "trio_connect"
        assert parser.recognize_message_type(b"$f$D#OK#@") == "trio_disconnect"

    def test_map_global_and_blinking_lights(self):
        parser = BikeDataParser()

        assert parser.recognize_message_type(b"$m$G#0000#@") == "map_global"
        assert parser.recognize_message_type(b"$s$LFB#1#@") == "blinking_lights"

    def test_new_types_do_not_reach_a_broadcast_parser(self):
        """handle_message must log them, not feed them to a frame parser."""
        parser = BikeDataParser()
        parser.handle_message(b"$b$P#1#@")

        assert parser.state["battery_primary"] is None
