#!/usr/bin/env python3
"""
ClipKeeper — Modern Clipboard Manager for Linux.
Entry point.
"""

import sys
import os
import argparse

# Add the parent directory to path so we can import the src package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _send_remote_action(action: str) -> bool:
    """Send action to a running instance over D-Bus.

    org.gtk.Actions.Activate expects signature (sava{sv}):
      s   — action name
      av  — array of variants (parameters)
      a{sv} — platform data dict
    """
    import shutil
    import subprocess

    # Prefer gdbus which handles GVariant types natively
    if shutil.which("gdbus"):
        try:
            result = subprocess.run(
                [
                    "gdbus", "call",
                    "--session",
                    "--dest", "com.clipkeeper.app",
                    "--object-path", "/com/clipkeeper/app",
                    "--method", "org.gtk.Actions.Activate",
                    action, "[]", "{}",
                ],
                capture_output=True,
                timeout=3,
            )
            return result.returncode == 0
        except Exception:
            pass

    # Fallback to dbus-send (may not be available)
    if shutil.which("dbus-send"):
        try:
            result = subprocess.run(
                [
                    "dbus-send",
                    "--session",
                    "--type=method_call",
                    "--dest=com.clipkeeper.app",
                    "/com/clipkeeper/app",
                    "org.gtk.Actions.Activate",
                    f"string:{action}",
                    "array:string:",
                    "dict:string:string:",
                ],
                capture_output=True,
                timeout=3,
            )
            return result.returncode == 0
        except Exception:
            pass

    return False


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--quit", action="store_true")
    parser.add_argument("--toggle", action="store_true")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--set-hotkey", metavar="KEY")
    args, remaining = parser.parse_known_args(sys.argv[1:])
    argv = [sys.argv[0], *remaining]

    if args.set_hotkey is not None:
        from src.hotkeys import apply_system_hotkey, display_hotkey

        ok, result = apply_system_hotkey(args.set_hotkey)
        if ok:
            print(f"[ClipKeeper] Hotkey set: {display_hotkey(result)}")
            return 0
        print(f"[ClipKeeper] Hotkey setup failed: {result}", flush=True)
        return 1

    if args.quit or args.toggle or args.show:
        action = "quit"
        if args.toggle or args.show:
            action = "toggle" if args.toggle else "show"

        if _send_remote_action(action):
            print(f"[ClipKeeper] {action.capitalize()} signal sent")
            return 0

        if args.quit:
            print("[ClipKeeper] Running instance not found")
            return 0

        print("[ClipKeeper] Running instance not found, starting new one...", flush=True)

    from src.application import ClipKeeperApp

    print("[ClipKeeper] Starting...", flush=True)
    app = ClipKeeperApp(daemon_mode=args.daemon)
    return app.run(argv)


if __name__ == "__main__":
    sys.exit(main())
