"""
ClipKeeper — Utility functions.
Hashing, time formatting, text truncation, image handling, syntax highlighting.
"""

import hashlib
import io
import os
import re
import time
import subprocess
import threading
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

from .i18n import tr


IMAGES_DIR = os.path.expanduser("~/.local/share/clipkeeper/images")


def compute_hash(data: bytes | str) -> str:
    """Compute SHA-256 hash of data."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def format_time_ago(timestamp: any) -> str:
    """Format a timestamp as a human-readable relative time string."""
    try:
        if timestamp is None:
            return tr("time.unknown")
        # Handle string timestamps if any (fallback)
        if isinstance(timestamp, str):
            # If it's something like "2026-02-15 16:30:00", we should parse it or ignore
            # For now, let's try to convert simple digit strings
            if timestamp.isdigit():
                timestamp = float(timestamp)
            else:
                # If migration missed some strings, we might have a problem.
                # Let's return a safe value.
                return tr("time.earlier")
        
        diff = time.time() - float(timestamp)
        if diff < 5:
            return tr("time.now")
        elif diff < 60:
            return tr("time.seconds_ago", count=int(diff))
        elif diff < 3600:
            m = int(diff / 60)
            return tr("time.minutes_ago", count=m)
        elif diff < 86400:
            h = int(diff / 3600)
            return tr("time.hours_ago", count=h)
        else:
            d = int(diff / 86400)
            if d == 1:
                return tr("time.yesterday")
            elif d < 30:
                return tr("time.days_ago", count=d)
            elif d < 365:
                months = d // 30
                return tr("time.months_ago", count=months)
            else:
                years = d // 365
                return tr("time.years_ago", count=years)
    except (ValueError, TypeError, Exception):
        return tr("time.some_time_ago")


def truncate_text(text: str, max_len: int = 120) -> str:
    """Truncate text, collapse whitespace, add ellipsis."""
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1] + "…"


# --- Image Handling ---

def save_image_to_file(
    image_data: bytes,
    content_hash: str,
    max_size: Optional[int] = None,
    quality: Optional[int] = None,
) -> tuple[str, str]:
    """Save image to filesystem. Returns (image_path, thumb_path)."""
    os.makedirs(IMAGES_DIR, exist_ok=True)

    image_path = os.path.join(IMAGES_DIR, f"{content_hash}.png")
    thumb_path = os.path.join(IMAGES_DIR, f"{content_hash}_thumb.png")

    processed_data = bytes(image_data)

    # Apply optional image settings (downscale + PNG compression).
    try:
        from PIL import Image

        max_dim = int(max_size) if max_size is not None else 2048
        quality_val = int(quality) if quality is not None else 85
        quality_val = max(1, min(100, quality_val))

        img = Image.open(io.BytesIO(processed_data))
        if max_dim > 0 and max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        compress_level = max(0, min(9, round((100 - quality_val) * 9 / 99)))
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True, compress_level=compress_level)
        processed_data = out.getvalue()
    except Exception:
        pass

    # Save original
    with open(image_path, "wb") as f:
        f.write(processed_data)

    # Generate thumbnail
    try:
        pixbuf = _load_pixbuf_from_bytes(processed_data)
        if pixbuf:
            thumb = _scale_pixbuf(pixbuf, 128)
            if thumb:
                thumb.savev(thumb_path, "png", [], [])
    except Exception as e:
        print(f"[ClipKeeper] Thumbnail generation error: {e}")
        thumb_path = image_path  # Fallback to original

    return image_path, thumb_path


def load_texture_from_path(path: str) -> Optional[Gdk.Texture]:
    """Load a Gdk.Texture from a file path."""
    if not path or not os.path.exists(path):
        return None
    try:
        return Gdk.Texture.new_from_filename(path)
    except Exception:
        return None


def load_pixbuf_from_path(path: str, size: int = 48) -> Optional[GdkPixbuf.Pixbuf]:
    """Load and scale a GdkPixbuf from file path."""
    if not path or not os.path.exists(path):
        return None
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        return _scale_pixbuf(pixbuf, size)
    except Exception:
        return None


def _load_pixbuf_from_bytes(data: bytes) -> Optional[GdkPixbuf.Pixbuf]:
    """Load a GdkPixbuf from raw bytes."""
    try:
        loader = GdkPixbuf.PixbufLoader()
        loader.write(data)
        loader.close()
        return loader.get_pixbuf()
    except Exception:
        return None


def _scale_pixbuf(pixbuf: GdkPixbuf.Pixbuf, size: int) -> Optional[GdkPixbuf.Pixbuf]:
    """Scale pixbuf preserving aspect ratio."""
    w, h = pixbuf.get_width(), pixbuf.get_height()
    if w > h:
        new_w, new_h = size, max(1, int(h * size / w))
    else:
        new_h, new_w = size, max(1, int(w * size / h))
    return pixbuf.scale_simple(new_w, new_h, GdkPixbuf.InterpType.BILINEAR)


# --- Syntax Highlighting ---

# Token colors for Pango markup (works in both light and dark themes)
SYNTAX_COLORS = {
    "keyword": "#c061cb",    # Purple
    "string": "#33d17a",     # Green
    "comment": "#9a9996",    # Gray
    "number": "#ff7800",     # Orange
    "function": "#62a0ea",   # Blue
    "type": "#f9f06b",       # Yellow
    "operator": "#c0bfbc",   # Light gray
}

SYNTAX_RULES = [
    ("comment", re.compile(r"(#[^\n]*|//[^\n]*|/\*.*?\*/)", re.DOTALL)),
    ("string", re.compile(r'(\"\"\".*?\"\"\"|\'\'\'.*?\'\'\'|\"(?:\\.|[^\"])*\"|\'(?:\\.|[^\'])*\')', re.DOTALL)),
    ("keyword", re.compile(
        r"\b(def|class|import|from|return|if|elif|else|for|while|try|except|finally|"
        r"with|as|in|not|and|or|is|None|True|False|self|yield|async|await|"
        r"function|const|let|var|export|default|new|this|typeof|instanceof|"
        r"fn|pub|mut|impl|struct|enum|match|use|mod|crate|"
        r"func|package|defer|go|chan|select|interface|"
        r"SELECT|FROM|WHERE|INSERT|UPDATE|DELETE|CREATE|TABLE|INTO|VALUES|"
        r"void|int|float|double|char|bool|string|null|undefined)\b"
    )),
    ("number", re.compile(r"\b(\d+\.?\d*(?:e[+-]?\d+)?|0x[0-9a-fA-F]+)\b")),
    ("function", re.compile(r"\b([a-zA-Z_]\w*)\s*\(")),
]


def highlight_code(text: str, max_len: int = 300) -> str:
    """Apply Pango markup syntax highlighting to code text."""
    if len(text) > max_len:
        text = text[:max_len] + "…"

    # Escape XML special chars first
    text = GLib.markup_escape_text(text)

    # Apply syntax rules (simple, non-overlapping)
    for token_type, pattern in SYNTAX_RULES:
        color = SYNTAX_COLORS.get(token_type, "#ffffff")
        text = pattern.sub(
            rf'<span foreground="{color}">\1</span>', text
        )

    return text


# --- URL Fetching ---

def fetch_url_title_async(url: str, callback):
    """Fetch page title from URL in a background thread."""
    def _fetch():
        title = _fetch_url_title(url)
        GLib.idle_add(callback, url, title)

    thread = threading.Thread(target=_fetch, daemon=True)
    thread.start()


def _fetch_url_title(url: str) -> Optional[str]:
    """Fetch page title from URL using curl."""
    try:
        result = subprocess.run(
            ["curl", "-sL", "--max-time", "5", "--max-filesize", "100000", url],
            capture_output=True, text=True, timeout=6,
        )
        if result.returncode == 0:
            match = re.search(r"<title[^>]*>([^<]+)</title>", result.stdout, re.IGNORECASE)
            if match:
                return match.group(1).strip()[:100]
    except Exception:
        pass
    return None


# --- Category Icons ---

CATEGORY_EMOJI = {
    "text": "",
    "url": "",
    "email": "",
    "phone": "",
    "code": "",
    "color": "",
    "image": "",
}


def get_category_emoji(category: str) -> str:
    return CATEGORY_EMOJI.get(category, "")
