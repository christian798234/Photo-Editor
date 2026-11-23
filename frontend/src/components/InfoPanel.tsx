import { api } from "../api";
import type { Photo } from "../types";

function Row({ k, v }: { k: string; v?: string | number | null }) {
  if (v === undefined || v === null || v === "") return null;
  return (<><dt>{k}</dt><dd>{v}</dd></>);
}

export function InfoPanel({ photo, onLocate, onRetry }: { photo: Photo; onLocate: () => void; onRetry: () => void }) {
  const md = photo.metadata;
  const cam = md?.camera;
  const decodeText: Record<Photo["decode_status"], string> = {
    pending: "Not decoded yet",
    supported: "Decoded successfully",
    unsupported: "Not supported by the installed decoder",
    failed: "Could not be decoded",
    needs_converter: "Needs Adobe DNG Converter",
  };
  const isRaw = photo.kind === "raw";
  return (
    <div className="info-panel">
      <h3 className="camera-name">{cam?.identified ? cam.display_name : md ? "Unknown camera" : "Reading…"}</h3>
      {cam?.identified && (cam.make_raw || cam.model_raw) && (
        <div className="small muted" title="Exact values stored in the file">
          From file: “{cam.make_raw}” / “{cam.model_raw}” ({cam.source})
        </div>
      )}
      <dl>
        <Row k="File" v={photo.original_name} />
        <Row k="Type" v={photo.format_label ? `${photo.format_label}${isRaw ? " RAW" : ""}` : undefined} />
        <Row k="Lens" v={md?.lens} />
        <Row k="ISO" v={md?.iso ?? undefined} />
        <Row k="Shutter" v={md?.shutter_display} />
        <Row k="Aperture" v={md?.f_number ? `f/${md.f_number}` : undefined} />
        <Row k="Focal length" v={md?.focal_length ? `${md.focal_length} mm` : undefined} />
        <Row k="Taken" v={md?.datetime_original} />
        <Row k="Dimensions" v={photo.full_size ? `${photo.full_size[0]} × ${photo.full_size[1]} px` : undefined} />
        <Row k="Location" v={md?.has_gps ? "GPS present (removed on export unless you keep it)" : undefined} />
        <dt>Decoding</dt>
        <dd className={`decode-${photo.decode_status}`}>{decodeText[photo.decode_status]}</dd>
      </dl>
      {photo.format_note && <p className="small warn">{photo.format_note}</p>}
      {photo.decode_error && <p className="error-text" role="alert">{photo.decode_error}</p>}
      {photo.decode_status === "needs_converter" && (
        <div className="row">
          <button onClick={() => api.openHelp("dng_converter").catch(() => {})}>Get Adobe DNG Converter (free)</button>
          <button className="primary" onClick={onRetry}>Try again</button>
        </div>
      )}
      {photo.converted_dng && (
        <p className="small muted">Decoded via Adobe DNG Converter{photo.high_efficiency ? " (Nikon High Efficiency NEF)" : ""}.
          Your original file is unchanged.</p>
      )}
      {photo.decode_detail && <details className="small muted"><summary>Technical detail</summary>{photo.decode_detail}</details>}
      {photo.preview_kind === "embedded" && photo.decode_status === "pending" && (
        <p className="small warn">Showing the camera's embedded JPEG until the RAW rendering is ready. Edits always use the RAW data.</p>
      )}
      {!photo.source_available && (
        <div className="missing" role="alert">
          <p><strong>Original file not found</strong> at:<br /><span className="path">{photo.source.path}</span></p>
          <p className="small">Your edits are kept. Point to the file's new location to export or view at 100% again.</p>
          <button onClick={onLocate}>Locate original…</button>
        </div>
      )}
      {photo.source_available && (photo.decode_status === "failed" || photo.decode_status === "unsupported") && (
        <button onClick={onRetry}>Try again</button>
      )}
      {photo.source_available && (
        <details className="small muted"><summary>Original location</summary>
          <span className="path">{photo.source.path}</span>
          {photo.source.kind === "imported_copy" && <div>(a copy of a file dragged into the browser)</div>}
        </details>
      )}
    </div>
  );
}
