# Bird Photo Editor

A local Windows 11 application that automatically develops **bird photographs from RAW files**.
Import photos, click **Auto Edit**, compare before/after, adjust a few sliders if you like, and
export finished JPEG or 16-bit TIFF files.

* Runs entirely on your computer and opens in your web browser. No accounts, subscriptions,
  cloud uploads or telemetry.
* Detects the camera (Nikon, Sony, Canon, Fujifilm, …) from each file automatically. Mixed
  batches are fine.
* Never modifies your original files.

> **Status:** Milestones 1–3 implemented. A Windows installer (`BirdPhotoEditor-Setup-x.y.z.exe`) is built
> automatically on GitHub's Windows machines. See [What has and has not been verified](#what-has-and-has-not-been-verified).

---

## 1. Install

You need **Windows 10 or 11 (64-bit)** and about **600 MB** of free disk space. 8 GB of RAM works; 16 GB is
recommended for 45-megapixel cameras. No Python or other software is needed.

1. Download **`BirdPhotoEditor-Setup-x.y.z.exe`**: from the repository's **Releases** page, or from the
   latest successful **Actions → Windows installer** run (under *Artifacts*; GitHub sign-in required).
2. Double-click it. The installer is **not code-signed**, so Windows SmartScreen may say *"Windows protected
   your PC"*. Click **More info → Run anyway**.
3. Click through the installer. It installs for your user account only (**no administrator rights**). Leave
   **"Bird detection models"** ticked if you want bird-aware editing (adds about 80 MB). Optionally tick
   *Create a desktop shortcut*.

Updating: run a newer installer; your photos, edits and history are kept.
**Uninstalling**: any of these works:
* Run the installer (`BirdPhotoEditor-Setup-….exe`) again and choose **Uninstall**;
* Start menu → *Bird Photo Editor* folder → **Uninstall Bird Photo Editor**;
* Windows *Settings → Apps → Installed apps → Bird Photo Editor → Uninstall*.

You'll be asked whether to also delete your saved edits and previews. Your original photos and exported files
are never touched. Running the installer again also offers **Update / reinstall**, which keeps your edits.

## 2. Start

Open **Bird Photo Editor** from the Start menu or desktop. It opens in **its own program window**, like any
other Windows application, with its own taskbar icon and no browser. Close the window to quit. Opening it
again while it is running brings the existing window to the front.

The window uses Microsoft Edge WebView2, which is part of Windows 11 and installed on almost all Windows 10
PCs. If it is missing, the app says so and opens in your web browser instead (install the free *WebView2
Runtime* from Microsoft to get the program window).

In the program window, **dragging photos or a whole folder** onto it links the originals where they are (no
copies are made).

### Two monitors and split screen

* The window **reopens where you left it**: same monitor, size and maximized state. If that monitor is no
  longer connected, it opens on the main screen.
* Moving the window between monitors with different Windows scaling (e.g. a laptop at 150% and a monitor at
  100%) keeps the 100% view pixel-accurate.
* **Split screen / Snap**: the window can be snapped to half (or a quarter) of the screen (Win + ←/→). In
  narrow windows the toolbar labels shorten and the adjustment panel becomes a slide-out panel: click
  **Adjust ▸** to open it and **×** to close it.

<details>
<summary>Alternative: run from the source code (developers, or if you prefer not to use the installer)</summary>

