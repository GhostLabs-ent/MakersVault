"""Inspect signed APT metadata and simulate only the approved native updates.

Run only inside a disposable copy of the existing API image. Updating package
indexes writes its temporary container layer, never the host or vault volumes.
No packages are installed by this probe.
"""
import hashlib
import json
from pathlib import Path
import subprocess


TARGETS = {
    "libc6": "2.41-12+deb13u4",
    "libc-bin": "2.41-12+deb13u4",
    "libsqlite3-0": "3.46.1-7+deb13u2",
    "perl-base": "5.40.1-6+deb13u1",
    "gzip": "1.13-1+deb13u1",
    "libpcre2-8-0": "10.46-1~deb13u2",
}


def run(command, timeout=120):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    return {"command": command, "exit_code": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr}


sources = sorted(Path("/etc/apt/sources.list.d").glob("*"))
if Path("/etc/apt/sources.list").exists():
    sources.append(Path("/etc/apt/sources.list"))
record = {
    "scope": "Disposable-container signed-index update plus simulation only; no package install",
    "targets": TARGETS,
    "sources": {str(file): {"text": file.read_text(),
                            "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
                for file in sources if file.is_file()},
    "installed": run(["dpkg-query", "--show", "--showformat=${Package}\t${Version}\n", *TARGETS]),
}
record["index_update"] = run([
    "apt-get", "-o", "APT::Update::Error-Mode=any", "-o", "Acquire::AllowInsecureRepositories=false",
    "-o", "APT::Get::AllowUnauthenticated=false", "update",
])
if record["index_update"]["exit_code"] == 0:
    record["policy"] = run(["apt-cache", "policy", *TARGETS])
    record["simulation"] = run([
        "apt-get", "--simulate", "--no-install-recommends", "--only-upgrade",
        "-o", "APT::Get::AllowUnauthenticated=false", "install",
        *(f"{name}={version}" for name, version in TARGETS.items()),
    ])
print(json.dumps(record, sort_keys=True))
raise SystemExit(0 if record.get("simulation", {}).get("exit_code") == 0 else 1)
