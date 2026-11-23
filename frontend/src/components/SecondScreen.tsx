import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { DisplayState } from "../types";
import { BASELINE } from "../types";
import { useDevicePixelRatio, useElementSize, useRenderedImage } from "../useRender";

function Pane({ state, before, label }: { state: DisplayState; before: boolean; label?: string }) {
  const [ref, size] = useElementSize<HTMLDivElement>();
  const dpr = useDevicePixelRatio();
  const maxEdge = Math.min(4096, Math.max(256, Math.ceil(Math.max(size.w, size.h) * dpr)));
  const body = useMemo(() => (state.recipe && size.w > 0 ? {
    recipe: before ? { ...BASELINE, crop: state.recipe.crop } : state.recipe, before, max_edge: maxEdge } : null),
  [state.recipe, before, maxEdge, size.w]);
  const { url } = useRenderedImage(state.photo_id, body, 60);
  return (
    <div className="ss-pane" ref={ref}>
      {url && <img src={url} alt={label ?? "Photo"} draggable={false} />}
      {label && <span className="pane-label">{label}</span>}
    </div>
  );
}

/** Large preview for a second monitor; follows the main window. */
export function SecondScreen() {
  const [state, setState] = useState<DisplayState | null>(null);
  const [hint, setHint] = useState(true);

  useEffect(() => {
    document.title = "Bird Photo Editor - Second screen";
    let stopped = false;
    const ctrl = new AbortController();
    (async () => {
      let v = 0;
      while (!stopped) {
        try {
          const r = await api.display(v, ctrl.signal);
          if (r.version !== v) { v = r.version; setState(r.state); }
        } catch {
          if (stopped) return;
          await new Promise((res) => setTimeout(res, 2000));
        }
      }
    })();
    const t = window.setTimeout(() => setHint(false), 6000);
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") window.close(); };
    window.addEventListener("keydown", key);
    return () => { stopped = true; ctrl.abort(); window.clearTimeout(t); window.removeEventListener("keydown", key); };
  }, []);

  if (!state?.photo_id || !state.recipe) {
    return <div className="second-screen empty"><p>Select a photo in the main Bird Photo Editor window.</p></div>;
  }
  const split = state.compare === "side" || state.compare === "slider";
  return (
    <div className="second-screen" onMouseMove={() => setHint(true)}>
      {split ? (
        <div className="ss-split">
          <Pane state={state} before label="Before" />
          <Pane state={state} before={false} label="After" />
        </div>
      ) : (
        <Pane state={state} before={state.compare === "before"} label={state.compare === "before" ? "Before" : undefined} />
      )}
      <div className={`ss-info ${hint ? "" : "hidden"}`}>{state.name} · follows the main window · close this window to stop</div>
    </div>
  );
}
