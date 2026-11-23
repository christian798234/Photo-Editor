"""Native program window for Bird Photo Editor.

The editor runs in its own window (Microsoft Edge WebView2 on Windows, via
pywebview) instead of a browser tab. The window loads the same local,
token-protected interface from 127.0.0.1, so all features behave exactly as
before; it just has no tabs, no address bar and its own taskbar entry.

Also provides:
* native Windows open/folder dialogs (``window.create_file_dialog``);
* drag-and-drop with real file paths, so dropped photos are *linked* in
  place rather than copied.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

WEBVIEW2_CLIENT = r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def webview2_version() -> str | None:
    """Installed WebView2 runtime version on Windows, or None."""
    if sys.platform != "win32":
        return None
    import winreg
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, WEBVIEW2_CLIENT),
                      (winreg.HKEY_CURRENT_USER, WEBVIEW2_CLIENT.replace("WOW6432Node\\", ""))):
        try:
            with winreg.OpenKey(hive, key) as k:
                v, _ = winreg.QueryValueEx(k, "pv")
                if v and v != "0.0.0.0":
                    return str(v)
        except OSError:
            continue
    return None


def available() -> tuple[bool, str]:
    """Can a native window be shown? (ok, reason-if-not)"""
    try:
        import webview  # noqa: F401
    except Exception as e:
        return False, f"pywebview not available ({e.__class__.__name__})"
    if sys.platform == "win32" and webview2_version() is None:
        return False, ("the Microsoft Edge WebView2 Runtime is not installed. Install it from "
                       "https://developer.microsoft.com/microsoft-edge/webview2/")
    return True, ""


class DesktopWindow:
    def __init__(self, url: str, on_closed: Callable[[], None], storage: Path,
                 import_paths: Callable[[list[str]], dict] | None = None, icon: str | None = None):
        import webview

        self.webview = webview
        self.on_closed = on_closed
        self.import_paths = import_paths
        self.storage = storage
        self.icon = icon
        self.window = webview.create_window(
            "Bird Photo Editor", url, width=1440, height=920, min_size=(1000, 660),
            background_color="#1b1c1f", text_select=True)
        self.window.events.closed += self._closed
        self.window.events.loaded += self._loaded

    # -------------------------------------------------------------- events
    def _closed(self) -> None:
        log.info("desktop window closed")
        try:
            self.on_closed()
        except Exception:
            log.exception("shutdown after window close failed")

    def _loaded(self) -> None:
        log.info("desktop window loaded the editor")
        if self.import_paths is None:
            return
        try:
            from webview.dom import DOMEventHandler

            def ignore(_e) -> None:
                pass

            doc = self.window.dom.document
            doc.events.dragenter += DOMEventHandler(ignore, True, True)
            doc.events.dragover += DOMEventHandler(ignore, True, True, debounce=300)
            doc.events.drop += DOMEventHandler(self._drop, True, True)
        except Exception:
            log.warning("could not enable drag-and-drop with file paths", exc_info=True)

    def _drop(self, e: dict) -> None:
        files = (e.get("dataTransfer") or {}).get("files") or []
        paths = [f.get("pywebviewFullPath") for f in files if isinstance(f, dict)]
        paths = [p for p in paths if isinstance(p, str) and p]
        if not paths:
            return                      # the page falls back to copying the files
        try:
            res = self.import_paths(paths)
            n = len(res.get("photo_ids", []))
            self.window.evaluate_js(f"window.dispatchEvent(new CustomEvent('birdedit-imported', {{detail: {n}}}))")
        except Exception:
            log.exception("drop import failed")

    def bring_to_front(self) -> None:
        """Called when the program is started again while already open."""
        try:
            self.window.restore()
            self.window.show()
            self.window.on_top = True
            self.window.on_top = False
        except Exception:
            log.debug("bring to front failed", exc_info=True)

    # ------------------------------------------------------------- dialogs
    def choose(self, mode: str, arg: str) -> list[str]:
        wv = self.webview
        types = ("Photos (RAW, JPEG, TIFF) (" + ";".join(sorted({p for p in arg.split() if p})) + ")",
                 "All files (*.*)")
        if mode == "files":
            res = self.window.create_file_dialog(wv.FileDialog.OPEN, allow_multiple=True, file_types=types)
        elif mode == "file":
            res = self.window.create_file_dialog(wv.FileDialog.OPEN, allow_multiple=False, file_types=types)
        else:
            res = self.window.create_file_dialog(wv.FileDialog.FOLDER)
        if not res:
            return []
        if isinstance(res, str):
            res = [res]
        return [str(p) for p in res if p]

    # ---------------------------------------------------------------- run
    def run(self) -> None:
        self.storage.mkdir(parents=True, exist_ok=True)
        kwargs: dict = {"debug": False, "private_mode": False, "storage_path": str(self.storage)}
        if sys.platform == "win32":
            kwargs["gui"] = "edgechromium"
        if self.icon:
            kwargs["icon"] = self.icon
        log.info("starting desktop window (%s)", kwargs.get("gui", "default backend"))
        self.webview.start(**kwargs)
