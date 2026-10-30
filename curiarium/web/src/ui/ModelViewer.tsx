import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { uploadGeneratedThumbnail } from "../lib/api";
import { PREVIEW_MAX_ATTEMPTS, PREVIEW_RETRY_MS, PREVIEW_SETTLE_MS, previewQueue } from "../lib/previewQueue";
import type { PreviewQueue, PreviewQueueStats } from "../lib/previewQueue";
import { ResolvedTheme } from "../lib/settings";
import { snapshotCache } from "../lib/snapshotCache";
import { acquireSnapshotRenderer } from "../lib/snapshotRenderer";
import { buildStepGroup } from "../lib/step/buildStepGroup";
import { parseStepInWorker, stepSizeNotice } from "../lib/step/parseStepInWorker";
import { STEP_MAX_BYTES } from "../lib/step/protocol";

type ModelViewerProps = { url: string; ext: string; assetId?: string; theme: ResolvedTheme };

type ModelPalette = {
  color: THREE.Color;
  emissive: THREE.Color;
  emissiveIntensity: number;
  metalness: number;
  roughness: number;
};

function readCssColorVar(name: string, fallback: string) {
  if (typeof window === "undefined") return new THREE.Color(fallback);
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return new THREE.Color(value || fallback);
}

function paletteForTheme(theme: ResolvedTheme): ModelPalette {
  const fallback =
    theme === "neon"
      ? "#b6ff2b"
      : theme === "purple"
        ? "#c77dff"
        : theme === "blue"
          ? "#74d4ff"
          : theme === "dark"
            ? "#e2e8f0"
            : "#cbd5e1";
  const emissiveFallback =
    theme === "neon"
      ? "#3a7a1a"
      : theme === "purple"
        ? "#6a2da8"
        : theme === "blue"
          ? "#1f5c9a"
          : theme === "dark"
            ? "#475569"
            : "#94a3b8";
  return {
    color: readCssColorVar("--mv-model-color", fallback),
    emissive: readCssColorVar("--mv-model-emissive", emissiveFallback),
    emissiveIntensity:
      theme === "neon" || theme === "purple" || theme === "blue"
        ? 0.35
        : theme === "dark"
          ? 0.08
          : 0.05,
    metalness: 0.2,
    roughness: theme === "neon" || theme === "purple" || theme === "blue" ? 0.6 : 0.8,
  };
}

function applyThemeToObject(obj: THREE.Object3D, palette: ModelPalette) {
  obj.traverse(child => {
    if (!(child instanceof THREE.Mesh)) return;
    const materials = Array.isArray(child.material) ? child.material : [child.material];
    materials.forEach(mat => {
      const typed = mat as THREE.MeshStandardMaterial;
      if (typed.color) typed.color.copy(palette.color);
      if (typed.emissive) {
        typed.emissive.copy(palette.emissive);
        typed.emissiveIntensity = palette.emissiveIntensity;
      }
      if (typeof typed.metalness === "number") typed.metalness = palette.metalness;
      if (typeof typed.roughness === "number") typed.roughness = palette.roughness;
      mat.needsUpdate = true;
    });
  });
}

