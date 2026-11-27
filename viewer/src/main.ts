import "./style.css";
import { ScanViewer, type ViewMode } from "./viewer3d";

type Stage = { key: string; label: string; status: string; seconds: number | null; detail: string | null };
type Photo = {
  name: string; image?: string; width?: number; height?: number; focal35?: number | null;
  sharpness?: number; mean?: number; flags?: string[];
};
type Project = {
  id: string; name: string; created: string; status: string; photos: Photo[];
  job: null | { kind: string; status: string; error: string | null; seconds?: number; finished: string | null;
    options: { preset?: string; exclude_flagged?: boolean }; stages: Stage[] };
  result: null | { faces: number; vertices: number; dense_points: number; registered_photos: number | null;
    bbox_size: number[]; units: string; exports: string[] };
  history: { preset: string; started: string; status: string; seconds: number; error: string | null }[];
};
type Status = { busy: boolean; current: string | null; tools: Record<string, boolean>;
  presets: Record<string, string>; default_folder: string };

const $ = <T extends HTMLElement>(sel: string, root: ParentNode = document) => root.querySelector(sel) as T;
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const fmtTime = (s: number | null | undefined) => {
  if (s == null) return "";
  if (s < 60) return `${s.toFixed(0)} s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m} min ${Math.round(s % 60)} s` : `${Math.floor(m / 60)} h ${m % 60} min`;
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { msg = (await r.json()).detail ?? msg; } catch { /* not JSON */ }
    throw new Error(msg);
  }
  const type = r.headers.get("content-type") ?? "";
  return (type.includes("json") ? r.json() : r.text()) as Promise<T>;
}

let status: Status;
let currentId: string | null = null;
let viewer: ScanViewer | null = null;
let viewerKey = "";
let pollTimer: number | undefined;
let openLog: string | null = null;

async function refreshList() {
  const list = await api<{ id: string; name: string; photo_count: number; status: string }[]>("/api/projects");
  $("#project-list").innerHTML = list.length
    ? list.map((p) => `<li><a href="#${esc(p.id)}" class="${p.id === currentId ? "active" : ""}">
        <b>${esc(p.name)}</b><span class="muted">${esc(p.id.slice(0, 10))} · ${p.photo_count} photos · ${esc(p.status)}</span></a></li>`).join("")
    : `<li class="muted">No scans yet.</li>`;
}

function stageRow(s: Stage) {
  const icon = { done: "✔", running: "⏳", failed: "✖", cancelled: "■", interrupted: "■", pending: "·" }[s.status] ?? "·";
  return `<tr class="st-${esc(s.status)}"><td>${icon}</td><td>${esc(s.label)}</td>
    <td class="muted">${esc(s.detail ?? "")}</td><td class="num">${fmtTime(s.seconds)}</td>
    <td>${s.status !== "pending" ? `<button class="link" data-log="${esc(s.key)}">log</button>` : ""}</td></tr>`;
}

