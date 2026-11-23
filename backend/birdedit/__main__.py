"""Start Bird Photo Editor:  ``python -m birdedit``

* Binds to 127.0.0.1 only.
* Uses port 8765, or the next free port up to 8784. If an instance of this
  app is already running on one of those ports, it just opens the browser.
* Opens the default browser once the server answers.
* On failure, writes the log file and (on Windows) shows a message box.
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

from .config import AppPaths, default_data_dir

PORT_RANGE = range(8765, 8785)


def message_box(title: str, text: str) -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
            return
        except Exception:
            pass
    print(f"\n{title}\n{text}\n", file=sys.stderr)


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if sys.platform != "win32":
            # Match uvicorn: a socket in TIME_WAIT does not block a POSIX bind.
            # (On Windows SO_REUSEADDR would allow port hijacking; not used.)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def instance_version(port: int) -> str | None:
    """Version of a Bird Photo Editor running on ``port``, or None."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as r:
            d = json.loads(r.read().decode())
            return str(d.get("version", "")) if d.get("app") == "bird-photo-editor" else None
    except Exception:
        return None


def existing_instance(port: int) -> bool:
    return instance_version(port) is not None


def ask_old_instance_to_quit(port: int) -> bool:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/quit", data=b"", method="POST")
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        return False
    for _ in range(40):
        time.sleep(0.25)
        if port_is_free(port):
            return True
    return False


def pick_port(requested: int | None) -> tuple[int, bool]:
    """Return (port, already_running)."""
    if requested:
        if port_is_free(requested):
            return requested, False
        if existing_instance(requested):
            return requested, True
        raise RuntimeError(f"Port {requested} is already used by another program. "
                           f"Close that program or start with a different --port.")
    for port in PORT_RANGE:
        if existing_instance(port):
            return port, True
    for port in PORT_RANGE:
        if port_is_free(port):
            return port, False
    raise RuntimeError(f"No free port between {PORT_RANGE.start} and {PORT_RANGE.stop - 1}. "
                       "Close other programs using these ports and try again.")


def setup_logging(paths: AppPaths) -> str:
    log_file = paths.logs / "bird-photo-editor.log"
    handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr is not None:          # None in a windowed (no console) .exe
        console = logging.StreamHandler()
        console.setLevel(logging.WARNING)
        root.addHandler(console)
    return str(log_file)


