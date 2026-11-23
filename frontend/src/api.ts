import type { Crop, DisplayState, EditLevel, History, Job, Limits, MaskInfo, Photo, Recipe, Settings, SubjectStatus } from "./types";

function readToken(): string {
  const meta = document.querySelector('meta[name="birdedit-token"]')?.getAttribute("content") ?? "";
  if (meta && !meta.startsWith("__")) return meta;
  return (import.meta.env.VITE_BIRDEDIT_TOKEN as string | undefined) ?? "";
}

export const TOKEN = readToken();

export class ApiError extends Error {
  status: number;
  body: any;
  constructor(status: number, message: string, body?: any) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("X-BirdEdit-Token", TOKEN);
  if (init.body && typeof init.body === "string") headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "Cannot reach the Bird Photo Editor background process. Is its window still open?");
  }
  if (!res.ok) {
    let body: any = null;
    let msg = res.status >= 500
      ? `Something went wrong inside Bird Photo Editor (error ${res.status}). The log file is in %LOCALAPPDATA%\\BirdPhotoEditor\\logs.`
      : `Request failed (${res.status})`;
    try {
      body = await res.json();
      if (typeof body?.detail === "string") msg = body.detail;
      else if (Array.isArray(body?.detail)) msg = body.detail.map((d: any) => d.msg).join("; ");
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg, body);
  }
  return res;
}

async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  return (await request(path, init)).json() as Promise<T>;
}

export const api = {
  photos: () => json<Photo[]>("/api/photos"),
  photo: (id: string) => json<Photo>(`/api/photos/${id}`),
  remove: (id: string) => json(`/api/photos/${id}`, { method: "DELETE" }),
  reprocess: (id: string) => json<Job>(`/api/photos/${id}/reprocess`, { method: "POST" }),
  importDialog: () => json<{ job: Job | null; photo_ids: string[] }>("/api/import/dialog", { method: "POST" }),
  upload: (files: File[]) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f, f.name);
    return json<{ job: Job | null; photo_ids: string[]; rejected: string[] }>("/api/import/upload", {
      method: "POST",
      body: fd,
    });
  },
  relocate: (id: string) => json<{ ok: boolean; cancelled?: boolean }>(`/api/photos/${id}/relocate`, { method: "POST" }),
  relocateConfirm: (id: string, pending_id: string) =>
    json(`/api/photos/${id}/relocate/confirm`, { method: "POST", body: JSON.stringify({ pending_id }) }),
  saveRecipe: (id: string, recipe: Recipe) =>
    json<{ summary: string; recipe: Recipe; edit_level: EditLevel }>(`/api/photos/${id}/recipe`, { method: "PUT", body: JSON.stringify(recipe) }),
  limits: () => json<Limits>("/api/limits"),
  auto: (id: string, look: "natural" | "crisp" | "soft_background") =>
    json<{ recipe: Recipe; summary: string; edit_level: EditLevel }>(`/api/photos/${id}/auto`, { method: "POST", body: JSON.stringify({ look }) }),
  autoAll: (ids: string[], look: "natural" | "crisp") =>
    json<Job>("/api/auto-all", { method: "POST", body: JSON.stringify({ photo_ids: ids, look }) }),
  subjectStatus: () => json<SubjectStatus>("/api/subject/status"),
  detect: (id: string, points?: { x: number; y: number; bird: boolean }[], redetect = false) =>
    json<MaskInfo & { birds: unknown[] }>(`/api/photos/${id}/detect`, { method: "POST", body: JSON.stringify({ points: points ?? null, redetect }) }),
  acceptMask: (id: string) => json(`/api/photos/${id}/mask/accept`, { method: "POST" }),
  clearMask: (id: string) => json(`/api/photos/${id}/mask`, { method: "DELETE" }),
  maskBlob: async (id: string) => (await request(`/api/photos/${id}/mask.png?v=${Date.now()}`)).blob(),
  cropSuggestion: (id: string, aspect: string, portrait: boolean) =>
    json<{ crop: Crop | null; message: string; pixels?: [number, number] }>(`/api/photos/${id}/crop-suggestion`, {
      method: "POST", body: JSON.stringify({ aspect, portrait }) }),
  setDisplay: (state: object) => json<{ version: number }>("/api/display", { method: "POST", body: JSON.stringify(state) }),
  display: (since: number, signal?: AbortSignal) =>
    request(`/api/display?since=${since}`, { signal }).then((r) => r.json() as Promise<{ version: number; state: DisplayState | null }>),
  screens: () => json<{ count: number; second_open: boolean; shell: string }>("/api/screens"),
  secondScreen: () => json<{ ok: boolean; other_monitor: boolean | null; already_open: boolean }>("/api/second-screen", { method: "POST" }),
  history: (id: string) => json<History>(`/api/photos/${id}/history`),
  saveHistory: (id: string, h: History) => json(`/api/photos/${id}/history`, { method: "PUT", body: JSON.stringify(h) }),
  paste: (ids: string[], s: Pick<Recipe, "look" | "strength" | "sliders">) =>
    json("/api/paste", { method: "POST", body: JSON.stringify({ photo_ids: ids, ...s }) }),
  render: async (id: string, body: object, signal: AbortSignal) => {
    const res = await request(`/api/photos/${id}/render`, { method: "POST", body: JSON.stringify(body), signal });
    return res.blob();
  },
  renderRegion: async (id: string, body: object, signal: AbortSignal) => {
    const res = await request(`/api/photos/${id}/render-region`, { method: "POST", body: JSON.stringify(body), signal });
    return {
      blob: await res.blob(),
      x: Number(res.headers.get("X-x")),
      y: Number(res.headers.get("X-y")),
      w: Number(res.headers.get("X-width")),
      h: Number(res.headers.get("X-height")),
    };
  },
  jobs: () => json<Job[]>("/api/jobs"),
  cancelJob: (id: string) => json(`/api/jobs/${id}/cancel`, { method: "POST" }),
  chooseFolder: () => json<{ path: string }>("/api/dialog/folder", { method: "POST" }),
  export: (body: object) => json<Job>("/api/export", { method: "POST", body: JSON.stringify(body) }),
  openHelp: (topic: "dng_converter") => json("/api/open-help", { method: "POST", body: JSON.stringify({ topic }) }),
  openFolder: (path: string) => json("/api/open-folder", { method: "POST", body: JSON.stringify({ path }) }),
  settings: () => json<Settings>("/api/settings"),
  saveSettings: (s: Settings) => json("/api/settings", { method: "PUT", body: JSON.stringify(s) }),
  system: () => json<Record<string, string | number>>("/api/system"),
};

export function imageUrl(id: string, name: "thumb.jpg" | "embedded.jpg", version: string): string {
  return `/api/photos/${id}/image/${name}?t=${encodeURIComponent(TOKEN)}&v=${encodeURIComponent(version)}`;
}
