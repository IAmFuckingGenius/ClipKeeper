"""
ClipKeeper — Clipboard Monitor.
Watches the system clipboard for changes using GDK4.
Stores new clips with auto-detected content types.

On GNOME Wayland the GDK "changed" signal is unreliable (fires only once
or not at all for rapid copies), so we use fast polling (every 500 ms) as
the primary detection mechanism.  The GDK signal is still connected as an
optimistic fast-path for the cases where it does fire.
"""

import base64
import binascii
import os
import queue
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
    _WL_IMAGE_MIME = "image/png"

    # Polling interval in milliseconds.
    # 500 ms is a good balance between responsiveness and CPU usage.
    _POLL_INTERVAL_MS = 100

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.last_hash: str | None = None
        self._paused = False
        self._poll_source_id: int | None = None
        self._wl_image_watch_process = None
        self._wl_image_watch_active = False
        self._state_lock = threading.Lock()
        self._image_queue: queue.Queue = queue.Queue(maxsize=128)
        self._image_worker_stop = threading.Event()
        self._image_worker_thread = threading.Thread(
            target=self._image_worker_loop, daemon=True
        )
        self._image_worker_thread.start()

        display = Gdk.Display.get_default()
        if display is None:
            print("[ClipKeeper] Warning: No display available")
            return

        self.clipboard = display.get_clipboard()

        # GDK signal — optimistic fast-path (unreliable on GNOME Wayland)
        self.clipboard.connect("changed", self._on_clipboard_changed)

        # Wayland fast image snapshots to avoid losing rapid screenshots.
        self._start_wl_image_watcher()

        # Fast polling — primary detection mechanism
        self._poll_source_id = GLib.timeout_add(self._POLL_INTERVAL_MS, self._poll_clipboard)

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

    def _on_clipboard_changed(self, clipboard):
        """Called when clipboard content changes (GDK signal)."""
        if self._paused:
            return
        self._read_clipboard()

    def _poll_clipboard(self) -> bool:
        """Fast polling — primary clipboard detection on GNOME Wayland."""
        if not self._paused:
            self._read_clipboard()
        return True  # keep the timer alive

    def _read_clipboard(self):
        """Read the current clipboard content."""
        if self._paused:
            return

        try:
            formats = self.clipboard.get_formats()

            if self._clipboard_has_image(formats):
                self.clipboard.read_texture_async(None, self._on_texture_read)
            elif formats.contain_gtype(GObject.TYPE_STRING):
                self.clipboard.read_text_async(None, self._on_text_read)
        except Exception as e:
            print(f"[ClipKeeper] Error reading clipboard: {e}")

    def _start_wl_image_watcher(self):
        """Capture each image clipboard event as its own snapshot (Wayland)."""
        if not os.environ.get("WAYLAND_DISPLAY"):
            return

        try:
            result = subprocess.run(["which", "wl-paste"], capture_output=True, timeout=2)
            if result.returncode != 0:
                return
        except Exception:
            return

        def _watch_thread():
            try:
                self._wl_image_watch_process = subprocess.Popen(
                    [
                        "wl-paste",
                        "--watch",
                        "--type",
                        self._WL_IMAGE_MIME,
                        "sh",
                        "-c",
                        "base64 -w0; echo",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
                self._wl_image_watch_active = True

                for line in self._wl_image_watch_process.stdout:
                    if self._paused:
                        continue
                    encoded = line.strip()
                    if not encoded:
                        continue
                    try:
                        data = base64.b64decode(encoded)
                    except (binascii.Error, ValueError):
                        continue
                    GLib.idle_add(self._process_wl_image_snapshot, data)
            except Exception as e:
                print(f"[ClipKeeper] wl image watcher error: {e}")
            finally:
                self._wl_image_watch_active = False

        thread = threading.Thread(target=_watch_thread, daemon=True)
        thread.start()

    def _process_wl_image_snapshot(self, image_data: bytes) -> bool:
        """Process one image snapshot captured by wl-paste watcher."""
        if self._paused or not image_data:
            return False

        if self.is_incognito:
            with self._state_lock:
                self.last_hash = compute_hash(image_data)
            return False

        self._queue_image_snapshot(image_data)
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

    def _on_text_read(self, clipboard, result):
        """Handle text clipboard content."""
        try:
            text = clipboard.read_text_finish(result)
            self._process_text_content(text)
        except Exception as e:
            print(f"[ClipKeeper] Error reading text: {e}")

    def _on_texture_read(self, clipboard, result):
        """Handle image clipboard content."""
        try:
            texture = clipboard.read_texture_finish(result)
            if texture:
                png_bytes = texture.save_to_png_bytes()
                image_data = png_bytes.get_data()

                if image_data:
                    if self.is_incognito:
                        with self._state_lock:
                            self.last_hash = compute_hash(image_data)
                        return

                    self._queue_image_snapshot(
                        image_data,
                        width=texture.get_width(),
                        height=texture.get_height(),
                    )
        except Exception as e:
            print(f"[ClipKeeper] Error reading texture: {e}")

    def _process_text_content(self, text: str | None) -> bool:
        """Process text clipboard payload and store it as a clip if needed."""
        if self._paused or not text:
            return False

        text = text.strip()
        if not text:
            return False

        # Some screenshot tools copy file paths/URIs instead of raw image mime.
        image_ref_path = self._extract_image_file_path(text)
        if image_ref_path:
            self._handle_image_file_reference(image_ref_path)
            return False

        # Process with script if configured
        script_path = self.db.get_setting("script_path")
        if script_path and os.path.exists(script_path):
            try:
                cmd = [script_path]
                if not os.access(script_path, os.X_OK):
                    if script_path.endswith(".py"):
                        cmd = ["python3", script_path]
                    elif script_path.endswith(".sh"):
                        cmd = ["bash", script_path]

                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                processed, _ = proc.communicate(input=text, timeout=1.0)
                if proc.returncode == 0 and processed:
                    text = processed.strip()
            except (subprocess.TimeoutExpired, Exception) as e:
                print(f"[ClipKeeper] Script error: {e}")

        if self.is_incognito:
            with self._state_lock:
                self.last_hash = compute_hash(text)
            return False

        content_hash = compute_hash(text)
        if not self._mark_hash_if_new(content_hash):
            return False

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

            if category == "url" and metadata.get("url"):
                fetch_url_title_async(
                    metadata["url"],
                    lambda url, title: self._on_url_title_fetched(clip_id, title),
                )

        return False

    def _store_image_clip(self, image_data: bytes, width: int | None = None, height: int | None = None):
        content_hash = compute_hash(image_data)

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
            with self._state_lock:
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

        self._queue_image_snapshot(image_data, width=width, height=height)
        return True

    def _mark_hash_if_new(self, content_hash: str) -> bool:
        """Returns True if hash is new and becomes current last_hash."""
        with self._state_lock:
            if content_hash == self.last_hash:
                return False
            self.last_hash = content_hash
            return True

    def _queue_image_snapshot(self, image_data: bytes, width: int | None = None, height: int | None = None):
        """Queue image snapshot for background processing to avoid UI loop stalls."""
        content_hash = compute_hash(image_data)
        if not self._mark_hash_if_new(content_hash):
            return

        try:
            self._image_queue.put_nowait((image_data, width, height))
        except queue.Full:
            # Drop oldest snapshot and enqueue the newest one.
            try:
                self._image_queue.get_nowait()
                self._image_queue.task_done()
            except queue.Empty:
                pass
            try:
                self._image_queue.put_nowait((image_data, width, height))
            except queue.Full:
                pass

    def _image_worker_loop(self):
        while not self._image_worker_stop.is_set():
            try:
                item = self._image_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if item is None:
                self._image_queue.task_done()
                break

            image_data, width, height = item
            try:
                clip_id = self._store_image_clip(image_data, width=width, height=height)
                if clip_id is not None:
                    GLib.idle_add(self._emit_new_clip, clip_id)
            except Exception as e:
                print(f"[ClipKeeper] Error processing image snapshot: {e}")
            finally:
                self._image_queue.task_done()

    def _emit_new_clip(self, clip_id: int) -> bool:
        self.emit("new-clip", clip_id)
        return False

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
            self.emit("new-clip", clip_id)

    def stop(self):
        """Stop monitoring."""
        if self._poll_source_id:
            try:
                GLib.source_remove(self._poll_source_id)
            except Exception:
                pass
            self._poll_source_id = None

        if self._wl_image_watch_process:
            try:
                self._wl_image_watch_process.terminate()
            except Exception:
                pass
            self._wl_image_watch_process = None

        self._image_worker_stop.set()
        try:
            self._image_queue.put_nowait(None)
        except queue.Full:
            pass
