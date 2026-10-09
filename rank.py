"""rank.py <clips-name> <plan.json> -> 4-criteria scores per shot, ranked sheet, and picks written into the plan.

popularity  = 35% replay heatmap + 30% use in viral edits (views-weighted) + 35% iconic (Claude's read)
originality = 70% not-overused-in-edits + 30% not a near-duplicate of another shot in the source
quality     = defects only: 50% crisp (absolute threshold) + 30% not black/blown out + 20% no flicker;
              text/blank = 0, soft = -30
impact      = 45% impact (Claude's read) + 35% peak motion spike + 20% colour pop
Each slot in the edit weights the four differently: the drop wants popular + hard-hitting,
the build-up wants fresher shots, fast cuts want impact. One shot per scene.
"""
import json, sys
from pathlib import Path

import cv2
import numpy as np

from edit import cut_times

ROOT = Path(__file__).parent
WEIGHTS = {  # popularity, originality, quality, impact
    "build":  (0.25, 0.25, 0.25, 0.25),
    "drop":   (0.45, 0.05, 0.15, 0.35),
    "impact": (0.20, 0.20, 0.20, 0.40),
    "close":  (0.40, 0.10, 0.20, 0.30),
}
SHARP_OK = 150  # Laplacian variance at 320x180 above which a frame is crisp enough
ROLE_FIT = {("drop", "impact"): 0.08, ("impact", "drop"): 0.08, ("close", "drop"): 0.05, ("build", "close"): 0.0}


def pct(values: list[float]) -> np.ndarray:
    """Percentile rank 0..1, robust to outliers."""
    v = np.array(values, dtype=float)
    return np.argsort(np.argsort(v)) / max(1, len(v) - 1)


def score(sig: list[dict], vision: dict) -> list[dict]:
    sharp, peak, sat = pct([s["sharp"] for s in sig]), pct([s["peak"] for s in sig]), pct([s["sat"] for s in sig])
    heat = np.array([s["heat"] or 0 for s in sig]); heat = heat / (heat.max() or 1)
    use = np.array([s["edit_usage"] for s in sig]); use_n = use / (use.max() or 1)
    clusters = [s["cluster"] for s in sig]
    out = []
    for k, s in enumerate(sig):
        v = vision.get(str(s["id"]), {"iconic": 3, "impact": 3, "role": "filler"})
        flags = v.get("flags", [])
        dup = clusters.count(s["cluster"]) > 1
        # a signal this source doesn't have (no heatmap, no viral-edit matches) is left out and its
        # weight re-spread, instead of squashing every shot toward 0
        parts = [(0.35, v["iconic"] / 10)] + ([(0.35, heat[k])] if heat.max() > 0 else [])             + ([(0.30, use_n[k])] if use.max() > 0 else [])
        pop = sum(w * x for w, x in parts) / sum(w for w, _ in parts)
        orig = 0.70 * (1 - use_n[k]) + 0.30 * (0.5 if dup else 1.0)
        # defects only, never style: soft bloom and bright golden light are art direction, not low quality
        crisp = min(1.0, s["sharp"] / SHARP_OK)
        exposed = 1.0 if s["exposure"] >= 0.2 else s["exposure"] / 0.2   # only near-black / blown out
        qual = 0.5 * crisp + 0.3 * exposed + 0.2 * (1 - min(1.0, s["flicker"] * 3))
        if "text" in flags or "blank" in flags:
            qual = 0.0
        if "soft" in flags:
            qual -= 0.3
        imp = 0.45 * v["impact"] / 10 + 0.35 * peak[k] + 0.20 * sat[k]
        out.append({**s, "role": v["role"], "flags": flags, "note": v.get("note", ""),
                    "subject": v.get("subject"), "fight": v.get("fight"),
                    "popularity": round(pop * 100), "originality": round(orig * 100),
                    "quality": round(max(0.0, qual) * 100), "impact": round(imp * 100)})
    return out


def slot_value(shot: dict, slot_role: str) -> float:
    w = WEIGHTS[slot_role]
    v = (w[0] * shot["popularity"] + w[1] * shot["originality"] + w[2] * shot["quality"] + w[3] * shot["impact"]) / 100
    if shot["role"] == slot_role:
        v += 0.15
    v += ROLE_FIT.get((slot_role, shot["role"]), 0.0)
    if "in-intro" in shot["flags"]:
        return -9.0  # already on screen in the intro
    if shot["role"] == "filler" or "other-character" in shot["flags"] or shot["quality"] == 0:
        v -= 0.5
    return v


def slot_roles(n: int, cuts: list[float], drop: float | None) -> list[str]:
    roles = []
    for i in range(n):
        if drop is not None and abs(cuts[i] - drop) < 0.05:
            roles.append("drop")
        elif i == n - 1:
            roles.append("close")
        elif drop is not None and cuts[i] < drop:
            roles.append("build")
        else:
            roles.append("impact")
    return roles


def hue_hists(shots: list[dict], video: Path) -> dict[int, np.ndarray]:
    """Hue/saturation histogram of each shot's impact frame: a cheap 'looks the same' signal."""
    cap = cv2.VideoCapture(str(video))
    out = {}
    for s in shots:
        cap.set(cv2.CAP_PROP_POS_MSEC, s["peak_t"] * 1000)
        ok, f = cap.read()
        if not ok:
            continue
        hsv = cv2.cvtColor(cv2.resize(f, (160, 90)), cv2.COLOR_BGR2HSV)
        h = cv2.calcHist([hsv], [0, 1], None, [18, 4], [0, 180, 0, 256])
        out[s["id"]] = cv2.normalize(h, h).flatten()
    return out


