/* Galactic Dan (RISC OS, 1992): what libroger needs to know about the game. */
#include <roger.h>

extern const struct roger_image recomp_image;      /* gen/entries.c (gen_c.py) */

static const char *const prefixes[] = {"<Obey$Dir>.", NULL};
static const char *const loaders[] = {"!TitlePic", NULL};   /* !Run shows it before !RunImage */

/* the deterministic headless scenario (asm/emu.py SCENARIO): click at the
 * title screen, then press Space */
static const struct roger_click clicks[] = {{1500000, 140, 20, 4}, {1520000, 140, 20, 0}};
static const struct roger_key keys[] = {{99, 6500000, 6600000}};

static const struct roger_config config = {
    .title = "Galactic Dan (recompiled)",
    .image_path = "../extracted/GalacticDan_8000,ff8",
    .image = &recomp_image,
    .loader_programs = loaders,
    .appdir = "../extracted/!Galactic",
    .dir_prefixes = prefixes,
    .initial_mode = 13,
    .wimpslot = 640 * 1024,              /* !Run: wimpslot -min 640K -max 640K */
    .stack = 0xA8000,
    .screen_base = 0x1B80000,
    .relative_mouse = 1,                  /* steering: the game re-centres the pointer */
    .clicks = clicks, .nclicks = 2,
    .keys = keys, .nkeys = 1,
    .interpret_gaps = 1,                  /* the translation came from a partial analysis */
};

int main(int argc, char **argv) { roger_main(argc, argv, &config); }
