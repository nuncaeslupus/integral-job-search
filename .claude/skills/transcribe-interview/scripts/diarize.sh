#!/usr/bin/env bash
# Diarization env — the pins ARE the lockfile, and they are a different, CONFLICTING
# set from transcribe.sh (pyannote 3.1 needs an OLD huggingface_hub; faster-whisper a
# new one), which is exactly why the two steps run in two separate ephemeral envs.
# torch 2.7.1's wheel bundles its own CUDA, so no LD_LIBRARY_PATH dance here.
set -euo pipefail
AUDIO="$1"; SRT="$2"; OUT="$3"
uv run --python 3.12 \
  --with "pyannote.audio==3.1.1" \
  --with "huggingface_hub==0.25.2" \
  --with "torch==2.7.1" \
  --with "torchaudio==2.7.1" \
  --with "numpy<2" \
  --with "av==13.1.0" \
  python "$(dirname "$0")/diarize.py" "$AUDIO" "$SRT" "$OUT"
