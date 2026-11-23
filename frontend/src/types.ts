export type Look = "natural" | "crisp" | "soft_background";
export type Aspect = "original" | "free" | "3:2" | "4:3" | "1:1" | "16:9";

export interface Sliders {
  exposure: number;
  warmth: number;
  highlights: number;
  shadows: number;
  color: number;
  noise_reduction: number;
  detail: number;
}

export interface Internal {
  tint: number;
  contrast: number;
  black: number;
  clarity: number;
}

export interface Crop {
  aspect: Aspect;
  portrait: boolean;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Subject {
  use_mask: boolean;
  background_nr: number;
}

export interface Recipe {
  schema_version: number;
  pipeline_version: string;
  look: Look;
  strength: number;
  sliders: Sliders;
  internal: Internal;
  subject: Subject;
  crop: Crop | null;
  auto_applied: boolean;
}

export interface Camera {
  make_raw: string;
  model_raw: string;
  make: string;
  model: string;
  source: string;
  identified: boolean;
  display_name: string;
}

export interface Metadata {
  camera: Camera;
  lens: string;
  iso: number | null;
  exposure_time: [number, number] | null;
  shutter_display: string;
  f_number: number | null;
  focal_length: number | null;
  datetime_original: string;
  has_gps: boolean;
}

export interface Photo {
  id: string;
  original_name: string;
  source: { path: string; kind: "linked" | "imported_copy" };
  source_available: boolean;
  status: "queued" | "processing" | "ready" | "error";
  status_message: string;
  decode_status: "pending" | "supported" | "unsupported" | "failed";
  decode_error: string;
  decode_detail?: string;
  format_note?: string;
  preview_kind: "none" | "embedded" | "rendered";
  container?: string;
  format_label?: string;
  kind?: string;
  metadata?: Metadata;
  decoder_info?: Record<string, unknown>;
  full_size?: [number, number];
  recipe: Recipe;
  summary: string;
  mask: MaskInfo | null;
  edit_level?: EditLevel;
}

export interface EditLevel { level: "none" | "light" | "moderate" | "strong"; notes: string[] }
export interface Limits { enabled: boolean; limits: Record<string, [number, number]> }

export interface MaskInfo {
  status: "good" | "uncertain" | "none";
  message: string;
  accepted: boolean;
  usable: boolean;
  has_mask: boolean;
  birds: number;
  detection: string;
  seconds: number;
  points: [number, number, number][];
  source: string;
  shape: [number, number] | null;
}

export interface SubjectStatus {
  installed: boolean;
  enabled: boolean | null;
  runtime: string;
  models: { key: string; name: string; license: string; size_mb: number | null; intact: boolean }[];
}

export interface HistoryEntry { label: string; time: number; recipe: Recipe }
export interface History { entries: HistoryEntry[]; index: number }

export interface JobResult {
  item: string;
  ok: boolean;
  message: string;
  output?: string;
}

export interface Job {
  id: string;
  kind: "import" | "export" | "auto";
  title: string;
  total: number;
  done: number;
  status: "queued" | "running" | "done" | "cancelled" | "failed";
  message: string;
  item_progress: number;
  results: JobResult[];
  finished: number | null;
}

export interface Settings {
  export_folder: string;
  export_format: "jpeg" | "tiff16";
  jpeg_quality: number;
  long_edge: number | null;
  keep_gps: boolean;
  subject_detection: boolean | null;
  natural_limits: boolean;
}

export const BASELINE: Recipe = {
  schema_version: 1,
  pipeline_version: "1.0",
  look: "natural",
  strength: 100,
  sliders: { exposure: 0, warmth: 0, highlights: 0, shadows: 0, color: 0, noise_reduction: 0, detail: 0 },
  internal: { tint: 0, contrast: 0, black: 0, clarity: 0 },
  subject: { use_mask: false, background_nr: 0 },
  crop: null,
  auto_applied: false,
};

export interface DisplayState {
  photo_id: string | null;
  recipe: Recipe | null;
  compare: "after" | "before" | "slider" | "side";
  name: string;
}
