"""Integration tests through the HTTP API with synthetic files.

These prove the application logic (identification, separation of camera
recognition and decode support, per-photo processing, export policy). They do
NOT prove real Nikon/Sony RAW compatibility; see test_raw_samples.py.
"""

import hashlib
import io
import shutil
from pathlib import Path

import exifread
import numpy as np
import pytest
import tifffile
from PIL import Image

from conftest import gradient_image, make_jpeg, make_tiff_raw_stub, wait_jobs


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def upload(client, paths):
    files = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in paths]
    r = client.post("/api/import/upload", files=files)
    assert r.status_code == 200, r.text
    wait_jobs(client)
    return r.json()


def by_name(client):
    return {p["original_name"]: p for p in client.get("/api/photos").json()}


def test_mixed_camera_batch_is_identified_per_file(client, tmp_path):
    files = [
        make_tiff_raw_stub(tmp_path / "DSC_0001.NEF", "NIKON CORPORATION", "NIKON Z 8"),
        make_tiff_raw_stub(tmp_path / "DSC00002.ARW", "SONY", "ILCE-1"),
        make_jpeg(tmp_path / "sony.jpg", gradient_image(tint=(1.1, 1.0, 0.9)), "SONY", "ILCE-7RM5"),
        make_jpeg(tmp_path / "nikon.jpg", gradient_image(tint=(0.9, 1.0, 1.1)), "NIKON CORPORATION", "NIKON D850"),
        make_jpeg(tmp_path / "nometa.jpg", gradient_image()),
    ]
    tiff = tmp_path / "scan.tif"
    tifffile.imwrite(tiff, (gradient_image().astype(np.uint16) * 257), photometric="rgb")
    files.append(tiff)
    upload(client, files)
    ph = by_name(client)
    assert ph["DSC_0001.NEF"]["metadata"]["camera"]["display_name"] == "Nikon Z 8"
    assert ph["DSC00002.ARW"]["metadata"]["camera"]["display_name"] == "Sony ILCE-1"
    assert ph["sony.jpg"]["metadata"]["camera"]["display_name"] == "Sony ILCE-7RM5"
    assert ph["nikon.jpg"]["metadata"]["camera"]["display_name"] == "Nikon D850"
    assert ph["nometa.jpg"]["metadata"]["camera"]["display_name"] == "Unknown camera"
    # Recognised camera, but the stub is not real RAW data -> separate decode status.
    for n in ("DSC_0001.NEF", "DSC00002.ARW"):
        assert ph[n]["metadata"]["camera"]["identified"] is True
        assert ph[n]["decode_status"] in ("unsupported", "failed")
        assert ph[n]["decode_error"]
    for n in ("sony.jpg", "nikon.jpg", "nometa.jpg", "scan.tif"):
        assert ph[n]["decode_status"] == "supported", ph[n]["decode_error"]
    assert ph["scan.tif"]["full_size"] == [360, 240]

    # Auto Edit All estimates each photo independently (opposite casts).
    ids = [ph[n]["id"] for n in ("sony.jpg", "nikon.jpg")]
    client.post("/api/auto-all", json={"photo_ids": ids, "look": "natural"})
    wait_jobs(client)
    ph = by_name(client)
    w_warm = ph["sony.jpg"]["recipe"]["sliders"]["warmth"]
    w_cool = ph["nikon.jpg"]["recipe"]["sliders"]["warmth"]
    assert w_warm < 0 < w_cool
    assert ph["sony.jpg"]["summary"]


