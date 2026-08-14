import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import {
  Asset,
  requestPreviewRetry,
  updatePreviewState,
  uploadGeneratedThumbnail,
} from "../lib/api";
import {
  PreviewJobError,
  PreviewQueueFullError,
  createPreviewJob,
  type PreviewGeometry,
  type PreviewJobHandle,
} from "../lib/previewJobs";
import { ResolvedTheme } from "../lib/settings";

type ModelViewerProps = {
  url: string;
  ext: string;
  assetId?: string;
  assetSize?: number;
  requireConfirmation?: boolean;
  theme: ResolvedTheme;
};

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

export default function ModelViewer({
  url,
  ext,
  assetId,
  assetSize,
  requireConfirmation = false,
  theme,
}: ModelViewerProps) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const activeDetailJobRef = useRef<PreviewJobHandle<PreviewGeometry> | null>(null);
  const detailCancelledRef = useRef(false);
  const [viewError, setViewError] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(!requireConfirmation);
  const [loading, setLoading] = useState(!requireConfirmation);
  const [retryable, setRetryable] = useState(false);
  const [retryAttempt, setRetryAttempt] = useState(0);

  useEffect(() => {
    let disposed = false;
    let activeObject: THREE.Object3D | null = null;
    let detailJob: PreviewJobHandle<PreviewGeometry> | null = null;
    const mount = mountRef.current;
    if (!mount || !confirmed) return;
    const palette = paletteForTheme(theme);
    detailCancelledRef.current = false;
    setViewError(null);
    setRetryable(false);
    setLoading(true);
    const reportError = (message: string) => {
      if (!disposed) {
        setViewError(message);
        setLoading(false);
      }
    };

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1000);
    let renderer: THREE.WebGLRenderer | null = null;

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
    const renderAndSaveView = () => {
      saveView();
      renderer?.render(scene, camera);
    };

    (async () => {
      try {
        await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
        if (disposed) return;
        renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true, powerPreference: "low-power" });
        renderer.setPixelRatio(1);
        renderer.setSize(
          Math.min(mount.clientWidth || 300, 640),
          Math.min(mount.clientHeight || 300, 480),
          false,
        );
        renderer.domElement.style.width = "100%";
        renderer.domElement.style.height = "100%";
        mount.appendChild(renderer.domElement);

        await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
        if (disposed || !renderer) return;

        scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 1.6));
        scene.add(new THREE.AmbientLight(0xffffff, 0.9));
        const dir1 = new THREE.DirectionalLight(0xffffff, 1.4);
        dir1.position.set(3, 6, 2);
        const dir2 = new THREE.DirectionalLight(0xffffff, 1.2);
        dir2.position.set(-4, -2, 3);
        scene.add(dir1);
        scene.add(dir2);
        camera.position.set(1, 1, 3);

        await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
        if (disposed || !renderer) return;
        const { OrbitControls } = await import("three/examples/jsm/controls/OrbitControls.js");
        controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = false;
        controls.enablePan = true;
        controls.target.set(0, 0, 0);
        controls.addEventListener("change", renderAndSaveView);

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
          if (e === "step" || e === "stp") {
            reportError("Interactive STEP preview is not available in this browser. Download the model to inspect it in your CAD or slicer application.");
          } else {
            const rect = mount.getBoundingClientRect();
            const createdJob = await createPreviewJob({
              url,
              ext: e,
              width: Math.max(300, Math.floor(rect.width || 900)),
              height: Math.max(300, Math.floor(rect.height || 600)),
              mode: "geometry",
              detail: true,
              byteSize: assetSize,
            });
            detailJob = createdJob;
            activeDetailJobRef.current = createdJob;
            if (detailCancelledRef.current) {
              createdJob.cancel();
              return;
            }
            if (disposed) {
              createdJob.cancel();
              return;
            }
            const previewGeometry = await createdJob.promise;
            if (activeDetailJobRef.current === createdJob) activeDetailJobRef.current = null;
            if (disposed) return;
            const geometry = new THREE.BufferGeometry();
            geometry.setAttribute("position", new THREE.BufferAttribute(previewGeometry.positions, 3));
            geometry.setAttribute("normal", new THREE.BufferAttribute(previewGeometry.normals, 3));
            geometry.setIndex(new THREE.BufferAttribute(previewGeometry.indices, 1));
            geometry.computeBoundingSphere();
            const obj = new THREE.Mesh(
              geometry,
              new THREE.MeshLambertMaterial({ color: 0xdddddd }),
            );
            applyThemeToObject(obj, palette);
            activeObject = obj;
            scene.add(obj);
            const box = new THREE.Box3().setFromObject(obj);
            if (!box.isEmpty()) centerSceneOn(box);
          }
        } catch (err) {
          activeDetailJobRef.current = null;
          console.error("Viewer asset load failed:", err);
          if (err instanceof PreviewJobError) {
            if (err.reason === "cancelled") return;
            setRetryable(err.reason === "timeout" || err.reason === "invalid_geometry");
            reportError(previewReasonLabel(err.reason).replace("automatic preview", "interactive preview"));
          } else if (err instanceof PreviewQueueFullError) {
            setRetryable(true);
            reportError("Preview work is busy. Try the interactive preview again in a moment.");
          } else {
            setRetryable(true);
            reportError("Preview failed to load.");
          }
        }
      } catch (err) {
        console.error("Viewer init failed:", err);
        setRetryable(true);
        reportError("The interactive viewer could not start.");
      }

      const onResize = () => {
        if (!mount || !renderer) return;
        const w = mount.clientWidth || 300;
        const h = mount.clientHeight || 300;
        renderer.setSize(Math.min(w, 640), Math.min(h, 480), false);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.render(scene, camera);
      };
      window.addEventListener("resize", onResize);
      teardown = () => window.removeEventListener("resize", onResize);

      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
      if (disposed || !renderer) return;
      renderer.render(scene, camera);
      requestAnimationFrame(() => {
        if (disposed) return;
        setLoading(false);
      });
    })();

  return () => {
    disposed = true;
    detailJob?.cancel();
    activeDetailJobRef.current = null;
    try {
      teardown?.();
      if (renderer) mount.removeChild(renderer.domElement);
    } catch {}
    if (activeObject) {
      disposeObject3D(activeObject);
    }
    try {
      controls?.removeEventListener("change", renderAndSaveView);
      controls?.dispose();
    } catch {}
    try {
      renderer?.forceContextLoss?.();
    } catch {}
    renderer?.dispose();
  };
}, [url, ext, assetId, assetSize, confirmed, retryAttempt, theme]);

  if (!confirmed) {
    return (
      <div className="w-full h-full bg-panel-soft rounded-md flex items-center justify-center px-6 text-center">
        <div>
          <div className="text-sm font-semibold text-primary">Interactive preview paused</div>
          <div className="mt-1 text-xs text-muted">This model exceeds the automatic preview policy. Opening it uses the larger, bounded detail-view budget.</div>
          <button
            type="button"
            className="mt-3 rounded-md border border-panel-strong px-3 py-2 text-xs font-medium hover:bg-panel-strong"
            onClick={() => setConfirmed(true)}
          >
            Try interactive preview
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={mountRef}
      data-detail-preview-state={viewError ? "error" : loading ? "loading" : "ready"}
      className="w-full h-full bg-panel-soft rounded-md overflow-hidden relative"
    >
      {loading && !viewError && (
        <div className="absolute inset-0 z-10 flex items-center justify-center text-sm text-muted bg-panel-overlay">
          <div className="text-center">
            <div>Preparing interactive preview...</div>
            <button
              type="button"
              className="mt-3 rounded-md border border-panel-strong px-3 py-2 text-xs font-medium hover:bg-panel-strong"
              onClick={() => {
                detailCancelledRef.current = true;
                activeDetailJobRef.current?.cancel();
                activeDetailJobRef.current = null;
                setLoading(false);
                setRetryable(true);
                setViewError("Interactive preview cancelled.");
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {viewError && (
        <div className="absolute inset-0 z-10 flex items-center justify-center px-4 text-center text-sm font-medium text-red-700 dark:text-red-300 bg-panel-overlay">
          <div>
            <div>{viewError}</div>
            {retryable && (
              <button
                type="button"
                className="mt-3 rounded-md border border-current px-3 py-2 text-xs"
                onClick={() => setRetryAttempt(value => value + 1)}
              >
                Try again
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

type SnapshotState = "idle" | "queued" | "loading" | "failed" | "skipped";
type ModelSnapshotProps = ModelViewerProps & {
  mode?: "automatic" | "on-demand";
  previewStatus: Asset["preview_status"];
  previewReason?: string | null;
  onAssetChanged?: (asset: Asset) => void;
};

const snapshotCache = new Map<string, string>();

const previewReasonLabel = (reason?: string | null) => {
  switch (reason) {
    case "file_too_large": return "This model is too large for an automatic preview.";
    case "too_many_triangles": return "This model is too complex for an automatic preview.";
    case "archive_entries":
    case "archive_expanded": return "This 3MF is too complex for an automatic preview.";
    case "step_manual_only": return "STEP previews are available from model details.";
    case "timeout": return "Preview generation timed out.";
    case "malformed_stl": return "MakersVault could not read this STL preview.";
    case "malformed_obj": return "MakersVault could not read this OBJ preview.";
    case "malformed_3mf": return "MakersVault could not read this 3MF preview.";
    default: return "MakersVault could not read this model preview.";
  }
};

export function ModelSnapshot({
  url,
  ext,
  assetId,
  mode = "automatic",
  previewStatus,
  previewReason,
  onAssetChanged,
}: ModelSnapshotProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [snapshot, setSnapshot] = useState<string | null>(null);
  const effectiveStatus = previewStatus === "ready" ? "pending" : previewStatus;
  const [state, setState] = useState<SnapshotState>(
    effectiveStatus === "failed" ? "failed" : effectiveStatus === "skipped_policy" ? "skipped" : "idle",
  );
  const [reason, setReason] = useState(previewReason || null);
  const [requested, setRequested] = useState(
    effectiveStatus === "retry_requested" || (mode === "automatic" && effectiveStatus === "pending"),
  );
  const [queueAttempt, setQueueAttempt] = useState(0);

  useEffect(() => {
    const status = previewStatus === "ready" ? "pending" : previewStatus;
    setReason(previewReason || null);
    if (status === "failed") {
      setState("failed");
      setRequested(false);
    } else if (status === "skipped_policy") {
      setState("skipped");
      setRequested(false);
    }
    else if (status === "retry_requested" || (mode === "automatic" && status === "pending")) setRequested(true);
  }, [mode, previewStatus, previewReason]);

  useEffect(() => {
    let disposed = false;
    let observer: IntersectionObserver | null = null;
    let retryTimer = 0;
    let jobHandle: PreviewJobHandle<Blob> | null = null;
    const cacheKey = assetId ? `asset:${assetId}` : url;
    if (snapshotCache.has(cacheKey)) {
      setSnapshot(snapshotCache.get(cacheKey)!);
      return;
    }
    const load = async () => {
      if (!containerRef.current) return;
      setState("queued");
      try {
        const rect = containerRef.current.getBoundingClientRect();
        const width = Math.max(120, Math.floor(rect.width || 240));
        const height = Math.max(120, Math.floor(rect.height || 180));
        jobHandle = await createPreviewJob({
          url,
          ext,
          width,
          height,
          mode: "thumbnail",
          onStart: async () => {
            if (disposed) return;
            setState("loading");
            if (assetId) {
              try {
                onAssetChanged?.(await updatePreviewState(assetId, { status: "pending" }));
              } catch (error) {
                console.warn("Preview start state could not be persisted:", error);
              }
            }
          },
        });
        if (disposed) {
          jobHandle.cancel();
          return;
        }
        const blob = await jobHandle.promise;
        if (disposed) return;
        const objectUrl = URL.createObjectURL(blob);
        snapshotCache.set(cacheKey, objectUrl);
        setSnapshot(objectUrl);
        setState("idle");
        setReason(null);
        if (assetId) {
          try {
            onAssetChanged?.(await uploadGeneratedThumbnail(assetId, blob));
          } catch (err) {
            console.warn("Generated preview could not be persisted:", err);
          }
        }
      } catch (err) {
        if (disposed) return;
        if (err instanceof PreviewQueueFullError) {
          setState("queued");
          retryTimer = window.setTimeout(() => setQueueAttempt(value => value + 1), 350);
          return;
        }
        if (err instanceof PreviewJobError && err.reason === "cancelled") return;
        if (!(err instanceof PreviewJobError)) {
          console.warn("Snapshot generation failed:", err);
        }
        const jobError = err instanceof PreviewJobError
          ? err
          : new PreviewJobError("invalid_geometry", "Preview generation failed");
        const nextState = jobError.skipped ? "skipped" : "failed";
        setState(nextState);
        setReason(jobError.reason);
        if (assetId) {
          try {
            const updated = await updatePreviewState(assetId, {
              status: jobError.skipped ? "skipped_policy" : "failed",
              reason: jobError.reason,
            });
            onAssetChanged?.(updated);
          } catch (stateError) {
            console.warn("Preview state could not be persisted:", stateError);
          }
        }
      }
    };
    if (!requested || previewStatus === "failed" || previewStatus === "skipped_policy") {
      if (previewStatus === "failed") setState("failed");
      else if (previewStatus === "skipped_policy") setState("skipped");
      else setState("idle");
      return () => { disposed = true; };
    }
    if (mode === "automatic" && typeof IntersectionObserver !== "undefined") {
      observer = new IntersectionObserver(entries => {
        if (!entries.some(entry => entry.isIntersecting)) return;
        observer?.disconnect();
        void load();
      }, { rootMargin: "240px" });
      if (containerRef.current) observer.observe(containerRef.current);
    } else {
      void load();
    }
    return () => {
      disposed = true;
      observer?.disconnect();
      window.clearTimeout(retryTimer);
      jobHandle?.cancel();
    };
  }, [url, ext, assetId, mode, requested, queueAttempt, onAssetChanged, previewStatus]);

  const retry = async (event: React.MouseEvent) => {
    event.stopPropagation();
    if (assetId) {
      try {
        onAssetChanged?.(await requestPreviewRetry(assetId));
      } catch (error) {
        console.warn("Preview retry could not be requested:", error);
        return;
      }
    }
    setReason(null);
    setState("idle");
    setRequested(true);
    setQueueAttempt(value => value + 1);
  };

  return (
    <div
      ref={containerRef}
      data-preview-state={snapshot ? "ready" : state}
      className="w-full h-full bg-panel-soft flex items-center justify-center rounded-md overflow-hidden"
    >
      {snapshot ? (
        <img src={snapshot} alt="Preview" className="w-full h-full object-cover" />
      ) : state === "loading" ? (
        <span className="text-xs text-muted">Generating preview...</span>
      ) : state === "queued" ? (
        <span className="text-xs text-muted">Preview queued</span>
      ) : state === "skipped" ? (
        <div className="px-4 text-center text-xs text-muted">
          <div className="font-semibold text-primary">Preview paused</div>
          <div className="mt-1">{previewReasonLabel(reason)}</div>
        </div>
      ) : state === "failed" ? (
        <div className="px-4 text-center text-xs text-muted">
          <div className="font-semibold text-primary">Preview unavailable</div>
          <div className="mt-1">{previewReasonLabel(reason)}</div>
          <button type="button" className="mt-2 underline underline-offset-2" onClick={retry}>Retry preview</button>
        </div>
      ) : mode === "on-demand" && !requested ? (
        <button
          type="button"
          className="rounded-md border border-panel-strong px-3 py-2 text-xs font-medium hover:bg-panel-strong"
          onClick={event => { event.stopPropagation(); setRequested(true); }}
        >
          Generate preview
        </button>
      ) : (
        <span className="text-xs text-muted">Preview queued</span>
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

async function loadSimple3MFGroup(url: string): Promise<THREE.Group> {
  const resp = await fetch(url);
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

async function loadObjectFromAsset(ext: string, url: string): Promise<THREE.Object3D | null> {
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
    return await load3MFObject(url);
  }
  if (ext === "obj") {
    const { OBJLoader } = await import("three/examples/jsm/loaders/OBJLoader.js");
    return await new Promise<THREE.Group>((resolve, reject) => {
      new OBJLoader().load(url, resolve, undefined, reject);
    });
  }
  return null;
}

async function load3MFObject(url: string) {
  try {
    return await loadSimple3MFGroup(url);
  } catch (err) {
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
