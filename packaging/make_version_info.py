"""Write the Windows version resource for the .exe from birdedit.__version__."""
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
version = re.search(r'__version__ = "([^"]+)"', (root / "backend/birdedit/__init__.py").read_text()).group(1)
nums = tuple(int(x) for x in version.split(".")) + (0,) * (4 - len(version.split(".")))
out = root / "packaging" / "build"
out.mkdir(parents=True, exist_ok=True)
(out / "version_info.txt").write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
      StringStruct('ProductName', 'Bird Photo Editor'),
      StringStruct('FileDescription', 'Bird Photo Editor'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('ProductVersion', '{version}'),
      StringStruct('OriginalFilename', 'BirdPhotoEditor.exe'),
      StringStruct('LegalCopyright', 'Open-source components; see licenses')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding="utf-8")
print(version)
if len(sys.argv) > 1:
    Path(sys.argv[1]).write_text(version)
