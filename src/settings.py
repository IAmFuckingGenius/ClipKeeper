"""
ClipKeeper — Settings Window.
Adw.PreferencesWindow for configuring the application.
"""

from __future__ import annotations

import os
import subprocess

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .database import Database
from .hotkeys import display_hotkey, get_active_hotkey
from .i18n import tr

# Default settings
DEFAULTS = {
    "max_history": "500",
    "theme": "system",       # system, light, dark
    "compact_mode": "false",
    "image_quality": "85",
    "max_image_size": "2048",  # max dimension in px before downscaling
    "show_notifications": "false",
    "auto_start": "false",
    "theme_accent": "standard",
    "language": "system",
    "hotkey": "Super+C",
    "backup_enabled": "true",
    "backup_interval_minutes": "60",
    "backup_keep_count": "20",
    "backup_dir": "",
    "backup_last_ts": "0",
    "script_path": "",
    "show_action_quick": "true",
    "show_action_edit": "true",
    "show_action_translate": "true",
    "show_action_qr": "true",
    "show_action_preview": "true",
    "show_action_favorite": "true",
    "show_action_pin": "true",
    "show_action_snippet": "true",
    "show_action_delete": "true",
}


class SettingsManager:
    """Manages application settings with database persistence."""

    def __init__(self, db: Database):
        self.db = db
        self._cache = {}
        self._load_defaults()

    def _load_defaults(self):
        """Load defaults for any unset settings."""
        for key, default in DEFAULTS.items():
            if not self.db.get_setting(key):
                self.db.set_setting(key, default)

    def get(self, key: str) -> str:
        if key not in self._cache:
            self._cache[key] = self.db.get_setting(key, DEFAULTS.get(key, ""))
        return self._cache[key]

    def get_int(self, key: str) -> int:
        try:
            return int(self.get(key))
        except (ValueError, TypeError):
            return int(DEFAULTS.get(key, "0"))

    def get_bool(self, key: str) -> bool:
        return self.get(key).lower() == "true"

    def set(self, key: str, value: str):
        self._cache[key] = value
        self.db.set_setting(key, value)


