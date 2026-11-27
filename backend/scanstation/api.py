"""FastAPI app: the Scan Station backend. Listens on 127.0.0.1 only."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import projects
from .config import COLMAP_EXE, SCANS_DIR, VIEWER_DIST, openmvs
from .pipeline import PRESETS, RECON_STAGES, runner

def _mark_interrupted(p: dict) -> None:
    p["job"]["status"] = "interrupted"
    p["job"]["error"] = "The Scan Station was stopped while this job was running."
    for s in p["job"]["stages"]:
        if s["status"] in ("running", "pending"):
            s["status"] = "interrupted"
    p["status"] = "interrupted"


@asynccontextmanager
async def lifespan(_app):
    # A job that was running when the server stopped can't still be running.
    for summary in projects.list_projects():
        p = projects.load(summary["id"])
        if p.get("job") and p["job"]["status"] == "running":
            projects.update(p["id"], _mark_interrupted)
    yield


app = FastAPI(title="Scan Station v0", lifespan=lifespan)


def _get(pid: str) -> dict:
    if not projects.exists(pid):
        raise HTTPException(404, f"No project {pid!r}")
    return projects.load(pid)


def _inside(base: Path, rel: str) -> Path:
    """Resolve rel under base, refusing anything that escapes it."""
    path = (base / rel).resolve()
    if base.resolve() not in path.parents:
        raise HTTPException(404, "Not found")
    if not path.is_file():
        raise HTTPException(404, "Not found")
    return path


class NewProject(BaseModel):
    name: str
    folder: str
    notes: str = ""


class RunRequest(BaseModel):
    preset: str = "draft"
    exclude_flagged: bool = False


@app.get("/api/status")
def status():
    tools = {"colmap": COLMAP_EXE.is_file()}
    for t in ("InterfaceCOLMAP", "DensifyPointCloud", "ReconstructMesh", "RefineMesh", "TextureMesh"):
        tools[t] = openmvs(t).is_file()
    return {"busy": runner.busy(), "current": runner.current, "tools": tools,
            "scans_dir": str(SCANS_DIR),
            "presets": {k: v["label"] for k, v in PRESETS.items()},
            "default_folder": str(Path.home() / "Downloads")}


@app.get("/api/projects")
def list_projects():
    return projects.list_projects()


@app.post("/api/projects")
def create_project(req: NewProject):
    if runner.busy():
        raise HTTPException(409, "A job is running; wait for it to finish first.")
    try:
        p = projects.create(req.name, req.folder, req.notes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    runner.start_check(p["id"])
    return projects.load(p["id"])


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return _get(pid)


@app.post("/api/projects/{pid}/run")
def run(pid: str, req: RunRequest):
    _get(pid)
    try:
        runner.start_reconstruction(pid, req.preset, req.exclude_flagged)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return projects.load(pid)


@app.post("/api/projects/{pid}/cancel")
def cancel(pid: str):
    _get(pid)
    return {"cancelled": runner.cancel(pid)}


@app.get("/api/projects/{pid}/log/{stage}", response_class=PlainTextResponse)
def log(pid: str, stage: str, tail: int = 200):
    _get(pid)
    if stage not in {k for k, _ in RECON_STAGES} | {"check", "error"}:
        raise HTTPException(404, "Unknown stage")
    f = projects.project_dir(pid) / "logs" / f"{stage}.log"
    if not f.is_file():
        return ""
    lines = f.read_text("utf-8", errors="replace").splitlines()
    return "\n".join(lines[-tail:])


@app.get("/api/projects/{pid}/thumb/{name}")
def thumb(pid: str, name: str):
    _get(pid)
    return FileResponse(_inside(projects.project_dir(pid) / "work" / "thumbs", name))


@app.get("/api/projects/{pid}/models/{name}")
def model_file(pid: str, name: str):
    _get(pid)
    return FileResponse(_inside(projects.project_dir(pid) / "models", name))


@app.get("/api/projects/{pid}/exports/{name}")
def export_file(pid: str, name: str):
    _get(pid)
    path = _inside(projects.project_dir(pid) / "exports", name)
    return FileResponse(path, filename=path.name)


if VIEWER_DIST.is_dir():
    app.mount("/", StaticFiles(directory=VIEWER_DIST, html=True), name="viewer")
