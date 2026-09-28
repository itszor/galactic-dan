#!/bin/sh
# Reassemble galdan.s and compare with the original image.
set -e
cd "$(dirname "$0")"
arm-none-eabi-as -march=armv2a -o galdan.o galdan.s
arm-none-eabi-ld -Ttext=0x8000 -e _start --no-warn-rwx-segments -o galdan.elf galdan.o
arm-none-eabi-objcopy -O binary -j .text galdan.elf GalacticDan,ff8
cmp GalacticDan,ff8 "/home/jules/games/galactic dan/extracted/GalacticDan_8000,ff8" && echo "IDENTICAL to original"
