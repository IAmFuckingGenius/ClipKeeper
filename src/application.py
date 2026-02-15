"""
ClipKeeper — Application.
Single-instance Adw.Application with daemon mode, system tray,
settings, and menu actions.
"""

import os
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .database import BACKUPS_DIR, Database
from .hotkeys import apply_system_hotkey, default_toggle_command, display_hotkey
from .i18n import set_locale, tr
from .monitor import ClipboardMonitor
from .settings import SettingsManager, SettingsWindow
from .tray import TrayIndicator
from .window import ClipKeeperWindow


class ClipKeeperApp(Adw.Application):
    """Main application class for ClipKeeper with daemon mode."""

    def __init__(self, daemon_mode=False):
        super().__init__(
            application_id="com.clipkeeper.app",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.db = None
        self.monitor = None
        self.window = None
        self.tray = None
        self.settings_manager = None
        self.settings_window = None
        self._css_provider = None
        self._daemon_mode = daemon_mode
        self._backup_timeout_id = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        print("[ClipKeeper] startup...", flush=True)

        # Initialize database
        self.db = Database()

        # Initialize settings
        self.settings_manager = SettingsManager(self.db)
        set_locale(self.settings_manager.get("language"))

        # Apply theme
        self._apply_theme()

        self._update_visuals()

        # Load CSS
        self._load_css()

        # Register actions
        self._register_actions()
        self._setup_backup_timer()
        hotkey_value = self.settings_manager.get("hotkey")
        ok = self.apply_hotkey(hotkey_value, notify=False)
        print(f"[ClipKeeper] hotkey '{hotkey_value}' apply={'ok' if ok else 'FAILED'}", flush=True)

        print("[ClipKeeper] startup done", flush=True)

    def _update_visuals(self):
        """Apply visual settings (theme, compact)."""
        # Accent Color
        accent = self.settings_manager.get("theme_accent")
        
        if accent == "standard":
            if hasattr(self, "_accent_provider"):
                display = Gdk.Display.get_default()
                Gtk.StyleContext.remove_provider_for_display(display, self._accent_provider)
                delattr(self, "_accent_provider")
            return

        colors = {
            "blue": "#3584e4",
            "purple": "#9141ac",
            "green": "#2ec27e",
            "orange": "#ff7800",
            "grey": "#77767b",
        }
        color_val = colors.get(accent, "#3584e4")
        
        # Create a provider for accent color override
        if not hasattr(self, "_accent_provider"):
            self._accent_provider = Gtk.CssProvider()
            display = Gdk.Display.get_default()
            Gtk.StyleContext.add_provider_for_display(
                display, self._accent_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
            )
            
        css = f"""
        @define-color accent_bg_color {color_val};
        @define-color accent_fg_color #ffffff;
        """
        self._accent_provider.load_from_data(css.encode())
        
        # Compact Mode (needs window to be created, so this part checks periodically or when window shows)
        pass

    def update_compact_mode(self):
        if self.window:
            is_compact = self.settings_manager.get_bool("compact_mode")
            if is_compact:
                self.window.add_css_class("compact")
            else:
                self.window.remove_css_class("compact")

    def _apply_theme(self):
        """Apply saved theme setting."""
        theme = self.settings_manager.get("theme")
        style_manager = Adw.StyleManager.get_default()
        themes = {
            "system": Adw.ColorScheme.DEFAULT,
            "light": Adw.ColorScheme.FORCE_LIGHT,
            "dark": Adw.ColorScheme.FORCE_DARK,
        }
        style_manager.set_color_scheme(themes.get(theme, Adw.ColorScheme.DEFAULT))

    def do_activate(self):
        print("[ClipKeeper] activate...", flush=True)

        if self.window is None:
            # First activation — create everything
            self.window = ClipKeeperWindow(self, self.db)
            print("[ClipKeeper] window created", flush=True)

            # Start clipboard monitoring
            self.monitor = ClipboardMonitor(self.db)
            self.monitor.connect("new-clip", self._on_new_clip)
            print("[ClipKeeper] monitor started", flush=True)

            # Start system tray
            self.tray = TrayIndicator(self)
            self._update_tray_stats()
            print(f"[ClipKeeper] tray started (available={self.tray.available})", flush=True)

            # Keep running even when window is hidden (daemon mode)
            self.hold()
            
            self._update_visuals()
            self.update_compact_mode()

            if self._daemon_mode:
                # Don't show window in daemon mode
                print("[ClipKeeper] daemon mode — window hidden", flush=True)
            else:
                self.window.show_at_cursor()
                print("[ClipKeeper] window presented", flush=True)
        else:
            # Toggle window visibility
            self._update_visuals()
            self.update_compact_mode()
            if self.window.is_visible():
                self.window.set_visible(False)
            else:
                self.window.show_at_cursor()
                self.window.search_entry.grab_focus()

    def do_full_quit(self):
        """Actually quit the application (not just hide)."""
        if self.monitor:
            self.monitor.stop()
        if self.tray:
            self.tray.stop()
        self.release()
        self.quit()

    @property
    def is_incognito(self) -> bool:
        return self.monitor.is_incognito if self.monitor else False

    def toggle_incognito(self):
        """Toggle incognito mode (stop recording history)."""
        if self.monitor:
            new_state = not self.monitor.is_incognito
            self.monitor.is_incognito = new_state
            print(f"[ClipKeeper] Incognito mode: {new_state}")
            return new_state
        return False

    def _on_new_clip(self, monitor, clip_id):
        """New clipboard entry detected."""
        if self.window and self.window.is_visible():
            self.window.refresh_list()
        self._update_tray_stats()

    def _update_tray_stats(self):
        """Update tray icon with current stats."""
        if self.tray and self.tray.available and self.db:
            stats = self.db.get_stats()
            self.tray.update_stats(stats)

    # --- Actions ---

    def _register_actions(self):
        """Register Gio.Actions for the menu."""
        actions = {
            "clear-history": self._on_clear_history,
            "export-history": self._on_export,
            "import-history": self._on_import,
            "open-settings": self._on_open_settings,
            "quit": lambda a, p: self.do_full_quit(),
            "toggle": lambda a, p: self.do_activate(),
            "show": self._on_action_show,
        }
        for name, callback in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

    def _on_action_show(self, action, param):
        """Explicitly show the window (don't toggle)."""
        if self.window is None:
            self.do_activate()
        else:
            self._update_visuals()
            self.update_compact_mode()
            self.window.show_at_cursor()
            self.window.search_entry.grab_focus()

    def _on_clear_history(self, action, param):
        if not self.window:
            return
        dialog = Adw.MessageDialog(
            transient_for=self.window,
            heading=tr("app.clear_dialog.title"),
            body=tr("app.clear_dialog.body"),
        )
        dialog.add_response("cancel", tr("common.cancel"))
        dialog.add_response("clear", tr("common.clear"))
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_clear_response)
        dialog.present()

    def _on_clear_response(self, dialog, response):
        if response == "clear":
            self.db.clear_unpinned()
            if self.window:
                self.window.refresh_list()
            self._update_tray_stats()

    def _on_export(self, action, param):
        if not self.window:
            return

        dialog = Gtk.FileDialog(
            title=tr("app.export.title"),
            initial_name="clipkeeper_export.json",
        )
        dialog.save(self.window, None, self._on_export_done)

    def _on_export_done(self, dialog, result):
        try:
            file = dialog.save_finish(result)
            if file:
                path = file.get_path()
                self.db.export_to_json(path)
                self._show_toast(
                    tr("app.toast.export_done", filename=os.path.basename(path))
                )
        except Exception as e:
            print(f"[ClipKeeper] Export error: {e}")

    def _on_import(self, action, param):
        if not self.window:
            return

        dialog = Gtk.FileDialog(
            title=tr("app.import.title"),
        )

        json_filter = Gtk.FileFilter()
        json_filter.set_name(tr("app.import.filter_json"))
        json_filter.add_pattern("*.json")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(json_filter)
        dialog.set_filters(filters)

        dialog.open(self.window, None, self._on_import_done)

    def _on_import_done(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                path = file.get_path()
                count = self.db.import_from_json(path)
                self.window.refresh_list()
                self._update_tray_stats()
                self._show_toast(tr("app.toast.import_done", count=count))
        except Exception as e:
            print(f"[ClipKeeper] Import error: {e}")

    def _on_open_settings(self, action, param):
        if self.window is None:
            self.do_activate()
        if self.settings_window and self.settings_window.is_visible():
            self.settings_window.present()
            return
        self.settings_window = SettingsWindow(self, self.settings_manager)
        self.settings_window.connect("close-request", self._on_settings_close_request)
        self.settings_window.present()

    def _on_settings_close_request(self, window):
        self.settings_window = None
        return False

    def apply_language(self, language_value: str):
        self.settings_manager.set("language", language_value)
        set_locale(language_value)
        self._show_toast(tr("settings.language.restart_hint"))

    def apply_hotkey(self, hotkey_value: str, notify: bool = True) -> bool:
        self.settings_manager.set("hotkey", hotkey_value)
        ok, result = apply_system_hotkey(
            hotkey_value,
            command=default_toggle_command(),
            name=tr("app.name"),
        )
        if notify:
            if ok:
                human = display_hotkey(result)
                self._show_toast(tr("app.toast.hotkey_applied", binding=human))
            else:
                self._show_toast(tr("app.toast.hotkey_failed_details", reason=result))
        return ok

    def backup_dir(self) -> str:
        raw = self.settings_manager.get("backup_dir").strip()
        return os.path.expanduser(raw or BACKUPS_DIR)

    def create_backup(self, silent: bool = True) -> bool:
        try:
            keep = max(1, self.settings_manager.get_int("backup_keep_count"))
            path = self.db.create_backup(self.backup_dir(), keep_files=keep)
            self.settings_manager.set("backup_last_ts", str(time.time()))
            if not silent:
                self._show_toast(
                    tr("app.toast.backup_done", filename=os.path.basename(path))
                )
            return True
        except Exception as e:
            print(f"[ClipKeeper] Backup error: {e}")
            if not silent:
                self._show_toast(tr("app.toast.backup_failed"))
            return False

    def reconfigure_backup(self):
        self._setup_backup_timer()

    def _setup_backup_timer(self):
        if self._backup_timeout_id:
            GLib.source_remove(self._backup_timeout_id)
            self._backup_timeout_id = None

        enabled = self.settings_manager.get_bool("backup_enabled")
        if not enabled:
            return

        interval_minutes = max(5, self.settings_manager.get_int("backup_interval_minutes"))
        interval_seconds = interval_minutes * 60
        self._backup_timeout_id = GLib.timeout_add_seconds(
            interval_seconds, self._on_backup_tick
        )

        last_raw = self.settings_manager.get("backup_last_ts")
        try:
            last_ts = float(last_raw) if last_raw else 0.0
        except (TypeError, ValueError):
            last_ts = 0.0
        if time.time() - last_ts >= interval_seconds:
            GLib.idle_add(self.create_backup, True)

    def _on_backup_tick(self):
        self.create_backup(silent=True)
        return True

    # --- Theme & CSS ---


    def _load_css(self):
        css_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "style.css",
        )
        if os.path.exists(css_path):
            self._css_provider = Gtk.CssProvider()
            self._css_provider.load_from_path(css_path)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                self._css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def _show_toast(self, text: str):
        """Show toast if window supports it."""
        if not self.window or not hasattr(self.window, "add_toast"):
            print(f"[ClipKeeper] {text}", flush=True)
            return
        self.window.add_toast(Adw.Toast(title=text))

    def do_shutdown(self):
        if self._backup_timeout_id:
            GLib.source_remove(self._backup_timeout_id)
            self._backup_timeout_id = None
        if self.monitor:
            self.monitor.stop()
        if self.tray:
            self.tray.stop()
        if self.db:
            self.db.close()
        Adw.Application.do_shutdown(self)
