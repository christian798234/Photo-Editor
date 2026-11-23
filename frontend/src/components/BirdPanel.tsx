import type { Photo, Recipe, SubjectStatus } from "../types";

export type SelectTool = "off" | "add" | "remove";

interface Props {
  photo: Photo;
  recipe: Recipe;
  status: SubjectStatus | null;
  busy: boolean;
  showMask: boolean;
  setShowMask: (v: boolean) => void;
  tool: SelectTool;
  setTool: (t: SelectTool) => void;
  onEnable: (on: boolean) => void;
  onDetect: () => void;
  onAccept: () => void;
  onClear: () => void;
  onChange: (r: Recipe) => void;
}

export function BirdPanel(p: Props) {
  const { photo, recipe, status } = p;
  const ready = photo.decode_status === "supported";
  if (!status) return null;
  if (!status.installed) {
    return (
      <section className="bird-panel">
        <h3>Bird selection</h3>
        <p className="small muted">Bird detection isn't installed in this copy of the app (it is an optional part of the installer).
          Editing works normally on the whole photo.</p>
      </section>
    );
  }
  if (status.enabled === null || status.enabled === false) {
    return (
      <section className="bird-panel consent">
        <h3>Bird selection</h3>
        <p className="small">Let the app find the bird in each photo so it can measure exposure on the bird, reduce noise more
          in the background than on the feathers, and suggest crops.</p>
        <p className="small muted">Uses the local detection models included with the app ({status.models.map((m) => m.name).join(", ")};
          Apache-2.0). Runs on this computer only, and nothing is uploaded. Adds a second or two per photo.</p>
        <div className="row">
          <button className="primary" onClick={() => p.onEnable(true)}>Turn on bird detection</button>
          {status.enabled === null && <button onClick={() => p.onEnable(false)}>Not now</button>}
        </div>
      </section>
    );
  }
  const m = photo.mask;
  const usable = !!m?.usable;
  const statusText = !m ? "Not detected yet. Auto Edit will look for the bird."
    : m.status === "good" ? `${m.message}${m.source === "refined" ? " (adjusted by you)" : ""}`
    : m.accepted ? "Using an uncertain selection because you chose “Use anyway”."
    : m.message;
  return (
    <section className="bird-panel">
      <h3>Bird selection</h3>
      <p className={`small ${usable ? "ok-text" : m?.status === "uncertain" ? "warn" : "muted"}`} role="status">{statusText}</p>
      <div className="row">
        <button disabled={!ready || p.busy} onClick={p.onDetect}>{m ? "Detect again" : "Detect bird"}</button>
        {m?.has_mask && (
          <label className="check"><input type="checkbox" checked={p.showMask} onChange={(e) => p.setShowMask(e.target.checked)} /> Show selection</label>
        )}
      </div>
      <div className="row" role="radiogroup" aria-label="Selection tool">
        <span className="small muted">Fix by clicking:</span>
        <button role="radio" aria-checked={p.tool === "add"} className={p.tool === "add" ? "active" : ""} disabled={!ready || p.busy}
          onClick={() => p.setTool(p.tool === "add" ? "off" : "add")} title="Click on parts of the bird that were missed">+ Bird</button>
        <button role="radio" aria-checked={p.tool === "remove"} className={p.tool === "remove" ? "active" : ""} disabled={!ready || p.busy || !m?.has_mask}
          onClick={() => p.setTool(p.tool === "remove" ? "off" : "remove")} title="Click on areas that are not the bird">− Not bird</button>
      </div>
      {m?.status === "uncertain" && m.has_mask && !m.accepted && (
        <button onClick={p.onAccept}>Use anyway</button>
      )}
      {m && <button className="ghost small-btn" onClick={p.onClear}>Clear selection</button>}

      <label className="check">
        <input type="checkbox" checked={recipe.subject.use_mask} disabled={!usable}
          onChange={(e) => p.onChange({ ...recipe, subject: { ...recipe.subject, use_mask: e.target.checked,
            background_nr: e.target.checked && recipe.subject.background_nr === 0 ? 25 : recipe.subject.background_nr } })} />
        Bird-aware processing
      </label>
      <div className="slider-row">
        <div className="slider-head">
          <label htmlFor="sl-bgnr">Background noise reduction</label>
          <output htmlFor="sl-bgnr">{Math.round(recipe.subject.background_nr)}</output>
        </div>
        <input id="sl-bgnr" type="range" min={0} max={100} step={1} value={recipe.subject.background_nr}
          disabled={!recipe.subject.use_mask || !usable}
          onChange={(e) => p.onChange({ ...recipe, subject: { ...recipe.subject, background_nr: Number(e.target.value) } })} />
        <div className="slider-hint">{usable ? "Extra smoothing outside the bird; the bird keeps its feather texture."
          : "Available when a reliable bird selection exists."}</div>
      </div>
    </section>
  );
}
