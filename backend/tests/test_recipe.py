import pytest
from pydantic import ValidationError

from birdedit.config import AppPaths
from birdedit.recipe import Crop, Recipe, Sliders, effective
from birdedit.store import Store


def test_validation_limits():
    with pytest.raises(ValidationError):
        Sliders(exposure=5)
    with pytest.raises(ValidationError):
        Sliders(noise_reduction=-1)
    with pytest.raises(ValidationError):
        Recipe(strength=200)
    with pytest.raises(ValidationError):
        Crop(x=0.5, w=0.6)
    with pytest.raises(ValidationError):
        Recipe.model_validate({"sliders": {"exposure": 1, "unknown_key": 3}})


def test_mask_dependent_recipes_are_flagged():
    assert Recipe(look="soft_background").needs_mask
    assert Recipe(subject={"use_mask": True}).needs_mask
    assert not Recipe().needs_mask
    with pytest.raises(ValidationError):
        Recipe(subject={"background_nr": 500})


def test_strength_scales_everything():
    r = Recipe(strength=50, sliders=Sliders(exposure=1.0, detail=40))
    e = effective(r)
    assert e.exposure == 0.5 and e.detail == 20
    assert effective(Recipe(strength=0, sliders=Sliders(exposure=2))).is_identity


def test_recipe_persistence_roundtrip(tmp_path):
    store = Store(AppPaths(tmp_path / "d"))
    src = tmp_path / "photo.jpg"
    src.write_bytes(b"x")
    rec = store.create(src, "linked", "photo.jpg")
    r = Recipe(look="crisp", strength=80, sliders=Sliders(exposure=0.35, warmth=-7),
               crop=Crop(aspect="3:2", x=0.1, y=0.1, w=0.6, h=0.4), auto_applied=True)
    store.put_recipe(rec["id"], r)
    # Reopen the project from disk.
    store2 = Store(AppPaths(tmp_path / "d"))
    assert store2.get_recipe(rec["id"]) == r
    assert [p["id"] for p in store2.list()] == [rec["id"]]
    saved = (store.photo_dir(rec["id"]) / "recipe.json").read_text()
    assert '"pipeline_version"' in saved


def test_invalid_ids_are_rejected(tmp_path):
    from birdedit.store import NotFound
    store = Store(AppPaths(tmp_path / "d"))
    for bad in ["../../etc", "a" * 31, "ZZ" * 16, "..\\x"]:
        with pytest.raises(NotFound):
            store.get(bad)
