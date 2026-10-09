"""check.py <video.mp4> <cuts.json> <out.jpg> [offset_s] : contact sheet, one row per slot (first frame, +3,
middle, last), so framing, freeze, flash and ramp can be looked at per slot. offset = intro length when the
video is the full intro + edit."""
import json, sys

import cv2
import numpy as np


def main(video: str, cuts_path: str, out: str, offset: float = 0.0) -> None:
    frames = json.loads(open(cuts_path).read())["cut_frames"]
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    base = round(offset * fps)
    rows = []
    for i in range(len(frames) - 1):
        a, b = frames[i], frames[i + 1]
        tiles = []
        for k in (a, a + 3, (a + b) // 2, b - 1):
            cap.set(cv2.CAP_PROP_POS_FRAMES, base + k)
            ok, f = cap.read()
            f = cv2.resize(f if ok else np.zeros((1920, 1080, 3), np.uint8), (180, 320))
            cv2.putText(f, f"s{i} f{k}", (4, 14), 0, 0.45, (0, 255, 255), 1)
            tiles.append(f)
        rows.append(np.hstack(tiles))
    half = (len(rows) + 1) // 2
    left, right = rows[:half], rows[half:] + [np.zeros_like(rows[0])] * (half - len(rows[half:]))
    cv2.imwrite(out, np.hstack([np.vstack(left), np.full((half * 320, 12, 3), 40, np.uint8), np.vstack(right)]))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else 0.0)