def test_corrupt_and_unsupported_files_do_not_crash(client, tmp_path):
    junk = tmp_path / "broken.NEF"
    junk.write_bytes(b"\x00" * 5000)
    trunc = tmp_path / "trunc.jpg"
    good = io.BytesIO()
    Image.fromarray(gradient_image()).save(good, "JPEG")
    trunc.write_bytes(good.getvalue()[:300])
    txt = tmp_path / "notes.txt"
    txt.write_text("hello")
    r = client.post("/api/import/upload", files=[
        ("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in (junk, trunc, txt)])
    assert "notes.txt: not a supported photo type" in r.json()["rejected"]
    wait_jobs(client)
    ph = by_name(client)
    assert ph["broken.NEF"]["decode_status"] == "unsupported"
    assert ph["broken.NEF"]["metadata"]["camera"]["display_name"] == "Unknown camera"
    assert ph["trunc.jpg"]["decode_status"] == "failed"
    # Rendering an undecodable photo is refused cleanly.
    rid = ph["broken.NEF"]["id"]
    assert client.post(f"/api/photos/{rid}/render", json={"recipe": {}}).status_code == 409


def test_edit_render_export_and_originals_unchanged(client, tmp_path):
    src_dir = tmp_path / "My Photos ü 鳥"
    src_dir.mkdir()
    src = make_jpeg(src_dir / "Grand héron (1).jpg", gradient_image(480, 720), "SONY", "ILCE-1", gps=True, iso=1600)
    before_hash = sha(src)
    # Simulate the native dialog returning the real path (linked, not copied).
    store = client.app.state.store
    rec = store.create(src, "linked", src.name)
    client.post(f"/api/photos/{rec['id']}/reprocess")
    wait_jobs(client)
    pid = rec["id"]

    auto = client.post(f"/api/photos/{pid}/auto", json={"look": "natural"}).json()
    recipe = auto["recipe"]
    assert auto["summary"].endswith(".")
    r = client.post(f"/api/photos/{pid}/render", json={"recipe": recipe, "max_edge": 400})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert max(Image.open(io.BytesIO(r.content)).size) == 400
    rb = client.post(f"/api/photos/{pid}/render", json={"recipe": recipe, "before": True, "max_edge": 400})
    assert Image.open(io.BytesIO(rb.content)).size == Image.open(io.BytesIO(r.content)).size
    reg = client.post(f"/api/photos/{pid}/render-region", json={"recipe": recipe, "x": 100, "y": 50, "w": 200, "h": 120})
    assert reg.status_code == 200 and Image.open(io.BytesIO(reg.content)).size == (200, 120)

    recipe["crop"] = {"aspect": "3:2", "portrait": False, "x": 0.1, "y": 0.1, "w": 0.6, "h": 0.6}
    assert client.put(f"/api/photos/{pid}/recipe", json=recipe).status_code == 200

    out_dir = tmp_path / "Exports with spaces ✓"
    out_dir.mkdir()
    for fmt in ("jpeg", "jpeg", "tiff16"):
        j = client.post("/api/export", json={"photo_ids": [pid], "folder": str(out_dir), "format": fmt})
        assert j.status_code == 200, j.text
        wait_jobs(client)
    names = sorted(p.name for p in out_dir.iterdir())
    assert names == ["Grand héron (1)_edited (2).jpg", "Grand héron (1)_edited.jpg", "Grand héron (1)_edited.tif"]

    jpg = out_dir / "Grand héron (1)_edited.jpg"
    im = Image.open(jpg)
    assert im.size == (432, 288)                        # crop applied at full resolution
    assert "icc_profile" in im.info
    tags = exifread.process_file(open(jpg, "rb"), details=False)
    assert str(tags["Image Make"]) == "SONY" and str(tags["Image Model"]) == "ILCE-1"
    assert str(tags["EXIF ISOSpeedRatings"]) == "1600"
    assert not any(k.startswith("GPS") for k in tags)    # GPS stripped by default
    with tifffile.TiffFile(out_dir / "Grand héron (1)_edited.tif") as tf:
        page = tf.pages[0]
        assert page.dtype == np.uint16 and page.shape == (288, 432, 3)
        assert 34675 in page.tags                        # ICC profile
        assert b"GPS" not in bytes(page.tags[700].value)

    # Opt-in GPS retention.
    gps_dir = tmp_path / "gps"
    gps_dir.mkdir()
    client.post("/api/export", json={"photo_ids": [pid], "folder": str(gps_dir), "keep_gps": True, "long_edge": 300})
    wait_jobs(client)
    out = next(gps_dir.iterdir())
    tags = exifread.process_file(open(out, "rb"), details=False)
    assert str(tags["GPS GPSLatitudeRef"]) == "N"
    assert max(Image.open(out).size) == 300

    assert sha(src) == before_hash                       # original untouched


def test_missing_original_keeps_edits_and_blocks_export(client, tmp_path):
    src = make_jpeg(tmp_path / "bird.jpg", gradient_image(), "NIKON CORPORATION", "NIKON Z 9")
    store = client.app.state.store
    rec = store.create(src, "linked", src.name)
    client.post(f"/api/photos/{rec['id']}/reprocess")
    wait_jobs(client)
    client.post(f"/api/photos/{rec['id']}/auto", json={"look": "crisp"})
    moved = tmp_path / "moved"
    moved.mkdir()
    shutil.move(src, moved / "bird.jpg")
    p = client.get(f"/api/photos/{rec['id']}").json()
    assert p["source_available"] is False and p["recipe"]["look"] == "crisp"
    # Preview still renders from the cache.
    assert client.post(f"/api/photos/{rec['id']}/render", json={"recipe": p["recipe"]}).status_code == 200
    out = tmp_path / "out"
    out.mkdir()
    client.post("/api/export", json={"photo_ids": [rec["id"]], "folder": str(out)})
    jobs = wait_jobs(client)
    assert "missing" in jobs[-1]["results"][0]["message"]
    assert not list(out.iterdir())


def test_paste_copies_user_settings_only(client, tmp_path):
    a = make_jpeg(tmp_path / "a.jpg", gradient_image(tint=(1.2, 1, 0.8)), "SONY", "ILCE-1")
    b = make_jpeg(tmp_path / "b.jpg", gradient_image(tint=(0.8, 1, 1.2)), "NIKON CORPORATION", "NIKON Z 8")
    upload(client, [a, b])
    ph = by_name(client)
    ra = client.post(f"/api/photos/{ph['a.jpg']['id']}/auto", json={"look": "natural"}).json()["recipe"]
    rb = client.post(f"/api/photos/{ph['b.jpg']['id']}/auto", json={"look": "natural"}).json()["recipe"]
    client.post("/api/paste", json={"photo_ids": [ph["b.jpg"]["id"]], "look": ra["look"],
                                    "strength": 70, "sliders": ra["sliders"]})
    nb = client.get(f"/api/photos/{ph['b.jpg']['id']}").json()["recipe"]
    assert nb["sliders"] == ra["sliders"] and nb["strength"] == 70
    assert nb["internal"] == rb["internal"]          # image-specific values not copied


def test_recipe_validation_via_api(client, tmp_path):
    upload(client, [make_jpeg(tmp_path / "a.jpg", gradient_image())])
    pid = by_name(client)["a.jpg"]["id"]
    assert client.put(f"/api/photos/{pid}/recipe", json={"sliders": {"exposure": 99}}).status_code == 422
    # No bird selection -> mask-dependent settings are refused.
    assert client.put(f"/api/photos/{pid}/recipe", json={"look": "soft_background"}).status_code == 409
    assert client.put(f"/api/photos/{pid}/recipe", json={"subject": {"use_mask": True}}).status_code == 409
    assert client.get("/api/photos/../../etc/passwd").status_code == 404


def test_export_folder_validation(client, tmp_path):
    upload(client, [make_jpeg(tmp_path / "a.jpg", gradient_image())])
    pid = by_name(client)["a.jpg"]["id"]
    for folder in ("relative/path", str(tmp_path / "does-not-exist"), ""):
        assert client.post("/api/export", json={"photo_ids": [pid], "folder": folder}).status_code == 400


def test_security_checks(data_dir):
    from fastapi.testclient import TestClient

    from birdedit.server import create_app
    app = create_app(token="secret", port=8765, data_dir=data_dir)
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/photos").status_code == 401
    assert c.get("/api/photos", headers={"X-BirdEdit-Token": "wrong"}).status_code == 401
    assert c.get("/api/photos", headers={"X-BirdEdit-Token": "secret"}).status_code == 200
    assert c.get("/api/photos?t=secret").status_code == 200
    assert c.get("/api/photos", headers={"X-BirdEdit-Token": "secret", "Origin": "https://evil.example"}).status_code == 403
    assert c.get("/api/health", headers={"Host": "evil.example:8765"}).status_code == 403
    r = c.get("/api/photos", headers={"X-BirdEdit-Token": "secret"})
    assert "access-control-allow-origin" not in r.headers
    app.state.jobs.shutdown()


def test_edit_history_persists(client, tmp_path):
    upload(client, [make_jpeg(tmp_path / "h.jpg", gradient_image())])
    pid = by_name(client)["h.jpg"]["id"]
    h = client.get(f"/api/photos/{pid}/history").json()
    assert h["index"] == 0 and h["entries"][0]["label"] == "Imported"
    r2 = dict(h["entries"][0]["recipe"])
    r2["sliders"] = {**r2["sliders"], "exposure": 0.5}
    h2 = {"entries": h["entries"] + [{"label": "Exposure +0.50 EV", "time": 1.0, "recipe": r2}], "index": 1}
    assert client.put(f"/api/photos/{pid}/history", json=h2).status_code == 200
    back = client.get(f"/api/photos/{pid}/history").json()
    assert back["index"] == 1 and back["entries"][1]["label"] == "Exposure +0.50 EV"
    assert client.put(f"/api/photos/{pid}/history", json={"entries": [], "index": 0}).status_code == 422


def test_import_paths_links_files_and_folders(client, tmp_path):
    folder = tmp_path / "Card ü 2026"
    folder.mkdir()
    make_jpeg(folder / "a.jpg", gradient_image(), "SONY", "ILCE-1")
    make_jpeg(folder / "b.JPG", gradient_image(), "NIKON CORPORATION", "NIKON Z 9")
    (folder / "notes.txt").write_text("not a photo")
    single = make_jpeg(tmp_path / "c.jpg", gradient_image())
    res = client.app.state.import_paths([str(folder), str(single), str(tmp_path / "missing.jpg")])
    assert len(res["photo_ids"]) == 3
    wait_jobs(client)
    ph = by_name(client)
    assert set(ph) == {"a.jpg", "b.JPG", "c.jpg"}
    assert all(p["source"]["kind"] == "linked" for p in ph.values())       # linked, not copied
    assert ph["a.jpg"]["source"]["path"] == str(folder / "a.jpg")


def test_show_endpoint_needs_no_token_but_checks_origin(data_dir):
    from fastapi.testclient import TestClient

    from birdedit.server import create_app
    app = create_app(token="secret", port=8765, data_dir=data_dir)
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    assert c.post("/api/show").json() == {"shell": "browser"}
    assert c.post("/api/show", headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.get("/api/system", headers={"X-BirdEdit-Token": "secret"}).json()["shell"] == "browser"
    app.state.jobs.shutdown()
