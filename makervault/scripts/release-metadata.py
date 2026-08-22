#!/usr/bin/env python3
"""Validate and inventory locally built MakersVault release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_record(path: Path, version: str, revision: str, created: str) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or len(value) != 1:
        raise RuntimeError(f"Unexpected Docker inspection document: {path}")
    image = value[0]
    labels = image.get("Config", {}).get("Labels") or {}
    expected = {
        "org.opencontainers.image.version": version,
        "org.opencontainers.image.revision": revision,
        "org.opencontainers.image.created": created,
        "org.opencontainers.image.source": "https://github.com/VincentCinque/MakersVault",
    }
    for key, expected_value in expected.items():
        if labels.get(key) != expected_value:
            raise RuntimeError(f"Image label mismatch for {key}: {path}")
    return {
        "id": image["Id"],
        "repo_tags": sorted(image.get("RepoTags") or []),
        "os": image.get("Os"),
        "architecture": image.get("Architecture"),
        "labels": {key: labels[key] for key in sorted(expected)},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--created", required=True)
    args = parser.parse_args()

    output = args.output_dir.resolve()
    bridge_names = sorted(
        path.name
        for path in output.glob("makersvault-bridge-*")
        if path.is_file() and not path.name.endswith(".spdx.json")
    )
    expected_bridges = sorted(
        (
            "makersvault-bridge-darwin-amd64",
            "makersvault-bridge-darwin-arm64",
            "makersvault-bridge-linux-amd64",
            "makersvault-bridge-linux-arm64",
            "makersvault-bridge-windows-amd64.exe",
            "makersvault-bridge-windows-arm64.exe",
        )
    )
    if bridge_names != expected_bridges:
        raise RuntimeError("Bridge platform artifact set is incomplete")

    manifest_path = output / "release-manifest.json"
    checksums_path = output / "SHA256SUMS"
    subjects = sorted(
        path for path in output.iterdir()
        if path.is_file() and path not in {manifest_path, checksums_path}
    )
    manifest = {
        "format": "makersvault-release-manifest",
        "format_version": 1,
        "version": args.version,
        "source_revision": args.revision,
        "source_tree": args.tree,
        "source_created_at": args.created,
        "images": {
            "api": image_record(output / "api-image-inspect.json", args.version, args.revision, args.created),
            "web": image_record(output / "web-image-inspect.json", args.version, args.revision, args.created),
        },
        "artifacts": [
            {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in subjects
        ],
        "sbom_format": "SPDX 2.3 JSON",
        "provenance": {
            "local": "immutable source revision and OCI labels recorded here",
            "published": "GitHub artifact attestations are generated only by the tag-gated release workflow",
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    checksum_subjects = sorted((*subjects, manifest_path), key=lambda path: path.name)
    checksums_path.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in checksum_subjects),
        encoding="utf-8",
    )
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
