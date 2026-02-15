"""
ClipKeeper — Main Window.
Popup window with category filters, search, history list, quick actions,
favorites filter, export/import, and large preview.
"""

import subprocess

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from .content_detector import ContentDetector
from .database import Database
from .i18n import tr
from .item_widget import ClipItemWidget
from .preview import PreviewPopover
from .utils import load_texture_from_path


# Categories for filter pills
CATEGORIES = ["all", "text", "url", "code", "image", "email", "phone", "color"]


class ClipKeeperWindow(Adw.ApplicationWindow):
    """Main popup window for ClipKeeper clipboard manager."""

    def __init__(self, app, db: Database):
        super().__init__(
            application=app,
            title=tr("app.name"),
            default_width=480,
            default_height=660,
            resizable=True,
        )
        self.db = db
        self._search_text = ""
        self._active_category = "all"
        self._favorites_only = False
        self._snippets_only = False
        self._search_timeout_id = None

        self._build_ui()
        self._setup_shortcuts()
        self.refresh_list()

        # Override close to hide instead of quit (daemon mode)
        self.connect("close-request", self._on_close_request)

    def show_at_cursor(self):
        """Show window near the mouse cursor position."""
        self.refresh_list()
        self._move_to_cursor()
        self.present()
        # Focus the first list row for arrow navigation
        GLib.idle_add(self._focus_first_row)

    def _move_to_cursor(self):
        """Move the window to the mouse cursor position."""
        try:
            # Try hyprctl first (Hyprland)
            result = subprocess.run(
                ["hyprctl", "cursorpos"], capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0 and "," in result.stdout:
                parts = result.stdout.strip().split(",")
                cx, cy = int(parts[0].strip()), int(parts[1].strip())
                self._apply_position(cx, cy)
                return
        except Exception:
            pass

        try:
            # Fallback: xdotool (X11)
            result = subprocess.run(
                ["xdotool", "getmouselocation"], capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split()
                cx = int(parts[0].split(":")[1])
                cy = int(parts[1].split(":")[1])
                self._apply_position(cx, cy)
                return
        except Exception:
            pass

    def _apply_position(self, cursor_x: int, cursor_y: int):
        """Apply window position near cursor, clamped to screen."""
        win_w = self.get_default_size()[0] or 480
        win_h = self.get_default_size()[1] or 660

        # Get monitor geometry that contains cursor
        display = Gdk.Display.get_default()
        monitors = display.get_monitors()
        monitor_geom = None
        for idx in range(monitors.get_n_items()):
            monitor = monitors.get_item(idx)
            geom = monitor.get_geometry()
            if geom.x <= cursor_x < geom.x + geom.width and geom.y <= cursor_y < geom.y + geom.height:
                monitor_geom = geom
                break

        if monitor_geom is None and monitors.get_n_items() > 0:
            monitor_geom = monitors.get_item(0).get_geometry()

        if monitor_geom is not None:
            screen_x = monitor_geom.x
            screen_y = monitor_geom.y
            screen_w = monitor_geom.width
            screen_h = monitor_geom.height
        else:
            screen_x = 0
            screen_y = 0
            screen_w, screen_h = 1920, 1080

        # Position: center horizontally on cursor, top at cursor
        x = cursor_x - win_w // 2
        y = cursor_y - 20  # slightly above cursor

        # Clamp to screen bounds
        x = max(screen_x + 10, min(x, screen_x + screen_w - win_w - 10))
        y = max(screen_y + 10, min(y, screen_y + screen_h - win_h - 10))

        # On X11, moving surface can work. On Wayland this is intentionally ignored.
        try:
            backend = type(display).__name__.lower()
            if "x11" in backend:
                surface = self.get_surface()
                if surface and hasattr(surface, "move"):
                    surface.move(x, y)
        except Exception:
            pass

        # Keep requested size consistent even when compositor ignores move requests.
        self.set_default_size(win_w, win_h)

    def _focus_first_row(self):
        """Focus the first row in the list for keyboard navigation."""
        row = self.listbox.get_row_at_index(0)
        if row:
            self.listbox.select_row(row)
            row.grab_focus()
        return False

    def _on_close_request(self, window):
        """Hide instead of closing (daemon mode)."""
        self.set_visible(False)
        return True  # Prevent default close

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(main_box)
        self.set_content(self._toast_overlay)

        # --- Header Bar ---
        header = Adw.HeaderBar(css_classes=["flat"])

        # Title
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.CENTER)
        title_box.append(Gtk.Image(icon_name="edit-paste-symbolic", pixel_size=18))
        title_box.append(Gtk.Label(label=tr("app.name"), css_classes=["title"]))
        header.set_title_widget(title_box)

        # Left: Stats
        self.stats_label = Gtk.Label(label="", css_classes=["dim-label", "caption"])
        header.pack_start(self.stats_label)

        # Right: Menu button
        menu_btn = Gtk.MenuButton(
            icon_name="open-menu-symbolic",
            css_classes=["flat"],
            tooltip_text=tr("window.menu"),
        )
        menu_btn.set_menu_model(self._build_menu())
        header.pack_end(menu_btn)

        main_box.append(header)

        # --- Search ---
        search_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            margin_start=12, margin_end=12, margin_top=4, margin_bottom=6,
        )
        self.search_entry = Gtk.SearchEntry(
            placeholder_text=tr("window.search_placeholder"),
            hexpand=True,
            css_classes=["clip-search"],
        )
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("activate", self._on_search_activate)
        search_box.append(self.search_entry)
        main_box.append(search_box)

        # --- Category Filter Pills ---
        filter_scroll = Gtk.ScrolledWindow(
            vscrollbar_policy=Gtk.PolicyType.NEVER,
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            margin_start=8, margin_end=8, margin_bottom=4,
            max_content_height=40,
        )
        filter_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_start=4, margin_end=4,
            css_classes=["filter-pills"],
        )

        self._filter_buttons = {}
        for cat in CATEGORIES:
            label = ContentDetector.get_category_label(cat)
            btn = Gtk.ToggleButton(
                label=label,
                css_classes=["pill", f"pill-{cat}"],
                active=(cat == "all"),
            )
            btn.connect("toggled", self._on_category_toggled, cat)
            filter_box.append(btn)
            self._filter_buttons[cat] = btn

        # Favorites toggle
        fav_btn = Gtk.ToggleButton(
            label=tr("window.favorites"),
            css_classes=["pill", "pill-fav"],
        )
        fav_btn.connect("toggled", self._on_favorites_toggled)
        filter_box.append(fav_btn)
        self._fav_button = fav_btn

        # Snippets toggle
        snip_btn = Gtk.ToggleButton(
            label=tr("window.snippets"),
            css_classes=["pill", "pill-fav"], # Re-use favored style or create new
        )
        snip_btn.connect("toggled", self._on_snippets_toggled)
        filter_box.append(snip_btn)
        self._snip_button = snip_btn

        filter_scroll.set_child(filter_box)
        main_box.append(filter_scroll)

        # --- Separator ---
        main_box.append(Gtk.Separator(css_classes=["spacer"]))

        # --- Scrollable List ---
        scrolled = Gtk.ScrolledWindow(
            vexpand=True,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            css_classes=["clip-scroll"],
        )
        self.listbox = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.SINGLE,
            css_classes=["clip-list"],
            activate_on_single_click=True,
        )
        self.listbox.set_placeholder(self._create_placeholder())
        self.listbox.connect("row-activated", self._on_row_activated)
        scrolled.set_child(self.listbox)
        main_box.append(scrolled)

        # --- Bottom Bar ---
        main_box.append(Gtk.Separator(css_classes=["spacer"]))
        bottom = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            margin_start=12, margin_end=12, margin_top=6, margin_bottom=6, spacing=8,
        )
        bottom.append(Gtk.Label(
            label=tr("window.copy_hint"),
            css_classes=["dim-label", "caption"], hexpand=True, halign=Gtk.Align.START,
        ))
        bottom.append(Gtk.Label(
            label=tr("window.hide_hint"),
            css_classes=["dim-label", "caption"], halign=Gtk.Align.END,
        ))
        main_box.append(bottom)

    def add_toast(self, toast: Adw.Toast):
        """Bridge method used by application actions."""
        if hasattr(self, "_toast_overlay"):
            self._toast_overlay.add_toast(toast)

    def _build_menu(self) -> Gio.Menu:
        """Build the header menu."""
        menu = Gio.Menu()
        menu.append(tr("window.menu.clear_history"), "app.clear-history")
        menu.append(tr("window.menu.export"), "app.export-history")
        menu.append(tr("window.menu.import"), "app.import-history")

        section = Gio.Menu()
        section.append(tr("window.menu.settings"), "app.open-settings")
        menu.append_section(None, section)

        return menu

    def _create_placeholder(self) -> Gtk.Widget:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12,
            halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER,
            margin_top=60, margin_bottom=60,
        )
        box.append(Gtk.Image(icon_name="edit-paste-symbolic", pixel_size=64, css_classes=["dim-label"], opacity=0.4))
        box.append(Gtk.Label(label=tr("window.empty"), css_classes=["title-3", "dim-label"]))
        box.append(Gtk.Label(label=tr("window.empty_help"), css_classes=["dim-label"]))
        return box

    def _setup_shortcuts(self):
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(controller)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.set_visible(False)
            return True

        # Ctrl+F to focus search
        if keyval == Gdk.KEY_f and state & Gdk.ModifierType.CONTROL_MASK:
            self.search_entry.grab_focus()
            return True

        # Arrow navigation in the list
        if keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            selected = self.listbox.get_selected_row()
            if selected is None:
                # No selection — select the first row
                row = self.listbox.get_row_at_index(0)
                if row:
                    self.listbox.select_row(row)
                    row.grab_focus()
                return True

            idx = selected.get_index()
            if keyval == Gdk.KEY_Down:
                next_row = self.listbox.get_row_at_index(idx + 1)
            else:
                next_row = self.listbox.get_row_at_index(max(0, idx - 1))

            if next_row:
                self.listbox.select_row(next_row)
                next_row.grab_focus()
            return True

        # Enter to activate selected row (copy & close)
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            selected = self.listbox.get_selected_row()
            if selected:
                self._on_row_activated(self.listbox, selected)
                return True
            return False

        # If typing text, redirect to search
        if keyval >= Gdk.KEY_space and keyval <= Gdk.KEY_asciitilde:
            if not self.search_entry.has_focus():
                self.search_entry.grab_focus()
                # Forward the key
                return False

        return False

    # --- List Management ---

    def refresh_list(self):
        while True:
            row = self.listbox.get_row_at_index(0)
            if row is None:
                break
            self.listbox.remove(row)

        category = self._active_category if self._active_category != "all" else None
        clips = self.db.get_clips(
            search=self._search_text or None,
            category=category,
            favorites_only=self._favorites_only,
            snippets_only=self._snippets_only,
            limit=100,
        )

        for clip in clips:
            # Assuming ClipKeeperWindow has access to settings via application
            app = self.get_application()
            settings = getattr(app, "settings_manager", None)
            widget = ClipItemWidget(dict(clip), settings_manager=settings)
            widget.connect("clip-delete", self._on_clip_delete)
            widget.connect("clip-pin", self._on_clip_pin)
            widget.connect("clip-favorite", self._on_clip_favorite)
            widget.connect("clip-preview", self._on_clip_preview)
            widget.connect("clip-edit", self._on_clip_edit)
            widget.connect("clip-snippet", self._on_clip_snippet)
            self.listbox.append(widget)

        self._update_stats()

    def _update_stats(self):
        stats = self.db.get_stats()
        parts = [f"{stats['total']}"]
        if stats["pinned"]:
            parts.append(tr("window.stats.pinned", count=stats["pinned"]))
        if stats["favorites"]:
            parts.append(tr("window.stats.favorites", count=stats["favorites"]))
        self.stats_label.set_label(" · ".join(parts))

    # --- Filter Handlers ---

    def _on_category_toggled(self, button, category):
        if button.get_active():
            self._active_category = category
            # Deactivate other category buttons
            for cat, btn in self._filter_buttons.items():
                if cat != category:
                    btn.handler_block_by_func(self._on_category_toggled)
                    btn.set_active(False)
                    btn.handler_unblock_by_func(self._on_category_toggled)
            self.refresh_list()
        else:
            # Don't allow deactivating the last active — reset to "all"
            if self._active_category == category:
                button.handler_block_by_func(self._on_category_toggled)
                button.set_active(True)
                button.handler_unblock_by_func(self._on_category_toggled)

    def _on_favorites_toggled(self, button):
        self._favorites_only = button.get_active()
        if self._favorites_only:
            # uncheck Snippets if strictly exclusive? No, can replace logic.
            # But let's unset snippets to avoid confusion or allow both?
            # Let's keep them independent for now.
            if self._snip_button.get_active():
                 self._snip_button.set_active(False)
        self.refresh_list()

    def _on_snippets_toggled(self, button):
        self._snippets_only = button.get_active()
        if self._snippets_only:
             if self._fav_button.get_active():
                 self._fav_button.set_active(False)
        self.refresh_list()

    # --- Search ---

    def _on_search_changed(self, entry):
        if self._search_timeout_id:
            GLib.source_remove(self._search_timeout_id)
        self._search_timeout_id = GLib.timeout_add(200, self._do_search)

    def _do_search(self) -> bool:
        self._search_text = self.search_entry.get_text()
        self.refresh_list()
        self._search_timeout_id = None
        return False

    def _on_search_activate(self, entry):
        row = self.listbox.get_row_at_index(0)
        if row:
            self._on_row_activated(self.listbox, row)

    # --- Row Actions ---

    def _on_row_activated(self, listbox, row):
        if not isinstance(row, ClipItemWidget):
            return

        clip = self.db.get_clip_by_id(row.clip_id)
        if clip is None:
            return

        display = Gdk.Display.get_default()
        clipboard = display.get_clipboard()

        if clip["content_type"] == "text" and clip["text_content"]:
            content = Gdk.ContentProvider.new_for_value(
                GObject.Value(GObject.TYPE_STRING, clip["text_content"])
            )
            clipboard.set_content(content)
        elif clip["content_type"] == "image" and clip["image_path"]:
            texture = load_texture_from_path(clip["image_path"])
            if texture:
                content = Gdk.ContentProvider.new_for_value(
                    GObject.Value(Gdk.Texture.__gtype__, texture)
                )
                clipboard.set_content(content)

        self.db.update_used_at(row.clip_id)
        self.set_visible(False)

    def _on_clip_delete(self, widget, clip_id):
        self.db.delete_clip(clip_id)
        self.refresh_list()

    def _on_clip_pin(self, widget, clip_id):
        new_state = self.db.toggle_pin(clip_id)
        if isinstance(widget, ClipItemWidget):
            widget.update_pin_state(new_state)
        self.refresh_list()

    def _on_clip_favorite(self, widget, clip_id):
        new_state = self.db.toggle_favorite(clip_id)
        if isinstance(widget, ClipItemWidget):
            widget.update_favorite_state(new_state)
        self.refresh_list()

    def _on_clip_preview(self, widget, clip_id):
        clip = self.db.get_clip_by_id(clip_id)
        if clip:
            preview = PreviewPopover(self.get_application(), dict(clip))
            preview.present()

    def _on_clip_edit(self, widget, clip_id, new_text):
        if self.db.update_clip_text(clip_id, new_text):
            self.refresh_list()

    def _on_clip_snippet(self, widget, clip_id):
        new_state = self.db.toggle_snippet(clip_id)
        if isinstance(widget, ClipItemWidget):
            widget.update_snippet_state(new_state)
        # If we are in snippets view, we might want to remove it from list
        if self._snippets_only and not new_state:
            self.refresh_list()


    def _on_incognito_toggled(self, btn):
        app = self.get_application()
        if app and hasattr(app, "toggle_incognito"):
            state = app.toggle_incognito()
            if state:
                btn.set_icon_name("user-spy-symbolic")
                btn.set_tooltip_text(tr("window.incognito.on"))
                btn.add_css_class("suggested-action") # Highlight
            else:
                btn.set_icon_name("user-available-symbolic")
                btn.set_tooltip_text(tr("window.incognito.off"))
                btn.remove_css_class("suggested-action")
