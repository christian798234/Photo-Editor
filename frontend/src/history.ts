import type { Recipe } from "./types";

const NAMES: Record<string, string> = {
  exposure: "Exposure", warmth: "Warmth", highlights: "Highlights", shadows: "Shadows", color: "Color intensity",
  noise_reduction: "Noise reduction", detail: "Detail", tint: "Tint", contrast: "Contrast", black: "Black point",
  clarity: "Local contrast",
};
const LOOKS: Record<string, string> = { natural: "Natural", crisp: "Crisp Detail", soft_background: "Soft Background" };

function fmt(key: string, v: number): string {
  if (key === "exposure") return `${v > 0 ? "+" : ""}${v.toFixed(2)} EV`;
  const r = Math.abs(v) < 10 && v % 1 !== 0 ? v.toFixed(1) : String(Math.round(v));
  return `${v > 0 ? "+" : ""}${r}`;
}

/** Describe what changed between two recipes in a few words. */
export function describeChange(a: Recipe, b: Recipe): string {
  const parts: string[] = [];
  if (a.look !== b.look) parts.push(`Look: ${LOOKS[b.look] ?? b.look}`);
  if (a.strength !== b.strength) parts.push(`Strength ${Math.round(b.strength)}%`);
  for (const k of Object.keys(b.sliders) as (keyof Recipe["sliders"])[]) {
    if (a.sliders[k] !== b.sliders[k]) parts.push(`${NAMES[k]} ${fmt(k, b.sliders[k])}`);
  }
  for (const k of Object.keys(b.internal) as (keyof Recipe["internal"])[]) {
    if (a.internal[k] !== b.internal[k]) parts.push(`${NAMES[k]} ${fmt(k, b.internal[k])}`);
  }
  if (a.subject.use_mask !== b.subject.use_mask) parts.push(b.subject.use_mask ? "Bird-aware on" : "Bird-aware off");
  else if (a.subject.background_nr !== b.subject.background_nr) parts.push(`Background noise reduction ${Math.round(b.subject.background_nr)}`);
  if (JSON.stringify(a.crop) !== JSON.stringify(b.crop)) parts.push(b.crop ? `Crop ${b.crop.aspect === "free" ? "" : b.crop.aspect}`.trim() : "Crop removed");
  if (!parts.length) return "Edit";
  return parts.length > 2 ? `${parts.slice(0, 2).join(", ")} +${parts.length - 2} more` : parts.join(", ");
}

export function timeAgo(t: number): string {
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(t * 1000).toLocaleDateString();
}
