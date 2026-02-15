"""
ClipKeeper — Item Widget.
Custom ListBoxRow for displaying a clipboard item with type-specific icons,
quick actions, syntax highlighting, link preview, and drag support.
"""

import json
import subprocess

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk

from .content_detector import ContentDetector
from .i18n import tr
from .utils import (
    format_time_ago,
    get_category_emoji,
    load_pixbuf_from_path,
)


class ClipItemWidget(Gtk.ListBoxRow):
    """A row widget representing a single clipboard history entry."""

    __gsignals__ = {
        "clip-delete": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "clip-pin": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "clip-favorite": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "clip-preview": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "clip-edit": (GObject.SignalFlags.RUN_FIRST, None, (int, str)),
        "clip-snippet": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self, clip_data, settings_manager=None):
        super().__init__()
        self.clip_data = clip_data
        self.settings = settings_manager
        self.clip_id = clip_data["id"]
        self.content_type = clip_data["content_type"]
        self.category = clip_data.get("category", "text") or "text"
        self.content_subtype = clip_data.get("content_subtype")
        self.text_content = clip_data["text_content"]
        self.image_path = clip_data.get("image_path")
        self.thumb_path = clip_data.get("thumb_path")
        self.pinned = bool(clip_data["pinned"])
        self.favorite = bool(clip_data.get("favorite", 0))
        self.is_sensitive = bool(clip_data.get("is_sensitive", 0))
        self.masked = self.is_sensitive
        self.created_at = clip_data["created_at"]
        self.used_at = clip_data["used_at"]
        self.use_count = clip_data.get("use_count", 1) or 1
        self.preview_text = clip_data["preview"] or ""
        self.metadata = {}
        if clip_data.get("metadata_json"):
            try:
                self.metadata = json.loads(clip_data["metadata_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        
        # We need to keep reference to label to update it
        self.preview_label = None

        self.set_css_classes(["clip-row"])
        if self.pinned:
            self.add_css_class("pinned")
        if self.favorite:
            self.add_css_class("favorited")
        self.add_css_class(f"category-{self.category}")

        self._build_ui()
        self._setup_drag()

    def _build_ui(self):
        # Main horizontal box
        main_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            margin_top=8,
            margin_bottom=8,
            margin_start=12,
            margin_end=8,
        )
        self.set_child(main_box)

        # Left: Type indicator
        main_box.append(self._create_left_indicator())

        # Center: Content
        center_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=3,
            hexpand=True,
            valign=Gtk.Align.CENTER,
        )
        main_box.append(center_box)

        # Preview text
        if self.category == "code" and self.text_content:
            # Keep list preview plain-text to avoid GTK markup rendering edge-cases.
            text_to_show = tr("item.masked") if self.masked else self.preview_text
            self.preview_label = Gtk.Label(
                use_markup=False,
                label=text_to_show,
                xalign=0,
                lines=2,
                ellipsize=3,
                max_width_chars=44,
                css_classes=["clip-preview", "monospace"],
            )
        elif self.category == "color":
            color_val = self.metadata.get("color_value", self.preview_text)
            self.preview_label = Gtk.Label(
                label=color_val,
                xalign=0,
                css_classes=["clip-preview", "monospace"],
            )
        else:
            text_to_show = tr("item.masked") if self.masked else self.preview_text
            self.preview_label = Gtk.Label(
                label=text_to_show,
                xalign=0,
                wrap=True,
                wrap_mode=2,
                max_width_chars=44,
                lines=2,
                ellipsize=3,
                css_classes=["clip-preview"],
            )
            if self.masked:
                self.preview_label.add_css_class("dim-label")

        center_box.append(self.preview_label)

        # Bottom row: metadata
        bottom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        center_box.append(bottom_row)

        # Time
        time_label = Gtk.Label(
            label=format_time_ago(self.used_at),
            xalign=0,
            css_classes=["clip-time", "dim-label"],
        )
        bottom_row.append(time_label)

        # Page title for URLs
        if self.metadata.get("page_title"):
            title_label = Gtk.Label(
                label=f"· {self.metadata['page_title'][:35]}",
                xalign=0,
                ellipsize=3,
                css_classes=["clip-meta", "dim-label"],
            )
            bottom_row.append(title_label)

        # Domain for URLs
        if self.metadata.get("domain"):
            domain_label = Gtk.Label(
                label=f"· {self.metadata['domain']}",
                xalign=0,
                css_classes=["clip-meta", "dim-label"],
            )
            bottom_row.append(domain_label)

        # Language for code
        if self.metadata.get("language"):
            lang_label = Gtk.Label(
                label=f"· {self.metadata['language']}",
                xalign=0,
                css_classes=["clip-meta", "dim-label", "monospace"],
            )
            bottom_row.append(lang_label)

        # Use count if > 1
        if self.use_count and self.use_count > 1:
            count_label = Gtk.Label(
                label=f"· ×{self.use_count}",
                xalign=0,
                css_classes=["clip-meta", "dim-label"],
            )
            bottom_row.append(count_label)

        # Right: Action buttons
        actions_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2,
            valign=Gtk.Align.CENTER,
            css_classes=["clip-actions"],
        )
        main_box.append(actions_box)

        # Top actions row
        top_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        actions_box.append(top_actions)

        # Collect all action buttons for navigation
        self.action_buttons = []
        
        # Get settings manager from root (passed in __init__)
        def should_show(key):
            if not self.settings:
                return True
            return self.settings.get(f"show_action_{key}") == "true"

        # Quick action (type-specific)
        if should_show("quick"):
            quick_action = self._get_quick_action()
            if quick_action:
                icon, tooltip, callback = quick_action
                qa_btn = Gtk.Button(
                    icon_name=icon,
                    css_classes=["flat", "circular", "clip-action-btn", "quick-action-btn"],
                    tooltip_text=tooltip,
                    valign=Gtk.Align.CENTER,
                    focusable=True,
                )
                qa_btn.connect("clicked", callback)
                top_actions.append(qa_btn)
                self.action_buttons.append(qa_btn)

        # Smart Actions: Edit (for text)
        if self.text_content and should_show("edit"):
            edit_btn = Gtk.Button(
                icon_name="document-edit-symbolic",
                css_classes=["flat", "circular", "clip-action-btn"],
                tooltip_text=tr("item.tooltip.edit"),
                valign=Gtk.Align.CENTER,
                focusable=True,
            )
            edit_btn.connect("clicked", self._on_edit_clicked)
            top_actions.append(edit_btn)
            self.action_buttons.append(edit_btn)

        # Smart Actions: Translate and QR (for text)
        if self.text_content:
            # Translate
            if should_show("translate"):
                trans_btn = Gtk.Button(
                    icon_name="preferences-desktop-locale-symbolic",
                    css_classes=["flat", "circular", "clip-action-btn"],
                    tooltip_text=tr("item.tooltip.translate"),
                    valign=Gtk.Align.CENTER,
                    focusable=True,
                )
                trans_btn.connect("clicked", self._on_translate_clicked)
                top_actions.append(trans_btn)
                self.action_buttons.append(trans_btn)

            # QR Code
            if should_show("qr"):
                from . import actions
                if actions.HAS_QR:
                    qr_btn = Gtk.Button(
                        icon_name="camera-video-symbolic", 
                        css_classes=["flat", "circular", "clip-action-btn"],
                        tooltip_text=tr("item.tooltip.qr"),
                        valign=Gtk.Align.CENTER,
                        focusable=True,
                    )
                    qr_btn.connect("clicked", self._on_qr_clicked)
                    top_actions.append(qr_btn)
                    self.action_buttons.append(qr_btn)

        # Reveal/Hide Button (for sensitive)
        if self.is_sensitive:
            icon = "view-reveal-symbolic" if self.masked else "view-conceal-symbolic"
            reveal_btn = Gtk.Button(
                icon_name=icon,
                css_classes=["flat", "circular", "clip-action-btn"],
                tooltip_text=tr("item.tooltip.reveal"),
                valign=Gtk.Align.CENTER,
                focusable=True,
            )
            reveal_btn.connect("clicked", self._on_reveal_clicked)
            top_actions.append(reveal_btn)
            self.action_buttons.append(reveal_btn)

        # Preview button
        if should_show("preview"):
            preview_btn = Gtk.Button(
                icon_name="view-more-symbolic",
                css_classes=["flat", "circular", "clip-action-btn"],
                tooltip_text=tr("item.tooltip.preview"),
                valign=Gtk.Align.CENTER,
                focusable=True,
            )
            preview_btn.connect("clicked", self._on_preview_clicked)
            top_actions.append(preview_btn)
            self.action_buttons.append(preview_btn)

        # Bottom actions row
        bottom_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        actions_box.append(bottom_actions)

        # Favorite button
        if should_show("favorite"):
            fav_icon = "starred-symbolic" if self.favorite else "non-starred-symbolic"
            self.fav_btn = Gtk.Button(
                icon_name=fav_icon,
                css_classes=["flat", "circular", "clip-action-btn"],
                tooltip_text=tr("item.tooltip.favorite"),
                valign=Gtk.Align.CENTER,
                focusable=True,
            )
            if self.favorite:
                self.fav_btn.add_css_class("favorite-btn")
            self.fav_btn.connect("clicked", self._on_favorite_clicked)
            bottom_actions.append(self.fav_btn)
            self.action_buttons.append(self.fav_btn)

        # Pin button
        if should_show("pin"):
            pin_icon = "view-pin-symbolic" if self.pinned else "view-pin-symbolic"
            self.pin_btn = Gtk.Button(
                icon_name=pin_icon,
                css_classes=["flat", "circular", "clip-action-btn"],
                tooltip_text=tr("item.tooltip.pin") if not self.pinned else tr("item.tooltip.unpin"),
                valign=Gtk.Align.CENTER,
                focusable=True,
            )
            if self.pinned:
                self.pin_btn.add_css_class("pinned-btn")
            self.pin_btn.connect("clicked", self._on_pin_clicked)
            bottom_actions.append(self.pin_btn)
            self.action_buttons.append(self.pin_btn)

        # Snippet button
        if should_show("snippet"):
            self.is_snippet = bool(self.clip_data.get("is_snippet", 0))
            snip_icon = "user-bookmarks-symbolic"
            self.snip_btn = Gtk.Button(
                icon_name=snip_icon,
                css_classes=["flat", "circular", "clip-action-btn"],
                tooltip_text=tr("item.tooltip.to_snippets") if not self.is_snippet else tr("item.tooltip.remove_snippets"),
                valign=Gtk.Align.CENTER,
                focusable=True,
            )
            if self.is_snippet:
                self.snip_btn.add_css_class("pinned-btn") 
                
            self.snip_btn.connect("clicked", self._on_snippet_clicked)
            bottom_actions.append(self.snip_btn)
            self.action_buttons.append(self.snip_btn)

        if should_show("delete"):
            delete_btn = Gtk.Button(
                icon_name="edit-delete-symbolic",
                css_classes=["flat", "circular", "clip-action-btn", "delete-btn"],
                tooltip_text=tr("item.tooltip.delete"),
                valign=Gtk.Align.CENTER,
                focusable=True,
            )
            delete_btn.connect("clicked", self._on_delete_clicked)
            bottom_actions.append(delete_btn)
            self.action_buttons.append(delete_btn)

        # Keyboard controller for navigating actions
        self._key_controller = Gtk.EventControllerKey()
        self._key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(self._key_controller)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle Left/Right arrows to navigate actions."""
        if keyval == Gdk.KEY_Right:
            # If row is focused, move to first button
            if self.is_focus():
                if self.action_buttons:
                    self.action_buttons[0].grab_focus()
                    return True
            # If a button is focused, move to next
            for i, btn in enumerate(self.action_buttons):
                if btn.is_focus():
                    if i + 1 < len(self.action_buttons):
                        self.action_buttons[i+1].grab_focus()
                    return True
        elif keyval == Gdk.KEY_Left:
            # If a button is focused, move left or back to row
            for i, btn in enumerate(self.action_buttons):
                if btn.is_focus():
                    if i > 0:
                        self.action_buttons[i-1].grab_focus()
                    else:
                        self.grab_focus()
                    return True
        return False

    def _create_left_indicator(self) -> Gtk.Widget:
        """Create left-side icon or thumbnail."""
        if self.content_type == "image" and self.thumb_path:
            pixbuf = load_pixbuf_from_path(self.thumb_path, size=48)
            if pixbuf:
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                frame = Gtk.Frame(css_classes=["clip-image-frame"])
                picture = Gtk.Picture(
                    paintable=texture,
                    content_fit=Gtk.ContentFit.COVER,
                    width_request=48,
                    height_request=48,
                    css_classes=["clip-thumbnail"],
                )
                frame.set_child(picture)
                return frame

        if self.category == "color":
            color_val = self.metadata.get("color_value", "#888")
            color_box = Gtk.Frame(css_classes=["clip-color-frame"])
            # Use a drawing area for the color swatch
            swatch = Gtk.Box(
                width_request=48,
                height_request=48,
                css_classes=["color-swatch"],
            )
            # Apply inline color via CSS — we can't set bg directly in GTK4
            # So use a label with the color emoji
            color_label = Gtk.Label(
                label="██",
                css_classes=["color-swatch-label"],
            )
            swatch.append(color_label)
            color_box.set_child(swatch)
            return color_box

        # Default icon
        icon_name = ContentDetector.get_category_icon(self.category)
        frame = Gtk.Frame(css_classes=["clip-icon-frame", f"icon-{self.category}"])
        icon = Gtk.Image(
            icon_name=icon_name,
            pixel_size=22,
            css_classes=["clip-type-icon"],
            margin_top=8,
            margin_bottom=8,
            margin_start=8,
            margin_end=8,
        )
        frame.set_child(icon)
        return frame

    def _get_quick_action(self):
        """Get type-specific quick action (icon, tooltip, callback)."""
        if self.category == "url":
            return ("web-browser-symbolic", tr("item.quick.open_url"), self._on_open_url)
        elif self.category == "email":
            return ("mail-send-symbolic", tr("item.quick.send_email"), self._on_open_email)
        elif self.category == "phone":
            return ("call-start-symbolic", tr("item.quick.dial"), self._on_dial_phone)
        return None

    def _setup_drag(self):
        """Setup drag-and-drop source."""
        if self.text_content:
            drag_source = Gtk.DragSource()
            drag_source.set_actions(Gdk.DragAction.COPY)
            drag_source.connect("prepare", self._on_drag_prepare)
            self.add_controller(drag_source)

    def _on_drag_prepare(self, source, x, y):
        """Prepare drag data."""
        if self.text_content:
            value = GObject.Value(GObject.TYPE_STRING, self.text_content)
            return Gdk.ContentProvider.new_for_value(value)
        return None

    # --- Signal Handlers ---
    
    def _on_edit_clicked(self, btn):
        from .edit_dialog import EditDialog
        # We need a proper parent window. traversing up or finding root
        root = self.get_root()
        dialog = EditDialog(root, self.text_content, self._on_text_saved)
        dialog.present()
        
    def _on_text_saved(self, new_text):
        if new_text and new_text != self.text_content:
            self.emit("clip-edit", self.clip_id, new_text)

    def _on_qr_clicked(self, btn):
        from . import actions
        actions.show_qr_code(btn, self.text_content)

    def _on_translate_clicked(self, btn):
        from . import actions
        actions.open_google_translate(self.text_content)

    def _on_pin_clicked(self, btn):
        self.emit("clip-pin", self.clip_id)

    def _on_delete_clicked(self, btn):
        self.emit("clip-delete", self.clip_id)

    def _on_favorite_clicked(self, btn):
        self.emit("clip-favorite", self.clip_id)

    def _on_preview_clicked(self, btn):
        self.emit("clip-preview", self.clip_id)

    def _on_snippet_clicked(self, btn):
        self.emit("clip-snippet", self.clip_id)

    def update_snippet_state(self, is_snippet: bool):
        self.is_snippet = is_snippet
        if is_snippet:
            self.snip_btn.add_css_class("pinned-btn")
            self.snip_btn.set_tooltip_text(tr("item.tooltip.remove_snippets"))
        else:
            self.snip_btn.remove_css_class("pinned-btn")
            self.snip_btn.set_tooltip_text(tr("item.tooltip.to_snippets"))

    def _on_open_url(self, btn):
        url = self.metadata.get("url") or self.text_content
        if url:
            try:
                subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def _on_open_email(self, btn):
        email = self.metadata.get("email") or self.text_content
        if email:
            try:
                subprocess.Popen(["xdg-open", f"mailto:{email}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def _on_dial_phone(self, btn):
        phone = self.metadata.get("phone") or self.text_content
        if phone:
            try:
                subprocess.Popen(["xdg-open", f"tel:{phone}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def update_pin_state(self, pinned: bool):
        self.pinned = pinned
        if pinned:
            self.add_css_class("pinned")
            self.pin_btn.add_css_class("pinned-btn")
            self.pin_btn.set_tooltip_text(tr("item.tooltip.unpin"))
        else:
            self.remove_css_class("pinned")
            self.pin_btn.remove_css_class("pinned-btn")
            self.pin_btn.set_tooltip_text(tr("item.tooltip.pin"))

    def update_favorite_state(self, fav: bool):
        self.favorite = fav
        if fav:
            self.add_css_class("favorited")
            self.fav_btn.set_icon_name("starred-symbolic")
            self.fav_btn.add_css_class("favorite-btn")
        else:
            self.remove_css_class("favorited")
            self.fav_btn.set_icon_name("non-starred-symbolic")
            self.fav_btn.remove_css_class("favorite-btn")

    def _on_reveal_clicked(self, btn):
        self.masked = not self.masked
        
        # Update icon
        icon = "view-reveal-symbolic" if self.masked else "view-conceal-symbolic"
        btn.set_icon_name(icon)
        
        # Update text
        if self.category == "code":
             text = tr("item.masked") if self.masked else self.preview_text
             self.preview_label.set_use_markup(False)
             self.preview_label.set_label(text)
        else:
             text = tr("item.masked") if self.masked else self.preview_text
             self.preview_label.set_label(text)
             
        if self.masked:
            self.preview_label.add_css_class("dim-label")
        else:
            self.preview_label.remove_css_class("dim-label")
