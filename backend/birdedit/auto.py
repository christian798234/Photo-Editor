"""Automatic, image-dependent edit estimation (no machine learning).

Everything here is computed from measurable statistics of the linear
preview plus the measured noise model. There is no subject detection: the
exposure metering is *centre-weighted* (birds are usually framed near the
centre), which is a heuristic, and the summary says so.
"""

from __future__ import annotations

import cv2
import numpy as np

from . import color
from .noise import NoiseModel
from .pipeline import build_tone_lut, tone_display
from .recipe import Effective, Internal, Recipe, Sliders, effective

TARGET_KEY = 0.15          # linear centre-weighted log-average target


def _small(lin: np.ndarray, edge: int = 640) -> np.ndarray:
    h, w = lin.shape[:2]
    f = edge / max(h, w)
    if f >= 1:
        return lin
    return cv2.resize(lin, (max(1, int(w * f)), max(1, int(h * f))), interpolation=cv2.INTER_AREA)


def _center_weights(h: int, w: int) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cy, cx = (h - 1) / 2, (w - 1) / 2
    r2 = ((yy - cy) / (0.32 * h)) ** 2 + ((xx - cx) / (0.32 * w)) ** 2
    return 0.4 + 0.6 * np.exp(-0.5 * r2)


def _wpercentile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    idx = np.argsort(values, axis=None)
    v = values.ravel()[idx]
    cw = np.cumsum(weights.ravel()[idx])
    return float(np.interp(q / 100.0 * cw[-1], cw, v))


def _eff(**kw) -> Effective:
    base = dict(exposure=0, warmth=0, tint=0, highlights=0, shadows=0, contrast=0,
                black=0, color=0, noise_reduction=0, detail=0, clarity=0)
    base.update(kw)
    return Effective(**base)


