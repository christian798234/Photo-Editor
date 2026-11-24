import numpy as np

from birdedit import auto, restraint
from birdedit.noise import NoiseModel
from birdedit.recipe import Internal, Recipe, Sliders, Subject

NM = NoiseModel(a=1e-6, b=1e-8, native_scale=1.0, method="measured")


def test_limits_clamp_every_value():
    r = Recipe(strength=150, sliders=Sliders(exposure=3, color=100, shadows=100, noise_reduction=100, detail=100),
               internal=Internal(contrast=40, clarity=40, black=5))
    lim = restraint.apply_limits(r)
    assert lim.strength == 100 and lim.sliders.exposure == 2.0 and lim.sliders.color == 35
    assert lim.sliders.shadows == 40 and lim.sliders.noise_reduction == 60 and lim.sliders.detail == 50
    assert lim.internal.contrast == 20 and lim.internal.clarity == 15 and lim.internal.black == 3
    assert restraint.within_limits(lim) and not restraint.within_limits(r)
    gentle = Recipe(sliders=Sliders(exposure=0.4, color=8))
    assert restraint.apply_limits(gentle) == gentle            # gentle edits untouched


def test_edit_level():
    assert restraint.edit_level(Recipe())["level"] == "none"
    assert restraint.edit_level(Recipe(sliders=Sliders(exposure=0.3, color=8, detail=30)))["level"] == "light"
    assert restraint.edit_level(Recipe(sliders=Sliders(exposure=1.5)))["level"] == "moderate"
    strong = restraint.edit_level(Recipe(sliders=Sliders(exposure=1.5, shadows=35), internal=Internal(contrast=19)))
    assert strong["level"] == "strong" and "processed" in strong["notes"][-1]
    over = restraint.edit_level(Recipe(strength=140, sliders=Sliders(color=60)))
    assert over["level"] == "strong" and "Beyond the natural limits" in over["notes"][0]


def test_auto_edits_stay_light_or_moderate_and_within_limits():
    rng = np.random.default_rng(0)
    scenes = {
        "very dark": np.full((200, 300, 3), 0.004, np.float32),
        "very bright": np.full((200, 300, 3), 0.85, np.float32),
        "dull grey": np.full((200, 300, 3), 0.2, np.float32) + rng.normal(0, 0.01, (200, 300, 3)).astype(np.float32),
        "noisy": np.clip(np.full((200, 300, 3), 0.05, np.float32) + rng.normal(0, 0.03, (200, 300, 3)), 0, 1).astype(np.float32),
    }
    noisy_nm = NoiseModel(a=1e-3, b=1e-5, native_scale=1.0, method="measured")
    for name, img in scenes.items():
        for look in ("natural", "crisp"):
            r, _ = auto.analyze_and_build(img, noisy_nm if name == "noisy" else NM, look)
            assert restraint.within_limits(r), (name, look, r)
            lvl = restraint.edit_level(r)
            assert lvl["level"] in ("light", "moderate"), (name, look, lvl)
    m = np.zeros((200, 300), np.uint8)
    m[60:140, 100:200] = 255
    r, _ = auto.analyze_and_build(scenes["dull grey"], NM, "soft_background", mask=m)
    assert restraint.within_limits(r) and r.subject.background_nr <= 45


def test_api_enforces_limits_and_reports_level(client, tmp_path):
    from conftest import gradient_image, make_jpeg, wait_jobs
    p = make_jpeg(tmp_path / "a.jpg", gradient_image())
    client.post("/api/import/upload", files=[("files", (p.name, p.read_bytes(), "image/jpeg"))])
    wait_jobs(client)
    pid = client.get("/api/photos").json()[0]["id"]
    res = client.put(f"/api/photos/{pid}/recipe", json={"strength": 150, "sliders": {"color": 90}}).json()
    assert res["recipe"]["strength"] == 100 and res["recipe"]["sliders"]["color"] == 35
    assert client.get(f"/api/photos/{pid}").json()["edit_level"]["level"] in ("light", "moderate")
    assert client.get("/api/limits").json()["enabled"] is True
    s = client.get("/api/settings").json()
    client.put("/api/settings", json={**s, "natural_limits": False})
    res = client.put(f"/api/photos/{pid}/recipe", json={"strength": 150, "sliders": {"color": 90}}).json()
    assert res["recipe"]["sliders"]["color"] == 90 and res["edit_level"]["level"] == "strong"
