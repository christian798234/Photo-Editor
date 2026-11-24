import { cropPixels, fitAspect, fullCrop } from "../crop";
import { IconCrop, IconPalette, IconSparkle, IconSun, IconWand } from "../icons";
import type { Aspect, Crop, Internal, Limits, Photo, Recipe, Sliders } from "../types";
import { InfoTip, Section, Slider, type SliderDef } from "../ui";

type SKey = keyof Sliders;
type IKey = keyof Internal;

const DEF: Record<string, SliderDef> = {
  exposure: { key: "exposure", label: "Exposure", min: -3, max: 3, step: 0.05, unit: " EV" },
  highlights: { key: "highlights", label: "Highlights", min: -100, max: 100, step: 1, hint: "Negative values protect bright and white feathers." },
  shadows: { key: "shadows", label: "Shadows", min: -100, max: 100, step: 1 },
  contrast: { key: "contrast", label: "Contrast", min: -30, max: 40, step: 0.5 },
  black: { key: "black", label: "Black point", min: 0, max: 5, step: 0.1, unit: "%" },
  warmth: { key: "warmth", label: "Warmth", min: -100, max: 100, step: 1, hint: "Cooler ← → warmer." },
  tint: { key: "tint", label: "Tint", min: -100, max: 100, step: 1, hint: "Green ← → magenta." },
  color: { key: "color", label: "Color intensity", min: -100, max: 100, step: 1, hint: "Muted colours gain most; vivid plumage is protected." },
  noise_reduction: { key: "noise_reduction", label: "Noise reduction", min: 0, max: 100, step: 1, hint: "Smooths noise. It cannot restore detail that was never recorded." },
  detail: { key: "detail", label: "Sharpening", min: 0, max: 100, step: 1, hint: "Capture sharpening. Judge it at 100% zoom." },
  clarity: { key: "clarity", label: "Local contrast", min: 0, max: 40, step: 1 },
  strength: { key: "strength", label: "Edit strength", min: 0, max: 150, step: 1, unit: "%", hint: "0% shows the unedited photo; 100% is the full edit." },
};

const ASPECTS: { v: Aspect; label: string }[] = [
  { v: "original", label: "Original" }, { v: "free", label: "Free" }, { v: "3:2", label: "3:2" },
  { v: "4:3", label: "4:3" }, { v: "1:1", label: "1:1" }, { v: "16:9", label: "16:9" },
];

const LOOKS = [
  { v: "natural", label: "Natural", hint: "Your camera's look, cleaned up." },
  { v: "crisp", label: "Crisp", hint: "A little more detail and contrast." },
  { v: "soft_background", label: "Soft background", hint: "Stronger background noise reduction. Needs a bird selection." },
] as const;

interface Props {
  photo: Photo;
  recipe: Recipe;
  onChange: (r: Recipe) => void;
  onLook: (look: "natural" | "crisp" | "soft_background") => void;
  busy: boolean;
  autoRecipe: Recipe | null;
  maskUsable: boolean;
  onSuggestCrop: (aspect: Aspect, portrait: boolean) => void;
  limits: Limits | null;
  onToggleLimits: (on: boolean) => void;
  cropDraft: Crop | null;
  setCropDraft: (c: Crop | null) => void;
}

