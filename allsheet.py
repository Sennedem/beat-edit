"""allsheet.py <clips-name> -> clips/<name>/all-<k>.jpg : every shot's impact frame (from signals.json), numbered,
30 per sheet. This is what Claude reads to write clips/<name>/vision.json (iconic, impact, role, subject, fight,
flags, note per shot) before rank.py runs."""
import json, sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).parent
PER_SHEET, COLS = 30, 6


def main(name: str) -> None:
    d = ROOT / "clips" / name
    shots = json.loads((d / "signals.json").read_text())
    cap = cv2.VideoCapture(str(d / "proxy.mp4"))
    sheets = []
    for k in range(0, len(shots), PER_SHEET):
        tiles = []
        for s in shots[k:k + PER_SHEET]:
            cap.set(cv2.CAP_PROP_POS_MSEC, s.get("peak_t", (s["start"] + s["end"]) / 2) * 1000)
            ok, f = cap.read()
            f = cv2.resize(f if ok else np.zeros((180, 320, 3), np.uint8), (320, 180))
            cv2.rectangle(f, (0, 0), (320, 22), (0, 0, 0), -1)
            cv2.putText(f, f"#{s['id']} {s['end'] - s['start']:.1f}s", (5, 16), 0, 0.5, (0, 255, 255), 1)
            tiles.append(f)
        while len(tiles) % COLS:
            tiles.append(np.zeros((180, 320, 3), np.uint8))
        path = d / f"all-{k // PER_SHEET}.jpg"
        cv2.imwrite(str(path), np.vstack([np.hstack(tiles[i:i + COLS]) for i in range(0, len(tiles), COLS)]))
        sheets.append(path.name)
    print(f"{len(shots)} shots on {len(sheets)} sheets: {', '.join(sheets)}")


if __name__ == "__main__":
    main(sys.argv[1])
