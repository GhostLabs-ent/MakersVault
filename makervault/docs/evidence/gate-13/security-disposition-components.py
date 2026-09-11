"""Benign exact-image follow-up; no network, application startup, or vault access."""
import ctypes
import ctypes.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess


package_search = subprocess.run(
    ["dpkg-query", "--search", "*zipdetails*"],
    capture_output=True, text=True, timeout=10, check=False,
)
assert package_search.returncode in (0, 1), package_search.stderr
search_paths = sorted(set(os.environ["PATH"].split(os.pathsep)) | {
    "/usr/bin", "/usr/sbin", "/bin", "/sbin", "/usr/local/bin", "/usr/local/sbin",
})
library_name = ctypes.util.find_library("sqlite3")
assert library_name
library = ctypes.CDLL(library_name)
print(json.dumps({
    "scope": "Installed package manifests and named executable paths; dynamic symbol presence only, no vulnerable function invoked",
    "zipdetails": {
        "which": shutil.which("zipdetails"),
        "searched_paths": search_paths,
        "present_paths": [str(Path(directory) / "zipdetails") for directory in search_paths
                          if os.path.lexists(Path(directory) / "zipdetails")],
        "package_search_exit": package_search.returncode,
        "package_search_stdout": package_search.stdout,
        "package_search_stderr": package_search.stderr,
    },
    "sqlite": {
        "python_runtime": sqlite3.sqlite_version,
        "library": library_name,
        "symbols": {name: hasattr(library, name) for name in (
            "sqlite3changeset_apply", "sqlite3changeset_apply_v2", "sqlite3changeset_apply_v3",
        )},
        "limit": "Absence of one symbol is not exclusion of all SESSION code or resolution of Debian version applicability",
    },
}, sort_keys=True))
