# Static recompilation of Galactic Dan: the translated program (gen/, from
# superspider analyse/gen) and game.c, linked with libroger (the RISC OS runtime).
ROGER   ?= $(HOME)/stuff/libroger
CC      ?= gcc
CFLAGS  ?= -O2 -g -w -fno-strict-aliasing $(if $(TRACE),-DRECOMP_TRACE)
GEN     := $(wildcard gen/code*.c) gen/entries.c
OBJ     := $(GEN:.c=.o) game.o
LIBS    := $(shell pkg-config --libs sdl3) -ljpeg -lm -lpthread
INC     := -I$(ROGER)/include

galdan: $(OBJ) $(ROGER)/libroger.a
	$(CC) $(CFLAGS) -o $@ $(OBJ) $(ROGER)/libroger.a $(LIBS)

$(ROGER)/libroger.a: FORCE
	$(MAKE) -C $(ROGER) libroger.a

%.o: %.c $(ROGER)/include/roger.h $(ROGER)/include/roger_cpu.h
	$(CC) $(CFLAGS) $(INC) -c -o $@ $<

# Coverage build for SuperSpider (~/stuff/superspider/PLAN.md, phase 0):
# "make cov" builds galdan-cov from separate *.cov.o objects (the normal
# build is untouched); it writes $$RECOMP_COV (default cov.out) at exit.
COVDIR  ?= $(HOME)/stuff/superspider/phase0/cov
COVOBJ  := $(OBJ:.o=.cov.o) cov.cov.o

cov: galdan-cov

galdan-cov: $(COVOBJ) FORCE
	$(MAKE) -C $(ROGER) cov COV=$(COVDIR)
	$(CC) $(CFLAGS) -o $@ $(COVOBJ) $(ROGER)/libroger-cov.a $(LIBS)

%.cov.o: %.c $(ROGER)/include/roger_cpu.h $(COVDIR)/cov.h
	$(CC) $(CFLAGS) -DRECOMP_COV $(INC) -I$(COVDIR) -c -o $@ $<

cov.cov.o: $(COVDIR)/cov.c $(COVDIR)/cov.h
	$(CC) $(CFLAGS) -c -o $@ $<

# Code/data analysis: SuperSpider (~/stuff/superspider, no Ghidra), into
# ../superspider/out/galdan.json, then superspider gen. ../superspider/galdan.roots adds entry
# points to the analysis: "make roots" merges the gap entries a --trace-gaps
# run logged (untranslated.log, or LOG=...) into it, so the next "make regen"
# translates them.
SS      ?= $(HOME)/stuff/superspider
SSBIN   := $(SS)/_build/default/bin/main.exe
SSD     := ../superspider
GALDAN  := ../game/GalacticDan_8000,ff8
LOG     ?= untranslated.log

regen:
	cd $(SS) && dune build
	mkdir -p $(SSD)/out
	$(SSBIN) analyse $(GALDAN) 8000 --full --roots $(SSD)/galdan.roots -o $(SSD)/out/galdan.json
	rm -rf gen
	$(SSBIN) gen $(GALDAN) 8000 $(SSD)/out/galdan.json --c gen --leaders=dispatch --header=galdan --covtag=G

roots:
	python3 $(SS)/tools/gap_roots.py $(GALDAN) 8000 $(SSD)/galdan.roots $(LOG)

clean:
	rm -f gen/*.o game.o galdan galdan-cov *.cov.o gen/*.cov.o

.PHONY: FORCE cov regen roots clean
