import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { Adjustments } from "./components/Adjustments";
import { ExportDialog } from "./components/ExportDialog";
import { Filmstrip } from "./components/Filmstrip";
import { InfoPanel } from "./components/InfoPanel";
import { JobsBar } from "./components/JobsBar";
import { Viewer, type Compare, type Zoom } from "./components/Viewer";
import type { Crop, Job, Photo, Recipe } from "./types";
import { BASELINE } from "./types";

interface History { stack: Recipe[]; index: number }
type Clip = Pick<Recipe, "look" | "strength" | "sliders">;

const same = (a: Recipe, b: Recipe) => JSON.stringify(a) === JSON.stringify(b);

export function App() {
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [recipe, setRecipe] = useState<Recipe>(BASELINE);
  const [summary, setSummary] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [compare, setCompare] = useState<Compare>("after");
  const [zoom, setZoom] = useState<Zoom>("fit");
  const [cropDraft, setCropDraft] = useState<Crop | null>(null);
  const [clip, setClip] = useState<Clip | null>(null);
  const [toasts, setToasts] = useState<{ id: number; text: string; kind: "info" | "error" }[]>([]);
  const [showExport, setShowExport] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [nativeDialogs, setNativeDialogs] = useState(true);

  const histories = useRef(new Map<string, History>());
  const commitTimer = useRef<number | null>(null);
  const pendingCommit = useRef(false);
  const polling = useRef(false);
  const lastDone = useRef("");
  const fileInput = useRef<HTMLInputElement>(null);
  const currentRef = useRef<string | null>(null);
  currentRef.current = currentId;

  const photo = useMemo(() => photos.find((p) => p.id === currentId) ?? null, [photos, currentId]);

  const toast = useCallback((text: string, kind: "info" | "error" = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, kind }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 9000 : 4500);
  }, []);
  const fail = useCallback((e: unknown) => toast(e instanceof Error ? e.message : String(e), "error"), [toast]);

  /* ------------------------------------------------------ loading */
  const refresh = useCallback(async () => {
    try {
      const list = await api.photos();
      setPhotos(list);
      setCurrentId((cur) => (cur && list.some((p) => p.id === cur) ? cur : list[0]?.id ?? null));
      // Adopt server-side recipe changes (e.g. Auto Edit All) for the current photo.
      const cur = list.find((p) => p.id === currentRef.current);
      if (cur && !pendingCommit.current) {
        const h = histories.current.get(cur.id);
        if (h && !same(h.stack[h.index], cur.recipe)) {
          h.stack = [...h.stack.slice(0, h.index + 1), cur.recipe];
          h.index = h.stack.length - 1;
          setRecipe(cur.recipe);
          setSummary(cur.summary);
        }
      }
    } catch (e) {
      fail(e);
    }
  }, [fail]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { api.system().then((s) => setNativeDialogs(!!s.native_dialogs)).catch(() => {}); }, []);

  // Job polling while anything is running.
  const startPolling = useCallback(() => { polling.current = true; }, []);
  useEffect(() => {
    const t = window.setInterval(async () => {
      if (!polling.current) return;
      try {
        const js = await api.jobs();
        setJobs(js);
        const sig = js.map((j) => `${j.id}:${j.done}:${j.status}:${j.item_progress > 0.25 ? 1 : 0}`).join("|");
        if (sig !== lastDone.current) {
          lastDone.current = sig;
          refresh();
        }
        if (!js.some((j) => j.status === "running" || j.status === "queued")) polling.current = false;
      } catch {
        /* backend gone; the next user action will report it */
      }
    }, 700);
    return () => window.clearInterval(t);
  }, [refresh]);

  // Switching photos: load its recipe and history.
  useEffect(() => {
    setCropDraft(null);
    if (!photo) return;
    let h = histories.current.get(photo.id);
    if (!h) {
      h = { stack: [photo.recipe], index: 0 };
      histories.current.set(photo.id, h);
    }
    setRecipe(h.stack[h.index]);
    setSummary(photo.summary);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photo?.id]);

  /* ------------------------------------------------------ editing */
  const save = useCallback(async (id: string, r: Recipe) => {
    try {
      const res = await api.saveRecipe(id, r);
      if (currentRef.current === id) setSummary(res.summary);
      setPhotos((ps) => ps.map((p) => (p.id === id ? { ...p, recipe: r, summary: res.summary } : p)));
    } catch (e) {
      fail(e);
    } finally {
      pendingCommit.current = false;
    }
  }, [fail]);

  const commit = useCallback((id: string, r: Recipe) => {
    const h = histories.current.get(id) ?? { stack: [], index: -1 };
    if (h.index >= 0 && same(h.stack[h.index], r)) { pendingCommit.current = false; return; }
    h.stack = [...h.stack.slice(0, h.index + 1), r].slice(-100);
    h.index = h.stack.length - 1;
    histories.current.set(id, h);
    save(id, r);
  }, [save]);

  const onChange = useCallback((r: Recipe) => {
    if (!currentId) return;
    setRecipe(r);
    pendingCommit.current = true;
    if (commitTimer.current) window.clearTimeout(commitTimer.current);
    const id = currentId;
    commitTimer.current = window.setTimeout(() => commit(id, r), 450);
  }, [currentId, commit]);

  const setNow = useCallback((r: Recipe) => {
    if (!currentId) return;
    if (commitTimer.current) window.clearTimeout(commitTimer.current);
    setRecipe(r);
    pendingCommit.current = true;
    commit(currentId, r);
  }, [currentId, commit]);

  const undoRedo = useCallback((dir: -1 | 1) => {
    if (!currentId) return;
    if (commitTimer.current) { window.clearTimeout(commitTimer.current); commit(currentId, recipe); }
    const h = histories.current.get(currentId);
    if (!h) return;
    const ni = h.index + dir;
    if (ni < 0 || ni >= h.stack.length) return;
    h.index = ni;
    setRecipe(h.stack[ni]);
    pendingCommit.current = true;
    save(currentId, h.stack[ni]);
  }, [currentId, recipe, commit, save]);

  const autoEdit = useCallback(async (look: "natural" | "crisp" = "natural") => {
    if (!photo) return;
    setBusy(true);
    try {
      const res = await api.auto(photo.id, look);
      setNow({ ...res.recipe });
      setSummary(res.summary);
      setCompare((c) => (c === "before" ? "slider" : c));
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }, [photo, setNow, fail]);

  const autoAll = useCallback(async () => {
    const ids = photos.filter((p) => p.decode_status === "supported").map((p) => p.id);
    if (!ids.length) return toast("No decoded photos to edit yet.");
    try {
      const j = await api.autoAll(ids, "natural");
      setJobs((js) => [...js, j]);
      startPolling();
    } catch (e) {
      fail(e);
    }
  }, [photos, toast, fail, startPolling]);

  /* ------------------------------------------------------ import */
  const uploadFiles = useCallback(async (files: File[]) => {
    if (!files.length) return;
    try {
      const r = await api.upload(files);
      r.rejected.forEach((m) => toast(m, "error"));
      if (r.job) { setJobs((js) => [...js, r.job!]); startPolling(); }
      await refresh();
      if (r.photo_ids[0]) setCurrentId(r.photo_ids[0]);
    } catch (e) {
      fail(e);
    }
  }, [toast, fail, refresh, startPolling]);

  const importDialog = useCallback(async () => {
    if (!nativeDialogs) {
      // No native picker: the browser picker must open synchronously from the click.
      fileInput.current?.click();
      return;
    }
    try {
      const r = await api.importDialog();
      if (r.job) { setJobs((js) => [...js, r.job!]); startPolling(); }
      await refresh();
      if (r.photo_ids[0]) setCurrentId(r.photo_ids[0]);
    } catch (e) {
      if (e instanceof ApiError && e.status === 501) {
        setNativeDialogs(false);
        toast("The Windows file dialog isn't available. Click Import Photos again to copy photos in through the browser.");
      } else fail(e);
    }
  }, [nativeDialogs, toast, fail, refresh, startPolling]);

  useEffect(() => {
    const over = (e: DragEvent) => { if (e.dataTransfer?.types.includes("Files")) { e.preventDefault(); setDragOver(true); } };
    const leave = (e: DragEvent) => { if (e.relatedTarget === null) setDragOver(false); };
    const drop = (e: DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      uploadFiles(Array.from(e.dataTransfer?.files ?? []));
    };
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, [uploadFiles]);

  /* ------------------------------------------------------ selection */
  const onSelect = useCallback((id: string, mode: "single" | "toggle" | "range") => {
    setCurrentId(id);
    setZoom("fit");
    setSelected((sel) => {
      if (mode === "single") return new Set([id]);
      const next = new Set(sel);
      if (mode === "toggle") { if (next.has(id)) next.delete(id); else next.add(id); return next; }
      const ids = photos.map((p) => p.id);
      const a = ids.indexOf(currentId ?? id), b = ids.indexOf(id);
      for (let i = Math.min(a, b); i <= Math.max(a, b); i++) next.add(ids[i]);
      return next;
    });
  }, [photos, currentId]);

  const removePhoto = useCallback(async (id: string) => {
    const p = photos.find((x) => x.id === id);
    if (!p || !window.confirm(`Remove “${p.original_name}” from this project?\n\nThe original file is NOT deleted; only the edits and previews are removed.`)) return;
    try {
      await api.remove(id);
      histories.current.delete(id);
      setSelected((s) => { const n = new Set(s); n.delete(id); return n; });
      await refresh();
    } catch (e) {
      fail(e);
    }
  }, [photos, refresh, fail]);

  const locate = useCallback(async () => {
    if (!photo) return;
    try {
      const r = await api.relocate(photo.id);
      if (!r.cancelled) toast("Original found.");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.body?.pending_id) {
        if (window.confirm(e.message)) await api.relocateConfirm(photo.id, e.body.pending_id).catch(fail);
      } else fail(e);
    }
    startPolling();
    refresh();
  }, [photo, toast, fail, refresh, startPolling]);

  /* ------------------------------------------------------ copy/paste */
  const copySettings = () => {
    setClip({ look: recipe.look, strength: recipe.strength, sliders: { ...recipe.sliders } });
    toast("Copied adjustments (look, strength and sliders). Camera color data is never copied.");
  };
  const pasteSettings = async () => {
    if (!clip) return;
    const targets = selected.size > 1 ? Array.from(selected) : currentId ? [currentId] : [];
    try {
      await api.paste(targets, clip);
      if (currentId && targets.includes(currentId)) setNow({ ...recipe, ...clip, sliders: { ...clip.sliders } });
      await refresh();
      toast(`Pasted adjustments to ${targets.length} photo${targets.length === 1 ? "" : "s"}.`);
    } catch (e) {
      fail(e);
    }
  };

  /* ------------------------------------------------------ keyboard */
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" && (e.target as HTMLInputElement).type === "text") return;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "z" && !e.shiftKey) { e.preventDefault(); undoRedo(-1); }
      else if (mod && (e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey))) { e.preventDefault(); undoRedo(1); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [undoRedo]);

  const h = currentId ? histories.current.get(currentId) : undefined;
  const canUndo = !!h && h.index > 0;
  const canRedo = !!h && h.index < h.stack.length - 1;
  const ready = photo?.decode_status === "supported";
  const anyEdited = photos.some((p) => p.recipe.auto_applied);
  const step = !photos.length ? 1 : !anyEdited ? 2 : 3;

  return (
    <div className={`app ${dragOver ? "drag-over" : ""}`}>
      <header className="topbar">
        <div className="brand">Bird Photo Editor</div>
        <ol className="steps" aria-label="Workflow">
          {["Import Photos", "Auto Edit", "Review", "Export"].map((s, i) => (
            <li key={s} className={i + 1 === step ? "current" : i + 1 < step ? "done" : ""}>{i + 1}. {s}</li>
          ))}
        </ol>
        <div className="actions">
          <button onClick={importDialog} title="Choose RAW, JPEG or TIFF files">Import Photos</button>
          <button className="ghost" onClick={() => fileInput.current?.click()} title="Copy files in through the browser">Upload copies…</button>
          <input ref={fileInput} type="file" multiple hidden
            accept=".nef,.nrw,.arw,.srf,.sr2,.cr2,.cr3,.raf,.orf,.rw2,.dng,.pef,.srw,.jpg,.jpeg,.tif,.tiff"
            onChange={(e) => { uploadFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
          <button className="primary" disabled={!ready || busy} onClick={() => autoEdit(recipe.look === "crisp" ? "crisp" : "natural")}>
            {busy ? "Editing…" : "Auto Edit"}
          </button>
          <button disabled={!photos.some((p) => p.decode_status === "supported")} onClick={autoAll}>Auto Edit All</button>
          <button disabled={!photos.some((p) => p.decode_status === "supported")} onClick={() => setShowExport(true)}>Export…</button>
        </div>
      </header>

      <JobsBar jobs={jobs} />

      <main className="workspace">
        <section className="center">
          <div className="view-toolbar" role="toolbar" aria-label="View options">
            <div className="seg" role="radiogroup" aria-label="Compare">
              {([["after", "After"], ["before", "Before"], ["slider", "Before/After slider"], ["side", "Side by side"]] as const).map(([v, l]) => (
                <button key={v} role="radio" aria-checked={compare === v} className={compare === v ? "active" : ""}
                  onClick={() => setCompare(v)} disabled={!!cropDraft}>{l}</button>
              ))}
            </div>
            <div className="seg" role="radiogroup" aria-label="Zoom">
              <button role="radio" aria-checked={zoom === "fit"} className={zoom === "fit" ? "active" : ""} onClick={() => setZoom("fit")}>Fit</button>
              <button role="radio" aria-checked={zoom === "100"} className={zoom === "100" ? "active" : ""} disabled={!ready || !!cropDraft}
                onClick={() => setZoom("100")}>100%</button>
            </div>
            <div className="seg">
              <button onClick={() => undoRedo(-1)} disabled={!canUndo} title="Undo (Ctrl+Z)">Undo</button>
              <button onClick={() => undoRedo(1)} disabled={!canRedo} title="Redo (Ctrl+Y)">Redo</button>
              <button onClick={() => setNow({ ...BASELINE })} disabled={!ready} title="Back to the unedited baseline rendering">Reset</button>
            </div>
            <div className="seg">
              <button onClick={copySettings} disabled={!ready}>Copy settings</button>
              <button onClick={pasteSettings} disabled={!clip || !ready}
                title={selected.size > 1 ? `Paste to ${selected.size} selected photos` : "Paste to this photo"}>
                Paste settings{selected.size > 1 ? ` (${selected.size})` : ""}
              </button>
            </div>
          </div>
          <Viewer photo={photo} recipe={recipe} compare={compare} zoom={zoom} setZoom={setZoom}
            cropDraft={cropDraft} setCropDraft={setCropDraft} />
          {summary && ready && <p className="summary" aria-live="polite">{summary}</p>}
          <Filmstrip photos={photos} currentId={currentId} selected={selected} onSelect={onSelect} onRemove={removePhoto} />
        </section>

        <aside className="sidebar">
          {photo ? (
            <>
              <InfoPanel photo={photo} onLocate={locate} onRetry={() => api.reprocess(photo.id).then(() => { startPolling(); refresh(); }).catch(fail)} />
              <Adjustments photo={photo} recipe={recipe} onChange={onChange} onLook={(l) => autoEdit(l)} busy={busy}
                cropDraft={cropDraft} setCropDraft={(c) => {
                  setCropDraft(c);
                  if (c) { setZoom("fit"); }
                }} />
            </>
          ) : (
            <p className="muted pad">No photo selected.</p>
          )}
        </aside>
      </main>

      {showExport && (
        <ExportDialog photos={photos} selected={selected} currentId={currentId} jobs={jobs}
          onClose={() => setShowExport(false)} onStarted={(j) => { setJobs((js) => [...js, j]); startPolling(); }} />
      )}

      <div className="toasts" aria-live="assertive">
        {toasts.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>)}
      </div>
      {dragOver && <div className="drop-hint">Drop photos to import (copies are made; originals are not changed)</div>}
    </div>
  );
}
