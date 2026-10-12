"""Minimal RISC OS environment around tools/arm2.py, enough to run Galactic
Dan's start-up, title and early game: file loading, VDU variables, keyboard,
sound stubs.  Used by difftest.py to compare two builds in lock-step.
"""
import os, sys, struct

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
from arm2 import ARM, Stop, V_, C_          # noqa: E402

APPDIR = os.path.join(HERE, '..', 'game', '!Galactic')
SCREEN = 0x1C00000 - 0x80000          # 2 x 160K screen banks just below 28MB
MEMSIZE = 0x1C00000
RETURN_TO_OS = 0x3FFFFF0
HANDLER_RET = 0x3FFFFE0
TICK_STEPS = 20000        # ~ one centisecond of ARM2 time
VSYNC_STEPS = 40000       # 50Hz

# SWI numbers (without X bit)
OS_WriteC, OS_WriteS, OS_Write0, OS_NewLine = 0, 1, 2, 3
OS_CLI, OS_Byte, OS_Word, OS_File = 5, 6, 7, 8


class RiscOS:
    def __init__(self, image, load, keys=None, trace=None, verbose=False, clicks=()):
        self.arm = ARM(MEMSIZE)
        self.arm.mem[load:load + len(image)] = image
        a = self.arm
        a.r[15] = load
        a.r[13] = 0xA8000            # top of the 640K wimpslot
        a.r[14] = RETURN_TO_OS
        a.r[12] = 0
        a.swi_handler = self.swi
        self.vdu = bytearray()        # everything written to the VDU stream
        self.events = []              # (step, name, args) for comparison
        self.vectors = {}
        self.files = {}
        self.keys = keys or {}        # inkey number -> (from_step, to_step)
        self.verbose = verbose
        self.bank = 0
        self.display_bank = 0
        self.monotonic = 0
        self.voices = 1
        self.done = None
        self.clicks = sorted(clicks)  # (step, x, y, buttons) -> mouse button events
        self.next_tick = TICK_STEPS
        self.next_vsync = VSYNC_STEPS
        self.in_handler = False

    # ---- helpers ------------------------------------------------------------
    def cstr(self, a, term=(0, 10, 13)):
        s = bytearray()
        while self.arm.mem[a] not in term:
            s.append(self.arm.mem[a]); a += 1
            if len(s) > 1024: break
        return bytes(s)

    def hostpath(self, name):
        n = name.decode('latin-1').strip()
        for pre in ('Disc1:', 'Disc2:', '<Obey$Dir>.'):
            if n.startswith(pre): n = n[len(pre):]
        parts = n.split('.')
        d = APPDIR
        for p in parts:
            want = p.lower().replace('/', '.')
            hit = None
            for f in os.listdir(d):
                if f.split(',')[0].lower() == want:
                    hit = f; break
            if hit is None:
                return None
            d = os.path.join(d, hit)
        return d

    def event(self, name, *args):
        self.events.append((self.arm.steps, name) + tuple(args))
        if self.verbose:
            print('%10d %-24s %s' % (self.arm.steps, name, ' '.join(
                a.decode('latin-1') if isinstance(a, bytes) else hex(a) if isinstance(a, int) else str(a)
                for a in args)))

    def pressed(self, inkey):
        w = self.keys.get(inkey)
        return w is not None and w[0] <= self.arm.steps < w[1]

    # ---- SWIs ---------------------------------------------------------------
    def swi(self, arm, n, pc):
        x = n & 0x20000
        b = n & ~0x20000
        r = arm.r
        arm.flags &= ~V_
        if 0x100 <= b <= 0x1FF:
            self.vdu.append(b - 0x100); return
        if b == OS_WriteC:
            self.vdu.append(r[0] & 0xFF); return
        if b == OS_WriteS:
            s = self.cstr(arm.r[15], term=(0,))
            self.vdu += s
            arm.r[15] = (arm.r[15] + len(s) + 4) & ~3
            return
        if b == OS_Write0:
            s = self.cstr(r[0], term=(0,)); self.vdu += s; r[0] += len(s) + 1; return
        if b == OS_NewLine:
            self.vdu += b'\n\r'; return
        if b == 0x46:                                   # OS_WriteN
            self.vdu += bytes(arm.mem[r[0]:r[0] + r[1]]); return
        if b == 0x45:                                   # OS_Plot
            self.vdu += bytes([25, r[0] & 255]) + struct.pack('<hh', r[1], r[2]); return
        if b in (0x36, 0x37):                           # Remove/RestoreCursors
            return
        if b == OS_Byte:
            return self.os_byte(r)
        if b == OS_Word:
            blk = bytes(arm.mem[r[1]:r[1] + 10])
            if r[0] == 21 and blk[0] == 0:          # define pointer shape: +6 = data pointer
                self.event('OS_Word', r[0], blk[:6], int.from_bytes(blk[6:10], 'little'))
            else:
                self.event('OS_Word', r[0], blk[:8])
            return
        if b == 0x1C:                                   # OS_Mouse
            r[0], r[1], r[2], r[3] = 640, 512, 0, self.monotonic; return
        if b in (0x1F, 0x20):                           # OS_Claim / OS_Release
            self.event('OS_Claim' if b == 0x1F else 'OS_Release', r[0], r[1], r[2])
            if b == 0x1F: self.vectors[r[0]] = (r[1], r[2])
            return
        if b == 0x2C:                                   # OS_ReadEscapeState
            arm.flags &= ~C_; return
        if b == 0x31:                                   # OS_ReadVduVariables
            i, o = r[0], r[1]
            while True:
                v = arm.rw(i)
                if v == 0xFFFFFFFF: break
                arm.ww(o, self.vduvar(v)); i += 4; o += 4
            return
        if b == 0x35:                                   # OS_ReadModeVariable
            r[2] = {0: 0, 1: 319, 2: 255, 3: 255, 4: 1, 5: 1, 6: 320, 7: 81920, 9: 3,
                    11: 319, 12: 255}.get(r[1], 0)
            return
        if b == 0x2E:                                   # OS_SpriteOp
            return self.sprite_op(r)
        if b == OS_File:
            return self.os_file(r)
        if b == OS_CLI:
            self.event('OS_CLI', self.cstr(r[0]))
            if self.cstr(r[0]).upper().startswith(b'QUIT'):
                raise Stop('OS_CLI QUIT')
            return
        if b == 0x11:
            raise Stop('OS_Exit')
        if b == 0x2B:
            raise Stop('OS_GenerateError: %r' % self.cstr(r[0] + 4))
        if b == 0x42:                                   # OS_ReadMonotonicTime
            r[0] = arm.steps // 20000; return
        if 0xD0 <= b <= 0xE8:                           # OS_Convert*
            return self.convert(b, r)
        if (b & ~0x3F) == 0x40140 or (b & ~0x3F) == 0x40180 or (b & ~0x3F) == 0x401C0:
            nargs = {0x40140: 5, 0x40141: 1, 0x40142: 2, 0x40143: 1, 0x40180: 1, 0x40183: 2,
                     0x40184: 1, 0x40185: 2, 0x40189: 4, 0x4018A: 2}.get(b, 3)
            self.event('Sound_%x' % b, *r[:nargs])
            if b == 0x40183:                            # Sound_InstallVoice -> slot
                r[1] = self.voices; self.voices += 1
            return
        self.event('unhandled SWI %x' % n, r[0], r[1], r[2])
        if not x:
            raise Stop('unhandled SWI %x at %08x' % (n, pc))
        arm.flags |= V_

    def vduvar(self, v):
        return {148: SCREEN + self.bank * 0x14000, 149: SCREEN + self.bank * 0x14000,
                150: 81920, 0: 0, 1: 319, 2: 255, 3: 255, 4: 1, 5: 1, 6: 320, 7: 81920,
                9: 3, 11: 319, 12: 255}.get(v, 0)

    def os_byte(self, r):
        op = r[0] & 0xFF
        if op == 129:
            if r[2] == 0xFF and r[1] >= 0x80:           # INKEY(-n): scan one key
                k = 256 - r[1]
                r[1] = r[2] = 0xFF if self.pressed(k) else 0
            else:                                       # INKEY(t): timed read
                r[1], r[2] = 0, 0xFF
                for k, (s, e) in self.keys.items():
                    if s <= self.arm.steps < e and k == 99:
                        r[1], r[2] = 32, 0
            return
        if op == 121:                                   # keyboard scan
            k = r[1] ^ 0x80 if r[1] & 0x80 else None
            if k is not None:
                r[1] = 0xFF if self.pressed(k + 1) else 0
            else:
                r[1] = 0xFF
            return
        if op in (112, 113):                            # VDU/display bank
            if op == 112: self.bank = max(0, r[1] - 1) & 1
            else: self.display_bank = max(0, r[1] - 1) & 1
            self.event('OS_Byte', op, r[1]); return
        if op == 19:                                    # wait for vsync
            self.monotonic += 1; return
        if op == 135:
            r[2] = 13; return
        self.event('OS_Byte', op, r[1], r[2])

    def os_file(self, r):
        op = r[0] & 0xFF
        name = self.cstr(r[1])
        path = self.hostpath(name)
        self.event('OS_File', op, name)
        if op in (255, 12, 14, 16):
            if path is None:
                raise Stop('file not found %r' % name)
            data = open(path, 'rb').read()
            addr = r[2] if r[3] & 0xFF == 0 else None
            if addr is None:
                raise Stop('load at file address unsupported %r' % name)
            self.arm.mem[addr:addr + len(data)] = data
            r[4] = len(data); r[0] = 1
            return
        if op in (5, 17, 13, 15):
            if path is None:
                r[0] = 0; return
            r[0] = 1; r[2] = 0xFFFFFD00; r[3] = 0; r[4] = os.path.getsize(path); r[5] = 3
            return
        raise Stop('OS_File %d unsupported' % op)

    def sprite_op(self, r):
        op = r[0] & 0xFF
        self.event('OS_SpriteOp', r[0], r[1], r[2])
        if op == 10 or op == 11:                        # load / merge sprite file
            name = self.cstr(r[2])
            path = self.hostpath(name)
            if path is None:
                raise Stop('sprite file not found %r' % name)
            data = open(path, 'rb').read()
            area = r[1]
            if op == 10:
                self.arm.mem[area + 4:area + 4 + len(data)] = data
            return
        if op == 9:                                     # initialise area
            return

    def convert(self, b, r):
        v, buf, size = r[0], r[1], r[2]
        if b <= 0xD4:
            digits = {0xD0: 1, 0xD1: 2, 0xD2: 4, 0xD3: 6, 0xD4: 8}[b]
            s = ('%0*X' % (digits, v & ((1 << (4 * digits)) - 1))).encode()
        else:
            k = (b - 0xD5) % 4
            v &= (1 << (8 * (k + 1))) - 1 if k < 3 else 0xFFFFFFFF
            s = ('{:,}'.format(v) if b >= 0xE1 else str(v)).replace(',', ' ').encode()
        self.arm.mem[buf:buf + len(s) + 1] = s + b'\0'
        r[0], r[1], r[2] = buf, buf + len(s), size - len(s) - 1

    # ---- interrupts ---------------------------------------------------------------
    def call_vector(self, vec, regs):
        """Call a claimed vector handler as the OS would from an interrupt,
        then resume the interrupted code with its state intact."""
        if vec not in self.vectors:
            return
        code, ws = self.vectors[vec]
        a = self.arm
        saved = (list(a.r), a.flags)
        for k, v in regs.items():
            a.r[k] = v
        a.r[12] = ws
        a.r[14] = HANDLER_RET
        a.r[15] = code
        self.in_handler = True
        n = 0
        while a.r[15] != HANDLER_RET:
            a.step(); n += 1
            if n > 200000:
                raise Stop('handler for vector %x did not return' % vec)
        self.in_handler = False
        a.r[:], a.flags = saved

    def interrupts(self):
        a = self.arm
        if self.in_handler:
            return
        if a.steps >= self.next_tick:
            self.next_tick += TICK_STEPS
            self.call_vector(0x1C, {})                       # TickerV
        if a.steps >= self.next_vsync:
            self.next_vsync += VSYNC_STEPS
            self.monotonic += 2
            self.call_vector(0x10, {0: 4, 1: 0})             # EventV: VSync
        if self.clicks and a.steps >= self.clicks[0][0]:
            _, x, y, b = self.clicks.pop(0)
            self.event('mouse', x, y, b)
            self.call_vector(0x10, {0: 10, 1: x, 2: y, 3: b, 4: self.monotonic})

    def step(self):
        a = self.arm
        if a.r[15] == RETURN_TO_OS:
            raise Stop('returned to OS')
        self.interrupts()
        a.step()

    # ---- run ------------------------------------------------------------------
    def run(self, steps):
        try:
            for _ in range(steps):
                self.step()
        except Stop as e:
            self.done = str(e)
        return self.done


