"""The rendering pipeline.  Order of operations (all float32):

  linear ProPhoto (decoder, camera WB)
   1. white balance refinement   (warmth / tint gains, luminance-neutral)
   2. exposure + tone curve      (one luminance LUT: black point, highlight
                                  shoulder, shadows, contrast; applied as a
                                  ratio so hue and saturation are preserved)
   3. colour intensity           (vibrance-style, protects saturated colours)
   4. gamut map -> linear sRGB   (luminance-preserving desaturation)
   5. sRGB transfer curve        (display-encoded)
   6. noise reduction            (Laplacian-pyramid shrinkage in Y/Cb/Cr,
                                  thresholds from the measured noise model)
   7. sharpening / clarity       (noise-gated unsharp mask with overshoot
                                  clamping; edge-aware local contrast)
  -> display/export sRGB

Every step is either per-pixel with global parameters or a local filter with
bounded support, so a tile rendered with enough padding is identical to the
same region of a full render (this is how 100% view and export work).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from . import color
from .noise import NoiseModel
from .recipe import Effective

PYR_ALIGN = 64            # tile origins must be multiples of this


# ------------------------------------------------------------- tone curve

_SHADOW_PEAK = (0.2727 ** 1.5) * (0.7273 ** 4)


def _smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def tone_display(d: np.ndarray, eff: Effective) -> np.ndarray:
    """Tone curve in the sRGB-encoded domain. Identity (with clip at 1)
    when every parameter is zero, so the baseline is plain decoder + sRGB."""
    d = d.astype(np.float64)
    b = eff.black / 100.0
    if b > 0:
        d = np.maximum((d - b) / (1.0 - b), 0.0)
    h = float(np.clip(eff.highlights / 100.0, -1.0, 1.0))
    if h < 0:
        a = -h
        k = 1.0 - 0.45 * a
        dmax = float(color.srgb_encode(np.array([2.0 ** (2.0 * a)], np.float32))[0])
        xm = (dmax - k) / (1.0 - k)
        if xm > 1.0001:
            wv = xm / (xm - 1.0)
            x = np.maximum((d - k) / (1.0 - k), 0.0)
            d = np.where(d > k, k + (1.0 - k) * (x / (1.0 + x / wv)), d)
    elif h > 0:
        dc = np.clip(d, 0.0, 1.0)
        d = d + h * 0.12 * _smoothstep(0.4, 0.9, dc) * (1.0 - dc)
    d = np.clip(d, 0.0, 1.0)
    s = float(np.clip(eff.shadows / 100.0, -1.0, 1.0))
    if s != 0:
        amp = s * (0.12 if s > 0 else 0.08)
        d = d + amp * (np.power(d, 1.5) * np.power(1.0 - d, 4)) / _SHADOW_PEAK
    c = float(np.clip(eff.contrast / 100.0, -0.3, 0.4))
    if c != 0:
        d = d + c * 2.0 * d * (1.0 - d) * (2.0 * d - 1.0)
    return np.clip(d, 0.0, 1.0)


def wb_gains(eff: Effective) -> np.ndarray:
    w = float(np.clip(eff.warmth, -150, 150)) / 100.0
    t = float(np.clip(eff.tint, -150, 150)) / 100.0
    g = np.array([2.0 ** (0.5 * w), 2.0 ** (-0.3 * t), 2.0 ** (-0.5 * w)])
    return g / float(g @ color.PROPHOTO_LUMA)


@dataclass
class ToneLUT:
    grid: np.ndarray       # encoded input luminance (pre-exposure), 0..D_MAX
    mult: np.ndarray       # linear multiplier Y_out / Y_in
    dout_dy: np.ndarray    # derivative of display output wrt linear input

    D_MAX = 1.6

    def lookup(self, d0: np.ndarray, table: np.ndarray) -> np.ndarray:
        """Fast linear interpolation on the uniform grid (d0 in [0, D_MAX])."""
        n = len(self.grid)
        t = np.clip(d0, 0.0, self.D_MAX).astype(np.float32) * np.float32((n - 1) / self.D_MAX)
        i = np.minimum(t.astype(np.int32), n - 2)
        frac = t - i
        tab = table.astype(np.float32)
        return tab[i] * (1.0 - frac) + tab[i + 1] * frac


def build_tone_lut(eff: Effective, n: int = 4096) -> ToneLUT:
    grid = np.linspace(0.0, ToneLUT.D_MAX, n)
    y0 = color.srgb_decode(grid.astype(np.float32)).astype(np.float64)
    gain = 2.0 ** float(np.clip(eff.exposure, -5, 5))
    d_in = color.srgb_encode((y0 * gain).astype(np.float32)).astype(np.float64)
    d_out = tone_display(d_in, eff)
    y_out = color.srgb_decode(d_out.astype(np.float32)).astype(np.float64)
    mult = np.empty_like(y0)
    mult[1:] = y_out[1:] / np.maximum(y0[1:], 1e-12)
    mult[0] = mult[1]
    dd = np.gradient(d_out, y0, edge_order=1)
    dd = np.nan_to_num(np.maximum(dd, 0.0), nan=0.0, posinf=0.0)
    return ToneLUT(grid, mult, dd)


# --------------------------------------------------------- noise reduction

def _band_noise_constants(levels: int = 7) -> np.ndarray:
    rng = np.random.default_rng(1234)
    n = rng.standard_normal((2048, 2048)).astype(np.float32)
    g = n
    out = []
    for _ in range(levels):
        down = cv2.pyrDown(g)
        up = cv2.pyrUp(down, dstsize=(g.shape[1], g.shape[0]))
        band = (g - up)[4:-4, 4:-4]
        out.append(float(band.std()))
        g = down
    return np.array(out, dtype=np.float32)


BAND_NOISE = _band_noise_constants()


def _shrink_pyramid(ch: np.ndarray, sigma: np.ndarray, k: float, levels: int,
                    keep: float, level_gain: np.ndarray) -> np.ndarray:
    gs = [ch]
    sg = [sigma]
    for _ in range(levels):
        gs.append(cv2.pyrDown(gs[-1]))
        # sigma map resampled to each level; BAND_NOISE already accounts for
        # how much level-0 white noise survives into band i.
        sg.append(cv2.pyrDown(sg[-1]))
    out = gs[-1]
    for i in range(levels - 1, -1, -1):
        size = (gs[i].shape[1], gs[i].shape[0])
        lap = gs[i] - cv2.pyrUp(gs[i + 1], dstsize=size)
        t = k * level_gain[i] * BAND_NOISE[min(i, len(BAND_NOISE) - 1)] * sg[i]
        t2 = t * t
        # Non-negative garrote: strong edges kept almost unchanged.
        shr = lap * np.maximum(0.0, 1.0 - t2 / np.maximum(lap * lap, 1e-12))
        lap = shr + keep * (lap - shr)
        out = cv2.pyrUp(out, dstsize=size) + lap
    return out


def denoise(disp: np.ndarray, sigma_map: np.ndarray, strength: float) -> np.ndarray:
    """strength: 0..1.5 (slider/100). sigma_map: expected luminance noise std
    in display units at this render scale."""
    if strength <= 0:
        return disp
    r, g, b = disp[..., 0], disp[..., 1], disp[..., 2]
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = b - y
    cr = r - y
    k_l = 1.6 * strength
    k_c = 2.0 + 2.5 * strength
    luma_gain = np.array([1.0, 0.9, 0.7, 0.5, 0.3], np.float32)
    chroma_gain = np.array([1.0, 1.0, 1.0, 0.9, 0.8, 0.6], np.float32)
    y = _shrink_pyramid(y, sigma_map, k_l, 5, keep=0.18, level_gain=luma_gain)
    # Chroma noise (in Cb/Cr difference units) is comparable to luma noise.
    cb = _shrink_pyramid(cb, sigma_map, k_c, 6, keep=0.0, level_gain=chroma_gain)
    cr = _shrink_pyramid(cr, sigma_map, k_c, 6, keep=0.0, level_gain=chroma_gain)
    return _ycc_to_rgb(y, cb, cr)


def _ycc_to_rgb(y, cb, cr) -> np.ndarray:
    r = y + cr
    b = y + cb
    g = (y - 0.299 * r - 0.114 * b) / 0.587
    return np.clip(np.stack([r, g, b], axis=-1), 0.0, 1.0).astype(np.float32)


# --------------------------------------------------------------- detail

def _guided(I: np.ndarray, r: int, eps: float) -> np.ndarray:
    ksize = (2 * r + 1, 2 * r + 1)
    mean_i = cv2.boxFilter(I, -1, ksize, borderType=cv2.BORDER_REFLECT)
    mean_ii = cv2.boxFilter(I * I, -1, ksize, borderType=cv2.BORDER_REFLECT)
    var = mean_ii - mean_i * mean_i
    a = var / (var + eps)
    bb = mean_i - a * mean_i
    mean_a = cv2.boxFilter(a, -1, ksize, borderType=cv2.BORDER_REFLECT)
    mean_b = cv2.boxFilter(bb, -1, ksize, borderType=cv2.BORDER_REFLECT)
    return mean_a * I + mean_b


def sharpen_and_clarity(disp: np.ndarray, sigma_map: np.ndarray, detail: float,
                        clarity: float, scale: float, nr_strength: float) -> np.ndarray:
    if detail <= 0 and clarity <= 0:
        return disp
    r, g, b = disp[..., 0], disp[..., 1], disp[..., 2]
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb, cr = b - y, r - y
    y_new = y
    if clarity > 0:
        rad = max(2, int(round(24 * scale)))
        base = _guided(y, rad, 0.004)
        mid = 4.0 * y * (1.0 - y)                    # protect highlights/shadows
        y_new = y_new + (clarity / 100.0) * 1.2 * mid * (y - base)
    if detail > 0:
        radius = max(0.5, 0.9 * scale)
        amount = (detail / 100.0) * 1.4 * min(1.0, 0.35 + 0.65 * min(scale, 1.0))
        blur = cv2.GaussianBlur(y, (0, 0), radius, borderType=cv2.BORDER_REFLECT)
        det = y - blur
        resid = sigma_map * (1.0 - 0.6 * min(nr_strength, 1.0))
        t = 1.5 * resid + 1e-4
        gate = np.clip((np.abs(det) - t) / t, 0.0, 1.0)
        y_new = y_new + amount * gate * det
    # Halo control: limit overshoot past the local 3x3 range (bright halos
    # are limited more strictly than dark ones).
    k = np.ones((3, 3), np.uint8)
    lo = cv2.erode(y, k, borderType=cv2.BORDER_REFLECT)
    hi = cv2.dilate(y, k, borderType=cv2.BORDER_REFLECT)
    y_new = np.clip(y_new, lo - 0.02, hi + 0.008)
    return _ycc_to_rgb(y_new, cb, cr)


# --------------------------------------------------------------- render

def render(lin: np.ndarray, eff: Effective, noise: NoiseModel, scale: float) -> np.ndarray:
    """Render linear ProPhoto -> display-encoded sRGB float32 in [0, 1].

    ``scale`` = rendered pixels per full-resolution pixel (1.0 for 100% view
    and export; < 1 for previews). It adapts filter radii and noise levels.
    """
    img = lin.astype(np.float32, copy=True)
    gains = wb_gains(eff).astype(np.float32)
    if not np.allclose(gains, 1.0):
        img *= gains
    lut = build_tone_lut(eff)
    y0 = color.luminance(img)
    d0 = np.clip(color.srgb_encode(y0), 0.0, ToneLUT.D_MAX)
    img *= lut.lookup(d0, lut.mult)[..., None]

    if eff.color != 0:
        v = float(np.clip(eff.color, -150, 150)) / 100.0 * 0.5
        y = color.luminance(img)[..., None]
        mx = color.channel_max(img)[..., None]
        mn = color.channel_min(img)[..., None]
        sat = np.clip((mx - mn) / np.maximum(mx, 1e-6), 0.0, 1.0)
        f = 1.0 + v * (1.0 - sat) ** 2 if v > 0 else 1.0 + v * 1.6
        img = y + (img - y) * f
        img = np.maximum(img, 0.0)

    disp = color.srgb_encode(color.gamut_map_to_srgb(img))
    del img

    nr = float(np.clip(eff.noise_reduction, 0, 150)) / 100.0
    if nr > 0 or eff.detail > 0:
        sig = noise.sigma(np.clip(y0, 0, None)).astype(np.float32) * noise.scale_factor(scale)
        sigma_map = (lut.lookup(d0, lut.dout_dy) * sig).astype(np.float32)
        sigma_map = np.minimum(sigma_map, 0.25)
        if nr > 0:
            disp = denoise(disp, sigma_map, nr)
        if eff.detail > 0 or eff.clarity > 0:
            disp = sharpen_and_clarity(disp, sigma_map, eff.detail, eff.clarity, scale, nr)
    elif eff.clarity > 0:
        disp = sharpen_and_clarity(disp, np.zeros(disp.shape[:2], np.float32), 0, eff.clarity, scale, 0)
    return np.clip(disp, 0.0, 1.0)


def render_region(lin_full: np.ndarray, eff: Effective, noise: NoiseModel,
                  x: int, y: int, w: int, h: int, pad: int = 128) -> np.ndarray:
    """Render a region of a full-resolution image with context padding."""
    H, W = lin_full.shape[:2]
    x0 = max(0, ((x - pad) // PYR_ALIGN) * PYR_ALIGN)
    y0 = max(0, ((y - pad) // PYR_ALIGN) * PYR_ALIGN)
    x1 = min(W, x + w + pad)
    y1 = min(H, y + h + pad)
    out = render(lin_full[y0:y1, x0:x1], eff, noise, 1.0)
    return out[y - y0:y - y0 + h, x - x0:x - x0 + w]


def render_tiled(lin_full: np.ndarray, eff: Effective, noise: NoiseModel,
                 crop: tuple[int, int, int, int], tile: int, pad: int,
                 out_dtype=np.uint16, cancel=None, progress=None) -> np.ndarray:
    """Render a crop of a full-resolution image tile by tile (bounded memory)."""
    cx, cy, cw, ch = crop
    maxv = 65535.0 if out_dtype == np.uint16 else 255.0
    out = np.empty((ch, cw, 3), dtype=out_dtype)
    tiles = [(tx, ty) for ty in range(0, ch, tile) for tx in range(0, cw, tile)]
    for i, (tx, ty) in enumerate(tiles):
        if cancel is not None and cancel():
            raise InterruptedError
        tw, th = min(tile, cw - tx), min(tile, ch - ty)
        part = render_region(lin_full, eff, noise, cx + tx, cy + ty, tw, th, pad)
        out[ty:ty + th, tx:tx + tw] = np.round(part * maxv).astype(out_dtype)
        if progress is not None:
            progress((i + 1) / len(tiles))
    return out
