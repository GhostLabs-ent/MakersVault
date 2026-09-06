"""Offline helper for generated Gate 13 volumes, never a live-vault tool."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def snapshot(database=Path("/app/data/app.db"), storage=Path("/app/storage")):
    if not database.exists():
        return {"schema": None, "database_sha256": None, "tables": {}, "files": {}}
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = {}
        for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            quoted = name.replace('"', '""')
            tables[name] = sorted([dict(row) for row in connection.execute(f'SELECT * FROM "{quoted}"')],
                                  key=lambda row: json.dumps(row, sort_keys=True))
        schema = connection.execute("SELECT MAX(version) FROM schema_migration").fetchone()[0]
    finally:
        connection.close()
    return {"schema": schema, "database_sha256": digest(database), "tables": tables,
            "files": {str(path.relative_to(storage)): digest(path)
                      for path in sorted(storage.rglob("*")) if path.is_file()}}


def seed_public_credential(user_id, database=Path("/app/data/app.db")):
    # Public P-256 generator point as an ES256 COSE key. This checks recovery
    # state; it is not a claim that a physical passkey ceremony was performed.
    x = "6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296"
    y = "4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5"
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    public_key = encode(bytes.fromhex("a5010203262001215820" + x + "225820" + y))
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migration").fetchone()[0] == 17
        assert connection.execute("SELECT role FROM useraccount WHERE id=?", (user_id,)).fetchone() == ("member",)
        connection.execute("UPDATE useraccount SET mfa_enabled=1 WHERE id=?", (user_id,))
        connection.execute("""INSERT INTO webauthncredential(
            id,user_id,credential_id,public_key,sign_count,transports_json,device_type,
            backed_up,label,created_at,last_used_at) VALUES (?,?,?,?,0,'["internal"]',
            'single_device',0,'Gate 13 public recovery fixture',?,NULL)""",
            (str(uuid4()), user_id, encode(uuid4().bytes), public_key, now))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("snapshot", "seed-public-credential"))
    parser.add_argument("--user-id")
    parser.add_argument("--confirm-disposable", action="store_true")
    args = parser.parse_args()
    if args.action == "snapshot":
        print(json.dumps(snapshot(), sort_keys=True))
    else:
        if not args.confirm_disposable or not args.user_id:
            parser.error("Fixture mutation requires --confirm-disposable and --user-id")
        seed_public_credential(args.user_id)
