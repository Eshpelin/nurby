#!/usr/bin/env python3
"""Create a real (email, password) login for every ux-army persona, so no
run ever lands on a login screen with no usable account.

Passwords are GENERATED here and written to testing/harness/credentials.json,
which is gitignored. Nothing secret is committed. The repo is public, and
even throwaway local-test credentials don't belong in it: they trip secret
scanners and normalise a pattern that eventually gets applied to something
that does matter.

credentials.json is the source of truth. Idempotent and self-healing:
- persona missing from the file -> generate a password
- user missing from the DB     -> create with that password
- user present in the DB       -> reset their hash to match the file,
                                  so a wiped DB or a lost file can't
                                  leave the two out of sync.

Usage:
    PYTHONPATH=. DATABASE_URL=postgresql+asyncpg://... \
        .venv-test/bin/python testing/harness/seed_persona_accounts.py
"""
import asyncio
import json
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from shared.auth import hash_password
from shared.models import User

HARNESS_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = HARNESS_DIR / "credentials.json"

# slug, display name, email, role. role="guardian" for the persona whose
# own story IS the Guardian panel (wellbeing reports, marking incidents
# reviewed); "admin" for everyone else, since each persona owns their own
# household/business story and needs full setup access (cameras,
# providers, rules) to pursue their goals.
PERSONAS = [
    ("ahmed-remote-son", "Ahmed", "ahmed@ux-army.test", "admin"),
    ("carlos-hobby-farmer", "Carlos", "carlos@ux-army.test", "admin"),
    ("dana-busy-parent", "Dana", "dana@ux-army.test", "admin"),
    ("daniel-new-dad", "Daniel", "daniel@ux-army.test", "admin"),
    ("elena-shop-owner", "Elena", "elena@ux-army.test", "admin"),
    ("george-ai-skeptic", "George", "george@ux-army.test", "admin"),
    ("jamal-apartment-renter", "Jamal", "jamal@ux-army.test", "admin"),
    ("june-hoa-manager", "June", "june@ux-army.test", "admin"),
    ("kevin-impatient-exec", "Kevin", "kevin@ux-army.test", "admin"),
    ("lisa-privacy-first", "Lisa", "lisa@ux-army.test", "admin"),
    ("margaret-retired-teacher", "Margaret", "margaret@ux-army.test", "admin"),
    ("mei-power-user", "Mei", "mei@ux-army.test", "admin"),
    ("nina-airbnb-host", "Nina", "nina@ux-army.test", "admin"),
    ("olga-professional-caregiver", "Olga", "olga@ux-army.test", "guardian"),
    ("priya-landlord", "Priya", "priya@ux-army.test", "admin"),
    ("ray-night-shift-nurse", "Ray", "ray@ux-army.test", "admin"),
    ("sofia-pet-parent", "Sofia", "sofia@ux-army.test", "admin"),
    ("steve-diy-tinkerer", "Steve", "steve@ux-army.test", "admin"),
    ("tom-security-nerd", "Tom", "tom@ux-army.test", "admin"),
    ("victor-gym-owner", "Victor", "victor@ux-army.test", "admin"),
]


def load_credentials() -> dict:
    if CREDENTIALS_FILE.exists():
        return json.loads(CREDENTIALS_FILE.read_text())
    return {}


def save_credentials(creds: dict) -> None:
    CREDENTIALS_FILE.write_text(json.dumps(creds, indent=2, sort_keys=True) + "\n")
    CREDENTIALS_FILE.chmod(0o600)


async def main() -> None:
    db_url = os.environ["DATABASE_URL"]
    creds = load_credentials()

    # Fill in any persona that has no password yet.
    for slug, name, email, role in PERSONAS:
        if slug not in creds:
            creds[slug] = {
                "email": email,
                "password": secrets.token_urlsafe(12),
                "role": role,
                "display_name": name,
            }
    save_credentials(creds)

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    created, reset = [], []
    async with session_factory() as db:
        for slug, name, email, role in PERSONAS:
            entry = creds[slug]
            existing = (
                await db.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if existing:
                # Keep the DB in step with the file rather than skipping:
                # a persona whose password drifted is a run that can't log in.
                existing.password_hash = hash_password(entry["password"])
                existing.is_active = True
                existing.is_provisional = False
                reset.append(slug)
            else:
                db.add(
                    User(
                        email=email,
                        display_name=name,
                        password_hash=hash_password(entry["password"]),
                        role=role,
                        is_active=True,
                        is_provisional=False,
                    )
                )
                created.append(slug)
        await db.commit()

    await engine.dispose()

    for slug in created:
        print(f"created  {slug}")
    for slug in reset:
        print(f"synced   {slug}")
    print(f"\n{len(created)} created, {len(reset)} synced")
    print(f"credentials: {CREDENTIALS_FILE.relative_to(Path.cwd())} (gitignored)")


if __name__ == "__main__":
    asyncio.run(main())