export default function ModelViewer({ url, ext, assetId, theme }: ModelViewerProps) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [viewError, setViewError] = useState<string | null>(null);
  const [sizeNotice, setSizeNotice] = useState<string | null>(null);
  const [stepStatus, setStepStatus] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    let activeObject: THREE.Object3D | null = null;
    const controller = new AbortController();
    const mount = mountRef.current; 
    if (!mount) return;
    const palette = paletteForTheme(theme);
    setViewError(null);
    setSizeNotice(null);
    setStepStatus(null);
    // Progress callbacks outlive the modal: a disposed viewer must stay silent.
    const stepReport: StepLoadReport = {
      onSize: (bytes: number) => {
        if (!disposed) setSizeNotice(stepSizeNotice(bytes));
      },
      onStatus: (status: string | null) => {
        if (!disposed) setStepStatus(status);
      },
    };
    const reportError = (message: string) => {
      if (!disposed) {
        setViewError(message);
      }
    };

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1000);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(mount.clientWidth || 300, mount.clientHeight || 300);
    mount.appendChild(renderer.domElement);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 1.6));
    scene.add(new THREE.AmbientLight(0xffffff, 0.9));
    const dir1 = new THREE.DirectionalLight(0xffffff, 1.4);
    dir1.position.set(3, 6, 2);
    const dir2 = new THREE.DirectionalLight(0xffffff, 1.2);
    dir2.position.set(-4, -2, 3);
    scene.add(dir1);
    scene.add(dir2);
    camera.position.set(1, 1, 3);

    let controls: any;
    let teardown: (() => void) | undefined;
    const storageKey = assetId ? `mv-view-${assetId}` : null;

    const loadSavedView = () => {
      if (!storageKey || typeof window === "undefined") return false;
      try {
        const raw = window.localStorage.getItem(storageKey);
        if (!raw) return false;
        const data = JSON.parse(raw);
        if (!Array.isArray(data?.position) || !Array.isArray(data?.target)) return false;
        camera.position.fromArray(data.position);
        controls?.target.fromArray(data.target);
        controls?.update();
        return true;
      } catch (err) {
        console.warn("Failed to load saved view", err);
        return false;
      }
    };

    const saveView = () => {
      if (!storageKey || typeof window === "undefined" || !controls) return;
      try {
        const payload = {
          position: camera.position.toArray(),
          target: controls.target.toArray(),
        };
        window.localStorage.setItem(storageKey, JSON.stringify(payload));
      } catch {}
    };

    (async () => {
      try {
        const { OrbitControls } = await import("three/examples/jsm/controls/OrbitControls.js");
        controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.05;
        controls.enablePan = true;
        controls.target.set(0, 0, 0);
        controls.addEventListener("change", saveView);

        const centerSceneOn = (box: THREE.Box3) => {
          const size = box.getSize(new THREE.Vector3());
          const center = box.getCenter(new THREE.Vector3());
          const radius = Math.max(size.x, size.y, size.z) || 1;
          if (!loadSavedView()) {
            camera.position.copy(center).add(new THREE.Vector3(radius * 1.8, radius * 1.2, radius * 1.8));
            camera.lookAt(center);
            controls?.target.copy(center);
            controls?.update();
          }
        };

        const e = (ext || "").toLowerCase();

        try {
          const obj = await loadObjectFromAsset(e, url, controller.signal, stepReport);
          if (!obj) {
            reportError("Preview unsupported for this file type.");
            return;
          }
          if (disposed) {
            disposeObject3D(obj);
            return;
          }
          applyThemeToObject(obj, palette);
          activeObject = obj;
          scene.add(obj);
          const box = new THREE.Box3().setFromObject(obj);
          if (!box.isEmpty()) {
            centerSceneOn(box);
          }
        } catch (err) {
          // Closing the modal aborts the load; that is not a failure to report.
          if (controller.signal.aborted) return;
          console.error("Viewer asset load failed:", err);
          // The error overlay must not sit under a stale "Parsing..." pill.
          setStepStatus(null);
          reportError("Preview failed to load.");
        }
      } catch (err) {
        console.error("Viewer init failed:", err);
      }

      const onResize = () => {
        if (!mount) return;
        const w = mount.clientWidth || 300;
        const h = mount.clientHeight || 300;
        renderer.setSize(w, h);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
      };
      window.addEventListener("resize", onResize);
      teardown = () => window.removeEventListener("resize", onResize);

      const animate = () => {
        if (disposed) return;
        renderer.render(scene, camera);
        requestAnimationFrame(animate);
      };
      animate();
    })();

  return () => {
    controller.abort();
    disposed = true;
    try {
      teardown?.();
      mount.removeChild(renderer.domElement);
    } catch {}
    if (activeObject) {
      disposeObject3D(activeObject);
    }
    try {
      controls?.removeEventListener("change", saveView);
      controls?.dispose();
    } catch {}
    try {
      renderer.forceContextLoss?.();
    } catch {}
    renderer.dispose();
  };
}, [url, ext, assetId, theme]);

  return (
    <div
      ref={mountRef}
      className="w-full h-full bg-panel-soft rounded-md overflow-hidden relative"
    >
      {viewError && (
        <div className="absolute inset-0 flex items-center justify-center px-4 text-center text-sm font-medium text-red-700 dark:text-red-300 bg-panel-overlay">
          {viewError}
        </div>
      )}
      {stepStatus && (
        <div className="pointer-events-none absolute left-2 top-2 rounded-md bg-panel-overlay px-2 py-1 text-xs font-medium text-muted">
          {stepStatus}
        </div>
      )}
      <StepSizeNotice notice={sizeNotice} />
    </div>
  );
}

