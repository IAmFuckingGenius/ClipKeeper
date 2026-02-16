"""
ClipKeeper — Clipboard Monitor.
Watches the system clipboard for changes using GDK4 + wl-paste fallback.
Stores new clips with auto-detected content types.
"""

import os
import subprocess
import threading
import urllib.parse

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, GObject

from .content_detector import ContentDetector
from .database import Database
from .i18n import tr
from .utils import compute_hash, save_image_to_file, truncate_text, fetch_url_title_async


class ClipboardMonitor(GObject.GObject):
    """Monitors the system clipboard and stores new entries."""

    __gsignals__ = {
        "new-clip": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }
    _IMAGE_MIME_TYPES = (
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
        "image/bmp",
        "image/tiff",
        "image/gif",
    )
    _IMAGE_EXTENSIONS = (
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".bmp",
        ".tif",
        ".tiff",
        ".gif",
    )

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.last_hash: str | None = None
        self._reading = False
        self._pending_read = False
        self._paused = False
        self._wl_paste_process = None

        display = Gdk.Display.get_default()
        if display is None:
            print("[ClipKeeper] Warning: No display available")
            return

        self.clipboard = display.get_clipboard()
        self.clipboard.connect("changed", self._on_clipboard_changed)

        # Start wl-paste watcher for reliable Wayland monitoring
        self._start_wl_paste_watcher()

        # Periodic polling as final fallback
        GLib.timeout_add_seconds(3, self._poll_clipboard)

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool):
        self._paused = value
        
    @property
    def is_incognito(self) -> bool:
        return getattr(self, "_is_incognito", False)

    @is_incognito.setter
    def is_incognito(self, value: bool):
        self._is_incognito = value

    def _start_wl_paste_watcher(self):
        """Start wl-paste --watch for Wayland clipboard monitoring."""
        # Check if wl-paste is available
        try:
            result = subprocess.run(
                ["which", "wl-paste"], capture_output=True, timeout=2
            )
            if result.returncode != 0:
                return
        except Exception:
            return

        def _watch_thread():
            try:
                # wl-paste --watch triggers whenever clipboard changes
                self._wl_paste_process = subprocess.Popen(
                    ["wl-paste", "--watch", "echo", "CLIPBOARD_CHANGED"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                for line in self._wl_paste_process.stdout:
                    if "CLIPBOARD_CHANGED" in line and not self._paused:
                        # Schedule clipboard read on the main thread
                        GLib.idle_add(self._read_clipboard)
            except Exception as e:
                print(f"[ClipKeeper] wl-paste watcher error: {e}")

        thread = threading.Thread(target=_watch_thread, daemon=True)
        thread.start()

    def _on_clipboard_changed(self, clipboard):
        """Called when clipboard content changes (GDK signal)."""
        if self._paused:
            return
        if self._reading:
            self._pending_read = True
            return
        GLib.timeout_add(150, self._read_clipboard)

    def _poll_clipboard(self) -> bool:
        """Periodic polling fallback."""
        if self._paused:
            return True
        if self._reading:
            self._pending_read = True
        else:
            self._read_clipboard()
        return True

    def _read_clipboard(self) -> bool:
        """Read the current clipboard content."""
        if self._paused:
            return False
        if self._reading:
            self._pending_read = True
            return False
        self._reading = True
        self._pending_read = False

        try:
            formats = self.clipboard.get_formats()

            # Image first
            if self._clipboard_has_image(formats):
                self.clipboard.read_texture_async(None, self._on_texture_read)
            elif formats.contain_gtype(GObject.TYPE_STRING):
                self.clipboard.read_text_async(None, self._on_text_read)
            else:
                self._finish_read()
        except Exception as e:
            print(f"[ClipKeeper] Error reading clipboard: {e}")
            self._finish_read()

        return False

    def _clipboard_has_image(self, formats) -> bool:
        try:
            if formats.contain_gtype(Gdk.Texture.__gtype__):
                return True
        except Exception:
            pass

        for mime in self._IMAGE_MIME_TYPES:
            try:
                if formats.contain_mime_type(mime):
                    return True
            except Exception:
                continue
        return False

    def _finish_read(self):
        self._reading = False
        if self._paused:
            self._pending_read = False
            return
        if self._pending_read:
            self._pending_read = False
            GLib.idle_add(self._read_clipboard)

    def _on_text_read(self, clipboard, result):
        """Handle text clipboard content."""
        try:
            text = clipboard.read_text_finish(result)
            if text and text.strip():
                text = text.strip()

                # Some screenshot tools copy file paths/URIs instead of raw image mime.
                # Handle those references as image clips.
                image_ref_path = self._extract_image_file_path(text)
                if image_ref_path:
                    if self._handle_image_file_reference(image_ref_path):
                        return

                # Process with script if configured
                script_path = self.db.get_setting("script_path")
                if script_path and os.path.exists(script_path):
                    try:
                        # Ensure executable or run with interpreter? 
                        # We'll assume executable or try basic run
                        cmd = [script_path]
                        if not os.access(script_path, os.X_OK):
                            # Try to make it executable or warn?
                            # Or if ends with .py use python, .sh use bash
                            if script_path.endswith(".py"):
                                cmd = ["python3", script_path]
                            elif script_path.endswith(".sh"):
                                cmd = ["bash", script_path]
                        
                        proc = subprocess.Popen(
                            cmd, 
                            stdin=subprocess.PIPE, 
                            stdout=subprocess.PIPE, 
                            stderr=subprocess.DEVNULL,
                            text=True
                        )
                        processed, _ = proc.communicate(input=text, timeout=1.0)
                        if proc.returncode == 0 and processed:
                            text = processed.strip()
                    except (subprocess.TimeoutExpired, Exception) as e:
                        print(f"[ClipKeeper] Script error: {e}")

                if self.is_incognito:
                     # Skip saving, but maybe update last hash to avoid re-triggering?
                     self.last_hash = compute_hash(text)
                     return

                content_hash = compute_hash(text)

                if content_hash != self.last_hash:
                    self.last_hash = content_hash

                    # Auto-detect content type
                    category, subtype, metadata, is_sensitive = ContentDetector.detect(text)
                    preview = truncate_text(text, 120)

                    clip_id = self.db.add_clip(
                        content_type="text",
                        content_hash=content_hash,
                        preview=preview,
                        category=category,
                        content_subtype=subtype,
                        text_content=text,
                        metadata=metadata,
                        is_sensitive=is_sensitive,
                    )

                    if clip_id is not None:
                        self.emit("new-clip", clip_id)

                        # Fetch URL title asynchronously if it's a URL
                        if category == "url" and metadata.get("url"):
                            fetch_url_title_async(
                                metadata["url"],
                                lambda url, title: self._on_url_title_fetched(clip_id, title)
                            )
        except Exception as e:
            print(f"[ClipKeeper] Error reading text: {e}")
        finally:
            self._finish_read()

    def _on_texture_read(self, clipboard, result):
        """Handle image clipboard content."""
        try:
            texture = clipboard.read_texture_finish(result)
            if texture:
                png_bytes = texture.save_to_png_bytes()
                image_data = png_bytes.get_data()

                if image_data:
                    if self.is_incognito:
                        self.last_hash = compute_hash(image_data)
                        return

                    clip_id = self._store_image_clip(
                        image_data,
                        width=texture.get_width(),
                        height=texture.get_height(),
                    )
                    if clip_id is not None:
                        self.emit("new-clip", clip_id)
        except Exception as e:
            print(f"[ClipKeeper] Error reading texture: {e}")
        finally:
            self._finish_read()

    def _store_image_clip(self, image_data: bytes, width: int | None = None, height: int | None = None):
        content_hash = compute_hash(image_data)
        if content_hash == self.last_hash:
            return None
        self.last_hash = content_hash

        max_image_size = 2048
        image_quality = 85
        try:
            max_image_size = int(self.db.get_setting("max_image_size", "2048"))
        except (TypeError, ValueError):
            max_image_size = 2048
        try:
            image_quality = int(self.db.get_setting("image_quality", "85"))
        except (TypeError, ValueError):
            image_quality = 85

        image_path, thumb_path = save_image_to_file(
            image_data,
            content_hash,
            max_size=max_image_size,
            quality=image_quality,
        )

        if width and height:
            preview = "🖼 " + tr("monitor.image_preview", width=width, height=height)
        else:
            preview = "🖼 " + tr("monitor.image_preview_generic")

        return self.db.add_clip(
            content_type="image",
            content_hash=content_hash,
            preview=preview,
            category="image",
            image_path=image_path,
            thumb_path=thumb_path,
            image_width=width,
            image_height=height,
        )

    def _handle_image_file_reference(self, path: str) -> bool:
        try:
            with open(path, "rb") as f:
                image_data = f.read()
        except OSError:
            return False

        if not image_data:
            return False

        if self.is_incognito:
            self.last_hash = compute_hash(image_data)
            return True

        width = None
        height = None
        try:
            texture = Gdk.Texture.new_from_filename(path)
            width = texture.get_width()
            height = texture.get_height()
        except Exception:
            pass

        clip_id = self._store_image_clip(image_data, width=width, height=height)
        if clip_id is not None:
            self.emit("new-clip", clip_id)
        return True

    def _extract_image_file_path(self, text: str) -> str | None:
        for raw_line in text.splitlines():
            candidate = raw_line.strip().strip("\x00")
            if not candidate:
                continue

            path = None
            if candidate.startswith("file://"):
                parsed = urllib.parse.urlparse(candidate)
                path = urllib.parse.unquote(parsed.path)
            elif candidate.startswith("/") or candidate.startswith("~"):
                path = os.path.expanduser(candidate)

            if not path:
                continue

            if os.path.isfile(path) and path.lower().endswith(self._IMAGE_EXTENSIONS):
                return path

        return None

    def _on_url_title_fetched(self, clip_id: int, title: str | None):
        """Update clip metadata with fetched URL title."""
        if title:
            self.db.update_metadata(clip_id, {"page_title": title})
            self.emit("new-clip", clip_id)  # Trigger UI refresh

    def stop(self):
        """Stop monitoring."""
        if self._wl_paste_process:
            try:
                self._wl_paste_process.terminate()
            except Exception:
                pass
