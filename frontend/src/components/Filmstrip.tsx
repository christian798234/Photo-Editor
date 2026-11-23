import { imageUrl } from "../api";
import type { Photo } from "../types";

interface Props {
  photos: Photo[];
  currentId: string | null;
  selected: Set<string>;
  onSelect: (id: string, mode: "single" | "toggle" | "range") => void;
  onRemove: (id: string) => void;
}

function statusLabel(p: Photo): { text: string; cls: string } {
  if (!p.source_available) return { text: "Missing", cls: "st-error" };
  if (p.decode_status === "unsupported") return { text: "Unsupported", cls: "st-error" };
  if (p.decode_status === "failed" || p.status === "error") return { text: "Error", cls: "st-error" };
  if (p.status !== "ready") return { text: p.preview_kind === "embedded" ? "Rendering…" : "Processing…", cls: "st-busy" };
  if (p.recipe.auto_applied) return { text: "Edited", cls: "st-done" };
  return { text: "Ready", cls: "st-ready" };
}

export function Filmstrip({ photos, currentId, selected, onSelect, onRemove }: Props) {
  return (
    <div className="filmstrip" role="listbox" aria-label="Imported photos" aria-multiselectable="true">
      {photos.map((p) => {
        const st = statusLabel(p);
        const hasThumb = p.preview_kind !== "none";
        return (
          <div key={p.id} role="option" aria-selected={selected.has(p.id)} tabIndex={0}
            className={`thumb ${p.id === currentId ? "current" : ""} ${selected.has(p.id) ? "selected" : ""}`}
            onClick={(e) => onSelect(p.id, e.shiftKey ? "range" : e.ctrlKey || e.metaKey ? "toggle" : "single")}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(p.id, e.ctrlKey ? "toggle" : "single"); }
              if (e.key === "Delete") onRemove(p.id);
            }}
            title={`${p.original_name}\n${p.metadata?.camera?.display_name ?? ""}`}>
            {hasThumb ? <img src={imageUrl(p.id, "thumb.jpg", `${p.status}-${p.preview_kind}`)} alt="" loading="lazy" />
              : <div className="thumb-placeholder">{p.original_name.split(".").pop()?.toUpperCase()}</div>}
            <span className={`thumb-status ${st.cls}`}>{st.text}</span>
            <span className="thumb-name">{p.original_name}</span>
            <button className="thumb-remove" aria-label={`Remove ${p.original_name} from project`}
              onClick={(e) => { e.stopPropagation(); onRemove(p.id); }}>×</button>
          </div>
        );
      })}
    </div>
  );
}