/** Input-only STEP progress UI, split out so it can render without WebGL. */
export function StepSizeNotice({ notice }: { notice: string | null }) {
  if (!notice) return null;
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-panel-overlay px-3 py-2 text-xs font-medium text-amber-800 dark:text-amber-200">
      {notice}
    </div>
  );
}

type SnapshotState = "idle" | "loading" | "error" | "skipped";

type SnapshotJob = (
  url: string,
  ext: string,
  width: number,
  height: number,
  theme: ResolvedTheme,
  signal: AbortSignal,
) => Promise<string>;

type ModelSnapshotProps = ModelViewerProps & {
  mode?: "automatic" | "on-demand";
  queue?: PreviewQueue;
  job?: SnapshotJob;
};

/** Thrown by snapshot generation when its card is gone; not a real failure. */
export class PreviewCancelledError extends Error {
  constructor() {
    super("Preview generation cancelled");
    this.name = "PreviewCancelledError";
  }
}

function ensureNotCancelled(signal?: AbortSignal) {
  if (signal?.aborted) throw new PreviewCancelledError();
}

export function ModelSnapshot({
  url,
  ext,
  assetId,
  mode = "automatic",
  queue = previewQueue,
  job = generateModelSnapshot,
}: ModelSnapshotProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [snapshot, setSnapshot] = useState<string | null>(null);
  const [state, setState] = useState<SnapshotState>("idle");
  const [requested, setRequested] = useState(mode === "automatic");

  useEffect(() => {
    if (mode === "automatic") setRequested(true);
  }, [mode]);

  useEffect(() => {
    let observer: IntersectionObserver | null = null;
    let settleTimer: ReturnType<typeof setTimeout> | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;
    const controller = new AbortController();
    const cacheKey = assetId ? `asset:${assetId}` : url;
    const cached = snapshotCache.get(cacheKey);
    if (cached !== undefined) {
      setSnapshot(cached);
      return () => controller.abort();
    }
    /** A dropped-but-visible card retries a bounded number of times instead of stranding. */
    const handleNoResult = (before: PreviewQueueStats) => {
      const stats = queue.getStats();
      if (stats.exhausted) {
        setState("skipped");
        return;
      }
      if (stats.timedOut > before.timedOut) {
        // A pathological model must not be re-run and burn the session budget.
        // Safe because drop/deny/abort all resolve synchronously (or are
        // pre-filtered above), so a `timedOut` delta across this await can only
        // be this job's own timeout.
        setState("error");
        return;
      }
      if (attempts >= PREVIEW_MAX_ATTEMPTS) {
        setState("error");
        return;
      }
      attempts += 1;
      setState("idle");
      retryTimer = setTimeout(() => {
        retryTimer = null;
        void load();
      }, PREVIEW_RETRY_MS * attempts);
    };
    const load = async () => {
      const container = containerRef.current;
      if (!container) return;
      setState("loading");
      try {
        const rect = container.getBoundingClientRect();
        const width = Math.max(120, Math.floor(rect.width || 240));
        const height = Math.max(120, Math.floor(rect.height || 180));
        const before = queue.getStats();
        const image = await queue.enqueue({
          signal: controller.signal,
          run: signal => job(url, ext, width, height, "light", signal),
        });
        if (controller.signal.aborted) return;
        if (image === null) {
          handleNoResult(before);
          return;
        }
        // Only after the abort check: a job whose card unmounted must never
        // write a snapshot that nothing is going to show.
        snapshotCache.set(cacheKey, image);
        setSnapshot(image);
        setState("idle");
        if (assetId) {
          try {
            const imageBlob = await fetch(image).then(response => response.blob());
            if (controller.signal.aborted) return;
            await uploadGeneratedThumbnail(assetId, imageBlob);
          } catch (err) {
            console.warn("Generated preview could not be persisted:", err);
          }
        }
      } catch (err) {
        if (controller.signal.aborted || err instanceof PreviewCancelledError) return;
        console.warn("Snapshot generation failed:", err);
        setState("error");
      }
    };
    if (!requested) {
      setState("idle");
      return () => controller.abort();
    }
    if (mode === "automatic" && typeof IntersectionObserver !== "undefined") {
      observer = new IntersectionObserver(entries => {
        if (!entries.some(entry => entry.isIntersecting)) return;
        observer?.disconnect();
        // Dwell: a card that scrolls away before this fires never enqueues.
        settleTimer = setTimeout(() => { void load(); }, PREVIEW_SETTLE_MS);
      }, { rootMargin: "240px" });
      if (containerRef.current) observer.observe(containerRef.current);
    } else {
      void load();
    }
    return () => {
      controller.abort();
      observer?.disconnect();
      if (settleTimer !== null) clearTimeout(settleTimer);
      if (retryTimer !== null) clearTimeout(retryTimer);
    };
  }, [url, ext, assetId, mode, requested, queue, job]);

  return (
    <div
      ref={containerRef}
      className="w-full h-full bg-panel-soft flex items-center justify-center rounded-md overflow-hidden"
    >
      {snapshot ? (
        <img src={snapshot} alt="Preview" className="w-full h-full object-cover" />
      ) : state === "loading" ? (
        <span className="text-xs text-muted">Generating preview...</span>
      ) : state === "skipped" ? (
        <span className="text-xs text-muted">Preview budget reached</span>
      ) : state === "error" ? (
        <span className="text-xs text-muted">Preview unavailable</span>
      ) : mode === "on-demand" && !requested ? (
        <button
          type="button"
          className="rounded-md border border-panel-strong px-3 py-2 text-xs font-medium hover:bg-panel-strong"
          onClick={event => { event.stopPropagation(); setRequested(true); }}
        >
          Generate preview
        </button>
      ) : (
        <span className="text-xs text-muted">Waiting to generate preview...</span>
      )}
    </div>
  );
}

