"""Read authenticated source/binary archives in a disposable exact-image container.

Download only. Do not build, install, extract a tree, apply patches or execute CVEs.
"""
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(command, cwd=None):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=60)
    record = {"command": command, "exit_code": result.returncode,
              "stdout": result.stdout, "stderr": result.stderr}
    report["commands"].append(record)
    assert result.returncode == 0, record
    return result.stdout


def stanzas(text):
    rows = []
    for block in text.strip().split("\n\n"):
        row = {}
        key = None
        for line in block.splitlines():
            if line.startswith(" ") and key:
                row[key] += "\n" + line.strip()
            elif ":" in line:
                key, value = line.split(":", 1)
                row[key] = value.strip()
        rows.append(row)
    return rows


options = ["-o", "Dir::Etc::sourcelist=/probe.sources", "-o", "Dir::Etc::sourceparts=-",
           "-o", "APT::Update::Error-Mode=any", "-o", "Acquire::AllowInsecureRepositories=false",
           "-o", "APT::Get::AllowUnauthenticated=false"]
targets = {"sqlite3": ("3.46.1-7+deb13u2", "libsqlite3-0", "3.46.1-7+deb13u2"),
           "zlib": ("1:1.3.dfsg+really1.3.1-1", "zlib1g", "1:1.3.dfsg+really1.3.1-1+b1")}
report = {"scope": "Authenticated source/binary metadata plus bounded archive reads; no install/build/exploit",
          "script_sha256": sha(Path(__file__).read_bytes()), "sources": Path("/probe.sources").read_text(),
          "commands": [], "packages": {}}
try:
    run(["apt-get", *options, "update"])
    for source, (version, binary, binary_version) in targets.items():
        package = report["packages"][source] = {"version": version, "binary": binary, "binary_version": binary_version}
        package["installed"] = run(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${source:Package}\t${source:Version}\n", binary]).strip()
        assert package["installed"].split("\t") == [binary, binary_version, source, version], package["installed"]
        metadata = next(row for row in stanzas(run(["apt-cache", *options, "showsrc", "--only-source", source]))
                        if row.get("Version") == version)
        package["source_metadata"] = metadata
        expected = {}
        for line in metadata["Checksums-Sha256"].splitlines():
            if line.strip():
                digest, size, name = line.split()
                assert "/" not in name and int(size) <= 64 * 1024 * 1024
                expected[name] = (digest, int(size))
        with tempfile.TemporaryDirectory(prefix="mv-held-source-") as scratch:
            run(["apt-get", *options, "--download-only", "--only-source", "source", f"{source}={version}"], cwd=scratch)
            package["source_archive_sha256"] = {}
            package["selected_text"] = {}
            package["patches"] = {}
            package["series"] = ""
            for file in sorted(Path(scratch).iterdir()):
                assert file.is_file() and file.name in expected, str(file)
                data = file.read_bytes()
                assert (sha(data), len(data)) == expected[file.name], file.name
                package["source_archive_sha256"][file.name] = sha(data)
                if ".tar." not in file.name:
                    continue
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
                    total = 0
                    for member in archive:
                        total += member.size
                        assert total <= 256 * 1024 * 1024
                        if not member.isfile():
                            continue
                        name = member.name.removeprefix("./")
                        selected = name.endswith(("/ext/misc/sqlar.c", "/ext/session/sqlite3session.c", "/gzwrite.c", "/gzguts.h"))
                        packaging = name in ("debian/rules", "debian/libsqlite3-0.install", "debian/zlib1g.install")
                        patch = name.startswith("debian/patches/")
                        if not (selected or packaging or patch):
                            continue
                        assert member.size <= 2 * 1024 * 1024
                        content = archive.extractfile(member).read().decode()
                        if name == "debian/patches/series":
                            package["series"] = content
                        elif patch:
                            package["patches"][name] = {"sha256": sha(content.encode()), "text": content,
                                "changed_paths": re.findall(r"^\+\+\+\s+(\S+)", content, re.MULTILINE)}
                        else:
                            package["selected_text"][name] = {"sha256": sha(content.encode()), "text": content}
            assert set(package["source_archive_sha256"]) == set(expected)
        binary_meta = next(row for row in stanzas(run(["apt-cache", *options, "show", f"{binary}={binary_version}"]))
                           if row.get("Version") == binary_version and row.get("SHA256"))
        assert int(binary_meta["Size"]) <= 16 * 1024 * 1024
        package["binary_metadata"] = binary_meta
        with tempfile.TemporaryDirectory(prefix="mv-held-binary-") as scratch:
            run(["apt-get", *options, "download", f"{binary}={binary_version}"], cwd=scratch)
            files = list(Path(scratch).glob("*.deb"))
            assert len(files) == 1
            package["binary_archive_sha256"] = sha(files[0].read_bytes())
            assert package["binary_archive_sha256"] == binary_meta["SHA256"]
            result = subprocess.run(["dpkg-deb", "--fsys-tarfile", str(files[0])], capture_output=True, timeout=30, check=True)
            assert len(result.stdout) <= 64 * 1024 * 1024
            package["installed_file_checks"] = []
            with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
                for member in archive:
                    name = member.name.removeprefix("./")
                    if member.isfile() and name.startswith(("usr/lib/", "lib/")):
                        archive_sha = sha(archive.extractfile(member).read())
                        assert sha((Path("/") / name).read_bytes()) == archive_sha
                        package["installed_file_checks"].append({"path": name, "sha256": archive_sha})
            assert package["installed_file_checks"]
    report["status"] = "passed_not_disposition"
except Exception as error:
    report["status"] = "failed"
    report["error"] = repr(error)
finally:
    print(json.dumps(report, sort_keys=True))
raise SystemExit(report["status"] != "passed_not_disposition")
