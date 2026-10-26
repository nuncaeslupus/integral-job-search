#!/usr/bin/env bash
# Record both sides of a video/phone call on Linux (PipeWire) until Ctrl-C:
# the mic (the candidate) and the system output (the interviewer), then mix them
# into one call.wav that transcribe.sh / diarize.sh take like any other recording.
# ponytail: one mixed track, so diarization still separates the voices; the two
# per-side tracks are kept and could each be transcribed alone to skip diarization.
set -euo pipefail
OUT="${1:?usage: record.sh <out-dir>}"
mkdir -p "$OUT"
pw-record --rate 16000 --channels 1 "$OUT/mic.wav" & MIC=$!
pw-record --rate 16000 --channels 1 -P '{ stream.capture.sink=true }' "$OUT/system.wav" & SYS=$!
# Background children of a non-interactive shell ignore SIGINT, so Ctrl-C alone
# would never stop them: forward it as TERM, which pw-record finalises cleanly.
trap 'kill -TERM "$MIC" "$SYS" 2>/dev/null || true' INT TERM
echo "Recording to $OUT — press Ctrl-C to stop." >&2
wait || true
wait || true
python3 "$(dirname "$0")/mix.py" "$OUT/mic.wav" "$OUT/system.wav" "$OUT/call.wav"
echo "Done: $OUT/call.wav" >&2
