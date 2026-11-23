"""Read capture metadata from file *content*.

Primary source: EXIF/TIFF tags parsed with ExifRead (pure Python, works for
JPEG, TIFF and TIFF-based RAW files such as NEF, NRW, ARW, DNG, CR2, ORF, RW2).
Fallbacks that also read real file content:

* Canon CR3: the CMT1/CMT2 boxes inside the ISO-BMFF container hold TIFF IFDs.
* Fujifilm RAF: the header stores the model; the embedded JPEG holds EXIF.
* Any RAW: EXIF of the embedded preview JPEG, and LibRaw's own fields
  (ISO, shutter, aperture, focal length, lens) when the decoder can open it.

All values are treated as untrusted display text.
"""

from __future__ import annotations

import io
import logging
import struct
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from typing import Any

import exifread

from .camera import CameraInfo, camera_from_strings, clean_metadata_string
from .formats import Container

logging.getLogger("exifread").setLevel(logging.CRITICAL)
log = logging.getLogger(__name__)

Rational = tuple[int, int]


@dataclass
class CaptureMetadata:
    camera: CameraInfo = field(default_factory=CameraInfo)
    lens: str = ""
    iso: float | None = None
    exposure_time: Rational | None = None     # seconds as (num, den)
    f_number: float | None = None
    focal_length: float | None = None
    datetime_original: str = ""
    orientation: int = 1
    artist: str = ""
    copyright: str = ""
    has_gps: bool = False
    gps: dict[str, Any] = field(default_factory=dict)  # raw rationals, for opt-in export

    def to_dict(self) -> dict:
        d = asdict(self)
        d["camera"] = self.camera.to_dict()
        d["shutter_display"] = format_shutter(self.exposure_time)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CaptureMetadata":
        cam = d.get("camera") or {}
        camera = CameraInfo(
            cam.get("make_raw", ""), cam.get("model_raw", ""),
            cam.get("make", ""), cam.get("model", ""), cam.get("source", ""),
        )
        et = d.get("exposure_time")
        return cls(
            camera=camera, lens=d.get("lens", ""), iso=d.get("iso"),
            exposure_time=tuple(et) if et else None, f_number=d.get("f_number"),
            focal_length=d.get("focal_length"),
            datetime_original=d.get("datetime_original", ""),
            orientation=int(d.get("orientation") or 1), artist=d.get("artist", ""),
            copyright=d.get("copyright", ""), has_gps=bool(d.get("has_gps")),
            gps=d.get("gps") or {},
        )


def format_shutter(et: Rational | None) -> str:
    if not et or et[1] == 0:
        return ""
    v = et[0] / et[1]
    if v <= 0:
        return ""
    if v >= 1:
        return f"{v:g} s"
    return f"1/{round(1 / v)} s"


# ---------------------------------------------------------------- helpers

def _first(tag: Any) -> Any:
    if tag is None:
        return None
    vals = getattr(tag, "values", tag)
    if isinstance(vals, (list, tuple)):
        return vals[0] if vals else None
    return vals


def _to_float(v: Any) -> float | None:
    v = _first(v)
    if v is None:
        return None
    try:
        if hasattr(v, "num") and hasattr(v, "den"):
            return float(v.num) / float(v.den) if v.den else None
        return float(v)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _to_rational(v: Any) -> Rational | None:
    v = _first(v)
    if v is None:
        return None
    if hasattr(v, "num") and hasattr(v, "den"):
        if v.den == 0:
            return None
        return (int(v.num), int(v.den))
    try:
        fr = Fraction(float(v)).limit_denominator(100000)
        return (fr.numerator, fr.denominator)
    except (TypeError, ValueError):
        return None


def _rational_list(tag: Any) -> list[Rational]:
    out = []
    for v in getattr(tag, "values", []) or []:
        if hasattr(v, "num"):
            out.append((int(v.num), int(v.den)))
        else:
            try:
                out.append((int(v), 1))
            except (TypeError, ValueError):
                pass
    return out


def _str(tag: Any) -> str:
    if tag is None:
        return ""
    vals = getattr(tag, "values", None)
    if isinstance(vals, str):
        return clean_metadata_string(vals)
    if isinstance(vals, (bytes, bytearray)):
        return clean_metadata_string(bytes(vals))
    return clean_metadata_string(str(tag))


def _exif_tags(data: bytes) -> dict:
    try:
        return exifread.process_file(io.BytesIO(data), details=False) or {}
    except Exception:  # malformed metadata must never crash an import
        log.debug("exifread failed", exc_info=True)
        return {}


