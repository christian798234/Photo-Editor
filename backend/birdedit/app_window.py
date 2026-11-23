"""Small desktop control window (used by the installed Windows app).

Shows that Bird Photo Editor is running, with "Open in browser" and "Quit".
Closing the window stops the local server. It also hosts the native
file/folder dialogs on the Tk main thread (a windowed .exe has no console).
"""

from __future__ import annotations

import queue
import threading
import webbrowser
from typing import Callable


class ControlWindow:
    def __init__(self, url: str, on_quit: Callable[[], None], log_file: str):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.url = url
        self.on_quit = on_quit
        self._calls: queue.Queue = queue.Queue()
        self.root = tk.Tk()
        self.root.title("Bird Photo Editor")
        self.root.resizable(False, False)
        try:
            self.root.iconbitmap(default="")
        except Exception:
            pass
        frm = ttk.Frame(self.root, padding=16)
        frm.grid()
        ttk.Label(frm, text="Bird Photo Editor is running", font=("Segoe UI", 12, "bold")).grid(column=0, row=0, columnspan=2, sticky="w")
        ttk.Label(frm, text="Your photos open in your web browser. Everything stays on this computer.\n"
                            "Keep this window open while you work. Closing it quits the app.",
                  justify="left").grid(column=0, row=1, columnspan=2, sticky="w", pady=(6, 10))
        ttk.Label(frm, text=url, foreground="#2f6fe0").grid(column=0, row=2, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Button(frm, text="Open in browser", command=self.open_browser).grid(column=0, row=3, sticky="w")
        ttk.Button(frm, text="Quit", command=self.quit).grid(column=1, row=3, sticky="e")
        ttk.Label(frm, text=f"Log: {log_file}", foreground="#777").grid(column=0, row=4, columnspan=2, sticky="w", pady=(10, 0))
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.after(100, self._pump)

    def open_browser(self) -> None:
        webbrowser.open(self.url)

    def quit(self) -> None:
        try:
            self.on_quit()
        finally:
            self.root.destroy()

    # Run a function on the Tk thread and wait for its result (for dialogs).
    def call(self, fn: Callable, timeout: float = 900):
        done = threading.Event()
        box: dict = {}

        def run():
            try:
                box["value"] = fn(self.root)
            except Exception as e:  # report to the caller
                box["error"] = e
            finally:
                done.set()

        self._calls.put(run)
        if not done.wait(timeout):
            raise TimeoutError("dialog timed out")
        if "error" in box:
            raise box["error"]
        return box["value"]

    def _pump(self) -> None:
        try:
            while True:
                self._calls.get_nowait()()
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    def run(self) -> None:
        self.root.mainloop()
