"""track.py : where the subject is in each frame, for a full-screen 9:16 crop that follows it.

track() scores candidate 9:16 windows with CLIP (character face / eye / character) a few times per shot and
glides the crop between them. The first attempt, edge/spectral saliency + motion, chased hair, hands and
chains (3 of 12 test shots wrong); CLIP got 12 of 12.
"""
import cv2
import numpy as np

def smooth(xs: np.ndarray, sigma: float, max_step: float) -> np.ndarray:
    """Gaussian smoothing (sigma in samples), then cap the per-sample move so a pan never whips."""
    if len(xs) < 3:
        return xs
    k = np.arange(-3 * sigma, 3 * sigma + 1)
    w = np.exp(-k ** 2 / (2 * sigma ** 2))
    pad = np.pad(xs, len(k) // 2, mode="edge")
    out = np.convolve(pad, w / w.sum(), "valid")[: len(xs)]
    for i in range(1, len(out)):
        out[i] = out[i - 1] + np.clip(out[i] - out[i - 1], -max_step, max_step)
    return out


N_WIN = 25          # candidate window positions per frame
PROMPTS = ["an anime character's face", "an anime character's eye", "an anime character"]
_CLIP = {}


def _clip():
    """CLIP ViT-B-32 + the prompt embeddings, loaded once."""
    if not _CLIP:
        import open_clip
        import torch
        model, _, prep = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
        tok = open_clip.get_tokenizer("ViT-B-32")
        with torch.no_grad():
            txt = model.encode_text(tok(PROMPTS))
            txt /= txt.norm(dim=-1, keepdim=True)
        _CLIP.update(model=model, prep=prep, txt=txt, torch=torch)
    return _CLIP


def window_scores(frame: np.ndarray, frac: float) -> tuple[np.ndarray, np.ndarray]:
    """CLIP score per candidate window centre: the best of face / eye / character, smoothed over neighbours.
    Calibrated 2026-10-08 on 12 Toji-pack shots against hand-marked face positions: 12/12 within 0.08 of the
    frame width (face prompt alone 11/12, edge saliency 9/12: it chased hair, hands and chains)."""
    from PIL import Image
    c = _clip()
    fh, fw = frame.shape[:2]
    w = fw * frac
    cs = np.linspace(w / 2, fw - w / 2, N_WIN)
    crops = [c["prep"](Image.fromarray(cv2.cvtColor(np.ascontiguousarray(frame[:, int(x - w / 2): int(x + w / 2)]),
                                                    cv2.COLOR_BGR2RGB))) for x in cs]
    with c["torch"].no_grad():
        im = c["model"].encode_image(c["torch"].stack(crops))
        im /= im.norm(dim=-1, keepdim=True)
        best = (100 * im @ c["txt"].T).numpy().max(1)
    k = np.array([1, 2, 3, 2, 1]) / 9
    return cs / fw, np.convolve(np.pad(best, 2, mode="edge"), k, "valid")


def track(frames: list[np.ndarray], frac: float, every: int = 15) -> np.ndarray:
    """Smoothed window centre (0..1 of the width, clamped so the window stays inside) for every frame.
    CLIP looks at every `every`-th frame (0.25 s at 60 fps, at least 3 looks per shot); in between the
    centre is interpolated, then smoothed so the crop glides instead of jitters."""
    n = len(frames)
    idx = sorted(set(np.linspace(0, n - 1, max(3, n // every + 1)).round().astype(int)))
    centres = []
    for k in idx:
        cs, score = window_scores(frames[k], frac)
        centres.append(cs[int(np.argmax(score))])
    xs = np.interp(np.arange(n), idx, centres)
    xs = smooth(xs, sigma=max(3.0, n / 5), max_step=0.006)
    half = frac / 2
    return np.clip(xs, half, 1 - half)
