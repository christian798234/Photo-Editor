"""Shared fixtures. All synthetic data is generated here; nothing in the
unit tests claims real-camera compatibility (see test_raw_samples.py)."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import numpy as np
import piexif
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def make_jpeg(path: Path, rgb: np.ndarray, make: str | None = None, model: str | None = None,
              gps: bool = False, iso: int | None = None, quality: int = 95) -> Path:
    zeroth, exif, gps_ifd = {}, {}, {}
    if make is not None:
        zeroth[piexif.ImageIFD.Make] = make.encode()
    if model is not None:
        zeroth[piexif.ImageIFD.Model] = model.encode()
    if iso:
        exif[piexif.ExifIFD.ISOSpeedRatings] = iso
    exif[piexif.ExifIFD.ExposureTime] = (1, 2000)
    exif[piexif.ExifIFD.FNumber] = (63, 10)
    if gps:
        gps_ifd = {piexif.GPSIFD.GPSLatitudeRef: b"N", piexif.GPSIFD.GPSLatitude: [(47, 1), (36, 1), (2280, 100)],
                   piexif.GPSIFD.GPSLongitudeRef: b"W", piexif.GPSIFD.GPSLongitude: [(122, 1), (19, 1), (5040, 100)]}
    exif_bytes = piexif.dump({"0th": zeroth, "Exif": exif, "GPS": gps_ifd, "1st": {}, "thumbnail": None})
    Image.fromarray(rgb).save(path, "JPEG", quality=quality, exif=exif_bytes)
    return path


def make_tiff_raw_stub(path: Path, make: str, model: str, size=(64, 48)) -> Path:
    """A TIFF-structured file carrying camera Make/Model, saved under a RAW
    extension. It is NOT real RAW data: LibRaw must refuse it, which is how we
    test 'camera identified but RAW not decodable'."""
    import tifffile
    data = np.zeros((size[1], size[0]), np.uint16)
    tifffile.imwrite(path, data, extratags=[(271, "s", 0, make, True), (272, "s", 0, model, True)],
                     metadata=None)
    return path


def gradient_image(h=240, w=360, tint=(1.0, 1.0, 1.0), seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = np.linspace(0.05, 0.95, w)[None, :, None]
    y = np.linspace(0.2, 1.0, h)[:, None, None]
    img = x * y * np.array(tint)[None, None, :]
    img = img + rng.normal(0, 0.01, img.shape)
    return (np.clip(img, 0, 1) * 255).astype(np.uint8)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "app data"
    monkeypatch.setenv("BIRDEDIT_DATA_DIR", str(d))
    return d


@pytest.fixture
def client(data_dir):
    from fastapi.testclient import TestClient

    from birdedit.server import create_app
    app = create_app(token="test-token", port=8765, data_dir=data_dir)
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    c.headers.update({"X-BirdEdit-Token": "test-token"})
    yield c
    app.state.jobs.shutdown()


def wait_jobs(client, timeout=60):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        jobs = client.get("/api/jobs").json()
        if all(j["status"] in ("done", "cancelled", "failed") for j in jobs):
            return jobs
        time.sleep(0.1)
    raise TimeoutError("jobs did not finish")
