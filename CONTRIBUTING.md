# Contributing to ClipKeeper

## Scope

ClipKeeper targets Linux desktop environments with GTK4/Libadwaita.

## Local Setup

1. Install dependencies:
   - `bash install.sh`
2. Run app:
   - `clipkeeper --daemon`
   - `clipkeeper --show`

## Development Rules

- Keep compatibility with GTK4 + Libadwaita.
- Preserve i18n keys in `data/locales/en.json` and `data/locales/ru.json`.
- For user-visible strings, use `tr("...")` from `src/i18n.py`.
- Keep hotkey backend working for GNOME and Hyprland.

## PR Checklist

- `python3 -m py_compile src/*.py` passes.
- New user-facing strings are added to both locales.
- README and installer are updated when behavior/dependencies change.
- No local absolute paths in committed files.

## Bug Reports

Include:

- OS distro + version
- Desktop environment / compositor (GNOME, Hyprland, KDE, etc.)
- Display protocol (Wayland/X11)
- ClipKeeper version/commit
- Steps to reproduce
- Logs from terminal run (`clipkeeper --show`)
