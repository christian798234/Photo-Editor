"""Path helpers that behave well on Windows 11.

* Paths are always handled as ``str``/``Path`` (Unicode-safe); never passed to
  a shell.
* Long paths (> 260 chars) get the ``\\\\?\\`` prefix on Windows so they work even
  when the system-wide LongPathsEnabled policy is off.
* Export filenames are sanitised against reserved characters and device names.
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from pathlib import Path

_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def io_path(p: str | os.PathLike[str]) -> str:
    """Return a string usable with ``open()`` even for long Windows paths."""
    s = os.fspath(p)
    if sys.platform == "win32":
        s = os.path.abspath(s)
        if len(s) >= 240 and not s.startswith("\\\\?\\"):
            if s.startswith("\\\\"):
                s = "\\\\?\\UNC\\" + s[2:]
            else:
                s = "\\\\?\\" + s
    return s


def safe_stem(name: str, max_len: int = 120) -> str:
    """Turn an arbitrary file stem into a safe Windows/POSIX filename stem."""
    name = unicodedata.normalize("NFC", name)
    name = _BAD_CHARS.sub("_", name)
    name = name.strip().rstrip(". ")
    if not name:
        name = "photo"
    if name.split(".")[0].upper() in _RESERVED_NAMES:
        name = "_" + name
    if len(name) > max_len:
        name = name[:max_len].rstrip(". ")
    return name


def reserve_unique_path(folder: Path, stem: str, suffix: str) -> Path:
    """Atomically create an empty, unique file ``folder/stem{suffix}``.

    If the name exists, `` (2)``, `` (3)``... are appended. The empty file is
    created with O_EXCL so two exports can never claim the same name and an
    existing file is never overwritten.
    """
    stem = safe_stem(stem)
    for n in range(1, 10_000):
        candidate = folder / (f"{stem}{suffix}" if n == 1 else f"{stem} ({n}){suffix}")
        try:
            fd = os.open(io_path(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue
        os.close(fd)
        return candidate
    raise RuntimeError("Could not find a free filename")


def retry_on_busy(fn, attempts: int = 40, delay: float = 0.025):
    """Run ``fn`` again if Windows reports the file as busy.

    On Windows, replacing or opening a file fails with PermissionError while
    another reader has it open, or while antivirus/indexing briefly scans a
    freshly written file. These locks last milliseconds, so wait and retry.
    """
    import time
    for i in range(attempts):
        try:
            return fn()
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay * (1 + i // 8))


def replace_file(src, dst) -> None:
    """os.replace with retries for briefly locked files (Windows)."""
    retry_on_busy(lambda: os.replace(io_path(src), io_path(dst)))


def read_text(path) -> str:
    def _read():
        with open(io_path(path), "r", encoding="utf-8") as f:
            return f.read()
    return retry_on_busy(_read)


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
