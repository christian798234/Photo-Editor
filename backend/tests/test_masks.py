"""Subject-mask tests.

Unit tests use synthetic masks. Tests that run the real models on a real bird
photo need BIRDEDIT_BIRD_SAMPLES (a folder of bird JPEGs) and are skipped
otherwise; a skip means "not verified", not "passed".
"""

import os
from pathlib import Path

import numpy as np
import pytest

from birdedit import auto, color, masks, pipeline
from birdedit.noise import NoiseModel
from birdedit.recipe import Recipe, Sliders, Subject, effective

from conftest import gradient_image, make_jpeg, wait_jobs

INSTALLED = masks.status()["installed"]
needs_models = pytest.mark.skipif(not INSTALLED, reason="bird detection models not installed")


def disk(h=200, w=300, cx=150, cy=100, r=40):
    yy, xx = np.mgrid[0:h, 0:w]
    return ((xx - cx) ** 2 + (yy - cy) ** 2 <= r * r)


def test_feather_grows_and_softens():
    m = disk()
    f = masks.feather(m)
    assert f.dtype == np.uint8
    assert (f[m] > 200).mean() > 0.97             # the whole bird counts as bird
    assert (f > 10).sum() > m.sum()               # grown slightly (conservative edges)
    assert 0 < f[100, 150 + 44] < 255             # soft transition near the edge


def test_quality_rejects_bad_masks():
    rgb = np.zeros((200, 300, 3), np.uint8)
    rgb[disk()] = 200
    logits = np.where(disk(), 5.0, -5.0).astype(np.float32)
    good = masks.quality(logits, [110, 60, 190, 140], rgb, 0.92)
    assert good["ok"], good
    spill = masks.quality(np.where(disk(r=90), 5.0, -5.0).astype(np.float32), [110, 60, 190, 140], rgb, 0.92)
    assert not spill["ok"]
    low = masks.quality(logits, [110, 60, 190, 140], rgb, 0.5)
    assert not low["ok"] and "low predicted quality" in low["reason"]
    unstable = masks.quality(np.where(disk(), 0.5, -0.5).astype(np.float32), None, rgb, 0.9)
    assert not unstable["ok"]


def test_crop_suggestion_never_cuts_bird():
    m = (disk(1000, 1500, 1100, 300, 80) * 255).astype(np.uint8)
    c = masks.suggest_crop(m, 1.5, (6000, 4000))
    assert c is not None
    x0, x1 = c["x"] * 1500, (c["x"] + c["w"]) * 1500
    y0, y1 = c["y"] * 1000, (c["y"] + c["h"]) * 1000
    assert x0 <= 1020 and x1 >= 1180 and y0 <= 220 and y1 >= 380
    assert abs((c["w"] * 6000) / (c["h"] * 4000) - 1.5) < 0.01
    assert c["x"] >= 0 and c["y"] >= 0 and c["x"] + c["w"] <= 1.0001 and c["y"] + c["h"] <= 1.0001
    # A bird that already fills the frame gets no suggestion.
    big = (disk(1000, 1500, 750, 500, 480) * 255).astype(np.uint8)
    assert masks.suggest_crop(big, 1.5, (6000, 4000)) is None


def test_masked_processing_treats_bird_and_background_differently():
    rng = np.random.default_rng(0)
    img = np.full((200, 300, 3), 0.1, np.float32) + rng.normal(0, 0.006, (200, 300, 3)).astype(np.float32)
    nm = NoiseModel(a=0.0, b=0.006 ** 2, native_scale=1.0, method="measured")
    m = disk().astype(np.float32)
    r = Recipe(sliders=Sliders(noise_reduction=40), subject=Subject(use_mask=True, background_nr=80))
    out = pipeline.render(img, effective(r), nm, 1.0, m)
    bird_std = out[85:115, 135:165].std()
    bg_std = out[10:40, 10:60].std()
    assert bg_std < 0.7 * bird_std                 # background smoothed more
    # Without the mask (or with use_mask False) the same recipe is global.
    out2 = pipeline.render(img, effective(r.model_copy(update={"subject": Subject()})), nm, 1.0, m)
    assert abs(out2[85:115, 135:165].std() - out2[10:40, 10:60].std()) < 0.3 * out2[10:40, 10:60].std()


