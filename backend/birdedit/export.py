"""Full-resolution export from the original file + saved recipe.

* JPEG: 8-bit sRGB with an embedded sRGB ICC profile and EXIF.
* TIFF: 16-bit sRGB (deflate compressed) with an embedded sRGB ICC profile
  and capture metadata as XMP. The pipeline is float32 throughout, so the
  16-bit file genuinely carries more than 8 bits of tonal precision.
* GPS is stripped unless ``keep_gps`` is set. Orientation is baked into the
  pixels and written as 1 ("normal").
* Files are never overwritten: a unique name is reserved atomically first.
"""

from __future__ import annotations

import io
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape

import cv2
import numpy as np
import piexif
from PIL import Image, ImageCms

from . import __version__, color
from .metadata import CaptureMetadata
from .winpath import io_path, replace_file, reserve_unique_path

SOFTWARE = f"Bird Photo Editor {__version__}"
_SRGB_ICC: bytes | None = None


def srgb_icc() -> bytes:
    global _SRGB_ICC
    if _SRGB_ICC is None:
        _SRGB_ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    return _SRGB_ICC


@dataclass
class ExportOptions:
    folder: Path
    format: Literal["jpeg", "tiff16"] = "jpeg"
    quality: int = 92
    long_edge: int | None = None
    keep_gps: bool = False
    suffix: str = "_edited"


def validate_folder(folder: str) -> Path:
    if not folder or not isinstance(folder, str):
        raise ValueError("Choose an export folder.")
    p = Path(folder).expanduser()
    if not p.is_absolute():
        raise ValueError("The export folder must be a full path, e.g. C:\\Users\\you\\Pictures\\Edited.")
    if not os.path.isdir(io_path(p)):
        raise ValueError("The export folder does not exist.")
    try:
        fd, tmp = tempfile.mkstemp(dir=io_path(p), prefix=".birdedit-write-test-")
        os.close(fd)
        os.unlink(tmp)
    except OSError:
        raise ValueError("The export folder is not writable.") from None
    return p


def resize_linear(disp: np.ndarray, long_edge: int) -> np.ndarray:
    """Downscale in linear light (avoids darkening fine bright detail)."""
    h, w = disp.shape[:2]
    f = long_edge / max(h, w)
    if f >= 1:
        return disp
    lin = color.srgb_decode(disp)
    lin = cv2.resize(lin, (max(1, round(w * f)), max(1, round(h * f))), interpolation=cv2.INTER_AREA)
    return color.srgb_encode(lin)


# ----------------------------------------------------------------- metadata

def _rat(x: float, den: int = 100) -> tuple[int, int]:
    return (int(round(x * den)), den)


def build_exif(md: CaptureMetadata, keep_gps: bool, width: int, height: int) -> bytes:
    zeroth: dict = {piexif.ImageIFD.Software: SOFTWARE.encode(), piexif.ImageIFD.Orientation: 1}
    exif: dict = {piexif.ExifIFD.PixelXDimension: width, piexif.ExifIFD.PixelYDimension: height,
                  piexif.ExifIFD.ColorSpace: 1}
    cam = md.camera
    if cam.make_raw:
        zeroth[piexif.ImageIFD.Make] = cam.make_raw.encode("utf-8", "replace")
    if cam.model_raw:
        zeroth[piexif.ImageIFD.Model] = cam.model_raw.encode("utf-8", "replace")
    if md.artist:
        zeroth[piexif.ImageIFD.Artist] = md.artist.encode("utf-8", "replace")
    if md.copyright:
        zeroth[piexif.ImageIFD.Copyright] = md.copyright.encode("utf-8", "replace")
    if md.datetime_original:
        dt = md.datetime_original.encode("ascii", "replace")[:19]
        exif[piexif.ExifIFD.DateTimeOriginal] = dt
        zeroth[piexif.ImageIFD.DateTime] = dt
    if md.exposure_time:
        exif[piexif.ExifIFD.ExposureTime] = tuple(int(v) for v in md.exposure_time)
    if md.f_number:
        exif[piexif.ExifIFD.FNumber] = _rat(md.f_number, 10)
    if md.iso:
        exif[piexif.ExifIFD.ISOSpeedRatings] = int(min(md.iso, 65535))
    if md.focal_length:
        exif[piexif.ExifIFD.FocalLength] = _rat(md.focal_length, 10)
    if md.lens:
        exif[piexif.ExifIFD.LensModel] = md.lens.encode("utf-8", "replace")
    gps: dict = {}
    if keep_gps and md.has_gps and md.gps:
        g = md.gps
        if len(g.get("GPSLatitude", [])) == 3 and g.get("GPSLatitudeRef") in ("N", "S"):
            gps[piexif.GPSIFD.GPSLatitude] = [tuple(v) for v in g["GPSLatitude"]]
            gps[piexif.GPSIFD.GPSLatitudeRef] = g["GPSLatitudeRef"].encode()
        if len(g.get("GPSLongitude", [])) == 3 and g.get("GPSLongitudeRef") in ("E", "W"):
            gps[piexif.GPSIFD.GPSLongitude] = [tuple(v) for v in g["GPSLongitude"]]
            gps[piexif.GPSIFD.GPSLongitudeRef] = g["GPSLongitudeRef"].encode()
        if g.get("GPSAltitude"):
            gps[piexif.GPSIFD.GPSAltitude] = tuple(g["GPSAltitude"][0])
            gps[piexif.GPSIFD.GPSAltitudeRef] = int(g.get("GPSAltitudeRef", 0))
    return piexif.dump({"0th": zeroth, "Exif": exif, "GPS": gps, "1st": {}, "thumbnail": None})


