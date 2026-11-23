"""Native file/folder pickers.

A browser cannot reveal the real path of a chosen file, so "Import Photos"
and "Choose folder" ask the local backend to show the standard Windows
dialog. The dialog runs in a short-lived child process (``tkinter`` ships
with the python.org installer); no shell is involved and no user-supplied
text is ever placed on the command line.

If no dialog is available (e.g. tkinter missing), the API reports it and the
web page falls back to browser upload / a typed folder path.
"""

from __future__ import annotations

import json
import subprocess
import sys

from .formats import SUPPORTED_EXTENSIONS

_SCRIPT = r"""
import json, sys
mode = sys.argv[1]
try:
    import tkinter as tk
    from tkinter import filedialog
except Exception as e:
    print(json.dumps({"error": "tkinter unavailable: %s" % e})); sys.exit(0)
try:
    root = tk.Tk()
except Exception as e:
    print(json.dumps({"error": "no display: %s" % e})); sys.exit(0)
root.withdraw()
try:
    root.attributes("-topmost", True)
except Exception:
    pass
root.update()
if mode == "files":
    pats = sys.argv[2]
    res = filedialog.askopenfilenames(parent=root, title="Import photos",
        filetypes=[("Photos (RAW, JPEG, TIFF)", pats), ("All files", "*.*")])
    out = list(res) if res else []
elif mode == "file":
    pats = sys.argv[2]
    res = filedialog.askopenfilename(parent=root, title="Locate the original file",
        filetypes=[("Photos (RAW, JPEG, TIFF)", pats), ("All files", "*.*")])
    out = [res] if res else []
else:
    res = filedialog.askdirectory(parent=root, title=sys.argv[2] if len(sys.argv) > 2 else "Choose a folder", mustexist=True)
    out = [res] if res else []
root.destroy()
sys.stdout.write(json.dumps({"paths": out}))
"""


class DialogUnavailable(Exception):
    pass


def available() -> bool:
    """Cheap check whether native dialogs can work (tkinter importable)."""
    if _window is not None or _desktop is not None:
        return True
    import importlib.util
    try:
        return importlib.util.find_spec("tkinter") is not None
    except (ImportError, ValueError):
        return False


# When the desktop control window is running, dialogs are shown by it on the
# Tk main thread instead of in a child process.
_window = None


def set_window(window) -> None:
    global _window
    _window = window


def _in_window(mode: str, arg: str) -> list[str]:
    from tkinter import filedialog

    def show(root):
        root.attributes("-topmost", True)
        try:
            if mode == "files":
                res = filedialog.askopenfilenames(parent=root, title="Import photos",
                                                  filetypes=[("Photos (RAW, JPEG, TIFF)", arg), ("All files", "*.*")])
                return list(res) if res else []
            if mode == "file":
                res = filedialog.askopenfilename(parent=root, title="Locate the original file",
                                                 filetypes=[("Photos (RAW, JPEG, TIFF)", arg), ("All files", "*.*")])
                return [res] if res else []
            res = filedialog.askdirectory(parent=root, title=arg, mustexist=True)
            return [res] if res else []
        finally:
            root.attributes("-topmost", False)

    return [p for p in _window.call(show) if isinstance(p, str) and p]


def _patterns() -> str:
    exts = sorted(SUPPORTED_EXTENSIONS)
    return " ".join(f"*{e} *{e.upper()}" for e in exts)


_desktop = None


def set_desktop(desktop) -> None:
    global _desktop
    _desktop = desktop


def _run(args: list[str], timeout: int = 900) -> list[str]:
    if _desktop is not None:
        return _desktop.choose(args[0], args[1] if len(args) > 1 else "")
    if _window is not None:
        return _in_window(args[0], args[1] if len(args) > 1 else "")
    if getattr(sys, "frozen", False):
        raise DialogUnavailable("dialogs need the app window")
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    exe = sys.executable
    if sys.platform == "win32" and exe.lower().endswith("python.exe"):
        alt = exe[:-10] + "pythonw.exe"
        import os
        if os.path.exists(alt):
            exe = alt
    try:
        proc = subprocess.run([exe, "-c", _SCRIPT, *args], capture_output=True, timeout=timeout,
                              encoding="utf-8", errors="replace", shell=False, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise DialogUnavailable(str(e)) from e
    try:
        res = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise DialogUnavailable("The file dialog could not be shown.") from None
    if "error" in res:
        raise DialogUnavailable(res["error"])
    return [p for p in res.get("paths", []) if isinstance(p, str) and p]


def choose_files() -> list[str]:
    return _run(["files", _patterns()])


def choose_file() -> list[str]:
    return _run(["file", _patterns()])


def choose_folder(title: str = "Choose a folder") -> list[str]:
    return _run(["folder", title])
