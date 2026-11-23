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

import json
import logging
import sys
import threading
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


def file_types(patterns: str) -> tuple[str, ...]:
    """Build pywebview file filters. pywebview only accepts a label made of
    letters, digits and spaces, followed by (*.ext;*.ext). Windows matches
    extensions case-insensitively, so lower-case patterns are enough."""
    exts = sorted({p.lower() for p in patterns.split() if p.startswith("*.")})
    candidates = [f"Photos ({';'.join(exts)})", "All files (*.*)"]
    try:
        from webview.util import parse_file_type
    except Exception:                 # pywebview not installed (tests on Linux)
        return tuple(candidates)
    valid = []
    for c in candidates:
        try:
            parse_file_type(c)
            valid.append(c)
        except ValueError:
            log.warning("skipping invalid file filter %r", c)
    return tuple(valid)


# ------------------------------------------------------------- geometry

DEFAULT_SIZE = (1440, 920)
MIN_SIZE = (640, 480)          # small enough to snap to half (or a quarter) of a screen


def choose_geometry(saved: dict | None, screens: list) -> dict | None:
    """Validate a saved window rectangle against the connected screens.

    Returns {x, y, width, height, maximized} to restore, or None to let the
    window open centred on the main screen (e.g. the monitor it was on has
    been unplugged). ``screens`` items need x, y, width, height attributes.
    """
    if not saved or not screens:
        return None
    try:
        x, y = int(saved["x"]), int(saved["y"])
        w, h = int(saved["width"]), int(saved["height"])
    except (KeyError, TypeError, ValueError):
        return None
    best = None
    for sc in screens:
        ix = min(x + w, sc.x + sc.width) - max(x, sc.x)
        iy = min(y + h, sc.y + sc.height) - max(y, sc.y)
        # The title bar area must be visible on this screen.
        if ix >= 160 and iy >= 80 and sc.y <= y + 10 < sc.y + sc.height:
            best = sc
            break
    if best is None:
        return None
    w = max(MIN_SIZE[0], min(w, best.width))
    h = max(MIN_SIZE[1], min(h, best.height))
    x = min(max(x, best.x), best.x + best.width - w)
    y = min(max(y, best.y), best.y + best.height - h)
    return {"x": x, "y": y, "width": w, "height": h, "maximized": bool(saved.get("maximized"))}


def screen_of(screens: list, cx: float, cy: float):
    for sc in screens:
        if sc.x <= cx < sc.x + sc.width and sc.y <= cy < sc.y + sc.height:
            return sc
    return screens[0] if screens else None


