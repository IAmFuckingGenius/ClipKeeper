"""Global hotkey helpers (GNOME and Hyprland)."""

from __future__ import annotations

import ast
import os
import re
import shlex
import shutil
import subprocess
from typing import Optional


GNOME_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_KEY = "custom-keybindings"
GNOME_BASE_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
GNOME_LEGACY_PATH = f"{GNOME_BASE_PATH}clipkeeper/"
GNOME_CUSTOM_PATH_RE = re.compile(rf"^{re.escape(GNOME_BASE_PATH)}custom(\d+)/$")

HYPR_DIR = os.path.expanduser("~/.config/hypr")
HYPR_MAIN_CONF = os.path.join(HYPR_DIR, "hyprland.conf")
HYPR_CLIP_CONF = os.path.join(HYPR_DIR, "clipkeeper.conf")
HYPR_SOURCE_MARKER = "clipkeeper.conf"


def has_gnome_hotkey_support() -> bool:
    if shutil.which("gsettings") is None:
        return False
    result = _run(["gsettings", "list-keys", GNOME_SCHEMA], timeout=5)
    return result.returncode == 0


def is_hyprland_session() -> bool:
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return True

    tokens = " ".join(
        [
            os.environ.get("XDG_CURRENT_DESKTOP", ""),
            os.environ.get("DESKTOP_SESSION", ""),
            os.environ.get("XDG_SESSION_DESKTOP", ""),
        ]
    ).lower()
    return "hypr" in tokens


def default_toggle_command() -> str:
    """Resolve command used by the desktop shortcut."""
    bin_path = os.path.expanduser("~/.local/bin/clipkeeper")
    if os.path.exists(bin_path):
        return f"{bin_path} --toggle"
    main_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    return f"python3 {shlex.quote(main_path)} --toggle"


