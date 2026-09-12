"""Inspect exact signed binary archives in a disposable container; install nothing."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

pins = dict(line.split("=", 1) for line in Path("/app/native-packages.lock").read_text().splitlines())
assert len(pins) == 6


def run(command, cwd=None, timeout=60):
    result = subprocess.run(command, cwd=cwd, capture_output=True, timeout=timeout, check=False)
    return {"command": command, "exit_code": result.returncode,
            "stdout": result.stdout.decode(errors="replace"), "stderr": result.stderr.decode(errors="replace")}


def stanza(text):
    fields = {}
    for line in text.splitlines():
        if line and not line[0].isspace() and ": " in line:
            key, value = line.split(": ", 1)
            fields[key] = value
    return fields


report = {"scope": "Signed APT indexes plus exact binary downloads and bounded archive reads; no install or application startup",
          "sources": Path("/etc/apt/sources.list.d/debian.sources").read_text(), "pins": pins, "packages": {}}
report["index_update"] = run(["apt-get", "-o", "APT::Update::Error-Mode=any",
    "-o", "Acquire::AllowInsecureRepositories=false", "-o", "APT::Get::AllowUnauthenticated=false", "update"])
try:
    assert report["index_update"]["exit_code"] == 0
    for package, version in pins.items():
        record = {}
        report["packages"][package] = record
        record["installed"] = run(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${source:Package}\t${source:Version}\n", package])
        record["metadata"] = run(["apt-cache", "show", f"{package}={version}"])
        assert record["metadata"]["exit_code"] == 0
        entries = [stanza(text) for text in record["metadata"]["stdout"].split("\n\n")]
        entry = next(row for row in entries if row.get("Version") == version and row.get("SHA256"))
        record["archive_metadata"] = {key: entry.get(key) for key in ("Package", "Version", "Source", "Architecture", "Filename", "SHA256", "Size")}
        assert int(entry["Size"]) <= 32 * 1024 * 1024
        with tempfile.TemporaryDirectory(prefix="mv-native-package-") as temporary:
            directory = Path(temporary)
            record["download"] = run(["apt-get", "-o", "APT::Get::AllowUnauthenticated=false", "download", f"{package}={version}"], cwd=directory)
            assert record["download"]["exit_code"] == 0
            archives = list(directory.glob("*.deb"))
            assert len(archives) == 1
            archive = archives[0]
            record["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
            assert record["archive_sha256"] == entry["SHA256"]
            result = subprocess.run(["dpkg-deb", "--fsys-tarfile", str(archive)], capture_output=True, timeout=30, check=True)
            assert len(result.stdout) <= 128 * 1024 * 1024
            with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as members:
                record["changelogs"] = {}
                record["installed_binary_checks"] = []
                for member in members:
                    if not member.isfile():
                        continue
                    name = member.name.removeprefix("./")
                    if name.endswith("changelog.Debian.gz"):
                        assert member.size <= 2 * 1024 * 1024
                        data = gzip.decompress(members.extractfile(member).read()).decode(errors="replace")
                        assert len(data) <= 8 * 1024 * 1024
                        lines = data.splitlines()
                        end = next((i + 1 for i, line in enumerate(lines) if line.startswith(" -- ")), len(lines))
                        record["changelogs"][name] = {"first_entry": "\n".join(lines[:end]),
                            "decompressed_sha256": hashlib.sha256(data.encode()).hexdigest()}
                    # Compare shipped executable/shared-library bytes, not generated configs/docs.
                    if name.startswith(("usr/lib/", "usr/bin/", "usr/sbin/", "lib/", "bin/", "sbin/")):
                        installed = Path("/") / name
                        assert installed.is_file(), name
                        archive_hash = hashlib.sha256(members.extractfile(member).read()).hexdigest()
                        installed_hash = hashlib.sha256(installed.read_bytes()).hexdigest()
                        assert archive_hash == installed_hash, name
                        record["installed_binary_checks"].append({"path": name, "sha256": archive_hash})
            record["status"] = "verified_archive_and_installed_binaries"
    report["status"] = "passed"
except Exception as error:
    report["status"] = "failed"
    report["error"] = repr(error)
finally:
    print(json.dumps(report, sort_keys=True))
raise SystemExit(report["status"] != "passed")
