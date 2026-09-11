"""Benign fixture-only checks, mounted read-only by verify-container-privileges.py."""
import argparse
import ctypes
import errno
import json
import os
from pathlib import Path
import subprocess
import sys

from container_privileges import process_privileges

parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=("app", "child", "seed", "read-private", "restore-metadata"))
parser.add_argument("--uid", type=int, default=1000)
parser.add_argument("--gid", type=int, default=1000)
parser.add_argument("--nested", action="store_true")
args = parser.parse_args()
if args.mode == "seed":
    for root in (Path("/app/data"), Path("/app/storage")):
        private = root / "private"
        private.mkdir()
        (private / "payload").write_bytes(b"preserve-fixture-bytes")
        os.chown(private / "payload", 1201, 1202)
        (private / "payload").chmod(0o600)
        os.chown(private, 1201, 1202)
        private.chmod(0o700)
    print(json.dumps({"seeded": True}))
elif args.mode == "read-private":
    assert Path("/app/storage/private/payload").read_bytes() == b"preserve-fixture-bytes"
    print(json.dumps({"read_private": True}))
elif args.mode == "restore-metadata":
    target = Path("/tmp/restore-metadata-fixture")
    target.write_bytes(b"restore-fixture")
    os.chown(target, 1201, 1202)
    # Trusted tar recovery must restore mode/timestamps after restoring ownership.
    target.chmod(0o600)
    os.utime(target, (1, 1))
    assert target.stat().st_uid == 1201 and target.stat().st_mtime == 1
    print(json.dumps({"restore_metadata": True}))
else:
    result = process_privileges(Path("/proc/self/status").read_text(), expected_uid=args.uid)
    assert os.getgid() == os.getegid() == args.gid
    try:
        os.setuid(0)
    except PermissionError:
        result["setuid_root_refused"] = True
    else:
        raise AssertionError("Application acquired root")
    libc = ctypes.CDLL(None, use_errno=True)
    assert libc.prctl(38, 0, 0, 0, 0) == -1, "NoNewPrivs unexpectedly cleared"
    result["clear_nnp_refused"] = True
    if args.mode == "app":
        for root in (Path("/app/data"), Path("/app/storage")):
            fixture = root / "runtime-write"
            if fixture.exists():
                assert fixture.read_bytes() == b"persistent-fixture-bytes"
            fixture.write_bytes(b"persistent-fixture-bytes")
            if args.nested:
                payload = root / "private/payload"
                assert payload.read_bytes() == b"preserve-fixture-bytes"
                assert payload.stat().st_uid == args.uid and payload.stat().st_gid == args.gid
        assert Path("/imports/source.stl").read_bytes() == b"external-source-bytes"
        try:
            Path("/imports/forbidden-write").write_bytes(b"no")
        except OSError as error:
            assert error.errno == errno.EROFS
            result["imports_read_only"] = True
        else:
            raise AssertionError("Mounted imports became writable")
        child = subprocess.check_output([sys.executable, __file__, "child", "--uid", str(args.uid), "--gid", str(args.gid)], text=True)
        result["child"] = json.loads(child)
        result["persistent_bytes"] = True
        result["nested_ownership"] = args.nested
    print(json.dumps(result, sort_keys=True))
