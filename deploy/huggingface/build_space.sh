#!/bin/bash
# Puts together the files of the Hugging Face Space in one folder (default: build/space), ready to upload:
#   deploy/huggingface/build_space.sh [OUT_DIR]
# The Space gets its own copy of the package, so it builds without access to this repository.
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${1:-$ROOT/build/space}
rm -rf "$OUT" && mkdir -p "$OUT"
cp "$ROOT/deploy/huggingface/Dockerfile" "$OUT/Dockerfile"
cp "$ROOT/deploy/huggingface/SPACE_README.md" "$OUT/README.md"
cp "$ROOT/pyproject.toml" "$ROOT/LICENSE" "$OUT/"
cp -r "$ROOT/src" "$OUT/src"
find "$OUT" -name "__pycache__" -type d -prune -exec rm -rf {} +
echo "Space files in $OUT"
