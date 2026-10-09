"""signals.py <name> [edit-url ...] -> clips/<name>/signals.json : measurable ranking signals per shot.

popularity  : YouTube "Most replayed" heatmap over the shot (start-of-video bias removed)
              + how often viral edits use the scene (CLIP match, weighted by log10 views)
originality : inverse of that edit usage, and near-duplicate clusters inside the source
quality     : sharpness, exposure, no fade/flash frames
impact      : peak motion spike (not the mean), colour pop, plus the impact-frame time for alignment
"""
import json, subprocess, sys
from pathlib import Path

import cv2
import numpy as np
import open_clip
import torch
from PIL import Image

ROOT = Path(__file__).parent
MODEL, _, PREP = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
MODEL.eval()


def embed(frames: list[np.ndarray]) -> np.ndarray:
    with torch.no_grad():
        x = torch.stack([PREP(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))) for f in frames])
        e = MODEL.encode_image(x)
    return (e / e.norm(dim=-1, keepdim=True)).numpy()


def frames_at(cap: cv2.VideoCapture, times) -> list[np.ndarray]:
    out = []
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, f = cap.read()
        if ok:
            out.append(f)
    return out


def heatmap_score(meta: dict, a: float, b: float) -> float | None:
    h = meta.get("heatmap")
    if not h:
        return None
    vals = np.array([p["value"] for p in h])
    base = np.median(vals[3:])
    # the first ~3 bins are high on every video (people watch the start); clamp them to the median
    fixed = [(p["start_time"], p["end_time"], base if i < 3 else p["value"]) for i, p in enumerate(h)]
    over = [v for s, e, v in fixed if e > a and s < b]
    return float(np.mean(over) / vals[3:].max()) if over else 0.0


def shot_metrics(cap: cv2.VideoCapture, fps: float, a: float, b: float) -> dict:
    """Dense pass at ~10 fps: motion curve (peak + its time), sharpness, exposure, saturation."""
    ts = np.arange(a + 0.04, b - 0.04, 0.1)
    prev, motion, sharp, bright, sat = None, [], [], [], []
    for t in ts:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, f = cap.read()
        if not ok:
            continue
        small = cv2.resize(f, (320, 180))
        g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        motion.append(float(np.mean(cv2.absdiff(g, prev))) if prev is not None else 0.0)
        sharp.append(float(cv2.Laplacian(g, cv2.CV_64F).var()))
        bright.append(float(g.mean()))
        sat.append(float(hsv[..., 1].mean()))
        prev = g
    if len(motion) < 2:
        return {"peak": 0, "peak_t": a, "sharp": 0, "exposure": 0, "flicker": 1, "sat": 0}
    m = np.array(motion[1:])
    i = int(np.argmax(m))
    return {"peak": float(m.max()), "mean_motion": float(m.mean()), "peak_t": round(float(ts[i + 1]), 3),
            "sharp": float(np.median(sharp)), "exposure": float(1 - abs(np.median(bright) - 115) / 115),
            "flicker": float(np.std(bright) / (np.mean(bright) + 1)), "sat": float(np.median(sat))}


def edit_usage(cap, shots, src_emb, urls: list[str], dst: Path) -> np.ndarray:
    """For each viral edit: 2 fps frames, centre-cropped to 16:9 where needed, matched to the source shots."""
    usage = np.zeros(len(shots))
    edits = dst / "edits"
    edits.mkdir(exist_ok=True)
    for url in urls:
        vid = url.rsplit("=", 1)[-1].rsplit("/", 1)[-1]
        f = edits / f"{vid}.mp4"
        info = edits / f"{vid}.json"
        if not f.exists():
            subprocess.run([sys.executable, "-m", "yt_dlp", "-q", "--no-playlist", "-f", "bv*[height<=480][vcodec^=avc1]/bv*[height<=480]/b",
                            "--remux-video", "mp4", "--write-info-json", "-o", str(edits / f"{vid}.%(ext)s"), url], check=True)
        meta = json.loads(info.with_suffix(".info.json").read_text(encoding="utf-8")) if info.with_suffix(".info.json").exists() else {}
        weight = np.log10(max(meta.get("view_count", 10_000), 10))
        ec = cv2.VideoCapture(str(f))
        dur = ec.get(cv2.CAP_PROP_FRAME_COUNT) / (ec.get(cv2.CAP_PROP_FPS) or 30)
        frames = frames_at(ec, np.arange(0.25, dur, 0.5))
        if not frames:
            continue
        sims = embed(frames) @ src_emb.T          # [edit frames, source frames]
        best = sims.max(axis=1)
        print("    sim pct 10/50/90/max:", np.round(np.percentile(best, [10, 50, 90, 100]), 3))
        np.save(edits / f"{vid}.sims.npy", sims)
        owner = SRC_OWNER[sims.argmax(axis=1)]
        hit = set()
        for s, o in zip(best, owner):
            if s >= MATCH:
                hit.add(int(o))
        for o in hit:
            usage[o] += weight
        print(f"  {vid}: {len(frames)} frames, {len(hit)} source shots matched (views {meta.get('view_count')})")
    return usage


MATCH = 0.905  # calibrated 2026-10-08: true matches >=0.908, other-shot-same-character <=0.898
SRC_OWNER = np.array([])


def main(name: str, urls: list[str]) -> None:
    global SRC_OWNER
    dst = ROOT / "clips" / name
    data = json.loads((dst / "shots.json").read_text())
    meta_p = dst / "meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    cap = cv2.VideoCapture(str(dst / "proxy.mp4"))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    shots = data["shots"]
    # 3 frames per shot -> CLIP embeddings (dedupe + edit matching)
    src_frames, owner = [], []
    for k, s in enumerate(shots):
        fr = frames_at(cap, np.linspace(s["start"] + 0.1, s["end"] - 0.1, 3))
        src_frames += fr
        owner += [k] * len(fr)
    src_emb = np.concatenate([embed(src_frames[i:i + 64]) for i in range(0, len(src_frames), 64)])
    SRC_OWNER = np.array(owner)
    shot_emb = np.stack([src_emb[SRC_OWNER == k].mean(0) for k in range(len(shots))])
    shot_emb /= np.linalg.norm(shot_emb, axis=1, keepdims=True)
    # near-duplicate clusters (same scene split by a cut, or repeated in the pack)
    sim = shot_emb @ shot_emb.T
    cluster = list(range(len(shots)))
    for i in range(len(shots)):
        for j in range(i):
            if sim[i, j] > 0.93:
                cluster[i] = cluster[j]
                break
    usage = edit_usage(cap, shots, src_emb, urls, dst) if urls else np.zeros(len(shots))
    out = []
    for k, s in enumerate(shots):
        m = shot_metrics(cap, fps, s["start"], s["end"])
        out.append({**s, **m, "heat": heatmap_score(meta, s["start"], s["end"]),
                    "edit_usage": round(float(usage[k]), 2), "cluster": cluster[k]})
    (dst / "signals.json").write_text(json.dumps(out, indent=1))
    print(f"{len(out)} shots, {len(set(cluster))} unique scenes, {int((usage > 0).sum())} shots seen in viral edits")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
