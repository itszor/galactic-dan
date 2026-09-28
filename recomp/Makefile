# Static recompilation of Galactic Dan
CC      ?= gcc
CFLAGS  ?= -O2 -g -w -fno-strict-aliasing $(if $(TRACE),-DRECOMP_TRACE)
GEN     := $(wildcard gen/code*.c) gen/entries.c
OBJ     := $(GEN:.c=.o) runtime.o vdu.o display.o
LIBS    := $(shell pkg-config --libs sdl3)
SDLCF   := $(shell pkg-config --cflags sdl3)

galdan: $(OBJ)
	$(CC) $(CFLAGS) -o $@ $(OBJ) $(LIBS)

gen/%.o: gen/%.c runtime.h gen/galdan.h
	$(CC) $(CFLAGS) -I. -c -o $@ $<

runtime.o: runtime.c runtime.h os.h
	$(CC) $(CFLAGS) -c -o $@ $<

vdu.o: vdu.c runtime.h os.h
	$(CC) $(CFLAGS) -c -o $@ $<

display.o: display.c os.h
	$(CC) $(CFLAGS) $(SDLCF) -c -o $@ $<

regen:
	python3 gen_c.py

clean:
	rm -f gen/*.o runtime.o vdu.o display.o galdan
