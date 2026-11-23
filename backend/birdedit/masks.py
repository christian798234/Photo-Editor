"""Optional bird-aware subject masks (Milestone 3).

Pipeline (all local, CPU via ONNX Runtime):

1. Detection: YOLOX-S (Apache-2.0, official ONNX release) finds COCO class
   "bird" boxes. If nothing is found on the whole frame, a second pass looks
   at overlapping tiles so small, distant birds have a better chance.
2. Segmentation: MobileSAM (Apache-2.0; ONNX converted from the official
   weights, see models/README.md), prompted with each box and optional
   user clicks.
3. Quality checks: a detector score or SAM's predicted IoU is never taken as
   proof of a good mask. Each mask must also pass stability, box-agreement,
   compactness and edge-agreement checks. Masks that fail are reported as
   "uncertain" and are not used automatically.
4. Conservative feathering: the bird mask is slightly grown and softened so
   feather edges always receive the gentler "bird" processing.

Nothing here generates or alters image content; masks only steer how much
noise reduction / sharpening is applied where.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import color

log = logging.getLogger(__name__)

COCO_BIRD = 14
DET_SIZE = 640
SAM_SIZE = 1024
SAM_MEAN = np.array([123.675, 116.28, 103.53], np.float32)
SAM_STD = np.array([58.395, 57.12, 57.375], np.float32)

MODELS = {
    "detector": {
        "file": "yolox_s.onnx",
        "sha256": "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063",
        "name": "YOLOX-S (COCO)", "license": "Apache-2.0",
        "source": "https://github.com/Megvii-BaseDetection/YOLOX/releases/tag/0.1.1rc0",
    },
    "sam_encoder": {
        "file": "mobile_sam_encoder.onnx",
        "sha256": "2c8c3bc527b63f798e52b921980259f9ffffe3fe78cba97967b019628a5ca3c7",
        "name": "MobileSAM image encoder", "license": "Apache-2.0",
        "source": "https://github.com/ChaoningZhang/MobileSAM (weights/mobile_sam.pt, converted)",
    },
    "sam_decoder": {
        "file": "mobile_sam_decoder.onnx",
        "sha256": "8f72ca4fb1b501bd030c19090f39d547987b609f79c1e9fc66f13b06a71d431f",
        "name": "MobileSAM mask decoder", "license": "Apache-2.0",
        "source": "https://github.com/ChaoningZhang/MobileSAM (weights/mobile_sam.pt, converted)",
    },
}
MASK_VERSION = "1"


def models_dir() -> Path:
    override = os.environ.get("BIRDEDIT_MODELS_DIR")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):                       # PyInstaller bundle
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "models"
    return Path(__file__).resolve().parent.parent / "models"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_verified: dict[str, bool] = {}


def status() -> dict:
    """Which models are present and intact (checksums verified once)."""
    d = models_dir()
    try:
        import onnxruntime as ort
        runtime = f"ONNX Runtime {ort.__version__} ({', '.join(ort.get_available_providers())})"
        rt_ok = True
    except Exception as e:  # not installed in this build
        runtime, rt_ok = f"ONNX Runtime not available ({e.__class__.__name__})", False
    items = []
    ok = rt_ok
    for key, m in MODELS.items():
        p = d / m["file"]
        present = p.is_file()
        if present and key not in _verified:
            _verified[key] = _sha256(p) == m["sha256"]
        intact = present and _verified.get(key, False)
        ok = ok and intact
        items.append({"key": key, "name": m["name"], "license": m["license"], "source": m["source"],
                      "present": present, "intact": intact,
                      "size_mb": round(p.stat().st_size / 1e6, 1) if present else None})
    return {"installed": ok, "runtime": runtime, "models": items, "models_dir": str(d)}


class _Sessions:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._s: dict = {}

    def get(self, key: str):
        with self._lock:
            if key not in self._s:
                import onnxruntime as ort
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = max(1, (os.cpu_count() or 2) - 1)
                self._s[key] = ort.InferenceSession(str(models_dir() / MODELS[key]["file"]), opts,
                                                    providers=["CPUExecutionProvider"])
            return self._s[key]


SESSIONS = _Sessions()
_RUN_LOCK = threading.Lock()


# ---------------------------------------------------------------- helpers

def display_image(lin_preview: np.ndarray) -> np.ndarray:
    """Linear ProPhoto preview -> normalised 8-bit sRGB for the models
    (dark RAWs are brightened so detection sees the scene)."""
    srgb = color.gamut_map_to_srgb(lin_preview)
    y = color.luminance(srgb, color.SRGB_LUMA)
    p = float(np.percentile(y, 99.0))
    gain = np.clip(0.85 / max(p, 1e-4), 0.5, 16.0)
    enc = color.srgb_encode(np.clip(srgb * gain, 0, 1))
    return np.round(enc * 255).astype(np.uint8)


@dataclass
class Bird:
    box: list[float]           # x0, y0, x1, y1 in mask/display pixels
    score: float


def _nms(boxes: np.ndarray, scores: np.ndarray, thr: float = 0.45) -> list[int]:
    if len(boxes) == 0:
        return []
    rects = [[float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])] for b in boxes]
    idx = cv2.dnn.NMSBoxes(rects, scores.astype(float).tolist(), 0.0, thr)
    return [int(i) for i in np.array(idx).reshape(-1)]


def _detect_once(rgb: np.ndarray, min_score: float) -> tuple[np.ndarray, np.ndarray]:
    h, w = rgb.shape[:2]
    r = min(DET_SIZE / h, DET_SIZE / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    canvas = np.full((DET_SIZE, DET_SIZE, 3), 114, np.uint8)
    canvas[:nh, :nw] = cv2.resize(rgb[..., ::-1], (nw, nh), interpolation=cv2.INTER_AREA)  # BGR
    x = canvas.transpose(2, 0, 1)[None].astype(np.float32)
    out = SESSIONS.get("detector").run(None, {"images": x})[0][0]
    grids, strides = [], []
    for s in (8, 16, 32):
        g = DET_SIZE // s
        yv, xv = np.meshgrid(np.arange(g), np.arange(g), indexing="ij")
        grids.append(np.stack([xv, yv], -1).reshape(-1, 2))
        strides.append(np.full((g * g, 1), s))
    grid = np.concatenate(grids).astype(np.float32)
    stride = np.concatenate(strides).astype(np.float32)
    xy = (out[:, :2] + grid) * stride
    wh = np.exp(np.clip(out[:, 2:4], -10, 10)) * stride
    score = out[:, 4] * out[:, 5 + COCO_BIRD]
    keep = score >= min_score
    xy, wh, score = xy[keep], wh[keep], score[keep]
    boxes = np.concatenate([xy - wh / 2, xy + wh / 2], 1) / r
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h)
    return boxes, score


def detect_birds(rgb: np.ndarray, min_score: float = 0.30) -> tuple[list[Bird], str]:
    boxes, scores = _detect_once(rgb, min_score)
    how = "whole frame"
    if len(boxes) == 0:
        # Small-bird pass: 2x2 overlapping tiles at higher effective resolution.
        h, w = rgb.shape[:2]
        th, tw = int(h * 0.6), int(w * 0.6)
        all_b, all_s = [], []
        for y0 in (0, h - th):
            for x0 in (0, w - tw):
                b, s = _detect_once(rgb[y0:y0 + th, x0:x0 + tw], min_score)
                if len(b):
                    b = b + np.array([x0, y0, x0, y0], np.float32)
                    all_b.append(b)
                    all_s.append(s)
        if all_b:
            boxes, scores = np.concatenate(all_b), np.concatenate(all_s)
            how = "tiles (small-bird pass)"
    keep = _nms(boxes, scores)
    birds = [Bird([round(float(v), 1) for v in boxes[i]], round(float(scores[i]), 3)) for i in keep]
    birds.sort(key=lambda b: -b.score)
    return birds[:8], how


# ----------------------------------------------------------- segmentation

class Embedding:
    def __init__(self, rgb: np.ndarray):
        h, w = rgb.shape[:2]
        self.scale = SAM_SIZE / max(h, w)
        nh, nw = int(round(h * self.scale)), int(round(w * self.scale))
        x = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA).astype(np.float32)
        x = (x - SAM_MEAN) / SAM_STD
        pad = np.zeros((SAM_SIZE, SAM_SIZE, 3), np.float32)
        pad[:nh, :nw] = x
        self.shape = (h, w)
        self.emb = SESSIONS.get("sam_encoder").run(None, {"image": pad.transpose(2, 0, 1)[None]})[0]


def segment(emb: Embedding, box: list[float] | None, points: list[tuple[float, float, int]]
            ) -> tuple[np.ndarray, float]:
    """Return (logits HxW, predicted IoU). points: (x, y, label 1=bird 0=not)."""
    coords, labels = [], []
    for x, y, lab in points:
        coords.append([x, y])
        labels.append(lab)
    if box is not None:
        coords += [[box[0], box[1]], [box[2], box[3]]]
        labels += [2, 3]
    else:
        coords.append([0.0, 0.0])
        labels.append(-1)
    c = np.array(coords, np.float32)[None] * emb.scale
    lab = np.array(labels, np.float32)[None]
    h, w = emb.shape
    masks, iou, _ = SESSIONS.get("sam_decoder").run(None, {
        "image_embeddings": emb.emb, "point_coords": c, "point_labels": lab,
        "mask_input": np.zeros((1, 1, 256, 256), np.float32),
        "has_mask_input": np.zeros(1, np.float32), "orig_im_size": np.array([h, w], np.float32)})
    iou = iou[0]
    # Box prompts: the single-mask output (index 0) is recommended; clicks:
    # pick the best of the multi-mask outputs.
    k = 0 if box is not None and not points else int(np.argmax(iou[1:]) + 1)
    return masks[0, k], float(iou[k])


def quality(logits: np.ndarray, box: list[float] | None, rgb: np.ndarray, pred_iou: float) -> dict:
    m = logits > 0
    area = int(m.sum())
    q: dict = {"predicted_iou": round(pred_iou, 3), "area_px": area}
    if area < 50:
        q.update(ok=False, reason="mask is empty or tiny")
        return q
    hi, lo = logits > 1.0, logits > -1.0
    stability = float(hi.sum() / max(lo.sum(), 1))
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
    largest = float(stats[1:, cv2.CC_STAT_AREA].max() / area) if n > 1 else 1.0
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    grad = cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
    edge = m & ~cv2.erode(m.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    edge_ratio = float(grad[edge].mean() / max(grad.mean(), 1e-3))
    q.update(stability=round(stability, 3), largest_component=round(largest, 3),
             edge_agreement=round(edge_ratio, 2))
    reasons = []
    if pred_iou < 0.75:
        reasons.append("low predicted quality")
    if stability < 0.80:
        reasons.append("unstable outline")
    if largest < 0.80:
        reasons.append("fragmented")
    if edge_ratio < 1.0:
        reasons.append("outline does not follow image edges")
    if box is not None:
        x0, y0, x1, y1 = box
        bw, bh = x1 - x0, y1 - y0
        fill = area / max(bw * bh, 1)
        ys, xs = np.nonzero(m)
        mx0, my0 = x0 - 0.1 * bw, y0 - 0.1 * bh
        inside = float(((xs >= mx0) & (xs <= x1 + 0.1 * bw) & (ys >= my0) & (ys <= y1 + 0.1 * bh)).mean())
        q.update(box_fill=round(fill, 3), inside_box=round(inside, 3))
        if not 0.12 <= fill <= 0.97:
            reasons.append("mask does not match the detected bird's size")
        if inside < 0.9:
            reasons.append("mask spills outside the bird")
    q["ok"] = not reasons
    q["reason"] = "; ".join(reasons)
    return q


def feather(binary: np.ndarray) -> np.ndarray:
    """Grow slightly and soften so feather edges count as 'bird'."""
    m = binary.astype(np.uint8)
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return np.zeros(binary.shape, np.uint8)
    size = max(xs.max() - xs.min(), ys.max() - ys.min())
    grow = max(2, int(round(size * 0.012)))
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
    soft = cv2.GaussianBlur(m.astype(np.float32), (0, 0), max(1.5, size * 0.008))
    return np.round(np.clip(soft, 0, 1) * 255).astype(np.uint8)


# ------------------------------------------------------------- top level

@dataclass
class MaskResult:
    status: str                         # good | uncertain | none
    message: str
    birds: list[dict] = field(default_factory=list)
    detection: str = ""
    points: list[list[float]] = field(default_factory=list)
    source: str = "auto"                # auto | refined
    seconds: float = 0.0
    shape: list[int] = field(default_factory=list)
    version: str = MASK_VERSION

    def to_dict(self) -> dict:
        return asdict(self)


def compute(lin_preview: np.ndarray, points: list[tuple[float, float, int]] | None = None,
            birds_hint: list[dict] | None = None, emb_cache: dict | None = None
            ) -> tuple[MaskResult, np.ndarray | None]:
    """Detect and segment birds. ``points`` are user clicks in mask pixels."""
    t0 = time.time()
    with _RUN_LOCK:
        rgb = display_image(lin_preview)
        h, w = rgb.shape[:2]
        if birds_hint is not None:
            birds = [Bird(b["box"], b["score"]) for b in birds_hint]
            how = "previous detection"
        else:
            birds, how = detect_birds(rgb)
        points = points or []
        if not birds and not any(p[2] == 1 for p in points):
            return MaskResult("none", "No bird was detected. Global editing is used. "
                              "You can click on the bird to select it.", detection=how,
                              seconds=round(time.time() - t0, 2), shape=[h, w]), None
        emb = emb_cache.get("emb") if emb_cache else None
        if emb is None or emb.shape != (h, w):
            emb = Embedding(rgb)
            if emb_cache is not None:
                emb_cache["emb"] = emb
        good_union = np.zeros((h, w), bool)     # masks that passed (or were clicked)
        all_union = np.zeros((h, w), bool)      # every outline, for "Use anyway"
        reports = []

        def add(logits, box, pts, score, click=None):
            q = quality(logits, box, rgb, segment_iou[0])
            rep = {"box": box, "score": score, "quality": q}
            if click is not None:
                rep["click"] = list(click)
            reports.append(rep)
            all_union[:] |= logits > 0
            if q["ok"] or pts:
                good_union[:] |= logits > 0

        segment_iou = [0.0]
        for b in birds:
            bx = b.box
            mx, my = 0.2 * (bx[2] - bx[0]), 0.2 * (bx[3] - bx[1])
            near = [p for p in points if bx[0] - mx <= p[0] <= bx[2] + mx and bx[1] - my <= p[1] <= bx[3] + my]
            logits, segment_iou[0] = segment(emb, bx, near)
            add(logits, bx, near, b.score)
        negatives = [p for p in points if p[2] == 0]
        for p in points:                                   # birds the detector missed
            if p[2] != 1 or any(r["box"] and r["box"][0] <= p[0] <= r["box"][2]
                                and r["box"][1] <= p[1] <= r["box"][3] for r in reports):
                continue
            logits, segment_iou[0] = segment(emb, None, [p] + negatives)
            add(logits, None, [p], None, click=p)
        refined = bool(points)
        good = good_union.any()
        secs = round(time.time() - t0, 2)
        if not all_union.any():
            return MaskResult("uncertain", "A bird was detected, but no outline could be made. "
                              "Global editing is used. Click on the bird to help.",
                              birds=reports, detection=how, points=[list(p) for p in points],
                              seconds=secs, shape=[h, w]), None
        union = good_union if good else all_union
        status = "good" if good else "uncertain"
        n = max(1, sum(1 for r in reports if r["quality"]["ok"] or r.get("click")))
        msg = (f"Selected {n} bird{'s' if n != 1 else ''}." if status == "good" else
               "The bird outline may be inaccurate, so it is not used automatically. "
               "Check the overlay, click to refine, or choose 'Use anyway'.")
        return MaskResult(status, msg, birds=reports, detection=how, points=[list(p) for p in points],
                          source="refined" if refined else "auto", seconds=secs, shape=[h, w]), feather(union)


# ------------------------------------------------------------ crop advice

def suggest_crop(mask: np.ndarray, ratio: float | None, full_size: tuple[int, int]) -> dict | None:
    """Crop (normalised) that keeps every masked bird fully inside, with
    margins. Never cuts the bird; returns None if no useful crop exists.
    The bird's facing direction is not estimated."""
    h, w = mask.shape
    ys, xs = np.nonzero(mask > 128)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = xs.min() / w, (xs.max() + 1) / w, ys.min() / h, (ys.max() + 1) / h
    bw, bh = x1 - x0, y1 - y0
    fw, fh = full_size
    # Margins and target size: bird about 45-60% of the crop's width/height.
    cw, ch = max(bw / 0.55, bw + 0.3 * bw), max(bh / 0.6, bh + 0.3 * bh)
    if ratio is not None:
        # Convert to pixel aspect, grow the smaller side to match.
        if (cw * fw) / (ch * fh) < ratio:
            cw = ch * fh * ratio / fw
        else:
            ch = cw * fw / ratio / fh
    if cw > 1 or ch > 1:
        s = max(cw, ch)
        cw, ch = cw / s, ch / s
        if cw < bw or ch < bh:
            return None                                  # cannot keep the bird with this aspect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    left = min(max(0.0, cx - cw / 2), 1 - cw)
    top = min(max(0.0, cy - ch / 2), 1 - ch)
    # Keep the bird inside after clamping.
    left = min(left, x0)
    top = min(top, y0)
    left = max(left, x1 - cw)
    top = max(top, y1 - ch)
    if cw * ch > 0.92:
        return None
    return {"x": round(left, 5), "y": round(top, 5), "w": round(cw, 5), "h": round(ch, 5),
            "pixels": [int(round(cw * fw)), int(round(ch * fh))]}


def save_mask_files(folder: Path, result: MaskResult, mask: np.ndarray | None) -> None:
    from .store import atomic_write_text
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "mask.png"
    if mask is not None:
        ok, buf = cv2.imencode(".png", mask)
        tmp = folder / ".mask.tmp.png"
        tmp.write_bytes(buf.tobytes())
        os.replace(tmp, p)
    elif p.exists():
        p.unlink()
    atomic_write_text(folder / "mask.json", json.dumps(result.to_dict(), indent=1))


def load_mask(folder: Path) -> tuple[dict | None, np.ndarray | None]:
    try:
        info = json.loads((folder / "mask.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None, None
    p = folder / "mask.png"
    mask = None
    if p.exists():
        mask = cv2.imdecode(np.frombuffer(p.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
    return info, mask
