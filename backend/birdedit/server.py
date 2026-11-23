"""FastAPI application: REST API + the built web interface."""

from __future__ import annotations

import logging
import os
import platform
import sys
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from . import PIPELINE_VERSION, __version__, dialogs, masks, restraint
from .config import MAX_INPUT_BYTES, AppPaths, default_data_dir
from .export import ExportOptions, validate_folder
from .formats import SUPPORTED_EXTENSIONS
from .jobs import JobManager
from .processing import Processor, export_one
from .recipe import Recipe
from .security import LocalGuard
from .store import NotFound, Store, atomic_write_text, fingerprint, valid_id
from .winpath import io_path, safe_stem

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "web"


class RenderReq(BaseModel):
    recipe: Recipe
    before: bool = False
    max_edge: int = Field(1600, ge=64, le=4096)
    ignore_crop: bool = False


class RegionReq(BaseModel):
    recipe: Recipe
    before: bool = False
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(gt=0, le=2400)
    h: int = Field(gt=0, le=2400)


class AutoReq(BaseModel):
    look: Literal["natural", "crisp", "soft_background"] = "natural"


class AutoAllReq(BaseModel):
    photo_ids: list[str]
    look: Literal["natural", "crisp"] = "natural"


class ClickPoint(BaseModel):
    x: float = Field(ge=0, le=1)        # normalised to the uncropped image
    y: float = Field(ge=0, le=1)
    bird: bool = True                    # False = "this is not the bird"


class DetectReq(BaseModel):
    points: Optional[list[ClickPoint]] = None
    redetect: bool = False


class CropSuggestReq(BaseModel):
    aspect: Literal["original", "free", "3:2", "4:3", "1:1", "16:9"] = "original"
    portrait: bool = False


class PasteReq(BaseModel):
    photo_ids: list[str]
    look: Literal["natural", "crisp", "soft_background"]
    strength: float = Field(ge=0, le=150)
    sliders: dict


class ExportReq(BaseModel):
    photo_ids: list[str]
    folder: str
    format: Literal["jpeg", "tiff16"] = "jpeg"
    quality: int = Field(92, ge=50, le=100)
    long_edge: Optional[int] = Field(None, ge=256, le=20000)
    keep_gps: bool = False


class HistoryEntry(BaseModel):
    label: str = Field(max_length=120)
    time: float
    recipe: Recipe


class History(BaseModel):
    entries: list[HistoryEntry] = Field(max_length=200)
    index: int = Field(ge=0)


class RelocateConfirm(BaseModel):
    pending_id: str


class SettingsModel(BaseModel):
    export_folder: str = ""
    export_format: Literal["jpeg", "tiff16"] = "jpeg"
    jpeg_quality: int = Field(92, ge=50, le=100)
    long_edge: Optional[int] = Field(None, ge=256, le=20000)
    keep_gps: bool = False
    subject_detection: Optional[bool] = None    # None = not asked yet
    natural_limits: bool = True                 # "Keep edits natural" (less is more)


