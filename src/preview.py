"""
ClipKeeper — Preview Popover.
Large preview for images and text/code content.
"""

import json

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from .utils import highlight_code, load_texture_from_path
from .i18n import tr


class PreviewPopover(Gtk.Window):
    """Large preview overlay for clipboard items."""

    def __init__(self, app, clip_data):
        super().__init__(
            title=tr("preview.title"),
            default_width=600,
            default_height=500,
            resizable=True,
            css_classes=["preview-window"],
        )
        self.clip_data = clip_data
        self._build_ui()
        self._setup_shortcuts()

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(main_box)

        # Header
        header = Adw.HeaderBar(css_classes=["flat"])
        header.set_title_widget(
            Gtk.Label(label=tr("preview.title"), css_classes=["title"])
        )

        # Copy button
        copy_btn = Gtk.Button(
            icon_name="edit-copy-symbolic",
            tooltip_text=tr("preview.copy"),
            css_classes=["flat"],
        )
        copy_btn.connect("clicked", self._on_copy)
        header.pack_end(copy_btn)

        # OCR Button (for images)
        if self.clip_data["content_type"] == "image":
            from . import actions
            if actions.HAS_OCR:
                ocr_btn = Gtk.Button(
                    icon_name="document-page-setup-symbolic", # distinct icon
                    tooltip_text=tr("preview.ocr"),
                    css_classes=["flat"],
                )
                ocr_btn.set_icon_name("view-paged-symbolic") # standard icon
                ocr_btn.set_icon_name("view-paged-symbolic") # standard icon
                ocr_btn.connect("clicked", self._on_ocr)
                header.pack_end(ocr_btn)

            # Edit/Open button
            edit_btn = Gtk.Button(
                icon_name="document-edit-symbolic",
                tooltip_text=tr("preview.edit_image"),
                css_classes=["flat"],
            )
            edit_btn.connect("clicked", self._on_edit_image)
            header.pack_end(edit_btn)

        main_box.append(header)

        # Content area
        content_type = self.clip_data["content_type"]
        category = self.clip_data.get("category", "text")

        if content_type == "image":
            self._build_image_preview(main_box)
        elif category == "code":
            self._build_code_preview(main_box)
        else:
            self._build_text_preview(main_box)

        # Metadata bar
        self._build_metadata_bar(main_box)

    def _build_image_preview(self, parent):
        """Full-size image preview with scroll."""
        scrolled = Gtk.ScrolledWindow(
            vexpand=True,
            hexpand=True,
        )

        image_path = self.clip_data.get("image_path") or self.clip_data.get("thumb_path")
        texture = load_texture_from_path(image_path)

        if texture:
            picture = Gtk.Picture(
                paintable=texture,
                content_fit=Gtk.ContentFit.CONTAIN,
                can_shrink=True,
                margin_start=12,
                margin_end=12,
                margin_top=12,
                margin_bottom=12,
            )
            scrolled.set_child(picture)
        else:
            label = Gtk.Label(
                label=tr("preview.image_not_found"),
                css_classes=["dim-label", "title-3"],
                vexpand=True,
            )
            scrolled.set_child(label)

        parent.append(scrolled)

    def _build_code_preview(self, parent):
        """Code preview with syntax highlighting."""
        scrolled = Gtk.ScrolledWindow(
            vexpand=True,
            margin_start=12,
            margin_end=12,
            margin_top=8,
            margin_bottom=8,
        )

        text = self.clip_data.get("text_content", "")
        highlighted = highlight_code(text, max_len=10000)

        label = Gtk.Label(
            use_markup=True,
            label=highlighted,
            wrap=True,
            selectable=True,
            xalign=0,
            yalign=0,
            css_classes=["preview-code", "monospace"],
            margin_start=16,
            margin_end=16,
            margin_top=12,
            margin_bottom=12,
        )
        scrolled.set_child(label)

        frame = Gtk.Frame(css_classes=["preview-code-frame"])
        frame.set_child(scrolled)
        parent.append(frame)

    def _build_text_preview(self, parent):
        """Full text preview."""
        scrolled = Gtk.ScrolledWindow(
            vexpand=True,
            margin_start=12,
            margin_end=12,
            margin_top=8,
            margin_bottom=8,
        )

        text = self.clip_data.get("text_content", "")
        label = Gtk.Label(
            label=text,
            wrap=True,
            selectable=True,
            xalign=0,
            yalign=0,
            css_classes=["preview-text"],
            margin_start=16,
            margin_end=16,
            margin_top=12,
            margin_bottom=12,
        )
        scrolled.set_child(label)
        parent.append(scrolled)

    def _build_metadata_bar(self, parent):
        """Show metadata at the bottom."""
        parent.append(Gtk.Separator(css_classes=["spacer"]))

        bar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=16,
            margin_start=16,
            margin_end=16,
            margin_top=8,
            margin_bottom=8,
        )

        # Type info
        category = self.clip_data.get("category", "text")
        from .content_detector import ContentDetector
        type_label = Gtk.Label(
            label=ContentDetector.get_category_label(category),
            css_classes=["dim-label", "caption"],
        )
        bar.append(type_label)

        # Size info
        text_content = self.clip_data.get("text_content")
        if text_content:
            size = len(text_content)
            if size < 1024:
                size_str = tr("preview.text_chars", count=size)
            else:
                size_str = tr("preview.text_kb", size=size / 1024)
            bar.append(Gtk.Label(label=size_str, css_classes=["dim-label", "caption"]))

        if self.clip_data.get("image_width"):
            bar.append(Gtk.Label(
                label=f"{self.clip_data['image_width']}×{self.clip_data['image_height']}",
                css_classes=["dim-label", "caption"],
            ))

        # Metadata
        meta_json = self.clip_data.get("metadata_json")
        if meta_json:
            try:
                meta = json.loads(meta_json)
                if meta.get("page_title"):
                    bar.append(Gtk.Label(
                        label=meta["page_title"][:40],
                        css_classes=["dim-label", "caption"],
                        ellipsize=3,
                        hexpand=True,
                        halign=Gtk.Align.END,
                    ))
                if meta.get("language"):
                    bar.append(Gtk.Label(
                        label=meta["language"],
                        css_classes=["dim-label", "caption", "monospace"],
                    ))
            except (json.JSONDecodeError, TypeError):
                pass

        parent.append(bar)

    def _on_copy(self, btn):
        """Copy content back to clipboard."""
        display = Gdk.Display.get_default()
        clipboard = display.get_clipboard()

        if self.clip_data["content_type"] == "text":
            from gi.repository import GObject
            content = Gdk.ContentProvider.new_for_value(
                GObject.Value(GObject.TYPE_STRING, self.clip_data["text_content"])
            )
            clipboard.set_content(content)
        elif self.clip_data["content_type"] == "image":
            image_path = self.clip_data.get("image_path")
            texture = load_texture_from_path(image_path)
            if texture:
                from gi.repository import GObject
                content = Gdk.ContentProvider.new_for_value(
                    GObject.Value(Gdk.Texture.__gtype__, texture)
                )
                clipboard.set_content(content)

        self.close()

    def _setup_shortcuts(self):
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key)
        self.add_controller(controller)

    def _on_key(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _on_ocr(self, btn):
        """Perform OCR and show text."""
        image_path = self.clip_data.get("image_path")
        if not image_path:
            return
        
        # Show loading?
        from . import actions
        text = actions.perform_ocr(image_path)
        
        if text:
            # Show in edit dialog
            from .edit_dialog import EditDialog
            dialog = EditDialog(self, text, self._on_ocr_save)
            dialog.present()
        else:
            # Show error toast? Or just label
            # For now just print or ignore
            pass

    def _on_ocr_save(self, text):
        # User saved the text from OCR.
        # Maybe copy to clipboard? 
        if text:
             display = Gdk.Display.get_default()
             clipboard = display.get_clipboard()
             from gi.repository import GObject
             clipboard.set_content(
                 Gdk.ContentProvider.new_for_value(
                     GObject.Value(GObject.TYPE_STRING, text)
                 )
             )
             self.close()

    def _on_edit_image(self, btn):
        """Open internal image editor."""
        image_path = self.clip_data.get("image_path")
        if not image_path:
            return
            
        from .image_editor import ImageEditor
        editor = ImageEditor(self, image_path, self._on_image_saved)
        editor.present()

    def _on_image_saved(self):
        """Reload preview after editing."""
        # Reload texture
        image_path = self.clip_data.get("image_path")
        if image_path:
            texture = load_texture_from_path(image_path)
            if texture:
                # Find the scrolled window child and replace picture
                # This is a bit hacky, better to rebuild part of ui or access widget directly
                # simplified: just close and reopen? or simpler: close.
                # User will likely want to see the result.
                
                # Let's try to find picture widget.
                # Access methods are limited.
                # Closing preview is safe fall back to force refresh from main list
                # But main list also needs refresh.
                pass
                
        # Emit signal to main window to refresh this item?
        # Actually, if we just close, the file is updated. 
        # But main window thumbnail still points to old file or cache.
        # We need to notify app.
        
        self.close()
        
        # We need to tell the parent (ClipKeeperWindow) to refresh the list or at least this item.
        # But PreviewPopover takes 'app' in init.
        # Let's see self.transient_for
        # The app should have a mechanism.
        # For now, closing is enough, user can reopen. Thumbnail might be stale though.
