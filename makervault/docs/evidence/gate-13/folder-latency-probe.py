"""Instrument the historical API or its proposed projection on a new HTTPS fixture only."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from uuid import uuid4
APP = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(APP / "scripts"))
from verification_runtime import DisposableStack, HOST, install_signal_handlers, run

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--projection", action="store_true")
args = parser.parse_args()
install_signal_handlers()

api = "sha256:a099ec86206c9e9204267e63ed4953f86f6ecb217077994f6488a536500ba27b"
web = "sha256:a833cb7fc959b27979c9d7e89fe02680913b61375d158aeebd43129d4fcc0352"
with tempfile.TemporaryDirectory(prefix="mv-folder-http-") as root:
    stack = DisposableStack(Path(root)/"stack", api, web)
    client_container = "mv-folder-probe-" + uuid4().hex
    overlay = json.loads(stack.overlay.read_text())
    overlay["services"]["api"] = {
        "volumes": [f"{HERE / 'folder-latency-asgi.py'}:/app/folder_diagnostic.py:ro"],
        "command": ["uvicorn", "folder_diagnostic:app", "--host", "0.0.0.0", "--port", "8000"],
        "environment": {"MV_FOLDER_PROJECTION": "1" if args.projection else "0"},
    }
    stack.overlay.write_text(json.dumps(overlay))
    try:
        stack.start()
        # Seed only this newly created fixture; same 80/4/2 tree as the stress benchmark.
        seed = """import json
from sqlmodel import Session
from main import engine, Folder
with Session(engine) as session:
    for r in range(80):
        root = Folder(name=f'Root {r:02d}', tags_json='["gate-3"]')
        session.add(root)
        for b in range(4):
            branch = Folder(name=f'Branch {b:02d}', parent_id=root.id, tags_json='["gate-3"]')
            session.add(branch)
            for l in range(2):
                session.add(Folder(name=f'Leaf {l:02d}', parent_id=branch.id, tags_json='["gate-3"]'))
    session.commit()
"""
        stack.compose("exec", "-T", "api", "python", "-c", seed)
        env = {**os.environ, "MV_API": stack.origin+"/api", "MV_ORIGIN": stack.origin,
               "MV_USER": stack.config["AUTH_USERNAME"], "MV_PASSWORD": stack.config["AUTH_PASSWORD"]}
        result = run(["docker", "run", "--rm", "--name", client_container, "--network", "host", "--add-host", f"{HOST}:127.0.0.1",
                      "-e", "MV_API", "-e", "MV_ORIGIN", "-e", "MV_USER", "-e", "MV_PASSWORD",
                      "-v", f"{stack.certificate}:/fixture/ca.crt:ro",
                      "-v", f"{APP / 'benchmarks'}:/bench:ro",
                      "-v", f"{HERE / 'folder-latency-client.mjs'}:/client.mjs:ro",
                      "sha256:1e23cb1539a3e04d9b5db3fb6da8cc89694a8d1358f8e5ac726157a32536caaa", "node", "/client.mjs"], env=env)
        print(result.stdout.decode())
    finally:
        run(["docker", "rm", "-f", client_container], check=False)
        stack.close()
