import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { PLYLoader } from "three/addons/loaders/PLYLoader.js";

export type ViewMode = "textured" | "shaded" | "wireframe" | "points";

/** 3D viewer for one scan: textured mesh, shaded, wireframe and point cloud. */
export class ScanViewer {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(45, 1, 0.001, 1000);
  private controls: OrbitControls;
  private root = new THREE.Group(); // everything loaded; rotated by the "turn" buttons
  private meshes: THREE.Mesh[] = [];
  private textured = new Map<THREE.Mesh, THREE.Material>();
  private shadedMat = new THREE.MeshStandardMaterial({ color: 0xbbbbbb, roughness: 0.8 });
  private wireMat = new THREE.MeshBasicMaterial({ color: 0x3fa7ff, wireframe: true });
  private points: THREE.Points | null = null;
  private pointsUrl = "";
  private mode: ViewMode = "textured";
  private resizeObs: ResizeObserver;
  private disposed = false;

  constructor(private container: HTMLElement) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(this.renderer.domElement);
    this.scene.background = new THREE.Color(0x1d1f23);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.8);
    sun.position.set(1, 2, 1.5);
    this.camera.add(sun); // light follows the camera, so the shaded view is always lit
    this.scene.add(this.camera);
    this.scene.add(this.root);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.resizeObs = new ResizeObserver(() => this.resize());
    this.resizeObs.observe(container);
    this.resize();
    const loop = () => {
      if (this.disposed) return;
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
      requestAnimationFrame(loop);
    };
    loop();
  }

  /** Load the textured GLB. COLMAP's world has Y pointing down, so flip it upright. */
  async loadModel(glbUrl: string, pointsUrl: string): Promise<{ faces: number }> {
    this.pointsUrl = pointsUrl;
    const gltf = await new GLTFLoader().loadAsync(glbUrl);
    let faces = 0;
    gltf.scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      const src = m.material as THREE.MeshStandardMaterial;
      // Photogrammetry textures already contain the real lighting: show them unlit.
      const basic = new THREE.MeshBasicMaterial({ map: src.map ?? null, color: src.map ? 0xffffff : src.color });
      m.geometry.computeVertexNormals();
      this.textured.set(m, basic);
      this.meshes.push(m);
      faces += (m.geometry.index ? m.geometry.index.count : m.geometry.attributes.position.count) / 3;
    });
    this.root.add(gltf.scene);
    this.root.rotation.set(Math.PI, 0, 0);
    this.setMode(this.mode);
    this.fit();
    return { faces };
  }

  async setMode(mode: ViewMode): Promise<void> {
    this.mode = mode;
    for (const m of this.meshes) {
      m.visible = mode !== "points";
      m.material = mode === "shaded" ? this.shadedMat : mode === "wireframe" ? this.wireMat : this.textured.get(m)!;
    }
    if (mode === "points" && !this.points && this.pointsUrl) {
      const geom = await new PLYLoader().loadAsync(this.pointsUrl);
      const mat = new THREE.PointsMaterial({ size: 1.5, sizeAttenuation: false, vertexColors: geom.hasAttribute("color") });
      this.points = new THREE.Points(geom, mat);
      this.root.add(this.points);
    }
    if (this.points) this.points.visible = mode === "points";
  }

  /** Turn the model 90 degrees about X or Z, for scans that come out tilted. */
  turn(axis: "x" | "z"): void {
    const q = new THREE.Quaternion().setFromAxisAngle(
      axis === "x" ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 0, 1), Math.PI / 2);
    this.root.quaternion.premultiply(q);
    this.fit();
  }

  fit(): void {
    const target = this.meshes.length ? this.meshes : this.points ? [this.points] : [];
    const box = new THREE.Box3();
    for (const o of target) box.expandByObject(o);
    if (box.isEmpty()) return;
    const size = box.getSize(new THREE.Vector3()).length();
    const center = box.getCenter(new THREE.Vector3());
    this.controls.target.copy(center);
    this.camera.near = size / 1000;
    this.camera.far = size * 100;
    this.camera.position.copy(center).add(new THREE.Vector3(0.6, 0.4, 1).normalize().multiplyScalar(size * 1.1));
    this.camera.updateProjectionMatrix();
  }

  /** Move the canvas into a new container (the page re-renders its HTML). */
  attach(container: HTMLElement): void {
    if (container === this.container) return;
    this.resizeObs.unobserve(this.container);
    this.container = container;
    container.appendChild(this.renderer.domElement);
    this.resizeObs.observe(container);
    this.resize();
  }

  private resize(): void {
    const w = this.container.clientWidth || 1;
    const h = this.container.clientHeight || 1;
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  dispose(): void {
    this.disposed = true;
    this.resizeObs.disconnect();
    this.controls.dispose();
    this.scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.geometry) m.geometry.dispose();
    });
    for (const mat of this.textured.values()) {
      (mat as THREE.MeshBasicMaterial).map?.dispose();
      mat.dispose();
    }
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
