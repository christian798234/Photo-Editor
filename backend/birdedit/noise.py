"""Signal-dependent noise model estimated from the image itself.

Model: sigma_lin(Y) = sqrt(a*Y + b) in linear working-space luminance units
(the classic Poisson-Gaussian sensor model), at the decoder's native pixel
scale. Estimation (Immerkaer's fast noise estimator on 8x8 blocks):

1. Laplacian-difference residual of the luminance.
2. Per block: mean signal and residual-based sigma.
3. Group blocks by brightness; the 10th-percentile sigma per group comes from
   flat blocks (texture and edges inflate the others).
4. Weighted least squares for a, b >= 0.

ISO is used only as a fallback prior when too few flat areas exist.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np

from .color import luminance

_K = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float32)
_FACTOR = np.sqrt(np.pi / 2.0) / 6.0
_LOW_PERCENTILE_BIAS = 1.12      # 10th percentile of block sigmas ~ 0.89 * true


@dataclass
class NoiseModel:
    a: float
    b: float
    native_scale: float          # image px per full-res px where this applies
    method: str                  # "measured" or "iso-fallback"
    bins: int = 0

    def sigma(self, y: np.ndarray | float) -> np.ndarray | float:
        return np.sqrt(np.maximum(self.a * np.asarray(y) + self.b, 0.0))

    def scale_factor(self, render_scale: float) -> float:
        """Noise shrinks roughly linearly with downscaling (area averaging)."""
        if render_scale >= self.native_scale:
            return 1.0
        return render_scale / self.native_scale

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "NoiseModel":
        return cls(**d)


def iso_prior(iso: float | None, native_scale: float) -> NoiseModel:
    iso = float(iso) if iso and iso > 0 else 400.0
    rel = 0.005 * np.sqrt(iso / 100.0)        # ~0.5% at mid-grey for ISO 100
    a = (rel ** 2) * 0.18
    return NoiseModel(a=float(a), b=float(a * 0.002), native_scale=native_scale,
                      method="iso-fallback")


def estimate(lin: np.ndarray, native_scale: float, iso: float | None) -> NoiseModel:
    y = luminance(lin).astype(np.float32)
    # Bound the work: analyse at most ~6 MP from the centre outward.
    h, w = y.shape
    max_px = 6_000_000
    if h * w > max_px:
        f = np.sqrt(max_px / (h * w))
        ch, cw = int(h * f), int(w * f)
        y0, x0 = (h - ch) // 2, (w - cw) // 2
        y = y[y0:y0 + ch, x0:x0 + cw]
        h, w = y.shape
    bs = 8
    h8, w8 = (h // bs) * bs, (w // bs) * bs
    if h8 < 64 or w8 < 64:
        return iso_prior(iso, native_scale)
    resid = np.abs(cv2.filter2D(y, -1, _K, borderType=cv2.BORDER_REFLECT))[:h8, :w8]
    yy = y[:h8, :w8]
    bm = yy.reshape(h8 // bs, bs, w8 // bs, bs).mean(axis=(1, 3))
    bmax = yy.reshape(h8 // bs, bs, w8 // bs, bs).max(axis=(1, 3))
    br = resid.reshape(h8 // bs, bs, w8 // bs, bs).mean(axis=(1, 3)) * _FACTOR
    ok = (bmax < 0.97) & (bm > 1e-4)
    bm, br = bm[ok], br[ok]
    if bm.size < 200:
        return iso_prior(iso, native_scale)
    edges = np.geomspace(1e-4, 1.0, 17)
    xs, ys, ws = [], [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = (bm >= lo) & (bm < hi)
        n = int(sel.sum())
        if n < 30:
            continue
        s = float(np.percentile(br[sel], 10)) * _LOW_PERCENTILE_BIAS
        xs.append(float(np.median(bm[sel])))
        ys.append(s * s)
        ws.append(np.sqrt(n))
    if len(xs) < 3:
        return iso_prior(iso, native_scale)
    X = np.array(xs)
    V = np.array(ys)
    W = np.array(ws) / np.maximum(V, 1e-12)      # relative-error weighting
    A = np.stack([X, np.ones_like(X)], axis=1) * W[:, None]
    sol, *_ = np.linalg.lstsq(A, V * W, rcond=None)
    a, b = float(sol[0]), float(sol[1])
    if a < 0:
        a, b = 0.0, float(np.average(V, weights=W))
    if b < 0:
        b = 0.0
        a = float(np.sum(W * W * X * V) / max(np.sum(W * W * X * X), 1e-20))
    return NoiseModel(a=a, b=b, native_scale=native_scale, method="measured", bins=len(xs))
