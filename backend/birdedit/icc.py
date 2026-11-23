"""Minimal reader for matrix/TRC ICC profiles (sRGB, Adobe RGB, ProPhoto,
Display P3 ... as embedded by cameras and editors).

It extracts the rXYZ/gXYZ/bXYZ colourants and r/g/bTRC curves so a JPEG or
TIFF can be converted to the linear ProPhoto working space at full precision.
LUT-based profiles are not handled here; the caller falls back to LittleCMS
(Pillow ImageCms) at 8 bits, or assumes sRGB if that also fails.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np


@dataclass
class MatrixTrcProfile:
    description: str
    to_xyz_d50: np.ndarray          # 3x3, columns = r, g, b colourants
    trcs: list                      # per channel: callable(enc)->lin

    def linearize(self, enc: np.ndarray) -> np.ndarray:
        out = np.empty_like(enc, dtype=np.float32)
        for c in range(3):
            out[..., c] = self.trcs[c](enc[..., c])
        return out


def _s15f16(b: bytes) -> float:
    return struct.unpack(">i", b)[0] / 65536.0


def _parse_curve(data: bytes):
    sig = data[:4]
    if sig == b"curv":
        n = struct.unpack(">I", data[8:12])[0]
        if n == 0:
            return lambda x: x.astype(np.float32)
        if n == 1:
            g = struct.unpack(">H", data[12:14])[0] / 256.0
            return lambda x, g=g: np.power(np.clip(x, 0, 1), g).astype(np.float32)
        table = np.frombuffer(data[12:12 + 2 * n], dtype=">u2").astype(np.float32) / 65535.0
        xs = np.linspace(0, 1, n, dtype=np.float32)
        return lambda x, xs=xs, t=table: np.interp(np.clip(x, 0, 1), xs, t).astype(np.float32)
    if sig == b"para":
        ftype = struct.unpack(">H", data[8:10])[0]
        nparams = {0: 1, 1: 3, 2: 4, 3: 5, 4: 7}.get(ftype)
        if nparams is None:
            raise ValueError("unknown parametric curve")
        p = [_s15f16(data[12 + 4 * i:16 + 4 * i]) for i in range(nparams)]
        g = p[0]
        a, b, c, d, e, f = (p + [1, 0, 0, 0, 0, 0])[1:7] if nparams > 1 else (1, 0, 0, 0, 0, 0)

        def curve(x, ftype=ftype, g=g, a=a, b=b, c=c, d=d, e=e, f=f):
            x = np.clip(x, 0, 1).astype(np.float32)
            if ftype == 0:
                return np.power(x, g)
            if ftype == 1:
                return np.where(x >= -b / a, np.power(np.maximum(a * x + b, 0), g), 0).astype(np.float32)
            if ftype == 2:
                return np.where(x >= -b / a, np.power(np.maximum(a * x + b, 0), g) + c, c).astype(np.float32)
            if ftype == 3:
                return np.where(x >= d, np.power(np.maximum(a * x + b, 0), g), c * x).astype(np.float32)
            return np.where(x >= d, np.power(np.maximum(a * x + b, 0), g) + e, c * x + f).astype(np.float32)

        return curve
    raise ValueError("unsupported curve type")


def parse_icc(profile: bytes) -> MatrixTrcProfile | None:
    try:
        if len(profile) < 132 or profile[36:40] != b"acsp":
            return None
        if profile[16:20] != b"RGB ":
            return None
        count = struct.unpack(">I", profile[128:132])[0]
        tags = {}
        for i in range(min(count, 200)):
            off = 132 + 12 * i
            sig, toff, tlen = struct.unpack(">4sII", profile[off:off + 12])
            tags[sig] = profile[toff:toff + tlen]
        cols = []
        for key in (b"rXYZ", b"gXYZ", b"bXYZ"):
            d = tags[key]
            if d[:4] != b"XYZ ":
                return None
            cols.append([_s15f16(d[8 + 4 * k:12 + 4 * k]) for k in range(3)])
        m = np.array(cols, dtype=np.float64).T
        trcs = [_parse_curve(tags[k]) for k in (b"rTRC", b"gTRC", b"bTRC")]
        desc = ""
        dd = tags.get(b"desc", b"")
        if dd[:4] == b"desc":
            n = struct.unpack(">I", dd[8:12])[0]
            desc = dd[12:12 + n].split(b"\x00")[0].decode("latin-1", "replace")
        elif dd[:4] == b"mluc":
            n_rec = struct.unpack(">I", dd[8:12])[0]
            if n_rec:
                ln, lo = struct.unpack(">II", dd[20:28])
                desc = dd[lo:lo + ln].decode("utf-16-be", "replace")
        return MatrixTrcProfile(desc.strip()[:80], m, trcs)
    except (KeyError, ValueError, struct.error):
        return None
