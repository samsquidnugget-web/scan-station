"""Paths and settings. Override any path with an environment variable."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Scan projects (git-ignored). Each project is one folder.
SCANS_DIR = Path(os.environ.get("SCANSTATION_SCANS", REPO / "Scans"))

# Reconstruction engines, unzipped in C:\Tools (see CLAUDE.md).
COLMAP_EXE = Path(os.environ.get("SCANSTATION_COLMAP", r"C:\Tools\COLMAP\bin\colmap.exe"))
OPENMVS_DIR = Path(os.environ.get("SCANSTATION_OPENMVS", r"C:\Tools\OpenMVS"))

# Built browser viewer (npm run build), served by the backend.
VIEWER_DIST = REPO / "viewer" / "dist"

PHOTO_EXTS = {".heic", ".heif", ".jpg", ".jpeg", ".png"}
PROJECT_SUBDIRS = ("photos", "work", "models", "exports", "logs")


def openmvs(tool: str) -> Path:
    return OPENMVS_DIR / f"{tool}.exe"
