"""Read-only installed-package inventory; fail if any approved pin is not installed."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("lock", type=Path)
args = parser.parse_args()
data = args.lock.read_bytes()
pins = dict(line.split("=", 1) for line in data.decode().splitlines())
assert len(pins) == 6
result = subprocess.run(
    ["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${db:Status-Status}\n"],
    capture_output=True, text=True, timeout=30, check=True,
)
installed = {}
for line in result.stdout.splitlines():
    package, version, status = line.split("\t")
    if status == "installed":
        installed[package.split(":", 1)[0]] = version
mismatches = {name: {"expected": version, "actual": installed.get(name)}
              for name, version in pins.items() if installed.get(name) != version}
print(json.dumps({"status": "failed" if mismatches else "passed", "pins": pins,
                  "lock_sha256": hashlib.sha256(data).hexdigest(),
                  "installed": installed, "mismatches": mismatches}, sort_keys=True))
raise SystemExit(bool(mismatches))
