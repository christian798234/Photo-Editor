import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { Job, Photo, Settings } from "../types";

interface Props {
  photos: Photo[];
  selected: Set<string>;
  currentId: string | null;
  jobs: Job[];
  onClose: () => void;
  onStarted: (job: Job) => void;
}

export function ExportDialog({ photos, selected, currentId, jobs, onClose, onStarted }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [s, setS] = useState<Settings>({ export_folder: "", export_format: "jpeg", jpeg_quality: 92, long_edge: null, keep_gps: false, subject_detection: null, natural_limits: true });
  const [which, setWhich] = useState<"current" | "selected" | "edited" | "all">(selected.size > 1 ? "selected" : "current");
  const [resize, setResize] = useState(false);
  const [error, setError] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);

  useEffect(() => {
    ref.current?.showModal();
    api.settings().then((st) => { setS(st); setResize(!!st.long_edge); }).catch(() => {});
  }, []);

  const exportable = photos.filter((p) => p.decode_status === "supported");
  const ids = (() => {
    if (which === "current") return currentId ? [currentId] : [];
    if (which === "selected") return exportable.filter((p) => selected.has(p.id)).map((p) => p.id);
    if (which === "edited") return exportable.filter((p) => p.recipe.auto_applied).map((p) => p.id);
    return exportable.map((p) => p.id);
  })();
  const job = jobs.find((j) => j.id === jobId);

  const choose = async () => {
    setError("");
    try {
      const r = await api.chooseFolder();
      if (r.path) setS({ ...s, export_folder: r.path });
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const start = async () => {
    setError("");
    const settings = { ...s, long_edge: resize ? s.long_edge ?? 2048 : null };
    try {
      await api.saveSettings(settings);
      const j = await api.export({ photo_ids: ids, folder: settings.export_folder, format: settings.export_format,
        quality: settings.jpeg_quality, long_edge: settings.long_edge, keep_gps: settings.keep_gps });
      setJobId(j.id);
      onStarted(j);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  return (
    <dialog ref={ref} className="export-dialog" onClose={onClose} aria-labelledby="export-title">
      <h2 id="export-title">Export photos</h2>
      {!job ? (
        <>
          <fieldset>
            <legend>Which photos</legend>
            <label className="check"><input type="radio" checked={which === "current"} onChange={() => setWhich("current")} /> Current photo</label>
            <label className="check"><input type="radio" checked={which === "selected"} onChange={() => setWhich("selected")} /> Selected photos ({exportable.filter((p) => selected.has(p.id)).length})</label>
            <label className="check"><input type="radio" checked={which === "edited"} onChange={() => setWhich("edited")} /> All auto-edited photos ({exportable.filter((p) => p.recipe.auto_applied).length})</label>
            <label className="check"><input type="radio" checked={which === "all"} onChange={() => setWhich("all")} /> All photos ({exportable.length})</label>
          </fieldset>
          <fieldset>
            <legend>Save to folder</legend>
            <div className="row">
              <input className="grow" type="text" aria-label="Export folder" placeholder="C:\Users\you\Pictures\Edited birds"
                value={s.export_folder} onChange={(e) => setS({ ...s, export_folder: e.target.value })} />
              <button className="btn" onClick={choose}>Choose…</button>
            </div>
          </fieldset>
          <fieldset>
            <legend>Format</legend>
            <label className="check"><input type="radio" checked={s.export_format === "jpeg"} onChange={() => setS({ ...s, export_format: "jpeg" })} /> JPEG (sRGB, for sharing and printing services)</label>
            {s.export_format === "jpeg" && (
              <label className="inline">Quality <input type="number" min={50} max={100} value={s.jpeg_quality}
                onChange={(e) => setS({ ...s, jpeg_quality: Number(e.target.value) })} /></label>
            )}
            <label className="check"><input type="radio" checked={s.export_format === "tiff16"} onChange={() => setS({ ...s, export_format: "tiff16" })} /> 16-bit TIFF (sRGB, for further editing; large files)</label>
            <label className="check"><input type="checkbox" checked={resize} onChange={(e) => setResize(e.target.checked)} /> Resize: long edge</label>
            {resize && <label className="inline"><input type="number" min={256} max={20000} value={s.long_edge ?? 2048}
              onChange={(e) => setS({ ...s, long_edge: Number(e.target.value) })} /> px</label>}
            <label className="check"><input type="checkbox" checked={s.keep_gps} onChange={(e) => setS({ ...s, keep_gps: e.target.checked })} /> Keep GPS location (removed by default)</label>
          </fieldset>
          <p className="small muted">Exports are rendered from the full-resolution original with your saved edits. Originals are never changed,
            and existing files are never overwritten: a number is added to the name instead.</p>
          {error && <p className="error-text" role="alert">{error}</p>}
          <div className="row end">
            <button className="btn ghost" onClick={() => ref.current?.close()}>Cancel</button>
            <button className="btn primary" disabled={!ids.length || !s.export_folder} onClick={start}>Export {ids.length} photo{ids.length === 1 ? "" : "s"}</button>
          </div>
        </>
      ) : (
        <>
          <p>{job.status === "running" || job.status === "queued" ? `Exporting ${Math.min(job.done + 1, job.total)} of ${job.total}…`
            : job.status === "cancelled" ? "Export cancelled." : "Export finished."}</p>
          <progress max={job.total} value={job.done + (job.status === "running" ? job.item_progress : 0)} />
          <ul className="results">
            {job.results.map((r, i) => <li key={i} className={r.ok ? "ok" : "fail"}>{r.ok ? "✓" : "✗"} {r.message}</li>)}
          </ul>
          <div className="row end">
            {(job.status === "running" || job.status === "queued") && <button className="btn" onClick={() => api.cancelJob(job.id)}>Cancel export</button>}
            {job.status === "done" && /Win/.test(navigator.userAgent) && (
              <button className="btn" onClick={() => api.openFolder(s.export_folder).catch((e) => setError(e.message))}>Open folder</button>
            )}
            <button className="btn primary" onClick={() => ref.current?.close()}>Close</button>
          </div>
          {error && <p className="error-text">{error}</p>}
        </>
      )}
    </dialog>
  );
}
