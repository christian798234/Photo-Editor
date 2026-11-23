"""Draw the app icon (blue rounded square with a white bird) as .ico/.png."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

out = Path(sys.argv[1] if len(sys.argv) > 1 else "packaging/build")
out.mkdir(parents=True, exist_ok=True)
S = 512
im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.rounded_rectangle([8, 8, S - 8, S - 8], radius=110, fill=(47, 111, 224, 255))
bird = [(110, 330), (190, 300), (250, 230), (320, 190), (395, 185), (430, 210), (400, 215),
        (370, 240), (345, 300), (290, 345), (210, 365), (140, 360)]
d.polygon(bird, fill=(255, 255, 255, 255))
d.polygon([(250, 260), (300, 140), (330, 150), (300, 260)], fill=(230, 238, 255, 255))   # wing
d.ellipse([382, 196, 394, 208], fill=(47, 111, 224, 255))                                 # eye
im.save(out / "icon.png")
im.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon written to", out)