Install Python 3.12 from python.org, then double-click `Setup Bird Photo Editor.bat` once and
`Start Bird Photo Editor.bat` each time. PowerShell equivalents:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Setup.ps1
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-BirdPhotoEditor.ps1
```
</details>

## 3. Using it

The steps across the top of the window show where you are: **1. Import → 2. Auto Edit → 3. Review → 4. Export**.

| Step | What to do |
|---|---|
| **Import Photos** | Click **Import Photos** to pick files with the normal Windows dialog, or drag photos or a folder onto the window. The app *links* to your originals (no copies). (Only when running in a web browser are dragged files *copied*, because a browser can't reveal where they live.) |
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
* **Copy settings / Paste settings**.
  Paste applies the look, strength and sliders to the current photo, or to every selected photo
  (Ctrl-click or Shift-click thumbnails). Camera-specific color data is never copied between photos.

### Less is more: no over-editing

The app is deliberately restrained. It aims for a photo that looks well exposed, not edited:

* **Auto Edit develops RAW files to about your camera's own look, no further.** It measures its result and
  aims for roughly the colour and contrast of the camera's standard JPEG rendering (measured on real Canon
  files), slightly below it. JPEG/TIFF files, already developed by the camera, only get a light touch-up. Bright scenes such as white birds or snow are only darkened slightly unless
  highlights are actually clipping.
* **Keep edits natural** (Advanced panel, **on by default**) caps every adjustment, manual or automatic, at a
  natural range (e.g. color intensity +35, contrast ±20, local contrast 15, strength 100%). The cap is enforced
  for exports too. Turning it off asks you to confirm first.
* **Natural texture:** noise reduction always keeps part of the fine grain, avoiding the smooth "plastic"
  look typical of over-processed or AI-generated images.
* An **edit-level badge** next to the summary says *Light*, *Moderate* or *Strong edit*. *Strong* lists what is
  pushing it there; lowering **Overall edit strength** is the simplest fix.
* The app never generates or replaces pixels (no generative fill, synthetic feathers, eyes or backgrounds).
  Bird detection only decides *how much* noise reduction and sharpening each area gets. Camera metadata is
  kept on export, and nothing is hidden or faked in the metadata.

No app can guarantee how a third-party "AI detection" or "over-editing" tool will judge a photo, and these
were not tested against any such tool. But a light, global, texture-preserving edit of a real capture is
the kind of result such tools and competition rules are designed to accept.

### Undoing edits

* **Undo / Redo** buttons (or Ctrl+Z / Ctrl+Y) step backwards and forwards.
* The **History** panel (bottom of the right-hand panel) lists every step by name, e.g. *"Auto Edit
  (Natural)"*, *"Exposure +0.30 EV"*, *"Crop 3:2"*. Click any step to return to exactly that state. Steps you
  undo stay listed (greyed out) until you make a new change, so you can jump forward again.
* Each slider has a **↺** button (or double-click the slider) that puts it back to the value Auto Edit chose.
* **Revert to original** returns to the unedited photo. It is itself a history step, so it can be undone.
* History is saved with the project and is still there after you close and reopen the app.

### Bird selection (optional)

With the bird detection models installed, the **Bird selection** panel asks once whether to turn detection on.
Nothing is uploaded; it runs on your PC. Once on, **Auto Edit** looks for birds and, when it finds a reliable
outline:

* measures **exposure on the bird** rather than the whole frame (helps dark birds against bright sky);
* applies **stronger noise reduction to the background** and gentler noise reduction and full sharpening to the bird
  (*Background noise reduction* slider);
* enables the **Soft Background** look (much stronger background noise reduction; it never blurs or replaces
  the background) and **Suggest crop** (keeps the whole bird with space around it).

Tick **Show selection** to see what was selected (red tint). To fix it, choose **+ Bird** and click parts that
were missed (or a bird that wasn't found), or **− Not bird** and click areas wrongly included. If the outline
fails the app's quality checks it is **not used automatically**; you'll see a message and can refine it or
choose **Use anyway**. If no bird is found, the photo is edited globally as before. The app never generates,
invents or repaints feathers, eyes or backgrounds. Details: [docs/BIRD_DETECTION.md](docs/BIRD_DETECTION.md).

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

### Nikon "High Efficiency" NEF files (Z8, Z9, Z6III, Zf …)

Newer Nikon cameras can record RAW with **High Efficiency** or **High Efficiency★** compression. It uses a
licensed codec (TicoRAW) that no free RAW decoder can read, including the one in this app. The app recognises
these files and tells you so. To edit them:

1. Install the free **Adobe DNG Converter** from Adobe (the app's **Get Adobe DNG Converter** button opens
   the download page).
2. Click **Try again** on the photo. From then on, Bird Photo Editor converts such files automatically in the
   background. Your NEF is not changed; the converted DNG is kept in the app's own data folder.

This has been confirmed working with a real Z6III High Efficiency★ file and Adobe's converter.

Alternatively, set the camera's *NEF (RAW) compression* to **Lossless compressed** for future photos. (Support
for lossless Z6III files has not been verified yet with a real file.)

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
* No photos, metadata or usage data are sent anywhere. The app makes no internet connections at all.
  The bird detection models are included in the installer; nothing is downloaded later.

---

## Features

**Working**

* Windows installer (per-user, no admin), desktop window, Start menu shortcut, uninstaller.
* Import (Windows dialog, drag-and-drop), content-based format detection, per-file camera identification.
* Genuine RAW decoding with LibRaw (via rawpy). The embedded camera JPEG is shown, clearly labelled, only until the RAW rendering is ready.
* Automatic, image-dependent editing (exposure with highlight protection, moderate shadow lift,
  conservative white-balance refinement, tone/contrast, vibrance-style color, measured-noise-based
  noise reduction, halo-limited sharpening). Natural, Crisp Detail and (with a bird selection) Soft Background looks.
* Optional local bird detection and segmentation with quality checks, click-to-refine, bird-metered
  exposure, background-weighted noise reduction and crop suggestions.
* Before/after slider, side-by-side, fit and real 100% view with panning.
* Sliders with per-slider reset, advanced controls, crop with aspect ratios, saved named history with
  click-to-jump, undo/redo, revert to original, copy/paste settings.
* Batch import, Auto Edit All and batch export with progress, cancellation and per-file results.
* Nondestructive recipes, project reopening, missing-original handling.
* JPEG and 16-bit TIFF export with ICC profile and metadata policy.

**Not included**

* GPU acceleration (all processing, including bird detection, runs on the CPU).
* Lens-profile, distortion, vignetting or chromatic-aberration correction; hot-pixel removal; local brushes.

**Known limitations**

* The installer is not code-signed, so SmartScreen warns on first run (signing needs a paid certificate).
* Bird detection can miss small, distant, camouflaged or partly hidden birds, and fine feather edges are
  approximate. Selections are computed at preview resolution and softened, which is fine for steering
  noise reduction but is not a precise cut-out. The direction the bird faces is not detected, so crop
  suggestions centre the bird with even margins.
* Without a bird selection, exposure metering is centre-weighted (a heuristic).
* Noise reduction smooths noise; it cannot restore detail that was never recorded. Clipped highlights and
  missed focus cannot be recovered.
* Fit-view previews approximate noise reduction and sharpening; the **100% view and exports are exact** and use
  capture sharpening (Richardson-Lucy deconvolution), which restores some lens/sensor softness but cannot fix
  missed focus or motion blur.
* Measured on the 4-core Linux test machine (your speed will differ): fit-view updates 0.3–1 s; a 12 MP RAW
  export about 17 s (24 MP Canon CR3, including capture sharpening); bird detection 0.5–2.6 s per photo; a selection refinement click about 0.15 s.

## What has and has not been verified

| Item | Status |
|---|---|
| Automated tests (76 tests) | Pass on Linux. The GitHub Actions workflow also runs them on Windows; see the latest *Windows installer* run for its result. |
| **Windows installer** | Built by GitHub Actions on `windows-latest`. That run installs it silently (into a folder with spaces and Unicode), starts the installed app, imports a test photo, auto-edits it with bird detection on, exports JPEG and 16-bit TIFF, checks the files, then uninstalls. The interactive parts (SmartScreen prompt, clicking through the wizard, the desktop window, native file dialogs) have not been tried by a person on Windows. |
| Real **Nikon** RAW | Verified end-to-end with one public NEF (Nikon D3S, ISO 3200, NASA image). **Nikon Z6III High Efficiency★ NEF verified by the user on Windows with version 0.6.2 and the real Adobe DNG Converter**: camera, lens and exposure data identified, file converted automatically, decoded and auto-edited (original unchanged). |
| Real **Sony** RAW | **Sony a7 V (ILCE-7M5) ARW verified by the user on Windows with version 0.6.5**: the built-in decoder (LibRaw 0.22.2) has no profile for this new model and produced a black band and greenish colour; through the real Adobe DNG Converter the file opens at the camera's official 7008 x 4672 px with Adobe's colour profile. |
| Real **Canon** RAW | **Canon EOS R6 Mark II CR3** (two real files from the user): camera, RF200-800mm lens, ISO, shutter, aperture, focal length and date read from the file; decoded directly (no conversion needed) at Canon's official 6000 x 4000, matching the camera's own JPEG framing; bird detected and auto-edited (Light). Checked here, not yet in the installed app. |
| Bird detection | Verified on **one** real bird photo (an eagle, from the darknet project's sample images): detected, outline passed the quality checks, click refinement worked. Correctly found no bird in two non-bird photos. Composite test images (two birds; one small bird) behaved as expected: both birds selected; the small one was found but its outline was rejected as uncertain. Your own bird photos are still needed for a real assessment. |
| Bird-photo editing quality | **Not verified** on the cases you listed (dark bird on bright sky, white bird, high ISO, small bird, multiple birds, no bird) with real files. |

## Troubleshooting

* **"Port … is already used by another program"**: another program is using ports 8765–8784. Close it, or run
  `.\scripts\Start-BirdPhotoEditor.ps1 --port 9000`.
* **Setup says no Python found**: install Python 3.12 (64-bit) from python.org and run Setup again.
* **The Windows file picker doesn't appear**: drag photos onto the browser window instead.

* **Logs:** `%LOCALAPPDATA%\BirdPhotoEditor\logs\bird-photo-editor.log`.
* **"Windows protected your PC"**: the installer isn't code-signed. Click *More info → Run anyway*.
* **Bird detection says "not installed"**: re-run the installer and tick *Bird detection models*.

---

## For developers

Ordinary users only need the installer. Developers need Python 3.12 and **Node.js 18+** (the built web
files are committed in `backend/birdedit/web/`). The installer is built by
`.github/workflows/windows-build.yml` (PyInstaller spec and Inno Setup script in `packaging/`); run it manually
from the Actions tab with *Publish the installer as a GitHub Release* ticked to create a Release.

```powershell
# backend tests
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q

# optional: real-camera end-to-end tests (skipped, and reported as unverified, without samples)
$env:BIRDEDIT_SAMPLES = "D:\raw-samples"         # real NEF/ARW files
$env:BIRDEDIT_BIRD_SAMPLES = "D:\bird-jpegs"     # real bird photos for the detection test
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