type Simple3MFMesh = {
  positions: Float32Array;
  indices: Uint32Array;
};

type Simple3MFComponent = {
  objectId: string;
  transform?: THREE.Matrix4 | null;
  sourcePath?: string | null;
};

type Simple3MFBuildItem = {
  objectId: string;
  transform?: THREE.Matrix4 | null;
  sourcePath?: string | null;
};

type Simple3MFObject = {
  id: string;
  mesh?: Simple3MFMesh;
  components?: Simple3MFComponent[];
};

type Simple3MFDocument = {
  path: string;
  objects: Map<string, Simple3MFObject>;
  buildItems: Simple3MFBuildItem[];
};

type NamespacedNode = {
  getElementsByTagNameNS: (namespaceURI: string, localName: string) => NodeListOf<Element>;
};

async function loadSimple3MFGroup(url: string, signal?: AbortSignal): Promise<THREE.Group> {
  const resp = await fetch(url, { signal });
  if (!resp.ok) {
    throw new Error(`3MF fetch failed with status ${resp.status}`);
  }
  const raw = new Uint8Array(await resp.arrayBuffer());
  const decoder = new TextDecoder();
  const documents = new Map<string, Simple3MFDocument>();

  const enqueueDocument = (label: string, data: Uint8Array | string) => {
    const xml = typeof data === "string" ? data : decoder.decode(data);
    try {
      const doc = buildSimple3MFDocument(xml, label);
      if (doc.objects.size || doc.buildItems.length) {
        documents.set(doc.path, doc);
      }
    } catch (err) {
      console.warn(`3MF fallback parse failed for ${label}`, err);
    }
  };

  let archiveParsed = false;
  try {
    const { unzipSync } = await import("fflate");
    const zipEntries = unzipSync(raw);
    const modelEntries = Object.keys(zipEntries).filter(key => /\.model$/i.test(key));
    if (modelEntries.length) {
      archiveParsed = true;
      for (const entry of modelEntries) {
        enqueueDocument(entry, zipEntries[entry]);
      }
    }
  } catch (err) {
    console.warn("3MF fallback unzip failed, attempting inline parse", err);
  }

  if (!archiveParsed) {
    enqueueDocument("/3D/3dmodel.model", raw);
  }

  if (!documents.size) {
    throw new Error("3MF fallback: no printable geometry found");
  }

  const root = buildSceneFromDocuments(documents);
  if (!root.children.length) {
    throw new Error("3MF fallback: no printable geometry found");
  }
  return root;
}

