import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, imageUrl } from "../api";
import type { Crop, Photo, Recipe } from "../types";
import { BASELINE } from "../types";
import { useDevicePixelRatio, useElementSize, useRenderedImage } from "../useRender";
import { CropOverlay } from "./CropOverlay";
import { MaskLayer } from "./MaskLayer";
import { IconAlert, IconImport } from "../icons";

export type Compare = "after" | "before" | "slider" | "side";
export type Zoom = "fit" | "100";

interface Props {
  photo: Photo | null;
  recipe: Recipe;
  compare: Compare;
  zoom: Zoom;
  setZoom: (z: Zoom) => void;
  cropDraft: Crop | null;
  setCropDraft: (c: Crop) => void;
  showMask: boolean;
  selecting: boolean;
  maskVersion: string;
  maskShape: [number, number] | null;
  onSelectClick: (x: number, y: number) => void;
  onImport?: () => void;
}


function cropRectPx(photo: Photo, crop: Crop | null) {
  const [fw, fh] = photo.full_size ?? [0, 0];
  if (!crop) return { x: 0, y: 0, w: fw, h: fh };
  const x = Math.round(crop.x * fw);
  const y = Math.round(crop.y * fh);
  return { x, y, w: Math.max(1, Math.min(fw - x, Math.round(crop.w * fw))), h: Math.max(1, Math.min(fh - y, Math.round(crop.h * fh))) };
}

/* ------------------------------------------------------------ fit pane */

