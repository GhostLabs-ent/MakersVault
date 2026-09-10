"""Benign runtime inspection only; no application startup, network or vault reads."""
import importlib.metadata
import json
import platform
import sqlite3
import struct
import subprocess
import sys
import zlib
from xml.parsers import expat

database = sqlite3.connect(":memory:")
options = [row[0] for row in database.execute("PRAGMA compile_options")]
functions = [row[0] for row in database.execute("PRAGMA function_list")]
database.close()
perl = subprocess.run(["perl", "-MConfig", "-e", 'print "$Config{archname}\\n$Config{ptrsize}\\n";'], capture_output=True, text=True, timeout=5)
modules = {}
for name in ("Archive::Tar", "Storable", "Socket", "File::Temp", "File::Find", "Encode", "Locale::Maketext", "HTTP::Tiny", "IO::Uncompress::Unzip", "IO::Compress", "File::GlobMapper"):
    result = subprocess.run(["perl", "-M" + name, "-e", "exit 0"], capture_output=True, timeout=5)
    modules[name] = result.returncode == 0
packages = {}
for name in ("httpx2", "httpcore2", "pytest", "fastapi", "pillow", "webauthn", "idna"):
    try:
        packages[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        packages[name] = None
print(json.dumps({"python": sys.version, "machine": platform.machine(), "pointer_bits": struct.calcsize("P")*8,
    "sqlite": sqlite3.sqlite_version, "sqlite_compile_options": options,
    "sqlite_archive_functions": [name for name in functions if "sqlar" in name or "zipfile" in name],
    "zlib_compile": zlib.ZLIB_VERSION, "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
    "expat": expat.EXPAT_VERSION, "perl": {"exit_code": perl.returncode, "config": perl.stdout.splitlines(), "modules_loadable": modules},
    "packages": packages,
    "benign_idna_observation": {"input": "\u1e9e.example", "stdlib_result": "\u1e9e.example".encode("idna").decode("ascii"),
      "scope": "Offline normalization only; no DNS/network request or demonstrated security bypass"}}, sort_keys=True))