function buildSceneFromDocuments(documents: Map<string, Simple3MFDocument>): THREE.Group {
  const root = new THREE.Group();
  const cache = new Map<string, THREE.Object3D>();

  const instantiateFromDoc = (
    docPath: string,
    objectId: string,
    stack: Set<string>
  ): THREE.Object3D | null => {
    const normalizedPath = normalizeModelPath(docPath);
    const cacheKey = `${normalizedPath}::${objectId}`;
    const cached = cache.get(cacheKey);
    if (cached) {
      return cached.clone(true);
    }
    const doc = documents.get(normalizedPath);
    if (!doc) {
      return null;
    }
    if (stack.has(cacheKey)) {
      console.warn("3MF fallback: detected recursive reference for %s", cacheKey);
      return null;
    }
    stack.add(cacheKey);
    const data = doc.objects.get(objectId);
    if (!data) {
      stack.delete(cacheKey);
      return null;
    }

    let created: THREE.Object3D | null = null;
    if (data.mesh) {
      created = meshToThreeObject(data.mesh);
    } else if (data.components?.length) {
      const group = new THREE.Group();
      for (const component of data.components) {
        const child = instantiateFromDoc(
          component.sourcePath ?? doc.path,
          component.objectId,
          stack
        );
        if (!child) continue;
        if (component.transform) {
          child.applyMatrix4(component.transform.clone());
        }
        group.add(child);
      }
      created = group;
    }
    stack.delete(cacheKey);

    if (!created) return null;
    cache.set(cacheKey, created);
    return created.clone(true);
  };

  for (const doc of documents.values()) {
    if (!doc.buildItems.length) continue;
    const docGroup = new THREE.Group();
    for (const item of doc.buildItems) {
      const built = instantiateFromDoc(
        item.sourcePath ?? doc.path,
        item.objectId,
        new Set<string>()
      );
      if (!built) continue;
      if (item.transform) {
        built.applyMatrix4(item.transform.clone());
      }
      docGroup.add(built);
    }
    if (docGroup.children.length) {
      root.add(docGroup);
    }
  }

  return root;
}

