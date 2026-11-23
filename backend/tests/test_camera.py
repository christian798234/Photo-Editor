import pytest

from birdedit.camera import camera_from_strings, clean_metadata_string, normalize_make, normalize_model


@pytest.mark.parametrize("raw,expected", [
    ("NIKON CORPORATION", "Nikon"), ("NIKON", "Nikon"), ("Nikon", "Nikon"),
    ("SONY", "Sony"), ("Sony", "Sony"), ("Canon", "Canon"), ("FUJIFILM", "Fujifilm"),
    ("OM Digital Solutions", "OM System"), ("OLYMPUS IMAGING CORP.", "Olympus"),
])
def test_make_normalisation(raw, expected):
    assert normalize_make(raw) == expected


def test_nikon_model_prefix_is_stripped_but_raw_kept():
    cam = camera_from_strings("NIKON CORPORATION", "NIKON Z 8", "EXIF")
    assert cam.make == "Nikon" and cam.model == "Z 8"
    assert cam.make_raw == "NIKON CORPORATION" and cam.model_raw == "NIKON Z 8"
    assert cam.display_name == "Nikon Z 8"


def test_sony_model_kept_exactly_as_reported():
    cam = camera_from_strings("SONY", "ILCE-7RM5", "EXIF")
    assert cam.display_name == "Sony ILCE-7RM5"   # no marketing-name guessing
    cam2 = camera_from_strings("SONY", "ILCE-1", "EXIF")
    assert cam2.model == "ILCE-1"


def test_canon_duplicate_make_in_model():
    assert camera_from_strings("Canon", "Canon EOS R5", "EXIF").display_name == "Canon EOS R5"


def test_unfamiliar_manufacturer_kept():
    cam = camera_from_strings("Acme Optical Works", "Birdcam 3000", "EXIF")
    assert cam.make == "Acme Optical Works" and cam.identified


def test_missing_metadata_is_unknown():
    cam = camera_from_strings(None, None, "EXIF")
    assert not cam.identified and cam.display_name == "Unknown camera"
    cam = camera_from_strings("", "   ", "EXIF")
    assert cam.display_name == "Unknown camera"


def test_model_only():
    cam = camera_from_strings("", "Mystery Model", "EXIF")
    assert cam.identified and cam.display_name == "Mystery Model"


def test_malformed_values_are_sanitised():
    s = clean_metadata_string(b"NIKON\x00\x00garbage")
    assert s == "NIKON"
    s = clean_metadata_string("Z 9\r\n; rm -rf /\x07")
    assert "\n" not in s and "\x07" not in s
    assert len(clean_metadata_string("x" * 500)) == 80
