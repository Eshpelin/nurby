# Backups

Nurby backups protect the database (including people, face/body embeddings,
cameras, rules, settings and history) and thumbnails. Recordings are excluded
by default because they can be very large; include the recordings volume only
when an evidence archive needs it.

Archives are encrypted with a passphrase and use the `JWT_SECRET` stored
inside the encrypted payload so sealed camera and integration credentials stay
usable after restore. Keep the passphrase and the archive separate. Losing
both means the backup cannot be opened.

## Manual backup

Use Settings → Backups → Back up now for a small configuration/identity backup.
For automation or a mounted host drive, run:

```sh
python scripts/nurby_backup.py backup --passphrase 'from-your-password-manager'
```

Set `NURBY_BACKUP_VOLUME` in `.env` to the host directory that should receive
archives. The Docker default is the persistent `backups` volume.

To include recordings:

```sh
python scripts/nurby_backup.py backup --include-recordings --passphrase '...'
```

## Restore

Restore is intentionally a command-line operation because it replaces the
installation's database state. Stop the API and workers, make sure migrations
have run on the target installation, then run:

```sh
python scripts/nurby_backup.py restore /path/to/nurby-20260925T120000Z.nurby \
  --passphrase 'from-your-password-manager' --env-file .env
```

Start Nurby again afterward. The mobile app must be paired again on the new
host, but it will see the restored household, cameras and history.

## Scheduling

The CLI is safe to call from cron or a systemd timer. Prefer a passphrase file
with permissions `0600` and a wrapper that passes it to the command, or use a
secret manager; never put the passphrase in a repository.

For a single-API deployment, an opt-in in-process scheduler is also available:

```dotenv
NURBY_BACKUP_SCHEDULE_HOURS=24
NURBY_BACKUP_PASSPHRASE=from-your-secret-manager
NURBY_BACKUP_RETENTION_COUNT=7
NURBY_BACKUP_INCLUDE_RECORDINGS=false
```

The scheduler runs after startup, writes to `NURBY_BACKUP_VOLUME`, retains the
newest configured number of `nurby-*.nurby` archives, and leaves the previous
archive intact when a run fails. Do not enable it in multiple API replicas;
use one external timer instead. The Settings page and System Doctor show the
last successful archive and warn after seven days.