export function Adjustments({ photo, recipe, onChange, onLook, busy, autoRecipe, maskUsable, onSuggestCrop,
  limits, onToggleLimits, cropDraft, setCropDraft }: Props) {
  // With "Keep edits natural" on, sliders only cover the natural range.
  const lim = (d: SliderDef): SliderDef => {
    const l = limits?.enabled ? limits.limits[d.key] : undefined;
    return l ? { ...d, min: Math.max(d.min, l[0]), max: Math.min(d.max, l[1]) } : d;
  };
  const ready = photo.decode_status === "supported";
  const fullSize = photo.full_size ?? [0, 0];
  const [cw, ch] = cropPixels(recipe.crop, fullSize);

  const s = (k: SKey) => (
    <Slider key={k} def={lim(DEF[k])} value={recipe.sliders[k]} disabled={!ready}
      onChange={(v) => onChange({ ...recipe, sliders: { ...recipe.sliders, [k]: v } })}
      resetTo={autoRecipe ? autoRecipe.sliders[k] : undefined} />
  );
  const i = (k: IKey) => (
    <Slider key={k} def={lim(DEF[k])} value={recipe.internal[k]} disabled={!ready}
      onChange={(v) => onChange({ ...recipe, internal: { ...recipe.internal, [k]: v } })}
      resetTo={autoRecipe ? autoRecipe.internal[k] : undefined} />
  );
  const setAspect = (a: Aspect) => cropDraft && setCropDraft(fitAspect({ ...cropDraft, aspect: a }, fullSize));

  return (
    <div className="adjustments" aria-disabled={!ready}>
      <Section id="edit" title="Edit" icon={<IconWand size={16} />}>
        <div className="chips" role="radiogroup" aria-label="Look">
          {LOOKS.map((l) => {
            const active = recipe.look === l.v && recipe.auto_applied;
            const disabled = !ready || busy || (l.v === "soft_background" && !maskUsable);
            return (
              <button key={l.v} role="radio" aria-checked={active} className={`chip ${active ? "active" : ""}`}
                disabled={disabled} onClick={() => onLook(l.v)}
                title={l.v === "soft_background" && !maskUsable ? "Needs a reliable bird selection (Bird section)" : l.hint}>
                {l.label}
              </button>
            );
          })}
        </div>
        <Slider def={lim(DEF.strength)} value={recipe.strength} disabled={!ready} resetTo={100}
          onChange={(v) => onChange({ ...recipe, strength: v })} />
        <label className="switch-row">
          <span className="switch">
            <input type="checkbox" checked={!!limits?.enabled} onChange={(e) => onToggleLimits(e.target.checked)} />
            <span className="switch-track" aria-hidden="true" />
          </span>
          <span>Keep edits natural</span>
          <InfoTip text="Caps every adjustment, including exports, so photos never look over-processed. Recommended." />
        </label>
      </Section>

      <Section id="light" title="Light" icon={<IconSun size={16} />}>
        {s("exposure")}{s("highlights")}{s("shadows")}{i("contrast")}{i("black")}
      </Section>

      <Section id="color" title="Color" icon={<IconPalette size={16} />}>
        {s("warmth")}{i("tint")}{s("color")}
      </Section>

      <Section id="detail" title="Detail" icon={<IconSparkle size={16} />}>
        {s("detail")}{s("noise_reduction")}{i("clarity")}
      </Section>

      <Section id="crop" title="Crop" icon={<IconCrop size={16} />}
        right={<span className="muted mono">{cw} × {ch}</span>}>
        {!cropDraft ? (
          <div className="btn-row">
            <button className="btn" disabled={!ready} onClick={() => setCropDraft(recipe.crop ?? fullCrop("original"))}>
              {recipe.crop ? "Edit crop" : "Crop photo"}</button>
            {recipe.crop && <button className="btn ghost" onClick={() => onChange({ ...recipe, crop: null })}>Remove</button>}
          </div>
        ) : (
          <>
            <div className="chips" role="radiogroup" aria-label="Aspect ratio">
              {ASPECTS.map((a) => (
                <button key={a.v} role="radio" aria-checked={cropDraft.aspect === a.v}
                  className={`chip ${cropDraft.aspect === a.v ? "active" : ""}`} onClick={() => setAspect(a.v)}>{a.label}</button>
              ))}
            </div>
            <label className="switch-row">
              <span className="switch">
                <input type="checkbox" checked={cropDraft.portrait} disabled={cropDraft.aspect === "free" || cropDraft.aspect === "1:1"}
                  onChange={(e) => setCropDraft(fitAspect({ ...cropDraft, portrait: e.target.checked }, fullSize))} />
                <span className="switch-track" aria-hidden="true" />
              </span>
              <span>Portrait orientation</span>
            </label>
            <button className="btn wide" disabled={!maskUsable} onClick={() => onSuggestCrop(cropDraft.aspect, cropDraft.portrait)}
              title={maskUsable ? "Propose a crop that keeps the whole bird" : "Needs a reliable bird selection"}>
              Suggest crop around the bird</button>
            <div className="btn-row">
              <button className="btn primary" onClick={() => {
                const full = cropDraft.x <= 0.0005 && cropDraft.y <= 0.0005 && cropDraft.w >= 0.999 && cropDraft.h >= 0.999;
                onChange({ ...recipe, crop: full ? null : cropDraft });
                setCropDraft(null);
              }}>Apply crop</button>
              <button className="btn" onClick={() => setCropDraft(fullCrop(cropDraft.aspect === "free" ? "free" : cropDraft.aspect))}>Reset</button>
              <button className="btn ghost" onClick={() => setCropDraft(null)}>Cancel</button>
            </div>
          </>
        )}
      </Section>
    </div>
  );
}
