import { IconBird } from "../icons";
import type { Photo, Recipe, SubjectStatus } from "../types";
import { InfoTip, Section, Slider } from "../ui";

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
  const m = photo.mask;
  const usable = !!m?.usable;
  const badge = !status.installed ? null : !status.enabled ? <span className="tag">Off</span>
    : usable ? <span className="tag ok">Selected</span> : m?.status === "uncertain" ? <span className="tag warn">Uncertain</span>
    : m ? <span className="tag">No bird</span> : null;

  let body;
  if (!status.installed) {
    body = <p className="note">Bird detection isn't installed in this copy of the app (optional installer component).
      Editing works normally on the whole photo.</p>;
  } else if (!status.enabled) {
    body = (
      <div className="callout accent">
        <p><strong>Let the app find the bird.</strong> Exposure is measured on the bird, the background gets more noise
          reduction than the feathers, and crops can be suggested.</p>
        <p className="muted">Runs on this computer only; nothing is uploaded.
          <InfoTip text={`Models: ${status.models.map((x) => x.name).join(", ")} (Apache-2.0).`} /></p>
        <div className="btn-row">
          <button className="btn primary" onClick={() => p.onEnable(true)}>Turn on bird detection</button>
          {status.enabled === null && <button className="btn ghost" onClick={() => p.onEnable(false)}>Not now</button>}
        </div>
      </div>
    );
  } else {
    const statusText = !m ? "Not detected yet. Auto Edit will look for the bird."
      : m.status === "good" ? `${m.message}${m.source === "refined" ? " (adjusted by you)" : ""}`
      : m.accepted ? "Using an uncertain selection (you chose “Use anyway”)." : m.message;
    body = (
      <>
        <p className={`note ${usable ? "ok" : m?.status === "uncertain" ? "warn" : ""}`} role="status">{statusText}</p>
        <div className="btn-row">
          <button className="btn" disabled={!ready || p.busy} onClick={p.onDetect}>{m ? "Detect again" : "Detect bird"}</button>
          {m?.has_mask && (
            <label className="switch-row inline">
              <span className="switch"><input type="checkbox" checked={p.showMask} onChange={(e) => p.setShowMask(e.target.checked)} />
                <span className="switch-track" aria-hidden="true" /></span>
              <span>Show</span>
            </label>
          )}
        </div>
        <div className="seg-control" role="radiogroup" aria-label="Selection tool">
          <button role="radio" aria-checked={p.tool === "add"} className={p.tool === "add" ? "active" : ""} disabled={!ready || p.busy}
            onClick={() => p.setTool(p.tool === "add" ? "off" : "add")} title="Click parts of the bird that were missed">+ Bird</button>
          <button role="radio" aria-checked={p.tool === "remove"} className={p.tool === "remove" ? "active" : ""} disabled={!ready || p.busy || !m?.has_mask}
            onClick={() => p.setTool(p.tool === "remove" ? "off" : "remove")} title="Click areas that are not the bird">− Not bird</button>
        </div>
        <div className="btn-row">
          {m?.status === "uncertain" && m.has_mask && !m.accepted && <button className="btn" onClick={p.onAccept}>Use anyway</button>}
          {m && <button className="btn ghost small" onClick={p.onClear}>Clear selection</button>}
        </div>
        <label className="switch-row">
          <span className="switch">
            <input type="checkbox" checked={recipe.subject.use_mask} disabled={!usable}
              onChange={(e) => p.onChange({ ...recipe, subject: { ...recipe.subject, use_mask: e.target.checked,
                background_nr: e.target.checked && recipe.subject.background_nr === 0 ? 25 : recipe.subject.background_nr } })} />
            <span className="switch-track" aria-hidden="true" />
          </span>
          <span>Bird-aware processing</span>
          <InfoTip text="Sharpening and gentle noise reduction on the bird; extra smoothing only outside it." />
        </label>
        <Slider def={{ key: "bgnr", label: "Background noise reduction", min: 0, max: 100, step: 1 }}
          value={recipe.subject.background_nr} disabled={!recipe.subject.use_mask || !usable}
          onChange={(v) => p.onChange({ ...recipe, subject: { ...recipe.subject, background_nr: v } })} />
      </>
    );
  }
  return (
    <Section id="bird" title="Bird" icon={<IconBird size={16} />} right={badge}>
      {body}
    </Section>
  );
}
