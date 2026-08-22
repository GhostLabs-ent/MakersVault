#!/usr/bin/env python3
"""Compare rebuilt image runtime content independent of layer packing metadata."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path


def load_release_metadata():
    path = Path(__file__).with_name("release-metadata.py")
    spec = importlib.util.spec_from_file_location("makersvault_release_metadata", path)
    if not spec or not spec.loader:
        raise RuntimeError("Cannot load release metadata helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspect(reference: str) -> dict:
    value = json.loads(
        subprocess.check_output(
            ["docker", "image", "inspect", reference], text=True
        )
    )
    if len(value) != 1:
        raise RuntimeError(f"Unexpected image inspection result: {reference}")
    return value[0]


def compare(name: str, first_ref: str, second_ref: str, helper) -> dict:
    first = inspect(first_ref)
    second = inspect(second_ref)
    first_config, first_filesystem = helper.normalized_runtime_digests(first)
    second_config, second_filesystem = helper.normalized_runtime_digests(second)
    if first_config != second_config:
        raise RuntimeError(f"{name} normalized runtime configuration differs")
    if first_filesystem != second_filesystem:
        raise RuntimeError(f"{name} normalized filesystem content differs")
    return {
        "first_image_id": first["Id"],
        "second_image_id": second["Id"],
        "layer_packing_identical": first["Id"] == second["Id"],
        "normalized_config_sha256": first_config,
        "normalized_filesystem_sha256": first_filesystem,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-first", required=True)
    parser.add_argument("--api-second", required=True)
    parser.add_argument("--web-first", required=True)
    parser.add_argument("--web-second", required=True)
    args = parser.parse_args()
    helper = load_release_metadata()
    result = {
        "api": compare("API", args.api_first, args.api_second, helper),
        "web": compare("web", args.web_first, args.web_second, helper),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
