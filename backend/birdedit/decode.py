"""Decode RAW / JPEG / TIFF into the linear ProPhoto float32 working space.

RAW baseline decoder settings (stored in every recipe, see ``DECODER_SETTINGS``):
camera "as shot" white balance, LibRaw's camera colour matrix, AHD demosaic,
no auto-brightening, linear output (gamma 1), highlight mode "clip",
16-bit output to ProPhoto. Embedded JPEG previews are never used for edits.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field

import numpy as np
import rawpy
from PIL import Image, ImageCms, ImageOps

from . import color
from .config import MAX_PIXELS
from .formats import Container, Kind, Sniff
from .icc import parse_icc

log = logging.getLogger(__name__)
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

DECODER_SETTINGS = {
    "decoder": "LibRaw via rawpy",
    "rawpy_version": rawpy.__version__,
    "libraw_version": ".".join(str(x) for x in rawpy.libraw_version),
    "white_balance": "camera as-shot",
    "demosaic": "AHD",
    "highlight_mode": "clip",
    "output_color": "ProPhoto (linear)",
    "auto_bright": False,
}


class DecodeError(Exception):
    """A file could not be decoded. ``user_message`` is safe to display."""

    def __init__(self, user_message: str, detail: str = "", code: str = "failed"):
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail
        self.code = code            # "unsupported" (decoder lacks support) or "failed"


@dataclass
class Decoded:
    image: np.ndarray                 # HxWx3 float32 linear ProPhoto, >= 0
    full_size: tuple[int, int]        # (width, height) of the full-res oriented image
    scale: float                      # image pixels per full-res pixel (<= 1)
    noise_native_scale: float         # scale at which pixel noise ~= full-res noise
    info: dict = field(default_factory=dict)


def _libraw_error(e: Exception, camera_name: str) -> DecodeError:
    name = type(e).__name__
    cam = f" from {camera_name}" if camera_name and camera_name != "Unknown camera" else ""
    if "Unsupported" in name:
        msg = (f"This RAW file{cam} uses a format or compression variant that the installed "
               "decoder (LibRaw) does not support.")
    elif "Data" in name or "IO" in name or "OutOfOrder" in name:
        msg = (f"The RAW file{cam} could not be read. It may be incomplete, damaged, "
               "or a variant the decoder cannot handle.")
    elif "Memory" in name:
        msg = "Not enough memory to decode this RAW file."
    else:
        msg = f"The RAW file{cam} could not be decoded."
    code = "unsupported" if "Unsupported" in name else "failed"
    return DecodeError(msg, f"{name}: {e}", code)


def _open_raw(data: bytes, camera_name: str) -> rawpy.RawPy:
    try:
        return rawpy.imread(io.BytesIO(data))
    except Exception as e:  # LibRaw raises a family of LibRawError subclasses
        raise _libraw_error(e, camera_name) from e


def _raw_full_size(raw: rawpy.RawPy) -> tuple[int, int]:
    s = raw.sizes
    w, h = s.width, s.height
    if s.flip in (5, 6):
        w, h = h, w
    return int(w), int(h)


def _crop_rect(raw: rawpy.RawPy) -> tuple[int, int, int, int] | None:
    """The camera's official image area (from maker notes or DNG DefaultCrop),
    in unrotated sensor coordinates, if it is smaller than the decoded frame."""
    s = raw.sizes
    if s.crop_width <= 0 or s.crop_height <= 0:
        return None
    # LibRaw gives the crop origin relative to the whole sensor readout
    # (raw_width x raw_height); the decoded image starts at left/top_margin.
    x = int(s.crop_left_margin) - int(s.left_margin)
    y = int(s.crop_top_margin) - int(s.top_margin)
    w, h = int(s.crop_width), int(s.crop_height)
    if x < 0 or y < 0 or x + w > s.width or y + h > s.height:
        return None                    # inconsistent metadata: keep the full decoded frame
    if w >= s.width and h >= s.height:
        return None
    return x, y, w, h


def _rotate_rect(rect, W: int, H: int, flip: int):
    """Map a rectangle in unrotated coordinates (frame W x H) through LibRaw's flip."""
    x, y, w, h = rect
    if flip == 3:
        return W - x - w, H - y - h, w, h
    if flip == 5:      # rotated 90 degrees counter-clockwise
        return y, W - x - w, h, w
    if flip == 6:      # rotated 90 degrees clockwise
        return H - y - h, x, h, w
    return x, y, w, h


