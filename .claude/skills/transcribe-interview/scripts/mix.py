"""Mix two same-format 16-bit WAVs (record.sh's mic + system tracks) into one. Stdlib only."""

import sys
import wave
from array import array


def read(path: str) -> tuple[wave._wave_params, array[int]]:
    with wave.open(path) as w:
        params = w.getparams()
        samples = array("h", w.readframes(w.getnframes()))
    return params, samples


def mix(a: array[int], b: array[int]) -> array[int]:
    if len(a) < len(b):
        a, b = b, a
    out = array("h", a)
    for i, s in enumerate(b):
        out[i] = max(-32768, min(32767, out[i] + s))
    return out


def main(mic: str, system: str, out: str) -> None:
    params, a = read(mic)
    other, b = read(system)
    if (params.nchannels, params.sampwidth, params.framerate) != (
        other.nchannels,
        other.sampwidth,
        other.framerate,
    ) or params.sampwidth != 2:
        sys.exit(f"mix.py: {mic} and {system} differ in format or are not 16-bit")
    with wave.open(out, "wb") as w:
        w.setparams(params)
        w.writeframes(mix(a, b).tobytes())


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        assert mix(array("h", [1, 32000]), array("h", [2, 32000, 5])).tolist() == [3, 32767, 5]
        print("ok")
    else:
        main(*sys.argv[1:4])
