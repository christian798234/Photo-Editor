"""Program-window helpers. The window itself needs Windows/WebView2 and is
exercised by the Windows CI job; these tests cover the logic around it."""

import pytest

from birdedit import desktop, dialogs


def test_file_filters_are_valid_for_pywebview():
    pytest.importorskip("webview")
    from webview.util import parse_file_type
    types = desktop.file_types(dialogs._patterns())
    assert types[0].startswith("Photos (*.") and "*.nef" in types[0] and "*.arw" in types[0]
    assert types[-1] == "All files (*.*)"
    for t in types:
        parse_file_type(t)                    # raises ValueError if pywebview would reject it


def test_dialog_failure_returns_friendly_message(client, monkeypatch):
    def boom():
        raise ValueError("bad filter")
    monkeypatch.setattr(dialogs, "choose_files", boom)
    r = client.post("/api/import/dialog")
    assert r.status_code == 501 and "Import Photos again" in r.json()["detail"]
    monkeypatch.setattr(dialogs, "choose_folder", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    r = client.post("/api/dialog/folder")
    assert r.status_code == 501 and "folder" in r.json()["detail"]


def test_desktop_choose_uses_valid_filters():
    pytest.importorskip("webview")
    from webview.util import parse_file_type
    seen = {}

    class FakeWindow:
        def create_file_dialog(self, kind, allow_multiple=False, file_types=()):
            for t in file_types:
                parse_file_type(t)
            seen["types"] = file_types
            return ("C:\\\\Photos\\\\DSC_0001.NEF",)

    d = desktop.DesktopWindow.__new__(desktop.DesktopWindow)
    import webview
    d.webview, d.window = webview, FakeWindow()
    assert d.choose("files", dialogs._patterns()) == ["C:\\\\Photos\\\\DSC_0001.NEF"]
    assert seen["types"]


class Sc:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.width, self.height = x, y, w, h


def test_window_position_restored_on_connected_monitor():
    screens = [Sc(0, 0, 1920, 1080), Sc(1920, 0, 2560, 1440)]
    g = desktop.choose_geometry({"x": 2100, "y": 100, "width": 1500, "height": 900, "maximized": True}, screens)
    assert g == {"x": 2100, "y": 100, "width": 1500, "height": 900, "maximized": True}
    # Left monitor arrangement (negative coordinates) also works.
    left = [Sc(0, 0, 1920, 1080), Sc(-1920, 0, 1920, 1080)]
    assert desktop.choose_geometry({"x": -1800, "y": 50, "width": 900, "height": 1000}, left)["x"] == -1800


def test_window_falls_back_when_monitor_unplugged():
    only_laptop = [Sc(0, 0, 1366, 768)]
    assert desktop.choose_geometry({"x": 2100, "y": 100, "width": 1500, "height": 900}, only_laptop) is None
    # Partly off-screen / too large: pulled inside the screen and shrunk to fit.
    g = desktop.choose_geometry({"x": 1000, "y": 20, "width": 1600, "height": 1000}, only_laptop)
    assert g["width"] == 1366 and g["height"] == 768 and g["x"] == 0 and g["y"] == 0
    assert desktop.choose_geometry(None, only_laptop) is None
    assert desktop.choose_geometry({"x": "junk"}, only_laptop) is None


def test_minimum_size_allows_snapping_to_half_screen():
    assert desktop.MIN_SIZE[0] <= 1366 // 2 and desktop.MIN_SIZE[1] <= 768 // 2 + 100


def test_screen_of_picks_monitor_under_point():
    screens = [Sc(0, 0, 1920, 1080), Sc(1920, 0, 2560, 1440)]
    assert desktop.screen_of(screens, 2500, 500) is screens[1]
    assert desktop.screen_of(screens, -50, 500) is screens[0]


def test_display_relay_and_second_screen_endpoints(client):
    import threading
    r = client.post("/api/display", json={"photo_id": "a" * 32, "compare": "after", "name": "x.NEF"})
    v = r.json()["version"]
    got = client.get("/api/display", params={"since": v - 1}).json()
    assert got["version"] == v and got["state"]["name"] == "x.NEF"
    # A waiting reader is released by the next update.
    out = {}
    t = threading.Thread(target=lambda: out.update(client.get("/api/display", params={"since": v}).json()))
    t.start()
    client.post("/api/display", json={"photo_id": "b" * 32})
    t.join(5)
    assert out["state"]["photo_id"] == "b" * 32
    # Browser mode: no second-screen window available.
    assert client.post("/api/second-screen").status_code == 409
    assert client.get("/api/screens").json()["shell"] == "browser"


def test_quit_endpoint_and_version_check(data_dir):
    from fastapi.testclient import TestClient

    from birdedit import __version__
    from birdedit.server import create_app
    app = create_app(token="secret", port=8765, data_dir=data_dir)
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    assert c.get("/api/health").json()["version"] == __version__
    quit_called = []
    app.state.quit_app = lambda: quit_called.append(True)
    assert c.post("/api/quit").json() == {"ok": True}
    import time
    time.sleep(0.6)
    assert quit_called == [True]
    assert c.post("/api/quit", headers={"Origin": "https://evil.example"}).status_code == 403
    app.state.jobs.shutdown()


def test_unexpected_errors_explain_and_point_to_log(client, monkeypatch):
    from fastapi.testclient import TestClient
    c = TestClient(client.app, base_url="http://127.0.0.1:8765", raise_server_exceptions=False)
    c.headers.update({"X-BirdEdit-Token": "test-token"})
    monkeypatch.setattr(client.app.state.store, "list", lambda: 1 / 0)
    r = c.get("/api/photos")
    assert r.status_code == 500 and "ZeroDivisionError" in r.json()["detail"] and "log file" in r.json()["detail"]
