# Milestone 3 proposal: optional bird-aware masks

**Status: not implemented. Nothing has been downloaded.** This document is for you to decide
whether to proceed. Model weights would be downloaded only after you explicitly agree in the app.
Downloading a model never uploads your photos.

## What it would add

1. Detect birds (bounding boxes) → 2. segment each bird (pixel mask) → 3. use the mask to:
   * apply stronger noise reduction to the background and gentler, detail-preserving processing to the bird;
   * enable the **Soft Background** look (stronger background noise reduction, never blur replacement);
   * offer optional crop suggestions that keep wings, tail, feet and beak inside the frame, with room
     in the direction the bird faces when that can be estimated.

The mask is feathered conservatively at edges, multiple birds are unioned, and you could click the
bird to choose or refine the selection. If detection fails or the mask fails quality checks, the
app falls back to the current global processing and tells you. A detector's confidence score is not
treated as proof that a mask is good: masks would also be checked for plausible size, compactness
and edge agreement. No generative fill, no invented feathers or eyes, no background replacement.

## Candidate components (to be re-verified before integration)

| Role | Candidate | Licence | Approx. download | Notes |
|---|---|---|---|---|
| Runtime | ONNX Runtime (`onnxruntime`, CPU) | MIT | ~15 MB wheel | Prebuilt Windows wheels. Optional `onnxruntime-directml` for DirectX 12 GPUs (NVIDIA, AMD or Intel), so an NVIDIA GPU is not assumed. |
| Bird detection | YOLOX-S / YOLOX-Tiny (COCO "bird" class) | Apache-2.0 | ~35 MB / ~20 MB | Official ONNX exports exist. Ultralytics YOLO models were rejected because of their AGPL-3.0 licence. |
| Segmentation | MobileSAM (box-prompted) | Apache-2.0 | ~40 MB | Small, CPU-friendly variant of Segment Anything. Fallback/alternative: SAM ViT-B (Apache-2.0, ~375 MB, slower). |

Expected hardware: runs on CPU; on a typical 4–8 core laptop, roughly a few seconds per photo
(**to be measured**; not a promise). About 300–600 MB of extra RAM while running. Sizes, licences
and checksums would be confirmed and pinned (SHA-256) before download.

## Known limitations to expect

* COCO-trained detectors can miss small, distant, camouflaged or partially hidden birds, and may
  confuse birds with similarly shaped objects.
* Fine feather edges, thin legs and translucent wing tips are hard to segment, which is why edges
  would be processed conservatively.
* Detection says nothing about the eye or focus point; the app would not claim eye detection.

## Needed from you

* Agreement to proceed (and whether the ~60–75 MB CPU download is acceptable).
* Real bird photos for testing: a dark bird on a bright sky, a white bird, a high-ISO frame, a small
  bird in a large frame, several birds, and a frame with no bird.
