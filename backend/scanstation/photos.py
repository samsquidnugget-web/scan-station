"""Photo preparation: HEIC -> JPEG for COLMAP, thumbnails, blur/exposure checks."""
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pillow_heif
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()

EXIF_IFD = 0x8769
GPS_IFD = 0x8825
ORIENTATION = 0x0112
TAG_MAKE, TAG_MODEL = 0x010F, 0x0110
TAG_FOCAL, TAG_FOCAL35 = 0x920A, 0xA405

# Thresholds for flags. Blur is judged against the rest of the set.
BLUR_RATIO = 0.4          # flag if sharpness < 40 % of the set's median
DARK_MEAN, BRIGHT_MEAN = 45, 215
CLIP_BRIGHT_FRAC = 0.08   # > 8 % of pixels blown out
CLIP_DARK_FRAC = 0.25     # > 25 % of pixels crushed black


def _sharpness(gray: np.ndarray) -> float:
    """90th-percentile Laplacian variance over an 8x8 grid of tiles.

    Using the sharpest tiles (not the whole frame) means a plain, out-of-focus
    background doesn't make a sharp object look blurry.
    """
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    h, w = gray.shape
    vals = [lap[y:y + h // 8, x:x + w // 8].var()
            for y in range(0, h - h // 8 + 1, h // 8)
            for x in range(0, w - w // 8 + 1, w // 8)]
    return float(np.percentile(vals, 90))


def prepare_one(src: Path, out_jpg: Path, out_thumb: Path) -> dict:
    """Write an upright, landscape JPEG (EXIF kept, GPS dropped) and measure it.

    Portrait shots are turned 90 degrees so every photo from the same lens has
    the same width x height. COLMAP can then share one camera calibration
    between them, which makes the solve more stable.
    """
    im = Image.open(src)
    im = ImageOps.exif_transpose(im)  # pixels upright, orientation tag reset
    exif = im.getexif()
    sub = exif.get_ifd(EXIF_IFD)
    info = {
        "make": exif.get(TAG_MAKE), "model": exif.get(TAG_MODEL),
        "focal_mm": float(sub[TAG_FOCAL]) if TAG_FOCAL in sub else None,
        "focal35": int(sub[TAG_FOCAL35]) if TAG_FOCAL35 in sub else None,
    }
    im = im.convert("RGB")
    rotated = im.height > im.width
    if rotated:
        im = im.transpose(Image.Transpose.ROTATE_270)

    exif[ORIENTATION] = 1
    if GPS_IFD in exif:
        del exif[GPS_IFD]
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_jpg, "JPEG", quality=95, exif=exif.tobytes())

    thumb = im.copy()
    thumb.thumbnail((320, 320))
    out_thumb.parent.mkdir(parents=True, exist_ok=True)
    thumb.save(out_thumb, "JPEG", quality=80)

    small = im.copy()
    small.thumbnail((1024, 1024))
    gray = cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2GRAY)
    info.update({
        "width": im.width, "height": im.height, "rotated": rotated,
        "sharpness": round(_sharpness(gray), 1),
        "mean": round(float(gray.mean()), 1),
        "bright_frac": round(float((gray > 245).mean()), 3),
        "dark_frac": round(float((gray < 10).mean()), 3),
    })
    return info


def flag_set(photos: list[dict]) -> None:
    """Add 'flags' (list of reasons) to each checked photo, judged against the set."""
    checked = [p for p in photos if "sharpness" in p]
    if not checked:
        return
    median_sharp = float(np.median([p["sharpness"] for p in checked]))
    common = Counter((p["width"], p["height"], p["focal35"]) for p in checked).most_common(1)[0][0]
    for p in checked:
        flags = []
        if p["sharpness"] < BLUR_RATIO * median_sharp:
            flags.append(f"blurry ({p['sharpness']:.0f} vs set median {median_sharp:.0f})")
        if p["mean"] < DARK_MEAN or p["dark_frac"] > CLIP_DARK_FRAC:
            flags.append("too dark")
        if p["mean"] > BRIGHT_MEAN or p["bright_frac"] > CLIP_BRIGHT_FRAC:
            flags.append("overexposed")
        if (p["width"], p["height"], p["focal35"]) != common:
            flags.append(f"different size/zoom ({p['width']}x{p['height']}, {p['focal35']} mm equiv.)")
        p["flags"] = flags


def camera_groups(photos: list[dict]) -> int:
    return len({(p["width"], p["height"], p["focal35"]) for p in photos})
