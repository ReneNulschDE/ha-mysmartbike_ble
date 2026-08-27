# MySmartBike BLE Integration for Home Assistant

[![GitHub release](https://img.shields.io/github/release/renenulschde/ha-mysmartbike_ble.svg)](https://github.com/renenulschde/ha-mysmartbike_ble/releases)
![](https://img.shields.io/github/downloads/renenulschde/ha-mysmartbike_ble/latest/total) ![Validate with HACS](https://github.com/ReneNulschDE/mbapi2020/workflows/Validate%20with%20HACS/badge.svg) 
![HassFest tests](https://github.com/renenulschde/ha-mysmartbike_ble/workflows/Validate%20with%20hassfest/badge.svg) 


Home Assistant custom component for E-Bikes with Mahle SmartBike systems (X25, X35+, ebikemotion, ...) via Bluetooth Low Energy (BLE).

Many premium E-Bike brands use Mahle drive systems and the MySmartBike app for connectivity. This integration works with bikes from various manufacturers including Schindelhauer, Orbea, Bianchi, Pinarello, Scott, and others that use the Mahle BLE protocol.

## Tested Bikes

This integration has been developed and tested with:

| Brand | Model | Status |
|-------|-------|--------|
| Orbea | Vibe | Fully tested |
| Schindelhauer | Arthur IX | Fully tested |


**Your bike not listed?** If you have an E-Bike that uses the MySmartBike app (or ebikemotion app), it will likely work with this integration. Please open an issue to report compatibility!

## Features

This integration provides real-time monitoring of your E-Bike through Bluetooth LE connection with 14 sensors, 1 binary sensor, and 1 switch:

### Connection Control

- **Auto-connect** (Switch) - Controls whether the integration may connect to your E-Bike
  - This is the connection *wish*, not the connection status. It stays on while the bike is away, so the integration reconnects on its own once the bike is switched on.
  - Turning it off disconnects from the bike and **the bike will shut down after approximately 5 minutes**. You must manually turn the bike back on or connect it to power to reconnect!
  - Use it to save energy when you don't need active monitoring
  - The position is remembered across Home Assistant restarts

- **Connected** (Binary Sensor) - The actual live BLE connection status

### Battery Sensors
- **Battery State of Charge** (%)
- **Battery Temperature** (°C)
- **Battery Remaining Energy** (Wh)

### Motor Sensors
- **Assist Level** - disabled by default
- **Motor Temperature** (°C)
- **Speed** (km/h)

### E-Bike Management (EBM)
- **Odometer** (km)
- **Range** (km)
- **Trip A Distance** (km)
- **Trip A Range** (km) - disabled by default
- **Light Status**
- **EBM Status**

Trip A values are only reported by newer X20 bikes (device names starting with `HUS`). On X25 / X35+ bikes they stay "Unknown".

### Diagnostics
- **Last Seen** (Timestamp) - When the bike last sent data, so you can tell how fresh the values are
- **Signal Strength** (dBm) - disabled by default

### Device Information
The integration automatically retrieves and displays:
- **Serial Number** (VIN) - 17-character bike serial number
- **Protocol Version** - BLE protocol version (e.g., 1.02, 3.00)

## Requirements

- Home Assistant 2024.6.0 or newer
- Bluetooth adapter with BLE support
- Bluetooth proxies with **active connections** are supported (e.g. ESPHome). Shelly proxies are passive-only: they can see the bike but never connect to it.
- E-Bike with Mahle SmartBike system (compatible with MySmartBike or ebikemotion app)

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/renenulschde/ha-mysmartbike_ble`
6. Select category "Integration"
7. Click "Add"
8. Search for "MySmartBike BLE" in HACS
9. Click "Download"
10. Restart Home Assistant

### Manual Installation

1. Download the latest release from the [releases page](https://github.com/renenulschde/ha-mysmartbike_ble/releases)
2. Extract the files
3. Copy the `custom_components/mysmartbike_ble` folder to your Home Assistant `custom_components` directory
4. Restart Home Assistant

## Configuration

The integration is configured through the Home Assistant UI:

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for **MySmartBike BLE**
4. Select your iWoc/HUS device from the list
5. Click **Submit**

The integration will automatically discover iWoc and HUS devices in range via Bluetooth.

## Troubleshooting

### Device not found

- Make sure your E-Bike is turned on and in range
- Check that Bluetooth is enabled on your Home Assistant host
- Verify that the device name starts with "iWoc" or "HUS" (please report other device names)
- Check the log. If it says the bike *is advertising but no adapter or proxy that supports active connections can reach it*, the bike is only being seen by a passive proxy (e.g. a Shelly). You need a local Bluetooth adapter or an ESPHome proxy with `active: true` in range of the bike.

### Connection issues

- Ensure no other device is connected to the E-Bike via Bluetooth
- Try restarting the Bluetooth service on your Home Assistant host
- Check the Home Assistant logs for detailed error messages

### Sensor values not updating

- While connected, the bike pushes data continuously and the sensors update within a second
- The 30-second interval is only the retry timer used while the bike is *not* connected
- Some sensors may show "Unknown" until the bike sends that specific data
- Check if the bike is actively transmitting data (try riding or using the display)

### Values after a Home Assistant restart

The integration keeps working when the bike is switched off or out of range:

- Counters and battery values (odometer, trip distance, range, state of charge,
  remaining energy, light) are stored and shown again after a restart
- Momentary readings (speed, motor temperature, assist level, battery current)
  are **not** restored and show "Unknown" until the bike connects again — a
  stale speed reading would look like live data from a parked bike
- Use **Connected** and **Last Seen** to tell live data from last known values
- The **Auto-connect** switch keeps its position across restarts, so a bike you
  deliberately disconnected is not woken up again by a Home Assistant restart

Values are only stored from the moment the bike connects. Directly after
installing or updating the integration, sensors read "Unknown" until the bike
has been connected once — from then on they survive restarts.

### Auto-connect Switch

- **To disconnect**: Turn off the "Auto-connect" switch in Home Assistant
  - ⚠️ This will shut down your bike after approximately 5 minutes!
  - The bike will remain on for about 5 minutes before automatically powering off
- **To reconnect**:
  1. First, manually turn on your bike OR connect it to power
  2. Wait for the bike to be fully powered on
  3. Turn on the "Auto-connect" switch in Home Assistant
- **Use case**: Turn off the connection when you don't need monitoring to save your bike's battery


### Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This is an unofficial integration and is not affiliated with or endorsed by Mahle, Schindelhauer, Orbea, or any other E-Bike manufacturer. Use at your own risk.
