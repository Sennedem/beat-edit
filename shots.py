"""shots.py <url-or-file> <name> -> clips/<name>/{source.mp4, shots.json, sheet.jpg}

Any video (YouTube, TikTok, an anime episode, a local file) -> shot boundaries (PySceneDetect)
-> per-shot action score (mean frame difference) + sharpness -> numbered contact sheet of the top shots.
"""
import json, subprocess, sys
from pathlib import Path

import cv2
import numpy as np
from scenedetect import ContentDetector, detect

ROOT = Path(__file__).parent
MIN_LEN, TOP_N = 0.5, 24


def fetch(src: str, dst: Path) -> Path:
    out = dst / "source.mp4"
    if out.exists():
        return out
    if Path(src).exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-an", "-c:v", "libx264", "-crf", "18", str(out)], check=True)
    else:
        # prefer H.264: AV1/VP9 decode in OpenCV is ~10x slower
        subprocess.run([sys.executable, "-m", "yt_dlp", "-q", "--no-playlist", "-f",
                        "bv*[height<=1080][vcodec^=avc1]/bv*[height<=1080][ext=mp4]/bv*[height<=1080]/b",
                        "--remux-video", "mp4", "-o", str(out), src], check=True)
    return out


def save_meta(src: str, dst: Path) -> None:
    """For an online source: title, views and YouTube's "Most replayed" heatmap -> meta.json (signals.py
    uses the heatmap for popularity; on a scene pack, replays = editors scrubbing to the clips they want)."""
    out = dst / "meta.json"
    if out.exists() or Path(src).exists():
        return
    r = subprocess.run([sys.executable, "-m", "yt_dlp", "-j", "--no-playlist", src],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print(f"no metadata for {src} (popularity will rely on the other signals)")
        return
    info = json.loads(r.stdout)
    keep = {k: info.get(k) for k in ("id", "title", "view_count", "duration", "heatmap")}
    out.write_text(json.dumps(keep, indent=1), encoding="utf-8")


def proxy(video: Path) -> Path:
    """640px H.264 with a keyframe every 15 frames: fast to scan and cheap to seek. Edits still cut the full source."""
    out = video.with_name("proxy.mp4")
    if not out.exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-an", "-vf", "scale=640:-2",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-g", "15", str(out)], check=True)
    return out


def score_shot(cap: cv2.VideoCapture, fps: float, a: float, b: float) -> tuple[float, float]:
    """Action = mean abs diff between 8 sampled frame pairs; sharpness = Laplacian variance."""
    diffs, sharp = [], []
    for t in np.linspace(a + 0.05, b - 0.1, 8):
        frames = []
        for dt in (0, 2 / fps):
            cap.set(cv2.CAP_PROP_POS_MSEC, (t + dt) * 1000)
            ok, f = cap.read()
            if ok:
                frames.append(cv2.cvtColor(cv2.resize(f, (320, 180)), cv2.COLOR_BGR2GRAY))
        if len(frames) == 2:
            diffs.append(float(np.mean(cv2.absdiff(*frames))))
            sharp.append(float(cv2.Laplacian(frames[0], cv2.CV_64F).var()))
    return (np.mean(diffs) if diffs else 0.0), (np.mean(sharp) if sharp else 0.0)


def contact_sheet(cap: cv2.VideoCapture, shots: list[dict], path: Path) -> None:
    tiles = []
    for s in shots:
        cap.set(cv2.CAP_PROP_POS_MSEC, (s["start"] + s["end"]) / 2 * 1000)
        ok, f = cap.read()
        f = cv2.resize(f if ok else np.zeros((180, 320, 3), np.uint8), (320, 180))
        label = f"#{s['id']} {s['end'] - s['start']:.1f}s act {s['action']:.0f}"
        cv2.rectangle(f, (0, 0), (320, 24), (0, 0, 0), -1)
        cv2.putText(f, label, (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        tiles.append(f)
    while len(tiles) % 4:
        tiles.append(np.zeros((180, 320, 3), np.uint8))
    rows = [np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]
    cv2.imwrite(str(path), np.vstack(rows))


def main(src: str, name: str) -> None:
    dst = ROOT / "clips" / name
    dst.mkdir(parents=True, exist_ok=True)
    video = proxy(fetch(src, dst))
    save_meta(src, dst)
    scenes = detect(str(video), ContentDetector(threshold=27))
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    shots = []
    for i, (a, b) in enumerate(scenes):
        a, b = a.get_seconds(), b.get_seconds()
        if b - a < MIN_LEN:
            continue
        action, sharp = score_shot(cap, fps, a, b)
        shots.append({"id": i, "start": round(a, 3), "end": round(b, 3), "action": round(action, 1), "sharp": round(sharp)})
    # drop near-black / blurry shots (fades, credits), then rank by action
    usable = [s for s in shots if s["sharp"] > 40]
    top = sorted(usable, key=lambda s: -s["action"])[:TOP_N]
    (dst / "shots.json").write_text(json.dumps({"source": src, "fps": fps, "shots": shots, "top": [s["id"] for s in top]}, indent=1))
    contact_sheet(cap, top, dst / "sheet.jpg")
    print(f"{len(scenes)} cuts, {len(shots)} shots >= {MIN_LEN}s, top {len(top)} on sheet -> {dst / 'sheet.jpg'}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
