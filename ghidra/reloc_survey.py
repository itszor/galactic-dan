import sys, os, json, pickle, collections, re, subprocess
sys.path.insert(0, '.')
import spider
img = open('../game/GalacticDan_8000,ff8', 'rb').read(); base = 0x8000; end = base + len(img)
sp = pickle.load(open('galdan.json.pickle', 'rb'))
code = set(sp.code)
W = lambda a: int.from_bytes(img[a-base:a-base+4], 'little')
dis = {}
for line in subprocess.run(['arm-none-eabi-objdump','-z','-b','binary','-m','armv2a','-D','--adjust-vma=0x8000','../game/GalacticDan_8000,ff8'],capture_output=True,text=True).stdout.splitlines():
    m = re.match(r'\s*([0-9a-f]+):\s+[0-9a-f]{8}\s+(.*)$', line)
    if m: dis[int(m.group(1),16)] = m.group(2).split('@')[0].strip()
loads = collections.defaultdict(list)
for a in sorted(code):
    w = W(a)
    if (w & 0x0F7F0000) == 0x051F0000 and not (w >> 22) & 1:
        off = w & 0xFFF; lit = a + 8 + (off if w & (1<<23) else -off)
        if base <= lit < end and lit not in code: loads[lit].append(a)
cls = collections.Counter()
samples = collections.defaultdict(list)
for lit, sites in sorted(loads.items()):
    v = W(lit)
    k = 'in-image' if base <= v < end else 'above' if end <= v < 0x100000 else 'other'
    cls[k] += 1
    if k != 'other': samples[k].append((lit, v, sites))
print(cls)
for k in ('in-image','above'):
    print('==', k)
    for lit, v, sites in samples[k][:400]:
        a = sites[0]
        ctx = ' ; '.join(dis.get(x,'?') for x in range(a, a+16, 4))
        print('%x=%x  @%x: %s' % (lit, v, a, ctx))

print('\n######## still numeric in galdan.s')
src = open('../asm/galdan.s').read().splitlines()
numeric = set()
for i, l in enumerate(src):
    m = re.match(r'^(d|var)_([0-9a-f]+):$', l)
    if m and i + 1 < len(src) and src[i+1].startswith('\t.word\t0x'):
        numeric.add(int(m.group(2), 16))
kinds = collections.Counter()
for lit in sorted(numeric):
    if lit not in loads: continue
    v = W(lit)
    for a in loads[lit][:1]:
        ctx = ' ; '.join(dis.get(x,'?') for x in range(a, a+20, 4))
        print('%x=%08x  @%x: %s' % (lit, v, a, ctx))
