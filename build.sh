#!/bin/sh
# Build Galactic Dan from your own copy of the game:
#     ./build.sh "Galactic Dan (19xx)(Fourth Dimension).adf"     (the TOSEC dump; or an unprotected disc made from an original)
# then: cd recomp && ./galdan
# The steps are recipe.json's "build", run by SuperSpider's tools/weave.py.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
SUPERSPIDER="${SUPERSPIDER:-$HOME/stuff/superspider}"
[ $# -gt 0 ] || { echo "usage: $0 DISC.adf" >&2; exit 2; }
(cd "$SUPERSPIDER" && dune build)
WEAVE_RECIPES="$HERE" exec python3 -I "$SUPERSPIDER/tools/weave.py" build "$@"
