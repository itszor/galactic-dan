/* Minimal RISC OS VDU driver and sprite plotting for mode 13 (320x256, 8bpp),
 * enough for Galactic Dan: MODE/CLS/CLG, COLOUR/GCOL/tints, windows, origin,
 * PLOT (move, lines, points, triangles, rectangles), and OS_SpriteOp
 * 9/10/24/28/34 on user sprite areas.
 */
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <stdlib.h>
#include "runtime.h"
#include "os.h"

static const uint8_t vdu_params[32] = {
    0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 1, 2, 5, 0, 0, 1, 9, 8, 5, 0, 0, 4, 4, 0, 2};

static uint8_t qbuf[16];
static int qwant, qhave;
static int gfg_col = 63, gbg_col = 0, gfg_act, gbg_act, tfg_col = 63, tbg_col = 0;
static int tint_tfg = 3, tint_tbg, tint_gfg = 3, tint_gbg;
static int ox, oy;                              /* graphics origin (OS units) */
int vdu_mode = 13;                              /* 13: 320x256, 15: 640x256 (both 8bpp) */
static int scr_w = 320, xeig = 2;
static int wl = 0, wb = 0, wr = 319, wt = 255;  /* graphics window (pixels, y down) */
static int cx, cy, px_, py_;                    /* last two points (absolute OS units) */
unsigned vdu_unhandled;

static uint8_t *bankmem(void) { return MEM + os_write_bank_addr(); }

/* GCOL colour number 0..63 + tint -> 8bpp pixel byte */
static uint8_t colour_byte(int c, int tint)
{
    c &= 63;
    return (uint8_t)(((c & 1) << 2) | (((c >> 1) & 1) << 4) | (((c >> 2) & 1) << 5) |
                     (((c >> 3) & 1) << 6) | (((c >> 4) & 1) << 3) | (((c >> 5) & 1) << 7) |
                     (tint & 3));
}

static void pset(int x, int y, int fg)          /* pixel coords, y down */
{
    if (x < wl || x > wr || y < wb || y > wt) return;
    uint8_t *p = bankmem() + y * scr_w + x;
    int act = fg ? gfg_act : gbg_act;
    uint8_t c = fg ? colour_byte(gfg_col, tint_gfg) : colour_byte(gbg_col, tint_gbg);
    switch (act & 7) {
    case 0: *p = c; break;
    case 1: *p |= c; break;
    case 2: *p &= c; break;
    case 3: *p ^= c; break;
    case 4: *p = ~*p; break;
    default: break;
    }
}
static int tox(int x) { return x >> xeig; }
static int toy(int y) { return 255 - (y >> 2); }

static void hline(int x0, int x1, int y, int fg)
{
    if (x0 > x1) { int t = x0; x0 = x1; x1 = t; }
    for (int x = x0; x <= x1; x++) pset(x, y, fg);
}

static void line(int x0, int y0, int x1, int y1, int fg)
{
    int dx = abs(x1 - x0), dy = -abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    int err = dx + dy;
    for (;;) {
        pset(x0, y0, fg);
        if (x0 == x1 && y0 == y1) break;
        int e2 = 2 * err;
        if (e2 >= dy) { err += dy; x0 += sx; }
        if (e2 <= dx) { err += dx; y0 += sy; }
    }
}

static void triangle(int x0, int y0, int x1, int y1, int x2, int y2, int fg)
{
    /* sort by y, scan-convert */
    int t;
    if (y0 > y1) { t = x0; x0 = x1; x1 = t; t = y0; y0 = y1; y1 = t; }
    if (y0 > y2) { t = x0; x0 = x2; x2 = t; t = y0; y0 = y2; y2 = t; }
    if (y1 > y2) { t = x1; x1 = x2; x2 = t; t = y1; y1 = y2; y2 = t; }
    for (int y = y0; y <= y2; y++) {
        int xa = y2 == y0 ? x0 : x0 + (x2 - x0) * (y - y0) / (y2 - y0), xb;
        if (y < y1) xb = y1 == y0 ? x0 : x0 + (x1 - x0) * (y - y0) / (y1 - y0);
        else xb = y2 == y1 ? x1 : x1 + (x2 - x1) * (y - y1) / (y2 - y1);
        hline(xa, xb, y, fg);
    }
}

