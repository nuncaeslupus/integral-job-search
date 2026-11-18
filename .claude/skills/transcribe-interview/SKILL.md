---
name: transcribe-interview
description: Use whenever an interview (or any two-person conversation) is about to be recorded or has been, to record it and turn it into a readable, speaker-separated dialog — transcribe audio or video, diarize, then clean the overlaps by hand. Triggers — "transcribe this interview", "who said what in this recording", "how do I record my interview", a .m4a/.mp3/.wav/.mp4 of a conversation. Owns scripts — record.sh, mix.py, transcribe.py, diarize.py. Do NOT use for a single-speaker memo (diarization adds nothing) or for live captioning.
---

# transcribe-interview

Turn a recorded two-person interview into a readable dialog file: GPU transcription
(faster-whisper), speaker separation (pyannote), then a model cleanup pass that fixes
the overlap misattributions and names the speakers.

CANARY: transcribe-interview-loaded-2026-10-26-66869dcb-6093d1171606d814

## When to load

Load this skill when:

- an interview is coming up — offer to record it (next section);
- the candidate (or owner) hands over a recording of an interview and wants to review what was said;
- step 12 (`interview_log`) has a recording to work from, before writing up lessons;
- someone asks "who said what" in a two-person audio file.

If the recording is one speaker, skip diarization — just run the transcription step.

## Before the interview — offer to record it

Offer it once, as an option, never a condition: with a recording, the candidate and the tool
can go through the interview together afterwards — what was asked, how each answer landed, what
to prepare for the next one. Suggest asking the interviewer's leave at the start, as a request
to record it for the candidate's own notes; most say yes, and it is the honest default. Do not give legal advice on recording.

If they are unsure how, offer the simplest route that fits, in this order:

- **In person or by phone** — the phone's voice-recorder app, phone on the table.
- **Video call** — the platform's own Record button (Meet, Zoom, Teams), which also announces the
  recording to everyone; the host may need to allow it.
- **Any desktop OS** — OBS Studio, capturing the mic plus desktop audio.
- **Linux with PipeWire** — this skill's recorder: it captures the mic and the call's audio
  output and mixes them into one `call.wav`; Ctrl-C stops it.

  ```bash
  bash ${CLAUDE_SKILL_DIR}/scripts/record.sh <profiles-root>/<handle>/interviews/<id>   # -> mic.wav, system.wav, call.wav
  ```

Whatever they used, there is nothing to convert: step 1 below decodes any audio or video file
(m4a, mp3, ogg/opus, wav, mp4, mkv, webm) as it is.

## Prerequisites (one-time)

- **A CUDA GPU.** Both models run locally; nothing leaves the machine. Tested on an 8 GB RTX 4060.
- **`uv`** on PATH. No other system packages — not even ffmpeg; PyAV decodes the audio.
- **A Hugging Face token** at `~/.cache/huggingface/token` (or `$HF_TOKEN`). pyannote's model is gated:
  sign in at huggingface.co, accept the licenses for **`pyannote/speaker-diarization-3.1`** AND
  **`pyannote/segmentation-3.0`**, then create a **Read** token (no inference scope — pyannote runs locally).

The recording, transcript and dialog are candidate data: they live under the candidate's
profile (`<profiles-root>/<handle>/interviews/<id>/`), **never in this repo**. Only this
skill's code is committed.

## How to use

Four steps. The first two are scripts; the third assigns names; the fourth is the model's own.

```bash
OUT=<profiles-root>/<handle>/interviews/<id>            # outside the repo

# 1. Transcribe -> transcript.txt + transcript.srt  (~1 min of audio ≈ seconds on GPU)
bash ${CLAUDE_SKILL_DIR}/scripts/transcribe.sh "<recording>.m4a" "$OUT/transcript.txt"

# 2. Diarize + merge with the srt -> dialog_raw.md  (SPEAKER_00 / SPEAKER_01)
bash ${CLAUDE_SKILL_DIR}/scripts/diarize.sh "<recording>.m4a" "$OUT/transcript.srt" "$OUT/dialog_raw.md"
```

Run each script in the **background** and wait for the completion signal — the first run of
each downloads its model, and a backgrounded `nohup … &` detaches the real process so the
harness reports a misleading early exit. Run the real command in the foreground of the bg task.

### 3. Who is who

Read a few turns of `dialog_raw.md`. One obvious line fixes the mapping — e.g. the interviewer
introducing their company ("somos una agencia de talento") is not the candidate. Settle which of
SPEAKER_00 / SPEAKER_01 is each person before cleaning.

### 4. The cleanup pass — the model's own, spent in tokens

Diarization assigns each segment to the speaker it overlaps most. On short cross-talk ("sí, sí",
a back-channel, a cut-off word) that assignment is often wrong, and the raw turns are fragmented.
Read `dialog_raw.md` against `transcript.txt` and write a clean `dialog.md`:

- **Reassign misattributed lines** by sense, not audio — a question belongs to the interviewer,
  an answer to the candidate; a line that continues the previous speaker's point stays theirs.
  When a turn clearly glues two voices together, split it at the boundary.
- **Never change the words.** Fix only speaker attribution, paragraphing and obvious punctuation.
  Do not paraphrase, summarise, invent or drop content — a cleaned dialog that no longer matches
  what was said is worse than a messy accurate one.
- **Merge** consecutive same-speaker fragments into one turn, keeping the opening timestamp.
- **Lay it out readably** — a short header (participants with their real names, date, duration,
  the role/employer if known), then the dialog with bold speaker names and a timestamp per turn.
- **Flag, never guess** — mark a genuinely ambiguous passage `[unclear: …]` rather than committing
  it to a speaker.

`dialog.md` is the deliverable. Keep `dialog_raw.md` beside it so the cleanup stays auditable.

## Gotchas

- **Two conflicting dependency sets, one per step.** Transcription needs a new `huggingface_hub`;
  pyannote 3.1 needs an old one. They cannot share an env, so each `.sh` is its own pinned
  ephemeral `uv` env — that is the lockfile. Do not try to merge them into one `pyproject.toml`.
- **The pins are load-bearing, every one.** `av<14` (PyAV 14 dropped a kwarg faster-whisper's
  decoder passes), `numpy<2` (pyannote 3.1 uses the removed `np.NaN`), `torch==2.7.1`
  (torchaudio ≥2.8 dropped `AudioMetaData`), `huggingface_hub==0.25.2` (newer dropped
  `use_auth_token`). Loosen one and the chain breaks somewhere surprising. `pyannote.audio<4` is
  deliberate: 4.x redirects to a *different* gated model needing a separate license.
- **ctranslate2 does not bundle CUDA; torch does.** `transcribe.sh` resolves the cuBLAS/cuDNN
  wheels onto `LD_LIBRARY_PATH` (via `nvidia.__path__`, not `nvidia.__file__`, which is `None` for
  the namespace package). `diarize.sh` needs none of that — torch's wheel carries its own CUDA.
- **torch ≥2.6 defaults `weights_only=True`.** `diarize.py` forces it back off to load pyannote's
  official checkpoint; the file is trusted, so this is safe.
- **`record.sh` forwards Ctrl-C as TERM.** Background children of a non-interactive shell ignore
  SIGINT, so `kill -INT` never stops `pw-record`; to stop the script from another process, send TERM.
- **Whisper detects one language per window.** Heavy ES/EN code-switching can garble the switched
  parts; here `large-v3` handled it, but check the switched passages before trusting them.
