"""Colour-space math for the working space.

Working space: **linear ProPhoto RGB (D50)**, float32, exactly as LibRaw
produces with ``output_color=ProPhoto, gamma=(1,1)``. LibRaw defines ProPhoto
via its sRGB->ProPhoto matrix (Bradford D65->D50); we use the same matrix so a
RAW decoded to ProPhoto and converted here matches LibRaw's own sRGB output
(verified in tests/test_color.py against a real NEF when samples exist).

Display/export space: sRGB (IEC 61966-2-1) with its standard transfer curve.
"""

from __future__ import annotations

import numpy as np

# LibRaw's prophoto_rgb matrix: linear sRGB(D65) -> linear ProPhoto(D50).
SRGB_TO_PROPHOTO = np.array(
    [[0.529317, 0.330092, 0.140588],
     [0.098368, 0.873465, 0.028169],
     [0.016879, 0.117663, 0.865457]], dtype=np.float64)
PROPHOTO_TO_SRGB = np.linalg.inv(SRGB_TO_PROPHOTO)

# ProPhoto -> XYZ (D50), ICC/ROMM definition.
PROPHOTO_TO_XYZ_D50 = np.array(
    [[0.7976749, 0.1351917, 0.0313534],
     [0.2880402, 0.7118741, 0.0000857],
     [0.0000000, 0.0000000, 0.8252100]], dtype=np.float64)
XYZ_D50_TO_PROPHOTO = np.linalg.inv(PROPHOTO_TO_XYZ_D50)

# Rec.709/sRGB luminance weights, and the matching weights for ProPhoto data.
SRGB_LUMA = np.array([0.2126, 0.7152, 0.0722])
PROPHOTO_LUMA = SRGB_LUMA @ PROPHOTO_TO_SRGB


def apply_matrix(img: np.ndarray, m: np.ndarray) -> np.ndarray:
    """Apply a 3x3 matrix to an HxWx3 float image."""
    h, w, _ = img.shape
    out = img.reshape(-1, 3) @ m.T.astype(np.float32)
    return out.reshape(h, w, 3)


def luminance(img: np.ndarray, weights: np.ndarray = PROPHOTO_LUMA) -> np.ndarray:
    w = weights.astype(np.float32)
    return img[..., 0] * w[0] + img[..., 1] * w[1] + img[..., 2] * w[2]


def channel_max(img: np.ndarray) -> np.ndarray:
    return np.maximum(np.maximum(img[..., 0], img[..., 1]), img[..., 2])


def channel_min(img: np.ndarray) -> np.ndarray:
    return np.minimum(np.minimum(img[..., 0], img[..., 1]), img[..., 2])


def srgb_encode(lin: np.ndarray) -> np.ndarray:
    lin = np.clip(lin, 0.0, None)
    return np.where(lin <= 0.0031308, lin * 12.92,
                    1.055 * np.power(lin, 1.0 / 2.4, dtype=np.float32) - 0.055).astype(np.float32)


def srgb_decode(enc: np.ndarray) -> np.ndarray:
    enc = np.clip(enc, 0.0, None)
    return np.where(enc <= 0.04045, enc / 12.92,
                    np.power((enc + 0.055) / 1.055, 2.4, dtype=np.float32)).astype(np.float32)


def gamut_map_to_srgb(prophoto_lin: np.ndarray) -> np.ndarray:
    """Linear ProPhoto -> linear sRGB in [0, 1].

    Out-of-gamut colours are pulled toward their own luminance (a hue- and
    luminance-preserving desaturation) instead of being clipped per channel,
    which avoids hue shifts in saturated feathers.
    """
    rgb = apply_matrix(prophoto_lin, PROPHOTO_TO_SRGB)
    y = np.clip(luminance(rgb, SRGB_LUMA), 0.0, 1.0)[..., None]
    d = rgb - y
    mn = channel_min(rgb)[..., None]
    mx = channel_max(rgb)[..., None]
    t = np.ones_like(y)
    neg = mn < 0
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(neg, np.minimum(t, y / np.maximum(y - mn, 1e-9)), t)
        over = mx > 1
        t = np.where(over, np.minimum(t, (1 - y) / np.maximum(mx - y, 1e-9)), t)
    t = np.clip(t, 0.0, 1.0)
    return np.clip(y + d * t, 0.0, 1.0).astype(np.float32)
