"""Read-only dependency/image audit; fresh reports, never automatic remediation."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from verification_runtime import APP, REPO, run, install_signal_handlers

NODE = "node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293"
PYTHON = "python:3.11-slim@sha256:a630a63cdb314e2d138a2fca3e375e319e8568346ffafac5b980f888630ac4f1"
GRYPE = "anchore/grype@sha256:8a93fc48da96bd6ec5981279d099b69de11541dc68fdf222fb9161f8ff284af7"
GO = "golang:1.26.6@sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6"


def json_stream(value):
    decoder = json.JSONDecoder()
    records = []
    value = value.strip()
    while value:
        record, end = decoder.raw_decode(value)
        records.append(record)
        value = value[end:].lstrip()
    if not records:
        raise ValueError("Scanner returned no JSON evidence")
    return records


def scan(label, arguments, output):
    name = "mv-g13c-audit-" + uuid4().hex
    try:
        result = run(["docker", "run", "--rm", "--name", name, *arguments], check=False)
    finally:
        # Only the unique container this invocation attempted to create.
        run(["docker", "rm", "-f", name], check=False)
    (output / f"{label}.stderr.txt").write_bytes(result.stderr)
    (output / f"{label}.json").write_bytes(result.stdout)
    return summarize(label, result.returncode, json_stream(result.stdout.decode()))


def summarize(label, exit_code, records):
    if label.startswith("npm-"):
        report = records[0]
        if exit_code not in (0, 1) or "error" in report or "metadata" not in report:
            raise RuntimeError(f"{label}: incomplete audit, not a clean result")
        return {"exit_code": exit_code, "vulnerabilities": report["metadata"]["vulnerabilities"]}
    if label.startswith("python-"):
        report = records[0]
        if exit_code not in (0, 1) or not report.get("dependencies"):
            raise RuntimeError(f"{label}: incomplete audit, not a clean result")
        return {"exit_code": exit_code, "dependencies": len(report["dependencies"]),
                "advisories": sum(len(item.get("vulns", [])) for item in report["dependencies"]),
                "skipped": [item["name"] for item in report["dependencies"] if item.get("skip_reason")]}
    if label == "go":
        config = next((item["config"] for item in records if "config" in item), None)
        if exit_code or not config:
            raise RuntimeError("Go scan did not complete")
        # JSON mode emits database entries even when they do not affect this
        # build. Count actual findings, not those advisory inventory records.
        findings = [item["finding"] for item in records if "finding" in item]
        return {"exit_code": exit_code, "config": config, "findings": findings}
    report = records[0]
    database = report.get("descriptor", {}).get("db", {})
    if exit_code or "matches" not in report or database.get("status", {}).get("valid") is not True:
        raise RuntimeError(f"{label}: incomplete image scan, not a clean result")
    return {"exit_code": exit_code, "matches": len(report["matches"]),
            "severity": dict(Counter(item["vulnerability"]["severity"] for item in report["matches"])),
            "database": report["descriptor"]["db"], "scanner": report["descriptor"]["version"]}


def main():
    install_signal_handlers()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="new private report directory; never overwritten")
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--web-image", required=True)
    parser.add_argument("--phase", choices=("all", "languages", "images"), default="all")
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.umask(0o077)
    locks = ["api/requirements.lock", "api/requirements-dev.lock", "web/package-lock.json",
             "benchmarks/organization/package-lock.json", "benchmarks/preview/package-lock.json", "slicer-bridge/go.mod"]
    summary = {"captured_at": datetime.now(timezone.utc).isoformat(),
               "source_revision": run(["git", "-C", REPO, "rev-parse", "HEAD"]).stdout.decode().strip(),
               "lock_sha256": {name: hashlib.sha256((APP / name).read_bytes()).hexdigest() for name in locks},
               "phase": args.phase, "scans": {}, "images": {}}
    jobs = {}
    for label, directory, flags in (("npm-web", "web", []), ("npm-production", "web", ["--omit=dev"]),
                                    ("npm-organization", "benchmarks/organization", []), ("npm-preview", "benchmarks/preview", [])):
        jobs[label] = ["-v", f"{APP / directory}:/source:ro", "-w", "/source", NODE,
                       "npm", "audit", "--json", "--ignore-scripts", *flags]
    for label, lock in (("python-runtime", "requirements.lock"), ("python-development", "requirements-dev.lock")):
        jobs[label] = ["-v", f"{APP / 'api' / lock}:/audit/requirements.lock:ro", PYTHON, "sh", "-c",
                       "pip install --quiet pip-audit==2.9.0 && pip-audit --disable-pip --no-deps -r /audit/requirements.lock --format=json"]
    jobs["go"] = ["-e", "GOTELEMETRY=off", "-v", f"{APP / 'slicer-bridge'}:/src:ro", "-w", "/src", GO,
                  "sh", "-c", "go install golang.org/x/vuln/cmd/govulncheck@v1.7.0 && govulncheck -json ./..."]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {name: pool.submit(scan, name, command, args.output) for name, command in jobs.items()
                   if args.phase != "images"}
        for name, future in futures.items():
            summary["scans"][name] = future.result()
            (args.output / "partial-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
            print(f"Completed {name}", flush=True)
    with tempfile.TemporaryDirectory(prefix="makersvault-image-audit-") as temporary:
        work = Path(temporary)
        cache = work / "cache"
        cache.mkdir()
        scratch = work / "scratch"
        scratch.mkdir()
        for label, image in (("api", args.api_image), ("web", args.web_image)):
            if args.phase == "languages":
                continue
            identity = json.loads(run(["docker", "image", "inspect", image]).stdout)[0]
            summary["images"][label] = {"id": identity["Id"], "labels": identity["Config"].get("Labels", {})}
            run(["docker", "image", "save", "-o", work / f"{label}.tar", identity["Id"]])
            summary["scans"][f"image-{label}"] = scan(f"image-{label}", [
                "--user", f"{os.getuid()}:{os.getgid()}",
                "-e", "GRYPE_CHECK_FOR_APP_UPDATE=false", "-e", "GRYPE_DB_CACHE_DIR=/cache",
                "-v", f"{work}:/scan:ro", "-v", f"{cache}:/cache", "-v", f"{scratch}:/tmp", GRYPE,
                f"docker-archive:/scan/{label}.tar", "-o", "json"], args.output)
            print(f"Completed image-{label}", flush=True)
            (args.output / "partial-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    summary["status"] = "audit_completed_not_release_clearance"
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
