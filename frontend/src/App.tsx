import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { Adjustments } from "./components/Adjustments";
import { BirdPanel, type SelectTool } from "./components/BirdPanel";
import { HistoryPanel } from "./components/HistoryPanel";
import { describeChange } from "./history";
import { ExportDialog } from "./components/ExportDialog";
import { Filmstrip } from "./components/Filmstrip";
import { InfoPanel } from "./components/InfoPanel";
import { JobsBar } from "./components/JobsBar";
import { Viewer, type Compare, type Zoom } from "./components/Viewer";
import type { Crop, EditLevel, History, Job, Limits, Photo, Recipe, SubjectStatus } from "./types";
import { BASELINE } from "./types";

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
  const [shell, setShell] = useState<"browser" | "desktop">("browser");
  const shellRef = useRef<"browser" | "desktop">("browser");
  const [subject, setSubject] = useState<SubjectStatus | null>(null);
  const [showMask, setShowMask] = useState(false);
  const [tool, setTool] = useState<SelectTool>("off");
  const [maskVersion, setMaskVersion] = useState("0");
  const [historyView, setHistoryView] = useState<History | null>(null);
  const [limits, setLimits] = useState<Limits | null>(null);
  const [editLevel, setEditLevel] = useState<EditLevel | null>(null);

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
        if (h && !same(h.entries[h.index].recipe, cur.recipe)) {
          h.entries = [...h.entries.slice(0, h.index + 1), { label: "Auto Edit All", time: Date.now() / 1000, recipe: cur.recipe }];
          h.index = h.entries.length - 1;
          setHistoryView({ ...h });
          api.saveHistory(cur.id, h).catch(() => {});
          setRecipe(cur.recipe);
          setSummary(cur.summary);
        }
      }
    } catch (e) {
      fail(e);
    }
  }, [fail]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    api.system().then((s) => {
      setNativeDialogs(!!s.native_dialogs);
      const sh = s.shell === "desktop" ? "desktop" : "browser";
      setShell(sh);
      shellRef.current = sh;
    }).catch(() => {});
  }, []);
  const loadSubject = useCallback(() => api.subjectStatus().then(setSubject).catch(() => {}), []);
  useEffect(() => { loadSubject(); }, [loadSubject]);
  const loadLimits = useCallback(() => api.limits().then(setLimits).catch(() => {}), []);
  useEffect(() => { loadLimits(); }, [loadLimits]);
  const toggleLimits = useCallback(async (on: boolean) => {
    if (!on && !window.confirm("Allow stronger edits?\n\nWith natural limits off, adjustments can go far enough to look over-processed.")) return;
    try {
      const st = await api.settings();
      await api.saveSettings({ ...st, natural_limits: on });
      await loadLimits();
    } catch (e) { fail(e); }
  }, [loadLimits, fail]);

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
    setTool("off");
    if (!photo) { setHistoryView(null); return; }
    const id = photo.id;
    const known = histories.current.get(id);
    if (known) {
      setRecipe(known.entries[known.index].recipe);
      setHistoryView({ ...known });
    } else {
      setRecipe(photo.recipe);
      setHistoryView(null);
      api.history(id).then((h) => {
        // The saved history must end at the recipe that is actually stored.
        if (!same(h.entries[h.index].recipe, photo.recipe)) {
          h.entries = [...h.entries.slice(0, h.index + 1), { label: "Edit", time: Date.now() / 1000, recipe: photo.recipe }];
          h.index = h.entries.length - 1;
        }
        histories.current.set(id, h);
        if (currentRef.current === id) { setHistoryView({ ...h }); setRecipe(h.entries[h.index].recipe); }
      }).catch(fail);
    }
    setSummary(photo.summary);
    setEditLevel(photo.edit_level ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photo?.id]);

  /* ------------------------------------------------------ editing */
  const save = useCallback(async (id: string, r: Recipe) => {
    try {
      const res = await api.saveRecipe(id, r);
      let saved = r;
      if (!same(res.recipe, r)) {
        // The server kept the edit within the natural limits.
        saved = res.recipe;
        const h = histories.current.get(id);
        if (h) { h.entries[h.index] = { ...h.entries[h.index], recipe: saved }; persistHistory(id, { ...h }); }
        if (currentRef.current === id) setRecipe(saved);
      }
      if (currentRef.current === id) { setSummary(res.summary); setEditLevel(res.edit_level); }
      setPhotos((ps) => ps.map((p) => (p.id === id ? { ...p, recipe: saved, summary: res.summary, edit_level: res.edit_level } : p)));
    } catch (e) {
      fail(e);
    } finally {
      pendingCommit.current = false;
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fail]);

  const persistHistory = useCallback((id: string, h: History) => {
    histories.current.set(id, h);
    if (currentRef.current === id) setHistoryView({ ...h });
    api.saveHistory(id, h).catch(() => {});
  }, []);

  const commit = useCallback((id: string, r: Recipe, label?: string) => {
    const h = histories.current.get(id) ?? { entries: [{ label: "Imported", time: Date.now() / 1000, recipe: BASELINE }], index: 0 };
    const prev = h.entries[h.index].recipe;
    if (same(prev, r)) { pendingCommit.current = false; return; }
    const entries = [...h.entries.slice(0, h.index + 1), { label: label ?? describeChange(prev, r), time: Date.now() / 1000, recipe: r }].slice(-200);
    persistHistory(id, { entries, index: entries.length - 1 });
    save(id, r);
  }, [save, persistHistory]);

  const onChange = useCallback((r: Recipe) => {
    if (!currentId) return;
    setRecipe(r);
    pendingCommit.current = true;
    if (commitTimer.current) window.clearTimeout(commitTimer.current);
    const id = currentId;
    commitTimer.current = window.setTimeout(() => { commitTimer.current = null; commit(id, r); }, 600);
  }, [currentId, commit]);

  const setNow = useCallback((r: Recipe, label?: string) => {
    if (!currentId) return;
    if (commitTimer.current) { window.clearTimeout(commitTimer.current); commitTimer.current = null; }
    setRecipe(r);
    pendingCommit.current = true;
    commit(currentId, r, label);
  }, [currentId, commit]);

  const jumpTo = useCallback((index: number) => {
    if (!currentId) return;
    if (commitTimer.current) { window.clearTimeout(commitTimer.current); commitTimer.current = null; commit(currentId, recipe); }
    const h = histories.current.get(currentId);
    if (!h || index < 0 || index >= h.entries.length || index === h.index) return;
    const target = h.entries[index].recipe;
    if (target.subject?.use_mask || target.look === "soft_background") {
      if (!photos.find((p) => p.id === currentId)?.mask?.usable) {
        toast("That step used a bird selection that no longer exists. Detect the bird again first.", "error");
        return;
      }
    }
    persistHistory(currentId, { ...h, index });
    setRecipe(target);
    pendingCommit.current = true;
    save(currentId, target);
  }, [currentId, recipe, commit, save, persistHistory, photos, toast]);

  const undoRedo = useCallback((dir: -1 | 1) => {
    const h = currentId ? histories.current.get(currentId) : undefined;
    if (h) jumpTo(h.index + dir);
  }, [currentId, jumpTo]);

  const autoEdit = useCallback(async (look: "natural" | "crisp" | "soft_background" = "natural") => {
    if (!photo) return;
    setBusy(true);
    try {
      const res = await api.auto(photo.id, look);
      const names = { natural: "Natural", crisp: "Crisp Detail", soft_background: "Soft Background" };
      setNow({ ...res.recipe }, `Auto Edit (${names[look]})`);
      setEditLevel(res.edit_level);
      setMaskVersion(String(Date.now()));
      refresh();
      setSummary(res.summary);
      setCompare((c) => (c === "before" ? "slider" : c));
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }, [photo, setNow, fail, refresh]);

  /* ------------------------------------------------------ bird selection */
  const enableSubject = useCallback(async (on: boolean) => {
    try {
      const st = await api.settings();
      await api.saveSettings({ ...st, subject_detection: on });
      await loadSubject();
      if (on) toast("Bird detection is on. Auto Edit will now look for the bird.");
    } catch (e) { fail(e); }
  }, [loadSubject, toast, fail]);

  const afterMaskChange = useCallback(async () => {
    setMaskVersion(String(Date.now()));
    await refresh();
  }, [refresh]);

  const detect = useCallback(async () => {
    if (!photo) return;
    setBusy(true);
    try {
      const r = await api.detect(photo.id, undefined, true);
      toast(r.message, r.status === "good" ? "info" : "error");
      setShowMask(true);
      await afterMaskChange();
    } catch (e) { fail(e); } finally { setBusy(false); }
  }, [photo, toast, fail, afterMaskChange]);

  const selectClick = useCallback(async (x: number, y: number) => {
    if (!photo || tool === "off") return;
    const shape = photo.mask?.shape;
    const prev = (photo.mask?.points ?? []).map(([px, py, lab]) =>
      ({ x: shape ? px / shape[1] : 0, y: shape ? py / shape[0] : 0, bird: !!lab }));
    setBusy(true);
    try {
      await api.detect(photo.id, [...prev, { x, y, bird: tool === "add" }]);
      setShowMask(true);
      await afterMaskChange();
    } catch (e) { fail(e); } finally { setBusy(false); }
  }, [photo, tool, fail, afterMaskChange]);

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
    let linked = false;      // program window: the app links dropped files in place
    const imported = (e: Event) => {
      linked = true;
      const n = (e as CustomEvent).detail ?? 0;
      toast(n ? `Importing ${n} photo${n === 1 ? "" : "s"} (originals linked in place, not copied).`
              : "No supported photos were found in what you dropped.", n ? "info" : "error");
      startPolling();
      refresh();
    };
    const over = (e: DragEvent) => { if (e.dataTransfer?.types.includes("Files")) { e.preventDefault(); setDragOver(true); } };
    const leave = (e: DragEvent) => { if (e.relatedTarget === null) setDragOver(false); };
    const drop = (e: DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const files = Array.from(e.dataTransfer?.files ?? []);
      if (shellRef.current !== "desktop") { uploadFiles(files); return; }
      // In the program window the app receives the real paths; if it does
      // not (e.g. files dragged from a web page), copy them in instead.
      linked = false;
      window.setTimeout(() => { if (!linked) uploadFiles(files); }, 1500);
    };
    window.addEventListener("birdedit-imported", imported);
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("birdedit-imported", imported);
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, [uploadFiles, toast, startPolling, refresh]);

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
      if (currentId && targets.includes(currentId)) setNow({ ...recipe, ...clip, sliders: { ...clip.sliders } }, "Pasted settings");
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

  const h = historyView;
  const canUndo = !!h && h.index > 0;
  const canRedo = !!h && h.index < h.entries.length - 1;
  const lastAuto = h ? [...h.entries.slice(0, h.index + 1)].reverse().find((e) => e.label.startsWith("Auto Edit"))?.recipe ?? null : null;
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
          {shell === "browser" && (
            <button className="ghost" onClick={() => fileInput.current?.click()} title="Copy files in through the browser">Upload copies…</button>
          )}
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
              <button onClick={() => setNow({ ...BASELINE }, "Revert to original")} disabled={!ready}
                title="Back to the unedited baseline rendering (can be undone)">Revert to original</button>
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
            cropDraft={cropDraft} setCropDraft={setCropDraft}
            showMask={showMask && !!photo?.mask?.has_mask} selecting={tool !== "off"} maskVersion={maskVersion}
            maskShape={photo?.mask?.shape ?? null} onSelectClick={selectClick} />
          {summary && ready && (
            <div className="summary" aria-live="polite">
              {editLevel && editLevel.level !== "none" && (
                <span className={`level level-${editLevel.level}`} title={editLevel.notes.join(" ")}>
                  {editLevel.level === "light" ? "Light edit" : editLevel.level === "moderate" ? "Moderate edit" : "Strong edit"}
                </span>
              )}
              <span>{summary}</span>
              {editLevel?.level === "strong" && <div className="small warn">{editLevel.notes.join(" ")}</div>}
            </div>
          )}
          <Filmstrip photos={photos} currentId={currentId} selected={selected} onSelect={onSelect} onRemove={removePhoto} />
        </section>

        <aside className="sidebar">
          {photo ? (
            <>
              <InfoPanel photo={photo} onLocate={locate} onRetry={() => api.reprocess(photo.id).then(() => { startPolling(); refresh(); }).catch(fail)} />
              <Adjustments photo={photo} recipe={recipe} onChange={onChange} onLook={(l) => autoEdit(l)} busy={busy}
                autoRecipe={lastAuto} maskUsable={!!photo.mask?.usable} limits={limits} onToggleLimits={toggleLimits}
                onSuggestCrop={async (aspect, portrait) => {
                  try {
                    const r = await api.cropSuggestion(photo.id, aspect, portrait);
                    if (r.crop) setCropDraft(r.crop);
                    toast(r.message);
                  } catch (e) { fail(e); }
                }}
                cropDraft={cropDraft} setCropDraft={(c) => {
                  setCropDraft(c);
                  if (c) { setZoom("fit"); setTool("off"); }
                }} />
              <BirdPanel photo={photo} recipe={recipe} status={subject} busy={busy} showMask={showMask} setShowMask={setShowMask}
                tool={tool} setTool={(t) => { setTool(t); if (t !== "off") { setZoom("fit"); setCropDraft(null); } }}
                onEnable={enableSubject} onDetect={detect}
                onAccept={() => api.acceptMask(photo.id).then(afterMaskChange).catch(fail)}
                onClear={() => api.clearMask(photo.id).then(async () => {
                  setShowMask(false); setTool("off");
                  const r = await api.photo(photo.id);
                  if (!same(r.recipe, recipe)) setNow(r.recipe, "Bird selection cleared");
                  await afterMaskChange();
                }).catch(fail)}
                onChange={onChange} />
              <HistoryPanel history={historyView} onJump={jumpTo} />
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
      {dragOver && <div className="drop-hint">{shell === "desktop"
        ? "Drop photos or a folder to import (originals are linked, never changed)"
        : "Drop photos to import (copies are made; originals are not changed)"}</div>}
    </div>
  );
}
