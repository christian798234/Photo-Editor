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
from .recipe import Effective, Internal, Recipe, Sliders, Subject, effective

TARGET_KEY = 0.18          # linear centre-weighted log-average target

# "Development" targets for RAW files, relative to the unedited baseline.
# Calibrated against camera JPEGs (Canon R6 II standard picture style: about
# 1.25x the baseline saturation and 1.4-1.5x its tonal range). JPEG/TIFF input
# has already been developed by the camera, so it only gets a light touch.
RAW_TARGETS = {"sat": 1.25, "range": 1.42, "sat_cap": 0.40, "range_cap": 0.74}
RENDERED_TARGETS = {"sat": 1.06, "range": 1.05, "sat_cap": 0.40, "range_cap": 0.74}


def _display_stats(disp: np.ndarray) -> tuple[float, float]:
    """(mean saturation of mid-tones, 5-95% luminance range) of display RGB."""
    y = 0.2126 * disp[..., 0] + 0.7152 * disp[..., 1] + 0.0722 * disp[..., 2]
    mx, mn = disp.max(axis=2), disp.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1e-3)
    mid = (y > 0.1) & (y < 0.95)
    s = float(sat[mid].mean()) if mid.any() else float(sat.mean())
    lo, hi = np.percentile(y, [5, 95])
    return s, float(hi - lo)


def _calibrate(small: np.ndarray, recipe: Recipe, nm: NoiseModel, targets: dict,
               crisp: bool) -> tuple[float, float, dict]:
    """Adjust colour intensity and contrast so the result reaches the
    development targets. Few cheap renders of a small image, tone/colour only."""
    from .pipeline import render
    base = render(small, effective(Recipe()), nm, 1.0)
    s0, r0 = _display_stats(base)
    want_s = min(targets["sat_cap"], max(s0, s0 * targets["sat"]))
    want_r = min(targets["range_cap"], max(r0, r0 * targets["range"]))
    if crisp:
        want_s, want_r = min(targets["sat_cap"], want_s * 1.06), min(targets["range_cap"], want_r * 1.04)
    col, con = recipe.sliders.color, recipe.internal.contrast
    col0, con0 = col, con          # development only ever adds colour/contrast

    def measure(c, k):
        r = recipe.model_copy(update={
            "sliders": recipe.sliders.model_copy(update={"color": c, "noise_reduction": 0, "detail": 0}),
            "internal": recipe.internal.model_copy(update={"contrast": k, "clarity": 0})})
        return _display_stats(render(small, effective(r), nm, 1.0))

    for _ in range(4):
        s1, r1 = measure(col, con)
        if abs(s1 - want_s) < 0.006 and abs(r1 - want_r) < 0.01:
            break
        # Empirical sensitivities: ~0.0025 saturation per colour step,
        # ~0.006 range per contrast step (both re-measured each round).
        col = float(np.clip(col + (want_s - s1) / 0.004, col0, 35))
        con = float(np.clip(con + (want_r - r1) / 0.006, con0, 20))
    s1, r1 = measure(col, con)
    return round(col), round(con, 1), {"baseline_sat": round(s0, 3), "baseline_range": round(r0, 3),
                                        "target_sat": round(want_s, 3), "target_range": round(want_r, 3),
                                        "result_sat": round(s1, 3), "result_range": round(r1, 3)}


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


BACKGROUND_NR = {"natural": 20.0, "crisp": 12.0, "soft_background": 45.0}


