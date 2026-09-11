"""Assertions for shipped container policy and actual application process state."""
CAPABILITIES = {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID", "SETPCAP"}
CAP_FIELDS = ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")


def process_privileges(status, *, expected_uid=None):
    fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    uid = [int(value) for value in fields["Uid"].split()]
    assert len(uid) == 4 and all(value != 0 for value in uid), "Application must be non-root"
    if expected_uid is not None:
        assert uid == [expected_uid] * 4, "Unexpected application UID"
    caps = {field: int(fields[field].strip(), 16) for field in CAP_FIELDS}
    assert all(value == 0 for value in caps.values()), f"Application capabilities remain: {caps}"
    assert fields["NoNewPrivs"].strip() == "1", "Application can acquire new privileges"
    return {"uid": uid[0], "capabilities": caps, "no_new_privileges": True}


def compose_privileges(config):
    for name, capabilities in (("api", CAPABILITIES), ("web", set())):
        service = config["services"][name]
        assert set(service.get("cap_drop", [])) == {"ALL"}, f"{name}: must drop all default capabilities"
        assert set(service.get("cap_add", [])) == capabilities, f"{name}: unexpected capability allowlist"
        options = {value.replace(":", "=", 1) for value in service.get("security_opt", [])}
        assert "no-new-privileges=true" in options, f"{name}: no-new-privileges is required"
        assert not service.get("privileged", False), f"{name}: privileged containers are forbidden"
    return True


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(process_privileges(sys.stdin.read()), sort_keys=True))