def _apply_tags(md: CaptureMetadata, tags: dict, source: str) -> None:
    if not tags:
        return
    # Canon CR3 stores the EXIF and GPS blocks as separate TIFF structures, so
    # ExifRead labels their tags "Image X" instead of "EXIF X" / "GPS X".
    tags = dict(tags)
    for k in list(tags):
        if k.startswith("Image "):
            name = k[6:]
            if name.startswith("GPS"):
                tags.setdefault(f"GPS {name}", tags[k])
            else:
                tags.setdefault(f"EXIF {name}", tags[k])
    if not md.camera.identified:
        cam = camera_from_strings(_str(tags.get("Image Make")), _str(tags.get("Image Model")), source)
        if cam.identified:
            md.camera = cam
    if not md.lens:
        md.lens = _str(tags.get("EXIF LensModel"))
        if md.lens and not any(ch.isalnum() for ch in md.lens):
            md.lens = ""
    if md.iso is None:
        md.iso = _to_float(tags.get("EXIF ISOSpeedRatings") or tags.get("EXIF PhotographicSensitivity"))
    if md.exposure_time is None:
        md.exposure_time = _to_rational(tags.get("EXIF ExposureTime"))
    if md.f_number is None:
        md.f_number = _to_float(tags.get("EXIF FNumber"))
    if md.focal_length is None:
        md.focal_length = _to_float(tags.get("EXIF FocalLength"))
    if not md.datetime_original:
        md.datetime_original = _str(tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime"))
    o = tags.get("Image Orientation")
    if o is not None and md.orientation == 1:
        try:
            val = int(_first(o))
            if 1 <= val <= 8:
                md.orientation = val
        except (TypeError, ValueError):
            pass
    if not md.artist:
        md.artist = _str(tags.get("Image Artist"))
    if not md.copyright:
        md.copyright = _str(tags.get("Image Copyright"))
    gps_keys = [k for k in tags if k.startswith("GPS ")]
    if gps_keys and not md.has_gps:
        gps: dict[str, Any] = {}
        for key in ("GPSLatitude", "GPSLongitude", "GPSAltitude"):
            t = tags.get(f"GPS {key}")
            if t is not None:
                gps[key] = _rational_list(t)
        for key in ("GPSLatitudeRef", "GPSLongitudeRef"):
            t = tags.get(f"GPS {key}")
            if t is not None:
                gps[key] = _str(t)[:1]
        t = tags.get("GPS GPSAltitudeRef")
        if t is not None:
            try:
                gps["GPSAltitudeRef"] = int(_first(t))
            except (TypeError, ValueError):
                pass
        if gps.get("GPSLatitude") or gps.get("GPSLongitude"):
            md.has_gps = True
            md.gps = gps


# ------------------------------------------------------- container parsers

def _iter_boxes(buf: bytes, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        size, btype = struct.unpack(">I4s", buf[pos:pos + 8])
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack(">Q", buf[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            return
        yield btype, pos + header, pos + size
        pos += size


_CANON_UUID = bytes.fromhex("85c0b687820f11e08111f4ce462b6a48")


def cr3_tiff_blocks(buf: bytes) -> list[bytes]:
    """Return the CMT1..CMT4 TIFF blocks from a Canon CR3 file."""
    blocks: list[bytes] = []
    for btype, s, e in _iter_boxes(buf, 0, len(buf)):
        if btype != b"moov":
            continue
        for b2, s2, e2 in _iter_boxes(buf, s, e):
            if b2 == b"uuid" and buf[s2:s2 + 16] == _CANON_UUID:
                for b3, s3, e3 in _iter_boxes(buf, s2 + 16, e2):
                    if b3 in (b"CMT1", b"CMT2", b"CMT3", b"CMT4"):
                        blocks.append(buf[s3:e3])
    return blocks


def raf_model_and_jpeg(buf: bytes) -> tuple[str, bytes | None]:
    if len(buf) < 0x5C or not buf.startswith(b"FUJIFILMCCD-RAW"):
        return "", None
    model = clean_metadata_string(buf[0x1C:0x1C + 32])
    off, length = struct.unpack(">II", buf[0x54:0x5C])
    jpeg = buf[off:off + length] if 0 < off < len(buf) and length > 0 else None
    return model, jpeg


# ------------------------------------------------------------- public API

def read_metadata(data: bytes, container: Container, thumb_jpeg: bytes | None = None) -> CaptureMetadata:
    md = CaptureMetadata()
    if container in (Container.JPEG, Container.TIFF, Container.ORF, Container.RW2):
        _apply_tags(md, _exif_tags(data), "EXIF")
    elif container == Container.CR3:
        for block in cr3_tiff_blocks(data):
            _apply_tags(md, _exif_tags(block), "CR3 metadata")
    elif container == Container.RAF:
        model, jpeg = raf_model_and_jpeg(data)
        if jpeg:
            _apply_tags(md, _exif_tags(jpeg), "RAF embedded EXIF")
        if not md.camera.identified and model:
            md.camera = camera_from_strings("FUJIFILM", model, "RAF header")
    if thumb_jpeg:
        _apply_tags(md, _exif_tags(thumb_jpeg), "embedded preview EXIF")
    return md


def apply_libraw_fields(md: CaptureMetadata, raw: Any) -> None:
    """Fill gaps from LibRaw's parsed fields (it reads maker notes too)."""
    try:
        other = raw.other
        if md.iso is None and other.iso_speed:
            md.iso = float(other.iso_speed)
        if md.exposure_time is None and other.shutter_speed:
            fr = Fraction(float(other.shutter_speed)).limit_denominator(64000)
            md.exposure_time = (fr.numerator, fr.denominator)
        if md.f_number is None and other.aperture:
            md.f_number = round(float(other.aperture), 1)
        if md.focal_length is None and other.focal_length:
            md.focal_length = float(other.focal_length)
        if not md.datetime_original and other.timestamp:
            md.datetime_original = other.timestamp.strftime("%Y:%m:%d %H:%M:%S")
    except Exception:
        log.debug("LibRaw 'other' unavailable", exc_info=True)
    try:
        lens = raw.lens
        if not md.lens and lens.model:
            md.lens = clean_metadata_string(lens.model)
    except Exception:
        log.debug("LibRaw 'lens' unavailable", exc_info=True)
