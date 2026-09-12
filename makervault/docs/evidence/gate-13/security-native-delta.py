"""Benign read-only follow-up to the new scanner delta; never exercises a defect."""
import ctypes
import ctypes.util
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

search = subprocess.run(["dpkg-query", "--search", "*nscd*"],
                        capture_output=True, text=True, timeout=10, check=False)
assert search.returncode in (0, 1)
paths = sorted(set(os.environ["PATH"].split(os.pathsep)) | {"/usr/sbin", "/sbin", "/usr/bin", "/bin"})
changelogs = {}
for package in ("gzip", "libc-bin", "libc6", "libpcre2-8-0", "libsqlite3-0", "perl-base"):
    file = Path("/usr/share/doc") / package / "changelog.Debian.gz"
    if not file.exists():
        changelogs[package] = {"present": False}
        continue
    with gzip.open(file, "rt", errors="replace") as stream:
        data = stream.read(1024 * 1024)
    lines = data.splitlines()
    # Only report the installed release's first entry, not all historical releases.
    end = next((i + 1 for i, line in enumerate(lines) if line.startswith(" -- ")), len(lines))
    changelogs[package] = {"present": True, "path": str(file),
                           "compressed_sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                           "first_entry": "\n".join(lines[:end]),
                           "read_limit_bytes": 1024 * 1024}
print(json.dumps({
    "scope": "Named package/command preconditions and installed distribution changelogs only; no native call-graph proof",
    "size_t_bytes": ctypes.sizeof(ctypes.c_size_t),
    "pcre2_libraries": {str(width): ctypes.util.find_library(f"pcre2-{width}") for width in (8, 16, 32)},
    "nscd": {"which": shutil.which("nscd"), "present_paths": [str(Path(folder) / "nscd")
             for folder in paths if os.path.lexists(Path(folder) / "nscd")],
             "package_search_exit": search.returncode, "package_search_stdout": search.stdout,
             "package_search_stderr": search.stderr},
    "changelogs": changelogs,
}, sort_keys=True))