def _dms_to_xmp(dms: list, ref: str) -> str:
    d, m, s = (a / b if b else 0 for a, b in dms)
    minutes = m + s / 60.0
    return f"{int(d)},{minutes:.6f}{ref}"


def build_xmp(md: CaptureMetadata, keep_gps: bool) -> bytes:
    props = []

    def add(tag: str, val: str) -> None:
        if val:
            props.append(f"   <{tag}>{escape(val)}</{tag}>")

    add("tiff:Make", md.camera.make_raw)
    add("tiff:Model", md.camera.model_raw)
    add("tiff:Orientation", "1")
    add("xmp:CreatorTool", SOFTWARE)
    if md.datetime_original:
        dt = md.datetime_original
        add("exif:DateTimeOriginal", dt[:10].replace(":", "-") + "T" + dt[11:19] if len(dt) >= 19 else dt)
    if md.exposure_time:
        add("exif:ExposureTime", f"{md.exposure_time[0]}/{md.exposure_time[1]}")
    if md.f_number:
        add("exif:FNumber", f"{int(round(md.f_number * 10))}/10")
    if md.focal_length:
        add("exif:FocalLength", f"{int(round(md.focal_length * 10))}/10")
    if md.lens:
        add("aux:Lens", md.lens)
    if md.artist:
        props.append(f"   <dc:creator><rdf:Seq><rdf:li>{escape(md.artist)}</rdf:li></rdf:Seq></dc:creator>")
    if md.iso:
        props.append(f"   <exif:ISOSpeedRatings><rdf:Seq><rdf:li>{int(md.iso)}</rdf:li></rdf:Seq></exif:ISOSpeedRatings>")
    if keep_gps and md.has_gps:
        g = md.gps
        if len(g.get("GPSLatitude", [])) == 3 and g.get("GPSLatitudeRef") in ("N", "S"):
            add("exif:GPSLatitude", _dms_to_xmp(g["GPSLatitude"], g["GPSLatitudeRef"]))
        if len(g.get("GPSLongitude", [])) == 3 and g.get("GPSLongitudeRef") in ("E", "W"):
            add("exif:GPSLongitude", _dms_to_xmp(g["GPSLongitude"], g["GPSLongitudeRef"]))
    body = "\n".join(props)
    xml = (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about=""\n'
        '    xmlns:tiff="http://ns.adobe.com/tiff/1.0/"\n'
        '    xmlns:exif="http://ns.adobe.com/exif/1.0/"\n'
        '    xmlns:aux="http://ns.adobe.com/exif/1.0/aux/"\n'
        '    xmlns:xmp="http://ns.adobe.com/xap/1.0/"\n'
        '    xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f"{body}\n"
        "  </rdf:Description>\n </rdf:RDF>\n</x:xmpmeta>\n<?xpacket end=\"w\"?>"
    )
    return xml.encode("utf-8")


# -------------------------------------------------------------------- write

def write_output(pixels: np.ndarray, md: CaptureMetadata, stem: str, opts: ExportOptions) -> Path:
    """pixels: HxWx3 uint8 (jpeg) or uint16 (tiff16), sRGB-encoded."""
    suffix = ".jpg" if opts.format == "jpeg" else ".tif"
    final = reserve_unique_path(opts.folder, f"{stem}{opts.suffix}", suffix)
    fd, tmp = tempfile.mkstemp(dir=io_path(opts.folder), prefix=".birdedit-", suffix=suffix)
    os.close(fd)
    try:
        h, w = pixels.shape[:2]
        if opts.format == "jpeg":
            im = Image.fromarray(pixels)
            q = int(np.clip(opts.quality, 50, 100))
            with open(tmp, "wb") as f:
                im.save(f, "JPEG", quality=q, subsampling=0 if q >= 90 else 2, optimize=True,
                        icc_profile=srgb_icc(), exif=build_exif(md, opts.keep_gps, w, h))
        else:
            import tifffile

            extratags = [(34675, 7, len(srgb_icc()), srgb_icc(), True),
                         (700, 1, 0, build_xmp(md, opts.keep_gps), True)]
            if md.camera.make_raw:
                extratags.append((271, "s", 0, md.camera.make_raw, True))
            if md.camera.model_raw:
                extratags.append((272, "s", 0, md.camera.model_raw, True))
            with open(tmp, "wb") as f:
                tifffile.imwrite(f, pixels, photometric="rgb", compression="zlib",
                                 software=SOFTWARE, extratags=extratags, metadata=None)
        if os.name != "nt":
            os.chmod(tmp, 0o644)            # mkstemp creates 0600 files
        replace_file(tmp, final)            # replaces only our own reserved empty file
    except BaseException:
        for p in (tmp, io_path(final)):
            try:
                if os.path.exists(p) and (p == tmp or os.path.getsize(p) == 0):
                    os.unlink(p)
            except OSError:
                pass
        raise
    return final
