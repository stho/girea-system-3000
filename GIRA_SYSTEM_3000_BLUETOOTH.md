# Gira System 3000 Bluetooth Protocol Documentation

This document provides a detailed analysis of the binary protocol used by Gira System 3000 Bluetooth devices, based on reverse-engineering of the official application logic and data.

## 1. Binary Message Structure

The protocol uses a fixed-header binary format for both commands (Write) and status updates (Notification/Broadcast).

### Full Packet Breakdown
`[MessageType] [ObjectID High] [ObjectID Low] [ElementsNum] [PropertyID] [StartIndex] [ValueLength] [Value...]`

| Field | Size | Description |
| :--- | :--- | :--- |
| **MessageType** | 1 byte | `0xF6` (246): Write/Command<br>`0xF7` (247): Notification/Broadcast |
| **ObjectID** | 2 bytes | Identifies the device function/submodule. Shutter is `800` (`0x0320`). |
| **ElementsNum** | 1 byte | Number of elements being addressed. Usually `0x01`. |
| **PropertyID** | 1 byte | The specific parameter or action (see PID table). |
| **StartIndex** | 1 byte | Address offset. Usually `0x10` (Index 1). |
| **ValueLength** | 1 byte | Length of the data payload in bytes. |
| **Value** | Variable | The actual payload data, encoded according to the Data Type (PDT). |

---

## 2. Data Types (PDT) and Encoding

The protocol leverages standard KNX Data Point Types (DPT) for value encoding.

| Type Name | Size | KNX DPT | Description |
| :--- | :--- | :--- | :--- |
| **PDT_BINARY** | 1 byte | 1.xxx | `0x00` (Off/Up/Stop), `0x01` (On/Down) |
| **PDT_SCALING** | 1 byte | 5.001 | 0-255 representing 0-100%. `0x00` = 100% (Open), `0xFF` = 0% (Closed). |
| **PDT_ENUM8** | 1 byte | 20.xxx | Enumerated values (e.g., Operation Mode, Movement Status). |
| **PDT_UNSIGNED_INT**| 2 bytes | 7.xxx | Big-endian 16-bit integer (e.g., Move Time in seconds). |
| **PDT_CONTROL** | 10 bytes| - | Complex control structure for state/loading management. |

---

## 3. Comprehensive Property ID (PID) Table

All PIDs listed below are for **ObjectID 800 (Shutter)**.

### Operational Commands
| PID | Hex | Name | Type | Description |
| :--- | :--- | :--- | :--- | :--- |
| 255 | `0xFF` | `PID_Move UpDown` | Binary | `0`: Up, `1`: Down |
| 254 | `0xFE` | `PID_StopStep UpDown` | Binary | `0`: Step/Tilt Up, `1`: Step/Tilt Down |
| 253 | `0xFD` | `PID_STOP` | Binary | `0`: Stop movement |
| 252 | `0xFC` | `PPID_Set_Absolute_Position_Blinds` | Scaling | Set blind position (0-255) |
| 251 | `0xFB` | `PPID_Set_Absolute_Position_Slat` | Scaling | Set slat/tilt position (0-255) |

### Status & Feedback
| PID | Hex | Name | Type | Description |
| :--- | :--- | :--- | :--- | :--- |
| 247 | `0xF7` | `PID_INFO_MOVE_UP_DOWN_STOP` | Enum8 | `0-1`: Stopped, `>1`: Moving |
| 246 | `0xF6` | `PID_CURRENT_ABSOLUTE_POSITION_BLINDS`| Scaling | Current blind position (Read-only) |
| 245 | `0xF5` | `PID_CURRENT_ABSOLUTE_POSITION_SLATS` | Scaling | Current slat position (Read-only) |
| 242 | `0xF2` | `PID_Info_Blocking_Function_State` | Binary | `1`: Blocked (e.g., wind alarm) |

### Configuration & Settings
| PID | Hex | Name | Type | Description |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `0x01` | `PID_OBJECT_TYPE` | UInt16 | Device Type (Shutter = 800) |
| 5 | `0x05` | `PID_LOAD_STATE_CONTROL` | Control | Mgmt: 1=Start, 2=Done, 4=Unload |
| 52 | `0x34` | `PID_MOVE_UP_DOWN_TIME` | UInt16 | Total travel time in seconds |
| 67 | `0x43` | `PID_MAX_SLAT_MOVE_TIME` | UInt16 | Slat adjustment time in ms |
| 160 | `0xA0` | `PID_ENABLE_INVERS_MODE` | Binary | Invert Up/Down logic |
| 162 | `0xA2` | `PID_OPERATION_MODE` | Enum8 | `0`: Blinds (Slats), `1`: Roller Shutter |
| 169 | `0xA9` | `PID_VENTILATION_BLINDS_POS` | Scaling | Preset ventilation position (Blinds) |
| 170 | `0xAA` | `PID_VENTILATION_SLATS_POS` | Scaling | Preset ventilation position (Slats) |
| 181 | `0xB5` | `PID_BLOCKING_FUNCTION_ENABLE` | Binary | Enable/Disable lock function |

---

## 4. Advanced Functions

### Sun Protection & Twilight
The device supports automatic positions based on environmental triggers (Sun/Twilight).
- **Sun Activation**: PIDs `172` (Blind) and `173` (Slat).
- **Sun Deactivation**: PIDs `174` (Blind) and `175` (Slat).
- **Twilight Activation**: PIDs `176` (Blind) and `177` (Slat).
- **Twilight Deactivation**: PIDs `178` (Blind) and `179` (Slat).

