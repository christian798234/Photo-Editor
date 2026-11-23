# Bird detection and bird-aware editing

Optional. Everything runs locally with ONNX Runtime on the CPU; photos are never uploaded.

## Models (installed by the "Bird detection models" installer component)

| Role | Model | Licence | Size | Origin |
|---|---|---|---|---|
| Find birds (boxes) | YOLOX-S, COCO class "bird" | Apache-2.0 | 36 MB | Official ONNX file, YOLOX release 0.1.1rc0 |
| Outline birds (masks) | MobileSAM encoder + decoder | Apache-2.0 | 28 + 16 MB | Converted to ONNX from the official `mobile_sam.pt` with `scripts/export_mobilesam_onnx.py` |

SHA-256 checksums are pinned in `backend/birdedit/masks.py` and verified before use
(`backend/models/README.md`). Ultralytics YOLO models were not used because of their AGPL-3.0 licence.

## How it works

1. **Consent.** Detection stays off until you click *Turn on bird detection* in the app (and the models are
   only present if you kept the installer component).
2. **Detection.** The preview is brightened for analysis and YOLOX looks for birds (score ≥ 0.30). If none is
   found, a second pass checks four overlapping tiles at higher magnification for small, distant birds.
3. **Segmentation.** Each box prompts MobileSAM. Your clicks (*+ Bird* / *− Not bird*) are added as point
   prompts; a *+ Bird* click away from any box outlines a bird the detector missed. The image embedding is
   cached, so a click takes about 0.15 s.
4. **Quality checks.** A detector score is not taken as proof of a good outline. Each mask must also pass:
   predicted quality ≥ 0.75, stability (outline barely changes with the threshold), mostly one connected piece,
   outline following real image edges, size consistent with the detected box, and nothing spilling far outside
   it. A failing mask is marked *uncertain* and is not used unless you click *Use anyway*.
5. **Conservative edges.** The selected area is grown slightly and softened, so feather edges, thin legs and
   wing tips get the gentle "bird" treatment rather than background smoothing. Multiple birds are combined.
6. **Use in editing** (only when the recipe's *Bird-aware processing* is on):
   * exposure is metered mostly on the bird;
   * noise reduction on the bird is 0.8× the global amount; outside it, global + extra background amount;
   * sharpening and local contrast are full on the bird and 35% on the background;
   * *Soft Background* raises background noise reduction strongly. It never blurs or replaces anything;
   * *Suggest crop* keeps the union of all birds inside with margins (bird ≈ 55–60% of the crop), never cuts
     the bird, clamps to the frame, and declines when the bird already fills the frame.
7. The mask is stored with the project (`photos/<id>/mask.png`, `mask.json` with boxes, scores, quality
   figures, clicks and timing) and is applied identically to previews, 100% view and full-resolution export.

## What it does not do

No generative fill, no invented feather or eye detail, no catchlights, no background replacement, no change to
the bird's shape. It does not detect eyes or judge focus, and it does not estimate which way the bird faces.

## Known limitations

* Small, distant, camouflaged or partly hidden birds may be missed; bird-like shapes can occasionally be
  detected (the quality checks and your review guard against using bad outlines).
* Masks are computed at preview resolution (≤ 2048 px) and softened: right for steering noise reduction, not
  a precise cut-out.
* Verified so far on one real bird photo plus synthetic composites; your own photos are needed.
