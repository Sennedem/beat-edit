"""beatmap.py <audio> -> <stem>.beatmap.json : beats, downbeats, bpm, drop candidates (Beat This! + bass-energy jump).

Also writes <stem>.song.wav (stereo, full quality: put this in the plan as "audio") and <stem>.mono.wav (what the
beat tracker reads). Any input format ffmpeg reads works: wav, mp3, m4a, flac.
"""
import json, subprocess, sys
from pathlib import Path

import numpy as np
import soundfile as sf
from beat_this.inference import File2Beats


def to_wav(src: Path, tag: str, channels: int) -> Path:
    """New file next to the source, never the source itself (a .wav master used to be overwritten in place)."""
    wav = src.with_name(f"{src.stem}.{tag}.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-ac", str(channels), "-ar", "44100", str(wav)],
                   check=True)
    return wav


def bass_energy(wav: Path, times: np.ndarray, win: float = 0.5) -> np.ndarray:
    """Low-pass RMS (<150 Hz via FFT mask) in the half-second after each time."""
    y, sr = sf.read(str(wav))
    out = []
    for t in times:
        seg = y[int(t * sr): int((t + win) * sr)]
        if len(seg) < 64:
            out.append(0.0)
            continue
        spec = np.abs(np.fft.rfft(seg))
        freqs = np.fft.rfftfreq(len(seg), 1 / sr)
        out.append(float(np.sqrt(np.mean(spec[freqs < 150] ** 2))))
    return np.array(out)


def main(path: str) -> None:
    src = Path(path)
    song = to_wav(src, "song", 2)
    wav = to_wav(src, "mono", 1)
    beats, downbeats = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)(str(wav))
    bpm = 60 / float(np.median(np.diff(beats)))
    # drop = downbeat with the largest bass-energy jump vs the bar before it
    e = bass_energy(wav, downbeats)
    jumps = np.r_[0, np.diff(e)]
    order = np.argsort(-jumps)
    drops = [round(float(downbeats[i]), 3) for i in order[:3]]
    out = {"audio": song.name, "bpm": round(bpm, 1), "beats": [round(float(b), 3) for b in beats],
           "downbeats": [round(float(d), 3) for d in downbeats], "drop_candidates": drops}
    dst = src.with_name(f"{src.stem}.beatmap.json")
    dst.write_text(json.dumps(out, indent=1))
    print(f"bpm {out['bpm']} | {len(beats)} beats | {len(downbeats)} downbeats | drop candidates {drops}")
    print("downbeats:", out["downbeats"])
    print(f"plan: \"audio\": \"song/{song.name}\", \"beatmap\": \"song/{dst.name}\"")


if __name__ == "__main__":
    main(sys.argv[1])
