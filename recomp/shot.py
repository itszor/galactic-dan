"""shot.py prefix.screen out.png : render both mode-13 banks of a screen dump."""
import sys
from PIL import Image
pix = open(sys.argv[1], 'rb').read()[0x20000:0x20000 + 320 * 512]
pal = []
for c in range(256):
    t = c & 3
    r = ((c >> 4) & 1) << 3 | ((c >> 2) & 1) << 2 | t
    g = ((c >> 6) & 1) << 3 | ((c >> 5) & 1) << 2 | t
    b = ((c >> 7) & 1) << 3 | ((c >> 3) & 1) << 2 | t
    pal += [r * 17, g * 17, b * 17]
im = Image.frombytes('P', (320, 512), pix)
im.putpalette(pal)
im.resize((640, 1024), Image.NEAREST).save(sys.argv[2])
