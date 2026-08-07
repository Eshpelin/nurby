"""Voice policy presets (issue #156).

The settings a camera needs to speak safely are quiet hours, a cooldown,
a daily cap and a volume ceiling. Exposed raw, that is four numbers and
two times per camera, and most households will get at least one of them
wrong in a direction they only discover at 3am.

So the product is the presets and the switches are the escape hatch. A
household picks an intent, and the numbers follow from it. Anyone who
wants the numbers can still have them, and choosing them moves the camera
to ``custom`` rather than silently diverging from a named preset it no
longer matches.

The presets deliberately differ in more than volume. A deterrent
announcement is occasional, loud and firm; a concierge greeting is
frequent, quieter and needs a short cooldown because a visitor who says
two things should not be answered once. Those are different products
sharing a mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass

SILENT = "silent"
DETERRENT = "deterrent"
CONCIERGE = "concierge"
CUSTOM = "custom"


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    description: str
    speaker_enabled: bool
    speaker_volume: int
    speaker_cooldown_seconds: int
    speaker_daily_cap: int
    speaker_quiet_start: str | None
    speaker_quiet_end: str | None

    def as_settings(self) -> dict:
        """The camera fields this preset implies. Pure, for tests."""
        return {
            "speaker_enabled": self.speaker_enabled,
            "speaker_volume": self.speaker_volume,
            "speaker_cooldown_seconds": self.speaker_cooldown_seconds,
            "speaker_daily_cap": self.speaker_daily_cap,
            "speaker_quiet_start": self.speaker_quiet_start,
            "speaker_quiet_end": self.speaker_quiet_end,
        }


PRESETS: dict[str, Preset] = {
    SILENT: Preset(
        key=SILENT,
        label="Silent",
        description=(
            "This camera never speaks. Rules with a speak action are "
            "recorded as suppressed rather than played."
        ),
        speaker_enabled=False,
        speaker_volume=70,
        speaker_cooldown_seconds=30,
        speaker_daily_cap=50,
        speaker_quiet_start=None,
        speaker_quiet_end=None,
    ),
    DETERRENT: Preset(
        key=DETERRENT,
        label="Deterrent",
        description=(
            "Announcements only, never a reply. Firm and occasional: a long "
            "cooldown so a lingering visitor is warned once rather than "
            "harangued, and a low daily cap so a misfiring rule cannot turn "
            "into a nuisance."
        ),
        speaker_enabled=True,
        speaker_volume=80,
        speaker_cooldown_seconds=120,
        speaker_daily_cap=20,
        speaker_quiet_start="22:00",
        speaker_quiet_end="07:00",
    ),
    CONCIERGE: Preset(
        key=CONCIERGE,
        label="Concierge",
        description=(
            "Greets people at a door. Quieter and more frequent than the "
            "deterrent, with a short cooldown so a visitor who says two "
            "things is not answered once. Says nothing about the household."
        ),
        speaker_enabled=True,
        speaker_volume=60,
        speaker_cooldown_seconds=15,
        speaker_daily_cap=100,
        speaker_quiet_start="23:00",
        speaker_quiet_end="07:00",
    ),
}


def get(key: str | None) -> Preset | None:
    """Look up a preset. None for custom or anything unknown. Pure."""
    return PRESETS.get((key or "").strip().lower())


def matches(camera, preset: Preset) -> bool:
    """Whether a camera's settings still match a preset. Pure, for tests."""
    return all(
        getattr(camera, field, None) == value
        for field, value in preset.as_settings().items()
    )


def infer(camera) -> str:
    """Which preset a camera currently reflects, or ``custom``. Pure.

    Used when displaying a camera whose settings were changed directly
    rather than through a preset, so the UI can say "custom" honestly
    instead of showing a preset the camera no longer matches.
    """
    for preset in PRESETS.values():
        if matches(camera, preset):
            return preset.key
    return CUSTOM


def listing() -> list[dict]:
    """Presets in the order they should be offered. Pure.

    Silent first, and it is the default: a camera that can talk should
    start out not talking.
    """
    order = (SILENT, DETERRENT, CONCIERGE)
    out = [
        {
            "key": PRESETS[key].key,
            "label": PRESETS[key].label,
            "description": PRESETS[key].description,
            "settings": PRESETS[key].as_settings(),
        }
        for key in order
    ]
    out.append({
        "key": CUSTOM,
        "label": "Custom",
        "description": "Your own settings. Shown when a camera matches no preset.",
        "settings": {},
    })
    return out
