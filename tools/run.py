import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from arm2 import ARM, Stop

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, 'out', '!Galactic')
fname, LOAD = sys.argv[1], int(sys.argv[2], 16)
dump = sys.argv[3] if len(sys.argv) > 3 else 'mem.bin'

arm = ARM()
img = open(os.path.join(D, fname), 'rb').read()
arm.mem[LOAD:LOAD + len(img)] = img
arm.r[15] = LOAD
arm.r[13] = 0xA0000
arm.r[14] = 0x3FFFFF0
arm.r[12] = 0x8000
rma_next = [0x900000]
vectors = {}


def cstr(a):
    s = bytearray()
    while arm.mem[a] >= 32 or arm.mem[a] == 0xA0:
        s.append(arm.mem[a]); a += 1
    return bytes(s)


def swi(arm, n, pc):
    x = n & ~0x20000
    regs = ' '.join('%08x' % v for v in arm.r[:8])
    print('SWI &%X at %08x  r0-r7=%s' % (n, pc, regs))
    if x == 0x1E and arm.r[0] == 6:          # OS_Module claim
        arm.r[2] = rma_next[0]; rma_next[0] += (arm.r[3] + 0xFFF) & ~0xFFF
        print('   RMA claim %x -> %08x' % (arm.r[3], arm.r[2])); return
    if x == 0x1F:                            # OS_Claim
        vectors[arm.r[0]] = (arm.r[1], arm.r[2])
        print('   OS_Claim vector %x -> code %08x r12 %08x' % (arm.r[0], arm.r[1], arm.r[2])); return
    if x in (0, 3):                          # WriteC / NewLine
        return
    if x == 5:
        print('   OS_CLI %r' % cstr(arm.r[0]))
    raise Stop('unhandled SWI')


arm.swi_handler = swi
try:
    while True:
        if arm.r[15] == 0x3FFFFF0:
            raise Stop('returned')
        arm.step()
except Stop as e:
    print('stop:', e, 'pc=%08x steps=%d' % (arm.r[15], arm.steps))
    print(' '.join('r%d=%08x' % (k, v) for k, v in enumerate(arm.r)))
print('vectors:', {hex(k): tuple(map(hex, v)) for k, v in vectors.items()})
open(os.path.join(HERE, dump), 'wb').write(arm.mem)