class DesktopWindow:
    def __init__(self, url: str, on_closed: Callable[[], None], storage: Path,
                 import_paths: Callable[[list[str]], dict] | None = None, icon: str | None = None):
        import webview

        self.webview = webview
        self.on_closed = on_closed
        self.import_paths = import_paths
        self.storage = storage
        self.icon = icon
        self.url = url
        self.second = None
        self._lock = threading.Lock()
        self._geom_file = storage.parent / "window.json"
        saved = None
        try:
            saved = json.loads(self._geom_file.read_text("utf-8"))
        except (OSError, ValueError):
            pass
        try:
            screens = list(webview.screens)
        except Exception:
            screens = []
        geom = choose_geometry(saved, screens)
        self._geom = dict(geom or {"x": None, "y": None, "width": DEFAULT_SIZE[0],
                                   "height": DEFAULT_SIZE[1], "maximized": False})
        log.info("screens: %s; restoring window %s",
                 [(s.x, s.y, s.width, s.height, getattr(s, "scale", 1.0)) for s in screens], geom)
        self.window = webview.create_window(
            "Bird Photo Editor", url, width=self._geom["width"], height=self._geom["height"],
            x=self._geom["x"], y=self._geom["y"], maximized=self._geom["maximized"],
            min_size=MIN_SIZE, background_color="#1b1c1f", text_select=True)
        ev = self.window.events
        ev.closed += self._closed
        ev.closing += self._save_geometry
        ev.loaded += self._loaded
        ev.moved += self._moved
        ev.resized += self._resized
        ev.maximized += lambda *a: self._geom.update(maximized=True)
        ev.restored += lambda *a: self._geom.update(maximized=False)

    # -------------------------------------------------------------- events
    def _moved(self, *args) -> None:
        if len(args) >= 2 and not self._geom.get("maximized"):
            self._geom.update(x=int(args[0]), y=int(args[1]))
        self._save_soon()

    def _resized(self, *args) -> None:
        if len(args) >= 2 and not self._geom.get("maximized"):
            self._geom.update(width=int(args[0]), height=int(args[1]))
        self._save_soon()

    def _save_soon(self) -> None:
        """Also save shortly after moving/resizing, not only on close."""
        t = getattr(self, "_save_timer", None)
        if t is not None:
            t.cancel()
        self._save_timer = threading.Timer(1.5, self._write_geometry)
        self._save_timer.daemon = True
        self._save_timer.start()

    def _write_geometry(self) -> None:
        try:
            if self._geom.get("x") is not None:
                self._geom_file.write_text(json.dumps(self._geom), "utf-8")
        except OSError:
            log.debug("could not save window position", exc_info=True)

    def _save_geometry(self, *args) -> None:
        try:
            if not self._geom.get("maximized"):
                self._geom.update(x=self.window.x, y=self.window.y,
                                  width=self.window.width, height=self.window.height)
            self._write_geometry()
        except Exception:
            log.debug("could not save window position", exc_info=True)

    def _closed(self) -> None:
        log.info("desktop window closed")
        second = self.second
        if second is not None:
            try:
                second.destroy()
            except Exception:
                pass
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

    def close(self) -> None:
        """Close the window (and so the app), e.g. when a newer version starts."""
        try:
            self._save_geometry()
            self.window.destroy()
        except Exception:
            log.exception("closing the window failed")
            self.on_closed()

    def bring_to_front(self) -> None:
        """Called when the program is started again while already open."""
        try:
            self.window.restore()
            self.window.show()
            self.window.on_top = True
            self.window.on_top = False
        except Exception:
            log.debug("bring to front failed", exc_info=True)

    # --------------------------------------------------------- second screen
    def screens_info(self) -> dict:
        try:
            screens = list(self.webview.screens)
        except Exception:
            screens = []
        return {"count": len(screens), "second_open": self.second is not None}

    def open_second_screen(self) -> dict:
        """Open (or bring forward) a large preview window, on another monitor
        when one is connected."""
        with self._lock:
            if self.second is not None:
                try:
                    self.second.restore()
                    self.second.show()
                    return {"ok": True, "other_monitor": None, "already_open": True}
                except Exception:
                    self.second = None
            try:
                screens = list(self.webview.screens)
            except Exception:
                screens = []
            target, other = None, False
            if screens:
                try:
                    cx = self.window.x + self.window.width / 2
                    cy = self.window.y + self.window.height / 2
                    current = screen_of(screens, cx, cy)
                except Exception:
                    current = screens[0]
                others = [s for s in screens if s is not current]
                target = others[0] if others else current
                other = bool(others)
            kwargs = {"maximized": True} if other else {"width": 1200, "height": 800}
            if target is not None:
                kwargs["screen"] = target
            win = self.webview.create_window(
                "Bird Photo Editor - Second screen", self.url.rstrip("/") + "/?view=second",
                background_color="#000000", min_size=(320, 240), **kwargs)

            def gone(*a):
                self.second = None

            win.events.closed += gone
            win.events.loaded += lambda *a: log.info("second-screen window loaded")
            self.second = win
            log.info("second-screen window opened (other monitor: %s)", other)
            return {"ok": True, "other_monitor": other, "already_open": False}

    # ------------------------------------------------------------- dialogs
    def choose(self, mode: str, arg: str) -> list[str]:
        wv = self.webview
        types = file_types(arg)
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
