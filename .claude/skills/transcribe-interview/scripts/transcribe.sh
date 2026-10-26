#!/usr/bin/env bash
# Transcription env — the pins ARE the lockfile. ctranslate2 does not bundle CUDA,
# so resolve the wheels' libcublas/libcudnn and export LD_LIBRARY_PATH before the run.
set -euo pipefail
cd "$(dirname "$0")"
AUDIO="$1"; OUT="$2"
UV="uv run --python 3.12 \
  --with faster-whisper==1.2.1 \
  --with av==13.1.0 \
  --with ctranslate2==4.8.4 \
  --with nvidia-cublas-cu12 \
  --with nvidia-cudnn-cu12"
LIBS=$($UV python -c 'import os,nvidia;b=list(nvidia.__path__)[0];print(":".join(os.path.join(b,p,"lib") for p in ("cublas","cudnn")))')
echo "LD_LIBRARY_PATH libs: $LIBS" >&2
LD_LIBRARY_PATH="$LIBS:${LD_LIBRARY_PATH:-}" $UV python transcribe.py "$AUDIO" "$OUT"
