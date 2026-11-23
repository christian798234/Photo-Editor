import { useEffect, useRef } from "react";
import { api } from "../api";

interface Props {
  photoId: string;
  version: string;            // changes whenever the selection changes
  box: { w: number; h: number };
  fullSize: [number, number];
  show: boolean;
  points: [number, number, number][];   // in mask pixels: x, y, label
  maskShape: [number, number] | null;   // h, w
  clickable: boolean;
  onClick: (x: number, y: number) => void;   // normalised 0..1
}

/** Tinted overlay of the bird selection on top of the uncropped preview. */
export function MaskLayer({ photoId, version, box, fullSize, show, points, maskShape, clickable, onClick }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [fw, fh] = fullSize;
  const ar = fw / fh;
  let w = box.w, h = box.h;
  if (w / h > ar) w = h * ar; else h = w / ar;
  const ox = (box.w - w) / 2, oy = (box.h - h) / 2;

  useEffect(() => {
    let cancelled = false;
    const c = canvas.current;
    if (!c) return;
    const ctx = c.getContext("2d")!;
    ctx.clearRect(0, 0, c.width, c.height);
    if (!show) return;
    api.maskBlob(photoId).then(async (blob) => {
      const bmp = await createImageBitmap(blob);
      if (cancelled) return;
      c.width = bmp.width;
      c.height = bmp.height;
      ctx.drawImage(bmp, 0, 0);
      const img = ctx.getImageData(0, 0, bmp.width, bmp.height);
      const d = img.data;
      for (let i = 0; i < d.length; i += 4) {
        const a = d[i];                    // grey mask value
        d[i] = 255; d[i + 1] = 60; d[i + 2] = 60; d[i + 3] = Math.round(a * 0.45);
      }
      ctx.putImageData(img, 0, 0);
    }).catch(() => { /* no mask yet */ });
    return () => { cancelled = true; };
  }, [photoId, version, show]);

  return (
    <div className={`mask-layer ${clickable ? "clickable" : ""}`}
      onClick={(e) => {
        if (!clickable) return;
        const r = e.currentTarget.getBoundingClientRect();
        const x = (e.clientX - r.left - ox) / w, y = (e.clientY - r.top - oy) / h;
        if (x >= 0 && x <= 1 && y >= 0 && y <= 1) onClick(x, y);
      }}>
      <canvas ref={canvas} style={{ left: ox, top: oy, width: w, height: h }} aria-hidden="true" />
      {maskShape && points.map(([px, py, lab], i) => (
        <span key={i} className={`sel-point ${lab ? "pos" : "neg"}`}
          style={{ left: ox + (px / maskShape[1]) * w, top: oy + (py / maskShape[0]) * h }}>{lab ? "+" : "−"}</span>
      ))}
    </div>
  );
}
