import { api } from "../api";
import { IconAlert, IconCamera, IconCheck } from "../icons";
import type { Photo } from "../types";
import { InfoTip, Section } from "../ui";

export function InfoPanel({ photo, onLocate, onRetry, dngConverter, onUseConverter }: {
  photo: Photo; onLocate: () => void; onRetry: () => void; dngConverter: boolean; onUseConverter: () => void }) {
  const md = photo.metadata;
  const cam = md?.camera;
  const isRaw = photo.kind === "raw";
  const ok = photo.decode_status === "supported";
  const decodeText: Record<Photo["decode_status"], string> = {
    pending: "Reading photo…",
    supported: photo.converted_dng ? "Decoded via Adobe DNG Converter" : "Decoded",
    unsupported: "Not supported by the built-in decoder",
    failed: "Could not be decoded",
    needs_converter: "Needs Adobe DNG Converter",
  };
  const exposure = [md?.iso ? `ISO ${md.iso}` : "", md?.shutter_display ?? "", md?.f_number ? `f/${md.f_number}` : "",
    md?.focal_length ? `${md.focal_length} mm` : ""].filter(Boolean);
  const getConverter = () => api.openHelp("dng_converter").catch(() => {});

  return (
    <Section id="photo" title="Photo" icon={<IconCamera size={16} />}>
      <div className="camera-card">
        <div className="camera-line">
          <span className="camera-name">{cam?.identified ? cam.display_name : md ? "Unknown camera" : "Reading…"}</span>
          {cam?.identified && (cam.make_raw || cam.model_raw) && (
            <InfoTip text={`Exactly as stored in the file: “${cam.make_raw}” / “${cam.model_raw}” (${cam.source}).`} />
          )}
        </div>
        {md?.lens && <div className="lens-line">{md.lens}</div>}
        {exposure.length > 0 && (
          <div className="exif-pills">{exposure.map((e) => <span key={e} className="pill">{e}</span>)}</div>
        )}
        <dl className="meta-grid">
          <dt>File</dt><dd title={photo.original_name}>{photo.original_name}</dd>
          {photo.format_label && (<><dt>Type</dt><dd>{photo.format_label}{isRaw ? " RAW" : ""}</dd></>)}
          {photo.full_size && (<><dt>Size</dt><dd>{photo.full_size[0]} × {photo.full_size[1]} px</dd></>)}
          {md?.datetime_original && (<><dt>Taken</dt><dd>{md.datetime_original.replace(/^(\d{4}):(\d{2}):(\d{2})/, "$1-$2-$3")}</dd></>)}
          {md?.has_gps && (<><dt>Location</dt><dd>GPS (removed on export unless kept)</dd></>)}
        </dl>
        <div className={`decode-status ${ok ? "ok" : photo.decode_status === "pending" ? "busy" : "bad"}`}>
          {ok ? <IconCheck size={14} /> : photo.decode_status === "pending" ? null : <IconAlert size={14} />}
          <span>{decodeText[photo.decode_status]}</span>
        </div>
      </div>

      {photo.format_note && <p className="note warn">{photo.format_note}</p>}
      {photo.decode_error && <p className="note error" role="alert">{photo.decode_error}</p>}
      {(photo.profile_warning || photo.decode_status === "needs_converter") && (
        <div className="callout warn" role="alert">
          {photo.profile_warning && <p>{photo.profile_warning}</p>}
          <div className="btn-row">
            <button className="btn" onClick={getConverter}>Get Adobe DNG Converter</button>
            <button className="btn primary" onClick={onRetry}>Try again</button>
          </div>
        </div>
      )}
      {isRaw && !photo.converted_dng && ok && !photo.profile_warning && (
        <div className="callout subtle">
          <p>Colors or edges look wrong (e.g. a very new camera)?</p>
          {dngConverter
            ? <button className="btn" onClick={onUseConverter}>Use Adobe DNG Converter</button>
            : <button className="btn" onClick={getConverter}>Get Adobe DNG Converter</button>}
        </div>
      )}
      {photo.decode_detail && <details className="details"><summary>Technical detail</summary><code>{photo.decode_detail}</code></details>}
      {photo.preview_kind === "embedded" && photo.decode_status === "pending" && (
        <p className="note">Showing the camera's preview until the RAW is ready. Edits always use the RAW data.</p>
      )}
      {!photo.source_available && (
        <div className="callout error" role="alert">
          <p><strong>Original file not found</strong><br /><span className="path">{photo.source.path}</span></p>
          <p>Your edits are kept. Point to the file's new location to export or view at 100%.</p>
          <button className="btn primary" onClick={onLocate}>Locate original…</button>
        </div>
      )}
      <div className="btn-row">
        {photo.source_available && (photo.decode_status === "failed" || photo.decode_status === "unsupported") && (
          <button className="btn" onClick={onRetry}>Try again</button>
        )}
        {photo.source_available && ok && (
          <button className="btn ghost small" onClick={onRetry} title="Open this photo again from the original file (edits are kept)">Reload photo</button>
        )}
      </div>
      {photo.source_available && (
        <details className="details"><summary>Original location</summary>
          <span className="path">{photo.source.path}</span>
          {photo.source.kind === "imported_copy" && <div className="muted">(a copy of a file dragged into the browser)</div>}
        </details>
      )}
    </Section>
  );
}
