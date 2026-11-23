"""Glue between the store, the decoder and the pipeline."""

from __future__ import annotations

import gc
import io
import logging
import threading
from collections import OrderedDict

import cv2
import numpy as np
from PIL import Image

from . import auto, decode, formats, metadata, noise, pipeline
from .config import MAX_INPUT_BYTES, PREVIEW_MAX_EDGE, THUMB_MAX_EDGE
from .jobs import Job
from .recipe import Recipe, baseline_recipe, effective
from .store import Store
from .summary import summarize

log = logging.getLogger(__name__)


def _resize_max(img: np.ndarray, max_edge: int) -> np.ndarray:
    h, w = img.shape[:2]
    f = max_edge / max(h, w)
    if f >= 1:
        return img
    return cv2.resize(img, (max(1, round(w * f)), max(1, round(h * f))), interpolation=cv2.INTER_AREA)


def to_jpeg_bytes(disp: np.ndarray, quality: int = 88) -> bytes:
    im = Image.fromarray(np.round(np.clip(disp, 0, 1) * 255).astype(np.uint8))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


class FullResCache:
    """At most one full-resolution decoded image in memory (it can be 0.5 GB)."""

    def __init__(self) -> None:
        self.slot = threading.Semaphore(1)     # full-res work in flight
        self._lock = threading.Lock()
        self._item: tuple[str, decode.Decoded] | None = None

    def get(self, photo_id: str) -> decode.Decoded | None:
        with self._lock:
            if self._item and self._item[0] == photo_id:
                return self._item[1]
        return None

    def put(self, photo_id: str, dec: decode.Decoded) -> None:
        with self._lock:
            self._item = (photo_id, dec)

    def clear(self, photo_id: str | None = None) -> None:
        with self._lock:
            if photo_id is None or (self._item and self._item[0] == photo_id):
                self._item = None
        gc.collect()


