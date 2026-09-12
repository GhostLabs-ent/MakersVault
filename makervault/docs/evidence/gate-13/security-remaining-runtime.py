"""Bounded exact-image component/available-version review; no install or CVE input."""
import ctypes
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess


report = {"script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "commands": []}


def run(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    report["commands"].append({"command": command, "exit_code": result.returncode,
                               "stdout": result.stdout, "stderr": result.stderr})
    assert result.returncode == 0
    return result.stdout


try:
    options = ["-o", "APT::Update::Error-Mode=any", "-o", "Acquire::AllowInsecureRepositories=false",
               "-o", "APT::Get::AllowUnauthenticated=false"]
    report["apt_sources"] = {str(p): p.read_text() for p in sorted(Path("/etc/apt/sources.list.d").glob("*.sources"))}
    run(["apt-get", *options, "update"])
    packages = ["libc6", "libc-bin", "libsqlite3-0"]
    report["installed"] = run(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${source:Package}\t${source:Version}\n", *packages])
    report["apt_policy"] = run(["apt-cache", "policy", *packages])
    libc = ctypes.CDLL("libc.so.6")
    report["libc_symbols"] = {name: hasattr(libc, name) for name in ["strfmon", "strfmon_l", "tdelete", "iconv", "iconv_open"]}
    files = [Path("/usr/lib/x86_64-linux-gnu/libc.so.6"),
             Path("/usr/lib/x86_64-linux-gnu/libsqlite3.so.0.8.6")]
    report["library_sha256"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    report["gconv_modules"] = {}
    for name in ["SHIFT_JISX0213.so", "EUC-JISX0213.so"]:
        file = Path("/usr/lib/x86_64-linux-gnu/gconv") / name
        report["gconv_modules"][name] = {"exists": file.is_file(),
            "sha256": hashlib.sha256(file.read_bytes()).hexdigest() if file.is_file() else None}
    report["iconv_aliases"] = [line.strip() for line in run(["iconv", "-l"]).splitlines()
                               if "JISX0213" in line.upper()]
    with sqlite3.connect(":memory:") as connection:
        report["sqlite_version"] = sqlite3.sqlite_version
        report["sqlite_compile_options"] = [row[0] for row in connection.execute("PRAGMA compile_options")]
        report["python_connection_changeset_members"] = [name for name in dir(connection)
                                                         if "changeset" in name.lower() or "session" in name.lower()]
    report["status"] = "passed_observations_not_disposition"
except Exception as error:
    report["status"] = "failed"
    report["error"] = repr(error)
finally:
    print(json.dumps(report, sort_keys=True))
raise SystemExit(report["status"] != "passed_observations_not_disposition")
