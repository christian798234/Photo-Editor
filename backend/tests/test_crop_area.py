"""Decoded RAWs are trimmed to the camera's official image area (maker-note or
DNG DefaultCrop), consistently for every orientation and for half-size previews."""

import io

import numpy as np
import pytest
import rawpy

from birdedit import decode, formats

from conftest import make_dng_with_crop

ROT = {1: lambda a: a, 3: lambda a: a[::-1, ::-1], 6: lambda a: np.rot90(a, -1), 8: lambda a: np.rot90(a, 1)}


@pytest.mark.parametrize("orientation", [1, 3, 6, 8])
def test_official_crop_matches_reference_for_each_orientation(tmp_path, orientation):
    p = make_dng_with_crop(tmp_path / f"o{orientation}.dng", orientation)
    data = p.read_bytes()
    dec = decode.decode(data, formats.classify(data[:64], ".dng"), half=False)
    # Reference: decode unrotated, crop in sensor coordinates, then rotate.
    r = rawpy.imread(io.BytesIO(data))
    ref = r.postprocess(output_bps=16, gamma=(1, 1), no_auto_bright=True, use_camera_wb=True,
                        demosaic_algorithm=rawpy.DemosaicAlgorithm.DHT, highlight_mode=rawpy.HighlightMode.Clip,
                        output_color=rawpy.ColorSpace.ProPhoto, user_flip=0).astype(np.float32) / 65535
    x, y, w, h = 8, 4, 584, 392
    ref = ROT[orientation](ref[y:y + h, x:x + w])
    assert dec.image.shape == ref.shape, (dec.image.shape, ref.shape)
    assert np.abs(dec.image - ref).max() < 2e-3
    exp_full = (584, 392) if orientation in (1, 3) else (392, 584)
    assert dec.full_size == exp_full and dec.info["profile_known"] is True


def test_half_size_crop_is_consistent(tmp_path):
    p = make_dng_with_crop(tmp_path / "half.dng", 6)
    data = p.read_bytes()
    half = decode.decode(data, formats.classify(data[:64], ".dng"), half=True)
    assert half.full_size == (392, 584)
    assert abs(half.image.shape[1] - 196) <= 1 and abs(half.image.shape[0] - 292) <= 1


def test_no_crop_when_not_provided(tmp_path):
    p = make_dng_with_crop(tmp_path / "full.dng", 1, crop=(0, 0, 600, 400))
    data = p.read_bytes()
    dec = decode.decode(data, formats.classify(data[:64], ".dng"), half=False)
    assert dec.full_size == (600, 400) and dec.image.shape[:2] == (400, 600)


def test_crop_origin_is_relative_to_full_sensor(tmp_path):
    """LibRaw reports the official area relative to the whole sensor readout
    (as Canon CR3 and DNG ActiveArea files have masked borders). Found with a
    real Canon EOS R6 Mark II CR3: 6000x4000 starting 14/12 px inside the
    decoded frame, not 168/108."""
    import tifffile
    h, w = 400, 600
    yy, xx = np.mgrid[0:h, 0:w]
    raw = (512 + (0.05 + 0.4 * xx / w + 0.3 * (yy / h) ** 2) * 15000).astype(np.uint16)
    raw[:10, :] = 0
    raw[:, :12] = 0
    cm = [1.0, -0.2, -0.1, -0.3, 1.2, 0.1, -0.05, 0.2, 0.8]
    srat = [x for v in cm for x in (int(round(v * 10000)), 10000)]
    p = tmp_path / "aa.dng"
    tifffile.imwrite(p, raw, photometric=32803, metadata=None, extratags=[
        (271, "s", 0, "SONY", True), (272, "s", 0, "T", True), (50706, "B", 4, (1, 4, 0, 0), True),
        (33421, "H", 2, (2, 2), True), (33422, "B", 4, (0, 1, 1, 2), True), (50714, "H", 1, (512,), True),
        (50717, "H", 1, (16383,), True), (50728, "2I", 3, (10000, 10000, 10000, 10000, 10000, 10000), True),
        (50721, "2i", 9, srat, True), (50778, "H", 1, (21,), True),
        (50829, "I", 4, (10, 12, 400, 600), True),               # ActiveArea: masked top/left border
        (50719, "I", 2, (4, 2), True), (50720, "I", 2, (576, 384), True)])
    data = p.read_bytes()
    dec = decode.decode(data, formats.classify(data[:64], ".dng"), half=False)
    assert dec.full_size == (576, 384)
    assert dec.info["official_crop"] == [4, 2, 576, 384]        # inside the 588x390 decoded frame
