"""Disposable startup/ownership/capability regression matrix; never uses a live vault."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from container_privileges import CAPABILITIES
from verification_runtime import APP, run, install_signal_handlers


def main():
    install_signal_handlers()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-image", required=True)
    args = parser.parse_args()
    image = json.loads(run(["docker", "image", "inspect", args.api_image]).stdout)[0]["Id"]
    containers, volumes = [], []
    report = {"image": image, "cases": {}, "negative_controls": {}}
    with tempfile.TemporaryDirectory(prefix="makersvault-containment-") as temporary:
        imports = Path(temporary) / "imports"
        imports.mkdir(mode=0o755)
        (imports / "source.stl").write_bytes(b"external-source-bytes")
        (imports / "source.stl").chmod(0o644)

        def probe_result(result):
            # Account tools may print informational output before the probe JSON.
            lines = result.stdout.decode(errors="replace").splitlines()
            assert lines, f"Missing probe output: {result.stderr!r}"
            try:
                parsed = json.loads(lines[-1])
            except ValueError as error:
                raise AssertionError(f"Invalid fixture output: {result.stdout!r}; {result.stderr!r}") from error
            return {**parsed, "startup_stdout": lines[:-1], "startup_stderr": result.stderr.decode(errors="replace")}

        def pair():
            names = ["mv-containment-"+uuid4().hex for _ in range(2)]
            for name in names:
                run(["docker", "volume", "create", "--label", "makersvault.fixture=containment", name])
                volumes.append(name)
            return names

        def command(names, mode="app", *, caps=CAPABILITIES, uid=1000, gid=1000, nested=False, retain=False):
            name = "mv-containment-"+uuid4().hex
            containers.append(name)
            command = ["docker", "create" if retain else "run", *([] if retain else ["--rm"]),
                       "--name", name, "--network", "none", "--security-opt", "no-new-privileges:true", "--cap-drop", "ALL"]
            for cap in sorted(caps):
                command += ["--cap-add", cap]
            command += ["--env", f"PUID={uid}", "--env", f"PGID={gid}",
                        "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "CHOWN_MODE="+("recursive" if nested else "minimal"),
                        "--mount", f"type=bind,src={APP / 'scripts'},dst=/probe,readonly",
                        "--mount", f"type=bind,src={imports},dst=/imports,readonly"]
            for volume, target in zip(names, ("/app/data", "/app/storage")):
                command += ["--mount", f"type=volume,src={volume},dst={target}"]
            if mode != "app":
                command += ["--entrypoint", "python"]
            command += [image, *(["python"] if mode == "app" else []), "/probe/container-privilege-probe.py", mode,
                        "--uid", str(uid), "--gid", str(gid), *(["--nested"] if nested else [])]
            return name, command

        def invoke(names, mode="app", **kwargs):
            _, cmd = command(names, mode, **kwargs)
            result = run(cmd, check=False)
            assert result.returncode == 0, result.stderr.decode(errors="replace")
            return probe_result(result)

        try:
            fresh = pair()
            name, cmd = command(fresh, retain=True)
            run(cmd)
            for stage in ("fresh_default", "same_container_restart"):
                result = run(["docker", "start", "--attach", name])
                state = json.loads(run(["docker", "inspect", "--format", "{{json .State}}", name]).stdout)
                assert state["ExitCode"] == 0, result.stderr.decode(errors="replace")
                report["cases"][stage] = probe_result(result)
            report["cases"]["existing_volume_recreate"] = invoke(fresh)
            custom = pair()
            invoke(custom, "seed")
            report["cases"]["custom_uid_gid_recursive_ownership"] = invoke(custom, uid=1501, gid=1601, nested=True)
            report["cases"]["custom_uid_gid_existing_volume"] = invoke(custom, uid=1501, gid=1601, nested=True)
            # Non-default existing base-image group exercises reuse rather than groupadd.
            report["cases"]["existing_group"] = invoke(pair(), uid=1502, gid=1)
            private = pair()
            invoke(private, "seed")
            report["cases"]["operator_read_private"] = invoke(private, "read-private")
            report["cases"]["operator_restore_metadata"] = invoke(private, "restore-metadata")
            for cap in sorted(CAPABILITIES):
                mode = "read-private" if cap == "DAC_OVERRIDE" else "restore-metadata" if cap == "FOWNER" else "app"
                names = private if mode != "app" else pair()
                _, cmd = command(names, mode, caps=CAPABILITIES-{cap})
                result = run(cmd, check=False)
                assert result.returncode != 0, f"Removing {cap} did not trigger its expected necessity check"
                report["negative_controls"][cap] = {"mode": mode, "exit_code": result.returncode,
                                                     "stderr": result.stderr.decode(errors="replace")[-2000:]}
            assert (imports / "source.stl").read_bytes() == b"external-source-bytes"
            report["status"] = "passed"
        finally:
            for name in containers:
                run(["docker", "rm", "-f", name], check=False)
            for name in volumes:
                run(["docker", "volume", "rm", name])
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
