# MySmartBike BLE Integration for Home Assistant

[![GitHub release](https://img.shields.io/github/release/renenulschde/ha-mysmartbike_ble.svg)](https://github.com/renenulschde/ha-mysmartbike_ble/releases)

Home Assistant custom component for E-Bikes with Mahle SmartBike systems (X25, X35+, ebikemotion, ...) via Bluetooth Low Energy (BLE).

Many premium E-Bike brands use Mahle drive systems and the MySmartBike app for connectivity. This integration works with bikes from various manufacturers including Schindelhauer, Orbea, Bianchi, Pinarello, Scott, and others that use the Mahle BLE protocol.

## Tested Bikes

This integration has been developed and tested with:

| Brand | Model | Status |
|-------|-------|--------|
| Schindelhauer | Arthur IX | Fully tested |

**Your bike not listed?** If you have an E-Bike that uses the MySmartBike app (or ebikemotion app), it will likely work with this integration. Please open an issue to report compatibility!

## Features

This integration provides real-time monitoring of your E-Bike through Bluetooth LE connection with 11 sensors, 1 binary sensor, and 1 switch:

### Connection Control

- **Connection Switch** - Control the BLE connection to your E-Bike
  - Turning off this switch will disconnect from the bike and **the bike will shut down after approximately 5 minutes**. You must manually turn the bike back on or connect it to power to reconnect!
  - Use this switch to save energy when you don't need active monitoring
  - The bike will automatically turn off about 5 minutes after disconnection to conserve battery

- **Connected** (Binary Sensor) - Shows current BLE connection status to the bike

### Battery Sensors
- **Battery State of Charge** (%)
- **Battery Temperature** (°C)
- **Battery Remaining Energy** (Wh)

### Motor Sensors
- **Assist Level**
- **Motor Temperature** (°C)
- **Speed** (km/h)

### E-Bike Management (EBM)
- **Odometer** (km)
- **Range** (km)
- **Light Status**

### Device Information
The integration automatically retrieves and displays:
- **Serial Number** (VIN) - 17-character bike serial number
- **Protocol Version** - BLE protocol version (e.g., 1.02, 3.00)

## Requirements

- Home Assistant 2024.1.6 or newer
- Bluetooth adapter with BLE support
- Bluetooth proxies with active connections are supported (ex. EspHome) - Shelly is not support as active direct connections are not possible.
- E-Bike with Mahle SmartBike system (compatible with MySmartBike or ebikemotion app)

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/renenulschde/ha-mysmartbike-ble`
6. Select category "Integration"
7. Click "Add"
8. Search for "MySmartBike BLE" in HACS
9. Click "Download"
10. Restart Home Assistant

### Manual Installation

1. Download the latest release from the [releases page](https://github.com/renenulschde/ha-mysmartbike-ble/releases)
2. Extract the files
3. Copy the `custom_components/mysmartbike_ble` folder to your Home Assistant `custom_components` directory
4. Restart Home Assistant

## Configuration

The integration is configured through the Home Assistant UI:

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for **MySmartBike BLE**
4. Select your iWoc device from the list
5. Click **Submit**

The integration will automatically discover iWoc devices in range via Bluetooth.

## Troubleshooting

### Device not found

- Make sure your E-Bike is turned on and in range
- Check that Bluetooth is enabled on your Home Assistant host
- Verify that the device name starts with "iWoc" (please report other device names)

### Connection issues

- Ensure no other device is connected to the E-Bike via Bluetooth
- Try restarting the Bluetooth service on your Home Assistant host
- Check the Home Assistant logs for detailed error messages

### Sensor values not updating

- The integration updates data every 30 seconds when connected
- Some sensors may show "Unknown" until the bike sends that specific data
- Check if the bike is actively transmitting data (try riding or using the display)

### Connection Switch

- **To disconnect**: Turn off the "Connection" switch in Home Assistant
  - ⚠️ This will shut down your bike after approximately 5 minutes!
  - The bike will remain on for about 5 minutes before automatically powering off
- **To reconnect**:
  1. First, manually turn on your bike OR connect it to power
  2. Wait for the bike to be fully powered on
  3. Turn on the "Connection" switch in Home Assistant
- **Use case**: Turn off the connection when you don't need monitoring to save your bike's battery


### Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This is an unofficial integration and is not affiliated with or endorsed by Mahle, Schindelhauer, Orbea, or any other E-Bike manufacturer. Use at your own risk.
