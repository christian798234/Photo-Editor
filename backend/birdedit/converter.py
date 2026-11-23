"""Optional RAW -> DNG conversion with the free Adobe DNG Converter.

Some RAW variants cannot be decoded by any free decoder. The important case
for bird photographers is Nikon's "High Efficiency" / "High Efficiency*" NEF
(Z8, Z9, Z6III, Zf, Z50II ...), which uses the licensed intoPIX TicoRAW codec.
Adobe licenses that codec, and its free DNG Converter can turn such files into
standard DNGs, which LibRaw decodes normally.

If the converter is installed, Bird Photo Editor runs it automatically for
files LibRaw cannot read. The original file is only read; the DNG is written
to the app's own cache folder. Nothing is downloaded or uploaded by the app.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

DOWNLOAD_PAGE = "https://helpx.adobe.com/camera-raw/using/adobe-dng-converter.html"
EXE_NAME = "Adobe DNG Converter.exe"


class ConversionError(Exception):
    pass


def is_nikon_high_efficiency(data: bytes) -> bool:
    """Nikon HE/HE* NEFs store the image as TicoRAW (JPEG XS based) data,
    which carries the intoPIX contact marker right after the codestream start."""
    i = data.find(b"CONTACT_INTOPIX")
    return i > 0 and data.rfind(b"\xff\x10\xff\x50", max(0, i - 64), i) >= 0


def find_dng_converter() -> Path | None:
    override = os.environ.get("BIRDEDIT_DNG_CONVERTER")
    if override:
        p = Path(override)
        return p if p.is_file() else None
    if sys.platform != "win32":
        return None
    roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
             os.environ.get("ProgramW6432"),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")]
    for root in roots:
        if not root:
            continue
        p = Path(root) / "Adobe" / "Adobe DNG Converter" / EXE_NAME
        if p.is_file():
            return p
    return None


def convert_to_dng(src: Path, out_dir: Path, exe: Path | None = None, timeout: int = 300) -> Path:
    """Convert ``src`` into ``out_dir/converted.dng`` (lossless, no preview)."""
    exe = exe or find_dng_converter()
    if exe is None:
        raise ConversionError("Adobe DNG Converter is not installed.")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "converted.dng"
    if out.exists():
        out.unlink()
    cmd = [str(exe), "-c", "-p0", "-d", str(out_dir), "-o", out.name, str(src)]
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000    # CREATE_NO_WINDOW
    log.info("converting with Adobe DNG Converter: %s", src.name)
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, shell=False, **kwargs)
    except subprocess.TimeoutExpired:
        raise ConversionError("Adobe DNG Converter took too long.") from None
    except OSError as e:
        raise ConversionError(f"Adobe DNG Converter could not be started ({e}).") from None
    if not out.is_file() or out.stat().st_size == 0:
        detail = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace")[-300:]
        raise ConversionError(f"Adobe DNG Converter did not produce a DNG (exit code {proc.returncode}). {detail}".strip())
    return out
