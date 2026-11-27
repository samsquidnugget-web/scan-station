"""Background jobs: photo checks, and COLMAP -> OpenMVS reconstruction.

Only one job runs at a time, because they all share the 4 GB GPU.
"""
import shutil
import struct
import subprocess
import threading
import time
import traceback
from pathlib import Path

import numpy as np
import trimesh

from . import photos as photomod
from . import projects
from .config import COLMAP_EXE, openmvs

# Settings tuned for a 4 GB GTX 1650 (see CLAUDE.md, Phase 1 section 5).
PRESETS = {
    "draft": {
        "label": "Draft (faster, lower detail)",
        "sift_max_image_size": 2000,
        "undistort_max_image_size": 3000,
        "densify_resolution_level": 1,
        "densify_max_resolution": 1600,
        "refine_resolution_level": 2,
        "refine_scales": 1,
        "texture_resolution_level": 1,
    },
    "quality": {
        "label": "Quality (slower, more detail)",
        "sift_max_image_size": 3200,
        "undistort_max_image_size": -1,     # keep full resolution for textures
        "densify_resolution_level": 1,
        "densify_max_resolution": 2560,
        "refine_resolution_level": 1,
        "refine_scales": 2,
        "texture_resolution_level": 0,
    },
}

RECON_STAGES = [
    ("features", "Find features (COLMAP, GPU)"),
    ("matching", "Match photos (COLMAP, GPU)"),
    ("mapping", "Solve cameras (COLMAP)"),
    ("undistort", "Undistort images (COLMAP)"),
    ("interface", "Convert to OpenMVS"),
    ("densify", "Dense point cloud (OpenMVS, GPU)"),
    ("mesh", "Build mesh (OpenMVS)"),
    ("refine", "Refine mesh (OpenMVS)"),
    ("texture", "Texture mesh (OpenMVS)"),
    ("export", "Export OBJ / PLY / GLB"),
]

MAX_VIEWER_POINTS = 2_000_000
CREATE_NO_WINDOW = 0x08000000


class Cancelled(Exception):
    pass


class StageFailed(Exception):
    pass


class JobRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None
        self._cancel = threading.Event()
        self.current: str | None = None   # project id

    # ---------- public ----------
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start_check(self, pid: str) -> None:
        self._start(pid, "check", self._run_check, {})

    def start_reconstruction(self, pid: str, preset: str, exclude_flagged: bool) -> None:
        if preset not in PRESETS:
            raise ValueError(f"Unknown preset {preset!r}")
        p = projects.load(pid)
        if not all("sharpness" in ph for ph in p["photos"]):
            raise ValueError("Photo checks haven't finished for this project yet.")
        self._start(pid, "reconstruct", self._run_reconstruction,
                    {"preset": preset, "exclude_flagged": exclude_flagged})

    def cancel(self, pid: str) -> bool:
        if self.current != pid or not self.busy():
            return False
        self._cancel.set()
        proc = self._proc
        if proc and proc.poll() is None:
            # Kill the whole process tree (OpenMVS/COLMAP may use helpers).
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, creationflags=CREATE_NO_WINDOW)
        return True

    # ---------- internals ----------
    def _start(self, pid, kind, fn, opts) -> None:
        with self._lock:
            if self.busy():
                raise RuntimeError(f"Another job is running (project {self.current}). "
                                   "Only one job runs at a time because they share the GPU.")
            self._cancel.clear()
            self.current = pid
            stages = ([("check", "Convert and check photos")] if kind == "check" else RECON_STAGES)

            def init(p):
                p["job"] = {
                    "kind": kind, "status": "running", "started": projects.now(),
                    "finished": None, "error": None, "options": opts,
                    "stages": [{"key": k, "label": lbl, "status": "pending", "seconds": None,
                                "detail": None} for k, lbl in stages],
                }
                p["status"] = "checking" if kind == "check" else "running"
            projects.update(pid, init)
            self._thread = threading.Thread(target=self._wrap, args=(pid, kind, fn, opts),
                                            daemon=True)
            self._thread.start()

    def _wrap(self, pid, kind, fn, opts) -> None:
        t0 = time.time()
        status, error = "done", None
        try:
            fn(pid, **opts)
        except Cancelled:
            status, error = "cancelled", "Cancelled by user."
        except StageFailed as e:
            status, error = "failed", str(e)
        except Exception as e:  # noqa: BLE001 - report everything to the UI
            status, error = "failed", f"{type(e).__name__}: {e}"
            log = projects.project_dir(pid) / "logs" / "error.log"
            log.write_text(traceback.format_exc(), "utf-8")
        total = round(time.time() - t0, 1)

        def fin(p):
            j = p["job"]
            j.update(status=status, error=error, finished=projects.now(), seconds=total)
            for s in j["stages"]:
                if s["status"] == "running":
                    s["status"] = "failed" if status == "failed" else status
            if kind == "check":
                p["status"] = "checked" if status == "done" else "check " + status
            else:
                p["status"] = "reconstructed" if status == "done" else status
                p["history"].append({
                    "preset": opts.get("preset"), "started": j["started"], "status": status,
                    "seconds": total, "error": error,
                    "stages": {s["key"]: s["seconds"] for s in j["stages"]},
                    "result": p.get("result") if status == "done" else None,
                })
        projects.update(pid, fin)
        self._proc = None
        self.current = None

    def _stage(self, pid, key, status, seconds=None, detail=None) -> None:
        def f(p):
            for s in p["job"]["stages"]:
                if s["key"] == key:
                    s["status"] = status
                    if seconds is not None:
                        s["seconds"] = round(seconds, 1)
                    if detail is not None:
                        s["detail"] = detail
        projects.update(pid, f)

    def _exec(self, pid, key, cmd: list, cwd: Path) -> None:
        """Run one external program, logging to logs/<key>.log."""
        if self._cancel.is_set():
            raise Cancelled()
        d = projects.project_dir(pid)
        log_path = d / "logs" / f"{key}.log"
        cwd.mkdir(parents=True, exist_ok=True)
        before = set(cwd.glob("*.log"))
        with open(log_path, "a", encoding="utf-8", errors="replace") as log:
            log.write(f"$ {' '.join(str(c) for c in cmd)}\n\n")
            log.flush()
            self._proc = subprocess.Popen([str(c) for c in cmd], cwd=cwd, stdout=log,
                                          stderr=subprocess.STDOUT,
                                          creationflags=CREATE_NO_WINDOW)
            code = self._proc.wait()
            self._proc = None
            # OpenMVS writes its own log file into the working folder: append it.
            for f in sorted(set(cwd.glob("*.log")) - before):
                log.write(f"\n----- {f.name} -----\n")
                log.write(f.read_text("utf-8", errors="replace"))
                f.unlink()
        if self._cancel.is_set():
            raise Cancelled()
        if code != 0:
            raise StageFailed(f"Stage '{key}' failed (exit code {code}). See logs/{key}.log.")

    def _timed(self, pid, key, fn):
        self._stage(pid, key, "running")
        t = time.time()
        detail = fn()
        self._stage(pid, key, "done", time.time() - t, detail)

    # ---------- job: photo checks ----------
    def _run_check(self, pid) -> None:
        d = projects.project_dir(pid)
        self._stage(pid, "check", "running")
        t = time.time()
        p = projects.load(pid)
        results = []
        for i, ph in enumerate(p["photos"]):
            if self._cancel.is_set():
                raise Cancelled()
            stem = Path(ph["name"]).stem
            info = photomod.prepare_one(d / "photos" / ph["name"],
                                        d / "work" / "images" / f"{stem}.jpg",
                                        d / "work" / "thumbs" / f"{stem}.jpg")
            info["image"] = f"{stem}.jpg"
            results.append(info)
            self._stage(pid, "check", "running", detail=f"{i + 1} / {len(p['photos'])} photos")

        def f(p):
            for ph, info in zip(p["photos"], results):
                ph.update(info)
            photomod.flag_set(p["photos"])
        projects.update(pid, f)
        n_flag = sum(1 for ph in projects.load(pid)["photos"] if ph.get("flags"))
        self._stage(pid, "check", "done", time.time() - t,
                    f"{len(results)} photos converted, {n_flag} flagged")

    # ---------- job: reconstruction ----------
    def _run_reconstruction(self, pid, preset, exclude_flagged) -> None:
        cfg = PRESETS[preset]
        d = projects.project_dir(pid)
        work = d / "work"
        images = work / "images"
        cdir, dense, mvs = work / "colmap", work / "dense", work / "mvs"

        # Fresh run: clear previous intermediates, results and logs.
        for folder in (cdir, dense, mvs, d / "models", d / "exports"):
            shutil.rmtree(folder, ignore_errors=True)
        for f in (d / "logs").glob("*.log"):
            f.unlink()
        for folder in (cdir, mvs, d / "models", d / "exports"):
            folder.mkdir(parents=True)
        projects.update(pid, lambda p: p.update(result=None))

        p = projects.load(pid)
        use = [ph for ph in p["photos"] if not (exclude_flagged and ph.get("flags"))]
        if len(use) < 3:
            raise StageFailed(f"Only {len(use)} photos left after excluding flagged ones.")
        (cdir / "image_list.txt").write_text("\n".join(ph["image"] for ph in use) + "\n", "utf-8")
        single_camera = photomod.camera_groups(use) == 1
        db = cdir / "database.db"

        self._timed(pid, "features", lambda: self._exec(pid, "features", [
            COLMAP_EXE, "feature_extractor",
            "--database_path", db, "--image_path", images,
            "--image_list_path", cdir / "image_list.txt",
            "--ImageReader.camera_model", "SIMPLE_RADIAL",
            "--ImageReader.single_camera", int(single_camera),
            "--FeatureExtraction.use_gpu", 1,
            "--FeatureExtraction.max_image_size", cfg["sift_max_image_size"],
        ], cdir) or f"{len(use)} photos, {'one shared camera' if single_camera else 'several cameras'}")

        self._timed(pid, "matching", lambda: self._exec(pid, "matching", [
            COLMAP_EXE, "exhaustive_matcher", "--database_path", db,
            "--FeatureMatching.use_gpu", 1, "--FeatureMatching.guided_matching", 1,
        ], cdir))

        sparse = cdir / "sparse"
        sparse.mkdir()

        def mapping():
            no_model = ("COLMAP could not work out where the photos were taken from "
                        "(no camera solution). Usually this means too little overlap "
                        "between photos, too few photos, or a plain or shiny surface. "
                        "See logs/mapping.log.")
            try:
                self._exec(pid, "mapping", [
                    COLMAP_EXE, "mapper", "--database_path", db, "--image_path", images,
                    "--output_path", sparse,
                ], cdir)
            except StageFailed as e:
                if not any(m.is_dir() for m in sparse.iterdir()):
                    raise StageFailed(no_model) from e
                raise
            models = [(registered_images(m), m) for m in sparse.iterdir() if m.is_dir()]
            if not models:
                raise StageFailed(no_model)
            n, best = max(models)
            if n < 3:
                raise StageFailed(f"COLMAP only placed {n} photos.")
            projects.update(pid, lambda p: p.update(sparse_model=best.name))
            self._registered = n
            return (f"{n} of {len(use)} photos placed"
                    + (f" (in {len(models)} separate pieces; using the biggest)" if len(models) > 1 else ""))
        self._timed(pid, "mapping", mapping)
        best = sparse / projects.load(pid)["sparse_model"]

        self._timed(pid, "undistort", lambda: self._exec(pid, "undistort", [
            COLMAP_EXE, "image_undistorter", "--image_path", images, "--input_path", best,
            "--output_path", dense, "--output_type", "COLMAP",
            "--max_image_size", cfg["undistort_max_image_size"],
        ], cdir))

        def omvs(key, tool, *args):
            self._exec(pid, key, [openmvs(tool), *args, "-w", mvs], mvs)

        self._timed(pid, "interface", lambda: omvs(
            "interface", "InterfaceCOLMAP", "-i", dense, "-o", mvs / "scene.mvs",
            "--image-folder", dense / "images"))
        self._timed(pid, "densify", lambda: omvs(
            "densify", "DensifyPointCloud", "-i", "scene.mvs", "-o", "scene_dense.mvs",
            "--resolution-level", cfg["densify_resolution_level"],
            "--max-resolution", cfg["densify_max_resolution"], "--cuda-device", -1))
        need(mvs / "scene_dense.ply", "densify")
        self._timed(pid, "mesh", lambda: omvs(
            "mesh", "ReconstructMesh", "-i", "scene_dense.mvs", "-p", "scene_dense.ply",
            "-o", "scene_mesh.ply"))
        need(mvs / "scene_mesh.ply", "mesh")
        self._timed(pid, "refine", lambda: omvs(
            "refine", "RefineMesh", "-i", "scene_dense.mvs", "-m", "scene_mesh.ply",
            "-o", "scene_refine.ply", "--resolution-level", cfg["refine_resolution_level"],
            "--scales", cfg["refine_scales"]))
        need(mvs / "scene_refine.ply", "refine")
        self._timed(pid, "texture", lambda: omvs(
            "texture", "TextureMesh", "-i", "scene_dense.mvs", "-m", "scene_refine.ply",
            "-o", "scene_texture.obj", "--export-type", "obj",
            "--resolution-level", cfg["texture_resolution_level"]))
        need(mvs / "scene_texture.obj", "texture")

        self._timed(pid, "export", lambda: self._export(pid, mvs, d))

    def _export(self, pid, mvs: Path, d: Path) -> str:
        exports, models = d / "exports", d / "models"
        # OBJ: OpenMVS's own output (obj + mtl + texture images), copied as-is.
        obj = mvs / "scene_texture.obj"
        copied = [obj, mvs / "scene_texture.mtl"]
        for line in (mvs / "scene_texture.mtl").read_text("utf-8").splitlines():
            if line.strip().lower().startswith("map_kd"):
                copied.append(mvs / line.split(None, 1)[1].strip())
        for f in copied:
            need(f, "texture")
            shutil.copy2(f, exports / f.name)

        mesh = trimesh.load(obj, force="mesh", process=False)
        if len(mesh.faces) == 0:
            raise StageFailed("Textured mesh is empty.")
        mesh.export(exports / "scene_texture.glb")
        shutil.copy2(exports / "scene_texture.glb", models / "model.glb")
        # PLY: geometry with colours sampled from the texture (opens in MeshLab etc.).
        colored = mesh.copy()
        colored.visual = mesh.visual.to_color()
        colored.export(exports / "scene_texture.ply")

        # Dense point cloud for the viewer's "points" mode (thinned if huge).
        cloud = trimesh.load(mvs / "scene_dense.ply", process=False)
        pts = np.asarray(cloud.vertices)
        cols = getattr(cloud, "colors", None)
        cols = np.asarray(cols) if cols is not None and len(cols) else None
        n_dense = len(pts)
        if n_dense > MAX_VIEWER_POINTS:
            idx = np.random.default_rng(0).choice(n_dense, MAX_VIEWER_POINTS, replace=False)
            pts = pts[idx]
            cols = cols[idx] if cols is not None else None
        trimesh.PointCloud(pts, colors=cols).export(models / "points.ply")

        size = mesh.bounds[1] - mesh.bounds[0]
        result = {
            "faces": int(len(mesh.faces)), "vertices": int(len(mesh.vertices)),
            "dense_points": int(n_dense), "registered_photos": getattr(self, "_registered", None),
            "bbox_size": [round(float(v), 4) for v in size],
            "units": "arbitrary (no scale reference yet)",
            "exports": sorted(f.name for f in exports.iterdir()),
        }
        projects.update(pid, lambda p: p.update(result=result))
        return f"{result['faces']:,} faces, {n_dense:,} dense points"


def need(path: Path, stage: str) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise StageFailed(f"Stage '{stage}' finished but {path.name} is missing. See logs/{stage}.log.")


def registered_images(model_dir: Path) -> int:
    """Number of images in a COLMAP binary model (first uint64 of images.bin)."""
    f = model_dir / "images.bin"
    if not f.is_file():
        return 0
    with open(f, "rb") as fh:
        return struct.unpack("<Q", fh.read(8))[0]


runner = JobRunner()
