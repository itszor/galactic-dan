"""Dynamic discovery of position-dependent words in the image.

Runs the original under emu.RiscOS, tracking for each register the image word
it was loaded from (if loaded unchanged).  Records:

  offset facts:  word X (loaded into rM) is added to a base that is pc or an
                 address-valued register  ->  X = target - base
  pointer facts: word X (loaded into rB) is used directly as a memory base
                 address or jump target  ->  X = target (absolute)

Words written by the program before being used are ignored (run-time
relocation).  Output: JSON for gen_asm.py --dyn=FILE.

Usage: provtrack.py image steps out.json [key-script]
"""
import sys, json, collections
import emu

WS_TOP = 0xA8000


def main():
    img = open(sys.argv[1], 'rb').read()
    steps = int(float(sys.argv[2]))
    keys = {}
    if len(sys.argv) > 4 and sys.argv[4]:
        for k in sys.argv[4].split(','):
            n, r = k.split('@'); s, e = r.split('-')
            keys[int(n)] = (int(float(s)), int(float(e)))
    base, end = 0x8000, 0x8000 + len(img)
    sc = dict(emu.SCENARIO)
    if keys: sc['keys'] = keys
    ros = emu.RiscOS(img, base, **sc)
    arm = ros.arm
    reads, writes = [], []
    written = set()
    rw0, rb0, ww0, wb0 = arm.rw, arm.rb, arm.ww, arm.wb
    arm.rw = lambda a: (reads.append(a & 0x3FFFFFC), rw0(a))[1]
    arm.rb = lambda a: (reads.append(None), rb0(a))[1]

    def ww(a, v):
        written.add(a & 0x3FFFFFC); writes_log.append(a & 0x3FFFFFC); ww0(a, v)

    def wb(a, v):
        written.add(a & 0x3FFFFFC); wb0(a, v)
    arm.ww, arm.wb = ww, wb

    prov = [None] * 16               # image word each register was loaded from
    taint = [False] * 16             # register holds a pc-derived address
    shadow = {}                      # memory word -> holds a pc-derived address
    writes_log = []
    offsets = {}                     # X -> (target, base, use pc)
    pointers = {}                    # X -> (target, use pc)
    conflicts = collections.Counter()

    def in_img(x):
        return x is not None and base <= x < end

    def is_addr(v):
        return base <= v < WS_TOP

    def fact_offset(x, target, b, pc):
        if not in_img(x) or x in written:
            return
        if target == b and b != pc + 8:
            return                       # zero-valued variable, not an offset
        old = offsets.get(x)
        if old and (old[0], old[1]) != (target, b):
            conflicts[x] += 1
            if old[0] - old[1] != target - b:
                print('inconsistent offset word %x: %r vs %r' % (x, old, (target, b, pc)))
            return
        offsets[x] = (target, b, pc)

    def fact_pointer(x, v, pc):
        if not in_img(x) or x in written or not is_addr(v):
            return
        pointers.setdefault(x, (v, pc))

    try:
        for _ in range(steps):
            if arm.r[15] == emu.RETURN_TO_OS:
                break
            ros.interrupts()                         # handlers run outside tracking
            pc = arm.r[15]
            i = arm.rw(pc); reads.clear()
            before = list(arm.r)
            t = (i >> 25) & 7
            cond_ok = arm.cond(i >> 28)
            # ---- uses (evaluated on pre-state) ----
            if cond_ok and t in (0, 1) and (i & 0x0E000090) != 0x90 and not (i & 0x0FC000F0) == 0x90:
                op = (i >> 21) & 15
                rn = (i >> 16) & 15
                if op in (4, 2) and t == 0 and ((i >> 4) & 0xFF) == 0:
                    rm = i & 15
                    vn = arm.r[15] + 8 if rn == 15 else before[rn]
                    vm = before[rm] if rm != 15 else pc + 8
                    res = (vn + vm) & 0xFFFFFFFF if op == 4 else (vn - vm) & 0xFFFFFFFF
                    # base + offset where offset came from an image word
                    if op == 4 and rm != 15 and prov[rm] is not None and (rn == 15 or taint[rn]) \
                            and is_addr(res):
                        fact_offset(prov[rm], res, vn, pc)
                    elif op == 4 and rn != 15 and prov[rn] is not None and (rm == 15 or taint[rm]) \
                            and is_addr(res):
                        fact_offset(prov[rn], res, vm, pc)
                if ((i >> 12) & 15) == 15 and op == 13 and t == 0 and ((i >> 4) & 0xFF) == 0:
                    rm = i & 15                             # mov pc, rm
                    if prov[rm] is not None:
                        fact_pointer(prov[rm], before[rm] & 0x3FFFFFC, pc)
            if cond_ok and t in (2, 3):
                rn = (i >> 16) & 15
                if t == 3 and ((i >> 4) & 0xFF) == 0 and (i >> 24) & 1:
                    rm = i & 15
                    vn = pc + 8 if rn == 15 else before[rn]
                    if prov[rm] is not None and (rn == 15 or taint[rn]) and (i >> 23) & 1:
                        fact_offset(prov[rm], (vn + before[rm]) & 0xFFFFFFFF, vn, pc)
                if rn != 15 and prov[rn] is not None:
                    fact_pointer(prov[rn], before[rn], pc)
            if cond_ok and t == 4:
                rn = (i >> 16) & 15
                if rn != 15 and prov[rn] is not None:
                    fact_pointer(prov[rn], before[rn], pc)
            # ---- execute ----
            reads.clear(); writes_log.clear()
            tb = list(taint)
            try:
                arm.step()
            except emu.Stop as e:
                ros.done = str(e); break
            del reads[:1]                            # the instruction fetch
            if not cond_ok:
                continue
            # ---- taint update ----
            T = lambda r: True if r == 15 else tb[r]
            if t in (0, 1):
                if (i & 0x0FC000F0) == 0x90:
                    taint[(i >> 16) & 15] = False
                elif (i & 0x0FB00FF0) == 0x01000090:
                    taint[(i >> 12) & 15] = False
                else:
                    op, rd, rn = (i >> 21) & 15, (i >> 12) & 15, (i >> 16) & 15
                    reg2 = t == 0
                    t2 = T(i & 15) if reg2 and ((i >> 4) & 0xFF) == 0 else False
                    if not 8 <= op <= 11 and rd != 15:
                        if op == 4: taint[rd] = T(rn) != t2
                        elif op == 2: taint[rd] = T(rn) and not t2
                        elif op == 13: taint[rd] = t2
                        elif op in (0, 12, 14) and not reg2: taint[rd] = T(rn)
                        else: taint[rd] = False
            elif t in (2, 3):
                rn, rd = (i >> 16) & 15, (i >> 12) & 15
                word = not (i >> 22) & 1
                if (i >> 20) & 1:
                    if rd != 15:
                        taint[rd] = word and bool(reads) and shadow.get(reads[0], False)
                elif word and writes_log:
                    shadow[writes_log[0]] = T(rd)
                if ((i >> 21) & 1 or not (i >> 24) & 1) and not ((i >> 20) & 1 and rd == rn):
                    taint[rn] = tb[rn]
            elif t == 4:
                rn = (i >> 16) & 15
                regs = [k for k in range(16) if i & (1 << k)]
                if (i >> 20) & 1:
                    for k, a in zip(regs, reads):
                        if k != 15: taint[k] = shadow.get(a, False)
                else:
                    for k, a in zip(regs, writes_log):
                        shadow[a] = T(k)
            elif t == 5 and (i >> 24) & 1:
                taint[14] = True
            elif t == 7:
                for k in range(8):
                    if arm.r[k] != before[k]: taint[k] = False
            # ---- provenance update ----
            if t in (0, 1):
                if (i & 0x0FC000F0) == 0x90:
                    prov[(i >> 16) & 15] = None
                elif (i & 0x0FB00FF0) == 0x01000090:
                    prov[(i >> 12) & 15] = None
                else:
                    op, rd = (i >> 21) & 15, (i >> 12) & 15
                    if not 8 <= op <= 11:
                        if op == 13 and t == 0 and ((i >> 4) & 0xFF) == 0 and (i & 15) != 15:
                            prov[rd] = prov[i & 15]          # plain mov copies provenance
                        else:
                            prov[rd] = None
            elif t in (2, 3):
                rn, rd = (i >> 16) & 15, (i >> 12) & 15
                if (i >> 21) & 1 or not (i >> 24) & 1:
                    prov[rn] = None
                if (i >> 20) & 1:
                    word = not (i >> 22) & 1
                    prov[rd] = reads[0] if word and reads and reads[0] is not None else None
            elif t == 4:
                rn = (i >> 16) & 15
                if (i >> 20) & 1:
                    regs = [k for k in range(16) if i & (1 << k)]
                    for k, a in zip(regs, reads):
                        prov[k] = a
                if (i >> 21) & 1 and not ((i >> 20) & 1 and i & (1 << rn)):
                    prov[rn] = None
            elif t == 5 and (i >> 24) & 1:
                prov[14] = None
            elif t == 7:
                for k in range(8): prov[k] = None
    finally:
        pass
    print('ran %d steps (%s); offset facts %d, pointer facts %d, conflicting %d' % (
        arm.steps, ros.done, len(offsets), len(pointers), len(conflicts)))
    json.dump(dict(offsets={'%x' % k: ['%x' % v[0], '%x' % v[1], '%x' % v[2]] for k, v in offsets.items()},
                   pointers={'%x' % k: ['%x' % v[0], '%x' % v[1]] for k, v in pointers.items()},
                   conflicts=['%x' % k for k in conflicts]),
              open(sys.argv[3], 'w'), indent=0)
    emu.screenshot(ros, 'prov_last.png', ros.display_bank)


if __name__ == '__main__':
    main()