class SettingsWindow(Adw.PreferencesWindow):
    """Settings window for ClipKeeper."""

    def __init__(self, app, settings: SettingsManager):
        super().__init__(
            title=tr("settings.title"),
            default_width=540,
            default_height=620,
        )
        self.app = app
        self.settings = settings
        self._build_ui()

    def _build_ui(self):
        """Build the preferences UI."""
        # --- General Page ---
        general_page = Adw.PreferencesPage(
            title=tr("settings.page.general"),
            icon_name="preferences-system-symbolic",
        )
        self.add(general_page)

        # History group
        history_group = Adw.PreferencesGroup(
            title=tr("settings.group.history"),
            description=tr("settings.group.history.desc"),
        )
        general_page.add(history_group)

        max_history_row = Adw.SpinRow(
            title=tr("settings.max_history"),
            subtitle=tr("settings.max_history.subtitle"),
            adjustment=Gtk.Adjustment(
                value=self.settings.get_int("max_history"),
                lower=50,
                upper=5000,
                step_increment=50,
                page_increment=100,
            ),
        )
        max_history_row.connect("notify::value", self._on_int_changed, "max_history")
        history_group.add(max_history_row)

        behavior_group = Adw.PreferencesGroup(
            title=tr("settings.group.behavior"),
        )
        general_page.add(behavior_group)

        autostart_row = Adw.SwitchRow(
            title=tr("settings.autostart"),
            subtitle=tr("settings.autostart.subtitle"),
            active=self.settings.get_bool("auto_start"),
        )
        autostart_row.connect("notify::active", self._on_autostart_changed)
        behavior_group.add(autostart_row)

        script_group = Adw.PreferencesGroup(
            title=tr("settings.group.script"),
            description=tr("settings.group.script.desc"),
        )
        general_page.add(script_group)

        script_row = Adw.ActionRow(title=tr("settings.script_path"))
        script_row.set_subtitle(tr("settings.script_path.subtitle"))

        script_path = self.settings.get("script_path")
        self.script_label = Gtk.Label(
            label=script_path if script_path else tr("common.not_selected"),
            ellipsize=3,
            max_width_chars=25,
            valign=Gtk.Align.CENTER,
            css_classes=["dim-label"],
        )

        script_btn = Gtk.Button(
            icon_name="document-open-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text=tr("settings.script.select"),
            css_classes=["flat"],
        )
        script_btn.connect("clicked", self._on_select_script)

        clear_btn = Gtk.Button(
            icon_name="edit-clear-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text=tr("settings.script.clear"),
            css_classes=["flat"],
        )
        clear_btn.connect("clicked", self._on_clear_script)

        script_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        script_box.append(self.script_label)
        script_box.append(script_btn)
        script_box.append(clear_btn)
        script_row.add_suffix(script_box)

        script_group.add(script_row)

        # --- Appearance Page ---
        appearance_page = Adw.PreferencesPage(
            title=tr("settings.page.appearance"),
            icon_name="preferences-desktop-theme-symbolic",
        )
        self.add(appearance_page)

        appearance_group = Adw.PreferencesGroup(
            title=tr("settings.group.appearance"),
        )
        appearance_page.add(appearance_group)

        theme_row = Adw.ComboRow(
            title=tr("settings.theme"),
            subtitle=tr("settings.theme.subtitle"),
            model=Gtk.StringList.new([
                tr("settings.theme.system"),
                tr("settings.theme.light"),
                tr("settings.theme.dark"),
            ]),
        )
        theme_map = ["system", "light", "dark"]
        current_theme = self.settings.get("theme")
        if current_theme in theme_map:
            theme_row.set_selected(theme_map.index(current_theme))
        else:
            theme_row.set_selected(0)

        theme_row.connect("notify::selected", self._on_theme_changed, theme_map)
        appearance_group.add(theme_row)

        accent_row = Adw.ComboRow(
            title=tr("settings.accent"),
            subtitle=tr("settings.accent.subtitle"),
            model=Gtk.StringList.new([
                tr("settings.accent.standard"),
                tr("settings.accent.blue"),
                tr("settings.accent.purple"),
                tr("settings.accent.green"),
                tr("settings.accent.orange"),
                tr("settings.accent.grey"),
            ]),
        )
        accents = ["standard", "blue", "purple", "green", "orange", "grey"]
        current = self.settings.get("theme_accent")
        if current in accents:
            accent_row.set_selected(accents.index(current))
        else:
            accent_row.set_selected(0)

        accent_row.connect("notify::selected", self._on_accent_changed, accents)
        appearance_group.add(accent_row)

        compact_row = Adw.SwitchRow(
            title=tr("settings.compact_mode"),
            subtitle=tr("settings.compact_mode.subtitle"),
            active=self.settings.get_bool("compact_mode"),
        )
        compact_row.connect("notify::active", self._on_bool_changed, "compact_mode")
        appearance_group.add(compact_row)

        # --- Interface Page ---
        interface_page = Adw.PreferencesPage(
            title=tr("settings.page.interface"),
            icon_name="ui-display-symbolic",
        )
        self.add(interface_page)

        actions_group = Adw.PreferencesGroup(
            title=tr("settings.group.actions"),
            description=tr("settings.group.actions.desc"),
        )
        interface_page.add(actions_group)

        action_configs = [
            ("show_action_quick", "settings.action.quick.title", "settings.action.quick.subtitle"),
            ("show_action_edit", "settings.action.edit.title", "settings.action.edit.subtitle"),
            ("show_action_translate", "settings.action.translate.title", "settings.action.translate.subtitle"),
            ("show_action_qr", "settings.action.qr.title", "settings.action.qr.subtitle"),
            ("show_action_preview", "settings.action.preview.title", "settings.action.preview.subtitle"),
            ("show_action_favorite", "settings.action.favorite.title", "settings.action.favorite.subtitle"),
            ("show_action_pin", "settings.action.pin.title", "settings.action.pin.subtitle"),
            ("show_action_snippet", "settings.action.snippet.title", "settings.action.snippet.subtitle"),
            ("show_action_delete", "settings.action.delete.title", "settings.action.delete.subtitle"),
        ]

        for key, title_key, subtitle_key in action_configs:
            row = Adw.SwitchRow(
                title=tr(title_key),
                subtitle=tr(subtitle_key),
                active=(self.settings.get(key) == "true"),
            )
            row.connect("notify::active", self._on_bool_changed, key)
            actions_group.add(row)

        # --- Storage Page ---
        storage_page = Adw.PreferencesPage(
            title=tr("settings.page.storage"),
            icon_name="drive-harddisk-symbolic",
        )
        self.add(storage_page)

        image_group = Adw.PreferencesGroup(
            title=tr("settings.group.images"),
            description=tr("settings.group.images.desc"),
        )
        storage_page.add(image_group)

        quality_row = Adw.SpinRow(
            title=tr("settings.image_quality"),
            subtitle=tr("settings.image_quality.subtitle"),
            adjustment=Gtk.Adjustment(
                value=self.settings.get_int("image_quality"),
                lower=10,
                upper=100,
                step_increment=5,
                page_increment=10,
            ),
        )
        quality_row.connect("notify::value", self._on_quality_changed)
        image_group.add(quality_row)

        size_row = Adw.SpinRow(
            title=tr("settings.max_image_size"),
            subtitle=tr("settings.max_image_size.subtitle"),
            adjustment=Gtk.Adjustment(
                value=self.settings.get_int("max_image_size"),
                lower=256,
                upper=8192,
                step_increment=256,
                page_increment=512,
            ),
        )
        size_row.connect("notify::value", self._on_size_changed)
        image_group.add(size_row)

        backup_group = Adw.PreferencesGroup(
            title=tr("settings.group.backup"),
            description=tr("settings.group.backup.desc"),
        )
        storage_page.add(backup_group)

        backup_enabled_row = Adw.SwitchRow(
            title=tr("settings.backup.enabled"),
            subtitle=tr("settings.backup.enabled.subtitle"),
            active=self.settings.get_bool("backup_enabled"),
        )
        backup_enabled_row.connect("notify::active", self._on_backup_enabled_changed)
        backup_group.add(backup_enabled_row)

        backup_interval_row = Adw.SpinRow(
            title=tr("settings.backup.interval"),
            subtitle=tr("settings.backup.interval.subtitle"),
            adjustment=Gtk.Adjustment(
                value=max(5, self.settings.get_int("backup_interval_minutes")),
                lower=5,
                upper=1440,
                step_increment=5,
                page_increment=30,
            ),
        )
        backup_interval_row.connect(
            "notify::value", self._on_int_changed, "backup_interval_minutes"
        )
        backup_group.add(backup_interval_row)

        backup_keep_row = Adw.SpinRow(
            title=tr("settings.backup.keep"),
            subtitle=tr("settings.backup.keep.subtitle"),
            adjustment=Gtk.Adjustment(
                value=max(1, self.settings.get_int("backup_keep_count")),
                lower=1,
                upper=500,
                step_increment=1,
                page_increment=10,
            ),
        )
        backup_keep_row.connect("notify::value", self._on_int_changed, "backup_keep_count")
        backup_group.add(backup_keep_row)

        backup_path_row = Adw.ActionRow(title=tr("settings.backup.path"))
        backup_path = self.app.backup_dir() if hasattr(self.app, "backup_dir") else "~/.local/share/clipkeeper/backups"
        backup_path_row.set_subtitle(tr("settings.backup.path.subtitle", path=backup_path))

        open_backup_btn = Gtk.Button(label=tr("common.open_folder"), css_classes=["flat"])
        open_backup_btn.connect("clicked", self._on_open_backup_dir)
        backup_now_btn = Gtk.Button(label=tr("common.backup_now"), css_classes=["suggested-action"])
        backup_now_btn.connect("clicked", self._on_backup_now)

        backup_path_row.add_suffix(open_backup_btn)
        backup_path_row.add_suffix(backup_now_btn)
        backup_group.add(backup_path_row)

        stats = self.app.db.get_stats()
        stats_group = Adw.PreferencesGroup(
            title=tr("settings.group.stats"),
        )
        storage_page.add(stats_group)

        stats_row = Adw.ActionRow(
            title=tr("settings.stats.total"),
            subtitle=tr(
                "settings.stats.subtitle",
                total=stats["total"],
                images=stats["images"],
                pinned=stats["pinned"],
            ),
        )
        stats_group.add(stats_row)

        # --- Keyboard Page ---
        keyboard_page = Adw.PreferencesPage(
            title=tr("settings.page.keyboard"),
            icon_name="input-keyboard-symbolic",
        )
        self.add(keyboard_page)

        keys_group = Adw.PreferencesGroup(
            title=tr("settings.group.hotkey"),
            description=tr("settings.group.hotkey.desc"),
        )
        keyboard_page.add(keys_group)

        hotkey_row = Adw.ActionRow(
            title=tr("settings.hotkey.label"),
            subtitle=tr("settings.group.hotkey.desc"),
        )
        self.hotkey_entry = Gtk.Entry(
            text=self._current_hotkey_display(),
            width_chars=14,
            valign=Gtk.Align.CENTER,
        )
        apply_hotkey_btn = Gtk.Button(label=tr("common.apply"), css_classes=["suggested-action"])
        apply_hotkey_btn.connect("clicked", self._on_apply_hotkey)

        hotkey_row.add_suffix(self.hotkey_entry)
        hotkey_row.add_suffix(apply_hotkey_btn)
        keys_group.add(hotkey_row)

        reset_hotkey_row = Adw.ActionRow(
            title=tr("settings.hotkey.reset"),
            subtitle=tr("settings.hotkey.help", binding=self.settings.get("hotkey")),
        )
        self.hotkey_help_row = reset_hotkey_row
        reset_btn = Gtk.Button(label=tr("common.apply"), css_classes=["flat"])
        reset_btn.connect("clicked", self._on_reset_hotkey)
        reset_hotkey_row.add_suffix(reset_btn)
        keys_group.add(reset_hotkey_row)

        # --- Language Page ---
        language_page = Adw.PreferencesPage(
            title=tr("settings.page.language"),
            icon_name="preferences-desktop-locale-symbolic",
        )
        self.add(language_page)

        language_group = Adw.PreferencesGroup(
            title=tr("settings.group.language"),
            description=tr("settings.group.language.desc"),
        )
        language_page.add(language_group)

        language_row = Adw.ComboRow(
            title=tr("settings.language"),
            model=Gtk.StringList.new([
                tr("settings.language.system"),
                tr("settings.language.english"),
                tr("settings.language.russian"),
            ]),
        )
        language_map = ["system", "en", "ru"]
        current_lang = self.settings.get("language")
        if current_lang not in language_map:
            current_lang = "system"
        language_row.set_selected(language_map.index(current_lang))
        language_row.connect("notify::selected", self._on_language_changed, language_map)
        language_group.add(language_row)

        restart_hint = Adw.ActionRow(
            title=tr("settings.language.restart_hint"),
        )
        language_group.add(restart_hint)

    # --- Handlers ---

    def _on_bool_changed(self, row, param, key):
        self.settings.set(key, str(row.get_active()).lower())
        if key == "compact_mode" and hasattr(self.app, "update_compact_mode"):
            self.app.update_compact_mode()

    def _on_backup_enabled_changed(self, row, param):
        self.settings.set("backup_enabled", str(row.get_active()).lower())
        if hasattr(self.app, "reconfigure_backup"):
            self.app.reconfigure_backup()

    def _on_int_changed(self, row, param, key):
        value = int(row.get_value())
        self.settings.set(key, str(value))
        if key == "max_history" and hasattr(self.app, "db") and self.app.db:
            self.app.db._auto_cleanup(value)
        if key in {"backup_interval_minutes", "backup_keep_count"} and hasattr(self.app, "reconfigure_backup"):
            self.app.reconfigure_backup()

    def _on_accent_changed(self, row, param, accents):
        idx = row.get_selected()
        if 0 <= idx < len(accents):
            self.settings.set("theme_accent", accents[idx])
            if hasattr(self.app, "_update_visuals"):
                self.app._update_visuals()

    def _on_theme_changed(self, row, param, theme_map):
        idx = row.get_selected()
        if 0 <= idx < len(theme_map):
            theme = theme_map[idx]
            self.settings.set("theme", theme)
            if hasattr(self.app, "_apply_theme"):
                self.app._apply_theme()

    def _on_language_changed(self, row, param, language_map):
        idx = row.get_selected()
        if 0 <= idx < len(language_map):
            language = language_map[idx]
            if hasattr(self.app, "apply_language"):
                self.app.apply_language(language)
            else:
                self.settings.set("language", language)

    def _on_autostart_changed(self, row, pspec):
        enabled = row.get_active()
        self.settings.set("auto_start", str(enabled).lower())
        self._apply_autostart(enabled)

    def _on_quality_changed(self, row, pspec):
        self.settings.set("image_quality", str(int(row.get_value())))

    def _on_size_changed(self, row, pspec):
        self.settings.set("max_image_size", str(int(row.get_value())))

    def _on_select_script(self, btn):
        dialog = Gtk.FileDialog(title=tr("settings.file_dialog.script"))
        dialog.open(self, None, self._on_script_selected)

    def _on_script_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                path = file.get_path()
                self.settings.set("script_path", path)
                self.script_label.set_label(path)
        except Exception as e:
            print(f"Error selecting script: {e}")

    def _on_clear_script(self, btn):
        self.settings.set("script_path", "")
        self.script_label.set_label(tr("common.not_selected"))

    def _on_apply_hotkey(self, btn):
        value = self.hotkey_entry.get_text().strip() or "disabled"
        self.settings.set("hotkey", value)
        if hasattr(self.app, "apply_hotkey"):
            self.app.apply_hotkey(value, notify=True)
        self.hotkey_help_row.set_subtitle(tr("settings.hotkey.help", binding=value))

    def _on_reset_hotkey(self, btn):
        self.hotkey_entry.set_text("Super+C")
        self._on_apply_hotkey(btn)

    def _on_open_backup_dir(self, btn):
        target = self.app.backup_dir() if hasattr(self.app, "backup_dir") else os.path.expanduser("~/.local/share/clipkeeper/backups")
        os.makedirs(target, exist_ok=True)
        try:
            subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"[ClipKeeper] Failed to open backup folder: {e}")

    def _on_backup_now(self, btn):
        if hasattr(self.app, "create_backup"):
            self.app.create_backup(silent=False)

    def _current_hotkey_display(self) -> str:
        active_binding = get_active_hotkey()
        if active_binding:
            return display_hotkey(active_binding)
        stored = self.settings.get("hotkey")
        return stored if stored else "Super+C"

    def _apply_autostart(self, enabled: bool):
        """Apply autostart toggle by writing/removing desktop entry."""
        autostart_dir = os.path.expanduser("~/.config/autostart")
        autostart_file = os.path.join(autostart_dir, "clipkeeper.desktop")

        if not enabled:
            try:
                os.remove(autostart_file)
            except FileNotFoundError:
                pass
            except OSError as e:
                print(f"[ClipKeeper] Autostart disable error: {e}")
            return

        os.makedirs(autostart_dir, exist_ok=True)
        bin_path = os.path.expanduser("~/.local/bin/clipkeeper")
        if os.path.exists(bin_path):
            exec_cmd = f"{bin_path} --daemon"
        else:
            main_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
            exec_cmd = f"python3 {main_path.replace(' ', '\\ ')} --daemon"

        desktop = "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=ClipKeeper",
                "Comment=Modern clipboard manager for Linux",
                f"Exec={exec_cmd}",
                "Icon=edit-paste",
                "Terminal=false",
                "Categories=Utility;GTK;",
                "Keywords=clipboard;paste;copy;history;",
                "X-GNOME-Autostart-enabled=true",
            ]
        )

        try:
            with open(autostart_file, "w", encoding="utf-8") as f:
                f.write(desktop + "\n")
        except OSError as e:
            print(f"[ClipKeeper] Autostart enable error: {e}")
