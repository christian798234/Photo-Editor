import { useRef } from "react";
import { aspectRatio, cropPixels } from "../crop";
import type { Crop } from "../types";

type Mode = "move" | "nw" | "ne" | "sw" | "se" | "n" | "s" | "e" | "w";

interface Props {
  box: { w: number; h: number };
  fullSize: [number, number];
  crop: Crop;
  onChange: (c: Crop) => void;
}

export function CropOverlay({ box, fullSize, crop, onChange }: Props) {
  const start = useRef<{ mode: Mode; sx: number; sy: number; c: Crop } | null>(null);
  const [fw, fh] = fullSize;
  const ar = fw / fh;
  let w = box.w, h = box.h;
  if (w / h > ar) w = h * ar; else h = w / ar;
  const ox = (box.w - w) / 2, oy = (box.h - h) / 2;
  const ratio = aspectRatio(crop.aspect, crop.portrait, fullSize);
  const MIN = 0.03;

  const apply = (mode: Mode, dx: number, dy: number, c0: Crop): Crop => {
    let { x, y, w: cw, h: ch } = c0;
    if (mode === "move") {
      x = Math.min(Math.max(0, x + dx), 1 - cw);
      y = Math.min(Math.max(0, y + dy), 1 - ch);
      return { ...c0, x, y };
    }
    const right = x + cw, bottom = y + ch;
    if (mode.includes("w")) x = Math.min(Math.max(0, x + dx), right - MIN);
    if (mode.includes("e")) cw = Math.min(Math.max(MIN, cw + dx), 1 - x);
    if (mode.includes("n")) y = Math.min(Math.max(0, y + dy), bottom - MIN);
    if (mode.includes("s")) ch = Math.min(Math.max(MIN, ch + dy), 1 - y);
    if (mode.includes("w")) cw = right - x;
    if (mode.includes("n")) ch = bottom - y;
    if (ratio !== null) {
      // Keep the aspect: derive height from width (in pixel terms), anchored
      // at the corner opposite the handle; shrink if it would leave the image.
      let nh = (cw * fw) / ratio / fh;
      const maxH = mode.includes("n") ? bottom : 1 - y;
      if (nh > maxH) { nh = maxH; cw = (nh * fh * ratio) / fw; if (mode.includes("w")) x = right - cw; }
      if (mode.includes("n")) y = bottom - nh;
      ch = nh;
    }
    return { ...c0, x, y, w: cw, h: ch };
  };

  const down = (mode: Mode) => (e: React.PointerEvent) => {
    e.stopPropagation();
    e.preventDefault();
    start.current = { mode, sx: e.clientX, sy: e.clientY, c: crop };
    const move = (ev: PointerEvent) => {
      const s = start.current;
      if (!s) return;
      onChange(apply(s.mode, (ev.clientX - s.sx) / w, (ev.clientY - s.sy) / h, s.c));
    };
    const up = () => {
      start.current = null;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const onKey = (e: React.KeyboardEvent) => {
    const step = e.shiftKey ? 0.05 : 0.01;
    const d: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (d[e.key]) { e.preventDefault(); onChange(apply("move", d[e.key][0], d[e.key][1], crop)); }
  };

  const [pw, ph] = cropPixels(crop, fullSize);
  const handles: Mode[] = ratio === null ? ["nw", "ne", "sw", "se", "n", "s", "e", "w"] : ["nw", "ne", "sw", "se"];
  const style = { left: ox + crop.x * w, top: oy + crop.y * h, width: crop.w * w, height: crop.h * h };
  return (
    <div className="crop-overlay">
      <div className="crop-shade" style={{ left: ox, top: oy, width: w, height: h }} />
      <div className="crop-rect" style={style} onPointerDown={down("move")} tabIndex={0} onKeyDown={onKey}
        aria-label={`Crop area ${pw} by ${ph} pixels. Use arrow keys to move.`}>
        <div className="crop-grid" />
        {handles.map((m) => <div key={m} className={`crop-handle h-${m}`} onPointerDown={down(m)} />)}
        <span className="crop-dims">{pw} × {ph} px ({((pw * ph) / 1e6).toFixed(1)} MP)</span>
      </div>
    </div>
  );
}
