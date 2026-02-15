#!/usr/bin/env bash
# ClipKeeper installer for Linux user environment.
# Usage:
#   bash install.sh
#   bash install.sh --skip-deps

set -euo pipefail

APP_NAME="clipkeeper"
APP_DIR="$(realpath "$(dirname "$0")")"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
ICON_SRC="$APP_DIR/data/icons/hicolor/scalable/apps/clipkeeper-tray.svg"
SKIP_DEPS=false

for arg in "$@"; do
  case "$arg" in
    --skip-deps)
      SKIP_DEPS=true
      ;;
  esac
done

echo "[ClipKeeper] Starting installation"

if [[ "$SKIP_DEPS" == false ]]; then
  echo "[ClipKeeper] Checking system dependencies"
  CORE_PACKAGES=(
    python3 python3-gi python3-gi-cairo python3-pil
    gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdkpixbuf-2.0
    gir1.2-ayatanaappindicator3-0.1
    wl-clipboard xclip curl xdg-utils
  )
  OPTIONAL_PACKAGES=(
    python3-qrcode python3-pytesseract tesseract-ocr
  )

  if command -v apt >/dev/null 2>&1; then
    if ! sudo apt update -qq; then
      echo "[ClipKeeper] Warning: apt update failed, trying install with current indexes"
    fi

    available_core=()
    missing_core=()
    for pkg in "${CORE_PACKAGES[@]}"; do
      if apt-cache show "$pkg" >/dev/null 2>&1; then
        available_core+=("$pkg")
      else
        missing_core+=("$pkg")
      fi
    done

    if [[ "${#available_core[@]}" -gt 0 ]]; then
      sudo apt install -y "${available_core[@]}"
    fi

    if [[ "${#missing_core[@]}" -gt 0 ]]; then
      echo "[ClipKeeper] Warning: some core packages were not found in repos: ${missing_core[*]}"
    fi

    available_optional=()
    missing_optional=()
    for pkg in "${OPTIONAL_PACKAGES[@]}"; do
      if apt-cache show "$pkg" >/dev/null 2>&1; then
        available_optional+=("$pkg")
      else
        missing_optional+=("$pkg")
      fi
    done

    if [[ "${#available_optional[@]}" -gt 0 ]]; then
      sudo apt install -y "${available_optional[@]}" || true
    fi

    if printf '%s\n' "${missing_optional[@]}" | grep -qx "python3-pytesseract"; then
      if command -v pip3 >/dev/null 2>&1; then
        echo "[ClipKeeper] python3-pytesseract not found, trying pip3 --user pytesseract"
        if pip3 install --user pytesseract >/dev/null 2>&1; then
          filtered_missing=()
          for pkg in "${missing_optional[@]}"; do
            if [[ "$pkg" != "python3-pytesseract" ]]; then
              filtered_missing+=("$pkg")
            fi
          done
          missing_optional=("${filtered_missing[@]}")
          echo "[ClipKeeper] pytesseract installed via pip3"
        else
          echo "[ClipKeeper] Warning: pip3 install pytesseract failed (OCR integration may be disabled)"
        fi
      else
        echo "[ClipKeeper] Optional dependency missing: python3-pytesseract (OCR integration will be disabled)"
      fi
    fi

    if [[ "${#missing_optional[@]}" -gt 0 ]]; then
      echo "[ClipKeeper] Optional packages not found: ${missing_optional[*]}"
    fi
  else
    echo "[ClipKeeper] Warning: apt not found, install dependencies manually"
  fi
else
  echo "[ClipKeeper] Dependency installation skipped (--skip-deps)"
fi

echo "[ClipKeeper] Installing launcher"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/$APP_NAME" <<EOF
#!/usr/bin/env bash
exec python3 "$APP_DIR/src/main.py" "\$@"
EOF
chmod +x "$BIN_DIR/$APP_NAME"

echo "[ClipKeeper] Installing desktop entry"
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/$APP_NAME.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ClipKeeper
Comment=Modern clipboard manager for Linux
Exec=$BIN_DIR/$APP_NAME --show
Icon=clipkeeper-tray
Terminal=false
Categories=Utility;GTK;
Keywords=clipboard;paste;copy;history;
EOF

echo "[ClipKeeper] Installing icon"
mkdir -p "$ICON_DIR"
cp "$ICON_SRC" "$ICON_DIR/clipkeeper-tray.svg"
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "[ClipKeeper] Configuring autostart"
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_DIR/$APP_NAME.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ClipKeeper
Comment=Modern clipboard manager for Linux
Exec=$BIN_DIR/$APP_NAME --daemon
Icon=clipkeeper-tray
Terminal=false
Categories=Utility;GTK;
Keywords=clipboard;paste;copy;history;
X-GNOME-Autostart-enabled=true
EOF

echo "[ClipKeeper] Trying to configure default hotkey: Super+C"
if "$BIN_DIR/$APP_NAME" --set-hotkey "<Super>c" >/dev/null 2>&1; then
  HOTKEY_STATUS="configured via gsettings"
else
  HOTKEY_STATUS="not configured automatically (set it in ClipKeeper Settings > Keyboard)"
fi

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  echo "[ClipKeeper] Warning: $BIN_DIR is not in PATH"
  echo "[ClipKeeper] Add it with: echo 'export PATH=\$PATH:\$HOME/.local/bin' >> ~/.zshrc"
fi

echo

echo "[ClipKeeper] Installation completed"
echo "[ClipKeeper] Command: $APP_NAME"
echo "[ClipKeeper] CLI examples:"
echo "  $APP_NAME --show"
echo "  $APP_NAME --toggle"
echo "  $APP_NAME --quit"
echo "[ClipKeeper] Hotkey status: $HOTKEY_STATUS"
echo "[ClipKeeper] You can change the hotkey in ClipKeeper Settings > Keyboard"
