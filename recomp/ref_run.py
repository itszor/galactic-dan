"""Run the Python reference emulator (asm/emu.py) to an instruction count and
write the same outputs as the recompiled binary (<prefix>.events/.vdu/.screen/.regs).

Usage: ref_run.py steps [prefix]
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'asm'))
import emu


def fmt(a):
    if isinstance(a, bytes):
        return a.hex() or '-'
    return '%x' % a


def main():
    n = int(float(sys.argv[1]))
    prefix = sys.argv[2] if len(sys.argv) > 2 else 'ref'
    img = open(os.path.join(os.path.dirname(__file__), '..', 'extracted', 'GalacticDan_8000,ff8'), 'rb').read()
    ros = emu.RiscOS(img, 0x8000, **emu.SCENARIO)
    a = ros.arm
    tf = None
    for x in sys.argv[3:]:
        if x.startswith('--trace='):                 # --trace=from:to -> ref.trace
            lo, hi = (int(float(v)) for v in x[8:].split(':'))
            tf = open('ref.trace', 'w')
            st = a.step

            def traced():
                if lo <= a.steps < hi:
                    tf.write('%d %x %s %x\n' % (a.steps, a.r[15], ' '.join('%x' % v for v in a.r[:15]), a.flags))
                st()
            a.step = traced
    try:
        while a.steps < n:
            ros.step()
        why = 'instruction limit'
    except emu.Stop as e:
        why = str(e)
    with open(prefix + '.events', 'w') as f:
        for e in ros.events:
            f.write('%d %s%s\n' % (e[0], e[1].replace(' ', '_'), ''.join(' ' + fmt(x) for x in e[2:])))
    open(prefix + '.vdu', 'wb').write(bytes(ros.vdu))
    open(prefix + '.screen', 'wb').write(bytes(a.mem[emu.SCREEN - 0x20000:emu.SCREEN + 0x40000]))
    with open(prefix + '.regs', 'w') as f:
        for k in range(15):
            f.write('r%d %08x\n' % (k, a.r[k]))
        f.write('psr %08x\n' % a.flags)
    if tf:
        tf.close()
    print('stopped: %s after %d instructions' % (why, a.steps))


if __name__ == '__main__':
    main()
