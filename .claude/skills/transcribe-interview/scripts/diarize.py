#!/usr/bin/env python3
"""Diarize an interview and merge speakers with an existing Whisper .srt.

Decode the audio to a 16k mono array with PyAV (no system ffmpeg needed), hand
it to pyannote as an in-memory waveform, then assign each srt segment the
speaker with the most time overlap and collapse consecutive same-speaker
segments into turns. Speakers stay SPEAKER_00/01 here; naming is the cleanup
pass's job (see SKILL.md).
"""
import re
import sys
from pathlib import Path

import av
import numpy as np
import torch

# ponytail: torch>=2.6 defaults weights_only=True; the pyannote 3.1 checkpoint is an
# official, trusted file that pickles TorchVersion etc. Force the old behaviour.
_orig_load = torch.load
torch.load = lambda *a, **k: _orig_load(*a, **{**k, "weights_only": False})

from pyannote.audio import Pipeline  # noqa: E402

audio_path = sys.argv[1]
srt_path = Path(sys.argv[2])
out_path = Path(sys.argv[3])


def load_audio(path: str, sr: int = 16000) -> np.ndarray:
    """Decode any container to mono float32 at sr via PyAV — no system ffmpeg."""
    container = av.open(path)
    resampler = av.AudioResampler(format="s16", layout="mono", rate=sr)
    chunks = []
    for frame in container.decode(audio=0):
        for rf in resampler.resample(frame):
            chunks.append(rf.to_ndarray().reshape(-1))
    return np.concatenate(chunks).astype(np.float32) / 32768.0


# token is read by huggingface_hub from ~/.cache/huggingface/token (or $HF_TOKEN)
pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
pipeline.to(torch.device("cuda"))

wav = load_audio(audio_path)
diar = pipeline({"waveform": torch.from_numpy(wav)[None, :], "sample_rate": 16000})
turns = [(t.start, t.end, spk) for t, _, spk in diar.itertracks(yield_label=True)]
print(f"diarization: {len(turns)} turns, speakers={sorted({s for *_, s in turns})}",
      file=sys.stderr)


def to_sec(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


# parse srt -> [(start, end, text)]
blocks = re.split(r"\n\s*\n", srt_path.read_text(encoding="utf-8").strip())
segs = []
for b in blocks:
    lines = b.splitlines()
    if len(lines) < 2:
        continue
    m = re.match(r"(\S+)\s*-->\s*(\S+)", lines[1])
    if not m:
        continue
    segs.append((to_sec(m.group(1)), to_sec(m.group(2)), " ".join(lines[2:]).strip()))


def speaker_for(s: float, e: float) -> str:
    best, best_ov = "SPEAKER_?", 0.0
    for ts, te, spk in turns:
        ov = min(e, te) - max(s, ts)
        if ov > best_ov:
            best_ov, best = ov, spk
    return best


# assign + collapse consecutive same-speaker segments into turns
dialog, cur_spk, buf, buf_start = [], None, [], 0.0
for s, e, text in segs:
    spk = speaker_for(s, e)
    if spk != cur_spk and buf:
        mm, ss = divmod(int(buf_start), 60)
        dialog.append(f"[{mm:02d}:{ss:02d}] {cur_spk}: {' '.join(buf)}")
        buf = []
    if not buf:
        buf_start = s
    cur_spk = spk
    buf.append(text)
if buf:
    mm, ss = divmod(int(buf_start), 60)
    dialog.append(f"[{mm:02d}:{ss:02d}] {cur_spk}: {' '.join(buf)}")

out_path.write_text("\n\n".join(dialog) + "\n", encoding="utf-8")
print(f"wrote {out_path} ({len(dialog)} turns)", file=sys.stderr)
