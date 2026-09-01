"""Disposable Gate 11A Argon2id time/memory benchmark; handles test data only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import resource
import sys
import time

API_ROOT = Path(__file__).parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from identity_service import (
    ARGON2_MEMORY_KIB,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    PASSWORD_HASHER,
)


def _measure(operation):
    started = time.perf_counter()
    result = operation()
    return result, round(time.perf_counter() - started, 4)


def _peak_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-operation-seconds", type=float, default=5.0)
    parser.add_argument("--max-rss-mib", type=int, default=192)
    args = parser.parse_args(argv)
    if args.max_operation_seconds <= 0 or args.max_rss_mib <= 0:
        raise ValueError("benchmark limits must be positive")

    password = "Gate 11A disposable benchmark passphrase"
    encoded, hash_seconds = _measure(lambda: PASSWORD_HASHER.hash(password))
    verified, verify_seconds = _measure(lambda: PASSWORD_HASHER.verify(encoded, password))
    peak_rss_bytes = _peak_rss_bytes()
    report = {
        "argon2id": {
            "memory_kib": ARGON2_MEMORY_KIB,
            "parallelism": ARGON2_PARALLELISM,
            "time_cost": ARGON2_TIME_COST,
        },
        "hash_seconds": hash_seconds,
        "max_operation_seconds": args.max_operation_seconds,
        "max_rss_bytes": args.max_rss_mib * 1024 * 1024,
        "peak_rss_bytes": peak_rss_bytes,
        "verify_seconds": verify_seconds,
        "verified": bool(verified),
    }
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    if not verified:
        return 2
    if max(hash_seconds, verify_seconds) > args.max_operation_seconds:
        return 2
    if peak_rss_bytes > args.max_rss_mib * 1024 * 1024:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