def analyze_and_build(lin_preview: np.ndarray, noise: NoiseModel, look: str = "natural",
                      noise_render_scale: float = 1.0) -> tuple[Recipe, dict]:
    """Return (auto recipe, analysis facts used by the summary)."""
    if look not in ("natural", "crisp"):
        look = "natural"
    crisp = look == "crisp"
    facts: dict = {"look": look}

    clipped = float(np.mean(color.channel_max(lin_preview) >= 0.995))
    facts["clipped_fraction"] = clipped
    s = _small(lin_preview)
    h, w = s.shape[:2]
    wts = _center_weights(h, w)
    y = np.maximum(color.luminance(s), 1e-5)

    # --- white balance refinement (conservative, damped) -----------------
    # Two passes: a loose selection estimates the overall cast, then pixels
    # that are near-neutral *relative to that cast* refine it. This finds
    # grey/white areas (sky haze, white feathers, rocks) even under a cast.
    mx = color.channel_max(s)
    mn = color.channel_min(s)
    base_ok = (y >= np.percentile(y, 20)) & (mx < 0.95) & (y > 1e-3)
    lr = np.log2(np.maximum(s[..., 0], 1e-6) / np.maximum(s[..., 1], 1e-6))
    lb = np.log2(np.maximum(s[..., 2], 1e-6) / np.maximum(s[..., 1], 1e-6))
    chroma = (mx - mn) / np.maximum(mx, 1e-6)
    loose = base_ok & (chroma < 0.35)
    warmth = tint = 0.0
    frac_neutral = 0.0
    if loose.mean() > 0.03:
        cr0, cb0 = float(np.median(lr[loose])), float(np.median(lb[loose]))
        rel = np.hypot(lr - cr0, lb - cb0)
        neutral = base_ok & (rel < 0.12)
        frac_neutral = float(neutral.mean())
        if frac_neutral > 0.03:
            c_r = -float(np.median(lr[neutral]))
            c_b = -float(np.median(lb[neutral]))
            warmth = float(np.clip(0.35 * (c_r - c_b) * 100.0, -15, 15))
            tint = float(np.clip(0.35 * ((c_r + c_b) / 2.0) / 0.3 * 100.0, -10, 10))
            if abs(warmth) < 2:
                warmth = 0.0
            if abs(tint) < 2:
                tint = 0.0
    facts["neutral_fraction"] = frac_neutral

    # --- exposure (centre-weighted, highlight-capped) ----------------------
    key = float(np.exp(np.sum(wts * np.log(y)) / np.sum(wts)))
    ev = 0.7 * np.log2(TARGET_KEY / key)
    ev = float(np.clip(ev, -1.5, 1.5))
    p995 = float(np.percentile(color.luminance(lin_preview), 99.5))
    if p995 > 1e-4:
        ev = min(ev, float(np.log2(2.4 / p995)))
    if clipped > 0.005:
        ev = min(ev, 0.3)
    ev = round(ev * 20) / 20
    if abs(ev) < 0.1:
        ev = 0.0
    facts["key"] = key

    # --- highlights: map the brightest real highlight to white -------------
    p999 = float(np.percentile(color.luminance(lin_preview), 99.9)) * 2.0 ** ev
    highlights = 0.0
    if p999 > 1.0:
        highlights = -float(np.clip(np.log2(p999) / 2.0, 0.0, 1.0)) * 100.0
        highlights = min(highlights, -10.0)
    else:
        dh = float(color.srgb_encode(np.array([p999], np.float32))[0])
        if dh > 0.9:
            highlights = -15.0
    highlights = round(highlights)

    d = tone_display(color.srgb_encode((y * 2.0 ** ev).astype(np.float32)),
                     _eff(exposure=ev, highlights=highlights))
    # --- shadows: lift moderately when much of the frame is dark -----------
    dark_frac = float(np.sum(wts * (d < 0.18)) / np.sum(wts))
    shadows = float(np.clip((dark_frac - 0.15) * 80.0, 0.0, 30.0))
    shadows = round(shadows)
    facts["dark_fraction"] = dark_frac

    # --- black point: remove haze only, never crush ------------------------
    p01 = float(np.percentile(d, 0.1))
    black = float(min(p01 * 0.5 * 100.0, 3.0)) if p01 > 0.04 else 0.0
    black = round(black, 1)

    d2 = tone_display(d, _eff(shadows=shadows, black=black))
    spread = _wpercentile(d2, wts, 95) - _wpercentile(d2, wts, 5)
    contrast = float(np.clip(8 + (0.55 - spread) * 30, 4, 18)) + (6 if crisp else 0)
    facts["tonal_spread"] = spread

    sat = np.clip((mx - mn) / np.maximum(mx, 1e-6), 0, 1)
    mid = (d2 > 0.15) & (d2 < 0.9)
    msat = float(sat[mid].mean()) if mid.any() else 0.2
    color_v = float(np.clip(12 + (0.2 - msat) * 40, 5, 20)) + (5 if crisp else 0)
    facts["mean_saturation"] = msat

    # --- noise reduction and detail from the measured noise ----------------
    eff_tone = _eff(exposure=ev, highlights=highlights, shadows=shadows, black=black,
                    contrast=contrast)
    lut = build_tone_lut(eff_tone)
    y_med = float(np.median(y))
    d0 = float(color.srgb_encode(np.array([y_med], np.float32))[0])
    slope = float(np.interp(d0, lut.grid, lut.dout_dy))
    sigma_disp = float(noise.sigma(y_med)) * slope * noise.scale_factor(noise_render_scale)
    facts["noise_sigma_display"] = sigma_disp
    facts["noise_method"] = noise.method
    nr = float(np.clip(20 + sigma_disp * 4000, 20, 80))
    detail = float(np.clip(45 - sigma_disp * 2500, 20, 45))
    clarity = 0.0
    if crisp:
        nr *= 0.8
        detail = min(60.0, detail + 15)
        clarity = 12.0

    recipe = Recipe(
        look=look,
        strength=100,
        sliders=Sliders(exposure=ev, warmth=round(warmth), highlights=highlights,
                        shadows=shadows, color=round(color_v),
                        noise_reduction=round(nr), detail=round(detail)),
        internal=Internal(tint=round(tint), contrast=round(contrast, 1), black=black,
                          clarity=clarity),
        auto_applied=True,
    )
    return recipe, facts


def noise_display_sigma(recipe: Recipe, noise: NoiseModel, y_med: float = 0.1) -> float:
    eff = effective(recipe)
    lut = build_tone_lut(eff)
    d0 = float(color.srgb_encode(np.array([y_med], np.float32))[0])
    return float(noise.sigma(y_med)) * float(np.interp(d0, lut.grid, lut.dout_dy))
