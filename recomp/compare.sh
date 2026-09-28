#!/bin/sh
# compare.sh N : run reference emulator and recompiled binary to N instructions, diff outputs
N=${1:-2e6}
cd "$(dirname "$0")"
python3 ref_run.py $N ref &
( time ./galdan --limit=$N --out=rec ) 2>&1 | grep -v '^$'
wait
for x in events vdu screen regs; do
  if cmp -s ref.$x rec.$x; then echo "$x: identical"; else echo "$x: DIFFERENT"; fi
done