def profile_known(raw: rawpy.RawPy, is_dng: bool) -> bool:
    """Does the decoder have a colour profile for this camera? (DNGs carry their own.)"""
    if is_dng:
        return True
    try:
        return bool(np.any(np.abs(np.asarray(raw.rgb_xyz_matrix)[:3]) > 1e-6))
    except Exception:
        return True


def _has_empty_border(img: np.ndarray) -> bool:
    """True if a band along the bottom or right edge is essentially black while
    the photo itself is not: a sign the decoder used the wrong image area for
    this camera (unused sensor pixels)."""
    h, w = img.shape[:2]
    if h < 64 or w < 64:
        return False
    y = img.mean(axis=2)
    body = float(np.median(y[: int(h * 0.8), : int(w * 0.8)]))
    if body < 0.002:
        return False                                   # genuinely dark photo
    bh, bw = max(2, int(h * 0.005)), max(2, int(w * 0.005))   # outermost 0.5% of each edge
    band_b = y[h - bh:, :]
    band_r = y[:, w - bw:]
    return bool(np.percentile(band_b, 95) < body * 0.02 or np.percentile(band_r, 95) < body * 0.02)


def raw_info(raw: rawpy.RawPy) -> dict:
    wb = [float(x) for x in raw.camera_whitebalance]
    has_wb = any(x > 0 for x in wb[:3])
    return {
        **DECODER_SETTINGS,
        "camera_wb_multipliers": wb,
        "wb_source": "camera as-shot" if has_wb else "decoder default (camera WB missing)",
        "raw_type": str(raw.raw_type).split(".")[-1],
        "color_desc": raw.color_desc.decode("ascii", "replace"),
        "white_level": int(raw.white_level),
        "black_levels": [int(x) for x in raw.black_level_per_channel],
        "flip": int(raw.sizes.flip),
        "sensor_frame": [int(raw.sizes.width), int(raw.sizes.height)],
        "official_crop": list(_crop_rect(raw) or []),
        "rgb_xyz_matrix": [[round(float(v), 4) for v in row] for row in np.asarray(raw.rgb_xyz_matrix)[:3]],
    }


def _postprocess(raw: rawpy.RawPy, half: bool) -> np.ndarray:
    rgb16 = raw.postprocess(
        half_size=half,
        output_bps=16,
        gamma=(1, 1),
        no_auto_bright=True,
        output_color=rawpy.ColorSpace.ProPhoto,
        use_camera_wb=True,
        demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
        highlight_mode=rawpy.HighlightMode.Clip,
    )
    out = rgb16.astype(np.float32)
    del rgb16
    out *= 1.0 / 65535.0
    return out


