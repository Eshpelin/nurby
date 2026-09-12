"""Every service image must contain the packages its code imports.

Issue #181: the Dockerfiles used to hand-list `services/` packages, and
`services/voice` was never added, so the API image could not start. The
fix was one `COPY services/ services/` per image. This test keeps it
that way: if someone reintroduces a per-package list, it must be
complete.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = sorted(ROOT.glob("services/*/Dockerfile"))


def _copied_packages(dockerfile: Path) -> set[str] | None:
    """Packages an image carries, or None if it copies the whole tree."""
    text = dockerfile.read_text()
    if re.search(r"^COPY services/ services/\s*$", text, re.M):
        return None
    return set(re.findall(r"^COPY services/([a-z_]+)/", text, re.M))


def _load_time_imports(pkg: str) -> set[str]:
    """Top-level `services.x` imports (indent 0) across a package."""
    out: set[str] = set()
    for py in (ROOT / "services" / pkg).rglob("*.py"):
        for line in py.read_text().splitlines():
            m = re.match(r"(?:from|import) services\.([a-z_]+)", line)
            if m:
                out.add(m.group(1))
    return out


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.parent.name)
def test_image_carries_what_it_imports(dockerfile: Path):
    copied = _copied_packages(dockerfile)
    if copied is None:
        return  # whole tree, nothing can be missing
    needed: set[str] = set()
    for pkg in copied:
        needed |= _load_time_imports(pkg)
    needed = {n for n in needed if (ROOT / "services" / n).is_dir()}
    missing = needed - copied
    assert not missing, (
        f"{dockerfile.relative_to(ROOT)} copies {sorted(copied)} but those "
        f"packages import {sorted(missing)} at module load. Add COPY lines "
        f"or switch to `COPY services/ services/`."
    )
