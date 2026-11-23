"""'Less is more': limits that keep edits looking like a photograph.

* ``NATURAL_LIMITS`` caps every adjustment (manual or automatic) when the
  "Keep edits natural" setting is on (the default). The limits are applied on
  the server, so previews and exports always respect them.
* ``edit_level`` rates how strong an edit is from its effective values and
  lists what makes it strong, so the photographer can see when an edit is
  drifting toward a processed look.

Nothing here adds, removes or synthesises image content; the app never does.
"""

from __future__ import annotations

from .recipe import Recipe, effective

# Raw-value ceilings (with strength capped at 100% these are also the
# effective ceilings).
NATURAL_LIMITS: dict[str, tuple[float, float]] = {
    "strength": (0, 100),
    "exposure": (-2.0, 2.0),
    "warmth": (-40, 40),
    "highlights": (-70, 30),
    "shadows": (-40, 40),
    "color": (-50, 25),
    "noise_reduction": (0, 60),
    "detail": (0, 50),
    "tint": (-30, 30),
    "contrast": (-20, 20),
    "black": (0, 3),
    "clarity": (0, 15),
    "background_nr": (0, 60),
}

# Beyond these effective values an adjustment counts as "noticeable".
NOTICEABLE: dict[str, float] = {
    "exposure": 1.0, "warmth": 20, "tint": 15, "highlights": 50, "shadows": 25, "color": 15,
    "contrast": 14, "black": 2, "clarity": 8, "noise_reduction": 45, "detail": 40, "background_nr": 45,
}

LABELS = {
    "exposure": "exposure", "warmth": "warmth", "tint": "tint", "highlights": "highlights",
    "shadows": "shadow lift", "color": "color intensity", "contrast": "contrast", "black": "black point",
    "clarity": "local contrast", "noise_reduction": "noise reduction", "detail": "sharpening",
    "background_nr": "background noise reduction", "strength": "edit strength",
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)


def apply_limits(recipe: Recipe) -> Recipe:
    """Return the recipe with every value inside the natural limits."""
    L = NATURAL_LIMITS
    sl = recipe.sliders.model_dump()
    for k in sl:
        sl[k] = _clamp(sl[k], *L[k])
    it = recipe.internal.model_dump()
    for k in it:
        it[k] = _clamp(it[k], *L[k])
    subj = recipe.subject.model_dump()
    subj["background_nr"] = _clamp(subj["background_nr"], *L["background_nr"])
    return Recipe.model_validate({**recipe.model_dump(), "strength": _clamp(recipe.strength, *L["strength"]),
                                  "sliders": sl, "internal": it, "subject": subj})


def within_limits(recipe: Recipe) -> bool:
    return apply_limits(recipe) == recipe


def edit_level(recipe: Recipe) -> dict:
    """{'level': 'none'|'light'|'moderate'|'strong', 'notes': [...]}"""
    e = effective(recipe)
    vals = {"exposure": abs(e.exposure), "warmth": abs(e.warmth), "tint": abs(e.tint),
            "highlights": abs(e.highlights) if e.highlights < 0 else e.highlights * 2,
            "shadows": abs(e.shadows), "color": max(e.color, 0), "contrast": abs(e.contrast),
            "black": e.black, "clarity": e.clarity, "noise_reduction": e.noise_reduction,
            "detail": e.detail, "background_nr": e.background_nr}
    if e.is_identity:
        return {"level": "none", "notes": []}
    beyond = [k for k, v in vals.items() if v > NOTICEABLE[k] + 1e-9]
    over = [k for k in NATURAL_LIMITS
            if k in vals and k != "strength" and getattr(e, k) is not None and
            not (NATURAL_LIMITS[k][0] - 1e-9 <= getattr(e, k) <= NATURAL_LIMITS[k][1] + 1e-9)]
    if recipe.strength > 100:
        over.append("strength")
    notes = []
    if over:
        notes.append("Beyond the natural limits: " + ", ".join(LABELS[k] for k in over) + ".")
        level = "strong"
    elif len(beyond) >= 3:
        level = "strong"
    elif beyond:
        level = "moderate"
    else:
        level = "light"
    if beyond:
        notes.append("Noticeable: " + ", ".join(LABELS[k] for k in beyond) + ".")
    if level == "strong":
        notes.append("This may start to look processed. Lowering Overall edit strength is the simplest fix.")
    return {"level": level, "notes": notes}
