"""intro.py <intro.json> -> out/<name>.mp4 : dialogue intro (voice only, no music) + captions, then the beat edit (v5).

intro.json: {"name", "source" (mp4), "start", "end", "subs": [[t0, t1, "text"], ...] (source time),
             "edit": "out/<edit>.mp4", "audio" + "audio_offset" (voice stem and the source time it starts at),
             "crop_bottom" (share of the frame holding burned-in subs), "sfx": {"audio", "offset", "start", "dur",
             "gain_db"} (the scene's own sound laid under the drop)}
Full-screen 9:16 that follows the character (track.py) with a slow push-in, captions
in the lower third clear of TikTok's UI, the intro runs on into the whiteout so ~0.5 s of silence sits before the
drop, the blast SFX lands on the drop, and one colour grade (edit.GRADE) covers intro + edit.
"""
import json, os, subprocess, sys
from pathlib import Path

import numpy as np
import soundfile as sf

from edit import FPS, GRADE, H, W, decode, place, probe
from track import track

ROOT = Path(__file__).parent
FONTS = ["C:/Windows/Fonts/arialbd.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/Library/Fonts/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
CAP_Y = 1180        # first caption row; TikTok's caption/description UI covers roughly the bottom 25%
CAP_SIZE, CAP_ROW = 64, 82
PUSH_IN = 0.07      # intro zooms 1.0 -> 1.07: builds toward the drop


def caption_font() -> str:
    """A bold sans for the captions: $BEATEDIT_FONT if set, else Arial Bold (Windows/macOS) or DejaVu (Linux),
    escaped for ffmpeg's drawtext."""
    for f in [os.environ.get("BEATEDIT_FONT", "")] + FONTS:
        if f and Path(f).exists():
            return f.replace("\\", "/").replace(":", "\\:")
    sys.exit("no caption font found: set BEATEDIT_FONT to the path of a .ttf file")


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "’").replace(":", "\\:").replace(",", "\\,")


def wrap(text: str, limit: int = 24) -> list[str]:
    """Greedy word wrap; 64 px Arial Bold fits ~24 characters in 1080 px with margin."""
    rows, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > limit:
            rows.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return rows + [cur]


def speech_phrases(wav: Path, offset: float, a: float, b: float, floor: float = 0.01) -> list[tuple[float, float]]:
    """Spoken phrases (source time) from the voice track: 0.1 s RMS above the floor, gaps < 0.4 s merged."""
    y, sr = sf.read(str(wav))
    y = y.mean(1) if y.ndim > 1 else y
    phrases, cur = [], None
    for t in np.arange(a, b, 0.1):
        seg = y[int((t - offset) * sr): int((t - offset + 0.1) * sr)]
        loud = len(seg) and np.sqrt(np.mean(seg ** 2)) > floor
        if loud and cur is None:
            cur = [t, t + 0.1]
        elif loud:
            cur[1] = t + 0.1
        elif cur is not None and t - cur[1] > 0.4:
            phrases.append(tuple(cur))
            cur = None
    return phrases + ([tuple(cur)] if cur else [])


def check_captions(cfg: dict, wav: Path, offset: float) -> None:
    """Every spoken phrase must overlap a caption (the uncaptioned-Geto-line bug, 2026-10-08). Fails the build."""
    a, b = cfg["start"], cfg["end"]
    bare = [(p0, p1) for p0, p1 in speech_phrases(wav, offset, a, b)
            if p1 - p0 >= 0.3 and not any(t0 < p1 and t1 > p0 for t0, t1, _ in cfg["subs"])]
    if bare:
        sys.exit("uncaptioned speech at " + ", ".join(f"{p0:.1f}-{p1:.1f}s" for p0, p1 in bare))
    # a caption that runs across a pause > 0.8 s is usually sitting on the next speaker's line (v3: Gojo's
    # caption over Geto's "Trust, huh?")
    phrases = speech_phrases(wav, offset, a, b)
    for t0, t1, text in cfg["subs"]:
        inside = [p for p in phrases if p[0] < t1 and p[1] > t0]
        gaps = [q[0] - p[1] for p, q in zip(inside, inside[1:])]
        if gaps and max(gaps) > 0.8:  # calibrated on 2 cases: same-speaker pause 0.6 s, speaker change 1.0 s
            sys.exit(f"caption '{text}' spans a {max(gaps):.1f}s pause: likely a speaker change, split it")