def create_app(token: str, port: int, data_dir: Path | None = None,
               dev_origins: tuple[str, ...] = ()) -> FastAPI:
    paths = AppPaths(data_dir or default_data_dir()).ensure()
    store = Store(paths)

    def load_settings() -> SettingsModel:
        try:
            return SettingsModel.model_validate_json(paths.settings_file.read_text("utf-8"))
        except (OSError, ValidationError, ValueError):
            return SettingsModel()

    def subject_enabled() -> bool:
        return bool(load_settings().subject_detection) and masks.status()["installed"]

    def limited(recipe: Recipe) -> Recipe:
        return restraint.apply_limits(recipe) if load_settings().natural_limits else recipe

    proc = Processor(store, subject_enabled, limited)
    jobs = JobManager()
    @asynccontextmanager
    async def lifespan(_app):
        yield
        jobs.shutdown()

    app = FastAPI(title="Bird Photo Editor", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.add_middleware(LocalGuard, port=port, token=token, extra_origins=dev_origins)
    app.state.store, app.state.proc, app.state.jobs = store, proc, jobs
    app.state.shell = "browser"          # "desktop" when shown in the program window
    pending_relocations: dict[str, tuple[str, str]] = {}
    export_folders: set[str] = set()

    def _photo_view(rec: dict) -> dict:
        recipe = store.get_recipe(rec["id"])
        out = dict(rec)
        out["source_available"] = store.source_available(rec)
        out["recipe"] = recipe.model_dump()
        out["summary"] = proc.summary(rec["id"], recipe) if recipe.auto_applied or recipe != Recipe() else ""
        out["edit_level"] = restraint.edit_level(recipe)
        out.pop("noise_model", None)
        info, m = proc.mask(rec["id"])
        out["mask"] = None if info is None else {
            "status": info.get("status"), "message": info.get("message"), "accepted": bool(info.get("accepted")),
            "usable": m is not None and (info.get("status") == "good" or bool(info.get("accepted"))),
            "has_mask": m is not None, "birds": len([b for b in info.get("birds", []) if b.get("quality", {}).get("ok")]),
            "detection": info.get("detection"), "seconds": info.get("seconds"),
            "points": info.get("points", []), "source": info.get("source"), "shape": info.get("shape")}
        return out

    def _get(photo_id: str) -> dict:
        try:
            return store.get(valid_id(photo_id))
        except NotFound:
            raise HTTPException(404, "Photo not found") from None

    def _start_import(ids: list[str]) -> dict:
        job = jobs.submit("import", f"Importing {len(ids)} photo(s)", ids, proc.import_one, pool="import")
        return job.to_dict()

    # ------------------------------------------------------------ basics
    @app.get("/api/health")
    def health():
        return {"app": "bird-photo-editor", "version": __version__}

    @app.post("/api/show")
    def show():
        """A second launch asks the running copy to bring its window forward."""
        fn = getattr(app.state, "show_window", None)
        if fn is not None:
            threading.Thread(target=fn, daemon=True).start()
        return {"shell": app.state.shell}

    @app.get("/api/system")
    def system():
        import rawpy
        return {
            "version": __version__, "pipeline_version": PIPELINE_VERSION,
            "python": sys.version.split()[0], "platform": platform.platform(),
            "rawpy": rawpy.__version__, "libraw": ".".join(map(str, rawpy.libraw_version)),
            "processing": "CPU", "gpu_acceleration": "Not implemented (CPU-only processing)",
            "cpu_count": os.cpu_count(), "data_dir": str(paths.root),
            "subject_masks": "installed" if masks.status()["installed"] else "not installed",
            "native_dialogs": dialogs.available(),
            "shell": app.state.shell,
        }

    # ------------------------------------------------------------- photos
    @app.get("/api/photos")
    def list_photos():
        return [_photo_view(r) for r in store.list()]

    @app.get("/api/photos/{photo_id}")
    def get_photo(photo_id: str):
        return _photo_view(_get(photo_id))

    @app.delete("/api/photos/{photo_id}")
    def remove_photo(photo_id: str):
        _get(photo_id)
        store.remove(photo_id)
        proc.full.clear(photo_id)
        return {"ok": True}

    @app.post("/api/photos/{photo_id}/reprocess")
    def reprocess(photo_id: str):
        _get(photo_id)
        store.update(photo_id, status="queued", status_message="Waiting to be processed")
        return _start_import([photo_id])

    @app.get("/api/photos/{photo_id}/image/{name}")
    def photo_image(photo_id: str, name: str):
        _get(photo_id)
        p = store.image_file(photo_id, name)
        if p is None:
            raise HTTPException(404, "Not available")
        return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    # ------------------------------------------------------------- import
    def import_paths(chosen: list[str]) -> dict:
        """Link files (or every supported photo in a dropped folder) in place."""
        files: list[Path] = []
        for p in chosen:
            path = Path(p)
            if os.path.isdir(io_path(path)):
                files += sorted(f for f in path.iterdir()
                                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS)
            elif os.path.isfile(io_path(path)) and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                files.append(path)
        ids = [store.create(f, "linked", f.name)["id"] for f in files]
        if not ids:
            return {"job": None, "photo_ids": []}
        return {"job": _start_import(ids), "photo_ids": ids}

    app.state.import_paths = import_paths

    @app.post("/api/import/dialog")
    def import_dialog():
        try:
            chosen = dialogs.choose_files()
        except dialogs.DialogUnavailable as e:
            raise HTTPException(501, f"The Windows file dialog is not available here ({e}). "
                                     "Drag photos onto the window or use 'Upload copies' instead.")
        return import_paths(chosen)

    @app.post("/api/import/upload")
    async def import_upload(files: list[UploadFile] = File(...)):
        ids = []
        rejected = []
        for uf in files:
            name = os.path.basename((uf.filename or "photo").replace("\\", "/"))
            ext = os.path.splitext(name)[1]
            if ext.lower() not in SUPPORTED_EXTENSIONS:
                rejected.append(f"{name}: not a supported photo type")
                continue
            folder = paths.imports / uuid.uuid4().hex
            folder.mkdir(parents=True)
            stem = safe_stem(os.path.splitext(name)[0])
            dest = folder / f"{stem}{ext}"
            size = 0
            with open(io_path(dest), "wb") as f:
                while chunk := await uf.read(4 << 20):
                    size += len(chunk)
                    if size > MAX_INPUT_BYTES:
                        break
                    f.write(chunk)
            if size > MAX_INPUT_BYTES:
                dest.unlink(missing_ok=True)
                folder.rmdir()
                rejected.append(f"{name}: file too large")
                continue
            ids.append(store.create(dest, "imported_copy", name)["id"])
        job = _start_import(ids) if ids else None
        return {"job": job, "photo_ids": ids, "rejected": rejected}

    # ----------------------------------------------------------- relocate
    @app.post("/api/photos/{photo_id}/relocate")
    def relocate(photo_id: str):
        rec = _get(photo_id)
        try:
            chosen = dialogs.choose_file()
        except dialogs.DialogUnavailable as e:
            raise HTTPException(501, f"The Windows file dialog is not available here ({e}).")
        if not chosen:
            return {"ok": False, "cancelled": True}
        path = Path(chosen[0])
        try:
            fp = fingerprint(path)
        except OSError:
            raise HTTPException(400, "That file could not be read.") from None
        old = rec["source"].get("fingerprint") or {}
        if old and fp != old:
            pid = uuid.uuid4().hex
            pending_relocations[pid] = (photo_id, str(path))
            return JSONResponse(status_code=409, content={
                "pending_id": pid,
                "detail": "The chosen file is not identical to the original that was imported. "
                          "Use it anyway? Your saved edits will be applied to this file."})
        return _apply_relocation(photo_id, path)

    def _apply_relocation(photo_id: str, path: Path) -> dict:
        rec = store.get(photo_id)
        src = dict(rec["source"])
        src.update(path=str(path), kind="linked", fingerprint=fingerprint(path))
        store.update(photo_id, source=src)
        proc.full.clear(photo_id)
        job = None
        if rec.get("decode_status") != "supported":
            job = _start_import([photo_id])
        return {"ok": True, "job": job}

    @app.post("/api/photos/{photo_id}/relocate/confirm")
    def relocate_confirm(photo_id: str, body: RelocateConfirm):
        item = pending_relocations.pop(body.pending_id, None)
        if not item or item[0] != photo_id:
            raise HTTPException(404, "Nothing to confirm")
        return _apply_relocation(photo_id, Path(item[1]))

    # ------------------------------------------------------------- recipes
    def _check_mask(photo_id: str, recipe: Recipe) -> None:
        if recipe.needs_mask and proc.usable_mask(photo_id) is None:
            raise HTTPException(409, "Bird-aware processing and the Soft Background look need a "
                                     "reliable bird selection, and this photo doesn't have one.")

    @app.put("/api/photos/{photo_id}/recipe")
    def put_recipe(photo_id: str, recipe: Recipe):
        _get(photo_id)
        _check_mask(photo_id, recipe)
        recipe = limited(recipe)
        store.put_recipe(photo_id, recipe)
        return {"ok": True, "summary": proc.summary(photo_id, recipe), "recipe": recipe.model_dump(),
                "edit_level": restraint.edit_level(recipe)}

    @app.post("/api/photos/{photo_id}/auto")
    def auto(photo_id: str, body: AutoReq):
        _get(photo_id)
        try:
            recipe, summary = proc.auto_edit(photo_id, body.look)
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        return {"recipe": recipe.model_dump(), "summary": summary, "edit_level": restraint.edit_level(recipe)}

    @app.post("/api/auto-all")
    def auto_all(body: AutoAllReq):
        ids = [p for p in body.photo_ids if _get(p)]

        def work(job, pid):
            rec = store.get(pid)
            if rec.get("decode_status") != "supported":
                return {"item": pid, "ok": False,
                        "message": f"{rec['original_name']}: skipped (not decoded)"}
            proc.auto_edit(pid, body.look)
            return {"item": pid, "ok": True, "message": f"{rec['original_name']}: auto edited"}

        return jobs.submit("auto", f"Auto editing {len(ids)} photo(s)", ids, work, pool="import").to_dict()

    @app.get("/api/limits")
    def limits():
        return {"enabled": load_settings().natural_limits,
                "limits": {k: list(v) for k, v in restraint.NATURAL_LIMITS.items()}}

    # ------------------------------------------------------------- history
    @app.get("/api/photos/{photo_id}/history")
    def get_history(photo_id: str):
        _get(photo_id)
        p = store.photo_dir(photo_id) / "history.json"
        try:
            h = History.model_validate_json(p.read_text("utf-8"))
            return h.model_dump()
        except (OSError, ValidationError, ValueError):
            import time as _t
            return {"entries": [{"label": "Imported", "time": _t.time(),
                                 "recipe": store.get_recipe(photo_id).model_dump()}], "index": 0}

    @app.put("/api/photos/{photo_id}/history")
    def put_history(photo_id: str, h: History):
        _get(photo_id)
        if not h.entries or h.index >= len(h.entries):
            raise HTTPException(422, "Invalid history")
        atomic_write_text(store.photo_dir(photo_id) / "history.json", h.model_dump_json())
        return {"ok": True}

    # ------------------------------------------------------- subject masks
    @app.get("/api/subject/status")
    def subject_status():
        st = masks.status()
        st["enabled"] = load_settings().subject_detection
        return st

    @app.post("/api/photos/{photo_id}/detect")
    def detect(photo_id: str, body: DetectReq):
        rec = _get(photo_id)
        if rec.get("decode_status") != "supported":
            raise HTTPException(409, "This photo has not been decoded.")
        if not load_settings().subject_detection:
            raise HTTPException(409, "Bird detection is switched off. Turn it on in the Bird selection panel.")
        try:
            pts = [p.model_dump() for p in body.points] if body.points is not None else None
            return proc.detect(photo_id, pts, body.redetect)
        except ValueError as e:
            raise HTTPException(409, str(e)) from None

    @app.post("/api/photos/{photo_id}/mask/accept")
    def accept_mask(photo_id: str):
        _get(photo_id)
        try:
            return proc.accept_mask(photo_id)
        except ValueError as e:
            raise HTTPException(409, str(e)) from None

    @app.delete("/api/photos/{photo_id}/mask")
    def delete_mask(photo_id: str):
        _get(photo_id)
        proc.clear_mask(photo_id)
        return {"ok": True}

    @app.get("/api/photos/{photo_id}/mask.png")
    def mask_png(photo_id: str):
        _get(photo_id)
        p = store.photo_dir(photo_id) / "mask.png"
        if not p.exists():
            raise HTTPException(404, "No selection")
        return FileResponse(p, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/api/photos/{photo_id}/crop-suggestion")
    def crop_suggestion(photo_id: str, body: CropSuggestReq):
        rec = _get(photo_id)
        m = proc.usable_mask(photo_id)
        if m is None:
            raise HTTPException(409, "Crop suggestions need a reliable bird selection.")
        fw, fh = rec["full_size"]
        ratios = {"3:2": 1.5, "4:3": 4 / 3, "1:1": 1.0, "16:9": 16 / 9,
                  "original": max(fw, fh) / min(fw, fh), "free": None}
        r = ratios[body.aspect]
        if r is not None and body.portrait:
            r = 1 / r
        sug = masks.suggest_crop(m, r, (fw, fh))
        if sug is None:
            return {"crop": None, "message": "No tighter crop is suggested: the bird already fills the frame, "
                                             "or this shape would cut it off."}
        crop = {"aspect": body.aspect, "portrait": body.portrait, **{k: sug[k] for k in ("x", "y", "w", "h")}}
        return {"crop": crop, "pixels": sug["pixels"],
                "message": f"Suggested crop keeps the whole bird: {sug['pixels'][0]} x {sug['pixels'][1]} px. "
                           "The direction the bird faces is not taken into account."}

    @app.post("/api/paste")
    def paste(body: PasteReq):
        from .recipe import Sliders
        try:
            sliders = Sliders.model_validate(body.sliders)
        except ValidationError as e:
            raise HTTPException(422, str(e)) from None
        done = []
        for pid in body.photo_ids:
            _get(pid)
            cur = store.get_recipe(pid)
            new = cur.model_copy(update={"look": body.look, "strength": body.strength,
                                         "sliders": sliders})
            new = limited(Recipe.model_validate(new.model_dump()))
            if new.look == "soft_background" and proc.usable_mask(pid) is None:
                new = new.model_copy(update={"look": "natural"})
            store.put_recipe(pid, new)
            done.append(pid)
        return {"ok": True, "photo_ids": done}

    # -------------------------------------------------------------- render
    @app.post("/api/photos/{photo_id}/render")
    def render(photo_id: str, body: RenderReq):
        _get(photo_id)
        try:
            data, info = proc.render_preview(photo_id, limited(body.recipe), body.before, body.max_edge,
                                             body.ignore_crop)
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        return Response(data, media_type="image/jpeg", headers={
            "Cache-Control": "no-store", "X-Width": str(info["width"]), "X-Height": str(info["height"])})

    @app.post("/api/photos/{photo_id}/render-region")
    def render_region(photo_id: str, body: RegionReq):
        rec = _get(photo_id)
        if rec.get("decode_status") != "supported":
            raise HTTPException(409, "This photo has not been decoded.")
        try:
            data, info = proc.render_region(photo_id, limited(body.recipe), body.before,
                                            body.x, body.y, body.w, body.h)
        except BlockingIOError as e:
            raise HTTPException(503, str(e)) from None
        except FileNotFoundError as e:
            raise HTTPException(410, str(e)) from None
        except Exception as e:
            log.exception("region render failed")
            raise HTTPException(500, getattr(e, "user_message", "Rendering failed.")) from None
        headers = {"Cache-Control": "no-store", **{f"X-{k.replace('_', '-')}": str(v) for k, v in info.items()}}
        return Response(data, media_type="image/jpeg", headers=headers)

    # ---------------------------------------------------------------- jobs
    @app.get("/api/jobs")
    def list_jobs():
        return jobs.list()

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        return {"ok": jobs.cancel(job_id)}

    # -------------------------------------------------------------- export
    @app.post("/api/dialog/folder")
    def choose_folder():
        try:
            chosen = dialogs.choose_folder("Choose where to save exported photos")
        except dialogs.DialogUnavailable as e:
            raise HTTPException(501, f"The Windows folder dialog is not available here ({e}). "
                                     "Type or paste the folder path instead.")
        return {"path": chosen[0] if chosen else ""}

    @app.post("/api/export")
    def export(body: ExportReq):
        try:
            folder = validate_folder(body.folder)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        ids = [p for p in body.photo_ids if _get(p)]
        if not ids:
            raise HTTPException(400, "No photos selected for export.")
        opts = ExportOptions(folder=folder, format=body.format, quality=body.quality,
                             long_edge=body.long_edge, keep_gps=body.keep_gps)
        export_folders.add(str(folder))
        job = jobs.submit("export", f"Exporting {len(ids)} photo(s)", ids,
                          lambda job, pid: export_one(proc, job, pid, opts), pool="heavy")
        return job.to_dict()

    @app.post("/api/open-folder")
    def open_folder(body: dict):
        path = str(body.get("path", ""))
        if path not in export_folders:
            raise HTTPException(403, "Only folders exported to in this session can be opened.")
        if sys.platform != "win32":
            raise HTTPException(501, "Opening folders is only supported on Windows.")
        os.startfile(io_path(path))  # type: ignore[attr-defined]
        return {"ok": True}

    # ------------------------------------------------------------ settings
    @app.get("/api/settings")
    def get_settings():
        return load_settings().model_dump()

    @app.put("/api/settings")
    def put_settings(s: SettingsModel):
        if s.subject_detection is None:
            s.subject_detection = load_settings().subject_detection
        atomic_write_text(paths.settings_file, s.model_dump_json(indent=1))
        return {"ok": True}

    # ------------------------------------------------------------ web page
    index_file = WEB_DIR / "index.html"

    @app.get("/", response_class=HTMLResponse)
    def index():
        if not index_file.exists():
            return HTMLResponse("<h1>Web interface not built</h1><p>Run the frontend build.</p>", 500)
        html = index_file.read_text("utf-8").replace("__BIRDEDIT_TOKEN__", token)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    if (WEB_DIR / "assets").exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

    return app
