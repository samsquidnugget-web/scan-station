# Scan Station: instructions for Claude

A home 3D-scanning system. iPhone photos are processed on a Windows laptop with
proven reconstruction engines. We do **not** write our own photogrammetry engine.

This repo is **public**. Anything committed here can be seen by anyone.

## Working rules (from the owner, always apply)

1. **The owner is not an experienced developer.** For every install, explain:
   what it is, why it's needed, where to download it (official source), how to
   install it, and how to check it worked. **Wait for the owner to confirm**
   before moving on to the next install or step.
2. **Free options only.** Ask before anything that costs money.
3. **Never say something works until it has actually run on this laptop.** No
   hidden placeholders, stubs or fake data. If something is unfinished, say so
   plainly.
4. **No passwords, keys, tokens or personal data in the repo.** That includes
   photos (iPhone photos contain GPS location in their EXIF data), scan
   outputs, and `phase1.md.pdf`, which stays local only.
5. **Commit as we go**, with small, clear commits.

## Decisions recorded (27 Nov 2026, final)

From the approved Phase 1 technical investigation:

- **Architecture:** Python Scan Station (FastAPI backend) + local browser UI
  (Vite + TypeScript + Three.js). COLMAP 4.x + OpenMVS are the core engine. Each
  stage reads and writes plain files, so engines can be swapped.
- **RealityScan:** included as a benchmark / max-quality engine (free under
  US$1M revenue, proprietary, needs an Epic account).
- **Mac:** none to buy. iPhone app builds (Phase 4) run on free GitHub Actions
  macOS runners. Sideloadly installs them with a free Apple ID (7-day
  re-signing). Pay for the Apple Developer Program only if that gets annoying.
- **Code hosting:** public GitHub repo (unlimited free macOS builds).
- **PC:** laptop with plenty of free space. Run long jobs plugged in.
- **Test objects** (reused in every phase):
  - easy: a textured shoe or mug
  - accuracy: a metal bracket measured with calipers
  - stress: a glossy or plain-white item

Phase 2 decisions (27 Nov 2026):

- Meshroom is **skipped** for v0.
- Photos move from iPhone to laptop with **LocalSend** over Wi-Fi.
- `phase1.md.pdf` is kept **out** of the repo.
- **The phone is an iPhone 15 Pro Max** (confirmed by the owner and by photo
  EXIF). Phase 1 said iPhone 16 Pro Max; that was wrong. The 15 Pro Max also
  has LiDAR and an A17 Pro chip, so it meets every Phase 1 requirement.
- **Capture at 1x** (main camera, 24 mm equivalent) and move closer instead
  of zooming. Zoomed shots are cropped to 12 MP and make the camera lens
  harder for COLMAP to calibrate.

## Phase 2 goal: "Scan Station v0"

1. Import a folder of iPhone photos (HEIC is converted, blurry or badly exposed
   photos are flagged).
2. Run COLMAP 4.x (camera solving), then OpenMVS: densify, mesh, refine,
   texture.
3. Show the result in a local browser viewer (textured, wireframe and
   point-cloud views; orbit and zoom).
4. Export OBJ, PLY and GLB.
5. Run the same photos through RealityScan and compare.

**Done means:** all three test objects finish unattended, open in the viewer
and export. Processing times and measured-vs-caliper errors are recorded.

## Hardware and environment (checked 27 Nov 2026)

- Windows 11 Home laptop, Intel Iris Xe + **NVIDIA GTX 1650 4 GB** (CUDA
  compute 7.5), 32 GB RAM, ~166 GB free on C:.
- NVIDIA driver 580.97 (CUDA 13.0). Git 2.56.1. GitHub CLI 2.106.0.
- Python 3.12.3 (**use this one**, in a project virtual environment) and 3.13.5.
- Node.js 26.13.1, npm 11.20.0.
- 4 GB VRAM means dense depth maps must be downscaled (about 2,000-3,200 px on
  the long edge). Textures still use full-resolution photos.

## Installed tools (verified on this laptop)

