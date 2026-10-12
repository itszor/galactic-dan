#!/usr/bin/env python3
"""The decrypted game, game/GalacticDan_8000,ff8, from the disc in game/!Galactic.

The original disc's !Runimage is the protection's encrypted loader (with
DARE and the RayGun module); the game it decrypts is an absolute at &8000.
Discs without the protection have it already:
  - an unprotected disc (tools/mkunprotected.py's): !Runimage is the game;
  - the TOSEC dump, a cracked copy: DAN (a utility) is the game followed
    by a 96-byte stub of the crack's.
Either way the result is checked against the game's sha256.

Usage: game.py   (run from anywhere; reads and writes ../game)
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.join(HERE, '..', 'game')
APP = os.path.join(GAME, '!Galactic')
OUT = os.path.join(GAME, 'GalacticDan_8000,ff8')
LENGTH = 336624
SHA256 = '4a7ab27c756605108d286ff4dd3f15a23e5cbdd53dfe3d56f57e95a3957b7960'


def find(leaf):
    for f in os.listdir(APP):
        if f.split(',')[0].lower() == leaf.lower():
            return os.path.join(APP, f)
    return None


for leaf in ('!Runimage', 'DAN'):
    p = find(leaf)
    if p and os.path.getsize(p) >= LENGTH:
        d = open(p, 'rb').read()[:LENGTH]
        if hashlib.sha256(d).hexdigest() == SHA256:
            open(OUT, 'wb').write(d)
            print('%s: the game, from %s' % (os.path.basename(OUT), leaf))
            sys.exit(0)
sys.exit('game.py: no decrypted game on this disc (an original, protected disc needs '
         'its protection run first: see ../README)')