### Multi-Device Protocol Scalability
While this documentation focuses on shutters (ObjectID 800), the protocol structure is designed to handle other Gira System 3000 Bluetooth devices by changing the `ObjectID`:
- **Switching Inserts**: Likely use ObjectIDs in the 100-200 range with `PID_ON_OFF`.
- **Dimming Inserts**: Likely use ObjectIDs in the 200-300 range with `PID_BRIGHTNESS` (PDT_SCALING).
- **Addressing**: The combination of `ObjectID` and `PropertyID` allows the Gira App to communicate with different hardware modules using the same BLE characteristic.

---

## 5. Comparison with Current Integration

| Feature | Protocol Support | Integration Support | Status |
| :--- | :--- | :--- | :--- |
| **Move Up/Down** | Yes (PID 255) | Yes | Complete |
| **Stop** | Yes (PID 253) | Yes | Complete |
| **Blind Position** | Yes (PID 252) | Yes | Complete |
| **Slat/Tilt Position** | Yes (PID 251) | **No** | Missing |
| **Moving Status** | Yes (PID 247) | **Yes** (only to end "opening/closing"; direction comes from the command) | Partial |
| **Block State** | Yes (PID 242) | **No** | Missing |
| **Op Mode Detection** | Yes (PID 162) | **No** | Manual |

### Implementation Recommendation
To improve the integration, the `GiraPassiveBluetoothDataUpdateCoordinator` should be updated to listen for PIDs `0xF5` (Slat position).

---

## 6. Room Thermostat

Analysed from the broadcasts and from notification logs (nRF Connect) taken while
the target temperature was changed on the device and in the Gira app.

### GATT
| Item | UUID | Properties |
| :--- | :--- | :--- |
| Service | `9769f147-f77a-43ae-8c35-09f0c5245308` | primary |
| Command characteristic | `97696341-f77a-43ae-8c35-09f0c5245308` | Write (same as the shutter) |
| Status characteristic | `9769c769-f77a-43ae-8c35-09f0c5245308` | Notify, Read (CCCD `0x2902`) |

The device must be bonded (pairing mode) before a client can connect. In pairing
mode it advertises the local name `Thermostat`, flags `05` and manufacturer data
`05 91 4a 09 01 15`.

### Message format = KNX cEMI
The frames are KNX cEMI interface object server frames, not a Gira specific
format:

`[MessageCode] [ObjectType 2 bytes] [Instance 1 byte] [PropertyID] [NoE/Start 2 bytes = 0x10 0x01] [Data]`

`10 01` is "1 element, start index 1" (the number of elements is 4 bits, the
start index 12 bits), **not** "start index" and "value length" as in section 1.
The length of the data depends on the property (1 byte for binary/enum values,
2 bytes for temperatures), it is not part of the frame.

| Code | cEMI name | Seen |
| :--- | :--- | :--- |
| `F6` | M_PropWrite.req | commands to the shutter (see above) |
| `F5` | M_PropWrite.con | notification after the app wrote a property (no data) |
| `F7` | M_PropInfo.ind | broadcasts and spontaneous notifications |
| `FB` | M_PropRead.con | answers to the reads of the app after connecting |

Temperatures are KNX DPT 9 (16 bit float: `S EEEE MMM MMMMMMMM`, value =
`0.01 * M * 2^E`), e.g. `0C1A` = 21.0 °C, `07D0` = 20.0 °C, `0CE2` = 25.0 °C.

### Properties
| ObjectType | PID | Type | Meaning | Status |
| :--- | :--- | :--- | :--- | :--- |
| `0x0141` | `0xFE` | DPT 9 | measured temperature (e.g. `07F2` = 20.34 °C), changes slowly | very likely |
| `0x0065` | `0xFF` | DPT 9 | target temperature | confirmed |
| `0x0065` | `0xF5` | DPT 9 | target temperature, always sent together with `0xFF` | confirmed |
| `0x0065` | `0xF4` | byte | `01` after the target was changed on the device | unknown meaning |
| `0x0065` | `0xA1` / `0xA0` / `0xA2` | DPT 9 | 7.0 / 18.0 / 24.0 °C (limits or presets) | unknown meaning |
| `0x0065` | `0x9F` / `0xA3` | DPT 9 | 21.0 °C | unknown meaning |
| `0x0000` | `0x0B` | 6 bytes | device ID `00 0A 4A 09 01 15`; the last four bytes are the first bytes of the broadcast manufacturer data | |
| `0x0000` | `0x02` | text | name ("Thermostat Kü…", read in several blocks) | |

The target temperature changes in steps of 0.5 °C. Changing it on the device
(20.0 -> 20.5 -> 21.0) and in the app (22.0 -> 25.0) both produce a pair of `F7`
notifications for `0xF5` and `0xFF` with the new value.

### Setting the target temperature (not yet confirmed)
For every step the app wrote one property to ObjectType `0x0065`: the device
answers with `F5 00 65 01 F6 10 01` (write confirmation of PID `0xF6`) and then
sends the new target temperature. The data of that write is not part of the
notification log. The command is therefore probably

`F6 00 65 01 F6 10 01 [DPT 9 target]`, written to `97696341-...`

but the PID and the data (absolute value or relative step) must still be
confirmed, e.g. with an Android Bluetooth HCI snoop log of the app.
