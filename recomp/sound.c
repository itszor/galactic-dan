/* High-level emulation of the RISC OS sound system for Galactic Dan.
 *
 * The game's 13 voice generators are one-shot sample players sharing one
 * fill routine (&261EC): position is 24.8 fixed point, advanced per output
 * sample by the channel's pitch increment; bytes are VIDC 8-bit logarithmic
 * (bit 0 sign, bits 7..1 magnitude); amplitude is applied in the log domain
 * as  magnitude - (127 - amp).  Rather than run that code into VIDC-format
 * buffers, we read each voice's sample start/length from its GateOn code and
 * mix in C: decode to 16-bit linear, pan per channel (Sound_Stereo), 48 kHz.
 *
 * Pitch: the standard oscillator adds a 16-bit increment into the top of a
 * 32-bit phase accumulator; &4000 is middle C (261.63 Hz) for a 256-byte
 * cycle, so a sample voice stepping by increment/256 bytes plays its data at
 *   256 * 261.63 * 2^((pitch - &4000) / 4096) * 48 / period  Hz
 * where period is the Sound_Configure sample period (the pitch table is for
 * the default 48us).  The game uses 96us, so &2500 -> 10.4 kHz: STEP1 (5000
 * bytes, duration 0.5 s) then lasts 0.48 s, LETSGO 0.98 s of its 1.3 s.
 */
#include <SDL3/SDL.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <math.h>
#include "runtime.h"
#include "os.h"

#define RATE     48000
#define NCHAN    8
#define MAXVOICE 32

static struct voice { uint32_t header, start, len; char name[16]; } voices[MAXVOICE + 1];
static struct chan {
    int voice, amp, pan, active;
    uint64_t pos, step, end;            /* 32.32 source-sample position */
    int64_t left;                       /* output frames until GateOff, -1 = forever */
} ch[NCHAN + 1];
static int16_t linear[128];             /* log magnitude -> linear */
static int master = 127, enabled = 1, ready;
static int period_us = 48;              /* Sound_Configure sample period per channel */
static SDL_AudioStream *stream;
static FILE *wav;
static uint32_t wav_frames;
static uint32_t shared_fill;

static void lock(void) { if (stream) SDL_LockAudioStream(stream); }
static void unlock(void) { if (stream) SDL_UnlockAudioStream(stream); }

static void build_tables(void)
{
    /* VIDC logarithmic format: 3-bit segment, 4-bit step (mu-law form, 0 = silence) */
    for (int m = 0; m < 128; m++) {
        int seg = m >> 4, step = m & 15;
        int lin = ((2 * step + 33) << seg) - 33;       /* 0 .. 8031 */
        linear[m] = (int16_t)(lin * 4);                /* ~ full 16-bit scale */
    }
}

static void mix(int16_t *out, int frames)
{
    for (int f = 0; f < frames; f++) {
        int l = 0, r = 0;
        for (int c = 1; c <= NCHAN; c++) {
            struct chan *k = &ch[c];
            if (!k->active) continue;
            if (k->pos >= k->end || k->left == 0) { k->active = 0; continue; }
            uint8_t b = MEM[voices[k->voice].start + (uint32_t)(k->pos >> 32)];
            int mag = (b >> 1) - (127 - k->amp);
            int v = mag > 0 ? linear[mag] : 0;
            if (b & 1) v = -v;
            v = v * master / 127 / 2;                  /* headroom for several channels */
            int pl = k->pan <= 0 ? 127 : 127 - k->pan, pr = k->pan >= 0 ? 127 : 127 + k->pan;
            l += v * pl / 127;
            r += v * pr / 127;
            k->pos += k->step;
            if (k->left > 0) k->left--;
        }
        out[2 * f] = (int16_t)(l > 32767 ? 32767 : l < -32768 ? -32768 : l);
        out[2 * f + 1] = (int16_t)(r > 32767 ? 32767 : r < -32768 ? -32768 : r);
    }
}

