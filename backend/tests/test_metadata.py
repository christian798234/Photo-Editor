import struct

import numpy as np

from birdedit.formats import Container
from birdedit.metadata import format_shutter, raf_model_and_jpeg, read_metadata

from conftest import gradient_image, make_jpeg, make_tiff_raw_stub


def test_tiff_based_raw_metadata_nikon_and_sony(tmp_path):
    nef = make_tiff_raw_stub(tmp_path / "a.NEF", "NIKON CORPORATION", "NIKON Z 9")
    arw = make_tiff_raw_stub(tmp_path / "b.ARW", "SONY", "ILCE-7RM5")
    md_n = read_metadata(nef.read_bytes(), Container.TIFF)
    md_s = read_metadata(arw.read_bytes(), Container.TIFF)
    assert md_n.camera.display_name == "Nikon Z 9"
    assert md_s.camera.display_name == "Sony ILCE-7RM5"
    assert md_s.camera.make_raw == "SONY"


def test_jpeg_exif(tmp_path):
    p = make_jpeg(tmp_path / "x.jpg", gradient_image(), "SONY", "ILCE-1", gps=True, iso=800)
    md = read_metadata(p.read_bytes(), Container.JPEG)
    assert md.camera.display_name == "Sony ILCE-1"
    assert md.iso == 800 and md.exposure_time == (1, 2000) and abs(md.f_number - 6.3) < 1e-6
    assert md.has_gps and md.gps["GPSLatitudeRef"] == "N"
    assert format_shutter(md.exposure_time) == "1/2000 s"


def test_missing_metadata(tmp_path):
    from PIL import Image
    p = tmp_path / "plain.jpg"
    Image.fromarray(gradient_image()).save(p, "JPEG")
    md = read_metadata(p.read_bytes(), Container.JPEG)
    assert md.camera.display_name == "Unknown camera" and not md.has_gps


def test_malformed_metadata_does_not_crash():
    junk = b"II*\x00" + bytes(range(256)) * 10
    md = read_metadata(junk, Container.TIFF)
    assert md.camera.display_name == "Unknown camera"
    md = read_metadata(b"\xff\xd8\xff\xe1\xff\xff garbage", Container.JPEG)
    assert not md.camera.identified


def test_cr3_metadata_boxes():
    # Build a minimal ISO-BMFF with moov/uuid(Canon)/CMT1 containing a TIFF IFD.
    import io

    import tifffile
    buf = io.BytesIO()
    tifffile.imwrite(buf, np.zeros((2, 2), np.uint8),
                     extratags=[(271, "s", 0, "Canon", True), (272, "s", 0, "Canon EOS R7", True)])
    tiff = buf.getvalue()

    def box(t, payload):
        return struct.pack(">I4s", 8 + len(payload), t) + payload

    cmt1 = box(b"CMT1", tiff)
    uuid = box(b"uuid", bytes.fromhex("85c0b687820f11e08111f4ce462b6a48") + cmt1)
    data = box(b"ftyp", b"crx \x00\x00\x00\x01") + box(b"moov", uuid)
    md = read_metadata(data, Container.CR3)
    assert md.camera.display_name == "Canon EOS R7" and md.camera.source == "CR3 metadata"


def test_raf_header_model():
    hdr = bytearray(0x200)
    hdr[0:16] = b"FUJIFILMCCD-RAW "
    hdr[0x1C:0x1C + 5] = b"X-H2S"
    model, jpeg = raf_model_and_jpeg(bytes(hdr))
    assert model == "X-H2S" and jpeg is None
    md = read_metadata(bytes(hdr), Container.RAF)
    assert md.camera.display_name == "Fujifilm X-H2S" and md.camera.source == "RAF header"


def test_filename_is_never_used_for_camera(tmp_path):
    from PIL import Image
    p = tmp_path / "NIKON_D850_DSC_0001.jpg"
    Image.fromarray(gradient_image()).save(p, "JPEG")
    assert read_metadata(p.read_bytes(), Container.JPEG).camera.display_name == "Unknown camera"
