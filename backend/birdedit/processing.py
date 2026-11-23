"""Glue between the store, the decoder and the pipeline."""

from __future__ import annotations

import gc
import io
import logging
import threading
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from . import auto, converter, decode, formats, masks, metadata, noise, pipeline
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


def needs_converter_message(camera: str, high_efficiency: bool) -> str:
    cam = f" from your {camera}" if camera and camera != "Unknown camera" else ""
    if high_efficiency:
        return (f"This NEF{cam} uses Nikon's High Efficiency RAW compression. No free RAW decoder can "
                "read it, including the one built into this app. Install the free Adobe DNG Converter, "
                "then click Try again: Bird Photo Editor will convert these files automatically (your NEF "
                "is not changed). For future photos you can also set the camera's NEF compression to "
                "'Lossless compressed'.")
    return (f"The RAW decoder in this app cannot read this file{cam}. If you install the free Adobe "
            "DNG Converter and click Try again, Bird Photo Editor will convert it automatically "
            "(your original is not changed).")


def profile_warning_message(camera: str) -> str:
    cam = camera if camera and camera != "Unknown camera" else "this camera"
    return (f"The RAW decoder built into this app does not yet have a colour profile for {cam}, so "
            "colours may be inaccurate (and the edges may include unused sensor pixels). Install the "
            "free Adobe DNG Converter and click Try again: the app then converts these files "
            "automatically and uses Adobe's profile for your camera. Your original is not changed.")


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
    def __init__(self, store: Store, subject_enabled=lambda: False, limit=lambda r: r) -> None:
        self.store = store
        self.limit = limit                          # natural limits (if switched on)
        self.full = FullResCache()
        self.subject_enabled = subject_enabled      # user consent + models installed
        self._masks: OrderedDict[str, tuple[float, dict | None, np.ndarray | None]] = OrderedDict()
        self._emb: OrderedDict[str, dict] = OrderedDict()
        self._full_mask: tuple[str, float, np.ndarray] | None = None
        self._mask_lock = threading.Lock()

    # ------------------------------------------------------------- masks
    def mask(self, photo_id: str) -> tuple[dict | None, np.ndarray | None]:
        folder = self.store.photo_dir(photo_id)
        p = folder / "mask.json"
        try:
            mtime = p.stat().st_mtime
        except OSError:
            return None, None
        with self._mask_lock:
            c = self._masks.get(photo_id)
            if c and c[0] == mtime:
                return c[1], c[2]
        info, m = masks.load_mask(folder)
        loaded = self.store.load_preview(photo_id)
        if m is not None and loaded is not None and m.shape != loaded[0].shape[:2]:
            m = None                                    # stale (preview was rebuilt)
            info = dict(info or {}, status="none", message="Selection is out of date; detect again.")
        with self._mask_lock:
            self._masks[photo_id] = (mtime, info, m)
            while len(self._masks) > 6:
                self._masks.popitem(last=False)
        return info, m

    def usable_mask(self, photo_id: str) -> np.ndarray | None:
        info, m = self.mask(photo_id)
        if m is None or not info:
            return None
        if info.get("status") == "good" or info.get("accepted"):
            return m
        return None

    def detect(self, photo_id: str, points: list | None = None, redetect: bool = False) -> dict:
        if not masks.status()["installed"]:
            raise ValueError("Bird detection is not installed in this copy of the app.")
        loaded = self.store.load_preview(photo_id)
        if loaded is None:
            raise ValueError("This photo has not been decoded yet.")
        prev, _ = loaded
        info, _ = self.mask(photo_id)
        hint = None
        if points is not None and info and info.get("birds") and not redetect:
            hint = [{"box": b["box"], "score": b["score"]} for b in info["birds"] if b.get("box")]
        with self._mask_lock:
            cache = self._emb.setdefault(photo_id, {})
            self._emb.move_to_end(photo_id)
            while len(self._emb) > 2:
                self._emb.popitem(last=False)
        h, w = prev.shape[:2]
        pts = [(float(p["x"]) * w, float(p["y"]) * h, 1 if p.get("bird", True) else 0) for p in (points or [])]
        result, m = masks.compute(prev, pts, hint, cache)
        masks.save_mask_files(self.store.photo_dir(photo_id), result, m)
        return result.to_dict()

    def accept_mask(self, photo_id: str) -> dict:
        """The user chose 'Use anyway' for an uncertain selection."""
        import json as _json

        from .store import atomic_write_text
        info, m = self.mask(photo_id)
        if not info or m is None:
            raise ValueError("There is no selection to use.")
        info = dict(info, accepted=True)
        atomic_write_text(self.store.photo_dir(photo_id) / "mask.json", _json.dumps(info, indent=1))
        return info

    def clear_mask(self, photo_id: str) -> None:
        folder = self.store.photo_dir(photo_id)
        for name in ("mask.json", "mask.png"):
            try:
                (folder / name).unlink()
            except OSError:
                pass
        with self._mask_lock:
            self._masks.pop(photo_id, None)
        r = self.store.get_recipe(photo_id)
        if r.needs_mask:
            from .recipe import Subject
            look = "natural" if r.look == "soft_background" else r.look
            self.store.put_recipe(photo_id, r.model_copy(update={"subject": Subject(), "look": look}))

    def _mask_full(self, photo_id: str, shape: tuple[int, int]) -> np.ndarray | None:
        m = self.usable_mask(photo_id)
        if m is None:
            return None
        info_mtime = self._masks.get(photo_id, (0,))[0]
        c = self._full_mask
        if c and c[0] == photo_id and c[1] == info_mtime and c[2].shape == shape:
            return c[2]
        full = cv2.resize(m, (shape[1], shape[0]), interpolation=cv2.INTER_LINEAR)
        self._full_mask = (photo_id, info_mtime, full)
        return full

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

        converted = None
        try:
            dec = decode.decode(data, sniff, half=True, orientation=md.orientation,
                                camera_name=md.camera.display_name, md=md)
        except decode.DecodeError as e:
            if sniff.kind != formats.Kind.RAW:
                st.update(photo_id, status="error", decode_status=e.code,
                          decode_error=e.user_message, decode_detail=e.detail[:300], metadata=md.to_dict())
                return {"item": photo_id, "ok": False, "message": f"{name}: {e.user_message}"}
            # A RAW variant LibRaw cannot read: convert with Adobe DNG Converter if installed.
            he = converter.is_nikon_high_efficiency(data)
            exe = converter.find_dng_converter()
            if exe is None:
                msg = needs_converter_message(md.camera.display_name, he)
                st.update(photo_id, status="error", decode_status="needs_converter", decode_error=msg,
                          decode_detail=e.detail[:300], metadata=md.to_dict(), high_efficiency=he)
                return {"item": photo_id, "ok": False, "message": f"{name}: needs Adobe DNG Converter"}
            st.update(photo_id, status_message="Converting with Adobe DNG Converter...")
            try:
                converted = converter.convert_to_dng(Path(rec["source"]["path"]), st.cache_dir(photo_id), exe)
                dng = converted.read_bytes()
                dec = decode.decode(dng, formats.classify(dng[:64], ".dng"), half=True,
                                    camera_name=md.camera.display_name)
                del dng
            except (converter.ConversionError, decode.DecodeError, OSError) as e2:
                msg = getattr(e2, "user_message", None) or str(e2)
                st.update(photo_id, status="error", decode_status="failed", metadata=md.to_dict(),
                          decode_error=f"Adobe DNG Converter could not convert this file: {msg}",
                          high_efficiency=he)
                return {"item": photo_id, "ok": False, "message": f"{name}: conversion failed"}
        # The decoder read the file but has no colour profile for this (newer)
        # camera: colours would be guesswork. Prefer Adobe's DNG, which has one.
        suspect = (not dec.info.get("profile_known", True)) or dec.info.get("empty_border", False)
        force = bool(rec.get("force_dng"))
        profile_missing = sniff.kind == formats.Kind.RAW and converted is None and (suspect or force)
        if dec.info.get("empty_border"):
            log.warning("%s: decoded frame has an empty border (decoder may not know this camera)", name)
        if profile_missing:
            exe = converter.find_dng_converter()
            if exe is not None:
                st.update(photo_id, status_message="Converting with Adobe DNG Converter (camera profile)...")
                try:
                    converted = converter.convert_to_dng(Path(rec["source"]["path"]), st.cache_dir(photo_id), exe)
                    dng = converted.read_bytes()
                    dec = decode.decode(dng, formats.classify(dng[:64], ".dng"), half=True,
                                        camera_name=md.camera.display_name)
                    del dng
                    profile_missing = False
                except (converter.ConversionError, decode.DecodeError, OSError) as e:
                    log.exception("conversion for missing camera profile failed")
                    converted = None
                    if force:
                        st.update(photo_id, force_dng=False)
                        raise RuntimeError(f"Adobe DNG Converter could not convert this file: {e}") from e
        del data
        job.item_progress = 0.7
        nm = noise.estimate(dec.image, dec.noise_native_scale, md.iso)
        prev = _resize_max(dec.image, PREVIEW_MAX_EDGE)
        scale = prev.shape[1] / dec.full_size[0]
        info = dict(dec.info)
        if converted is not None:
            info["converted_with"] = "Adobe DNG Converter (original file unchanged)"
        full_size = [int(dec.full_size[0]), int(dec.full_size[1])]
        del dec
        st.save_preview(photo_id, prev, scale)
        disp = pipeline.render(_resize_max(prev, THUMB_MAX_EDGE), effective(baseline_recipe()), nm, scale)
        (st.cache_dir(photo_id) / "thumb.jpg").write_bytes(to_jpeg_bytes(disp, 82))
        st.update(photo_id, status="ready", status_message="Ready", decode_status="supported",
                  decode_error="", metadata=md.to_dict(), decoder_info=info,
                  full_size=full_size, noise_model=nm.to_dict(), preview_kind="rendered",
                  converted_dng=converted is not None,
                  profile_warning=(profile_warning_message(md.camera.display_name)
                                   if profile_missing and suspect else ""))
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
        if self.subject_enabled():
            info, _ = self.mask(photo_id)
            if info is None:
                try:
                    self.detect(photo_id)
                except Exception:
                    log.exception("bird detection failed; using global editing")
        mask = self.usable_mask(photo_id) if self.subject_enabled() else None
        recipe, facts = auto.analyze_and_build(prev, nm, look, noise_render_scale=1.0, mask=mask)
        recipe = self.limit(recipe.model_copy(update={"crop": old.crop}))
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
        m8 = self.usable_mask(photo_id) if (recipe.needs_mask and not before) else None
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
            mreg = None
            if m8 is not None:
                mreg = m8[py0:py1, px0:px1]
                if mreg.shape[:2] != region.shape[:2]:
                    mreg = cv2.resize(mreg, (region.shape[1], region.shape[0]), interpolation=cv2.INTER_AREA)
                mreg = mreg.astype(np.float32) / 255.0
            out = pipeline.render(region, eff, nm, r_scale, mreg)
            ox, oy = round((x0 - px0) * f), round((y0 - py0) * f)
            ow, oh = max(1, round((x1 - x0) * f)), max(1, round((y1 - y0) * f))
            out = out[oy:oy + oh, ox:ox + ow]
        else:
            img = _resize_max(prev, max_edge)
            r_scale = scale * img.shape[1] / prev.shape[1]
            eff = effective(baseline_recipe() if before else recipe)
            mimg = None
            if m8 is not None:
                mimg = cv2.resize(m8, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_AREA) \
                    if m8.shape != img.shape[:2] else m8
                mimg = mimg.astype(np.float32) / 255.0
            out = pipeline.render(img, eff, nm, r_scale, mimg)
        return to_jpeg_bytes(out, 90), {"width": out.shape[1], "height": out.shape[0]}

    def _full_res(self, photo_id: str) -> decode.Decoded:
        cached = self.full.get(photo_id)
        if cached is not None:
            return cached
        rec = self.store.get(photo_id)
        if not self.store.source_available(rec):
            raise FileNotFoundError("The original file is missing; locate it to view at 100% or export.")
        self.full.clear()
        if rec.get("converted_dng"):
            dng_path = self.store.cache_dir(photo_id) / "converted.dng"
            if not dng_path.is_file():          # cache was cleared: convert again
                converter.convert_to_dng(Path(rec["source"]["path"]), self.store.cache_dir(photo_id))
            data = dng_path.read_bytes()
            dec = decode.decode(data, formats.classify(data[:64], ".dng"), half=False)
            del data
            self.full.put(photo_id, dec)
            return dec
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
            mf = self._mask_full(photo_id, (H, W)) if (recipe.needs_mask and not before) else None
            out = pipeline.render_region(dec.image, eff, nm, x, y, w, h, mask_full=mf)
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
    recipe = proc.limit(st.get_recipe(photo_id))
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

        mf = None
        if recipe.needs_mask:
            mf = proc._mask_full(photo_id, (H, W))
            if mf is None:
                return {"item": photo_id, "ok": False,
                        "message": f"{name}: its edit uses a bird selection that is no longer available. "
                                   "Detect the bird again or switch off bird-aware processing."}
        pixels = pipeline.render_tiled(dec.image, effective(recipe), nm, (cx, cy, cw, ch),
                                       TILE, TILE_PAD, np.uint16, cancel=lambda: job.cancelled,
                                       progress=prog, mask_full=mf)
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