# Standard scenario: click PLAY on the menu, press Space at the sector briefing.
SCENARIO = dict(clicks=[(1500000, 140, 20, 4), (1520000, 140, 20, 0)],
                keys={99: (6500000, 6600000)})


def screenshot(ros, path, bank=None):
    """Save the displayed mode-13 bank as PNG using the default 256-colour palette."""
    from PIL import Image
    if bank is None:
        bank = ros.display_bank
    base = SCREEN
    pix = bytes(ros.arm.mem[base:base + 320 * 512])
    pal = []
    for c in range(256):
        t = c & 3
        r = ((c >> 4) & 1) << 3 | ((c >> 2) & 1) << 2 | t
        g = ((c >> 6) & 1) << 3 | ((c >> 5) & 1) << 2 | t
        b = ((c >> 7) & 1) << 3 | ((c >> 3) & 1) << 2 | t
        pal += [r * 17, g * 17, b * 17]
    im = Image.frombytes('P', (320, 512), pix)
    im.putpalette(pal)
    im.save(path)


if __name__ == '__main__':
    img = open(sys.argv[1], 'rb').read()
    n = int(float(sys.argv[2])) if len(sys.argv) > 2 else 2000000
    ros = RiscOS(img, 0x8000, keys={99: (int(3e6), int(3.2e6))}, verbose=True)
    import time
    t = time.time()
    r = ros.run(n)
    print('stopped:', r, 'pc=%08x steps=%d %.0f insn/s' % (ros.arm.r[15], ros.arm.steps,
          ros.arm.steps / (time.time() - t)))
    print('VDU bytes:', len(ros.vdu), repr(bytes(ros.vdu[:120])))
    screenshot(ros, 'shot.png')