function FitPane(props: { photo: Photo; recipe: Recipe; before: boolean; ignoreCrop?: boolean; label?: string;
  onDoubleClick?: (fx: number, fy: number) => void }) {
  const { photo, recipe, before, ignoreCrop } = props;
  const [ref, size] = useElementSize<HTMLDivElement>();
  const dpr = useDevicePixelRatio();
  const maxEdge = Math.min(2048, Math.max(256, Math.ceil(Math.max(size.w, size.h) * dpr)));
  const ready = photo.decode_status === "supported" && size.w > 0;
  const body = useMemo(
    () => (ready ? { recipe, before, max_edge: maxEdge, ignore_crop: !!ignoreCrop } : null),
    [ready, recipe, before, maxEdge, ignoreCrop],
  );
  const { url, loading, error } = useRenderedImage(ready ? photo.id : null, body);
  const showEmbedded = !url && photo.preview_kind === "embedded";
  const src = url ?? (showEmbedded ? imageUrl(photo.id, "embedded.jpg", photo.status_message) : null);

  return (
    <div className="fit-pane" ref={ref}
      onDoubleClick={(e) => {
        if (!props.onDoubleClick) return;
        const img = (e.currentTarget.querySelector("img") as HTMLImageElement | null);
        if (!img) return;
        const r = img.getBoundingClientRect();
        // object-fit: contain -> compute displayed image rect
        const ar = img.naturalWidth / img.naturalHeight;
        let w = r.width, h = r.height;
        if (w / h > ar) w = h * ar; else h = w / ar;
        const ox = r.left + (r.width - w) / 2, oy = r.top + (r.height - h) / 2;
        props.onDoubleClick(Math.min(1, Math.max(0, (e.clientX - ox) / w)), Math.min(1, Math.max(0, (e.clientY - oy) / h)));
      }}>
      {src && <img src={src} alt={props.label ?? (before ? "Before" : "After")} draggable={false} />}
      {props.label && <span className="pane-label">{props.label}</span>}
      {showEmbedded && <span className="badge-embedded">Camera's embedded preview, not the RAW rendering. Rendering RAW…</span>}
      {loading && <span className="spinner" aria-label="Rendering" />}
      {error && <span className="pane-error">{error}</span>}
    </div>
  );
}

/* ----------------------------------------------------------- 100% pane */

interface Tile { url: string; x: number; y: number; w: number; h: number }

function ZoomPane(props: { photo: Photo; recipe: Recipe; before: boolean; pan: { x: number; y: number };
  view: { w: number; h: number }; label?: string }) {
  const { photo, recipe, before, pan, view } = props;
  const dpr = useDevicePixelRatio();
  const crop = cropRectPx(photo, recipe.crop);
  const [tile, setTile] = useState<Tile | null>(null);
  const [status, setStatus] = useState<string>("");
  const tileRef = useRef<Tile | null>(null);
  const base = useRenderedImage(photo.id, useMemo(() => ({ recipe, before, max_edge: 1600 }), [recipe, before]), 150);

  const vw = Math.min(crop.w - pan.x, Math.ceil(view.w * dpr));
  const vh = Math.min(crop.h - pan.y, Math.ceil(view.h * dpr));
  const key = JSON.stringify([photo.id, recipe, before, pan.x, pan.y, vw, vh]);

  useEffect(() => {
    if (vw <= 0 || vh <= 0) return;
    const ctrl = new AbortController();
    const t = window.setTimeout(async () => {
      setStatus("Rendering at 100%…");
      try {
        const r = await api.renderRegion(photo.id, {
          recipe, before, x: crop.x + pan.x, y: crop.y + pan.y, w: Math.min(vw, 2400), h: Math.min(vh, 2400),
        }, ctrl.signal);
        const next = { url: URL.createObjectURL(r.blob), x: r.x - crop.x, y: r.y - crop.y, w: r.w, h: r.h };
        if (tileRef.current) URL.revokeObjectURL(tileRef.current.url);
        tileRef.current = next;
        setTile(next);
        setStatus("");
      } catch (e) {
        if ((e as Error).name !== "AbortError") setStatus((e as Error).message);
      }
    }, 220);
    return () => { window.clearTimeout(t); ctrl.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => () => { if (tileRef.current) URL.revokeObjectURL(tileRef.current.url); }, []);

  const offX = crop.w / dpr < view.w ? (view.w - crop.w / dpr) / 2 : 0;
  const offY = crop.h / dpr < view.h ? (view.h - crop.h / dpr) / 2 : 0;
  return (
    <div className="zoom-pane">
      <div className="zoom-content" style={{ transform: `translate(${offX - pan.x / dpr}px, ${offY - pan.y / dpr}px)`,
        width: crop.w / dpr, height: crop.h / dpr }}>
        {base.url && <img className="zoom-base" src={base.url} alt="" draggable={false} />}
        {tile && <img className="zoom-tile" src={tile.url} alt={before ? "Before at 100%" : "After at 100%"} draggable={false}
          style={{ left: tile.x / dpr, top: tile.y / dpr, width: tile.w / dpr, height: tile.h / dpr }} />}
      </div>
      {props.label && <span className="pane-label">{props.label}</span>}
      {status && <span className={status.startsWith("Rendering") ? "zoom-status" : "pane-error"}>{status}</span>}
    </div>
  );
}

/* --------------------------------------------------------------- viewer */

export function Viewer({ photo, recipe, compare, zoom, setZoom, cropDraft, setCropDraft, showMask, selecting,
  maskVersion, maskShape, onSelectClick, onImport }: Props) {
  const [boxRef, box] = useElementSize<HTMLDivElement>();
  const [split, setSplit] = useState(0.5);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ sx: number; sy: number; px: number; py: number } | null>(null);
  const before = useMemo<Recipe>(() => ({ ...BASELINE, crop: recipe.crop }), [recipe.crop]);
  const crop = photo ? cropRectPx(photo, recipe.crop) : { x: 0, y: 0, w: 0, h: 0 };
  const dpr = useDevicePixelRatio();
  const paneW = compare === "side" ? Math.floor(box.w / 2) : box.w;

  const clampPan = useCallback((p: { x: number; y: number }) => ({
    x: Math.round(Math.max(0, Math.min(p.x, crop.w - paneW * dpr))),
    y: Math.round(Math.max(0, Math.min(p.y, crop.h - box.h * dpr))),
  }), [crop.w, crop.h, paneW, box.h, dpr]);

  const zoomTo = useCallback((fx: number, fy: number) => {
    setPan(clampPan({ x: fx * crop.w - (paneW * dpr) / 2, y: fy * crop.h - (box.h * dpr) / 2 }));
    setZoom("100");
  }, [clampPan, crop.w, crop.h, paneW, box.h, dpr, setZoom]);

  useEffect(() => {
    if (zoom === "100") setPan((p) => clampPan(p.x === 0 && p.y === 0
      ? { x: crop.w / 2 - (paneW * dpr) / 2, y: crop.h / 2 - (box.h * dpr) / 2 } : p));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoom, photo?.id, crop.w, crop.h]);

  useEffect(() => { setPan({ x: 0, y: 0 }); }, [photo?.id]);

  if (!photo) {
    return (
      <div className="viewer empty" ref={boxRef}>
        <div className="empty-state">
          <div className="empty-icon"><IconImport size={30} /></div>
          <h2>Import your bird photos</h2>
          <p>Drag RAW, JPEG or TIFF files here, or choose them from a folder.</p>
          {onImport && <button className="btn primary large" onClick={onImport}><IconImport />Import photos</button>}
          <div className="format-row" aria-label="Supported formats">
            {["NEF", "ARW", "CR3", "CR2", "RAF", "ORF", "RW2", "DNG", "JPEG", "TIFF"].map((f) => <span key={f} className="pill">{f}</span>)}
          </div>
          <p className="muted small">Originals are never changed. Everything stays on this computer.</p>
        </div>
      </div>
    );
  }

  if (photo.decode_status === "unsupported" || photo.decode_status === "failed" || photo.decode_status === "needs_converter") {
    return (
      <div className="viewer" ref={boxRef}>
        <div className="empty-state error-state" role="alert">
          <div className="empty-icon bad"><IconAlert size={28} /></div>
          <h2>This photo can't be displayed</h2>
          <p><strong>Camera:</strong> {photo.metadata?.camera?.display_name ?? "Unknown camera"}</p>
          <p>{photo.decode_error}</p>
        </div>
      </div>
    );
  }

  const ready = photo.decode_status === "supported" && photo.full_size;

  if (cropDraft && ready) {
    return (
      <div className="viewer" ref={boxRef}>
        <FitPane photo={photo} recipe={{ ...recipe, crop: null }} before={false} ignoreCrop />
        <CropOverlay box={box} fullSize={photo.full_size!} crop={cropDraft} onChange={setCropDraft} />
      </div>
    );
  }

  if ((showMask || selecting) && ready && zoom === "fit") {
    return (
      <div className="viewer" ref={boxRef}>
        <FitPane photo={photo} recipe={{ ...recipe, crop: null }} before={false} ignoreCrop />
        <MaskLayer photoId={photo.id} version={maskVersion} box={box} fullSize={photo.full_size!} show={showMask || selecting}
          points={photo.mask?.points ?? []} maskShape={maskShape} clickable={selecting} onClick={onSelectClick} />
        {selecting && <span className="zoom-hint">Click on the photo to refine the bird selection</span>}
      </div>
    );
  }

  const onPointerDown = (e: React.PointerEvent) => {
    if (zoom !== "100") return;
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    drag.current = { sx: e.clientX, sy: e.clientY, px: pan.x, py: pan.y };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    const d = drag.current;
    setPan(clampPan({ x: d.px - (e.clientX - d.sx) * dpr, y: d.py - (e.clientY - d.sy) * dpr }));
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (zoom !== "100") return;
    const step = 120 * dpr;
    const moves: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    const m = moves[e.key];
    if (m) { e.preventDefault(); setPan((p) => clampPan({ x: p.x + m[0], y: p.y + m[1] })); }
  };

  const pane = (isBefore: boolean, label?: string) =>
    zoom === "100" && ready ? (
      <ZoomPane photo={photo} recipe={isBefore ? before : recipe} before={isBefore} pan={pan}
        view={{ w: paneW, h: box.h }} label={label} />
    ) : (
      <FitPane photo={photo} recipe={isBefore ? before : recipe} before={isBefore} label={label} onDoubleClick={zoomTo} />
    );

  return (
    <div className={`viewer ${zoom === "100" ? "zoomed" : ""}`} ref={boxRef} tabIndex={0}
      aria-label={zoom === "100" ? "Photo at 100%. Drag or use arrow keys to pan." : "Photo preview. Double-click to view at 100%."}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={() => (drag.current = null)}
      onKeyDown={onKey}>
      {compare === "after" && pane(false)}
      {compare === "before" && pane(true, "Before (baseline RAW rendering)")}
      {compare === "side" && (
        <div className="side-by-side">
          <div className="side">{pane(true, "Before")}</div>
          <div className="side">{pane(false, "After")}</div>
        </div>
      )}
      {compare === "slider" && (
        <div className="slider-compare">
          <div className="layer">{pane(true, "Before")}</div>
          <div className="layer" style={{ clipPath: `inset(0 0 0 ${split * 100}%)` }}>{pane(false)}</div>
          <span className="pane-label right">After</span>
          <div className="split-handle" style={{ left: `${split * 100}%` }} role="slider" tabIndex={0}
            aria-label="Before/after divider" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(split * 100)}
            onPointerDown={(e) => {
              e.stopPropagation();
              const el = e.currentTarget.parentElement!;
              const move = (ev: PointerEvent) => {
                const r = el.getBoundingClientRect();
                setSplit(Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)));
              };
              const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
              window.addEventListener("pointermove", move);
              window.addEventListener("pointerup", up);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowLeft") { e.stopPropagation(); e.preventDefault(); setSplit((s) => Math.max(0, s - 0.05)); }
              if (e.key === "ArrowRight") { e.stopPropagation(); e.preventDefault(); setSplit((s) => Math.min(1, s + 0.05)); }
            }} />
        </div>
      )}
      {zoom === "100" && <span className="zoom-hint">100% · {crop.w} × {crop.h} px · drag to pan</span>}
    </div>
  );
}
