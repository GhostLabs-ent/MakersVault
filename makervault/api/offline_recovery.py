"""Interactive, stopped-instance Administrator recovery command."""

from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
import sys

from identity_service import PASSWORD_POLICY_VERSION, hash_new_password
from recovery_mutation import RecoveryMutationError, recover_existing_administrator


def recover_interactively(database: Path, backup: Path, username: str) -> dict[str, object]:
    password = getpass.getpass("New temporary password: ")
    confirmation = getpass.getpass("Confirm temporary password: ")
    if password != confirmation:
        raise RecoveryMutationError("password confirmation does not match")
    password_hash = hash_new_password(password)
    return recover_existing_administrator(
        database,
        backup,
        username,
        password_hash,
        PASSWORD_POLICY_VERSION,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recover one existing MakersVault Administrator while the instance is stopped"
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    try:
        result = recover_interactively(args.database, args.backup, args.username)
    except (RecoveryMutationError, ValueError) as exc:
        print(f"Administrator recovery error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
