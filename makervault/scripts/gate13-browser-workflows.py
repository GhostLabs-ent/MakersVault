"""Current browser workflows on unique production-HTTPS fixtures; no release writes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

from verification_runtime import APP, REPO, HOST, DisposableStack, image_identity, install_signal_handlers, run


def source_identity():
    revision = run(["git", "-C", REPO, "rev-parse", "HEAD"]).stdout.decode().strip()
    dirty = bool(run(["git", "-C", REPO, "status", "--porcelain", "--untracked-files=all", "--",
                      "makervault/api", "makervault/web", "makervault/scripts", "makervault/benchmarks"]).stdout)
    if dirty:
        raise ValueError("Commit verification sources before collecting browser evidence")
    return revision


def new_output(path):
    # Never reuse historical artifacts or turn an existing directory into a target.
    path = path.absolute()
    path.mkdir(mode=0o700, parents=False, exist_ok=False)
    return path


def run_case(root, output, images, browser_image, workflow, engine, profile=False):
    case = f"{workflow}-{engine}"
    case_output = output / case
    case_output.mkdir(mode=0o700)
    fixture = root / case
    fixture.mkdir()
    imports = fixture / "imports"
    imports.mkdir()
    source_files = {}
    if workflow == "mount":
        (imports / "parts").mkdir()
        source_files = {"one.stl": b"solid one\nendsolid one\n",
                        "parts/two.stl": b"solid two\nendsolid two\n",
                        "ignored.txt": b"excluded by extension\n"}
        for name, data in source_files.items():
            (imports / name).write_bytes(data)
        (imports / "rejected.stl").symlink_to("one.stl")
    stack = DisposableStack(fixture / "stack", images["api"], images["web"], imports=imports)
    container = "mv-g13-browser-" + uuid4().hex
    try:
        if workflow == "mount":
            stack.config["IMPORT_MOUNT_COPY"] = "true"
            stack.write_config()
        stack.start()
        package = "preview" if workflow == "preview" else "organization"
        script = {"organization": "organization-baseline.mjs", "preview": "preview-baseline.mjs",
                  "mount": "mount-scan-verification.mjs", "ordering": "request-order-regression.mjs"}[workflow]
        benchmark_env = {
            "MAKERSVAULT_BENCHMARK_API_URL": stack.origin + "/api",
            "MAKERSVAULT_BENCHMARK_WEB_URL": stack.origin,
            "MAKERSVAULT_BENCHMARK_USERNAME": stack.config["AUTH_USERNAME"],
            "MAKERSVAULT_BENCHMARK_PASSWORD": stack.config["AUTH_PASSWORD"],
            "MAKERSVAULT_BENCHMARK_BROWSER": engine,
            "MAKERSVAULT_BENCHMARK_OUTPUT": "/results/baseline.json",
            "MAKERSVAULT_MOUNT_SCAN_OUTPUT": "/results/baseline.json",
            "MAKERSVAULT_BENCHMARK_CORPUS": "/corpus",
            "MAKERSVAULT_ORGANIZATION_ASSETS": "600",
        }
        if profile:
            benchmark_env["MAKERSVAULT_CHROMIUM_PROFILE"] = "1"
        environment = {**os.environ, **benchmark_env}
        mounts = ["-v", f"{APP / 'benchmarks'}:/bench:ro", "-v", f"/bench/{package}/node_modules",
                  "-v", f"{stack.certificate}:/fixture/ca.crt:ro", "-v", f"{case_output}:/results"]
        if workflow == "preview":
            corpus = fixture / "corpus"
            run(["python3", APP / "benchmarks/preview/generate_corpus.py", "--output", corpus])
            mounts += ["-v", f"{corpus}:/corpus:ro"]
            (case_output / "corpus-manifest.json").write_bytes((corpus / "manifest.json").read_bytes())
            # The TLS probe resolves Playwright from the organization package.
            mounts += ["-v", "/bench/organization/node_modules"]
        env_args = [arg for key in benchmark_env for arg in ("-e", key)]
        setup = "npm ci --ignore-scripts --no-audit --no-fund"
        if workflow == "preview":
            setup += " && npm ci --prefix /bench/organization --ignore-scripts --no-audit --no-fund"
        command = setup + " && node /bench/organization/tls-probe.mjs && node " + script
        result = run(["docker", "run", "--rm", "--name", container, "--network", "host",
                      "--add-host", f"{HOST}:127.0.0.1", "--shm-size", "1g", "--memory", "4g",
                      *env_args, *mounts, "-w", f"/bench/{package}", browser_image,
                      "sh", "-c", command], env=environment, check=False)
        (case_output / "stdout.txt").write_bytes(result.stdout)
        (case_output / "stderr.txt").write_bytes(result.stderr)
        source_preserved = all((imports / name).read_bytes() == data for name, data in source_files.items())
        if workflow == "mount":
            source_preserved = source_preserved and (imports / "rejected.stl").readlink() == Path("one.stl")
        passed = result.returncode == 0 and (case_output / "baseline.json").is_file() and source_preserved
        return {"case": case, "status": "passed" if passed else "failed", "exit_code": result.returncode,
                "scope": "functional probes and metrics collection; preview budgets require review" if workflow == "preview"
                         else "workflow assertions (including existing budgets for organization)",
                "mounted_source_preserved": source_preserved if workflow == "mount" else None,
                "fixture_certificate_sha256": hashlib.sha256(stack.certificate.read_bytes()).hexdigest()}
    finally:
        # A timeout/interruption of docker's client must not orphan its container.
        run(["docker", "rm", "-f", container], check=False)
        stack.close()


def main():
    install_signal_handlers()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--web-image", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--revision", required=True, help="application image revision, separately from harness source")
    parser.add_argument("--browser-image", required=True, help="local browser-runtime build; resolved to an immutable ID")
    parser.add_argument("--output", required=True, type=Path, help="new private directory; never overwritten")
    parser.add_argument("--workflows", nargs="+", choices=("organization", "preview", "mount", "ordering"), default=["ordering", "organization", "preview", "mount"])
    parser.add_argument("--browsers", nargs="+", choices=("chromium", "firefox", "webkit"), default=["chromium", "firefox", "webkit"])
    parser.add_argument("--profile-chromium", action="store_true", help="private diagnostic traces; organization/Chromium only, not qualification timing")
    args = parser.parse_args()
    if args.profile_chromium and (args.workflows != ["organization"] or args.browsers != ["chromium"]):
        parser.error("--profile-chromium requires --workflows organization --browsers chromium")
    harness_revision = source_identity()
    images = {name: image_identity(image, args.version, args.revision)
              for name, image in (("api", args.api_image), ("web", args.web_image))}
    browser_image = json.loads(run(["docker", "image", "inspect", args.browser_image]).stdout)[0]["Id"]
    output = new_output(args.output)
    summary = {"captured_at": datetime.now(timezone.utc).isoformat(), "harness_revision": harness_revision,
               "application_revision": args.revision, "application_version": args.version,
               "diagnostic_profile": args.profile_chromium,
               "images": images, "browser_image": browser_image, "status": "in_progress", "cases": [],
               "scope": "Linux headless workflow checks; preview metrics need separate review; not physical passkeys, native workstation launch or a release qualification"}
    def save():
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    save()
    try:
        with tempfile.TemporaryDirectory(prefix="makersvault-g13-browser-") as temporary:
            for workflow in dict.fromkeys(args.workflows):
                engines = list(dict.fromkeys(args.browsers)) if workflow == "organization" else ["chromium"]
                for engine in engines:
                    print(f"Running {workflow}/{engine} on disposable production HTTPS", flush=True)
                    summary["cases"].append(run_case(Path(temporary), output, images, browser_image, workflow, engine, args.profile_chromium))
                    save()
        assert source_identity() == harness_revision, "Verification sources changed during the run"
        summary["status"] = "passed" if all(case["status"] == "passed" for case in summary["cases"]) else "failed"
    except BaseException as error:
        summary["status"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
        summary["error_type"] = type(error).__name__
        raise
    finally:
        save()
    print(json.dumps(summary, sort_keys=True))
    if summary["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
