#!/usr/bin/env bash
# Download the Essentia graphs and their label metadata into $1 (default /models).
set -euo pipefail

TARGET="${1:-/models}"
BASE="https://essentia.upf.edu/models"

mkdir -p "$TARGET"

fetch() {
  local url="$1"
  local name="$2"
  for ext in pb json; do
    echo "fetching ${name}.${ext}"
    curl -fsSL "${url}/${name}.${ext}" -o "${TARGET}/${name}.${ext}"
  done
}

fetch "${BASE}/feature-extractors/discogs-effnet" "discogs-effnet-bs64-1"
fetch "${BASE}/classification-heads/genre_discogs400" "genre_discogs400-discogs-effnet-1"
fetch "${BASE}/classification-heads/voice_instrumental" "voice_instrumental-discogs-effnet-1"

for mood in happy sad relaxed aggressive party; do
  fetch "${BASE}/classification-heads/mood_${mood}" "mood_${mood}-discogs-effnet-1"
done

echo "models in ${TARGET}:"
ls -1 "${TARGET}"