static void plot(int k, int x, int y)
{
    if (!(k & 4)) { x += cx; y += cy; }          /* relative */
    else { x += ox; y += oy; }
    int mode = k & 3, grp = k & ~7;
    int fg = mode != 3;
    int saved = gfg_act;
    if (mode == 2) gfg_act = 4;                  /* inverse */
    if (mode != 0) {
        int X0 = tox(cx), Y0 = toy(cy), X1 = tox(x), Y1 = toy(y);
        if (grp <= 56) line(X0, Y0, X1, Y1, fg);
        else if (grp == 64) pset(X1, Y1, fg);
        else if (grp == 80) triangle(tox(px_), toy(py_), X0, Y0, X1, Y1, fg);
        else if (grp == 96) {
            int ya = Y0 < Y1 ? Y0 : Y1, yb = Y0 < Y1 ? Y1 : Y0;
            for (int yy = ya; yy <= yb; yy++) hline(X0, X1, yy, fg);
        } else vdu_unhandled++;
    }
    gfg_act = saved;
    px_ = cx; py_ = cy; cx = x; cy = y;
}

static int s16(int i) { return (int16_t)(qbuf[i] | qbuf[i + 1] << 8); }

static void clear_rect(int x0, int y0, int x1, int y1, uint8_t c)
{
    for (int y = y0; y <= y1; y++) memset(bankmem() + y * scr_w + x0, c, x1 - x0 + 1);
}

static void reset_windows(void) { wl = 0; wb = 0; wr = scr_w - 1; wt = 255; ox = oy = 0; }

static void do_vdu(int code)
{
    switch (code) {
    case 12: clear_rect(0, 0, scr_w - 1, 255, colour_byte(tbg_col, tint_tbg)); break;
    case 16: clear_rect(wl, wb, wr, wt, colour_byte(gbg_col, tint_gbg)); break;
    case 17: { int c = qbuf[0]; if (c & 128) tbg_col = c & 63; else tfg_col = c & 63; break; }
    case 18: { int a = qbuf[0], c = qbuf[1];
               if (c & 128) { gbg_act = a; gbg_col = c & 63; } else { gfg_act = a; gfg_col = c & 63; }
               break; }
    case 20: tfg_col = gfg_col = 63; tbg_col = gbg_col = 0; gfg_act = gbg_act = 0;
             tint_tfg = tint_gfg = 3; tint_tbg = tint_gbg = 0; break;
    case 22: vdu_mode = qbuf[0] & 127;
             if (vdu_mode == 15) { scr_w = 640; xeig = 1; } else { vdu_mode = 13; scr_w = 320; xeig = 2; }
             reset_windows(); tfg_col = gfg_col = 63; tbg_col = gbg_col = 0;
             tint_tfg = tint_gfg = 3; tint_tbg = tint_gbg = 0;
             memset(MEM + os_screen_base(), 0, 0x28000); cx = cy = px_ = py_ = 0; break;
    case 23:
        if (qbuf[0] == 17 && qbuf[1] <= 3) {     /* VDU 23,17,n,tint: set tint */
            int t = qbuf[2] >> 6;
            if (qbuf[1] == 0) tint_tfg = t; else if (qbuf[1] == 1) tint_tbg = t;
            else if (qbuf[1] == 2) tint_gfg = t; else tint_gbg = t;
        }
        break;
    case 24: {                                   /* graphics window, OS units incl. origin */
        int l = tox(s16(0) + ox), b = toy(s16(2) + oy), r = tox(s16(4) + ox), t = toy(s16(6) + oy);
        wl = l < 0 ? 0 : l; wr = r > scr_w - 1 ? scr_w - 1 : r; wb = t < 0 ? 0 : t; wt = b > 255 ? 255 : b;
        break;
    }
    case 25: plot(qbuf[0], s16(1), s16(3)); break;
    case 26: reset_windows(); cx = cy = px_ = py_ = 0; break;   /* also homes the graphics cursor */
    case 29: ox = s16(0); oy = s16(2); break;
    default: break;                              /* 19 palette, 28 text window, cursor ops... */
    }
}