static void SDLCALL feed(void *ud, SDL_AudioStream *s, int additional, int total)
{
    (void)ud; (void)total;
    int16_t buf[2048];
    while (additional > 0) {
        int frames = additional / 4 < 1024 ? additional / 4 : 1024;
        if (frames <= 0) break;
        mix(buf, frames);                              /* stream lock is held here */
        SDL_PutAudioStreamData(s, buf, frames * 4);
        additional -= frames * 4;
    }
}

int sound_init_device(void)
{
    build_tables();
    if (!SDL_InitSubSystem(SDL_INIT_AUDIO)) { SDL_Log("audio: %s", SDL_GetError()); return 0; }
    SDL_AudioSpec spec = {SDL_AUDIO_S16, 2, RATE};
    stream = SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, &spec, feed, NULL);
    if (!stream) { SDL_Log("audio: %s", SDL_GetError()); return 0; }
    SDL_ResumeAudioStreamDevice(stream);
    ready = 1;
    return 1;
}

static void wav_header(void)
{
    uint32_t data = wav_frames * 4;
    uint8_t h[44];
    memcpy(h, "RIFF", 4); *(uint32_t *)(h + 4) = 36 + data; memcpy(h + 8, "WAVEfmt ", 8);
    *(uint32_t *)(h + 16) = 16; *(uint16_t *)(h + 20) = 1; *(uint16_t *)(h + 22) = 2;
    *(uint32_t *)(h + 24) = RATE; *(uint32_t *)(h + 28) = RATE * 4; *(uint16_t *)(h + 32) = 4;
    *(uint16_t *)(h + 34) = 16; memcpy(h + 36, "data", 4); *(uint32_t *)(h + 40) = data;
    fseek(wav, 0, SEEK_SET);
    fwrite(h, 1, 44, wav);
    fseek(wav, 0, SEEK_END);
}

int sound_init_wav(const char *path)
{
    build_tables();
    wav = fopen(path, "wb");
    if (!wav) return 0;
    wav_header();
    ready = 1;
    return 1;
}

/* headless: render `frames` of audio in step with emulated time */
void sound_render(int frames)
{
    if (!wav) return;
    int16_t buf[2048];
    while (frames > 0) {
        int n = frames < 1024 ? frames : 1024;
        mix(buf, n);
        fwrite(buf, 4, n, wav);
        wav_frames += n;
        frames -= n;
    }
}

void sound_close(void)
{
    if (wav) { wav_header(); fclose(wav); wav = 0; }
    if (stream) { SDL_DestroyAudioStream(stream); stream = 0; }
}

/* ---------------------------------------------------------------- voices */
static uint32_t branch_target(uint32_t a)
{
    uint32_t w = RD32(a);
    int32_t off = w & 0xFFFFFF;
    if (off & 0x800000) off -= 0x1000000;
    return (a + 8 + off * 4) & 0x3FFFFFC;
}

static void install_voice(uint32_t header, uint32_t slot)
{
    if (slot < 1 || slot > MAXVOICE) return;
    struct voice *v = &voices[slot];
    v->header = header;
    uint32_t name = header + RD32(header + 28);
    int k;
    for (k = 0; k < 15 && MEM[name + k] > 32; k++) v->name[k] = MEM[name + k];
    v->name[k] = 0;
    /* GateOn: find the values stored to SCCB+16 (sample start) and +28 (length) */
    uint32_t go = branch_target(header + 8), val[16] = {0};
    for (uint32_t a = go; a < go + 64; a += 4) {
        uint32_t w = RD32(a);
        if ((w & 0x0F7F0000) == 0x051F0000) {                     /* ldr rX, [pc, #imm] */
            uint32_t off = w & 0xFFF, lit = a + 8 + ((w & (1 << 23)) ? off : -off);
            val[(w >> 12) & 15] = RD32(lit);
        } else if ((w & 0x0FFFF000) == 0x03A00000)               /* mov rX, #imm (small) */
            val[(w >> 12) & 15] = w & 0xFF;
        else if ((w & 0x0FFF0FFF) == 0x05890010) v->start = val[(w >> 12) & 15];
        else if ((w & 0x0FFF0FFF) == 0x0589001C) v->len = val[(w >> 12) & 15];
        else if ((w >> 24) == 0xEA) break;                       /* b fill */
    }
    uint32_t fill = branch_target(header);
    if (!shared_fill) shared_fill = fill;
    if (fill != shared_fill || !v->start || !v->len)
        fprintf(stderr, "sound: voice %s at %x is not a plain sample player; ignored\n", v->name, header);
    if (fill != shared_fill) v->len = 0;
}

