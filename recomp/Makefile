# Static recompilation of Galactic Dan: the translated program (gen/, from
# gen_c.py) and game.c, linked with libroger (the RISC OS runtime).
ROGER   ?= $(HOME)/stuff/libroger
CC      ?= gcc
CFLAGS  ?= -O2 -g -w -fno-strict-aliasing $(if $(TRACE),-DRECOMP_TRACE)
GEN     := $(wildcard gen/code*.c) gen/entries.c
OBJ     := $(GEN:.c=.o) game.o
LIBS    := $(shell pkg-config --libs sdl3) -lm -lpthread
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
# ../superspider/out/, then gen_c.py. ../superspider/galdan.roots adds entry
# points to the analysis: "make roots" merges the gap entries a --trace-gaps
# run logged (untranslated.log, or LOG=...) into it, so the next "make regen"
# translates them.
SS      ?= $(HOME)/stuff/superspider
SSBIN   := $(SS)/_build/default/bin/main.exe
SSD     := ../superspider
GALDAN  := ../extracted/GalacticDan_8000,ff8
LOG     ?= untranslated.log

regen:
	cd $(SS) && dune build
	mkdir -p $(SSD)/out/galdan
	$(SSBIN) s1b $(GALDAN) 8000 --roots $(SSD)/galdan.roots -o $(SSD)/out/galdan.ss.json
	python3 $(SS)/phase6/ss_to_spider.py $(SSD)/out/galdan.ss.json $(GALDAN) 8000 \
	    $(SSD)/out/galdan.json $(SSD)/out/galdan ../ghidra
	rm -rf gen
	python3 gen_c.py --json=$(SSD)/out/galdan.json --tsvdir=$(SSD)/out/galdan --dyn=

roots:
	python3 $(SS)/tools/gap_roots.py $(GALDAN) 8000 $(SSD)/galdan.roots $(LOG)

# The previous analysis: the spider + Ghidra (../ghidra/run_ghidra.sh) and
# the run-time facts in ../asm/dyn_*.json.
regen-ghidra:
	python3 gen_c.py

clean:
	rm -f gen/*.o game.o galdan galdan-cov *.cov.o gen/*.cov.o

.PHONY: FORCE cov regen regen-ghidra roots clean
