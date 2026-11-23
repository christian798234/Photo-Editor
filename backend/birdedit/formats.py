"""Identify what a file really is from its bytes, not its extension.

The extension is used only as a *hint* to distinguish formats that share a
container (e.g. NEF, ARW, DNG and plain TIFF are all TIFF structures).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

RAW_EXTENSIONS = {
    ".nef", ".nrw", ".arw", ".srf", ".sr2", ".cr2", ".cr3", ".crw", ".raf",
    ".orf", ".rw2", ".dng", ".pef", ".srw", ".x3f", ".3fr", ".iiq", ".rwl", ".erf",
}
RASTER_EXTENSIONS = {".jpg", ".jpeg", ".jpe", ".tif", ".tiff"}
SUPPORTED_EXTENSIONS = RAW_EXTENSIONS | RASTER_EXTENSIONS


class Container(str, Enum):
    JPEG = "jpeg"
    TIFF = "tiff"          # TIFF structure: plain TIFF or TIFF-based RAW
    ORF = "orf"            # Olympus TIFF variant (IIRO / IIRS / MMOR)
    RW2 = "rw2"            # Panasonic TIFF variant (IIU)
    RAF = "raf"            # Fujifilm
    CR3 = "cr3"            # Canon ISO-BMFF
    CRW = "crw"            # Canon CIFF
    X3F = "x3f"            # Sigma
    UNKNOWN = "unknown"


class Kind(str, Enum):
    RAW = "raw"
    RASTER = "raster"      # JPEG / TIFF
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class Sniff:
    container: Container
    kind: Kind
    note: str = ""          # explanation when extension and content disagree


def sniff_container(head: bytes) -> Container:
    if head[:3] == b"\xff\xd8\xff":
        return Container.JPEG
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return Container.TIFF
    if head[:4] in (b"IIRO", b"IIRS", b"MMOR"):
        return Container.ORF
    if head[:4] == b"IIU\x00":
        return Container.RW2
    if head[:15] == b"FUJIFILMCCD-RAW":
        return Container.RAF
    if head[4:8] == b"ftyp" and head[8:12] == b"crx ":
        return Container.CR3
    if head[:2] == b"II" and head[6:14] == b"HEAPCCDR":
        return Container.CRW
    if head[:4] == b"FOVb":
        return Container.X3F
    return Container.UNKNOWN


def classify(head: bytes, extension: str) -> Sniff:
    ext = extension.lower()
    c = sniff_container(head)
    if c == Container.JPEG:
        note = "" if ext in {".jpg", ".jpeg", ".jpe"} else (
            f"File is named '{ext}' but its content is a JPEG; it was opened as a JPEG."
        )
        return Sniff(c, Kind.RASTER, note)
    if c == Container.TIFF:
        if ext in {".tif", ".tiff"}:
            return Sniff(c, Kind.RASTER)
        if ext in RAW_EXTENSIONS:
            return Sniff(c, Kind.RAW)
        return Sniff(c, Kind.UNSUPPORTED, "TIFF-structured file with an unrecognised extension.")
    if c in (Container.ORF, Container.RW2, Container.RAF, Container.CR3,
             Container.CRW, Container.X3F):
        note = "" if ext in RAW_EXTENSIONS else (
            f"File content looks like a {c.value.upper()} RAW file; opened as RAW."
        )
        return Sniff(c, Kind.RAW, note)
    return Sniff(c, Kind.UNSUPPORTED, "The file content is not a recognised image or RAW format.")
