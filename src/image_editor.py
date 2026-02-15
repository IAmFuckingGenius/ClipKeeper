import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf

from PIL import Image, ImageFilter, ImageDraw
import os

from .i18n import tr

class ImageEditor(Gtk.Window):
    """
    Simple Image Editor for Cropping and Blurring.
    """
    def __init__(self, parent, image_path, on_save_callback):
        super().__init__(modal=True, transient_for=parent)
        self.set_title(tr("image_editor.title"))
        self.set_default_size(800, 600)
        
        self.image_path = image_path
        self.on_save_callback = on_save_callback
        
        # Load image with PIL
        try:
            self.pil_image = Image.open(self.image_path)
            # Ensure we work with RGB/RGBA
            if self.pil_image.mode not in ("RGB", "RGBA"):
                self.pil_image = self.pil_image.convert("RGB")
        except Exception as e:
            print(f"Error loading image: {e}")
            self.destroy()
            return

        self.original_image = self.pil_image.copy() # For reset
        
        # Selection state
        self.selection_start = None # (x, y)
        self.selection_end = None   # (x, y)
        self.is_dragging = False
        
        self.surface_width = 0
        self.surface_height = 0
        self.display_scale = 1.0
        self.offset_x = 0
        self.offset_y = 0

        self._build_ui()

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(main_box)
        
        # Header
        header = Gtk.HeaderBar()
        self.set_titlebar(header)
        
        cancel_btn = Gtk.Button(label=tr("common.cancel"))
        cancel_btn.connect("clicked", lambda x: self.destroy())
        header.pack_start(cancel_btn)
        
        save_btn = Gtk.Button(label=tr("common.save"), css_classes=["suggested-action"])
        save_btn.connect("clicked", self._on_save)
        header.pack_end(save_btn)
        
        # Toolbar
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        toolbar.set_css_classes(["toolbar"])
        toolbar.set_margin_top(6)
        toolbar.set_margin_bottom(6)
        toolbar.set_margin_start(6)
        toolbar.set_margin_end(6)
        main_box.append(toolbar)
        
        self.btn_crop = Gtk.Button(label=tr("image_editor.crop"), icon_name="crop-symbolic")
        self.btn_crop.set_tooltip_text(tr("image_editor.crop_tip"))
        self.btn_crop.connect("clicked", self._on_crop)
        self.btn_crop.set_sensitive(False)
        toolbar.append(self.btn_crop)
        
        self.btn_blur = Gtk.Button(label=tr("image_editor.blur"), icon_name="blur-symbolic") # standard icon? maybe 'droplet-symbolic' or text
        self.btn_blur.set_tooltip_text(tr("image_editor.blur_tip"))
        self.btn_blur.connect("clicked", self._on_blur)
        self.btn_blur.set_sensitive(False)
        toolbar.append(self.btn_blur)
        
        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        
        reset_btn = Gtk.Button(label=tr("image_editor.reset"), icon_name="edit-undo-symbolic")
        reset_btn.connect("clicked", self._on_reset)
        toolbar.append(reset_btn)

        # Canvas Area
        self.scrolled = Gtk.ScrolledWindow()
        self.scrolled.set_vexpand(True)
        self.scrolled.set_hexpand(True)
        main_box.append(self.scrolled)
        
        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.set_draw_func(self._on_draw)
        
        # Event controller for mouse
        gesture = Gtk.GestureDrag()
        gesture.set_button(1) # Left click
        gesture.connect("drag-begin", self._on_drag_begin)
        gesture.connect("drag-update", self._on_drag_update)
        gesture.connect("drag-end", self._on_drag_end)
        self.drawing_area.add_controller(gesture)
        
        click_gesture = Gtk.GestureClick()
        click_gesture.connect("released", self._on_click_released)
        self.drawing_area.add_controller(click_gesture)

        self.scrolled.set_child(self.drawing_area)

    def _update_layout(self, width, height):
        # Calculate scaling to fit image in window (initially)
        # But here we probably want 1:1 or fit width?
        # Let's do 'contain' logic for display
        if width <= 0 or height <= 0: return
        
        img_w, img_h = self.pil_image.size
        
        scale_x = width / img_w
        scale_y = height / img_h
        self.display_scale = min(scale_x, scale_y, 1.0) # Downscale only, don't upscale
        
        # Center image
        self.surface_width = int(img_w * self.display_scale)
        self.surface_height = int(img_h * self.display_scale)
        
        self.offset_x = (width - self.surface_width) // 2
        self.offset_y = (height - self.surface_height) // 2
        
        self.drawing_area.queue_draw()

    def _on_draw(self, area, cr, width, height):
        # Background
        cr.set_source_rgb(0.2, 0.2, 0.2)
        cr.paint()
        
        if not self.pil_image:
            return

        # 1. Update layout metrics
        img_w, img_h = self.pil_image.size
        
        # Compute exact fit scale
        scale_x = width / img_w
        scale_y = height / img_h
        self.display_scale = min(scale_x, scale_y) * 0.95 # Leave some margin
        
        self.surface_width = int(img_w * self.display_scale)
        self.surface_height = int(img_h * self.display_scale)
        self.offset_x = (width - self.surface_width) / 2
        self.offset_y = (height - self.surface_height) / 2
        
        # 2. Convert PIL to GdkPixbuf (efficiently?)
        # For now, converting repeatedly in draw loop is bad, but it works for prototype.
        # Ensure RGB
        if self.pil_image.mode != "RGB":
             data = self.pil_image.convert("RGB").tobytes()
             n_channels = 3
             has_alpha = False
        else:
             data = self.pil_image.tobytes()
             n_channels = 3
             has_alpha = False
             
        # Create pixbuf
        stride = self.pil_image.width * n_channels
        pixbuf = GdkPixbuf.Pixbuf.new_from_data(
            data,
            GdkPixbuf.Colorspace.RGB,
            has_alpha,
            8,
            self.pil_image.width,
            self.pil_image.height,
            stride
        )
        
        # 3. Draw Image
        cr.save()
        cr.translate(self.offset_x, self.offset_y)
        cr.scale(self.display_scale, self.display_scale)
        
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
        cr.paint()
        cr.restore()
        
        # 4. Draw Selection Rect
        if self.selection_start and self.selection_end:
            x1, y1 = self.selection_start
            x2, y2 = self.selection_end
            
            # Map screen coords
            rx = min(x1, x2)
            ry = min(y1, y2)
            rw = abs(x1 - x2)
            rh = abs(y1 - y2)
            
            cr.set_source_rgba(1, 1, 1, 0.3)
            cr.rectangle(rx, ry, rw, rh)
            cr.fill_preserve()
            
            cr.set_source_rgba(1, 1, 1, 0.8)
            cr.set_line_width(2)
            cr.stroke()

    def _get_selection_rect_image_coords(self):
        """Convert screen selection to image coordinates."""
        if not self.selection_start or not self.selection_end:
            return None
            
        x1, y1 = self.selection_start
        x2, y2 = self.selection_end
        
        sx1 = (min(x1, x2) - self.offset_x) / self.display_scale
        sy1 = (min(y1, y2) - self.offset_y) / self.display_scale
        sx2 = (max(x1, x2) - self.offset_x) / self.display_scale
        sy2 = (max(y1, y2) - self.offset_y) / self.display_scale
        
        # Clamp
        w, h = self.pil_image.size
        sx1 = max(0, min(sx1, w))
        sy1 = max(0, min(sy1, h))
        sx2 = max(0, min(sx2, w))
        sy2 = max(0, min(sy2, h))
        
        return (int(sx1), int(sy1), int(sx2), int(sy2))

    def _on_drag_begin(self, gesture, x, y):
        self.is_dragging = True
        self.selection_start = (x, y)
        self.selection_end = (x, y)
        self.drawing_area.queue_draw()

    def _on_drag_update(self, gesture, offset_x, offset_y):
        if self.is_dragging and self.selection_start:
            start_x, start_y = self.selection_start
            self.selection_end = (start_x + offset_x, start_y + offset_y)
            self.drawing_area.queue_draw()

    def _on_drag_end(self, gesture, offset_x, offset_y):
        self.is_dragging = False
        if self.selection_start:
            start_x, start_y = self.selection_start
            self.selection_end = (start_x + offset_x, start_y + offset_y)
            
            # Check if selection is large enough
            coords = self._get_selection_rect_image_coords()
            if coords:
                x1, y1, x2, y2 = coords
                if abs(x2 - x1) > 5 and abs(y2 - y1) > 5:
                    self.btn_crop.set_sensitive(True)
                    self.btn_blur.set_sensitive(True)
                else:
                    self.btn_crop.set_sensitive(False)
                    self.btn_blur.set_sensitive(False)
                    
            self.drawing_area.queue_draw()

    def _on_click_released(self, gesture, n_press, x, y):
        # Clear selection on simple click
        if not self.is_dragging:
             self.selection_start = None
             self.selection_end = None
             self.btn_crop.set_sensitive(False)
             self.btn_blur.set_sensitive(False)
             self.drawing_area.queue_draw()

    def _on_crop(self, btn):
        coords = self._get_selection_rect_image_coords()
        if not coords: return
        
        x1, y1, x2, y2 = coords
        if abs(x2 - x1) < 5 or abs(y2 - y1) < 5: return
        
        self.pil_image = self.pil_image.crop((x1, y1, x2, y2))
        
        # Clear selection
        self.selection_start = None
        self.selection_end = None
        self.btn_crop.set_sensitive(False)
        self.btn_blur.set_sensitive(False)
        self.drawing_area.queue_draw()

    def _on_blur(self, btn):
        coords = self._get_selection_rect_image_coords()
        if not coords: return
        
        x1, y1, x2, y2 = coords
        if abs(x2 - x1) < 5 or abs(y2 - y1) < 5: return
        
        # Crop region, blur it, paste back
        region = self.pil_image.crop((x1, y1, x2, y2))
        # Apply heavy gaussian blur
        blurred = region.filter(ImageFilter.GaussianBlur(radius=15))
        self.pil_image.paste(blurred, (x1, y1))
        
        # Clear selection
        self.selection_start = None
        self.selection_end = None
        self.btn_crop.set_sensitive(False)
        self.btn_blur.set_sensitive(False)
        self.drawing_area.queue_draw()

    def _on_reset(self, btn):
        self.pil_image = self.original_image.copy()
        self.selection_start = None
        self.selection_end = None
        self.btn_crop.set_sensitive(False)
        self.btn_blur.set_sensitive(False)
        self.drawing_area.queue_draw()

    def _on_save(self, btn):
        # Save to file
        try:
            self.pil_image.save(self.image_path)
            if self.on_save_callback:
                self.on_save_callback()
            self.close()
        except Exception as e:
            print(f"Error saving image: {e}")
