"""Build an unprotected Galactic Dan disc image from the original DSK.

Replaces !RunImage (encrypted loader) with the decrypted game, removes the
DARE and RayGun (protection module) entries, drops the RayGun line from !Run,
and writes both a flat ADFS D .adf and a normal CPCEMU .dsk.
"""
import struct, sys

src_dsk, game_path, out_adf, out_dsk = sys.argv[1:5]
TSZ = 5376


def dsk_to_flat(d):
    flat = bytearray()
    for i in range(160):
        o = 0x100 + i * TSZ
        t = d[o:o + 256]
        ns, ssz = t[0x15], 128 << t[0x14]
        secs = {t[0x18 + 8 * k + 2]: d[o + 256 + k * ssz:o + 256 + (k + 1) * ssz] for k in range(ns)}
        if ssz == 1024 and sorted(secs) == list(range(5)):
            flat += b''.join(secs[k] for k in range(5))
        else:  # protection track: not part of the filesystem
            flat += b'\xe5' * 5120
    return flat


def ror13(v):
    return ((v >> 13) | (v << 19)) & 0xFFFFFFFF


def checkbyte(d):
    last = 5
    while d[last]:
        last += 26
    acc, i = 0, 0
    while i < (last & ~3):
        acc = struct.unpack_from('<I', d, i)[0] ^ ror13(acc); i += 4
    while i < last:
        acc = d[i] ^ ror13(acc); i += 1
    for i in range(2008, 2044, 4):
        acc = struct.unpack_from('<I', d, i)[0] ^ ror13(acc)
    return (acc ^ acc >> 8 ^ acc >> 16 ^ acc >> 24) & 0xFF


def entries(d):
    out, o = [], 5
    while d[o]:
        out.append(bytearray(d[o:o + 26])); o += 26
    return out


def name(e):
    return bytes(c & 0x7F for c in e[:10]).split(b'\r')[0].split(b'\0')[0].decode()


def write_dir(img, addr, ents):
    d = bytearray(img[addr:addr + 0x800])
    body = b''.join(ents) + b'\0'
    d[5:5 + 26 * 77] = body + bytes(26 * 77 - len(body))
    d[0x7FF] = checkbyte(d)
    img[addr:addr + 0x800] = d


img = dsk_to_flat(open(src_dsk, 'rb').read())
GAL = 0xC00
for a in (0x400, GAL, 0x1400):  # sanity-check the checksum routine
    assert checkbyte(img[a:a + 0x800]) == img[a + 0x7FF], hex(a)

ents = entries(img[GAL:GAL + 0x800])
by = {name(e).lower(): e for e in ents}
dare, runimg, run = by['dare'], by['!runimage'], by['!run']

game = open(game_path, 'rb').read()
dare_len = struct.unpack_from('<I', dare, 18)[0]
dare_at = int.from_bytes(dare[22:25], 'little') * 256
assert len(game) <= dare_len
img[dare_at:dare_at + dare_len] = game + bytes(dare_len - len(game))

# !RunImage -> decrypted game in DARE's sectors, filetype &FF8 (Absolute)
load = 0xFFFFF800 | (struct.unpack_from('<I', dare, 10)[0] & 0xFF)
struct.pack_into('<III', runimg, 10, load, struct.unpack_from('<I', dare, 14)[0], len(game))
runimg[22:25] = dare[22:25]

# !Run without the RayGun (protection module) line
run_at = int.from_bytes(run[22:25], 'little') * 256
run_len = struct.unpack_from('<I', run, 18)[0]
text = bytes(img[run_at:run_at + run_len])
new = b'\n'.join(l for l in text.split(b'\n') if b'RayGun' not in l)
img[run_at:run_at + 1024] = new + bytes(1024 - len(new))
struct.pack_into('<I', run, 18, len(new))

ents = [e for e in ents if name(e).lower() not in ('dare', 'raygun')]
write_dir(img, GAL, ents)
assert checkbyte(img[GAL:GAL + 0x800]) == img[GAL + 0x7FF]
open(out_adf, 'wb').write(img)

# Plain CPCEMU DSK: 80 cyl x 2 heads x 5 x 1K sectors, same layout as the source
hdr = bytearray(256)
hdr[:34] = b'MV - CPCEMU Disk-File\r\nDisk-Info\r\n'
hdr[0x22:0x2A] = b'(LIBDSK)'
hdr[0x30], hdr[0x31] = 80, 2
struct.pack_into('<H', hdr, 0x32, TSZ)
out = bytearray(hdr)
for i in range(160):
    t = bytearray(256)
    t[:12] = b'Track-Info\r\n'
    t[0x10], t[0x11] = i // 2, i % 2
    t[0x14], t[0x15], t[0x16], t[0x17] = 3, 5, 0x05, 0xE5
    for k in range(5):
        t[0x18 + 8 * k:0x18 + 8 * k + 4] = bytes([i // 2, i % 2, k, 3])
    out += t + img[i * 5120:(i + 1) * 5120]
open(out_dsk, 'wb').write(out)
print('ok', len(img), len(out))
