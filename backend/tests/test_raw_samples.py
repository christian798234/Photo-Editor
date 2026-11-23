"""End-to-end tests with REAL camera RAW files.

Set BIRDEDIT_SAMPLES to a folder of real files. Tests for a camera family are
SKIPPED (not passed) when no sample exists, and the skip reason states which
workflow remains unverified.
"""

import os
from pathlib import Path

import numpy as np
import pytest

from birdedit import auto, decode, formats, metadata, noise, pipeline
from birdedit.recipe import effective

SAMPLES = Path(os.environ.get("BIRDEDIT_SAMPLES", "")) if os.environ.get("BIRDEDIT_SAMPLES") else None


def samples(ext: str, make: str) -> list[Path]:
    if not SAMPLES or not SAMPLES.is_dir():
        return []
    out = []
    for p in sorted(SAMPLES.iterdir()):
        if p.suffix.lower() != ext:
            continue
        data = p.read_bytes()
        sn = formats.classify(data[:64], p.suffix)
        md = metadata.read_metadata(data, sn.container)
        if md.camera.make == make and len(data) > 1_000_000:   # real files, not metadata stubs
            out.append(p)
    return out


def _full_workflow(path: Path):
    data = path.read_bytes()
    from birdedit import converter
    if converter.is_nikon_high_efficiency(data) and converter.find_dng_converter() is None:
        with pytest.raises(decode.DecodeError):
            decode.decode(data, formats.classify(data[:64], path.suffix), half=True)
        pytest.skip(f"UNVERIFIED: {path.name} is a Nikon High Efficiency NEF; decoding it needs "
                    "Adobe DNG Converter, which is not installed here")
    sn = formats.classify(data[:64], path.suffix)
    assert sn.kind == formats.Kind.RAW
    md = metadata.read_metadata(data, sn.container, decode.embedded_preview_jpeg_bytes(data))
    assert md.camera.identified
    half = decode.decode(data, sn, half=True, md=md)
    assert half.image.dtype == np.float32 and half.image.ndim == 3
    nm = noise.estimate(half.image, half.noise_native_scale, md.iso)
    recipe, facts = auto.analyze_and_build(half.image, nm)
    full = decode.decode(data, sn, half=False)
    assert abs(full.image.shape[1] - full.full_size[0]) <= 2
    out = pipeline.render_tiled(full.image, effective(recipe), nm,
                                (0, 0, full.image.shape[1], full.image.shape[0]), 1024, 128)
    assert out.dtype == np.uint16 and out.shape[:2] == full.image.shape[:2]
    assert 0.02 < out.mean() / 65535 < 0.98
    return md


@pytest.mark.parametrize("path", samples(".nef", "Nikon") or [None])
def test_real_nikon_nef(path):
    if path is None:
        pytest.skip("UNVERIFIED: no real Nikon NEF sample in BIRDEDIT_SAMPLES")
    md = _full_workflow(path)
    assert md.camera.make == "Nikon"


@pytest.mark.parametrize("path", samples(".arw", "Sony") or [None])
def test_real_sony_arw(path):
    if path is None:
        pytest.skip("UNVERIFIED: no real Sony ARW sample in BIRDEDIT_SAMPLES")
    md = _full_workflow(path)
    assert md.camera.make == "Sony"
