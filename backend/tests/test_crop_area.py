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