function buildSimple3MFDocument(xml: string, label: string): Simple3MFDocument {
  const parser = new DOMParser();
  const doc = parser.parseFromString(xml, "application/xml");
  if (doc.querySelector("parsererror")) {
    throw new Error("3MF fallback: invalid XML");
  }

  const path = normalizeModelPath(label);
  const objects = new Map<string, Simple3MFObject>();
  for (const objectNode of findElements(doc, "object")) {
    const id = objectNode.getAttribute("id");
    if (!id) continue;
    const entry: Simple3MFObject = { id };
    const meshNode = findFirstElement(objectNode, "mesh");
    if (meshNode) {
      const mesh = parseSimple3MFMesh(meshNode);
      if (mesh) entry.mesh = mesh;
    }
    const componentsNode = findFirstElement(objectNode, "components");
    if (componentsNode) {
      const components = parseSimple3MFComponents(componentsNode);
      if (components.length) entry.components = components;
    }
    objects.set(id, entry);
  }

  const buildNode = findFirstElement(doc, "build");
  const buildItems = buildNode ? parseSimple3MFBuildItems(buildNode) : [];
  return { path, objects, buildItems };
}

function meshToThreeObject(mesh: Simple3MFMesh): THREE.Mesh {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(mesh.positions, 3));
  geometry.setIndex(new THREE.BufferAttribute(mesh.indices, 1));
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  return new THREE.Mesh(
    geometry,
    new THREE.MeshStandardMaterial({ color: 0xf1f5f9, metalness: 0.2, roughness: 0.8 })
  );
}

function parseSimple3MFMesh(meshNode: Element): Simple3MFMesh | null {
  const vertexNodes = findElements(meshNode, "vertex");
  const triangleNodes = findElements(meshNode, "triangle");
  if (!vertexNodes.length || !triangleNodes.length) return null;

  const positions = new Float32Array(vertexNodes.length * 3);
  vertexNodes.forEach((vertex, idx) => {
    positions[idx * 3 + 0] = parseFloat(vertex.getAttribute("x") || "0");
    positions[idx * 3 + 1] = parseFloat(vertex.getAttribute("y") || "0");
    positions[idx * 3 + 2] = parseFloat(vertex.getAttribute("z") || "0");
  });

  const indices = new Uint32Array(triangleNodes.length * 3);
  triangleNodes.forEach((tri, idx) => {
    indices[idx * 3 + 0] = parseInt(tri.getAttribute("v1") || "0", 10);
    indices[idx * 3 + 1] = parseInt(tri.getAttribute("v2") || "0", 10);
    indices[idx * 3 + 2] = parseInt(tri.getAttribute("v3") || "0", 10);
  });

  return { positions, indices };
}

function parseSimple3MFComponents(node: Element): Simple3MFComponent[] {
  const components: Simple3MFComponent[] = [];
  for (const componentNode of findElements(node, "component")) {
    const objectId = componentNode.getAttribute("objectid");
    if (!objectId) continue;
    const transformAttr = componentNode.getAttribute("transform");
    const pathAttr = getAttributeByLocalName(componentNode, "path");
    components.push({
      objectId,
      transform: transformAttr ? parse3MFMatrix(transformAttr) : undefined,
      sourcePath: pathAttr ? normalizeModelPath(pathAttr) : undefined,
    });
  }
  return components;
}

function parseSimple3MFBuildItems(node: Element): Simple3MFBuildItem[] {
  const items: Simple3MFBuildItem[] = [];
  for (const itemNode of findElements(node, "item")) {
    const objectId = itemNode.getAttribute("objectid");
    if (!objectId) continue;
    const transformAttr = itemNode.getAttribute("transform");
    const pathAttr = getAttributeByLocalName(itemNode, "path");
    items.push({
      objectId,
      transform: transformAttr ? parse3MFMatrix(transformAttr) : undefined,
      sourcePath: pathAttr ? normalizeModelPath(pathAttr) : undefined,
    });
  }
  return items;
}

