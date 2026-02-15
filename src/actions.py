import os
import urllib.parse
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango
from .i18n import tr

try:
    import qrcode
    from qrcode.exceptions import DataOverflowError
    HAS_QR = True
except ImportError:
    qrcode = None
    DataOverflowError = Exception
    HAS_QR = False

try:
    import pytesseract
    from PIL import Image, ImageOps, ImageEnhance
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

def perform_ocr(image_path: str) -> str:
    """Extract text from image using Tesseract with preprocessing."""
    if not HAS_OCR or not image_path:
        return ""
    try:
        img = Image.open(image_path)
        
        # Preprocessing for better accuracy
        # 1. Convert to grayscale
        img = img.convert('L')
        
        # 2. Check if dark mode (inverse if necessary)
        # Calculate average pixel brightness
        stat = list(img.getdata())
        avg_brightness = sum(stat) / len(stat)
        if avg_brightness < 128:
            # Dark background, light text -> Invert
            img = ImageOps.invert(img)
            
        # 3. Increase contrast
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)
        
        # 4. Resize (upscale) if small, helps with small fonts
        if img.width < 1000:
            scale = 2
            img = img.resize((img.width * scale, img.height * scale), Image.Resampling.LANCZOS)

        # 5. Denoise/Threshold (Optional, maybe too aggressive)
        # img = img.point(lambda x: 0 if x < 140 else 255) 

        # config: --psm 6 (Assume a single uniform block of text) or 3 (Fully automatic)
        # 3 is default. 6 is good for code snippets. Let's try default first or slightly tuned.
        custom_config = r'--psm 3'
        
        text = pytesseract.image_to_string(img, lang='rus+eng', config=custom_config)
        return text.strip()
    except pytesseract.TesseractNotFoundError:
        return tr("actions.ocr_missing")
    except Exception as e:
        print(f"OCR Error: {e}")
        return tr("actions.ocr_error", error=e)

def open_google_translate(text: str):
    """Open text in Google Translate."""
    if not text:
        return
    
    # Simple language detection isn't built-in, default to auto -> auto
    encoded = urllib.parse.quote(text)
    url = f"https://translate.google.com/?sl=auto&tl=auto&text={encoded}&op=translate"
    
    # Use gtk_show_uri (GTK4 way via launch_default_for_uri is preferred but this is easier)
    # Actually, let's use Gtk.FileLauncher or similar, or just xdg-open via python for simplicity
    import subprocess
    subprocess.Popen(["xdg-open", url])

def show_qr_code(parent_widget, text: str):
    """Show a popover with QR code for the text."""
    if not HAS_QR or not text:
        return

    popover = Gtk.Popover()
    popover.set_parent(parent_widget)
    
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_css_classes(["popover-content"])
    box.set_margin_top(12)
    box.set_margin_bottom(12)
    box.set_margin_start(12)
    box.set_margin_end(12)
    
    try:
        # Generate QR
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=8,
            border=3,
        )
        qr.add_data(text)
        qr.make(fit=True)
        
        # Save to temp file to display (simplest way with GTK)
        import tempfile
        img = qr.make_image(fill_color="black", back_color="white")
        
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        img.save(path)
        
        image = Gtk.Image.new_from_file(path)
        image.set_pixel_size(200)
        box.append(image)
        
        label = Gtk.Label(label=tr("actions.qr_scan"))
        label.set_css_classes(["caption"])
        box.append(label)
        
    except Exception as e:
        text = str(e)
        if isinstance(e, DataOverflowError) or "Invalid version" in text:
            err_label = Gtk.Label(label=tr("actions.qr_too_large"))
        else:
            err_label = Gtk.Label(label=tr("actions.error", error=e))
        box.append(err_label)

    popover.set_child(box)
    popover.popup()