def decode_raw(data: bytes, half: bool, camera_name: str = "", md=None) -> Decoded:
    raw = _open_raw(data, camera_name)
    # DNGVersion tag (50706 = 0xC612) in the first IFD: byte order depends on the file.
    is_dng = ((data[:4] == b"II*\x00" and b"\x12\xc6\x01\x00" in data[:65536]) or
              (data[:4] == b"MM\x00*" and b"\xc6\x12\x00\x01" in data[:65536]))
    try:
        if md is not None:
            from .metadata import apply_libraw_fields
            apply_libraw_fields(md, raw)
        try:
            full = _raw_full_size(raw)
            info = raw_info(raw)
            crop = _crop_rect(raw)
            known = profile_known(raw, is_dng)
            W0, H0, flip = int(raw.sizes.width), int(raw.sizes.height), int(raw.sizes.flip)
        except Exception as e:
            raise _libraw_error(e, camera_name) from e
        if full[0] * full[1] > MAX_PIXELS:
            raise DecodeError("Image is larger than the supported maximum size.")
        # Sanity check: even heavily compressed RAW data needs well over
        # 0.8 bits per pixel; a much smaller file is truncated or a stub.
        if full[0] * full[1] > 0 and len(data) < full[0] * full[1] * 0.1:
            cam = f" from {camera_name}" if camera_name and camera_name != "Unknown camera" else ""
            raise DecodeError(f"The RAW file{cam} appears to be incomplete (too small for its "
                              "image size). It may have been truncated while copying.")
        try:
            img = _postprocess(raw, half)
        except Exception as e:
            raise _libraw_error(e, camera_name) from e
    finally:
        raw.close()
    if float(img.max()) <= 1e-6:
        raise DecodeError("The RAW file decoded to an empty image; the file is probably "
                          "damaged or incomplete.")
    info["profile_known"] = known
    info["empty_border"] = _has_empty_border(img)
    log.info("decoded %s: frame %sx%s flip %s, official crop %s, colour profile %s",
             camera_name or "RAW", W0, H0, flip, crop, "known" if known else "MISSING")
    if crop is not None:
        # Keep only the camera's official image area (drops border pixels).
        fx = img.shape[1] / (H0 if flip in (5, 6) else W0)
        x, y, w, h = _rotate_rect(crop, W0, H0, flip)
        x0, y0 = int(round(x * fx)), int(round(y * fx))
        x1 = min(img.shape[1], int(round((x + w) * fx)))
        y1 = min(img.shape[0], int(round((y + h) * fx)))
        img = np.ascontiguousarray(img[y0:y1, x0:x1])
        full = (int(w), int(h))         # already in displayed (rotated) orientation
    scale = img.shape[1] / full[0]
    # A half-size LibRaw image picks (does not average) one pixel per 2x2
    # Bayer quad, so its per-pixel noise is close to full-resolution noise.
    return Decoded(img, full, scale, noise_native_scale=scale, info=info)


def extract_embedded_preview(data: bytes) -> Image.Image | None:
    """Embedded camera JPEG, oriented. Used ONLY as a labelled placeholder."""
    try:
        raw = rawpy.imread(io.BytesIO(data))
    except Exception:
        return None
    try:
        flip = raw.sizes.flip
        thumb = raw.extract_thumb()
    except Exception:
        return None
    finally:
        raw.close()
    try:
        if thumb.format == rawpy.ThumbFormat.JPEG:
            im = Image.open(io.BytesIO(thumb.data))
            im.load()
        else:
            im = Image.fromarray(thumb.data)
        im = im.convert("RGB")
    except Exception:
        return None
    if flip == 3:
        im = im.transpose(Image.Transpose.ROTATE_180)
    elif flip == 5:
        im = im.transpose(Image.Transpose.ROTATE_90)
    elif flip == 6:
        im = im.transpose(Image.Transpose.ROTATE_270)
    return im


def embedded_preview_jpeg_bytes(data: bytes) -> bytes | None:
    try:
        raw = rawpy.imread(io.BytesIO(data))
        try:
            thumb = raw.extract_thumb()
        finally:
            raw.close()
        if thumb.format == rawpy.ThumbFormat.JPEG:
            return bytes(thumb.data)
    except Exception:
        return None
    return None


# ----------------------------------------------------------------- raster

def _orient(arr: np.ndarray, orientation: int) -> np.ndarray:
    o = orientation
    if o == 2:
        return arr[:, ::-1]
    if o == 3:
        return arr[::-1, ::-1]
    if o == 4:
        return arr[::-1, :]
    if o == 5:
        return np.transpose(arr, (1, 0, 2))
    if o == 6:
        return np.rot90(arr, -1)
    if o == 7:
        return np.transpose(arr, (1, 0, 2))[::-1, ::-1]
    if o == 8:
        return np.rot90(arr, 1)
    return arr


