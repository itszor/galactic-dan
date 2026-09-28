#!/bin/sh
# Regenerate galdan.s from the analysis and check it rebuilds the original exactly.
#   ./regen.sh                    normal source
#   ./regen.sh --pad=ADDR:N,...   relocation-test build into ../asm_shifted
set -e
cd "$(dirname "$0")/../ghidra"
OUT=../asm
case "$1" in --pad=*) OUT=../asm_shifted ;; esac
python3 gen_asm.py ../extracted/GalacticDan_8000,ff8 8000 galdan.json $OUT \
    --dyn=../asm/dyn_menu.json,../asm/dyn_game.json --notes=../asm/notes.json "$@"