class Processor:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.full = FullResCache()

    # ------------------------------------------------------------ import
    def import_one(self, job: Job, photo_id: str) -> dict:
        st = self.store
        rec = st.get(photo_id)
        name = rec["original_name"]
        if not st.source_available(rec):
            st.update(photo_id, status="error", status_message="Original file not found",
                      decode_status="failed", decode_error="The original file could not be found.")
            return {"item": photo_id, "ok": False, "message": f"{name}: original file not found"}
        st.update(photo_id, status="processing", status_message="Reading file")
        try:
            data = st.read_source(rec, MAX_INPUT_BYTES)
        except (OSError, ValueError) as e:
            st.update(photo_id, status="error", decode_status="failed",
                      decode_error=f"The file could not be read: {e}")
            return {"item": photo_id, "ok": False, "message": f"{name}: could not be read"}

        ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        sniff = formats.classify(data[:64], ext)
        thumb_jpeg = decode.embedded_preview_jpeg_bytes(data) if sniff.kind == formats.Kind.RAW else None
        md = metadata.read_metadata(data, sniff.container, thumb_jpeg)
        if sniff.kind == formats.Kind.RAW and sniff.container == formats.Container.TIFF and ext:
            label = ext.lstrip(".").upper()          # NEF, ARW, DNG ... (TIFF-structured RAW)
        else:
            label = sniff.container.value.upper()
        st.update(photo_id, container=sniff.container.value, kind=sniff.kind.value, format_label=label,
                  format_note=sniff.note, metadata=md.to_dict(),
                  status_message="Identified camera" if md.camera.identified else "Reading image")
        if sniff.kind == formats.Kind.UNSUPPORTED:
            st.update(photo_id, status="error", decode_status="unsupported",
                      decode_error=sniff.note or "Unsupported file type.")
            return {"item": photo_id, "ok": False, "message": f"{name}: unsupported file"}
        if job.cancelled:
            raise InterruptedError

        # Temporary embedded preview (clearly labelled in the UI).
        if sniff.kind == formats.Kind.RAW:
            em = decode.extract_embedded_preview(data)
            if em is not None:
                em.thumbnail((PREVIEW_MAX_EDGE, PREVIEW_MAX_EDGE))
                cd = st.cache_dir(photo_id)
                em.save(cd / "embedded.jpg", "JPEG", quality=85)
                em.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE))
                em.save(cd / "thumb.jpg", "JPEG", quality=80)
                st.update(photo_id, preview_kind="embedded",
                          status_message="Showing camera preview; rendering RAW...")
        job.item_progress = 0.3
        if job.cancelled:
            raise InterruptedError

        try:
            dec = decode.decode(data, sniff, half=True, orientation=md.orientation,
                                camera_name=md.camera.display_name, md=md)
        except decode.DecodeError as e:
            st.update(photo_id, status="error", decode_status=e.code,
                      decode_error=e.user_message, decode_detail=e.detail[:300],
                      metadata=md.to_dict())
            return {"item": photo_id, "ok": False, "message": f"{name}: {e.user_message}"}
        del data
        job.item_progress = 0.7
        nm = noise.estimate(dec.image, dec.noise_native_scale, md.iso)
        prev = _resize_max(dec.image, PREVIEW_MAX_EDGE)
        scale = prev.shape[1] / dec.full_size[0]
        info = dict(dec.info)
        full_size = [int(dec.full_size[0]), int(dec.full_size[1])]
        del dec
        st.save_preview(photo_id, prev, scale)
        disp = pipeline.render(_resize_max(prev, THUMB_MAX_EDGE), effective(baseline_recipe()), nm, scale)
        (st.cache_dir(photo_id) / "thumb.jpg").write_bytes(to_jpeg_bytes(disp, 82))
        st.update(photo_id, status="ready", status_message="Ready", decode_status="supported",
                  decode_error="", metadata=md.to_dict(), decoder_info=info,
                  full_size=full_size, noise_model=nm.to_dict(), preview_kind="rendered")
        return {"item": photo_id, "ok": True, "message": f"{name}: ready"}

    # ------------------------------------------------------------- auto
    def auto_edit(self, photo_id: str, look: str = "natural") -> tuple[Recipe, str]:
        rec = self.store.get(photo_id)
        loaded = self.store.load_preview(photo_id)
        if loaded is None or rec.get("decode_status") != "supported":
            raise ValueError("This photo has not been decoded yet.")
        prev, scale = loaded
        nm = noise.NoiseModel.from_dict(rec["noise_model"])
        old = self.store.get_recipe(photo_id)
        recipe, facts = auto.analyze_and_build(prev, nm, look, noise_render_scale=1.0)
        recipe = recipe.model_copy(update={"crop": old.crop})
        self.store.put_facts(photo_id, facts)
        self.store.put_recipe(photo_id, recipe)
        return recipe, summarize(recipe, facts)

    def summary(self, photo_id: str, recipe: Recipe) -> str:
        return summarize(recipe, self.store.get_facts(photo_id))

    # ----------------------------------------------------------- render
    def render_preview(self, photo_id: str, recipe: Recipe, before: bool, max_edge: int,
                       ignore_crop: bool = False) -> tuple[bytes, dict]:
        rec = self.store.get(photo_id)
        loaded = self.store.load_preview(photo_id)
        if loaded is None:
            raise ValueError("No preview available yet.")
        prev, scale = loaded
        nm = noise.NoiseModel.from_dict(rec["noise_model"])
        crop = None if ignore_crop else recipe.crop
        img = prev
        if crop is not None:
            h, w = prev.shape[:2]
            x0, y0 = int(crop.x * w), int(crop.y * h)
            x1, y1 = max(x0 + 1, int((crop.x + crop.w) * w)), max(y0 + 1, int((crop.y + crop.h) * h))
            pad = 24
            px0, py0 = max(0, x0 - pad), max(0, y0 - pad)
            px1, py1 = min(w, x1 + pad), min(h, y1 + pad)
            region = prev[py0:py1, px0:px1]
            f = min(1.0, max_edge / max(x1 - x0, y1 - y0))
            if f < 1:
                region = cv2.resize(region, (max(1, round(region.shape[1] * f)), max(1, round(region.shape[0] * f))),
                                    interpolation=cv2.INTER_AREA)
            r_scale = scale * f
            eff = effective(baseline_recipe() if before else recipe)
            out = pipeline.render(region, eff, nm, r_scale)
            ox, oy = round((x0 - px0) * f), round((y0 - py0) * f)
            ow, oh = max(1, round((x1 - x0) * f)), max(1, round((y1 - y0) * f))
            out = out[oy:oy + oh, ox:ox + ow]
        else:
            img = _resize_max(prev, max_edge)
            r_scale = scale * img.shape[1] / prev.shape[1]
            eff = effective(baseline_recipe() if before else recipe)
            out = pipeline.render(img, eff, nm, r_scale)
        return to_jpeg_bytes(out, 90), {"width": out.shape[1], "height": out.shape[0]}

    def _full_res(self, photo_id: str) -> decode.Decoded:
        cached = self.full.get(photo_id)
        if cached is not None:
            return cached
        rec = self.store.get(photo_id)
        if not self.store.source_available(rec):
            raise FileNotFoundError("The original file is missing; locate it to view at 100% or export.")
        self.full.clear()
        data = self.store.read_source(rec, MAX_INPUT_BYTES)
        sniff = formats.classify(data[:64], "." + rec["original_name"].rsplit(".", 1)[-1].lower())
        orient = int((rec.get("metadata") or {}).get("orientation") or 1)
        dec = decode.decode(data, sniff, half=False, orientation=orient)
        del data
        self.full.put(photo_id, dec)
        return dec

    def render_region(self, photo_id: str, recipe: Recipe, before: bool,
                      x: int, y: int, w: int, h: int) -> tuple[bytes, dict]:
        """Genuine 100% rendering of a region (full-res coordinates)."""
        if not self.full.slot.acquire(timeout=0.5):
            raise BlockingIOError("Busy with another full-resolution task; try again shortly.")
        try:
            dec = self._full_res(photo_id)
            nm = noise.NoiseModel.from_dict(self.store.get(photo_id)["noise_model"])
            H, W = dec.image.shape[:2]
            x = int(np.clip(x, 0, W - 1))
            y = int(np.clip(y, 0, H - 1))
            w = int(np.clip(w, 1, min(2400, W - x)))
            h = int(np.clip(h, 1, min(2400, H - y)))
            eff = effective(baseline_recipe() if before else recipe)
            out = pipeline.render_region(dec.image, eff, nm, x, y, w, h)
            return to_jpeg_bytes(out, 92), {"x": x, "y": y, "width": w, "height": h,
                                            "full_width": W, "full_height": H}
        finally:
            self.full.slot.release()


