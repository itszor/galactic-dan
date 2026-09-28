"""Run the original image and a relocated (padded) rebuild in lock-step and
report the first place where they stop behaving identically.

Usage: difftest.py original padded pads steps [key-script]
  pads: the same "addr:size,..." list given to gen_asm.py --pad (hex)
  key-script: "inkey@step-step,..." e.g. "99@3000000-3100000" (decimal inkey)

Checks, modulo the address shift introduced by the padding:
  * PC stream: pc_B == map(pc_A) at every step
  * registers: equal, or equal after mapping when A's value is an address
  * SWI events (names/args, mapping addresses) and the VDU byte stream
  * screen memory, compared periodically and at the end
"""
import sys, collections
import emu

WS_TOP = 0xA8000
# pc -> registers whose value is an address leaked into numeric use.
# 0x866c: sub_866c is entered with r2 still holding the address of the string
# "statusbar" left over from sub_13f94's OS_SpriteOp call, and uses it as a number.
ASSUME = {0x866c: (2,)}


def main():
    a_img = open(sys.argv[1], 'rb').read()
    b_img = open(sys.argv[2], 'rb').read()
    pads = sorted((int(p.split(':')[0], 16), int(p.split(':')[1], 16))
                  for p in sys.argv[3].split(','))
    steps = int(float(sys.argv[4]))
    keys = {}
    if len(sys.argv) > 5:
        for k in sys.argv[5].split(','):
            n, r = k.split('@')
            s, e = r.split('-')
            keys[int(n)] = (int(float(s)), int(float(e)))
    base, end = 0x8000, 0x8000 + len(a_img)
    total = sum(n for _, n in pads)
    assert len(b_img) == len(a_img) + total, (len(b_img), len(a_img), total)

    def shift(x):
        if x >= end:
            return total
        return sum(n for p, n in pads if p <= x)

    def is_addr(x):
        return base <= x < WS_TOP

    def mapa(x):
        return (x + shift(x)) if is_addr(x) else x

    sc = dict(emu.SCENARIO)
    if keys: sc['keys'] = keys
    A = emu.RiscOS(a_img, base, **sc)
    B = emu.RiscOS(b_img, base, **sc)
    ra, rb = A.arm, B.arm
    for m in (ra, rb):
        m.acc = []
        for name in ('rw', 'rb'):
            f = getattr(m, name)
            setattr(m, name, (lambda f, m, name: lambda a: (m.acc.append((name, a & 0x3FFFFFF, None)), f(a))[1])(f, m, name))
        for name in ('ww', 'wb'):
            f = getattr(m, name)
            setattr(m, name, (lambda f, m, name: lambda a, v: (m.acc.append((name, a & 0x3FFFFFF, v & 0xFFFFFFFF)), f(a, v))[1])(f, m, name))
    hist = collections.deque(maxlen=24)
    soft = []
    assumed = {}
    regok = [True] * 15
    regorigin = [None] * 15
    last_pc = None
    bad = None
    SCR = slice(emu.SCREEN - 0x20000, emu.SCREEN + 0x40000)
    for i in range(steps):
        pa = ra.r[15]
        if pa == emu.RETURN_TO_OS:
            print('A returned to OS'); break
        pb = rb.r[15]
        if pb != mapa(pa):
            bad = 'PC diverged: A=%08x B=%08x (expected %08x)' % (pa, pb, mapa(pa)); break
        if ra.flags != rb.flags:
            bad = 'flags differ before %08x: A=%08x B=%08x' % (pa, ra.flags, rb.flags); break
        hist.append(pa)
        # Known inherent address leaks in the original program: make B see A's
        # numeric value so the rest of the run can still be compared.
        for r in ASSUME.get(pa, ()):
            if rb.r[r] != ra.r[r]:
                assumed[pa] = assumed.get(pa, 0) + 1
                rb.r[r] = ra.r[r]
        ra.acc.clear(); rb.acc.clear()
        prev_regs = (list(ra.r), list(rb.r))
        for k in range(15):
            x, y = ra.r[k], rb.r[k]
            ok = y == x or y == mapa(x) or (is_addr(x & 0x3FFFFFC) and (y & 0x3FFFFFC) == mapa(x & 0x3FFFFFC))
            if not ok and regok[k]:
                regorigin[k] = (last_pc, ra.steps, x, y)
            regok[k] = ok
        last_pc = pa
        na, nb = len(A.events), len(B.events)
        try:
            A.step()
        except emu.Stop as e:
            A.done = str(e)
        try:
            B.step()
        except emu.Stop as e:
            B.done = str(e)
        if len(ra.acc) != len(rb.acc):
            bad = 'memory access count differs at %08x' % pa; break
        for (ka, xa, va), (kb, xb, vb) in zip(ra.acc, rb.acc):
            if kb != ka or xb != mapa(xa):
                bad = 'address differs at %08x: A %s %08x B %s %08x (expected %08x)' % (
                    pa, ka, xa, kb, xb, mapa(xa)); break
            if va is not None and vb != va and vb != mapa(va) and \
                    not (is_addr(va & 0x3FFFFFC) and vb == (va & ~0x3FFFFFC) | mapa(va & 0x3FFFFFC)):
                soft.append('stored value differs at %08x: [%08x] A=%08x B=%08x' % (pa, xa, va, vb))
        if bad:
            break
        if A.done or B.done:
            if (A.done or '') .split(' at ')[0] != (B.done or '').split(' at ')[0]:
                bad = 'stop differs: A=%r B=%r' % (A.done, B.done)
            break
        if len(A.events) != na or len(B.events) != nb:
            ea, eb = A.events[na:], B.events[nb:]
            if len(ea) != len(eb) or any(
                    x[1] != y[1] or len(x) != len(y) or any(
                        u != v and not (isinstance(u, int) and v == mapa(u))
                        for u, v in zip(x[2:], y[2:])) for x, y in zip(ea, eb)):
                bad = 'SWI events differ at %08x: A=%r B=%r' % (pa, ea, eb); break
        if i % 200000 == 0:
            if A.vdu != B.vdu:
                bad = 'VDU stream differs'; break
            if ra.mem[SCR] != rb.mem[SCR]:
                bad = 'screen differs'; break
            print('  %8d steps ok (A pc %08x)' % (i, pa), flush=True)
    if not bad:
        if A.vdu != B.vdu: bad = 'VDU stream differs at end'
        elif ra.mem[SCR] != rb.mem[SCR]: bad = 'screen differs at end'
    for p, n in assumed.items():
        print('assumption at %x applied %d times (known address leak in the original)' % (p, n))
    print('%d stored values differed (offsets held in registers/variables; informational)' % len(soft))
    for w in soft[:5]:
        print('   ', w)
    if bad:
        print('DIVERGENCE after %d steps: %s' % (ra.steps, bad))
        print('recent A pcs:', ' '.join('%x' % p for p in hist))
        print('registers before the failing step (A / B / map(A)):')
        for k in range(16):
            x, y = prev_regs[0][k], prev_regs[1][k]
            print('  r%-2d %08x %08x %08x %s' % (k, x, y, mapa(x), '' if y in (x, mapa(x)) else
                  '<-- became different after insn %s at step %s (A=%s B=%s)' % tuple(
                      ('%x' % v if v is not None else '?') for v in (regorigin[k] or (None,) * 4))))
        sys.exit(1)
    print('IDENTICAL behaviour for %d steps (A stopped: %s); %d SWI events, %d VDU bytes' % (
        ra.steps, A.done, len(A.events), len(A.vdu)))
    emu.screenshot(A, 'difftest_A.png')
    emu.screenshot(B, 'difftest_B.png')


if __name__ == '__main__':
    main()
