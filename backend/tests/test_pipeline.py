import numpy as np
import pytest

from birdedit import auto, color, pipeline
from birdedit.noise import NoiseModel, estimate, iso_prior
from birdedit.recipe import Internal, Recipe, Sliders, baseline_recipe, effective

NM = NoiseModel(a=1e-6, b=1e-8, native_scale=1.0, method="measured")


def flat(v, shape=(64, 64)):
    return np.full((*shape, 3), v, np.float32)


def render(img, **sl):
    internal = {k: sl.pop(k) for k in list(sl) if k in Internal.model_fields}
    r = Recipe(sliders=Sliders(**sl), internal=Internal(**internal))
    return pipeline.render(img, effective(r), NM, 1.0)


def lin_out(img_disp):
    return color.srgb_decode(img_disp)


def test_identity_is_plain_srgb_encoding():
    img = flat(0.18)
    out = pipeline.render(img, effective(baseline_recipe()), NM, 1.0)
    expected = color.srgb_encode(color.gamut_map_to_srgb(img))
    assert np.allclose(out, expected, atol=1e-5)


def test_exposure_plus_one_ev_doubles_midtones():
    out0 = lin_out(render(flat(0.1)))
    out1 = lin_out(render(flat(0.1), exposure=1.0))
    assert np.allclose(out1 / out0, 2.0, rtol=0.01)


def test_warmth_shifts_red_blue_balance():
    base = render(flat(0.2))
    warm = render(flat(0.2), warmth=50)
    cool = render(flat(0.2), warmth=-50)
    assert warm[..., 0].mean() > base[..., 0].mean() > cool[..., 0].mean()
    assert warm[..., 2].mean() < base[..., 2].mean() < cool[..., 2].mean()


def test_highlight_protection_keeps_bright_detail_below_clip():
    # Two bright tones that would both clip at +1 EV without protection.
    img = np.concatenate([flat(0.7, (32, 32)), flat(0.9, (32, 32))], axis=1)
    clipped = render(img, exposure=1.0)
    protected = render(img, exposure=1.0, highlights=-60)
    assert np.isclose(clipped[:, :32].mean(), clipped[:, 32:].mean(), atol=1e-3)   # both clipped
    assert protected[:, 32:].mean() - protected[:, :32].mean() > 0.02             # separated
    assert protected.max() <= 1.0


def test_shadows_lift_darks_but_anchor_black():
    img = np.concatenate([flat(0.0, (16, 16)), flat(0.01, (16, 16))], axis=1)
    out = render(img, shadows=80)
    base = render(img)
    assert out[:, :16].max() == pytest.approx(0, abs=1e-6)     # black stays black
    assert out[:, 16:].mean() > base[:, 16:].mean()


def test_color_intensity_increases_saturation_without_clipping():
    img = flat(0.2)
    img[..., 0] *= 1.3
    sat = lambda o: (o.max(axis=2) - o.min(axis=2)).mean()
    assert sat(render(img, color=60)) > sat(render(img)) > sat(render(img, color=-60))


def test_noise_reduction_reduces_noise_and_keeps_edge():
    rng = np.random.default_rng(0)
    img = np.full((128, 128, 3), 0.05, np.float32)
    img[:, 64:] = 0.25
    sigma = 0.004
    noisy = img + rng.normal(0, sigma, img.shape).astype(np.float32)
    nm = NoiseModel(a=0.0, b=sigma ** 2, native_scale=1.0, method="measured")
    r0 = Recipe()
    r1 = Recipe(sliders=Sliders(noise_reduction=80))
    o0 = pipeline.render(noisy, effective(r0), nm, 1.0)
    o1 = pipeline.render(noisy, effective(r1), nm, 1.0)
    assert o1[8:-8, 8:56].std() < 0.6 * o0[8:-8, 8:56].std()
    edge0 = o0[:, 70:].mean() - o0[:, :58].mean()
    edge1 = o1[:, 70:].mean() - o1[:, :58].mean()
    assert abs(edge1 - edge0) < 0.01


