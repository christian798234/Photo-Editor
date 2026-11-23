"""Project persistence: photo records, edit recipes and caches.

Layout (inside the per-user data folder)::

    projects/default/project.json          photo order
    projects/default/photos/<id>/photo.json source reference + metadata
    projects/default/photos/<id>/recipe.json the edit recipe (nondestructive)
    projects/default/photos/<id>/facts.json  auto-analysis facts (for summary)
    cache/<id>/preview.npy                  linear ProPhoto preview (float16)
    cache/<id>/thumb.jpg, embedded.jpg      thumbnails

Originals are only ever opened for reading. Photo IDs are random hex strings,
never derived from file names or metadata, and are validated before being
used in any path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np

from .config import AppPaths
from .recipe import Recipe
from .winpath import io_path, read_text, replace_file

_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class NotFound(Exception):
    pass


def valid_id(photo_id: str) -> str:
    if not isinstance(photo_id, str) or not _ID_RE.match(photo_id):
        raise NotFound("Unknown photo")
    return photo_id


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=io_path(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        replace_file(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def fingerprint(path: Path) -> dict:
    """Cheap identity check: size + SHA-256 of the first and last MiB."""
    p = io_path(path)
    size = os.path.getsize(p)
    h = hashlib.sha256()
    with open(p, "rb") as f:
        h.update(f.read(1 << 20))
        if size > (2 << 20):
            f.seek(-(1 << 20), os.SEEK_END)
            h.update(f.read(1 << 20))
    return {"size": size, "sha256_head_tail": h.hexdigest()}


class Store:
    def __init__(self, paths: AppPaths, project: str = "default"):
        self.paths = paths.ensure()
        self.root = paths.projects / project
        self.photos_dir = self.root / "photos"
        self.photos_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._preview_cache: OrderedDict[str, tuple[np.ndarray, float]] = OrderedDict()
        # Photo records are kept in memory: the UI polls them constantly, and on
        # Windows reading a file while it is being replaced makes the write fail.
        self._records: dict[str, dict] = {}
        self._project_file = self.root / "project.json"
        if not self._project_file.exists():
            atomic_write_text(self._project_file, json.dumps({"order": []}))

    # ----------------------------------------------------------- order
    def _order(self) -> list[str]:
        try:
            return json.loads(read_text(self._project_file)).get("order", [])
        except (OSError, ValueError):
            return []

    def _set_order(self, order: list[str]) -> None:
        atomic_write_text(self._project_file, json.dumps({"order": order}))

    # ---------------------------------------------------------- records
    def photo_dir(self, photo_id: str) -> Path:
        return self.photos_dir / valid_id(photo_id)

    def cache_dir(self, photo_id: str) -> Path:
        d = self.paths.cache / valid_id(photo_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def create(self, source_path: Path, source_kind: str, original_name: str) -> dict:
        photo_id = uuid.uuid4().hex
        try:
            fp = fingerprint(source_path)
        except OSError:
            fp = {}
        rec = {
            "id": photo_id,
            "original_name": original_name,
            "source": {"path": str(source_path), "kind": source_kind, "fingerprint": fp},
            "status": "queued",
            "status_message": "Waiting to be processed",
            "decode_status": "pending",
            "decode_error": "",
            "decode_detail": "",
            "preview_kind": "none",
            "created": time.time(),
        }
        with self._lock:
            atomic_write_text(self.photo_dir(photo_id) / "photo.json", json.dumps(rec, indent=1))
            self._records[photo_id] = rec
            order = self._order()
            order.append(photo_id)
            self._set_order(order)
        return rec

    def get(self, photo_id: str) -> dict:
        p = self.photo_dir(photo_id) / "photo.json"
        with self._lock:
            cached = self._records.get(photo_id)
            if cached is not None:
                return json.loads(json.dumps(cached))       # independent copy
            try:
                rec = json.loads(read_text(p))
            except FileNotFoundError:
                raise NotFound("Unknown photo") from None
            self._records[photo_id] = rec
            return json.loads(json.dumps(rec))

    def update(self, photo_id: str, **fields: Any) -> dict:
        with self._lock:
            rec = self.get(photo_id)
            rec.update(fields)
            atomic_write_text(self.photo_dir(photo_id) / "photo.json", json.dumps(rec, indent=1))
            self._records[photo_id] = rec
            return json.loads(json.dumps(rec))

    def list(self) -> list[dict]:
        out = []
        for pid in self._order():
            try:
                out.append(self.get(pid))
            except (NotFound, ValueError):
                continue
        return out

    def remove(self, photo_id: str) -> None:
        """Remove from the project (never touches the original file)."""
        with self._lock:
            rec = self.get(photo_id)
            order = [p for p in self._order() if p != photo_id]
            self._set_order(order)
            self._records.pop(photo_id, None)
            shutil.rmtree(self.photo_dir(photo_id), ignore_errors=True)
            shutil.rmtree(self.paths.cache / photo_id, ignore_errors=True)
            self._preview_cache.pop(photo_id, None)
            src = rec.get("source", {})
            if src.get("kind") == "imported_copy":
                # Our own copy of a dragged-in file lives under imported-files.
                p = Path(src.get("path", ""))
                if p.parent.parent == self.paths.imports:
                    shutil.rmtree(p.parent, ignore_errors=True)

    def source_available(self, rec: dict) -> bool:
        try:
            return os.path.isfile(io_path(rec["source"]["path"]))
        except (KeyError, OSError):
            return False

    def read_source(self, rec: dict, max_bytes: int) -> bytes:
        p = io_path(rec["source"]["path"])
        size = os.path.getsize(p)
        if size > max_bytes:
            raise ValueError("File is too large")
        with open(p, "rb") as f:
            return f.read()

    # ---------------------------------------------------------- recipes
    def get_recipe(self, photo_id: str) -> Recipe:
        p = self.photo_dir(photo_id) / "recipe.json"
        if not p.exists():
            return Recipe()
        return Recipe.model_validate_json(read_text(p))

    def put_recipe(self, photo_id: str, recipe: Recipe) -> None:
        self.get(photo_id)
        atomic_write_text(self.photo_dir(photo_id) / "recipe.json", recipe.model_dump_json(indent=1))

    def get_facts(self, photo_id: str) -> dict:
        p = self.photo_dir(photo_id) / "facts.json"
        try:
            return json.loads(read_text(p))
        except (OSError, ValueError):
            return {}

    def put_facts(self, photo_id: str, facts: dict) -> None:
        atomic_write_text(self.photo_dir(photo_id) / "facts.json", json.dumps(facts))

    # ---------------------------------------------------------- previews
    def save_preview(self, photo_id: str, img: np.ndarray, scale: float) -> None:
        d = self.cache_dir(photo_id)
        tmp = d / ".preview.tmp.npy"
        np.save(io_path(tmp), img.astype(np.float16))
        replace_file(tmp, d / "preview.npy")
        atomic_write_text(d / "preview.json", json.dumps({"scale": scale, "shape": list(img.shape)}))
        with self._lock:
            self._preview_cache[photo_id] = (img.astype(np.float32), scale)
            self._trim_cache()

    def load_preview(self, photo_id: str) -> tuple[np.ndarray, float] | None:
        with self._lock:
            if photo_id in self._preview_cache:
                self._preview_cache.move_to_end(photo_id)
                return self._preview_cache[photo_id]
        d = self.paths.cache / valid_id(photo_id)
        try:
            img = np.load(io_path(d / "preview.npy")).astype(np.float32)
            scale = json.loads(read_text(d / "preview.json"))["scale"]
        except (OSError, ValueError, KeyError):
            return None
        with self._lock:
            self._preview_cache[photo_id] = (img, scale)
            self._trim_cache()
        return img, scale

    def _trim_cache(self, keep: int = 4) -> None:
        while len(self._preview_cache) > keep:
            self._preview_cache.popitem(last=False)

    def image_file(self, photo_id: str, name: str) -> Path | None:
        if name not in ("thumb.jpg", "embedded.jpg"):
            return None
        p = self.paths.cache / valid_id(photo_id) / name
        return p if p.exists() else None
