import json
import subprocess
import sys
from pathlib import Path


def test_disposable_scale_drill_keeps_semantic_and_byte_equality():
    script = Path(__file__).with_name("gate10_portable_scale_drill.py")
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--artifacts", "8",
            "--large-payload-mib", "1",
            "--max-rss-mib", "256",
            "--batch-size", "3",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["artifacts"] == 8
    assert report["external_records"] == 1
    assert report["large_payload_bytes"] == 1024 * 1024
    assert report["portable_members_compared"] > 20
    assert report["semantic_and_byte_equal"] is True
    assert all(
        worker["peak_rss_bytes"] <= report["max_rss_bytes"]
        for worker in report["workers"].values()
    )