def pick(shots: list[dict], roles: list[str], durs: list[float], hists: dict[int, np.ndarray],
         fight: str | None = None, main: str | None = None, main_share: float = 0.0) -> list[int]:
    """Drop and close first (they carry the story), then the longest slots (most screen time); one shot per
    scene cluster (neighbouring shots in the source count as one scene). A look-alike penalty only against
    the slots next to it, so a single-palette fight pack is not punished for being one palette. Each run of
    same-role slots is then put in source order, so the fight reads as a story.
    fight: only shots tagged with this fight (v4 leaked round-1 flashbacks into a round-2 edit).
    main/main_share: at least this share of slots shows the main character ('both' counts)."""
    if fight:
        shots = [s for s in shots if s.get("fight") in (None, fight)]
    budget = len(roles) - int(np.ceil(main_share * len(roles))) if main else len(roles)
    order = sorted(range(len(roles)), key=lambda i: (roles[i] not in ("drop", "close"), roles[i] != "drop", -durs[i], i))
    used, picks = set(), [None] * len(roles)

    def is_main(s: dict) -> bool:
        return not main or s.get("subject") in (main, "both")

    def lookalike(s: dict, i: int) -> float:
        nb = [picks[j] for j in (i - 1, i + 1) if 0 <= j < len(picks) and picks[j] is not None]
        return max((cv2.compareHist(hists[s["id"]], hists[p], cv2.HISTCMP_CORREL) for p in nb), default=0.0)

    for i in order:
        near = {p + d for p in picks if p is not None for d in (-1, 0, 1)}
        ok = [s for s in shots if s["cluster"] not in used and s["id"] not in near
              and (s["end"] - s["start"]) * 2.5 >= durs[i] and (budget > 0 or is_main(s))]
        best = max(ok, key=lambda s: slot_value(s, roles[i]) - 0.35 * max(0.0, lookalike(s, i) - 0.5))
        picks[i] = best["id"]
        used.add(best["cluster"])
        budget -= 0 if is_main(best) else 1
    start = {s["id"]: s["start"] for s in shots}
    i = 0
    while i < len(roles):
        j = i
        while j + 1 < len(roles) and roles[j + 1] == roles[i] and roles[i] in ("build", "impact"):
            j += 1
        picks[i:j + 1] = sorted(picks[i:j + 1], key=lambda p: start[p])
        i = j + 1
    return picks


def sheet(shots: list[dict], video: Path, path: Path, n: int = 24) -> None:
    cap = cv2.VideoCapture(str(video))
    tiles = []
    for s in shots[:n]:
        cap.set(cv2.CAP_PROP_POS_MSEC, s["peak_t"] * 1000)
        ok, f = cap.read()
        f = cv2.resize(f if ok else np.zeros((180, 320, 3), np.uint8), (320, 180))
        cv2.rectangle(f, (0, 0), (320, 40), (0, 0, 0), -1)
        cv2.putText(f, f"#{s['id']} {s['role']}", (5, 16), 0, 0.5, (0, 255, 255), 1)
        cv2.putText(f, f"P{s['popularity']} O{s['originality']} Q{s['quality']} I{s['impact']}", (5, 34), 0, 0.5, (255, 255, 255), 1)
        tiles.append(f)
    while len(tiles) % 4:
        tiles.append(np.zeros((180, 320, 3), np.uint8))
    cv2.imwrite(str(path), np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]))


def main(name: str, plan_path: str) -> None:
    d = ROOT / "clips" / name
    sig = json.loads((d / "signals.json").read_text())
    vision = json.loads((d / "vision.json").read_text())
    shots = score(sig, vision)
    shots.sort(key=lambda s: -(s["popularity"] + s["originality"] + s["quality"] + s["impact"]))
    (d / "ranked.json").write_text(json.dumps(shots, indent=1))
    sheet(shots, d / "proxy.mp4", d / "ranked.jpg")
    plan = json.loads(Path(plan_path).read_text())
    bm = json.loads((ROOT / plan["beatmap"]).read_text())
    cuts = cut_times(bm, plan["start"], plan["end"])
    durs = [b - a for a, b in zip(cuts, cuts[1:])]
    roles = plan.get("slot_roles") or slot_roles(len(durs), cuts, plan.get("drop"))
    plan["picks"] = pick(shots, roles, durs, hue_hists(shots, d / "proxy.mp4"),
                         plan.get("fight"), plan.get("main"), plan.get("main_share", 0.0))
    plan["roles"] = roles
    Path(plan_path).write_text(json.dumps(plan, indent=1))
    by_id = {s["id"]: s for s in shots}
    for r, p, dur in zip(roles, plan["picks"], durs):
        s = by_id[p]
        print(f"{r:6s} {dur:4.2f}s  #{p:<4} {s['subject'] or '?':5s} {s['fight'] or '?':3s} P{s['popularity']:>3} "
              f"O{s['originality']:>3} Q{s['quality']:>3} I{s['impact']:>3}  {s['note']}")
    if plan.get("main"):
        n = sum(by_id[p]["subject"] in (plan["main"], "both") for p in plan["picks"])
        print(f"{plan['main']}: {n}/{len(plan['picks'])} shots")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