def test_sharpening_limits_bright_halo():
    img = np.full((64, 64, 3), 0.05, np.float32)
    img[:, 32:] = 0.4
    out = render(img, detail=100)
    base = render(img)
    assert out.max() <= base.max() + 0.0081            # bright overshoot clamp
    assert out.min() >= base.min() - 0.0201


def test_tiled_render_equals_region_render():
    rng = np.random.default_rng(3)
    img = (rng.uniform(0, 0.6, (300, 400, 3))).astype(np.float32)
    eff = effective(Recipe(sliders=Sliders(exposure=0.5, noise_reduction=50, detail=40),
                           internal=Internal(contrast=10, clarity=10)))
    nm = iso_prior(800, 1.0)
    tiled = pipeline.render_tiled(img, eff, nm, (10, 20, 350, 260), 128, 128, np.uint16)
    region = pipeline.render_region(img, eff, nm, 10, 20, 350, 260, pad=128)
    assert tiled.dtype == np.uint16 and tiled.shape == (260, 350, 3)
    assert np.abs(tiled.astype(np.float32) / 65535 - region).max() < 2e-4


def test_16bit_output_keeps_more_than_8_bits():
    ramp = np.linspace(0.01, 0.2, 4000, dtype=np.float32)[None, :, None].repeat(3, 2).repeat(4, 0)
    out = pipeline.render_tiled(ramp, effective(baseline_recipe()), NM, (0, 0, 4000, 4), 1024, 64, np.uint16)
    assert len(np.unique(out[..., 1])) > 1000


def test_auto_is_image_dependent():
    dark = np.full((200, 300, 3), 0.01, np.float32)
    bright = np.full((200, 300, 3), 0.6, np.float32)
    r_dark, _ = auto.analyze_and_build(dark, NM)
    r_bright, _ = auto.analyze_and_build(bright, NM)
    assert r_dark.sliders.exposure > 0.5
    assert r_bright.sliders.exposure < 0
    assert r_dark.auto_applied and r_dark.look == "natural"


def test_auto_white_balance_is_damped():
    img = np.full((200, 300, 3), 0.15, np.float32)
    img[..., 0] *= 1.10       # warm cast on neutral content
    img[..., 2] *= 0.90
    r, _ = auto.analyze_and_build(img, NM)
    assert -15 <= r.sliders.warmth < 0       # corrects toward neutral, but only partly


def test_auto_protects_clipped_highlights_and_reports_them():
    img = np.full((200, 300, 3), 0.05, np.float32)
    img[80:120, 100:200] = 1.0              # clipped white "feathers"
    r, facts = auto.analyze_and_build(img, NM)
    assert facts["clipped_fraction"] > 0.05
    assert r.sliders.exposure <= 0.3
    from birdedit.summary import summarize
    assert "cannot be recovered" in summarize(r, facts)


def test_noise_model_recovers_synthetic_noise():
    rng = np.random.default_rng(5)
    y = np.linspace(0.01, 0.8, 1024, dtype=np.float32)[None, :].repeat(768, 0)
    clean = np.stack([y, y, y], axis=-1)
    a, b = 4e-4, 1e-6
    noisy = clean + rng.normal(0, 1, clean.shape).astype(np.float32) * np.sqrt(a * clean + b)
    # Noise is per channel; luminance noise of identical channels is the same.
    nm = estimate(noisy.astype(np.float32), 1.0, 400)
    assert nm.method == "measured"
    for yy in (0.05, 0.3):
        true = np.sqrt(a * yy + b) * np.sqrt((color.PROPHOTO_LUMA ** 2).sum())
        assert 0.6 * true < float(nm.sigma(yy)) < 1.6 * true


def test_noise_model_falls_back_to_iso_on_tiny_image():
    nm = estimate(np.zeros((20, 20, 3), np.float32), 1.0, 1600)
    assert nm.method == "iso-fallback"
