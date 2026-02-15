"""
ClipKeeper — System Tray Indicator.
Uses a separate lightweight subprocess to show the AppIndicator
(avoids GTK3/GTK4 conflict in the main process).
Falls back gracefully if AppIndicator is not available.
"""

import json
import os
import signal
import subprocess
import sys
import threading
from typing import Optional

from .i18n import tr


# Inline tray script that runs in a SEPARATE process (GTK3 only)
TRAY_SCRIPT = '''
import gi
gi.require_version("Gtk", "3.0")
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3
except (ValueError, ImportError):
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3

from gi.repository import Gtk, GLib
import sys, json, threading, select

class TrayApp:
    def __init__(self):
        import os
        self.labels = {}
        if len(sys.argv) > 2:
            try:
                self.labels = json.loads(sys.argv[2])
            except Exception:
                self.labels = {}

        def _t(key, default):
            value = self.labels.get(key)
            return value if isinstance(value, str) and value else default

        # Icons dir is passed as argv[1] from parent process
        # It should contain hicolor/scalable/apps/clipkeeper-tray.svg
        icons_dir = sys.argv[1] if len(sys.argv) > 1 else ''
        icon_svg = os.path.join(icons_dir, 'hicolor', 'scalable', 'apps', 'clipkeeper-tray.svg')

        if os.path.isfile(icon_svg):
            icon_name = 'clipkeeper-tray'
        else:
            icon_name = 'edit-paste'

        self.indicator = AppIndicator3.Indicator.new(
            "clipkeeper", icon_name,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS
        )
        # Set icon theme path BEFORE setting status  
        if os.path.isfile(icon_svg):
            self.indicator.set_icon_theme_path(icons_dir)
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title(_t("app_name", "ClipKeeper"))

        menu = Gtk.Menu()

        show_item = Gtk.MenuItem(label=_t("show_toggle", "Show / Hide"))
        show_item.connect("activate", lambda _: self.send_cmd("toggle"))
        menu.append(show_item)

        menu.append(Gtk.SeparatorMenuItem())

        self.pause_item = Gtk.CheckMenuItem(label=_t("pause", "Pause"))
        self.pause_item.connect("toggled", lambda i: self.send_cmd("pause" if i.get_active() else "resume"))
        menu.append(self.pause_item)

        menu.append(Gtk.SeparatorMenuItem())

        clear_item = Gtk.MenuItem(label=_t("clear_history", "Clear history"))
        clear_item.connect("activate", lambda _: self.send_cmd("clear"))
        menu.append(clear_item)

        menu.append(Gtk.SeparatorMenuItem())

        self.stats_items_fmt = _t("stats_items_fmt", "{total} items")
        self.stats_pinned_fmt = _t("stats_pinned_fmt", " · {pinned} pinned")
        self.stats_item = Gtk.MenuItem(label=f"📋 {self.stats_items_fmt.format(total=0)}")
        self.stats_item.set_sensitive(False)
        menu.append(self.stats_item)

        menu.append(Gtk.SeparatorMenuItem())

        settings_item = Gtk.MenuItem(label=_t("settings", "Settings"))
        settings_item.connect("activate", lambda _: self.send_cmd("settings"))
        menu.append(settings_item)

        restart_item = Gtk.MenuItem(label=_t("restart", "Restart"))
        restart_item.connect("activate", lambda _: self.send_cmd("restart"))
        menu.append(restart_item)

        quit_item = Gtk.MenuItem(label=_t("quit", "Quit"))
        quit_item.connect("activate", lambda _: self.send_cmd("quit"))
        menu.append(quit_item)

        menu.show_all()
        self.indicator.set_menu(menu)

        # Ensure we exit if parent dies (Linux only)
        try:
            import ctypes
            libc = ctypes.CDLL("libc.so.6")
            PR_SET_PDEATHSIG = 1
            SIGTERM = 15
            libc.prctl(PR_SET_PDEATHSIG, SIGTERM)
        except Exception:
            pass

        # Listen for commands from parent on stdin
        thread = threading.Thread(target=self.read_stdin, daemon=True)
        thread.start()

    def send_cmd(self, cmd):
        try:
            print(json.dumps({"action": cmd}), flush=True)
        except BrokenPipeError:
            sys.exit(0)

    def read_stdin(self):
        try:
            for line in sys.stdin:
                if not line:
                    break
                try:
                    data = json.loads(line.strip())
                    if "stats" in data:
                        GLib.idle_add(self.update_stats, data["stats"])
                except (json.JSONDecodeError, KeyError):
                    pass
        except (EOFError, OSError):
            pass
        finally:
            # Parent closed pipe or died
            GLib.idle_add(Gtk.main_quit)

    def update_stats(self, stats):
        try:
            text = f"📋 {self.stats_items_fmt.format(total=stats.get('total', 0))}"
            if stats.get('pinned'):
                text += self.stats_pinned_fmt.format(pinned=stats['pinned'])
            self.stats_item.set_label(text)
        except Exception:
            pass

    def run(self):
        Gtk.main()

if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())
    signal.signal(signal.SIGINT, lambda *_: Gtk.main_quit())
    app = TrayApp()
    app.run()
'''