def _fix_std_streams() -> None:
    """A windowed .exe has no console: give print() somewhere harmless to go."""
    import os
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _ask_existing_to_show(port: int) -> str | None:
    """Tell a running copy to bring its window forward; returns its shell."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/show", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.loads(r.read().decode()).get("shell")
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    _fix_std_streams()
    frozen = bool(getattr(sys, "frozen", False))
    ap = argparse.ArgumentParser(prog="birdedit", description="Bird Photo Editor (local)")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--ui", choices=("desktop", "browser", "server"), default=None,
                    help="desktop: own program window (default for the installed app); "
                         "browser: open in the web browser; server: no window")
    ap.add_argument("--no-browser", action="store_true", help="browser mode: do not open a tab")
    ap.add_argument("--dev", action="store_true", help="allow the Vite dev server origin")
    ap.add_argument("--window", dest="window", action="store_true", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--no-window", dest="window", action="store_false", help=argparse.SUPPRESS)
    ap.add_argument("--token", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    ui = args.ui or ("server" if args.window is False else "desktop" if frozen else "browser")

    paths = AppPaths(default_data_dir())
    try:
        paths.ensure()
    except OSError as e:
        message_box("Bird Photo Editor", f"Cannot create the data folder:\n{paths.root}\n\n{e}")
        return 2
    log_file = setup_logging(paths)
    log = logging.getLogger("birdedit")

    try:
        port, running = pick_port(args.port)
    except RuntimeError as e:
        message_box("Bird Photo Editor could not start", str(e))
        return 3
    url = f"http://127.0.0.1:{port}/"
    if running:
        from . import __version__
        other = instance_version(port)
        if other and other != __version__:
            # A different (usually older) version is still running: replace it.
            log.info("version %s is running on port %s; asking it to quit", other, port)
            if ask_old_instance_to_quit(port):
                running = False
            else:
                message_box("Bird Photo Editor",
                            f"An older version of Bird Photo Editor ({other}) is still running.\n\n"
                            "Close its window (or restart your PC), then start Bird Photo Editor again.")
                return 0
    if running:
        shell = _ask_existing_to_show(port)
        print(f"Bird Photo Editor is already running at {url}")
        if shell != "desktop" and ui != "server" and not args.no_browser:
            webbrowser.open(url)
        return 0

    if ui == "desktop":
        from . import desktop
        ok, why = desktop.available()
        if not ok:
            log.warning("program window unavailable: %s", why)
            if frozen:
                message_box("Bird Photo Editor",
                            f"The program window could not be opened because {why}\n\n"
                            "Bird Photo Editor will open in your web browser instead.")
            ui = "browser"

    try:
        import uvicorn

        from .security import new_token
        from .server import create_app

        token = args.token or new_token()
        dev_origins = ("http://localhost:5173", "http://127.0.0.1:5173") if args.dev else ()
        app = create_app(token=token, port=port, dev_origins=dev_origins)
        app.state.shell = "desktop" if ui == "desktop" else "browser"
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                access_log=False, log_config=None)
        server = uvicorn.Server(config)
    except Exception:
        log.exception("startup failed")
        message_box("Bird Photo Editor could not start",
                    f"{traceback.format_exc(limit=3)}\n\nDetails were written to:\n{log_file}")
        return 4

    def stop() -> None:
        server.should_exit = True

    app.state.quit_app = stop               # server-only mode; replaced below for windows

    failed: list = []

    def serve() -> None:
        try:
            server.run()
        except Exception:
            log.exception("server crashed")
            failed.append(True)

    def wait_ready() -> bool:
        for _ in range(240):
            if existing_instance(port):
                return True
            if failed:
                return False
            time.sleep(0.25)
        return False

    # ------------------------------------------------ program window (default)
    if ui == "desktop":
        from . import desktop, dialogs
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        if not wait_ready():
            message_box("Bird Photo Editor could not start", f"See the log file:\n{log_file}")
            return 5
        icon = None
        if frozen:
            cand = Path(sys.executable).parent / "_internal" / "icon.ico"
            icon = str(cand) if cand.exists() else None
        win = desktop.DesktopWindow(url, stop, paths.root / "webview", app.state.import_paths, icon)
        app.state.quit_app = win.close
        dialogs.set_desktop(win)
        app.state.show_window = win.bring_to_front
        app.state.open_second_screen = win.open_second_screen
        app.state.screens_info = win.screens_info
        try:
            win.run()                      # returns when the window is closed
        except Exception:
            log.exception("program window failed")
            message_box("Bird Photo Editor", "The program window stopped unexpectedly.\n"
                        f"Details were written to:\n{log_file}")
        stop()
        t.join(timeout=10)
        return 5 if failed else 0

    # ------------------------------------------------------- browser mode
    window = None
    if ui == "browser" and frozen:
        try:
            from . import dialogs
            from .app_window import ControlWindow
            window = ControlWindow(url, stop, log_file)
            dialogs.set_window(window)
            app.state.quit_app = lambda: window.root.after(0, window.quit)
        except Exception:
            log.warning("control window unavailable; running without it", exc_info=True)
            window = None

    def open_when_ready() -> None:
        if wait_ready():
            print(f"\nBird Photo Editor is running at {url}")
            if window is None:
                print("Keep this window open while you work. Close it to quit.\n")
            if args.dev:
                print(f"Dev token: {token}")
            if ui == "browser" and not args.no_browser:
                webbrowser.open(url)
        else:
            message_box("Bird Photo Editor", f"The server did not start in time.\nSee {log_file}")

    threading.Thread(target=open_when_ready, daemon=True).start()
    if window is not None:
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        window.run()
        stop()
        t.join(timeout=10)
        return 5 if failed else 0
    serve()
    if failed:
        message_box("Bird Photo Editor stopped unexpectedly", f"See the log file:\n{log_file}")
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(main())