function render(p: Project) {
  const job = p.job;
  const running = job?.status === "running";
  const checked = p.photos.every((ph) => ph.sharpness !== undefined);
  const flagged = p.photos.filter((ph) => ph.flags?.length);
  const d = $("#detail");
  d.className = "";
  d.innerHTML = `
    <h2>${esc(p.name)} <span class="muted">${esc(p.id)}</span></h2>
    <div class="cols">
      <div class="col">
        <section class="card">
          <h3>Reconstruction</h3>
          <div class="row">
            <select id="preset" ${running ? "disabled" : ""}>${Object.entries(status.presets)
              .map(([k, v]) => `<option value="${k}" ${job?.options?.preset === k ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>
            <label class="inline"><input type="checkbox" id="exclude" ${running ? "disabled" : ""}/> Leave out ${flagged.length} flagged photo(s)</label>
          </div>
          <div class="row">
            <button id="run" ${running || !checked || status.busy ? "disabled" : ""}>Run reconstruction</button>
            ${running ? `<button id="cancel" class="danger">Cancel</button>` : ""}
          </div>
          ${job ? `<p class="job-${esc(job.status)}"><b>${esc(job.kind === "check" ? "Photo check" : "Reconstruction")}:
             ${esc(job.status)}</b> ${job.seconds ? `in ${fmtTime(job.seconds)}` : ""} ${job.error ? `<br>${esc(job.error)}` : ""}</p>
             <table class="stages">${job.stages.map(stageRow).join("")}</table>` : ""}
          <pre id="log" class="${openLog ? "" : "hidden"}"></pre>
        </section>
        <section class="card">
          <h3>Photos <span class="muted">${p.photos.length} imported · ${checked ? `${flagged.length} flagged` : "checking…"}</span></h3>
          <div class="thumbs">${p.photos.map((ph) => `
            <figure class="${ph.flags?.length ? "flagged" : ""}" title="${esc(ph.name)}\nsharpness ${ph.sharpness ?? "?"}, brightness ${ph.mean ?? "?"}${ph.flags?.length ? "\n" + ph.flags.join("\n") : ""}">
              ${ph.image ? `<img loading="lazy" src="/api/projects/${esc(p.id)}/thumb/${esc(ph.image)}">` : `<div class="ph"></div>`}
              <figcaption>${esc(ph.name)}${ph.flags?.length ? `<br><span class="flag">${esc(ph.flags.join(", "))}</span>` : ""}</figcaption>
            </figure>`).join("")}</div>
        </section>
        ${p.history.length ? `<section class="card"><h3>Run history</h3><table>
          ${p.history.map((h) => `<tr><td>${esc(h.started)}</td><td>${esc(h.preset)}</td><td>${esc(h.status)}</td><td class="num">${fmtTime(h.seconds)}</td></tr>`).join("")}
          </table></section>` : ""}
      </div>
      <div class="col view-col">
        <section class="card view-card">
          <div class="row">
            ${(["textured", "shaded", "wireframe", "points"] as ViewMode[]).map((m) => `<button class="mode" data-mode="${m}" ${p.result ? "" : "disabled"}>${m}</button>`).join("")}
            <span class="spacer"></span>
            <button data-turn="x" ${p.result ? "" : "disabled"} title="Turn 90° about X">⟲ X</button>
            <button data-turn="z" ${p.result ? "" : "disabled"} title="Turn 90° about Z">⟲ Z</button>
          </div>
          <div id="view3d">${p.result ? "" : `<div class="empty">No model yet.</div>`}</div>
          ${p.result ? `<p class="muted">${p.result.faces.toLocaleString()} faces · ${p.result.dense_points.toLocaleString()} dense points ·
            ${p.result.registered_photos ?? "?"} photos placed · size ${p.result.bbox_size.map((v) => v.toFixed(3)).join(" × ")} (${esc(p.result.units)})</p>
            <p>Download: ${p.result.exports.filter((f) => /\.(obj|ply|glb)$/i.test(f)).map((f) =>
              `<a href="/api/projects/${esc(p.id)}/exports/${esc(f)}" download>${esc(f)}</a>`).join(" · ")}
              <span class="muted">(the OBJ also needs its .mtl and texture files, all in the project's exports folder)</span></p>` : ""}
        </section>
      </div>
    </div>`;

  $("#run", d)?.addEventListener("click", async () => {
    try {
      await api(`/api/projects/${p.id}/run`, { method: "POST", body: JSON.stringify({
        preset: $<HTMLSelectElement>("#preset", d).value, exclude_flagged: $<HTMLInputElement>("#exclude", d).checked }) });
      await load(p.id);
    } catch (e) { alert((e as Error).message); }
  });
  $("#cancel", d)?.addEventListener("click", async () => {
    if (confirm("Cancel this run?")) { await api(`/api/projects/${p.id}/cancel`, { method: "POST" }); await load(p.id); }
  });
  d.querySelectorAll<HTMLButtonElement>("[data-log]").forEach((b) => b.addEventListener("click", () => {
    openLog = openLog === b.dataset.log ? null : b.dataset.log!;
    showLog(p.id);
  }));
  if (openLog) showLog(p.id);

  // 3D view: rebuild only when a new result appears.
  const key = p.result ? `${p.id}|${job?.finished}` : "";
  if (key !== viewerKey) {
    viewer?.dispose();
    viewer = null;
    viewerKey = key;
  }
  if (p.result) {
    const host = $("#view3d", d);
    if (!viewer) {
      viewer = new ScanViewer(host);
      const base = `/api/projects/${p.id}/models/`;
      viewer.loadModel(base + "model.glb", base + "points.ply").catch((e) => alert("Could not load model: " + e.message));
    } else {
      viewer.attach(host);
    }
    d.querySelectorAll<HTMLButtonElement>("[data-mode]").forEach((b) =>
      b.addEventListener("click", () => viewer?.setMode(b.dataset.mode as ViewMode)));
    d.querySelectorAll<HTMLButtonElement>("[data-turn]").forEach((b) =>
      b.addEventListener("click", () => viewer?.turn(b.dataset.turn as "x" | "z")));
  }
}

async function showLog(pid: string) {
  const pre = $<HTMLPreElement>("#log");
  if (!pre) return;
  pre.classList.toggle("hidden", !openLog);
  if (!openLog) return;
  pre.textContent = `[${openLog}.log]\n` + (await api<string>(`/api/projects/${pid}/log/${openLog}?tail=80`));
  pre.scrollTop = pre.scrollHeight;
}

async function load(pid: string) {
  window.clearTimeout(pollTimer);
  if (pid !== currentId) { openLog = null; }
  currentId = pid;
  try {
    status = await api<Status>("/api/status");
    const p = await api<Project>(`/api/projects/${pid}`);
    if (currentId !== pid) return;
    render(p);
    await refreshList();
    if (p.job?.status === "running" || status.busy) pollTimer = window.setTimeout(() => load(pid), 2000);
  } catch (e) {
    $("#detail").innerHTML = `<p class="error">${esc((e as Error).message)}</p>`;
  }
}

async function init() {
  status = await api<Status>("/api/status");
  const missing = Object.entries(status.tools).filter(([, ok]) => !ok).map(([t]) => t);
  $("#tools").textContent = missing.length ? `Missing tools: ${missing.join(", ")}` : "COLMAP + OpenMVS found";
  $("#tools").className = missing.length ? "error" : "muted";
  const form = $<HTMLFormElement>("#new-form");
  (form.elements.namedItem("folder") as HTMLInputElement).value = status.default_folder;
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const fd = new FormData(form);
    const msg = $("#new-msg");
    msg.textContent = "Copying photos…";
    try {
      const p = await api<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name: fd.get("name"), folder: fd.get("folder") }) });
      msg.textContent = `Imported ${p.photos.length} photos.`;
      location.hash = p.id;
    } catch (e) { msg.textContent = (e as Error).message; }
  });
  window.addEventListener("hashchange", () => location.hash.length > 1 && load(location.hash.slice(1)));
  await refreshList();
  if (location.hash.length > 1) load(location.hash.slice(1));
}

init();
