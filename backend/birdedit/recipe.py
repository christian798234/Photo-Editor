"""Edit recipes: the complete, versioned description of an edit.

A recipe is stored as JSON next to (never inside) the original. It contains
only user-facing values plus a few automatically estimated internal values;
camera white-balance multipliers live in the decoder info, not here, so
copying a recipe between cameras never transfers one camera's colour data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import PIPELINE_VERSION

Look = Literal["natural", "crisp", "soft_background"]
Aspect = Literal["original", "free", "3:2", "4:3", "1:1", "16:9"]


class Sliders(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exposure: float = Field(0.0, ge=-3.0, le=3.0)          # EV
    warmth: float = Field(0.0, ge=-100, le=100)
    highlights: float = Field(0.0, ge=-100, le=100)        # <0 protects/recovers
    shadows: float = Field(0.0, ge=-100, le=100)
    color: float = Field(0.0, ge=-100, le=100)
    noise_reduction: float = Field(0.0, ge=0, le=100)
    detail: float = Field(0.0, ge=0, le=100)


class Internal(BaseModel):
    """Image-dependent values set by Auto Edit (shown read-only in Advanced)."""
    model_config = ConfigDict(extra="forbid")
    tint: float = Field(0.0, ge=-100, le=100)
    contrast: float = Field(0.0, ge=-30, le=40)
    black: float = Field(0.0, ge=0, le=5)                   # % of display range
    clarity: float = Field(0.0, ge=0, le=40)


class Crop(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aspect: Aspect = "free"
    portrait: bool = False
    x: float = Field(0.0, ge=0, le=1)
    y: float = Field(0.0, ge=0, le=1)
    w: float = Field(1.0, gt=0, le=1)
    h: float = Field(1.0, gt=0, le=1)

    @model_validator(mode="after")
    def _inside(self) -> "Crop":
        if self.x + self.w > 1.0001 or self.y + self.h > 1.0001:
            raise ValueError("crop rectangle must lie inside the image")
        return self


class Subject(BaseModel):
    """Bird-aware processing. Only valid when the photo has a usable mask;
    the server rejects recipes that ask for it otherwise."""
    model_config = ConfigDict(extra="forbid")
    use_mask: bool = False
    background_nr: float = Field(0.0, ge=0, le=100)   # extra noise reduction outside the bird


class Recipe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    pipeline_version: str = PIPELINE_VERSION
    look: Look = "natural"
    strength: float = Field(100.0, ge=0, le=150)           # percent
    sliders: Sliders = Field(default_factory=Sliders)
    internal: Internal = Field(default_factory=Internal)
    subject: Subject = Field(default_factory=Subject)
    crop: Optional[Crop] = None
    auto_applied: bool = False

    @property
    def needs_mask(self) -> bool:
        return self.look == "soft_background" or self.subject.use_mask


def baseline_recipe() -> Recipe:
    """The documented 'Before' rendering: decoder output + sRGB, no edits."""
    return Recipe()


USER_FACING_KEYS = ("look", "strength", "sliders")  # subject settings are per photo (mask-dependent)


@dataclass(frozen=True)
class Effective:
    """Recipe values after applying the edit-strength multiplier."""
    exposure: float
    warmth: float
    tint: float
    highlights: float
    shadows: float
    contrast: float
    black: float
    color: float
    noise_reduction: float
    detail: float
    clarity: float
    use_mask: bool = False
    background_nr: float = 0.0

    @property
    def is_identity(self) -> bool:
        return all(abs(float(v)) < 1e-9 for v in self.__dict__.values())


def effective(recipe: Recipe) -> Effective:
    s = recipe.strength / 100.0
    sl, it = recipe.sliders, recipe.internal
    return Effective(
        exposure=sl.exposure * s, warmth=sl.warmth * s, tint=it.tint * s,
        highlights=sl.highlights * s, shadows=sl.shadows * s,
        contrast=it.contrast * s, black=it.black * s, color=sl.color * s,
        noise_reduction=sl.noise_reduction * s, detail=sl.detail * s,
        clarity=it.clarity * s,
        use_mask=recipe.subject.use_mask,
        background_nr=recipe.subject.background_nr * s if recipe.subject.use_mask else 0.0,
    )
