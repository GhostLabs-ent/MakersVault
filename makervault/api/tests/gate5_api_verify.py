#!/usr/bin/env python3
"""Verify the Gate 5 fixture through supported authenticated API routes."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def request(base_url: str, path: str, token: str | None = None, body: dict | None = None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    target = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    with urllib.request.urlopen(
        urllib.request.Request(target, data=data, headers=headers), timeout=10
    ) as response:
        content = response.read()
        content_type = response.headers.get("Content-Type", "")
    return json.loads(content) if "application/json" in content_type else content


def expect_status(base_url: str, path: str, token: str, status: int) -> None:
    try:
        request(base_url, path, token)
    except urllib.error.HTTPError as exc:
        if exc.code == status:
            return
        raise
    raise AssertionError(f"Expected HTTP {status}: {path}")


def wait_for_health(base_url: str) -> None:
    last_error: Exception | None = None
    for _ in range(60):
        try:
            if request(base_url, "/health") == {"ok": True}:
                return
        except (OSError, urllib.error.URLError, ValueError) as exc:
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"API did not become healthy: {last_error}")


def verify(
    base_url: str,
    username: str,
    password: str,
    expected_path: Path,
    external_available: bool,
) -> None:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    wait_for_health(base_url)
    login = request(
        base_url,
        "/login",
        body={"username": username, "password": password},
    )
    token = login["token"]
    assets = request(base_url, "/assets?limit=100", token)
    by_id = {asset["id"]: asset for asset in assets}
    assert sorted(by_id) == expected["asset_ids"]

    assert by_id["asset-managed"]["name"] == "Renamed Bracket"
    assert by_id["asset-managed"]["filename"] == "old-bracket-name.stl"
    assert by_id["asset-managed"]["creator"] == "MakersVault Fixture"
    assert by_id["asset-managed"]["collection"] == "Workshop Upgrade"
    assert by_id["asset-interrupted"]["preview_reason"] == "worker_interrupted"
    prepared = by_id["asset-prepared"]["prepared_print"]
    assert {key: prepared[key] for key in expected["prepared_summary"]} == expected["prepared_summary"]
    assert prepared["removable"] is True

    folders = request(base_url, "/folders", token)
    parents = {folder["id"]: folder["parent_id"] for folder in folders}
    assert parents["folder-fasteners"] == "folder-workshop"
    assert parents["folder-jigs"] == "folder-workshop"

    related = request(base_url, "/asset/asset-prepared/files", token)
    assert [(item["id"], item["filename"]) for item in related] == [
        ("file-doc", "assembly.pdf")
    ]
    assert request(base_url, "/asset/asset-prepared/files/file-doc", token) == b"%PDF-1.4 gate5 assembly\n"
    assert request(base_url, "/asset/asset-prepared/prepared-print", token).endswith(b"G28\n")

    managed = request(base_url, by_id["asset-managed"]["url"], token)
    expected_hash = expected["managed_sha256"][
        "Workshop/Fasteners/Renamed Bracket/old-bracket-name.stl"
    ]
    assert hashlib.sha256(managed).hexdigest() == expected_hash
    assert request(base_url, by_id["asset-managed"]["thumb_url"], token) == b"legacy-derived-thumbnail"

    available_path = by_id["asset-external-available"]["url"]
    if external_available:
        assert request(base_url, available_path, token) == b"externally-owned-step\n"
    else:
        expect_status(base_url, available_path, token, 404)
    expect_status(base_url, by_id["asset-external-missing"]["url"], token, 404)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument(
        "--external",
        choices=("available", "unavailable"),
        required=True,
    )
    args = parser.parse_args()
    verify(
        args.base_url,
        args.username,
        args.password,
        args.expected,
        args.external == "available",
    )
    print("Gate 5 API fixture verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
