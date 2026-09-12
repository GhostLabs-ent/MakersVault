"""Run UP-1 against a new local web image and unchanged API in disposable HTTPS."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from uuid import uuid4

APP = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(APP / "scripts"))
from verification_runtime import DisposableStack, HOST, image_identity, install_signal_handlers, run

API = "sha256:dba3d2a7305b494d4d9a894d35fdee9743adbbf51f13c51678e98a2fcaf50b96"
BROWSER = "sha256:1e23cb1539a3e04d9b5db3fb6da8cc89694a8d1358f8e5ac726157a32536caaa"


def main():
    install_signal_handlers()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-image", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, exist_ok=False)
    api = image_identity(API, "development-gate13b", "6306ccff289d475530a6cacf4cb2e28db456ce08")
    web = image_identity(args.web_image, "development-upload-progress", args.revision)
    cases = []
    with tempfile.TemporaryDirectory(prefix="makersvault-up1-") as temporary:
        stack = DisposableStack(Path(temporary) / "stack", api, web)
        try:
            stack.start()
            for engine in ("chromium", "firefox", "webkit"):
                case = args.output / engine
                case.mkdir(mode=0o700)
                container = "mv-up1-browser-" + uuid4().hex
                env = {"MAKERSVAULT_BENCHMARK_API_URL": stack.origin + "/api",
                       "MAKERSVAULT_BENCHMARK_WEB_URL": stack.origin,
                       "MAKERSVAULT_BENCHMARK_USERNAME": stack.config["AUTH_USERNAME"],
                       "MAKERSVAULT_BENCHMARK_PASSWORD": stack.config["AUTH_PASSWORD"],
                       "MAKERSVAULT_BENCHMARK_BROWSER": engine,
                       "MAKERSVAULT_BENCHMARK_OUTPUT": "/results/result.json"}
                try:
                    result = run(["docker", "run", "--rm", "--pull", "never", "--name", container,
                                  "--network", "host", "--add-host", f"{HOST}:127.0.0.1",
                                  "--shm-size", "1g", "--memory", "4g",
                                  *[arg for key in env for arg in ("-e", key)],
                                  "-v", f"{APP / 'benchmarks'}:/bench:ro",
                                  "-v", "/bench/organization/node_modules",
                                  "-v", f"{stack.certificate}:/fixture/ca.crt:ro",
                                  "-v", f"{case}:/results", "-w", "/bench/organization", BROWSER,
                                  "sh", "-c", "npm ci --ignore-scripts --no-audit --no-fund && node tls-probe.mjs && node upload-progress-regression.mjs"],
                                 env={**os.environ, **env}, check=False)
                    (case / "stdout.log").write_bytes(result.stdout)
                    (case / "stderr.log").write_bytes(result.stderr)
                    cases.append({"engine": engine, "exit_code": result.returncode,
                                  "result": json.loads((case / "result.json").read_text()) if (case / "result.json").exists() else None})
                finally:
                    run(["docker", "rm", "-f", container], check=False)
        finally:
            stack.close()
    passed = all(case["exit_code"] == 0 and case["result"]["status"] == "passed" for case in cases) and len(cases) == 3
    report = {"status": "passed" if passed else "failed", "web_revision": args.revision,
              "images": {"api": api, "web": web, "browser": BROWSER}, "cases": cases,
              "scope": "UP-1 local HTTPS/browser qualification, not whole-gate/security acceptance or physical-device evidence"}
    (args.output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
