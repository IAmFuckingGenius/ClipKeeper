# Changelog

## v1.0.0 - 2026-02-15

### Added

- Tray menu item to open Settings.
- Automatic history backups with retention policy and manual backup trigger.
- Localization system with `ru` and `en` locales.
- Configurable global hotkey from Settings.
- Bootstrap installer (`bootstrap-install.sh`) for `curl | bash` install flow.
- Repository baseline files: `.gitignore`, `.gitattributes`, `.editorconfig`, `CONTRIBUTING.md`.

### Changed

- Installer improved with core/optional dependency handling and fallback logic.
- README rewritten with platform support matrix, known limitations, installation paths, and release guidance.
- UI theme refreshed (`data/style.css`) and waybar module style updated (`data/waybar.css`).
- Hotkey backend now supports GNOME and Hyprland flows.
- D-Bus action invocation path adjusted to robust action activation behavior.

### Fixed

- Clipboard action activation bug caused by incorrect D-Bus argument signature.
- Multiple settings/tray integration issues after large refactors.

