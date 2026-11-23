"""Adobe DNG Converter fallback (for RAW variants LibRaw cannot read, notably
Nikon High Efficiency NEF). Adobe's tool is replaced by a stand-in that writes
a synthetic DNG; the real converter is not available in the test environment."""

import os
import sys
from pathlib import Path

import pytest

from birdedit import converter

from conftest import make_synthetic_dng, wait_jobs

# A fake Nikon HE NEF: TIFF header + TicoRAW/JPEG XS marker, not decodable.
FAKE_HE = (b"II*\x00\x08\x00\x00\x00" + b"\x00" * 4096 + b"\xff\x10\xff\x50\x00\x22CONTACT_INTOPIX" + b"\x00" * 200000)


def fake_converter(tmp_path: Path) -> Path:
    script = tmp_path / "fake_dng_converter.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(Path(__file__).parent)!r})\n"
        "from pathlib import Path\n"
        "from conftest import make_synthetic_dng\n"
        "a = sys.argv[1:]\n"
        "out = Path(a[a.index('-d') + 1]) / a[a.index('-o') + 1]\n"
        "assert Path(a[-1]).is_file()\n"
        "make_synthetic_dng(out)\n", encoding="utf-8")
    if sys.platform == "win32":
        exe = tmp_path / "fake_converter.cmd"
        exe.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        exe = tmp_path / "fake_converter"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        exe.chmod(0o755)
    return exe


def test_high_efficiency_detection():
    assert converter.is_nikon_high_efficiency(FAKE_HE)
    assert not converter.is_nikon_high_efficiency(b"II*\x00" + b"\x00" * 1000)
    assert not converter.is_nikon_high_efficiency(b"CONTACT_INTOPIX without codestream start")


def test_he_nef_without_converter_gets_clear_guidance(client, tmp_path, monkeypatch):
    monkeypatch.setenv("BIRDEDIT_DNG_CONVERTER", str(tmp_path / "not-installed.exe"))
    nef = tmp_path / "Z63_0001.NEF"
    nef.write_bytes(FAKE_HE)
    client.post("/api/import/upload", files=[("files", (nef.name, nef.read_bytes(), "application/octet-stream"))])
    wait_jobs(client)
    p = client.get("/api/photos").json()[0]
    assert p["decode_status"] == "needs_converter" and p["high_efficiency"] is True
    assert "High Efficiency" in p["decode_error"] and "Adobe DNG Converter" in p["decode_error"]


def test_unreadable_raw_is_converted_and_edited(client, tmp_path, monkeypatch):
    monkeypatch.setenv("BIRDEDIT_DNG_CONVERTER", str(fake_converter(tmp_path)))
    src = tmp_path / "Z63_0002.NEF"
    src.write_bytes(FAKE_HE)
    before = src.read_bytes()
    store = client.app.state.store
    rec = store.create(src, "linked", src.name)
    client.post(f"/api/photos/{rec['id']}/reprocess")
    wait_jobs(client)
    p = client.get(f"/api/photos/{rec['id']}").json()
    assert p["decode_status"] == "supported", p["decode_error"]
    assert p["converted_dng"] is True and p["full_size"] == [600, 400]
    auto = client.post(f"/api/photos/{rec['id']}/auto", json={"look": "natural"}).json()
    out = tmp_path / "out"
    out.mkdir()
    client.post("/api/export", json={"photo_ids": [rec["id"]], "folder": str(out)})
    jobs = wait_jobs(client)
    assert jobs[-1]["results"][0]["ok"], jobs[-1]["results"]
    assert (out / "Z63_0002_edited.jpg").is_file()
    assert src.read_bytes() == before                       # original untouched
    assert auto["summary"]


def test_converter_failure_is_reported(client, tmp_path, monkeypatch):
    bad = tmp_path / ("bad.cmd" if sys.platform == "win32" else "bad")
    bad.write_text("@exit /b 3\r\n" if sys.platform == "win32" else "#!/bin/sh\nexit 3\n")
    if sys.platform != "win32":
        bad.chmod(0o755)
    monkeypatch.setenv("BIRDEDIT_DNG_CONVERTER", str(bad))
    nef = tmp_path / "x.NEF"
    nef.write_bytes(FAKE_HE)
    client.post("/api/import/upload", files=[("files", (nef.name, nef.read_bytes(), "application/octet-stream"))])
    wait_jobs(client)
    p = client.get("/api/photos").json()[0]
    assert p["decode_status"] == "failed" and "could not convert" in p["decode_error"]


def test_help_link_is_fixed(client, monkeypatch):
    import webbrowser
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda u: opened.append(u))
    assert client.post("/api/open-help", json={"topic": "dng_converter"}).json()["url"].startswith("https://helpx.adobe.com/")
    assert client.post("/api/open-help", json={"topic": "https://evil.example"}).status_code == 404
    assert opened == [converter.DOWNLOAD_PAGE]
