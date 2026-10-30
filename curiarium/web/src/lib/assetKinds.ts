/**
 * Asset-kind classification for the project landing page (Mf-6cxs).
 *
 * `AssetGrid` keeps its own extension sets because they drive its grid
 * affordances; these exist for the landing page's cover fallback, gallery and
 * open-in-slicer gates. The two sets intentionally agree on the model
 * extensions — if a third consumer ever appears, unify them rather than
 * adding another copy.
 */
import type { Asset } from "./api";

/** The fields needed to classify an asset; anything shaped like an Asset works. */
export type AssetKindSource = Pick<Asset, "filename" | "mime">;

/**
 * Lowercase extension without the dot. Returns "" for dotless names
 * ("README"), trailing dots ("backup.") and dotfiles (".gitignore").
 */
export function extOf(name: string): string {
  const base = name.split("/").pop() ?? name;
  const dot = base.lastIndexOf(".");
  if (dot <= 0 || dot === base.length - 1) return "";
  return base.slice(dot + 1).toLowerCase();
}

/** Extensions browsers render as `<img>` without plugins. */
const IMAGE_EXTS = new Set([
  "png",
  "jpg",
  "jpeg",
  "gif",
  "webp",
  "avif",
  "bmp",
  "svg",
  "tif",
  "tiff",
]);

/** Slicer-openable model extensions; mirrors the set in `AssetGrid`. */
const MODEL_EXTS = new Set(["stl", "3mf", "step", "stp", "obj"]);

/** True for assets that can appear in the gallery strip (mime first, then ext). */
export function isImageAsset(asset: AssetKindSource): boolean {
  const mime = (asset.mime || "").toLowerCase();
  if (mime.startsWith("image/")) return true;
  return IMAGE_EXTS.has(extOf(asset.filename));
}

/** True for 3MF containers, which can carry a usable cover thumbnail. */
export function is3mfAsset(asset: AssetKindSource): boolean {
  if (extOf(asset.filename) === "3mf") return true;
  const mime = (asset.mime || "").toLowerCase();
  // Covers both `model/3mf` and the official vendor mime
  // `application/vnd.ms-package.3dmanufacturing-3dmodel+xml`.
  return mime.includes("3mf") || mime.includes("3dmanufacturing");
}

/** True for slicer-openable files by extension; callers OR in `prepared_print`. */
export function isModelAsset(asset: AssetKindSource): boolean {
  return MODEL_EXTS.has(extOf(asset.filename));
}

/** Short uppercase type chip for compact file rows ("STL", "PDF", "FILE"). */
export function typeLabelFor(asset: AssetKindSource): string {
  const ext = extOf(asset.filename);
  return ext ? ext.toUpperCase() : "FILE";
}
