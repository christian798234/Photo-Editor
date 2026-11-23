from birdedit.formats import Container, Kind, classify, sniff_container


def test_content_sniffing():
    assert sniff_container(b"\xff\xd8\xff\xe1....") == Container.JPEG
    assert sniff_container(b"II*\x00\x08\x00\x00\x00") == Container.TIFF
    assert sniff_container(b"MM\x00*\x00\x00\x00\x08") == Container.TIFF
    assert sniff_container(b"FUJIFILMCCD-RAW 0201") == Container.RAF
    assert sniff_container(b"\x00\x00\x00\x18ftypcrx \x00\x00\x00\x01") == Container.CR3
    assert sniff_container(b"IIU\x00\x18\x00\x00\x00") == Container.RW2
    assert sniff_container(b"IIRO\x08\x00\x00\x00") == Container.ORF
    assert sniff_container(b"hello world") == Container.UNKNOWN


def test_extension_is_only_a_hint():
    # TIFF content named .NEF -> RAW; named .tif -> raster
    assert classify(b"II*\x00", ".NEF").kind == Kind.RAW
    assert classify(b"II*\x00", ".tif").kind == Kind.RASTER
    # JPEG content with a RAW extension is opened as JPEG, with a note
    s = classify(b"\xff\xd8\xff\xe0", ".ARW")
    assert s.kind == Kind.RASTER and "JPEG" in s.note
    # garbage with a RAW extension is unsupported, not trusted
    s = classify(b"not an image at all", ".NEF")
    assert s.kind == Kind.UNSUPPORTED
