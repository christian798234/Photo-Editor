import type { Aspect, Crop } from "./types";

export function aspectRatio(aspect: Aspect, portrait: boolean, fullSize: [number, number]): number | null {
  const map: Record<string, number> = { "3:2": 3 / 2, "4:3": 4 / 3, "1:1": 1, "16:9": 16 / 9 };
  let r: number | null = null;
  if (aspect === "original") r = Math.max(fullSize[0], fullSize[1]) / Math.min(fullSize[0], fullSize[1]);
  else if (aspect in map) r = map[aspect];
  if (r === null) return null;
  return portrait ? 1 / r : r;
}

/** Largest centred crop with the given aspect (pixel ratio w/h). */
export function fitAspect(crop: Crop, fullSize: [number, number]): Crop {
  const r = aspectRatio(crop.aspect, crop.portrait, fullSize);
  if (r === null) return crop;
  const [fw, fh] = fullSize;
  const cx = crop.x + crop.w / 2, cy = crop.y + crop.h / 2;
  let wpx = crop.w * fw, hpx = crop.h * fh;
  if (wpx / hpx > r) wpx = hpx * r; else hpx = wpx / r;
  let w = wpx / fw, h = hpx / fh;
  if (w > 1) { h /= w; w = 1; }
  if (h > 1) { w /= h; h = 1; }
  const x = Math.min(Math.max(0, cx - w / 2), 1 - w);
  const y = Math.min(Math.max(0, cy - h / 2), 1 - h);
  return { ...crop, x, y, w, h };
}

export function fullCrop(aspect: Aspect = "free"): Crop {
  return { aspect, portrait: false, x: 0, y: 0, w: 1, h: 1 };
}

export function cropPixels(crop: Crop | null, fullSize: [number, number]): [number, number] {
  if (!crop) return fullSize;
  return [Math.round(crop.w * fullSize[0]), Math.round(crop.h * fullSize[1])];
}