# ---------------------------------------------------------------- export

def export_one(proc: Processor, job: Job, photo_id: str, opts) -> dict:
    from .config import TILE, TILE_PAD
    from .export import resize_linear, write_output
    from .metadata import CaptureMetadata
    from .store import fingerprint
    from .winpath import safe_stem

    st = proc.store
    rec = st.get(photo_id)
    name = rec.get("original_name", photo_id)
    if rec.get("decode_status") != "supported":
        return {"item": photo_id, "ok": False, "message": f"{name}: cannot be exported (not decoded)"}
    if not st.source_available(rec):
        return {"item": photo_id, "ok": False,
                "message": f"{name}: original file is missing - use 'Locate original' first"}
    note = ""
    try:
        old_fp = rec["source"].get("fingerprint") or {}
        if old_fp and fingerprint(rec["source"]["path"]) != old_fp:
            note = " (note: the original file changed since import)"
    except OSError:
        pass
    recipe = st.get_recipe(photo_id)
    md = CaptureMetadata.from_dict(rec.get("metadata") or {})
    nm = noise.NoiseModel.from_dict(rec["noise_model"])
    while not proc.full.slot.acquire(timeout=0.5):
        if job.cancelled:
            raise InterruptedError
    try:
        dec = proc._full_res(photo_id)
        H, W = dec.image.shape[:2]
        if recipe.crop is not None:
            c = recipe.crop
            cx, cy = int(round(c.x * W)), int(round(c.y * H))
            cw = max(1, min(W - cx, int(round(c.w * W))))
            ch = max(1, min(H - cy, int(round(c.h * H))))
        else:
            cx, cy, cw, ch = 0, 0, W, H
        job.item_progress = 0.05

        def prog(f: float) -> None:
            job.item_progress = 0.05 + 0.85 * f

        pixels = pipeline.render_tiled(dec.image, effective(recipe), nm, (cx, cy, cw, ch),
                                       TILE, TILE_PAD, np.uint16, cancel=lambda: job.cancelled,
                                       progress=prog)
    finally:
        proc.full.slot.release()
        proc.full.clear()          # free the full-resolution buffer between files
    if opts.long_edge:
        f = pixels.astype(np.float32) / 65535.0
        f = resize_linear(f, int(opts.long_edge))
        pixels = np.round(np.clip(f, 0, 1) * 65535).astype(np.uint16)
    if opts.format == "jpeg":
        pixels = ((pixels.astype(np.uint32) + 128) // 257).astype(np.uint8)
    stem = safe_stem(name.rsplit(".", 1)[0] if "." in name else name)
    out = write_output(pixels, md, stem, opts)
    job.item_progress = 1.0
    return {"item": photo_id, "ok": True, "output": str(out),
            "message": f"{name} -> {out.name} ({pixels.shape[1]} x {pixels.shape[0]}){note}"}
