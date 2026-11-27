"""Scan projects on disk.

Layout of one project (Scans/<date>_<name>/):
    project.json   settings, photo checks, job status, run history
    photos/        originals, copied in and never modified
    work/          converted images, COLMAP and OpenMVS intermediates (deletable)
    models/        files the viewer loads
    exports/       OBJ / PLY / GLB for other programs
    logs/          one log file per pipeline stage
"""
import datetime as dt
import json
import re
import shutil
import threading
from pathlib import Path
from typing import Callable

from .config import PHOTO_EXTS, PROJECT_SUBDIRS, SCANS_DIR

_lock = threading.RLock()
_ID_RE = re.compile(r"^[0-9a-z][0-9a-z_-]*$")


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:40] or "scan"


def project_dir(pid: str) -> Path:
    if not _ID_RE.match(pid):
        raise ValueError(f"Bad project id: {pid!r}")
    return SCANS_DIR / pid


def exists(pid: str) -> bool:
    try:
        return (project_dir(pid) / "project.json").is_file()
    except ValueError:
        return False


def load(pid: str) -> dict:
    with _lock:
        return json.loads((project_dir(pid) / "project.json").read_text("utf-8"))


def save(p: dict) -> None:
    with _lock:
        d = project_dir(p["id"])
        tmp = d / "project.json.tmp"
        tmp.write_text(json.dumps(p, indent=2), "utf-8")
        tmp.replace(d / "project.json")


def update(pid: str, fn: Callable[[dict], None]) -> dict:
    """Load, change and save project.json under one lock."""
    with _lock:
        p = load(pid)
        fn(p)
        save(p)
        return p


def list_projects() -> list[dict]:
    if not SCANS_DIR.is_dir():
        return []
    out = []
    for d in sorted(SCANS_DIR.iterdir(), reverse=True):
        if (d / "project.json").is_file():
            p = load(d.name)
            out.append({
                "id": p["id"], "name": p["name"], "created": p["created"],
                "photo_count": len(p["photos"]), "status": p["status"],
            })
    return out


def find_photos(folder: Path) -> list[Path]:
    return sorted(f for f in folder.iterdir()
                  if f.is_file() and f.suffix.lower() in PHOTO_EXTS)


def create(name: str, source_folder: str, notes: str = "") -> dict:
    src = Path(source_folder.strip().strip('"'))
    if not src.is_dir():
        raise ValueError(f"Folder not found: {src}")
    files = find_photos(src)
    if len(files) < 3:
        raise ValueError(f"Found {len(files)} photos (HEIC/JPG/PNG) in {src}; need at least 3.")

    base = f"{dt.date.today().isoformat()}_{slugify(name)}"
    pid, n = base, 2
    while (SCANS_DIR / pid).exists():
        pid, n = f"{base}-{n}", n + 1
    d = SCANS_DIR / pid
    for sub in PROJECT_SUBDIRS:
        (d / sub).mkdir(parents=True)
    for f in files:
        shutil.copy2(f, d / "photos" / f.name)

    p = {
        "id": pid,
        "name": name.strip() or pid,
        "created": now(),
        "source_folder": str(src),
        "notes": notes,
        "photos": [{"name": f.name} for f in files],
        "status": "imported",
        "job": None,
        "history": [],
        "result": None,
    }
    save(p)
    return p
