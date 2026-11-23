import { useState } from "react";
import { cropPixels, fitAspect, fullCrop } from "../crop";
import type { Aspect, Crop, Internal, Limits, Photo, Recipe, Sliders } from "../types";

interface SliderDef<K> { key: K; label: string; min: number; max: number; step: number; unit?: string; hint?: string }

const SIMPLE: SliderDef<keyof Sliders>[] = [
  { key: "exposure", label: "Exposure", min: -3, max: 3, step: 0.05, unit: " EV" },
  { key: "warmth", label: "Warmth", min: -100, max: 100, step: 1, hint: "Cooler ← → Warmer" },
  { key: "highlights", label: "Highlights", min: -100, max: 100, step: 1, hint: "Negative values protect bright feathers" },
  { key: "shadows", label: "Shadows", min: -100, max: 100, step: 1 },
  { key: "color", label: "Color intensity", min: -100, max: 100, step: 1 },
  { key: "noise_reduction", label: "Noise reduction", min: 0, max: 100, step: 1, hint: "Smooths noise; it cannot restore lost detail" },
  { key: "detail", label: "Detail / sharpness", min: 0, max: 100, step: 1, hint: "Judge at 100% zoom" },
];

const ADVANCED: SliderDef<keyof Internal>[] = [
  { key: "tint", label: "Tint (green ↔ magenta)", min: -100, max: 100, step: 1 },
  { key: "contrast", label: "Contrast", min: -30, max: 40, step: 0.5 },
  { key: "black", label: "Black point", min: 0, max: 5, step: 0.1, unit: "%" },
  { key: "clarity", label: "Local contrast", min: 0, max: 40, step: 1 },
];

const ASPECTS: { v: Aspect; label: string }[] = [
  { v: "original", label: "Original" }, { v: "free", label: "Free" }, { v: "3:2", label: "3:2" },
  { v: "4:3", label: "4:3" }, { v: "1:1", label: "1:1" }, { v: "16:9", label: "16:9" },
];