void vdu_write(uint8_t c)
{
    if (qwant) {
        qbuf[qhave++] = c;
        if (qhave == qwant) { qwant = 0; do_vdu(qbuf[15]); }
        return;
    }
    if (c < 32) {
        if (vdu_params[c]) { qwant = vdu_params[c]; qhave = 0; qbuf[15] = c; }
        else do_vdu(c);
        return;
    }
    vdu_unhandled++;                             /* text output: not rendered (yet) */
}

/* ------------------------------------------------------------------ sprites */
static uint32_t rd32(uint32_t a) { return *(uint32_t *)(MEM + a); }

static uint32_t find_sprite(uint32_t area, uint32_t name)
{
    char want[13] = {0};
    for (int k = 0; k < 12; k++) {
        uint8_t c = MEM[name + k];
        if (c <= 32) break;
        want[k] = c;
    }
    uint32_t n = rd32(area + 4), s = area + rd32(area + 8);
    for (uint32_t k = 0; k < n; k++) {
        char nm[13] = {0};
        memcpy(nm, MEM + s + 4, 12);
        if (!strcasecmp(nm, want)) return s;
        s += rd32(s);
    }
    return 0;
}

static void put_sprite(uint32_t s, int x, int y, int action)
{
    int wwords = rd32(s + 16) + 1, h = rd32(s + 20) + 1;
    int first = rd32(s + 24), last = rd32(s + 28);
    uint32_t img = s + rd32(s + 32), mask = s + rd32(s + 36);
    int hasmask = mask != img && (action & 8);
    int wpx = (wwords * 32 - first - (31 - last)) / 8;
    int left = tox(x + ox), top = toy(y + oy) - (h - 1);
    for (int r = 0; r < h; r++) {
        int yy = top + r;
        if (yy < wb || yy > wt) continue;
        const uint8_t *src = MEM + img + r * wwords * 4 + first / 8;
        const uint8_t *msk = MEM + mask + r * wwords * 4 + first / 8;
        uint8_t *dst = bankmem() + yy * scr_w;
        for (int c = 0; c < wpx; c++) {
            int xx = left + c;
            if (xx < wl || xx > wr) continue;
            if (hasmask && !msk[c]) continue;
            switch (action & 7) {
            case 0: dst[xx] = src[c]; break;
            case 1: dst[xx] |= src[c]; break;
            case 2: dst[xx] &= src[c]; break;
            case 3: dst[xx] ^= src[c]; break;
            case 4: dst[xx] = ~dst[xx]; break;
            default: break;
            }
        }
    }
}

/* returns 1 if handled */
int sprite_op_full(void)
{
    uint32_t op = R[0] & 0xFF, area = R[1];
    uint32_t spr = 0;
    if ((R[0] & 0x300) == 0x100) spr = (op >= 24) ? find_sprite(area, R[2]) : 0;
    else if ((R[0] & 0x300) == 0x200) spr = R[2];
    if (getenv("RECOMP_SPRDEBUG"))
        fprintf(stderr, "SpriteOp %x area %x spr %x r3 %d r4 %d r5 %x cursor %d,%d origin %d,%d bank %x\n",
                R[0], area, spr, (int)R[3], (int)R[4], R[5], cx, cy, ox, oy, os_write_bank_addr());
    switch (op) {
    case 9:                                      /* initialise area */
        *(uint32_t *)(MEM + area + 4) = 0;
        *(uint32_t *)(MEM + area + 8) = 16;
        *(uint32_t *)(MEM + area + 12) = 16;
        return 1;
    case 24:                                     /* select sprite */
        if (spr) R[2] = spr;
        return 1;
    case 28:                                     /* put sprite at graphics cursor */
        if (spr) put_sprite(spr, cx - ox, cy - oy, R[5]);
        return 1;
    case 34:                                     /* put sprite at user coordinates */
        if (spr) put_sprite(spr, (int32_t)R[3], (int32_t)R[4], R[5]);
        return 1;
    default:
        return 0;
    }
}