def analyze_and_build(lin_preview: np.ndarray, noise: NoiseModel, look: str = "natural",
                      noise_render_scale: float = 1.0,
                      mask: np.ndarray | None = None,
                      rendered_source: bool = False) -> tuple[Recipe, dict]:
    """Return (auto recipe, analysis facts used by the summary).

    ``mask``: a validated bird mask (uint8, preview size) or None. With a mask,
    exposure is metered on the bird and background noise reduction is raised.
    """
    if look not in ("natural", "crisp", "soft_background"):
        look = "natural"
    if look == "soft_background" and mask is None:
        raise ValueError("The Soft Background look needs a reliable bird selection.")
    crisp = look == "crisp"
    facts: dict = {"look": look, "masked": mask is not None}

    clipped = float(np.mean(color.channel_max(lin_preview) >= 0.995))
    facts["clipped_fraction"] = clipped
    s = _small(lin_preview)
    h, w = s.shape[:2]
    if mask is not None:
        m_small = cv2.resize(mask, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        wts = 0.15 + 0.85 * m_small            # meter mostly on the bird
        facts["metering"] = "bird"
    else:
        wts = _center_weights(h, w)
        facts["metering"] = "centre-weighted"
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
            # Gentle: shade and golden light are part of the scene, so only a
            # fifth of any measured cast is corrected, capped at small values.
            warmth = float(np.clip(0.2 * (c_r - c_b) * 100.0, -8, 8))
            tint = float(np.clip(0.2 * ((c_r + c_b) / 2.0) / 0.3 * 100.0, -6, 6))
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
    # Bright scenes (white birds, snow, sky) are supposed to look bright:
    # darken only a little unless highlights are actually clipping.
    ev = max(ev, -1.0 if clipped > 0.005 else -0.5)
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
    shadows = float(np.clip((dark_frac - 0.15) * 60.0, 0.0, 20.0))
    shadows = round(shadows)
    facts["dark_fraction"] = dark_frac

    # --- black point: remove haze only, never crush ------------------------
    p01 = float(np.percentile(d, 0.1))
    black = float(min(p01 * 0.4 * 100.0, 2.0)) if p01 > 0.04 else 0.0
    black = round(black, 1)

    d2 = tone_display(d, _eff(shadows=shadows, black=black))
    spread = _wpercentile(d2, wts, 95) - _wpercentile(d2, wts, 5)
    contrast = min(14.0, float(np.clip(6 + (0.55 - spread) * 25, 3, 12)) + (4 if crisp else 0))
    facts["tonal_spread"] = spread

    sat = np.clip((mx - mn) / np.maximum(mx, 1e-6), 0, 1)
    mid = (d2 > 0.15) & (d2 < 0.9)
    msat = float(sat[mid].mean()) if mid.any() else 0.2
    color_v = float(np.clip(8 + (0.2 - msat) * 30, 3, 12)) + (3 if crisp else 0)
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
    nr = float(np.clip(15 + sigma_disp * 3500, 15, 55))
    # RAW needs the sharpening a camera applies to its JPEGs; JPEGs already have it.
    detail = float(np.clip((44 if not rendered_source else 30) - sigma_disp * 2500, 15, 44))
    clarity = 0.0 if rendered_source else 5.0
    if crisp:
        nr *= 0.85
        detail = min(50.0, detail + 6)
        clarity = 10.0

    recipe = Recipe(
        look=look,
        strength=100,
        sliders=Sliders(exposure=ev, warmth=round(warmth), highlights=highlights,
                        shadows=shadows, color=round(color_v),
                        noise_reduction=round(nr), detail=round(detail)),
        internal=Internal(tint=round(tint), contrast=round(contrast, 1), black=black,
                          clarity=clarity),
        subject=Subject(use_mask=mask is not None,
                        background_nr=BACKGROUND_NR[look] if mask is not None else 0.0),
        auto_applied=True,
    )
    # Development: reach camera-like colour and contrast (RAW) or a light
    # touch-up (JPEG/TIFF), measured on the actual result.
    targets = RENDERED_TARGETS if rendered_source else RAW_TARGETS
    small = _small(lin_preview, 512)
    col, con, cal = _calibrate(small, recipe, noise, targets, crisp)
    recipe = recipe.model_copy(update={
        "sliders": recipe.sliders.model_copy(update={"color": col}),
        "internal": recipe.internal.model_copy(update={"contrast": con})})
    facts["development"] = cal
    facts["rendered_source"] = rendered_source
    return recipe, facts


def noise_display_sigma(recipe: Recipe, noise: NoiseModel, y_med: float = 0.1) -> float:
    eff = effective(recipe)
    lut = build_tone_lut(eff)
    d0 = float(color.srgb_encode(np.array([y_med], np.float32))[0])
    return float(noise.sigma(y_med)) * float(np.interp(d0, lut.grid, lut.dout_dy))
