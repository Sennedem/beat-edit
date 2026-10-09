"""stems.py <url-or-file> <name> <start> <end> -> clips/intro/<name>.mp4, <name>.vocals.wav, <name>.score.wav

The intro scene, with its audio split by Demucs into the voices (vocals stem: the dialogue, no music) and
everything else (score stem: music + sound effects; the blast laid under the drop comes from here).
Only the window start..end (source seconds) is separated, because Demucs on a CPU is slow.
Prints the intro.json lines that point at the stems.
"""
import json, shutil, subprocess, sys, tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).parent


def fetch(src: str, out: Path) -> Path:
    """The scene WITH audio (shots.py keeps video only)."""
    if out.exists():
        return out
    if Path(src).exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-c:v", "libx264", "-crf", "18", "-c:a", "aac",
                        "-b:a", "192k", str(out)], check=True)
    else:
        subprocess.run([sys.executable, "-m", "yt_dlp", "-q", "--no-playlist", "-f",
                        "bv*[height<=1080][vcodec^=avc1]+ba/bv*[height<=1080]+ba/b",
                        "--merge-output-format", "mp4", "-o", str(out), src], check=True)
    return out


def blast_time(score: Path, offset: float) -> float:
    """Source time of the biggest jump in loudness in the score stem (0.1 s RMS steps): a suggestion for the
    sound laid under the drop. On the Hollow Purple scene it found the blast at 25.4 s (-38 -> -16 dB)."""
    y, sr = sf.read(str(score))
    y = y.mean(1) if y.ndim > 1 else y
    hop = int(0.1 * sr)
    db = 20 * np.log10(np.sqrt(np.array([np.mean(y[i:i + hop] ** 2) for i in range(0, len(y) - hop, hop)])) + 1e-9)
    k = int(np.argmax(np.diff(db))) + 1
    return round(offset + k * 0.1 - 0.05, 2)


def main(src: str, name: str, start: float, end: float) -> None:
    dst = ROOT / "clips" / "intro"
    dst.mkdir(parents=True, exist_ok=True)
    video = fetch(src, dst / f"{name}.mp4")
    with tempfile.TemporaryDirectory() as tmp:
        window = Path(tmp) / f"{name}.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
                        "-i", str(video), "-vn", "-ac", "2", "-ar", "44100", str(window)], check=True)
        subprocess.run([sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs", "-o", tmp,
                        str(window)], check=True)
        sep = Path(tmp) / "htdemucs" / name
        shutil.copy(sep / "vocals.wav", dst / f"{name}.vocals.wav")
        shutil.copy(sep / "no_vocals.wav", dst / f"{name}.score.wav")
    cfg = {"source": f"clips/intro/{name}.mp4", "audio": f"clips/intro/{name}.vocals.wav", "audio_offset": start,
           "sfx": {"audio": f"clips/intro/{name}.score.wav", "offset": start,
                   "start": blast_time(dst / f"{name}.score.wav", start), "dur": 1.6, "gain_db": 0}}
    print(f"stems -> {dst}\nintro.json lines:\n{json.dumps(cfg, indent=1)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]))
