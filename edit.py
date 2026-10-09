"""edit.py <plan.json> -> out/<name>.mp4 : a full-screen 9:16 beat edit, cuts frame-locked to the beat map (v5).

plan.json: {"name", "audio" (wav), "beatmap", "source" (mp4), "shots" (shots.json), "start", "end",
            "picks": [shot ids in order], "roles": [per slot], "drop": optional time of the drop}
Cut grammar: one cut per bar for the first half, every 2 beats after, every beat in the last bar.
Every frame is rendered in Python:
  framing  full-screen 9:16 crop that follows the character (track.py, CLIP), slow push-in on long slots
  velocity per-shot speed ramp, slow on the hit -> fast out of it; frames in between are blended, so fast
           parts get real motion blur from the 60 fps source and slow parts stay smooth
  hits     zoom punch on every cut, white flash on bar starts, freeze + flash + shake on the drop,
           decaying shake + RGB split on every snare (full strength in the fast half)
The colour grade (GRADE) is applied once over the whole video by intro.py, so intro and edit match.
"""
import json, subprocess, sys
from collections import deque

import cv2
import numpy as np
import soundfile as sf
from pathlib import Path

from track import track

ROOT = Path(__file__).parent
FPS, W, H = 30, 1080, 1920
GRADE = "eq=contrast=1.12:saturation=1.22:gamma=0.97,unsharp=5:5:0.6,vignette=angle=PI/5"

PUNCH = 0.06        # zoom punch on every cut: 1.06x -> 1.0x over 0.18 s
FREEZE = 6          # frames the drop's impact frame is held
EDGE = 0.25         # s kept clear of each shot boundary: Twixtor morphs one shot into the next there, and
                    # its motion spike fooled peak_t on #7 (v5 first render: a garbled frame on the cut)
PUSH = 0.05         # slow push-in over slots of a bar or longer
MAX_BLEND = 5       # most source frames averaged into one output frame (motion blur cap)
# speed ramp per slot kind: v(u) = a + (b - a) * u**p, u = 0..1 through the slot, in source seconds per output second
RAMPS = {"drop": (0.45, 1.4, 2.0), "build": (0.55, 1.7, 2.0), "long": (0.35, 2.4, 3.0),
         "short": (0.7, 1.5, 2.0), "close": (0.5, 0.5, 1.0)}


def beat_grid(bm: dict) -> tuple[float, float]:
    """Fit downbeat = t0 + n*bar by least squares. The detector skips beats on trap; the tempo grid does not."""
    d = np.array(bm["downbeats"])
    bar = float(np.median(np.diff(d)))
    bar = float(np.median([x for x in np.diff(d) if abs(x - bar) < 0.1 * bar]))
    n = np.round((d - d[0]) / bar)
    slope, t0 = np.polyfit(n, d, 1)
    return float(t0), float(slope)


def cut_times(bm: dict, start: float, end: float) -> list[float]:
    """One cut per bar in the first half, every 2 beats after, every beat in the last bar."""
    t0, bar = beat_grid(bm)
    beat = bar / 4
    k0 = round((start - t0) / beat)
    n_beats = round((end - start) / beat)
    grid = [t0 + (k0 + i) * beat for i in range(n_beats + 1)]
    cuts = []
    for i, t in enumerate(grid[:-1]):
        step = 4 if i < n_beats / 2 else 2 if i < n_beats - 4 else 1
        if i % step == 0:
            cuts.append(round(t, 3))
    return cuts + [round(grid[-1], 3)]