class TrayIndicator:
    """System tray indicator that runs in a subprocess to avoid GTK3/4 conflicts."""

    def __init__(self, app):
        self.app = app
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._script_path: Optional[str] = None
        self._available = False

        self._start_subprocess()

    def _start_subprocess(self):
        """Start the tray indicator subprocess."""
        try:
            # Compute the icons directory
            icons_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data", "icons",
            )

            # Write the tray script to a temp file (avoids -c quoting issues)
            import tempfile
            self._script_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", prefix="clipkeeper_tray_", delete=False
            )
            self._script_file.write(TRAY_SCRIPT)
            self._script_file.flush()
            self._script_file.close()
            self._script_path = self._script_file.name

            self._process = subprocess.Popen(
                [
                    sys.executable,
                    self._script_path,
                    icons_dir,
                    json.dumps(
                        {
                            "app_name": tr("app.name"),
                            "show_toggle": tr("tray.show_toggle"),
                            "pause": tr("tray.pause"),
                            "clear_history": tr("tray.clear_history"),
                            "stats_items_fmt": tr("tray.stats.items"),
                            "stats_pinned_fmt": tr("tray.stats.pinned"),
                            "settings": tr("tray.settings"),
                            "restart": tr("tray.restart"),
                            "quit": tr("tray.quit"),
                        },
                        ensure_ascii=False,
                    ),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # Line buffered
            )
            self._available = True

            # Read commands from tray subprocess
            self._reader_thread = threading.Thread(target=self._read_commands, daemon=True)
            self._reader_thread.start()
        except Exception as e:
            print(f"[ClipKeeper] Tray subprocess failed: {e}")
            self._available = False
            self._cleanup_script_file()

    def _read_commands(self):
        """Read JSON commands from the tray subprocess stdout."""
        if not self._process or not self._process.stdout:
            return

        try:
            for line in self._process.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    action = data.get("action")
                    if action:
                        from gi.repository import GLib
                        GLib.idle_add(self._handle_action, action)
                except json.JSONDecodeError:
                    # Log non-JSON output (likely warnings or errors)
                    print(f"[Tray] {line}", flush=True)
        except Exception as e:
            print(f"[ClipKeeper] Tray reader error: {e}", flush=True)
        finally:
            print(f"[ClipKeeper] Tray subprocess exited code={self._process.poll()}", flush=True)
            self._cleanup_script_file()

    def _handle_action(self, action: str):
        """Handle an action from the tray menu."""
        if action == "toggle":
            self.app.activate()
        elif action == "pause" and self.app.monitor:
            self.app.monitor.paused = True
        elif action == "resume" and self.app.monitor:
            self.app.monitor.paused = False
        elif action == "settings":
            self.app.activate_action("open-settings", None)
        elif action == "clear" and self.app.db:
            self.app.db.clear_unpinned()
            if self.app.window and self.app.window.is_visible():
                self.app.window.refresh_list()
            if hasattr(self.app, "_update_tray_stats"):
                self.app._update_tray_stats()
        elif action == "quit":
            self.app.do_full_quit()
        elif action == "restart":
            self.app.do_full_quit()
            # Re-execute the current script
            python = sys.executable
            os.execl(python, python, *sys.argv)

    def update_stats(self, stats: dict):
        """Send stats update to the tray subprocess."""
        if not self._available or not self._process or self._process.poll() is not None:
            return
        try:
            msg = json.dumps({"stats": stats}) + "\n"
            self._process.stdin.write(msg)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError):
            self._available = False

    def stop(self):
        """Stop the tray subprocess."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=2)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
        self._cleanup_script_file()

    @property
    def available(self) -> bool:
        return self._available

    def _cleanup_script_file(self):
        """Remove temporary tray script file if it exists."""
        if self._script_path and os.path.exists(self._script_path):
            try:
                os.remove(self._script_path)
            except OSError:
                pass
            finally:
                self._script_path = None
