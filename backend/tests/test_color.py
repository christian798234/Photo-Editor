import io

import numpy as np
from PIL import Image, ImageCms

from birdedit import color
from birdedit.decode import decode_jpeg
from birdedit.icc import parse_icc
from birdedit.noise import iso_prior
from birdedit.pipeline import render
from birdedit.recipe import baseline_recipe, effective


def test_srgb_roundtrip():
    x = np.linspace(0, 1, 1001, dtype=np.float32)
    assert np.abs(color.srgb_decode(color.srgb_encode(x)) - x).max() < 1e-5


def test_prophoto_matrix_matches_icc_srgb_colorants():
    prof = parse_icc(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    assert prof is not None
    m = color.XYZ_D50_TO_PROPHOTO @ prof.to_xyz_d50
    assert np.abs(m - color.SRGB_TO_PROPHOTO).max() < 2e-3


def test_gamut_map_in_range_and_neutral_preserved():
    rng = np.random.default_rng(1)
    img = rng.uniform(0, 1.5, (50, 50, 3)).astype(np.float32)
    out = color.gamut_map_to_srgb(img)
    assert out.min() >= 0 and out.max() <= 1
    grey = np.full((2, 2, 3), 0.18, np.float32)
    assert np.allclose(color.gamut_map_to_srgb(grey), 0.18, atol=1e-3)


def test_baseline_render_of_jpeg_reproduces_original():
    """'Before' for a JPEG must equal the JPEG itself (consistent baseline)."""
    rng = np.random.default_rng(2)
    rgb = rng.integers(0, 256, (64, 80, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, "PNG")  # lossless container for the test
    buf2 = io.BytesIO()
    Image.fromarray(rgb).save(buf2, "JPEG", quality=100)
    dec = decode_jpeg(buf2.getvalue())
    original = np.asarray(Image.open(io.BytesIO(buf2.getvalue())).convert("RGB")).astype(np.float32) / 255
    out = render(dec.image, effective(baseline_recipe()), iso_prior(100, 1.0), 1.0)
    assert out.shape == original.shape and out.dtype == np.float32
    assert np.abs(out - original).max() < 1.5 / 255
