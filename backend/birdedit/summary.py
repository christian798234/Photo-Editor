"""Plain-language edit summary generated from the actual parameters."""

from __future__ import annotations

from .recipe import Recipe, effective


def summarize(recipe: Recipe, facts: dict | None = None) -> str:
    facts = facts or {}
    e = effective(recipe)
    parts: list[str] = []
    if e.exposure >= 0.7:
        parts.append(f"brightened the image ({e.exposure:+.1f} EV)")
    elif e.exposure >= 0.1:
        parts.append(f"brightened the image slightly ({e.exposure:+.1f} EV)")
    elif e.exposure <= -0.7:
        parts.append(f"darkened the image ({e.exposure:+.1f} EV)")
    elif e.exposure <= -0.1:
        parts.append(f"darkened the image slightly ({e.exposure:+.1f} EV)")
    if e.highlights <= -10:
        parts.append("protected bright highlights")
    elif e.highlights >= 10:
        parts.append("brightened the highlights")
    if e.shadows >= 10:
        parts.append("lifted dark areas moderately" if e.shadows < 40 else "lifted dark areas")
    elif e.shadows <= -10:
        parts.append("deepened the shadows")
    if e.warmth >= 3:
        parts.append("warmed the color slightly" if e.warmth < 25 else "warmed the color")
    elif e.warmth <= -3:
        parts.append("cooled the color slightly" if e.warmth > -25 else "cooled the color")
    if abs(e.tint) >= 3:
        parts.append("corrected a slight color tint")
    if e.black > 0.4:
        parts.append("reduced haze in the darkest tones")
    if e.contrast >= 15:
        parts.append("added contrast")
    elif e.contrast >= 4:
        parts.append("added a little contrast")
    elif e.contrast <= -4:
        parts.append("reduced contrast")
    if e.color >= 25:
        parts.append("increased color intensity")
    elif e.color >= 4:
        parts.append("added a little color intensity")
    elif e.color <= -4:
        parts.append("reduced color intensity")
    if e.noise_reduction >= 5:
        sigma = facts.get("noise_sigma_display")
        if sigma is not None and sigma < 0.0015:
            level = "light"
        elif sigma is not None and sigma > 0.006:
            level = "strong" if e.noise_reduction >= 50 else "moderate"
        else:
            level = "moderate" if e.noise_reduction >= 35 else "light"
        if e.use_mask:
            extra = "much stronger" if e.background_nr >= 40 else "stronger"
            parts.append(f"applied {level} noise reduction to the bird and {extra} noise reduction to the background")
        else:
            parts.append(f"applied {level} noise reduction across the whole image")
    elif e.use_mask and e.background_nr >= 5:
        parts.append("reduced noise in the background only")
    if e.detail >= 5:
        parts.append("applied restrained sharpening" if e.detail < 50 else "applied extra sharpening")
    if e.clarity >= 5:
        parts.append("added gentle local contrast")

    if not parts:
        text = "No adjustments: this is the baseline RAW rendering."
    else:
        text = parts[0][0].upper() + parts[0][1:]
        if len(parts) > 1:
            text += ", " + ", ".join(parts[1:-1]) + (", and " if len(parts) > 2 else " and ") + parts[-1]
        text += "."
    if recipe.crop is not None:
        text += " Cropped."
    if e.use_mask:
        text += (" Bird selected with the local detection model" +
                 (" (exposure measured on the bird)." if facts.get("metering") == "bird" else "."))
    clipped = facts.get("clipped_fraction", 0.0)
    if clipped >= 0.002:
        text += (f" About {clipped * 100:.1f}% of the photo was overexposed in camera; "
                 "detail in those areas cannot be recovered.")
    return text
