"""Camera identification: normalise manufacturer names, keep raw values.

Rules (see README "How cameras are identified"):
* Make/Model come only from metadata inside the file, never from the filename.
* The original metadata strings are always kept alongside the display form.
* Recognising a camera says nothing about whether its RAW variant decodes;
  that is tracked separately (``decode_status`` in the photo record).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

# Upper-cased metadata Make prefixes -> display name.
_MAKE_ALIASES: list[tuple[str, str]] = [
    ("NIKON", "Nikon"),
    ("SONY", "Sony"),
    ("CANON", "Canon"),
    ("FUJIFILM", "Fujifilm"),
    ("FUJI PHOTO", "Fujifilm"),
    ("OLYMPUS", "Olympus"),
    ("OM DIGITAL", "OM System"),
    ("OM SYSTEM", "OM System"),
    ("PANASONIC", "Panasonic"),
    ("LEICA", "Leica"),
    ("PENTAX", "Pentax"),
    ("RICOH", "Ricoh"),
    ("SAMSUNG", "Samsung"),
    ("HASSELBLAD", "Hasselblad"),
    ("SIGMA", "Sigma"),
    ("APPLE", "Apple"),
    ("GOOGLE", "Google"),
    ("DJI", "DJI"),
    ("GOPRO", "GoPro"),
]

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def clean_metadata_string(value: object, max_len: int = 80) -> str:
    """Make an untrusted metadata value safe to display (never executed)."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    s = str(value).split("\x00", 1)[0]
    s = _CONTROL.sub("", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:max_len]


def normalize_make(make_raw: str) -> str:
    up = make_raw.upper().strip()
    if not up:
        return ""
    for prefix, display in _MAKE_ALIASES:
        if up.startswith(prefix):
            return display
    # Unfamiliar manufacturer: keep what the file says, tidied up.
    return make_raw.strip()


def normalize_model(model_raw: str, make_display: str) -> str:
    """Strip a duplicated manufacturer prefix ("NIKON Z 8" -> "Z 8").

    The model text is otherwise kept exactly as reported (e.g. Sony reports
    "ILCE-7RM5"; we do not translate it to a marketing name).
    """
    model = model_raw.strip()
    if make_display:
        for prefix in {make_display.upper(), make_display.upper().split()[0]}:
            if model.upper().startswith(prefix + " "):
                model = model[len(prefix) + 1:].strip()
                break
    return model


@dataclass(frozen=True)
class CameraInfo:
    make_raw: str = ""
    model_raw: str = ""
    make: str = ""             # normalised display manufacturer
    model: str = ""            # display model (exact reported model text)
    source: str = ""           # which metadata block supplied it

    @property
    def identified(self) -> bool:
        return bool(self.make or self.model)

    @property
    def display_name(self) -> str:
        if not self.identified:
            return "Unknown camera"
        if self.make and self.model:
            return f"{self.make} {self.model}"
        return self.make or self.model

    def to_dict(self) -> dict:
        d = asdict(self)
        d["identified"] = self.identified
        d["display_name"] = self.display_name
        return d


def camera_from_strings(make: object, model: object, source: str) -> CameraInfo:
    make_raw = clean_metadata_string(make)
    model_raw = clean_metadata_string(model)
    make_disp = normalize_make(make_raw)
    model_disp = normalize_model(model_raw, make_disp)
    if not (make_raw or model_raw):
        return CameraInfo(source="")
    return CameraInfo(make_raw, model_raw, make_disp, model_disp, source)