def snare_hits(audio: Path, bm: dict, start: float, end: float) -> list[float]:
    """Snare times: the half-beat position in the bar with the biggest 1.5-6 kHz jump, every bar.
    On 'ON YA MIND' that is beat 3 (half-time trap), 7.7-19.4 dB jumps vs at most 11 dB elsewhere, so a
    per-onset threshold would also fire on hats and fills; the bar position does not."""
    y, sr = sf.read(str(audio))
    y = y.mean(1) if y.ndim > 1 else y

    def band(t: float) -> float:
        seg = y[max(0, int(t * sr)): int((t + 0.06) * sr)]
        if len(seg) < 64:
            return -120.0
        spec, f = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))), np.fft.rfftfreq(len(seg), 1 / sr)
        return 20 * np.log10(spec[(f > 1500) & (f < 6000)].mean() + 1e-9)

    t0, bar = beat_grid(bm)
    half = bar / 8
    k0 = int(np.floor((start - t0) / bar)) * 8
    times = [t0 + (k0 + i) * half for i in range(int((end - start) / half) + 16)]
    jumps = {t: band(t) - band(t - 0.07) for t in times}
    phase = max(range(8), key=lambda p: np.mean([jumps[t] for k, t in enumerate(times) if k % 8 == p]))
    return [round(t, 3) for k, t in enumerate(times) if k % 8 == phase and start <= t < end]


def ramp_kind(role: str, dur: float) -> str:
    return role if role in ("drop", "build", "close") else "long" if dur > 0.7 else "short"


def time_map(n: int, kind: str, avail: float, freeze: int) -> np.ndarray:
    """Source offset (s) shown at each of the n output frames. Scaled down if the shot is too short."""
    a, b, p = RAMPS[kind]
    moving = n - freeze
    u = np.arange(moving) / max(1, moving)
    v = a + (b - a) * u ** p
    tau = np.concatenate([[0.0], np.cumsum(v[:-1]) / FPS])
    if tau[-1] > avail:
        tau *= avail / tau[-1]
    return np.concatenate([np.zeros(freeze), tau])


def decode(src: Path, ss: float, span: float, width: int | None = None, x0: int = 0, cw: int | None = None):
    """Yield BGR frames of src from ss for span seconds at the source frame rate (optionally scaled to
    `width`, or cropped to columns x0..x0+cw at full resolution)."""
    info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                           "-of", "csv=p=0", str(src)], capture_output=True, text=True, check=True).stdout
    sw, sh = map(int, info.strip().split(","))
    if width:
        vf, fw, fh = f"scale={width}:-2", width, round(width * sh / sw / 2) * 2
    else:
        cw = cw or sw - x0
        vf, fw, fh = f"crop={cw}:{sh}:{x0}:0", cw, sh
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{ss:.3f}", "-t", f"{span:.3f}", "-i", str(src), "-an",
                          "-vf", vf, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL)  # stopping early breaks its pipe; that is expected
    size, got = fw * fh * 3, 0
    try:
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            got += 1
            yield np.frombuffer(buf, np.uint8).reshape(fh, fw, 3)
    finally:
        p.kill()
        p.wait()
    if got == 0:
        raise RuntimeError(f"no frames decoded from {src} at {ss:.3f}s")


def probe(src: Path) -> tuple[int, int, float]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate", "-of", "csv=p=0", str(src)],
                         capture_output=True, text=True, check=True).stdout.strip().split(",")
    num, den = map(int, out[2].split("/"))
    return int(out[0]), int(out[1]), num / den


