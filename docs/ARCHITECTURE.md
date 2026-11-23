# Architecture

```
Browser (React/TypeScript UI, served by the backend)
   │  HTTP on 127.0.0.1 only; per-launch token; Host/Origin checks
   ▼
FastAPI backend (Python)  ──  job pools: "import" (1 worker), "heavy" (1 worker)
   ├─ formats.py    content sniffing (magic bytes); extension is only a hint
   ├─ metadata.py   EXIF/TIFF (ExifRead), CR3 boxes, RAF header, LibRaw fields
   ├─ camera.py     make/model normalisation (raw values always retained)
   ├─ decode.py     rawpy/LibRaw RAW decode; JPEG/TIFF with ICC → working space
   ├─ noise.py      per-image noise model estimated from the pixels
   ├─ auto.py       image statistics → automatic recipe
   ├─ pipeline.py   the rendering pipeline (identical for preview tiles & export)
   ├─ summary.py    plain-language summary from the effective parameters
   ├─ store.py      project records, recipes, preview caches (atomic writes)
   ├─ export.py     JPEG / 16-bit TIFF, ICC, EXIF/XMP, GPS policy, unique names
   ├─ masks.py      optional bird detection (YOLOX) + segmentation (MobileSAM), ONNX Runtime
   ├─ app_window.py desktop control window of the installed app (hosts native dialogs)
   ├─ dialogs.py    native Windows file/folder pickers (tkinter)
   └─ security.py   localhost guard middleware
```

The installed app is `BirdPhotoEditor.exe` (PyInstaller one-folder build, `packaging/birdedit.spec`)
wrapped by an Inno Setup installer (`packaging/installer.iss`), both produced and smoke-tested by
`.github/workflows/windows-build.yml` on a Windows runner. The .exe shows a small control window and runs
the same server as `python -m birdedit`.

`python -m birdedit` picks a free port (8765–8784), detects an already-running copy, starts
uvicorn bound to 127.0.0.1, opens the browser, and reports startup failures with a message box
and a log file. The UI is a static build, so end users need no Node.js.

## Image pipeline (pipeline version 1.0)

| # | Stage | Domain / precision | Notes |
|---|---|---|---|
| 0 | **RAW decode** | LibRaw → 16-bit linear → float32 | Camera as-shot WB, LibRaw camera matrix, AHD demosaic, highlight mode *clip*, `no_auto_bright`, gamma 1.0, output **ProPhoto RGB (linear, D50)**. Half-size decode for previews; full decode for 100% view and export. |
| 0' | JPEG/TIFF decode | 8/16-bit → float32 | ICC matrix/TRC profiles parsed and applied at full precision; LUT profiles via LittleCMS; no profile → sRGB assumed. Converted to linear ProPhoto. |
| 1 | **White balance refinement** | linear ProPhoto | Warmth/tint gains, normalised so neutral luminance is unchanged. Auto: two-pass near-neutral pixel search, 35% damped correction, capped (±15 warmth, ±10 tint), skipped if <3% neutral pixels. Never uses another photo's WB. |
| 2 | **Exposure + tone curve** | luminance LUT, applied as RGB ratio | Exposure (2^EV), black point, highlight shoulder (maps up to 2 EV of headroom into the top of the range), shadow lift (anchored at black), S-curve contrast. Applied to luminance and multiplied into RGB, so hue and saturation ratios are preserved. All-zero parameters = identity (clip at 1). |
| 3 | **Color intensity** | linear ProPhoto | Vibrance: boosts low-saturation colours more than already-saturated ones; negative values desaturate. |
| 4 | **Gamut map → linear sRGB** | float32 | LibRaw's ProPhoto↔sRGB matrix (verified to match LibRaw's own sRGB output on a real NEF). Out-of-gamut colours are desaturated toward their own luminance, not clipped per channel. |
| 5 | **sRGB transfer curve** | display-encoded float32 | |
| 5' | **Subject weighting** (optional) | per-pixel maps | With a valid bird mask (resampled to the render region): NR strength map = 0.8·NR on the bird, NR + 1.2·background NR elsewhere; sharpening weight 1 on the bird, 0.35 on the background. See docs/BIRD_DETECTION.md. |
| 6 | **Noise reduction** | Y/Cb/Cr on display values | Laplacian-pyramid shrinkage (non-negative garrote). Thresholds per pixel = *k* × expected noise, where expected noise = measured sensor model σ(Y) × the derivative of stages 1–5 at that pixel's brightness × resolution factor. Luma keeps 18% of the removed detail to avoid a plastic look; chroma is smoothed more strongly. |
| 7 | **Sharpening / local contrast** | luma on display values | Unsharp mask (radius ≈ 0.9 px at 100%) gated by the residual noise level; overshoot clamped to the local 3×3 range (+0.008 bright, −0.02 dark) to prevent halos. Local contrast (Crisp look) uses an edge-aware guided filter, weighted to midtones. |
| 8 | **Export** | uint16 tiles → 8/16-bit file | Tiled (1024 px + 128 px context, aligned to the pyramid grid), so memory is bounded and output matches region renders (verified < 2×10⁻⁴ difference). Optional resize in linear light. JPEG 8-bit or TIFF 16-bit, sRGB ICC embedded. |

