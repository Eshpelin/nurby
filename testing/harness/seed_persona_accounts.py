#!/usr/bin/env python3
"""One-shot: create a real (email, password) login for every ux-army
persona directly in the DB, so no future run ever lands on a login
screen with no usable account.

Previously only the first persona (the admin who runs product setup)
got real credentials; everyone else was meant to join later via an
invite key minted by that admin. In practice that means every persona
after the first depends on a still-working admin session existing at
the moment their turn comes up, days or weeks later. Pre-creating
accounts for everyone removes that dependency. It does trade away
dogfooding the invite-redeem flow for 19 personas — see the note in
testing/skills/user-army/SKILL.md.

Idempotent: skips any persona whose email already exists.

Usage:
    PYTHONPATH=. DATABASE_URL=postgresql+asyncpg://... \
        .venv-test/bin/python testing/harness/seed_persona_accounts.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from shared.auth import hash_password
from shared.models import User

# name, email, password, role. role="guardian" for personas whose own
# story is being the professional Guardian-panel user (reviewing a
# client's wellbeing/incidents), "admin" for everyone else - each
# persona is treated as the owner of their own household/business
# story and needs full setup access to do their goals (add cameras,
# providers, rules), not a member joining someone else's account.
PERSONAS = [
    ("ahmed-remote-son", "Ahmed", "ahmed@ux-army.test", "AhmedRemote2026!", "admin"),
    ("carlos-hobby-farmer", "Carlos", "carlos@ux-army.test", "CarlosFarm2026!", "admin"),
    ("dana-busy-parent", "Dana", "dana@ux-army.test", "DanaParent2026!", "admin"),
    ("daniel-new-dad", "Daniel", "daniel@ux-army.test", "DanielDad2026!", "admin"),
    ("elena-shop-owner", "Elena", "elena@ux-army.test", "ElenaShop2026!", "admin"),
    ("george-ai-skeptic", "George", "george@ux-army.test", "GeorgeSkeptic2026!", "admin"),
    ("jamal-apartment-renter", "Jamal", "jamal@ux-army.test", "JamalRenter2026!", "admin"),
    ("june-hoa-manager", "June", "june@ux-army.test", "JuneHoa2026!", "admin"),
    ("lisa-privacy-first", "Lisa", "lisa@ux-army.test", "LisaPrivacy2026!", "admin"),
    ("margaret-retired-teacher", "Margaret", "margaret@ux-army.test", "MargaretTeacher2026!", "admin"),
    ("mei-power-user", "Mei", "mei@ux-army.test", "MeiPower2026!", "admin"),
    ("nina-airbnb-host", "Nina", "nina@ux-army.test", "NinaHost2026!", "admin"),
    ("olga-professional-caregiver", "Olga", "olga@ux-army.test", "OlgaCaregiver2026!", "guardian"),
    ("priya-landlord", "Priya", "priya@ux-army.test", "PriyaLandlord2026!", "admin"),
    ("ray-night-shift-nurse", "Ray", "ray@ux-army.test", "RayNurse2026!", "admin"),
    ("sofia-pet-parent", "Sofia", "sofia@ux-army.test", "SofiaPet2026!", "admin"),
    ("steve-diy-tinkerer", "Steve", "steve@ux-army.test", "SteveDiy2026!", "admin"),
    ("tom-security-nerd", "Tom", "tom@ux-army.test", "TomSecurity2026!", "admin"),
    ("victor-gym-owner", "Victor", "victor@ux-army.test", "VictorGym2026!", "admin"),
]


async def main() -> None:
    db_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    created, skipped = [], []
    async with session_factory() as db:
        for slug, name, email, password, role in PERSONAS:
            existing = (
                await db.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if existing:
                skipped.append((slug, email))
                continue
            db.add(
                User(
                    email=email,
                    display_name=name,
                    password_hash=hash_password(password),
                    role=role,
                    is_active=True,
                    is_provisional=False,
                )
            )
            created.append((slug, email, password, role))
        await db.commit()

    await engine.dispose()

    for slug, email, password, role in created:
        print(f"created  {slug:30s} {email:30s} {role}")
    for slug, email in skipped:
        print(f"skip     {slug:30s} {email:30s} (already exists)")
    print(f"\n{len(created)} created, {len(skipped)} already existed")


if __name__ == "__main__":
    asyncio.run(main())
