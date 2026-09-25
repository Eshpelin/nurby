#!/usr/bin/env python3
"""Create and restore encrypted Nurby backups.

Examples:
  python scripts/nurby_backup.py backup --passphrase 'use-a-password-manager'
  python scripts/nurby_backup.py restore backups/nurby-20260925T120000Z.nurby --passphrase '...'
"""

from __future__ import annotations

import argparse
import getpass

from services.backup import BackupError, create_backup, restore_backup


def _passphrase(value: str | None) -> str:
    return value or getpass.getpass("Backup passphrase: ")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or restore an encrypted Nurby backup")
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup", help="create an encrypted archive")
    backup.add_argument("--passphrase")
    backup.add_argument("--output", help="archive path; defaults to BACKUP_PATH")
    backup.add_argument("--include-recordings", action="store_true", help="include the recordings volume")
    restore = sub.add_parser("restore", help="restore an archive into the configured installation")
    restore.add_argument("archive")
    restore.add_argument("--passphrase")
    restore.add_argument("--env-file", help="write the archived JWT_SECRET into this env file")
    args = parser.parse_args()
    try:
        if args.command == "backup":
            path = create_backup(_passphrase(args.passphrase), args.output, args.include_recordings)
            print(f"Backup written to {path}")
        else:
            result = restore_backup(args.archive, _passphrase(args.passphrase), args.env_file)
            print(f"Restored backup from {result['created_at']}")
    except BackupError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
