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

## Conventions

- Third-party engines (COLMAP, OpenMVS) are unzipped into `C:\Tools\`, not
  committed.
- Scan projects live in `Scans/` (git-ignored). Layout per scan:
  `project.json`, `photos/` (originals, never modified), `work/`, `models/`,
  `exports/`, `logs/`.
- Git commits use the GitHub noreply email, not a personal address.