**Before** = stages 0 → 4 → 5 with all parameters zero (decoder output in sRGB). Before and After
are rendered from the same cached data, with the same crop and colour space.

**Previews**: a ≤2048 px linear ProPhoto preview (float16 on disk) is cached per photo; sliders
re-render from it (debounced), never re-decoding the RAW. Fit-view noise reduction and sharpening
are scaled approximations; the 100% view renders a real full-resolution region with the same
code as export.

### Automatic settings (no machine learning)

Computed from the linear preview and the measured noise model:

* **Exposure:** centre-weighted log-average luminance → target 0.15, 70% damped, limited to ±1.5 EV,
  capped so the 99.5th percentile stays within the highlight shoulder's range, and ≤ +0.3 EV when
  more than 0.5% of pixels are clipped.
* **Highlights:** shoulder sized so the brightest real highlight (99.9th percentile) lands at white;
  a mild shoulder protects near-white feathers even when nothing exceeds white.
* **Shadows:** moderate lift (≤ 30) proportional to the centre-weighted dark fraction.
* **Black point:** only when the darkest tones are lifted (haze), ≤ 3%.
* **Contrast / colour:** from the tonal spread and mean saturation, within small ranges.
* **Noise reduction / detail:** from the measured noise σ at the median brightness after tone mapping.
  ISO is used only if the noise model cannot be measured.

## Nondestructive data model

```
%LOCALAPPDATA%\BirdPhotoEditor\
  projects\default\project.json             photo order
  projects\default\photos\<id>\photo.json    source path + fingerprint, metadata, decode status,
                                             decoder info, noise model, full size
  projects\default\photos\<id>\recipe.json   look, strength, sliders, internal values, crop,
                                             pipeline_version, schema_version
  projects\default\photos\<id>\facts.json    auto-analysis facts (for the summary)
  projects\default\photos\<id>\history.json  named edit steps + current position (undo/redo)
  projects\default\photos\<id>\mask.png|json bird selection and its provenance/quality
  cache\<id>\preview.npy|thumb.jpg|embedded.jpg
  imported-files\<random>\<name>             copies of files dragged into the browser
  logs\, settings.json
```

IDs are random 128-bit hex strings, validated before any path is built. Metadata values are
never used in paths or commands. Source fingerprint = size + SHA-256 of the first and last MiB;
used to warn when a relocated or changed original differs.

## Concurrency and memory

* One import worker (half-size decodes, ~130 MB for a 45 MP RAW) and one full-resolution worker.
* At most one full-resolution image is held in memory (float32, ~540 MB for 45 MP); it is released
  after each export. 100% view and export share a semaphore; a 100% request during an export gets
  a "busy, try again" message rather than doubling memory.
* Cancellation is checked between files, between pipeline stages of an import, and between export tiles.
* Preview LRU of 4 photos in memory; everything else is on disk.

## Security model

* Bound to 127.0.0.1. Host header must be `127.0.0.1:<port>` or `localhost:<port>` (DNS-rebinding
  protection). A present Origin header must be the app's own origin.
* Every `/api` request needs the per-launch random token (header, or `t=` query for `<img>` URLs),
  which is embedded only in the page the server itself serves. No CORS headers are ever sent.
* Files are read only from paths returned by the native picker, uploaded copies, or relocations the
  user chose. Exports go only to a folder the user chose; the folder is validated and filenames are
  sanitised (reserved characters, device names such as `CON`, length) and reserved with `O_EXCL`.
* The native dialog runs `python -c <fixed script>` with no shell and no user text on the command line.