function Slider(props: { def: SliderDef<string>; value: number; disabled?: boolean; onChange: (v: number) => void;
  resetTo?: number }) {
  const { def, value } = props;
  const resetTo = props.resetTo ?? 0;
  const id = `sl-${def.key}`;
  const shown = def.step < 1 ? value.toFixed(def.step < 0.1 ? 2 : 1) : String(Math.round(value));
  return (
    <div className="slider-row">
      <div className="slider-head">
        <label htmlFor={id}>{def.label}</label>
        <span className="slider-value">
          <output htmlFor={id}>{value > 0 && def.min < 0 ? "+" : ""}{shown}{def.unit ?? ""}</output>
          <button className="reset-btn" disabled={props.disabled || value === resetTo} onClick={() => props.onChange(resetTo)}
            aria-label={`Reset ${def.label}`} title={props.resetTo !== undefined ? "Back to the Auto Edit value" : "Back to zero"}>↺</button>
        </span>
      </div>
      <input id={id} type="range" min={def.min} max={def.max} step={def.step} value={value}
        disabled={props.disabled} aria-describedby={def.hint ? `${id}-hint` : undefined}
        onChange={(e) => props.onChange(Number(e.target.value))}
        onDoubleClick={() => props.onChange(resetTo)} />
      {def.hint && <div className="slider-hint" id={`${id}-hint`}>{def.hint}</div>}
    </div>
  );
}

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
  const lim = <K extends string>(d: SliderDef<K>): SliderDef<K> => {
    const l = limits?.enabled ? limits.limits[d.key] : undefined;
    return l ? { ...d, min: Math.max(d.min, l[0]), max: Math.min(d.max, l[1]) } : d;
  };
  const [showAdvanced, setShowAdvanced] = useState(false);
  const ready = photo.decode_status === "supported";
  const setSlider = (k: keyof Sliders, v: number) => onChange({ ...recipe, sliders: { ...recipe.sliders, [k]: v } });
  const setInternal = (k: keyof Internal, v: number) => onChange({ ...recipe, internal: { ...recipe.internal, [k]: v } });
  const fullSize = photo.full_size ?? [0, 0];

  const startCrop = () => setCropDraft(recipe.crop ?? fullCrop("original"));
  const setAspect = (a: Aspect) => cropDraft && setCropDraft(fitAspect({ ...cropDraft, aspect: a }, fullSize));
  const [cw, ch] = cropPixels(recipe.crop, fullSize);

  return (
    <div className="adjustments" aria-disabled={!ready}>
      <fieldset className="looks" disabled={!ready || busy}>
        <legend>Look</legend>
        <div className="look-buttons" role="radiogroup" aria-label="Look">
          {(["natural", "crisp"] as const).map((l) => (
            <button key={l} role="radio" aria-checked={recipe.look === l && recipe.auto_applied}
              className={recipe.look === l && recipe.auto_applied ? "active" : ""} onClick={() => onLook(l)}>
              {l === "natural" ? "Natural" : "Crisp Detail"}
            </button>
          ))}
          <button role="radio" aria-checked={recipe.look === "soft_background" && recipe.auto_applied}
            className={recipe.look === "soft_background" && recipe.auto_applied ? "active" : ""}
            disabled={!maskUsable} onClick={() => onLook("soft_background")}
            title={maskUsable ? "Stronger noise reduction on the background only" : "Needs a reliable bird selection (see Bird selection below)"}>
            Soft Background
          </button>
        </div>
        <p className="small muted">Choosing a look re-runs Auto Edit in that style. Soft Background smooths background noise
          more strongly (it never blurs or replaces the background) and needs a reliable bird selection.</p>
      </fieldset>

      <Slider def={lim({ key: "strength", label: "Overall edit strength", min: 0, max: 150, step: 1, unit: "%",
        hint: "0% = the unedited baseline" })} value={recipe.strength} disabled={!ready} resetTo={100}
        onChange={(v) => onChange({ ...recipe, strength: v })} />

      {SIMPLE.map((d) => (
        <Slider key={d.key} def={lim(d)} value={recipe.sliders[d.key]} disabled={!ready} onChange={(v) => setSlider(d.key, v)}
          resetTo={autoRecipe ? autoRecipe.sliders[d.key] : undefined} />
      ))}

      <section className="crop-section">
        <h3>Crop</h3>
        {!cropDraft ? (
          <div className="row">
            <button disabled={!ready} onClick={startCrop}>{recipe.crop ? "Edit crop" : "Crop…"}</button>
            {recipe.crop && <button onClick={() => onChange({ ...recipe, crop: null })}>Remove crop</button>}
            <span className="small muted">{cw} × {ch} px</span>
          </div>
        ) : (
          <>
            <div className="aspect-buttons" role="radiogroup" aria-label="Aspect ratio">
              {ASPECTS.map((a) => (
                <button key={a.v} role="radio" aria-checked={cropDraft.aspect === a.v}
                  className={cropDraft.aspect === a.v ? "active" : ""} onClick={() => setAspect(a.v)}>{a.label}</button>
              ))}
            </div>
            <label className="check">
              <input type="checkbox" checked={cropDraft.portrait} disabled={cropDraft.aspect === "free" || cropDraft.aspect === "1:1"}
                onChange={(e) => setCropDraft(fitAspect({ ...cropDraft, portrait: e.target.checked }, fullSize))} /> Portrait orientation
            </label>
            <div className="row">
              <button className="primary" onClick={() => {
                const full = cropDraft.x <= 0.0005 && cropDraft.y <= 0.0005 && cropDraft.w >= 0.999 && cropDraft.h >= 0.999;
                onChange({ ...recipe, crop: full ? null : cropDraft });
                setCropDraft(null);
              }}>Apply crop</button>
              <button onClick={() => setCropDraft(fullCrop(cropDraft.aspect === "free" ? "free" : cropDraft.aspect))}>Reset</button>
              <button onClick={() => setCropDraft(null)}>Cancel</button>
            </div>
            <button disabled={!maskUsable} onClick={() => onSuggestCrop(cropDraft.aspect, cropDraft.portrait)}
              title={maskUsable ? "Propose a crop that keeps the whole bird" : "Needs a reliable bird selection"}>Suggest crop</button>
            <p className="small muted">{maskUsable ? "The suggestion keeps the whole bird with some space around it. Adjust it before applying."
              : "Crop suggestions need a reliable bird selection."}</p>
          </>
        )}
      </section>

      <button className="disclosure" aria-expanded={showAdvanced} onClick={() => setShowAdvanced((s) => !s)}>
        {showAdvanced ? "▾" : "▸"} Advanced
      </button>
      {showAdvanced && (
        <div className="advanced">
          <label className="check">
            <input type="checkbox" checked={!!limits?.enabled} onChange={(e) => onToggleLimits(e.target.checked)} />
            Keep edits natural (recommended)
          </label>
          <p className="small muted">Caps every adjustment, including exports, so photos never look over-processed.
            Turning it off allows stronger edits.</p>
          <p className="small muted">These are set automatically by Auto Edit for each photo.</p>
          {ADVANCED.map((d) => (
            <Slider key={d.key} def={lim(d)} value={recipe.internal[d.key]} disabled={!ready} onChange={(v) => setInternal(d.key, v)}
              resetTo={autoRecipe ? autoRecipe.internal[d.key] : undefined} />
          ))}
        </div>
      )}
    </div>
  );
}