def test_masked_tiles_match_region_render():
    rng = np.random.default_rng(1)
    img = rng.uniform(0, 0.5, (300, 400, 3)).astype(np.float32)
    mfull = (disk(300, 400, 200, 150, 70) * 255).astype(np.uint8)
    eff = effective(Recipe(sliders=Sliders(noise_reduction=50, detail=40), subject=Subject(use_mask=True, background_nr=60)))
    nm = NoiseModel(a=1e-4, b=1e-6, native_scale=1.0, method="measured")
    tiled = pipeline.render_tiled(img, eff, nm, (0, 0, 400, 300), 128, 128, np.uint16, mask_full=mfull)
    region = pipeline.render_region(img, eff, nm, 0, 0, 400, 300, 128, mask_full=mfull)
    assert np.abs(tiled.astype(np.float32) / 65535 - region).max() < 2e-4


def test_auto_meters_on_bird_when_mask_given():
    img = np.full((200, 300, 3), 0.6, np.float32)        # bright sky
    m = disk()
    img[m] = 0.02                                         # dark bird
    nm = NoiseModel(a=1e-6, b=1e-8, native_scale=1.0, method="measured")
    r_plain, f1 = auto.analyze_and_build(img, nm)
    r_mask, f2 = auto.analyze_and_build(img, nm, mask=(m * 255).astype(np.uint8))
    assert f2["metering"] == "bird" and r_mask.subject.use_mask
    assert r_mask.sliders.exposure > r_plain.sliders.exposure
    with pytest.raises(ValueError):
        auto.analyze_and_build(img, nm, look="soft_background")


@needs_models
def test_no_bird_in_synthetic_scene():
    lin = color.apply_matrix(color.srgb_decode(gradient_image(480, 640).astype(np.float32) / 255),
                             color.SRGB_TO_PROPHOTO)
    res, m = masks.compute(lin)
    assert res.status == "none" and m is None


@needs_models
def test_models_match_pinned_checksums():
    st = masks.status()
    assert all(item["intact"] for item in st["models"])


@needs_models
def test_detection_requires_consent_and_falls_back(client, tmp_path):
    p = make_jpeg(tmp_path / "scene.jpg", gradient_image(480, 640), "SONY", "ILCE-1")
    client.post("/api/import/upload", files=[("files", (p.name, p.read_bytes(), "image/jpeg"))])
    wait_jobs(client)
    pid = client.get("/api/photos").json()[0]["id"]
    assert client.post(f"/api/photos/{pid}/detect", json={}).status_code == 409   # not switched on
    s = client.get("/api/settings").json()
    client.put("/api/settings", json={**s, "subject_detection": True})
    r = client.post(f"/api/photos/{pid}/detect", json={}).json()
    assert r["status"] == "none"
    auto_r = client.post(f"/api/photos/{pid}/auto", json={"look": "natural"}).json()
    assert auto_r["recipe"]["subject"]["use_mask"] is False                      # global fallback
    assert client.post(f"/api/photos/{pid}/auto", json={"look": "soft_background"}).status_code == 409
    assert client.post(f"/api/photos/{pid}/crop-suggestion", json={}).status_code == 409


BIRD_DIR = os.environ.get("BIRDEDIT_BIRD_SAMPLES")


@needs_models
@pytest.mark.skipif(not BIRD_DIR, reason="UNVERIFIED: no real bird photos in BIRDEDIT_BIRD_SAMPLES")
def test_real_bird_photos_are_segmented():
    from PIL import Image
    files = sorted(p for p in Path(BIRD_DIR).iterdir() if p.suffix.lower() in (".jpg", ".jpeg"))
    assert files
    for f in files:
        rgb = np.asarray(Image.open(f).convert("RGB")).astype(np.float32) / 255
        lin = color.apply_matrix(color.srgb_decode(rgb), color.SRGB_TO_PROPHOTO)
        res, m = masks.compute(lin)
        assert res.status == "good", (f.name, res.message, res.birds)
        assert m is not None and 0.01 < (m > 128).mean() < 0.9
