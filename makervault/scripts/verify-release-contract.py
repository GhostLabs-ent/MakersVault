#!/usr/bin/env python3
"""Fail when v5.1 release identity or publication safety drifts."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "makervault"
VERSION = "5.1.0"
TAG = f"v{VERSION}"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def require(value: bool, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def main() -> int:
    package = json.loads(read(APP / "web/package.json"))
    lock = json.loads(read(APP / "web/package-lock.json"))
    require(package["version"] == VERSION, "Web package version drifted")
    require(lock["version"] == VERSION, "Web lock root version drifted")
    require(lock["packages"][""]["version"] == VERSION, "Web lock package version drifted")

    compose = read(APP / "docker-compose.deploy.yml")
    example = read(APP / ".env.example")
    require(f"makersvault-api:{TAG}" in compose and f"makersvault-web:{TAG}" in compose,
            "Production Compose must default to the matched versioned images")
    require(f"makersvault-api:{TAG}" in example and f"makersvault-web:{TAG}" in example,
            "Environment example must default to the matched versioned images")
    require(":latest" not in compose and ":latest" not in example,
            "Moving image tags are not permitted in production defaults")

    api_dockerfile = read(APP / "api/Dockerfile")
    web_dockerfile = read(APP / "web/Dockerfile")
    for image in (
        "python:3.11-slim@sha256:",
        "node:20-alpine@sha256:",
        "nginxinc/nginx-unprivileged:1.27-alpine@sha256:",
    ):
        require(image in api_dockerfile + web_dockerfile, f"Base image is not digest-pinned: {image}")

    workflow = read(ROOT / ".github/workflows/release.yml")
    require("workflow_dispatch" not in workflow, "Publication workflow must be tag-gated only")
    require(":latest" not in workflow, "Publication workflow must not publish latest")
    require("environment: release" in workflow, "Publication requires the release environment")
    require("push-to-registry: true" in workflow, "Image attestations must reach the registry")
    uses = re.findall(r"^\s*uses:\s*([^\s#]+)", workflow, flags=re.MULTILINE)
    require(bool(uses), "Publication workflow has no actions")
    for action in uses:
        require(bool(re.search(r"@[0-9a-f]{40}$", action)), f"Action is not commit-pinned: {action}")

    required_files = (
        ROOT / "CHANGELOG.md",
        ROOT / "SECURITY.md",
        ROOT / "CONTRIBUTING.md",
        APP / "docs/BACKUP_AND_RECOVERY.md",
        APP / "docs/UPGRADE_V5.1.md",
        APP / "docs/KNOWN_LIMITATIONS.md",
        APP / "docs/RELEASE_NOTES_v5.1.0.md",
        ROOT / ".github/ISSUE_TEMPLATE/bug_report.yml",
        ROOT / ".github/ISSUE_TEMPLATE/feature_request.yml",
        ROOT / ".github/ISSUE_TEMPLATE/config.yml",
    )
    for path in required_files:
        require(path.is_file() and path.stat().st_size > 0, f"Release document is missing: {path}")

    for path in (
        APP / "scripts/build-release.sh",
        APP / "scripts/release-metadata.py",
        APP / "scripts/backup.sh",
        APP / "scripts/restore.sh",
    ):
        require(path.is_file() and os.access(path, os.X_OK), f"Release script is not executable: {path}")

    print(f"Release contract verified for {TAG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