def render_intro(cfg: dict, out: Path) -> float:
    """Full-screen tracked intro with captions and the voice track. Returns its duration."""
    a, b = cfg["start"], cfg["end"]
    src = ROOT / cfg["source"]
    sw, sh, sfps = probe(src)
    keep_h = round(sh * (1 - cfg.get("crop_bottom", 0.0)) / 2) * 2   # burned-in subs cut off
    n = round((b - a) * FPS)
    small = [f[: round(f.shape[0] * keep_h / sh)] for f in decode(src, a, b - a + 0.1, width=640)]
    path = track(small, keep_h * 9 / 16 / sw)
    font = caption_font()
    subs = "".join(
        f",drawtext=fontfile='{font}':text='{esc(row)}':fontsize={CAP_SIZE}:fontcolor=white:borderw=6:bordercolor=black"
        f":x=(w-text_w)/2:y={CAP_Y + r * CAP_ROW}:enable='between(t,{t0 - a:.2f},{t1 - a:.2f})'"
        for t0, t1, t in cfg["subs"] for r, row in enumerate(wrap(t)))
    voice, offset = ROOT / cfg["audio"], cfg.get("audio_offset", 0.0)
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-ss", f"{a - offset:.3f}", "-t", f"{b - a:.3f}", "-i", str(voice),
                            "-vf", f"null{subs},format=yuv420p", "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
                            "-crf", "17", "-preset", "medium", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "192k",
                            str(out)], stdin=subprocess.PIPE)
    step = sfps / FPS
    for j, f in enumerate(decode(src, a, b - a + 0.1)):
        if j % round(step) or j // round(step) >= n:
            continue
        k = j // round(step)
        u = k / max(1, n - 1)
        img = place(np.ascontiguousarray(f[:keep_h]), path[min(len(path) - 1, j)] * sw, 1 + PUSH_IN * u ** 1.5, 0, 0)
        enc.stdin.write(img.tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        sys.exit("intro encoder failed")
    return n / FPS


def main(path: str) -> None:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    check_captions(cfg, ROOT / cfg["audio"], cfg.get("audio_offset", 0.0))
    intro = ROOT / "out" / f"{cfg['name']}-intro.mp4"
    dur = render_intro(cfg, intro)
    out = ROOT / "out" / f"{cfg['name']}.mp4"
    sfx = cfg.get("sfx")
    inputs = ["-i", str(intro), "-i", str(ROOT / cfg["edit"])]
    graph = ("[0:v]setsar=1[i0];[1:v]setsar=1[i1];[0:a]aformat=sample_rates=44100:channel_layouts=stereo[s0];"
             "[1:a]aformat=sample_rates=44100:channel_layouts=stereo[s1];[i0][s0][i1][s1]concat=n=2:v=1:a=1[v0][a0];"
             f"[v0]{GRADE},format=yuv420p[v]")
    if sfx:
        # the scene's own blast, starting on the drop, faded out so it hands over to the beat
        inputs += ["-ss", f"{sfx['start'] - sfx['offset']:.3f}", "-t", f"{sfx['dur']:.3f}", "-i", str(ROOT / sfx["audio"])]
        ms = round(dur * 1000)
        graph += (f";[2:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={sfx.get('gain_db', 0)}dB,"
                  f"afade=t=out:st={sfx['dur'] * 0.4:.2f}:d={sfx['dur'] * 0.6:.2f},adelay={ms}|{ms},apad[fx];"
                  "[a0][fx]amerge=inputs=2,pan=stereo|c0=c0+c2|c1=c1+c3,alimiter=limit=0.95:level=0[a]")
    else:
        graph += ";[a0]anull[a]"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-c:a", "aac", "-b:a", "192k", str(out)],
                   check=True)
    print(f"intro {dur:.2f}s + edit -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