function parse3MFMatrix(transform: string): THREE.Matrix4 | null {
  const parts = transform
    .trim()
    .split(/\s+/)
    .map(v => parseFloat(v))
    .filter(v => !Number.isNaN(v));
  if (parts.length !== 12) return null;
  const matrix = new THREE.Matrix4();
  matrix.set(
    parts[0],
    parts[3],
    parts[6],
    parts[9],
    parts[1],
    parts[4],
    parts[7],
    parts[10],
    parts[2],
    parts[5],
    parts[8],
    parts[11],
    0,
    0,
    0,
    1
  );
  return matrix;
}

function getAttributeByLocalName(node: Element, localName: string): string | null {
  const direct = node.getAttribute(localName);
  if (direct !== null) {
    return direct;
  }
  if (typeof node.getAttributeNames === "function") {
    for (const attrName of node.getAttributeNames()) {
      const idx = attrName.indexOf(":");
      if (idx === -1) continue;
      if (attrName.slice(idx + 1) === localName) {
        const value = node.getAttribute(attrName);
        if (value !== null) {
          return value;
        }
      }
    }
  } else {
    for (const prefix of ["p", "m", "s"]) {
      const fallback = node.getAttribute(`${prefix}:${localName}`);
      if (fallback !== null) {
        return fallback;
      }
    }
  }
  return null;
}

function normalizeModelPath(path: string): string {
  const trimmed = (path || "").trim();
  if (!trimmed) return "/3D/3dmodel.model";
  let normalized = trimmed.replace(/\\/g, "/");
  normalized = normalized.replace(/^\/+/, "/");
  if (!normalized.startsWith("/")) {
    normalized = `/${normalized}`;
  }
  return normalized;
}

function findElements(node: Document | Element, localName: string) {
  const direct = Array.from(node.getElementsByTagName(localName));
  if (direct.length) return direct;
  if ("getElementsByTagNameNS" in node) {
    const nsMatches = (node as unknown as NamespacedNode).getElementsByTagNameNS("*", localName);
    return Array.from(nsMatches ?? []);
  }
  return [];
}


function findFirstElement(node: Document | Element, localName: string) {
  return findElements(node, localName)[0] ?? null;
}

/**
 * Renders a snapshot for one asset. Cancellation is cooperative: it is checked
 * at await boundaries (asset load, renderer-lock wait), and the STEP parse runs
 * in a worker that gets terminated on abort, as does the STEP/3MF download. It
 * still cannot interrupt a renderer draw, a `toDataURL` readback, or the
 * STL/OBJ XHR loads (three's loaders take no signal).
 */
async function generateModelSnapshot(
  url: string,
  ext: string,
  width: number,
  height: number,
  theme: ResolvedTheme,
  signal?: AbortSignal
) {
  const normalized = (ext || "").toLowerCase();
  ensureNotCancelled(signal);
  const object = await loadObjectFromAsset(normalized, url, signal);
  if (!object) {
    throw new Error(`Unsupported snapshot extension: ${ext}`);
  }
  try {
    ensureNotCancelled(signal);
    applyThemeToObject(object, paletteForTheme(theme));
    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 1.2));
    scene.add(new THREE.AmbientLight(0xffffff, 0.8));
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
    ensureNotCancelled(signal);
    const { renderer, release } = await acquireSnapshotRenderer();
    try {
      ensureNotCancelled(signal);
      renderer.setSize(width, height, false);
      scene.add(object);

      const box = new THREE.Box3().setFromObject(object);
      if (!box.isEmpty()) {
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        const radius = Math.max(size.x, size.y, size.z) || 1;
        camera.position.copy(center).add(new THREE.Vector3(radius * 1.8, radius * 1.3, radius * 1.6));
        camera.lookAt(center);
      } else {
        camera.position.set(1, 1, 3);
        camera.lookAt(new THREE.Vector3(0, 0, 0));
      }

      renderer.render(scene, camera);
      return renderer.domElement.toDataURL("image/png");
    } finally {
      release();
    }
  } finally {
    disposeObject3D(object);
  }
}

