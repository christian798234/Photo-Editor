# PyInstaller spec: builds dist/BirdPhotoEditor/ (one folder, windowed).
# Run from the repository root:  pyinstaller packaging/birdedit.spec
# The bird detection models are NOT bundled here; the installer installs them
# as an optional component next to the .exe.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).parent
datas = [(str(root / "backend" / "birdedit" / "web"), "birdedit/web"),
         (str(root / "packaging" / "build" / "icon.ico"), ".")]
binaries = []
hiddenimports = collect_submodules("uvicorn") + collect_submodules("birdedit")
import sys
pkgs = ["rawpy", "onnxruntime"]
if sys.platform == "win32":
    pkgs += ["webview", "pythonnet", "clr_loader"]      # program window (WebView2)
for pkg in pkgs:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(root / "packaging" / "launcher.py")],
    pathex=[str(root / "backend")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "httpx", "matplotlib", "torch", "IPython", "imagecodecs"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="BirdPhotoEditor",
    console=False,
    icon=str(root / "packaging" / "build" / "icon.ico"),
    version=str(root / "packaging" / "build" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="BirdPhotoEditor")