def normalize_hotkey(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return "disabled"

    low = raw.lower()
    if low in {"off", "none", "disable", "disabled"}:
        return "disabled"

    if raw.startswith("<"):
        return raw

    parts = [p.strip() for p in re.split(r"\s*\+\s*", raw) if p.strip()]
    if not parts:
        return "disabled"

    key = parts[-1]
    modifier_map = {
        "super": "Super",
        "win": "Super",
        "meta": "Meta",
        "ctrl": "Control",
        "control": "Control",
        "alt": "Alt",
        "shift": "Shift",
    }

    modifiers = []
    for part in parts[:-1]:
        normalized = modifier_map.get(part.lower())
        if normalized and normalized not in modifiers:
            modifiers.append(normalized)

    if len(key) == 1:
        key = key.lower()
    elif key.lower().startswith("f") and key[1:].isdigit():
        key = key.upper()

    return "".join(f"<{m}>" for m in modifiers) + key


def display_hotkey(binding: Optional[str]) -> str:
    if not binding:
        return "Disabled"

    binding = binding.strip()
    if binding.lower() == "disabled":
        return "Disabled"

    modifiers = re.findall(r"<([^>]+)>", binding)
    key = re.sub(r"<[^>]+>", "", binding)

    reverse_map = {
        "Super": "Super",
        "Meta": "Meta",
        "Control": "Ctrl",
        "Alt": "Alt",
        "Shift": "Shift",
    }

    parts = [reverse_map.get(m, m) for m in modifiers]
    if key:
        if len(key) == 1:
            parts.append(key.upper())
        else:
            parts.append(key)
    return "+".join(parts) if parts else "Disabled"


def get_active_hotkey() -> Optional[str]:
    if is_hyprland_session():
        hypr = get_hyprland_hotkey()
        if hypr:
            return hypr
    gnome = get_gnome_hotkey()
    if gnome:
        return gnome
    return None


def apply_system_hotkey(
    hotkey: str,
    *,
    command: Optional[str] = None,
    name: str = "ClipKeeper",
) -> tuple[bool, str]:
    if is_hyprland_session():
        ok, res = apply_hyprland_hotkey(hotkey, command=command)
        if ok:
            return ok, res

    if has_gnome_hotkey_support():
        return apply_gnome_hotkey(hotkey, command=command, name=name)

    if is_hyprland_session() or os.path.exists(HYPR_MAIN_CONF):
        return apply_hyprland_hotkey(hotkey, command=command)

    return False, "No supported hotkey backend (GNOME/Hyprland)"


# --- GNOME backend ---

def get_gnome_hotkey() -> Optional[str]:
    if not has_gnome_hotkey_support():
        return None

    bindings = _get_custom_keybindings()
    paths = _find_gnome_clipkeeper_paths(bindings)
    for path in paths:
        value = _gnome_get_string(path, "binding")
        if value:
            return value
    return None


def apply_gnome_hotkey(
    hotkey: str,
    *,
    command: Optional[str] = None,
    name: str = "ClipKeeper",
) -> tuple[bool, str]:
    if not has_gnome_hotkey_support():
        return False, "GNOME gsettings is unavailable"

    normalized = normalize_hotkey(hotkey)
    if normalized == "disabled":
        return remove_gnome_hotkey()

    bindings = _get_custom_keybindings()
    existing_paths = _find_gnome_clipkeeper_paths(bindings)

    target_path = None
    for path in existing_paths:
        if GNOME_CUSTOM_PATH_RE.match(path):
            target_path = path
            break

    if target_path is None:
        target_path = _allocate_gnome_custom_path(bindings)

    new_bindings = [b for b in bindings if b not in existing_paths]
    if target_path not in new_bindings:
        new_bindings.append(target_path)

    ok, err = _set_custom_keybindings(new_bindings)
    if not ok:
        return False, err

    cmd = command or default_toggle_command()
    schema = _gnome_schema_for_path(target_path)

    steps = [
        ["gsettings", "set", schema, "name", name],
        ["gsettings", "set", schema, "command", cmd],
        ["gsettings", "set", schema, "binding", normalized],
    ]

    for step in steps:
        result = _run(step, timeout=5)
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            return False, stderr or "Failed to set GNOME hotkey"

    read_back = _gnome_get_string(target_path, "binding")
    if read_back and read_back != normalized:
        return False, f"Binding mismatch after write: {read_back}"

    return True, normalized


def remove_gnome_hotkey() -> tuple[bool, str]:
    if not has_gnome_hotkey_support():
        return False, "GNOME gsettings is unavailable"

    bindings = _get_custom_keybindings()
    paths = _find_gnome_clipkeeper_paths(bindings)
    if not paths:
        return True, "ok"

    new_bindings = [b for b in bindings if b not in paths]
    return _set_custom_keybindings(new_bindings)


def _gnome_schema_for_path(path: str) -> str:
    return (
        "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"
        f"{path}"
    )


def _find_gnome_clipkeeper_paths(bindings: list[str]) -> list[str]:
    result: list[str] = []
    for path in bindings:
        if path == GNOME_LEGACY_PATH:
            result.append(path)
            continue

        name = (_gnome_get_string(path, "name") or "").lower()
        command = (_gnome_get_string(path, "command") or "").lower()

        if (
            "clipkeeper" in name
            or "clipkeeper" in command
            or command.endswith("main.py --toggle")
        ):
            result.append(path)

    return result


def _allocate_gnome_custom_path(bindings: list[str]) -> str:
    used = set()
    for path in bindings:
        match = GNOME_CUSTOM_PATH_RE.match(path)
        if match:
            used.add(int(match.group(1)))

    idx = 0
    while idx in used:
        idx += 1
    return f"{GNOME_BASE_PATH}custom{idx}/"


def _gnome_get_string(path: str, key: str) -> Optional[str]:
    schema = _gnome_schema_for_path(path)
    result = _run(["gsettings", "get", schema, key], timeout=5)
    if result.returncode != 0:
        return None
    return _strip_gvariant_string(result.stdout.strip())


def _get_custom_keybindings() -> list[str]:
    result = _run(["gsettings", "get", GNOME_SCHEMA, GNOME_KEY], timeout=5)
    if result.returncode != 0:
        return []

    text = result.stdout.strip()
    if text.startswith("@as "):
        text = text[4:]

    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return []

    if isinstance(parsed, list):
        return [str(v) for v in parsed]
    return []


def _set_custom_keybindings(bindings: list[str]) -> tuple[bool, str]:
    value = str(bindings)
    result = _run(["gsettings", "set", GNOME_SCHEMA, GNOME_KEY, value], timeout=5)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        return False, stderr or "Failed to update custom keybindings"
    return True, "ok"


# --- Hyprland backend ---

def get_hyprland_hotkey() -> Optional[str]:
    if not os.path.exists(HYPR_CLIP_CONF):
        return None

    try:
        with open(HYPR_CLIP_CONF, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped.startswith("bind ="):
                    continue
                # bind = SUPER SHIFT, C, exec, ...
                payload = stripped.split("=", 1)[1].strip()
                parts = [p.strip() for p in payload.split(",")]
                if len(parts) < 2:
                    continue
                modifiers = parts[0]
                key = parts[1]
                return _hypr_parts_to_normalized(modifiers, key)
    except OSError:
        return None

    return None


def apply_hyprland_hotkey(
    hotkey: str,
    *,
    command: Optional[str] = None,
) -> tuple[bool, str]:
    normalized = normalize_hotkey(hotkey)
    os.makedirs(HYPR_DIR, exist_ok=True)

    cmd = command or default_toggle_command()

    if normalized == "disabled":
        content = "# Managed by ClipKeeper\n# Hotkey disabled\n"
    else:
        hypr_binding = _normalized_to_hypr_binding(normalized)
        if hypr_binding is None:
            return False, "Unsupported hotkey format for Hyprland"
        content = (
            "# Managed by ClipKeeper\n"
            f"bind = {hypr_binding}, exec, {cmd}\n"
        )

    try:
        with open(HYPR_CLIP_CONF, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as exc:
        return False, f"Failed to write {HYPR_CLIP_CONF}: {exc}"

    ok, err = _ensure_hyprland_source_line()
    if not ok:
        return False, err

    if shutil.which("hyprctl"):
        reload_result = _run(["hyprctl", "reload"], timeout=3)
        if reload_result.returncode != 0:
            stderr = reload_result.stderr.strip() or reload_result.stdout.strip()
            return False, stderr or "Failed to reload Hyprland config"

    return True, normalized


def _ensure_hyprland_source_line() -> tuple[bool, str]:
    source_line = "source = ~/.config/hypr/clipkeeper.conf"

    existing = ""
    if os.path.exists(HYPR_MAIN_CONF):
        try:
            with open(HYPR_MAIN_CONF, "r", encoding="utf-8") as f:
                existing = f.read()
        except OSError as exc:
            return False, f"Failed to read {HYPR_MAIN_CONF}: {exc}"

        if HYPR_SOURCE_MARKER in existing:
            return True, "ok"

    try:
        with open(HYPR_MAIN_CONF, "a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write("\n# ClipKeeper managed hotkey\n")
            f.write(source_line + "\n")
    except OSError as exc:
        return False, f"Failed to update {HYPR_MAIN_CONF}: {exc}"

    return True, "ok"


def _normalized_to_hypr_binding(normalized: str) -> Optional[str]:
    modifiers = re.findall(r"<([^>]+)>", normalized)
    key = re.sub(r"<[^>]+>", "", normalized).strip()

    if not key:
        return None

    mod_map = {
        "Super": "SUPER",
        "Meta": "SUPER",
        "Control": "CTRL",
        "Alt": "ALT",
        "Shift": "SHIFT",
    }

    hypr_mods = []
    for modifier in modifiers:
        mapped = mod_map.get(modifier)
        if mapped and mapped not in hypr_mods:
            hypr_mods.append(mapped)

    key = key.upper()
    mod_part = " ".join(hypr_mods)
    return f"{mod_part}, {key}" if mod_part else f", {key}"


def _hypr_parts_to_normalized(modifiers: str, key: str) -> Optional[str]:
    mod_map = {
        "SUPER": "Super",
        "CTRL": "Control",
        "ALT": "Alt",
        "SHIFT": "Shift",
    }

    parts = []
    for token in modifiers.split():
        token = token.strip().upper()
        if not token:
            continue
        mapped = mod_map.get(token)
        if mapped and mapped not in parts:
            parts.append(mapped)

    key = key.strip()
    if not key:
        return None

    if len(key) == 1:
        key = key.lower()
    return "".join(f"<{m}>" for m in parts) + key


def _strip_gvariant_string(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        return text[1:-1]
    return text


def _run(args: list[str], timeout: int = 2) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr=str(exc))
