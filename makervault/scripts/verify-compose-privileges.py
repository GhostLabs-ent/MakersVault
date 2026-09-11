"""Validate rendered canonical and compatibility Compose privilege policies."""
import json
import os
from pathlib import Path
import subprocess

from container_privileges import compose_privileges

app = Path(__file__).resolve().parents[1]
env = {**os.environ, "AUTH_PASSWORD": "disposable-config-check-only", "AUTH_SECRET": "disposable-config-check-not-a-deployed-secret"}
for name in ("docker-compose.yml", "docker-compose.deploy.yml", "docker-deploy.yml"):
    result = subprocess.run(["docker", "compose", "--env-file", "/dev/null", "-f", str(app / name),
                             "config", "--format", "json"], env=env, capture_output=True, check=True, timeout=30)
    compose_privileges(json.loads(result.stdout))
    print(f"Privilege policy verified: {name}")