def _encoded_to_working(enc: np.ndarray, icc_bytes: bytes | None) -> tuple[np.ndarray, str]:
    """Display-encoded RGB in [0,1] -> linear ProPhoto, honouring an ICC profile."""
    prof = parse_icc(icc_bytes) if icc_bytes else None
    if prof is not None:
        lin = prof.linearize(enc)
        m = color.XYZ_D50_TO_PROPHOTO @ prof.to_xyz_d50
        return np.clip(color.apply_matrix(lin, m), 0, None), prof.description or "embedded ICC"
    lin = color.srgb_decode(enc)
    return color.apply_matrix(lin, color.SRGB_TO_PROPHOTO), "sRGB (assumed)" if not icc_bytes else "sRGB"


def decode_jpeg(data: bytes) -> Decoded:
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:
        raise DecodeError("The JPEG file could not be read; it may be damaged.", repr(e)) from e
    im = ImageOps.exif_transpose(im)
    icc = im.info.get("icc_profile")
    if icc and parse_icc(icc) is None:
        # LUT profile: let LittleCMS convert to sRGB at 8 bits.
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            dst = ImageCms.createProfile("sRGB")
            im = ImageCms.profileToProfile(im.convert("RGB"), src, dst, outputMode="RGB")
            icc = None
        except Exception:
            icc = None
    im = im.convert("RGB")
    enc = np.asarray(im, dtype=np.float32) / 255.0
    work, space = _encoded_to_working(enc, icc)
    h, w = work.shape[:2]
    return Decoded(work, (w, h), 1.0, 1.0, {"source_color_space": space, "bit_depth": 8})


def decode_tiff(data: bytes, orientation: int) -> Decoded:
    import tifffile

    try:
        with tifffile.TiffFile(io.BytesIO(data)) as tf:
            page = tf.pages[0]
            arr = page.asarray()
            icc_tag = page.tags.get(34675)
            icc = bytes(icc_tag.value) if icc_tag is not None else None
    except Exception as e:
        # Fall back to Pillow (e.g. compression tifffile cannot decode).
        try:
            im = Image.open(io.BytesIO(data))
            im.load()
            icc = im.info.get("icc_profile")
            arr = np.asarray(im.convert("RGB"))
        except Exception:
            raise DecodeError("The TIFF file could not be read; it may be damaged or use "
                              "an unsupported compression.", repr(e)) from e
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    if arr.ndim == 3 and arr.shape[0] in (3, 4) and arr.shape[2] not in (3, 4):
        arr = np.moveaxis(arr, 0, -1)  # planar
    if arr.ndim != 3 or arr.shape[2] < 3:
        raise DecodeError("This TIFF layout (channels/pages) is not supported.")
    arr = arr[..., :3]
    if arr.dtype == np.uint8:
        enc, bits = arr.astype(np.float32) / 255.0, 8
    elif arr.dtype == np.uint16:
        enc, bits = arr.astype(np.float32) / 65535.0, 16
    elif arr.dtype in (np.float32, np.float64, np.float16):
        enc, bits = np.clip(arr.astype(np.float32), 0, 1), 32
    else:
        raise DecodeError(f"TIFF sample format {arr.dtype} is not supported.")
    if enc.shape[0] * enc.shape[1] > MAX_PIXELS:
        raise DecodeError("Image is larger than the supported maximum size.")
    enc = np.ascontiguousarray(_orient(enc, orientation))
    work, space = _encoded_to_working(enc, icc)
    h, w = work.shape[:2]
    return Decoded(work, (w, h), 1.0, 1.0, {"source_color_space": space, "bit_depth": bits})


def decode(data: bytes, sniff: Sniff, *, half: bool, orientation: int = 1,
           camera_name: str = "", md=None) -> Decoded:
    if sniff.kind == Kind.RAW:
        return decode_raw(data, half=half, camera_name=camera_name, md=md)
    if sniff.container == Container.JPEG:
        return decode_jpeg(data)
    if sniff.container == Container.TIFF:
        return decode_tiff(data, orientation)
    raise DecodeError("This file type is not supported.")
