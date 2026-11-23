import { useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Debounced, abortable rendering of a preview image. Keeps showing the
 * previous image while a new one is being rendered. */
export function useRenderedImage(photoId: string | null, body: object | null, delay = 120) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const urlRef = useRef<string | null>(null);
  const key = photoId && body ? photoId + JSON.stringify(body) : "";

  useEffect(() => {
    if (!photoId || !body) return;
    const ctrl = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true);
      try {
        const blob = await api.render(photoId, body, ctrl.signal);
        const next = URL.createObjectURL(blob);
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = next;
        setUrl(next);
        setError(null);
      } catch (e) {
        if ((e as Error).name !== "AbortError") setError((e as Error).message);
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    }, delay);
    return () => {
      window.clearTimeout(timer);
      ctrl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => {
    // New photo: drop the old image immediately.
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = null;
    setUrl(null);
  }, [photoId]);

  useEffect(() => () => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
  }, []);

  return { url, loading, error };
}

export function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const r = entries[0].contentRect;
      setSize({ w: Math.round(r.width), h: Math.round(r.height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size] as const;
}

/** devicePixelRatio that updates when the window moves to a monitor with a
 * different Windows scaling (e.g. laptop at 150% + external monitor at 100%). */
export function useDevicePixelRatio(): number {
  const [dpr, setDpr] = useState(() => window.devicePixelRatio || 1);
  useEffect(() => {
    const mq = window.matchMedia(`(resolution: ${dpr}dppx)`);
    const onChange = () => setDpr(window.devicePixelRatio || 1);
    mq.addEventListener("change", onChange);
    window.addEventListener("resize", onChange);
    return () => { mq.removeEventListener("change", onChange); window.removeEventListener("resize", onChange); };
  }, [dpr]);
  return dpr;
}

/** True when a CSS media query matches (re-evaluated on resize/snap). */
export function useMediaQuery(query: string): boolean {
  const [match, setMatch] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setMatch(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return match;
}
