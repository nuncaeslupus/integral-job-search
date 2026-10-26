#!/usr/bin/env python3
"""Transcribe an interview recording with faster-whisper on the GPU.

ponytail: one pass, auto language. Heavy ES/EN code-switching is NOT fully
solved (Whisper fixes one language per window); upgrade path = per-segment
language detection if the English parts still garble. Good enough for review.
"""
import sys
from pathlib import Path

from faster_whisper import WhisperModel

audio = sys.argv[1]
out_txt = Path(sys.argv[2])
out_srt = out_txt.with_suffix(".srt")

# 8GB GPU: large-v3 in float16 fits (~5GB). Fall back to int8_float16 on OOM.
try:
    model = WhisperModel("large-v3", device="cuda", compute_type="float16")
except Exception as e:  # noqa: BLE001
    print(f"float16 failed ({e}); retrying int8_float16", file=sys.stderr)
    model = WhisperModel("large-v3", device="cuda", compute_type="int8_float16")

# language=None -> auto-detect; vad_filter trims silence and helps segmenting.
segments, info = model.transcribe(audio, language=None, vad_filter=True, beam_size=5)
print(f"detected language: {info.language} (p={info.language_probability:.2f})",
      file=sys.stderr)


def ts(t: float) -> str:
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


lines, srt = [], []
for i, seg in enumerate(segments, 1):
    stamp = f"[{ts(seg.start)[:-4]}]"
    text = seg.text.strip()
    lines.append(f"{stamp} {text}")
    srt.append(f"{i}\n{ts(seg.start)} --> {ts(seg.end)}\n{text}\n")
    print(f"{stamp} {text}", flush=True)

out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
out_srt.write_text("\n".join(srt), encoding="utf-8")
print(f"\nwrote {out_txt}\nwrote {out_srt}", file=sys.stderr)
