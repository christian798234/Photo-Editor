"""Smoke test of an INSTALLED Bird Photo Editor (used by the Windows CI job).

Usage: python ci_smoke.py <base_url> <token> <export_dir>
Imports a generated test photo, runs Auto Edit (with bird detection switched
on; the synthetic image contains no bird, so the global fallback is
exercised), exports a JPEG and a 16-bit TIFF and checks the files.
"""
import io
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import numpy as np
import piexif
from PIL import Image

base, token, export_dir = sys.argv[1].rstrip("/"), sys.argv[2], Path(sys.argv[3])


def call(method, path, body=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"X-BirdEdit-Token": token, **({"Content-Type": ctype} if data else {})})
    with urllib.request.urlopen(req, timeout=120) as r:
        payload = r.read()
        return json.loads(payload) if r.headers.get_content_type() == "application/json" else payload


def wait_jobs():
    for _ in range(600):
        jobs = call("GET", "/api/jobs")
        if all(j["status"] in ("done", "cancelled", "failed") for j in jobs):
            return jobs
        time.sleep(0.5)
    raise SystemExit("jobs did not finish")


system = call("GET", "/api/system")
print("system:", json.dumps(system, indent=1))
subject = call("GET", "/api/subject/status")
print("bird detection installed:", subject["installed"], subject["runtime"])
assert subject["installed"], "bird detection models missing from the installed app"

# A test photo with camera metadata and GPS, named with spaces + Unicode.
x = np.linspace(0, 1, 900)[None, :, None] * np.linspace(0.3, 1, 600)[:, None, None]
img = (np.concatenate([x * 0.9, x * 0.8, x * 0.6], axis=2) * 255).astype(np.uint8)
exif = piexif.dump({"0th": {piexif.ImageIFD.Make: b"SONY", piexif.ImageIFD.Model: b"ILCE-1"},
                    "Exif": {piexif.ExifIFD.ISOSpeedRatings: 3200},
                    "GPS": {piexif.GPSIFD.GPSLatitudeRef: b"N", piexif.GPSIFD.GPSLatitude: [(47, 1), (36, 1), (0, 1)]},
                    "1st": {}, "thumbnail": None})
buf = io.BytesIO()
Image.fromarray(img).save(buf, "JPEG", quality=95, exif=exif)
boundary = uuid.uuid4().hex
name = "Grand héron – test photo.jpg"
body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{name}\"\r\n"
        "Content-Type: image/jpeg\r\n\r\n").encode("utf-8") + buf.getvalue() + f"\r\n--{boundary}--\r\n".encode()
call("POST", "/api/import/upload", raw=body, ctype=f"multipart/form-data; boundary={boundary}")
wait_jobs()
photos = call("GET", "/api/photos")
p = photos[0]
print("imported:", p["original_name"], p["decode_status"], p["metadata"]["camera"]["display_name"])
assert p["decode_status"] == "supported" and p["metadata"]["camera"]["display_name"] == "Sony ILCE-1"

settings = call("GET", "/api/settings")
call("PUT", "/api/settings", {**settings, "subject_detection": True})
auto = call("POST", f"/api/photos/{p['id']}/auto", {"look": "natural"})
print("auto edit:", auto["summary"])
mask = call("GET", f"/api/photos/{p['id']}")["mask"]
print("bird selection:", mask)
assert mask is not None and mask["status"] == "none"          # no bird in a gradient

jpeg = call("POST", f"/api/photos/{p['id']}/render", {"recipe": auto["recipe"], "max_edge": 600})
assert jpeg[:3] == b"\xff\xd8\xff"

export_dir.mkdir(parents=True, exist_ok=True)
for fmt in ("jpeg", "tiff16"):
    call("POST", "/api/export", {"photo_ids": [p["id"]], "folder": str(export_dir), "format": fmt})
    jobs = wait_jobs()
    print("export:", jobs[-1]["results"])
    assert jobs[-1]["results"][0]["ok"]
files = sorted(f.name for f in export_dir.iterdir())
print("exported files:", files)
assert any(f.endswith(".jpg") for f in files) and any(f.endswith(".tif") for f in files)
out = Image.open(next(export_dir.glob("*.jpg")))
assert out.size == (900, 600) and "icc_profile" in out.info
assert not piexif.load(out.info["exif"]).get("GPS"), "GPS should be stripped by default"
print("SMOKE TEST PASSED")
