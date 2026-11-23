"""Where the application keeps its settings, project data and caches.

Everything lives in a per-user writable location so no administrator rights
are needed:

* Windows: ``%LOCALAPPDATA%\\BirdPhotoEditor``
* other systems: ``$XDG_DATA_HOME/bird-photo-editor`` or ``~/.local/share/...``

``BIRDEDIT_DATA_DIR`` overrides the location (used by tests).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_DIR_NAME_WINDOWS = "BirdPhotoEditor"
APP_DIR_NAME_POSIX = "bird-photo-editor"


def default_data_dir() -> Path:
    override = os.environ.get("BIRDEDIT_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_DIR_NAME_WINDOWS
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME_POSIX


@dataclass(frozen=True)
class AppPaths:
    root: Path

    @property
    def projects(self) -> Path:
        return self.root / "projects"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def imports(self) -> Path:
        """Copies of files that were dragged into the browser (no path known)."""
        return self.root / "imported-files"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def settings_file(self) -> Path:
        return self.root / "settings.json"

    def ensure(self) -> "AppPaths":
        for p in (self.root, self.projects, self.cache, self.imports, self.logs):
            p.mkdir(parents=True, exist_ok=True)
        return self


# Processing limits (conservative defaults; see README "Performance").
PREVIEW_MAX_EDGE = 2048          # long edge of the cached editing preview
THUMB_MAX_EDGE = 320
MAX_INPUT_BYTES = 1024 * 1024 * 1024   # refuse files larger than 1 GiB
MAX_PIXELS = 250_000_000               # refuse images above 250 MP
FULL_RES_WORKERS = 1                   # simultaneous full-resolution jobs
IMPORT_WORKERS = 1                     # simultaneous half-size RAW decodes
TILE = 1024                            # export tile size (pixels)
TILE_PAD = 128                         # overlap so local filters have context