static int find_voice(uint32_t nameptr)
{
    char want[16];
    int k;
    for (k = 0; k < 15 && MEM[nameptr + k] > 32; k++) want[k] = MEM[nameptr + k];
    want[k] = 0;
    for (int i = 1; i <= MAXVOICE; i++)
        if (voices[i].header && !strcasecmp(voices[i].name, want)) return i;
    return 0;
}

static void control(int c, int32_t amp, uint32_t pitch, uint32_t dur)
{
    if (c < 1 || c > NCHAN) return;
    struct chan *k = &ch[c];
    int logamp;
    if (amp >= 0x100) logamp = amp & 0x7F;
    else if (amp <= 0 && amp >= -15) logamp = amp == 0 ? 0 : 0x7F - (15 + amp) * 4;   /* BBC-style -15..0 */
    else return;
    if (amp >= 0x100 && (amp & 0x80)) { k->amp = logamp; return; }   /* smooth update, no retrigger */
    if (!enabled || !k->voice || !voices[k->voice].len) { k->active = 0; return; }
    double p = pitch >= 0x100 ? (double)(pitch & 0x7FFF)
                              : 0x4000 + ((double)pitch - 53) * 4096.0 / 48.0;   /* BBC pitch */
    /* The pitch table is for the default 48us period: at other periods the
       same increments are applied per (slower or faster) channel sample. */
    double src = 256.0 * 261.63 * pow(2.0, (p - 0x4000) / 4096.0) * 48.0 / period_us;
    k->amp = logamp;
    k->pos = 0;
    k->step = (uint64_t)(src / RATE * 4294967296.0);
    k->end = (uint64_t)voices[k->voice].len << 32;
    k->left = dur >= 255 ? -1 : (int64_t)dur * RATE / 20;
    k->active = logamp > 0;
}

/* called for every Sound SWI (after the event log); b has the X bit cleared */
void sound_swi(uint32_t b)
{
    if (!ready) return;
    lock();
    switch (b) {
    case 0x40140: if (R[2]) period_us = R[2]; break;        /* Sound_Configure */
    case 0x40141: if (R[0] == 1) enabled = 0; else if (R[0] == 2) enabled = 1; break;
    case 0x40142: if (R[0] >= 1 && R[0] <= NCHAN && (int32_t)R[1] != -128) {
                      int p = (int32_t)R[1]; ch[R[0]].pan = p < -127 ? -127 : p > 127 ? 127 : p; }
                  break;
    case 0x40180: if (R[0] >= 1 && R[0] <= 127) master = R[0]; break;
    case 0x40183: install_voice(R[0], R[1]); break;
    case 0x40185: if (R[0] >= 1 && R[0] <= NCHAN) ch[R[0]].voice = R[1] <= MAXVOICE ? R[1] : 0; break;
    case 0x4018A: if (R[0] >= 1 && R[0] <= NCHAN) ch[R[0]].voice = find_voice(R[1]); break;
    case 0x40189: control(R[0], (int32_t)R[1], R[2], R[3]); break;
    case 0x40186: control(R[0] & 0xFFFF, (int16_t)(R[0] >> 16), R[1] & 0xFFFF, R[1] >> 16); break;
    default: break;
    }
    unlock();
}