async function loadObjectFromAsset(
  ext: string,
  url: string,
  signal?: AbortSignal,
  report?: StepLoadReport
): Promise<THREE.Object3D | null> {
  if (ext === "stl") {
    const { STLLoader } = await import("three/examples/jsm/loaders/STLLoader.js");
    const geometry = await new Promise<THREE.BufferGeometry>((resolve, reject) => {
      new STLLoader().load(url, resolve, undefined, reject);
    });
    geometry.computeBoundingBox();
    const box = geometry.boundingBox ?? new THREE.Box3();
    const center = box.getCenter(new THREE.Vector3());
    geometry.translate(-center.x, -center.y, -center.z);
    const mesh = new THREE.Mesh(
      geometry,
      new THREE.MeshStandardMaterial({ metalness: 0.2, roughness: 0.8, color: 0xdddddd })
    );
    return mesh;
  }
  if (ext === "3mf") {
    return await load3MFObject(url, signal);
  }
  if (ext === "obj") {
    const { OBJLoader } = await import("three/examples/jsm/loaders/OBJLoader.js");
    return await new Promise<THREE.Group>((resolve, reject) => {
      new OBJLoader().load(url, resolve, undefined, reject);
    });
  }
  if (ext === "step" || ext === "stp") {
    return await loadStepObject(url, signal, report);
  }
  return null;
}

type StepLoadReport = {
  onSize(bytes: number): void;
  onStatus(status: string | null): void;
};

/**
 * Downloads a STEP file and hands the bytes to the worker, so the parser's WASM
 * module is never instantiated on this thread; only transferable geometry comes
 * back.
 */
async function loadStepObject(
  url: string,
  signal: AbortSignal | undefined,
  report?: StepLoadReport
): Promise<THREE.Group> {
  report?.onStatus("Downloading STEP file...");
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`STEP fetch failed with status ${response.status}`);
  }

  const declared = Number(response.headers.get("content-length"));
  const declaredBytes = Number.isFinite(declared) && declared > 0 ? declared : null;
  if (declaredBytes !== null) {
    report?.onSize(declaredBytes);
    // Refuse from the header alone: a 1 GB body must never be pulled into memory.
    if (declaredBytes > STEP_MAX_BYTES) {
      throw new Error(
        `STEP preview is limited to ${Math.floor(STEP_MAX_BYTES / (1024 * 1024))} MB`
      );
    }
  }

  const bytes = new Uint8Array(await response.arrayBuffer());
  ensureNotCancelled(signal);
  if (declaredBytes === null) {
    // No content-length: still warn on the real size, and still before parsing.
    report?.onSize(bytes.byteLength);
  }

  report?.onStatus("Parsing STEP off the main thread...");
  const geometry = await parseStepInWorker(bytes, { signal });
  ensureNotCancelled(signal);
  report?.onStatus(null);
  return buildStepGroup(geometry);
}

async function load3MFObject(url: string, signal?: AbortSignal) {
  try {
    return await loadSimple3MFGroup(url, signal);
  } catch (err) {
    ensureNotCancelled(signal);
    console.warn("Simple 3MF parse failed, falling back to ThreeMFLoader", err);
    return await loadViaThreeMFLoader(url);
  }
}

async function loadViaThreeMFLoader(url: string) {
  const { ThreeMFLoader } = await import("three/examples/jsm/loaders/3MFLoader.js");
  return await new Promise<THREE.Group>((resolve, reject) => {
    new ThreeMFLoader().load(url, resolve, undefined, reject);
  });
}

function disposeObject3D(obj: THREE.Object3D) {
  obj.traverse(child => {
    if (child instanceof THREE.Mesh) {
      child.geometry?.dispose();
      if (Array.isArray(child.material)) {
        child.material.forEach(mat => mat.dispose());
      } else {
        child.material?.dispose();
      }
    }
  });
}