def place(frame: np.ndarray, cx: float, zoom: float, dx: float, dy: float) -> np.ndarray:
    """Crop the 9:16 window centred on column cx (pixels of `frame`), zoomed, shaken, scaled to W x H."""
    fh, fw = frame.shape[:2]
    h = fh / zoom
    w = h * 9 / 16
    cx = float(np.clip(cx, w / 2, fw - w / 2))
    s = H / h
    m = np.float32([[s, 0, W / 2 - s * cx + dx], [0, s, H / 2 - s * fh / 2 + dy]])
    return cv2.warpAffine(frame, m, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def rgb_split(img: np.ndarray, px: int) -> np.ndarray:
    if px < 1:
        return img
    out = img.copy()
    out[:, px:, 2] = img[:, :-px, 2]
    out[:, :-px, 0] = img[:, px:, 0]
    return out


def flash(img: np.ndarray, alpha: float) -> np.ndarray:
    if alpha <= 0:
        return img
    return cv2.addWeighted(img, 1 - alpha, np.full_like(img, 255), alpha, 0)


def hit_env(t: float, hits: list[float], decay: float = 0.10, length: float = 0.35) -> tuple[float, float]:
    """(envelope 0..1 of the most recent hit, its song time)."""
    past = [h for h in hits if 0 <= t - h < length]
    if not past:
        return 0.0, -1.0
    h = max(past)
    return float(np.exp(-(t - h) / decay)), h


def prepare(ctx: dict, i: int) -> dict:
    """Slot i's source window, time map and crop path. Paths are cached in out/<name>/track.json, so an
    effects-only re-render skips CLIP. All slots are prepared before the encoder starts: CLIP's torch threads
    running beside libx264 turned a ~4 min render into 134 min (2026-10-08)."""
    shot, n = ctx["shots"][ctx["picks"][i]], ctx["frames"][i + 1] - ctx["frames"][i]
    role = ctx["roles"][i] if i < len(ctx["roles"]) else "impact"
    is_drop = ctx["drop"] is not None and abs(ctx["cuts"][i] - ctx["drop"]) < 0.05
    freeze = FREEZE if is_drop else 0
    lo_t, hi_t = shot["start"] + EDGE, shot["end"] - EDGE
    avail = hi_t - lo_t - 0.05
    tau = time_map(n, ramp_kind("drop" if is_drop else role, n / FPS), avail, freeze)
    span = tau[-1] + 2 / ctx["sfps"]
    peak = ctx["peaks"].get(shot["id"])
    if peak is not None and (is_drop or role in ("impact", "close")):
        ss = peak - 2 / ctx["sfps"]          # impact frame on the beat, shown in slow motion
    else:
        ss = lo_t + (avail - tau[-1]) / 2
    ss = float(np.clip(ss, lo_t, hi_t - span))

    key = f"{shot['id']}@{ss:.3f}+{span:.3f}"
    if key not in ctx["cache"]:
        small = list(decode(ctx["src"], ss, span + 0.05, width=640))
        ctx["cache"][key] = track(small, ctx["sh"] * 9 / 16 / ctx["sw"]).round(4).tolist()
    return {"shot": shot, "n": n, "role": role, "is_drop": is_drop, "freeze": freeze, "tau": tau, "span": span,
            "ss": ss, "path": np.array(ctx["cache"][key])}


def render_segment(ctx: dict, i: int, prep: dict) -> list[np.ndarray]:
    """All output frames of slot i: full-resolution columns around the crop path only."""
    shot, n, role, is_drop, freeze = prep["shot"], prep["n"], prep["role"], prep["is_drop"], prep["freeze"]
    tau, span, ss, path = prep["tau"], prep["span"], prep["ss"], prep["path"]
    long_slot = n >= 45
    margin = ctx["sh"] * 9 / 16 * 0.6
    lo = int(max(0, path.min() * ctx["sw"] - margin)) // 2 * 2
    hi = int(min(ctx["sw"], path.max() * ctx["sw"] + margin))
    cw = (hi - lo) // 2 * 2
    stream, buf, got = decode(ctx["src"], ss, span + 0.05, x0=lo, cw=cw), deque(maxlen=MAX_BLEND + 2), -1

    def frame_at(k: int) -> np.ndarray:
        nonlocal got
        while got < k:
            nxt = next(stream, None)
            if nxt is None:
                break
            buf.append(nxt.astype(np.float32))
            got += 1
        return buf[-1 - max(0, got - k)] if got - k < len(buf) else buf[0]

    out, prev_f = [], None
    for j in range(n):
        f = tau[j] * ctx["sfps"]
        k = int(f)
        if prev_f is not None and f - prev_f > 1.5:          # fast: average the frames passed over
            ks = range(max(int(prev_f) + 1, k - MAX_BLEND + 1), k + 1)
            img = np.mean([frame_at(q) for q in ks], axis=0)
        else:                                                 # slow: blend the two neighbours
            a = f - k
            img = frame_at(k) if a < 0.05 else (1 - a) * frame_at(k) + a * frame_at(k + 1)
        prev_f = f
        u = j / max(1, n - 1)
        cx = path[min(len(path) - 1, k)] * ctx["sw"] - lo
        tl = j / FPS
        t = ctx["cuts"][i] + tl
        env, h = hit_env(t, ctx["hits"])
        strong = h >= ctx["fast_from"]
        zoom = 1 + PUNCH * max(0.0, 1 - tl / 0.18) + (PUSH * u if long_slot else 0.0) + (0.05 if strong else 0.025) * env
        sk = (22 if strong else 0) * env + (24 * max(0.0, 1 - (tl - freeze / FPS) / 0.4) if is_drop and tl >= freeze / FPS else 0)
        img = place(img.astype(np.uint8), cx, zoom, sk * np.sin(t * 90), sk * 0.8 * np.cos(t * 70))
        img = rgb_split(img, round((14 if strong else 8) * env + (10 if is_drop and j < freeze + 4 else 0)))
        if is_drop:
            img = flash(img, 0.9 if j < 2 else max(0.0, 0.7 * (1 - (j - 2) / (freeze + 4))))
        elif ctx["bar_start"][i]:
            img = flash(img, max(0.0, 0.8 * (1 - tl / 0.12)))
        out.append(img)
    ctx["log"].append(f"slot {i:2d} #{shot['id']:<3} {role:6s} {n:3d}f ss={ss:7.3f} span={tau[-1]:.2f}s"
                      f" path={path.min():.2f}-{path.max():.2f}")
    return out


def main(plan_path: str) -> None:
    plan = json.loads(Path(plan_path).read_text())
    bm = json.loads((ROOT / plan["beatmap"]).read_text())
    shots = {s["id"]: s for s in json.loads((ROOT / plan["shots"]).read_text())["shots"]}
    ranked_p = (ROOT / plan["shots"]).with_name("ranked.json")
    peaks = {s["id"]: s["peak_t"] for s in json.loads(ranked_p.read_text())} if ranked_p.exists() else {}
    start, end, drop = plan["start"], plan["end"], plan.get("drop")
    cuts = cut_times(bm, start, end)
    t0, bar = beat_grid(bm)
    src = ROOT / plan["source"]
    sw, sh, sfps = probe(src)
    ctx = {"plan": plan, "shots": shots, "picks": plan["picks"], "roles": plan.get("roles", []), "drop": drop,
           "cuts": cuts, "frames": [round((c - start) * FPS) for c in cuts],  # cumulative rounding: no drift
           "peaks": peaks, "src": src, "sw": sw, "sh": sh, "sfps": sfps, "log": [],
           "hits": snare_hits(ROOT / plan["audio"], bm, start, end), "fast_from": start + (end - start) / 2,
           "bar_start": [abs(((c - t0) / bar) % 1 - 0.5) > 0.45 for c in cuts]}
    out = ROOT / "out" / f"{plan['name']}.mp4"
    enc_cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
               "-r", str(FPS), "-i", "-", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
               "-i", str(ROOT / plan["audio"]), "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
               "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
               # a mono song goes out as stereo at unity gain: ffmpeg's own upmix drops each side 3 dB, which
               # left the beat 3 dB under the intro voice (2026-10-09)
               *(["-af", "pan=stereo|c0=c0|c1=c0"] if sf.info(str(ROOT / plan["audio"])).channels == 1 else []),
               "-shortest", str(out)]
    work = ROOT / "out" / plan["name"]
    work.mkdir(parents=True, exist_ok=True)
    cache_p = work / "track.json"
    ctx["cache"] = json.loads(cache_p.read_text()) if cache_p.exists() else {}
    preps = [prepare(ctx, i) for i in range(len(cuts) - 1)]
    cache_p.write_text(json.dumps(ctx["cache"]))
    enc = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE)
    total = 0
    for i in range(len(cuts) - 1):
        for img in render_segment(ctx, i, preps[i]):
            enc.stdin.write(np.ascontiguousarray(img).tobytes())
            total += 1
        print(ctx["log"][-1], flush=True)
    enc.stdin.close()
    if enc.wait() != 0:
        sys.exit("encoder failed")
    (work / "cuts.json").write_text(json.dumps({"cuts_song_time": cuts, "cut_frames": ctx["frames"],
                                                "snares": ctx["hits"]}, indent=1))
    print(f"{len(cuts) - 1} segments, {total} frames, snares at {ctx['hits']} -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
