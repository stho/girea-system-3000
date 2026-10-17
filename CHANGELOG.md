# Changelog

## Release 1.2.0

### Added
- Opening / closing state. The cover now shows "opening" or "closing" right
  after a command, without waiting for the device. The end of the movement is
  taken from the movement status broadcast of the device, a reported target
  position, or an estimate from the travelled distance (about 0.65 s per percent).
  The estimated end position is corrected by the next position broadcast.
- Translations (English and German) for the config flow and for error messages.
- The config flow checks that the device can be reached and paired before the
  entry is created. MAC addresses are accepted in the usual spellings
  (`AA:BB:..`, `aa-bb-..`, `AABB..`). Errors are specific (device not found,
  cannot connect, invalid address).
- Unit tests and a CI workflow (ruff and unit tests) in addition to the existing
  hassfest and HACS validation.
- Debug logging of changed advertisements, to analyse what the device sends.

### Changed
- Entity and device identifiers are based on the MAC address instead of the
  config entry ID. Existing entries are migrated automatically on startup.
- The device is registered with manufacturer, model and the Bluetooth
  connection, so it is shown correctly in the device registry.
- The connection to the device is kept open for 10 s after a command, so that
  follow-up commands (stop, slider) do not have to connect again.
- The cover uses an assumed state, so the open and close buttons stay usable
  while the position is not yet known or still shows the old end position.
- README rewritten (installation, setup, Bluetooth proxy notes, limitations).

### Fixed
- Failed commands are now shown to the user as an error instead of being
  swallowed. Error messages are translated.
- A command now fails after at most 20 s if the device or Bluetooth proxy cannot
  be reached; before, it could hang for a minute or more.
- Fixed the deprecated `device_registry.async_get_device` lookup.
- The coordinator no longer fails before the first broadcast has been received.
- Removed unused imports and variables.

### Known limitations
- The position and movement status are only sent by the device every few
  seconds and can arrive with a delay (observed 15 s up to about 50 s, longer
  when the Bluetooth proxy is busy with other connections).
- The movement status value for "moving up" has not been observed yet. It is only
  used to detect that the shutter has stopped.
- The slat position (property 0xF5) is not evaluated.
