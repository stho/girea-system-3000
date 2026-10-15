# Girea System 3000

This is a custom component for Home Assistant to integrate the Gira System 3000 devices via
espHome bluetooth proxy or other bluetooth adapters.

Currently just the shutter controller "Jal+Schaltuhr" is implemented and tested.

> [!NOTE]
> Code was generated with Gemini 2.5 Flash support.

## Installation

### Option 1: HACS (Recommended)

1. **Prerequisite:** Ensure that HACS is installed and configured ([HACS Documentation](https://hacs.xyz)).
2. **Add Repository:** Add `https://github.com/stho/girea-system-3000` as a custom repository in
   HACS (category: Integration).
3. **Download:** Search for and install the **"Girea System 3000"** integration.
4. **Restart:** Restart Home Assistant to apply the changes.

### Option 2: Manual Installation

1. **Download:** Download the latest release from the Releases page.
2. **Extract & Copy:** Unpack the archive and copy the `custom_components/girea_system_3000`
   directory into the `custom_components` directory of your Home Assistant installation, so that
   you end up with `custom_components/girea_system_3000/manifest.json`.
3. **Restart:** Restart Home Assistant to load the new integration.


## Setup

You need a Bluetooth adapter or an ESPHome Bluetooth proxy that is connected to Home Assistant.

> [!IMPORTANT]
> The "Jal+Schaltuhr" must be in **pairing mode** while you add it to Home Assistant. The integration
> connects and pairs with the device once to check that it can be reached.
>
> *Note on range:* Ensure your Bluetooth adapter or proxy is **very close** to the Gira switch
> during this step. This proximity is **only required for the initial pairing process**; for regular
> switch commands later on, the adapter does not need to remain close to the switch.

### Option 1: Automatic discovery (recommended)

1. **Enter Pairing Mode:** Put your "Jal+Schaltuhr" shutter controller into pairing mode.
2. **Add the Device:** Home Assistant should list the controller as a discovered device under
   **Settings → Devices & services**. Click **Configure** on the discovered
   **Girea System 3000**.
3. **Choose a Name:** Enter a name for the shutter and submit. The device must still be in pairing
   mode. When the connection works, the cover entity is created.

### Option 2: Manual setup

Use this if the device is not discovered automatically.

1. **Enter Pairing Mode:** Put your "Jal+Schaltuhr" shutter controller into pairing mode.
2. **Find the MAC Address:** Open the Bluetooth monitoring tool in Home Assistant to find the
   controller's MAC address.
3. **Add the Device:** Go to **Settings → Devices & services → Add integration**, choose
   **Girea System 3000**, and enter the MAC address and a name. The address can be written with
   colons (`AA:BB:CC:DD:EE:FF`), with dashes, or without separators.

### If adding the device fails

- **"The device is not seen by any Bluetooth adapter or proxy"**: Check the MAC address, the power
  supply of the controller, and that an adapter or proxy is in range.
- **"Failed to connect to the device"**: Make sure the controller is in pairing mode and move the
  adapter or proxy closer to it. Then try again.

When a command from Home Assistant cannot be delivered later on (for example because the Bluetooth
proxy is offline), the action fails after about 20 seconds with an error message.


## Known issues

- There is still a little delay between pushing the button in the home assistant ui and actual start
  of the shutter movement.
- After a restart of Home Assistant, the position of the shutter is unknown until the shutter
  reports it the next time it moves.

## About this fork

This project is a fork of [Girea System 3000](https://github.com/clentfort/girea-system-3000),
originally created by [Christian Lentfort](https://github.com/clentfort).

### Changes in this fork

- General improvements
- User documentation
- HACS integration
- Github Actions integration

Please refer to the original repository for the upstream project and its development history.

## License

This project retains the MIT License of the original project. The original copyright and license
notices are preserved.

Copyright for original contributions remains with their respective authors. My original
contributions are Copyright (c) 2026 Stefan Hoppe.

See the [LICENSE](./LICENSE) file for the full license text.