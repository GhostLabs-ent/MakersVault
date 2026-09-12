"""Check documented operator preflight using generated credentials, never a live vault."""
import json
from pathlib import Path
import re
import stat
import subprocess
import tempfile

APP = Path(__file__).resolve().parents[3]


def run(command, *, success=True):
    result = subprocess.run([str(part) for part in command], cwd=APP.parent,
                            capture_output=True, text=True, timeout=120)
    # setup-env prints its generated password; never forward captured output.
    if (result.returncode == 0) != success:
        raise AssertionError(f"Unexpected exit code {result.returncode}: {command[0]}")
    return result


def main():
    with tempfile.TemporaryDirectory(prefix="makersvault-operator-preflight-") as temporary:
        directory = Path(temporary)
        generated = []
        for name in ("first.env", "second.env"):
            target = directory / name
            run([APP / "scripts/setup-env.sh", target])
            before = target.read_bytes()
            assert stat.S_IMODE(target.stat().st_mode) == 0o600
            values = dict(line.split("=", 1) for line in before.decode().splitlines()
                          if line and not line.startswith("#") and "=" in line)
            assert re.fullmatch(r"[a-f0-9]{40}", values["AUTH_PASSWORD"])
            assert re.fullmatch(r"[a-f0-9]{64}", values["AUTH_SECRET"])
            assert values["AUTH_PASSWORD"] != values["AUTH_SECRET"]
            run([APP / "scripts/setup-env.sh", target], success=False)
            assert target.read_bytes() == before
            generated.append(values)
        assert generated[0]["AUTH_PASSWORD"] != generated[1]["AUTH_PASSWORD"]
        assert generated[0]["AUTH_SECRET"] != generated[1]["AUTH_SECRET"]
        for manifest in ("docker-compose.yml", "docker-compose.deploy.yml", "docker-deploy.yml"):
            run(["docker", "compose", "--env-file", directory / "first.env",
                 "-f", APP / manifest, "config", "-q"])
        run([APP / "scripts/verify-compose-security.sh"])
    print(json.dumps({"status": "passed", "credential_generations": 2,
                      "password_hex_characters": 40, "secret_hex_characters": 64,
                      "credential_mode": "0600", "overwrite_refusals": 2,
                      "compose_configs": 3, "missing_secrets_rejected": True,
                      "started_services": False, "real_env_or_vault_changed": False}))


if __name__ == "__main__":
    main()
