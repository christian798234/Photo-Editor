# Bird Photo Editor

A local Windows 11 application that automatically develops **bird photographs from RAW files**.
Import photos, click **Auto Edit**, compare before/after, adjust a few sliders if you like, and
export finished JPEG or 16-bit TIFF files.

* Runs entirely on your computer and opens in your web browser. No accounts, subscriptions,
  cloud uploads or telemetry.
* Detects the camera (Nikon, Sony, Canon, Fujifilm, …) from each file automatically. Mixed
  batches are fine.
* Never modifies your original files.

> **Status:** working MVP (Milestones 1 and 2). It is started with a double-click launcher; it is
> **not** a packaged Windows installer (.exe/.msi). See [What has and has not been verified](#what-has-and-has-not-been-verified).

---

## 1. Install (one time)

You need **Windows 11**, about **1.5 GB** of free disk space and an internet connection for
setup. 8 GB of RAM works; 16 GB is recommended for 45-megapixel cameras.

1. **Install Python 3.12** from <https://www.python.org/downloads/windows/>
   ("Windows installer (64-bit)"). The default options are fine. Keep **"tcl/tk and IDLE"**
   ticked, because it provides the Windows file picker.
   *If you skip this step, Setup offers to install Python 3.12 for you with `winget`.*
2. Unzip the Bird Photo Editor folder somewhere in your user folder, e.g. `Documents\Bird Photo Editor`.
3. Double-click **`Setup Bird Photo Editor.bat`**. It takes a few minutes and does not need administrator rights.

Prefer PowerShell? Open PowerShell in the app folder and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Setup.ps1
```

`-ExecutionPolicy Bypass` applies only to this one command; it does not change your system settings.

## 2. Start

Double-click **`Start Bird Photo Editor.bat`** (or the desktop shortcut Setup can create). Your
browser opens at `http://127.0.0.1:8765/` (or the next free port). A console window titled
*"Bird Photo Editor - keep this window open"* stays open: **closing it quits the app.**

Starting it a second time just opens the browser on the copy that is already running.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-BirdPhotoEditor.ps1
```

## 3. Using it

The steps across the top of the window show where you are: **1. Import → 2. Auto Edit → 3. Review → 4. Export**.

| Step | What to do |
|---|---|
| **Import Photos** | Click **Import Photos** to pick files with the normal Windows dialog. The app *links* to your originals (no copies). You can also **drag files onto the window**; the browser can't reveal where dragged files live, so those are *copied* into the app's data folder. |
| **Auto Edit** | Edits the current photo. **Auto Edit All** edits every imported photo, each one analysed individually. |
| **Review** | Use **After / Before / Before/After slider / Side by side**. **Fit** shows the whole photo; **100%** (or double-click the photo) shows real pixels: drag or use the arrow keys to pan. Judge sharpness and noise at 100%. |
| **Export…** | Choose photos, a folder (**Choose…** opens the Windows folder picker), JPEG or 16-bit TIFF, optional resizing and whether to keep GPS. You'll see a result for each file. |

A short sentence under the photo describes what Auto Edit did, e.g. *"Brightened the image slightly
(+0.4 EV), protected bright highlights and applied light noise reduction across the whole image."*
It is generated from the actual settings.

### Controls

* **Look:** *Natural* (default, documentary) or *Crisp Detail* (a little more detail and contrast).
  *Soft Background* is shown but **disabled**: it needs a reliable bird mask (see Optional features).
* **Overall edit strength:** blends between the unedited baseline (0%) and the full edit (100%; up to 150%).
* **Exposure, Warmth, Highlights, Shadows, Color intensity, Noise reduction, Detail / sharpness.**
  Double-click a slider to set it to zero. *Highlights* below zero protects bright and white feathers.
* **Advanced** (hidden by default): tint, contrast, black point and local contrast, which Auto Edit sets per photo.
* **Crop:** Original, Free, 3:2, 4:3, 1:1, 16:9 (with a portrait option). The remaining pixel size is
  shown while you crop. There are no automatic crop suggestions (see Limitations).
* **Undo / Redo** (Ctrl+Z / Ctrl+Y), **Reset** (back to the unedited baseline), **Copy settings / Paste settings**.
  Paste applies the look, strength and sliders to the current photo, or to every selected photo
  (Ctrl-click or Shift-click thumbnails). Camera-specific color data is never copied between photos.

### What "Before" means

"Before" is the **baseline RAW rendering**. It uses your camera's as-shot white balance, the decoder's
color matrix for that camera, no automatic brightening, no noise reduction or sharpening, and the
standard sRGB tone curve. RAW files usually look flatter and darker than camera JPEGs at this stage;
that is expected. Before and After always use the same crop and color space.

## How cameras are identified

When you import, the app reads the **Make** and **Model** stored *inside* the file (EXIF/TIFF tags;
special readers for Canon CR3 and Fujifilm RAF). It never guesses from the file name or extension.

* The panel shows a tidy name ("Nikon Z 8") and, underneath, the exact text stored in the file
  ("NIKON CORPORATION" / "NIKON Z 8"). Sony reports internal model codes such as `ILCE-7RM5`; they are
  shown as reported, not translated.
* **Recognising a camera is not the same as being able to decode its RAW file.** Decoding is reported
  separately (*Decoded successfully / Not supported by the installed decoder / Could not be decoded*).
  If the camera is recognised but its RAW variant isn't supported, you'll see both facts.
* No camera information → **"Unknown camera"**; the photo is still processed if it can be decoded.
* Every photo is processed with its own white balance and color data, so mixed Nikon/Sony batches are safe.

**Formats:** Nikon NEF/NRW and Sony ARW (priority), plus Canon CR2/CR3, Fujifilm RAF, Olympus/OM ORF,
Panasonic RW2, DNG and others **when the installed LibRaw 0.22.2 supports that camera and compression
variant**. Also JPEG and TIFF (8/16-bit, with embedded color profiles honoured).

## Your files and data

* **Originals are only ever read.** Exports never overwrite anything; if a name exists, ` (2)`, ` (3)` … is added.
* Edits are stored as small "recipes" next to the project data, not in your photos:
  `%LOCALAPPDATA%\BirdPhotoEditor\projects\default\photos\<id>\recipe.json`. Each recipe holds the
  settings, the decoder settings and the pipeline version needed to reproduce an export.
* Previews and thumbnails: `%LOCALAPPDATA%\BirdPhotoEditor\cache`. You can delete this folder at any
  time. Previews of linked photos are rebuilt by choosing *Try again*.
* Photos dragged into the browser are copied to `%LOCALAPPDATA%\BirdPhotoEditor\imported-files`.
  **Removing a photo from the app (× on its thumbnail) never deletes your original.**
* Your photos and edits reappear the next time you start the app.

**If you move or delete an original:** the photo stays in the app with its edits and preview, marked
*Missing*. Exporting and 100% view need the original. Click **Locate original…** and point to the
file's new location. If the file isn't identical to the one imported, you'll be asked to confirm.

## Exports

* **JPEG:** full resolution (or resized), 8-bit sRGB with an embedded sRGB profile.
* **16-bit TIFF:** sRGB with an embedded profile, deflate-compressed. The processing pipeline works in
  32-bit floating point, so these files really contain more than 8 bits of tonal detail.
* Exports are rendered **from the original file with the saved recipe** at full resolution, not from
  the screen preview.
* Camera make/model, lens, exposure settings, date, artist and copyright are kept. **GPS location is
  removed unless you tick "Keep GPS location".** Orientation is applied to the pixels.

## Privacy and security

* The app's server listens only on `127.0.0.1` (your own computer), never on your network.
* Requests must carry a secret that is created each time the app starts and is known only to the
  page it serves. Requests from other websites and other host names are refused.
* No photos, metadata or usage data are sent anywhere. The app makes no internet connections at all
  (Setup downloads Python packages once).

---

## Features

**Working**

* Import (Windows dialog, drag-and-drop), content-based format detection, per-file camera identification.
* Genuine RAW decoding with LibRaw (via rawpy). The embedded camera JPEG is shown, clearly labelled, only until the RAW rendering is ready.
* Automatic, image-dependent editing (exposure with highlight protection, moderate shadow lift,
  conservative white-balance refinement, tone/contrast, vibrance-style color, measured-noise-based
  noise reduction, halo-limited sharpening). Natural and Crisp Detail looks.
* Before/after slider, side-by-side, fit and real 100% view with panning.
* Sliders, advanced controls, crop with aspect ratios, undo/redo/reset, copy/paste settings.
* Batch import, Auto Edit All and batch export with progress, cancellation and per-file results.
* Nondestructive recipes, project reopening, missing-original handling.
* JPEG and 16-bit TIFF export with ICC profile and metadata policy.

**Optional / not installed**

* **Bird-aware (subject mask) processing, Soft Background look and automatic crop suggestions:** not
  implemented yet (Milestone 3). Nothing in the app claims to detect birds, eyes or feathers. See
  [docs/SUBJECT_MASKS_PROPOSAL.md](docs/SUBJECT_MASKS_PROPOSAL.md). Model files would only be
  downloaded after you agree.
* **GPU acceleration:** not implemented; all processing is on the CPU.

**Known limitations**

* All adjustments are global (whole image). The centre-weighted exposure metering is a heuristic,
  not subject detection, so a small bird far from the centre may not be metered ideally.
* Noise reduction smooths noise; it cannot restore detail that was never recorded. Clipped
  (blown-out) highlights and missed focus cannot be recovered. The summary warns when a noticeable
  part of the photo was clipped in camera.
* No lens-profile, distortion, vignetting or chromatic-aberration correction (not implemented, so not offered).
* No hot-pixel removal, healing, or local brushes.
* Fit-view previews approximate noise reduction and sharpening; the **100% view and exports are exact**.
* Previews at fit size take roughly 0.3 to 1 s to update after a slider change. Exporting a 12 MP RAW took
  about 6 s on the 4-core test machine (decode + processing). Your speed will differ.
* Not a packaged Windows installer: Python is required and is set up by `Setup Bird Photo Editor.bat`.

## What has and has not been verified

| Item | Status |
|---|---|
| Automated tests (65 tests) | Pass on Linux (Python 3.13). Windows paths, long paths and reserved names are tested by simulating Windows path rules. |
| Real **Nikon** RAW | Verified end-to-end with one public NEF (Nikon D3S, ISO 3200, NASA image): identify → decode → auto edit → 100% view → JPEG and 16-bit TIFF export. |
| Real **Sony** RAW | **Not verified**: no Sony ARW sample was available. Sony identification logic is tested with synthetic files only. **Please supply one or more ARW files.** |
| Other real RAW files | Only metadata-only stub files (Canon CR3, Fujifilm RAF, Panasonic RW2, DNG, Nikon D70): camera identification works; their decode errors are reported correctly. |
| Bird-specific visual quality | **Not verified**: no bird photographs were available (dark bird on bright sky, white bird, high-ISO, small bird, several birds, no bird). |
| **Windows 11** | **Not run on Windows.** Development and testing happened on Linux. All packages were confirmed to exist as prebuilt Windows wheels for Python 3.12/3.13, but `Setup.ps1`, the launcher, the Windows file dialogs and "Open folder" have not been executed on Windows. |

## Troubleshooting

* **"Port … is already used by another program"**: another program is using ports 8765–8784. Close it, or run
  `.\scripts\Start-BirdPhotoEditor.ps1 --port 9000`.
* **Setup says no Python found**: install Python 3.12 (64-bit) from python.org and run Setup again.
* **The Windows file picker doesn't appear**: Python's tcl/tk component is missing (Setup warns about
  this). Drag photos onto the window instead, or modify your Python install to add "tcl/tk and IDLE".
* **Windows SmartScreen warns about the .bat file**: choose *More info → Run anyway*, or right-click the
  downloaded zip → *Properties* → *Unblock* before extracting.
* **Logs:** `%LOCALAPPDATA%\BirdPhotoEditor\logs\bird-photo-editor.log`.
* **Uninstall:** delete the app folder and `%LOCALAPPDATA%\BirdPhotoEditor` (this removes edits, previews and copies of
  dragged-in photos; your original photos and exports are not affected).

---

## For developers

Ordinary users need only Python (installed by Setup). Developers additionally need **Node.js 18+**
to rebuild the web interface; the built files are committed in `backend/birdedit/web/`.

```powershell
# backend tests
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q

# optional: real-camera end-to-end tests (skipped, and reported as unverified, without samples)
$env:BIRDEDIT_SAMPLES = "D:\raw-samples"
.\.venv\Scripts\python -m pytest -q tests\test_raw_samples.py -rs
```

```powershell
# frontend (rebuilds backend\birdedit\web)
cd frontend
npm ci
npm run build

# live development: backend + Vite dev server
cd backend; .\.venv\Scripts\python -m birdedit --dev --port 8765 --token devtoken --no-browser
cd frontend; $env:VITE_BIRDEDIT_TOKEN = "devtoken"; npm run dev
```

Architecture and the exact image pipeline: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