| Tool | Version | Location | Verified |
|---|---|---|---|
| 7-Zip | 26.06 | `C:\Program Files\7-Zip\7z.exe` | runs (27 Nov 2026) |
| COLMAP | 4.2.1, CUDA build (`colmap-x64-windows-cuda.zip`, SHA-256 matched GitHub) | `C:\Tools\COLMAP\bin\colmap.exe` | 27 Nov 2026: GPU SIFT extraction + GPU matching ran on two synthetic images (~3,060 features each, 2,819 verified matches). Not yet run on real photos. |
| OpenMVS | v2.4.0, CUDA build (`OpenMVS_Windows_x64_CUDA.7z`, SHA-256 matched GitHub) | `C:\Tools\OpenMVS\*.exe` | 27 Nov 2026: InterfaceCOLMAP, DensifyPointCloud, ReconstructMesh, RefineMesh, TextureMesh all start; all needed DLLs present; log shows "CUDA device 0 initialized: NVIDIA GeForce GTX 1650". Not yet run on a real scene. |
| NVIDIA CUDA Toolkit | 13.0 | `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.0` | Was already installed; neither COLMAP nor OpenMVS depends on it. |
| Python packages | see `backend/requirements.txt` | `.venv\` (Python 3.12.3) | 27 Nov 2026: HEIC write+read, OpenCV blur score, trimesh OBJ/PLY/GLB export+reload all ran. |
| Viewer packages | three 0.187.0, vite 8.4.0, typescript 7.0.2 | `viewer\node_modules\` | 27 Nov 2026: vite and tsc run; three loads in Node and builds geometry. 0 npm vulnerabilities. |
| LocalSend | 1.19.0 (winget `LocalSend.LocalSend`, installer hash matched GitHub release) | `%LOCALAPPDATA%\Programs\LocalSend\localsend_app.exe` | 27 Nov 2026: app starts, listens on TCP/UDP 53317; Wi-Fi profile is Private; firewall inbound allow rules (TCP + UDP) limited to **Private** networks only, at the owner's request. 27 Nov 2026: iPhone-to-laptop transfer worked (file lands in `Downloads`, arrived intact), but the test image was a 1122x1402 PNG with no EXIF, not an original camera photo. Second test, a fresh Camera-app photo sent with Send → Media, arrived as the original HEIC with full EXIF (Make/Model, lens, focal length, exposure; 44 tags). So LocalSend's Media option keeps originals. |

Notes on tools:
- OpenMVS prints `--help` output to a `.log` file in the working folder,
  not to the console, and exits with code 1 for `--help`. That is normal.
- `RefineMesh` defaults to CPU (`--cuda-device -2`).
- Not installed on purpose (yet): pymeshlab, open3d, usd-core, pycolmap.
  Phase 1 lists them, but v0 doesn't need them. Add them when a feature needs
  them.

Recreate the Python environment:
`py -3.12 -m venv .venv` then
`.venv\Scripts\python.exe -m pip install -r backend\requirements.txt`.
Recreate the viewer packages: `cd viewer` then `npm ci`.

Downloaded archives are kept in `C:\Tools\_downloads\` (outside the repo).

## Code layout and how to run (v0)

- `backend/scanstation/`: FastAPI app (`api.py`), project folders
  (`projects.py`), HEIC conversion + blur/exposure checks (`photos.py`), job
  runner and COLMAP/OpenMVS stages (`pipeline.py`), paths (`config.py`).
- `viewer/`: Vite + TypeScript + Three.js page (`src/main.ts` UI,
  `src/viewer3d.ts` 3D view). The backend serves the built `viewer/dist`.
- Start: `.\run.ps1` then open http://127.0.0.1:8000 (backend binds to
  127.0.0.1 only). For Claude: `.claude/launch.json` config `scanstation`.
- Pipeline: photo check (HEIC→upright landscape JPEG, EXIF kept, GPS
  dropped) → COLMAP feature_extractor / exhaustive_matcher / mapper /
  image_undistorter → OpenMVS InterfaceCOLMAP / DensifyPointCloud /
  ReconstructMesh / RefineMesh / TextureMesh (OBJ) → trimesh writes GLB and
  vertex-coloured PLY. Presets `draft` and `quality` are in `pipeline.py`.

### Verified so far (27 Nov 2026)
- Import + photo check + thumbnails work in the browser (3-photo test).
- COLMAP reads the focal length from the converted JPEG's EXIF ("Prior").
- A run that can't be solved stops at "Solve cameras" with a plain message.
- **Not yet verified:** a full run on a real object (densify → texture →
  export), the 3D view and the downloads.

## Conventions

- Third-party engines (COLMAP, OpenMVS) are unzipped into `C:\Tools\`, not
  committed.
- Scan projects live in `Scans/` (git-ignored). Layout per scan:
  `project.json`, `photos/` (originals, never modified), `work/`, `models/`,
  `exports/`, `logs/`.
- Git commits use the GitHub noreply email, not a personal address.
