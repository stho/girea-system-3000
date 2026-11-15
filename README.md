# Girea System 3000

This is a custom component for Home Assistant to integrate the Gira System 3000 devices via
espHome bluetooth proxy or other bluetooth adapters.

Currently the shutter controller "Jal+Schaltuhr" is implemented and tested. The room thermostat is supported experimentally (measured and target temperature from the Bluetooth broadcasts, setting the target temperature, and the week schedule, see below): choose the device type "Room thermostat" when adding it by MAC address.

> [!NOTE]
> Code was generated with Gemini 2.5 Flash support.
> The room thermostat support (sensors, setpoint, week schedule, the Bluetooth protocol analysis and
> the dashboard card) was developed with the help of AI ([Claude Code](https://claude.com/claude-code)).

## Installation

### Option 1: HACS (Recommended)

1. **Prerequisite:** Ensure that HACS is installed and configured ([HACS Documentation](https://hacs.xyz)).
2. **Add Repository:** Add `https://github.com/stho/girea-system-3000` as a custom repository in
   HACS (category: Integration).
3. **Download:** Search for and install the **"System 3000"** integration.
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

## Week schedule (room thermostat)

The time program of the thermostat can be edited in Home Assistant, in the same text format as the
MAX! integration [MAX-via-Cul](https://github.com/thnow/MAX-via-Cul). The schedule is stored in the
thermostat itself, so it keeps working without Home Assistant.

Entities of the thermostat device (category "Configuration"):

| Entity | Purpose |
| :--- | :--- |
| `1 Montag` … `7 Sonntag` (text) | Schedule of one weekday, e.g. `5,06:00,21,18:00,5` |
| `Wochenplan übertragen` (button) | Writes the whole week to the thermostat |
| `Wochenplan-Entwurf verwerfen` (button) | Drops the changes that were not transferred |
| `Wochenplan vom Gerät lesen` (button) | Reads the schedule from the thermostat (e.g. after a change in the Gira app) |
| `Wochenplan aktiv` (switch, default on) | Switches all switch points of the thermostat on or off |

**Format:** `Temperatur,HH:MM,Temperatur,HH:MM,…,Temperatur`. The first value applies from 00:00,
each following pair is a switch time and the temperature from that time on, the last value applies
until the end of the day. `5,06:00,21,18:00,5` means 5 °C until 06:00, 21 °C until 18:00 and 5 °C
until midnight. Temperatures from 5 to 30 °C in steps of 0.5 (decimal point, not comma), times to
the minute.

Changing a day only creates a draft (attribute `draft_pending`); press **Wochenplan übertragen** to
write it. Transferring switches the thermostat to the "Erweitert" mode of its time program and sets
its clock.

**Limits:** the thermostat stores at most 40 switch points per week. Every switch point belongs to
one day. A switch point at 00:00 is only needed when a day starts with another temperature than the
previous day ends with (otherwise the thermostat simply keeps that temperature over midnight). The
attribute `switch_points_used` shows how many points the week needs.

### Week schedule card

The integration brings a dashboard card **"Gira Wochenprofil"** in the look of the MAX! week profile
card. It is loaded automatically, there is no need to add a resource. Edit a dashboard, choose
**Add card** and search for "Gira Wochenprofil", or add it in YAML:

```yaml
type: custom:gira-week-profile-card
entity: climate.thermostat_kuche
```

The card shows one bar per weekday with the temperature of each period and marks the current day.
Tap a day to edit its periods; the change can be copied to Mo–Fr, Sa–So or all days. Changes are a
draft until you press transfer in the card, just like the text entities above. The card also has
buttons to discard the draft and to read the schedule from the thermostat, and it switches
"Wochenplan aktiv".

| Option | Default | Purpose |
| :--- | :--- | :--- |
| `entity` | (required) | Climate entity of the thermostat |
| `title` | `Wochenprofil` | Title of the card |
| `show_current_temp` | `true` | Show the measured temperature |
| `editable` | `true` | Allow editing in the card |
| `days`, `active`, `apply`, `discard`, `read` | derived from `entity` | Entity IDs, only needed if you renamed the entities (`days` is a list of the 7 text entities, Monday first) |

The card finds the other entities from the name of the climate entity, e.g.
`text.thermostat_kuche_1_montag` and `switch.thermostat_kuche_wochenplan_aktiv`. The card is in
German only.


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