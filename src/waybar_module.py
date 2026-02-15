#!/usr/bin/env python3
"""
ClipKeeper — Waybar custom module.
Outputs JSON for waybar's custom module protocol.
Shows clip count and provides click actions.

Waybar config example (add to ~/.config/waybar/config):

"custom/clipboard": {
    "exec": "python3 /home/fkgen/testbo/v1/src/waybar_module.py",
    "return-type": "json",
    "interval": 5,
    "on-click": "bash /home/fkgen/testbo/v1/run.sh",
    "on-click-right": "bash /home/fkgen/testbo/v1/run.sh --quit",
    "tooltip": true
}

Also add "custom/clipboard" to your modules-right (or modules-left/center).
"""

import json
import os
import sqlite3
import sys

try:
    from .i18n import set_locale, tr
except ImportError:
    from i18n import set_locale, tr


DB_PATH = os.path.expanduser("~/.local/share/clipkeeper/history.db")


def get_stats():
    """Read stats directly from the database."""
    if not os.path.exists(DB_PATH):
        return {"total": 0, "pinned": 0, "images": 0}

    try:
        conn = sqlite3.connect(DB_PATH, timeout=1)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) as c FROM clips").fetchone()["c"]
        pinned = conn.execute(
            "SELECT COUNT(*) as c FROM clips WHERE pinned = 1"
        ).fetchone()["c"]
        images = conn.execute(
            "SELECT COUNT(*) as c FROM clips WHERE content_type = 'image'"
        ).fetchone()["c"]
        lang_row = conn.execute(
            "SELECT value FROM settings WHERE key = 'language'"
        ).fetchone()
        conn.close()
        return {
            "total": total,
            "pinned": pinned,
            "images": images,
            "language": lang_row["value"] if lang_row else "system",
        }
    except Exception:
        return {"total": 0, "pinned": 0, "images": 0, "language": "system"}


def main():
    stats = get_stats()
    set_locale(stats.get("language", "system"))
    total = stats["total"]

    # Icon and text
    if total == 0:
        text = "󰅍"  # nerd font clipboard empty
    else:
        text = f"󰅍 {total}"

    # Tooltip
    parts = [tr("waybar.tooltip.header", total=total)]
    if stats["pinned"]:
        parts.append("📌 " + tr("waybar.tooltip.pinned", count=stats["pinned"]))
    if stats["images"]:
        parts.append("🖼 " + tr("waybar.tooltip.images", count=stats["images"]))
    parts.append("")
    parts.append(tr("waybar.tooltip.left_click"))
    parts.append(tr("waybar.tooltip.right_click"))
    tooltip = "\n".join(parts)

    # CSS class based on state
    css_class = "has-clips" if total > 0 else "empty"

    output = {
        "text": text,
        "tooltip": tooltip,
        "class": css_class,
        "alt": "clipboard",
    }

    print(json.dumps(output))


if __name__ == "__main__":
    main()
