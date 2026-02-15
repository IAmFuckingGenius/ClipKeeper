import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk

from .i18n import tr

class EditDialog(Gtk.Window):
    """Dialog for editing clip text."""

    def __init__(self, parent, text, on_save):
        super().__init__(transient_for=parent)
        self.set_modal(True)
        self.set_title(tr("edit.title"))
        self.set_default_size(500, 400)
        self.on_save = on_save

        # Main layout
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        self.set_child(box)

        # Text View
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        
        self.text_view = Gtk.TextView()
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.text_view.get_buffer().set_text(text)
        scrolled.set_child(self.text_view)
        box.append(scrolled)

        # Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_halign(Gtk.Align.END)
        
        cancel_btn = Gtk.Button(label=tr("common.cancel"))
        cancel_btn.connect("clicked", lambda _: self.close())
        btn_box.append(cancel_btn)
        
        save_btn = Gtk.Button(label=tr("common.save"))
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save_clicked)
        btn_box.append(save_btn)
        
        box.append(btn_box)

    def _on_save_clicked(self, btn):
        buffer = self.text_view.get_buffer()
        start, end = buffer.get_bounds()
        new_text = buffer.get_text(start, end, True).strip()
        
        if self.on_save:
            self.on_save(new_text)
        self.close()
