# Home / Away mode

**Issue:** #184 · **Status:** mode + rule condition already shipped; this adds the auto presence detector.

## What already existed

- Household mode `home` / `away` / `night` as an app setting + history table
  (`shared/household_mode.py`, `HouseholdModeChange`, `/api/household/mode`).
- Rules opt in via `conditions.modes`; the engine reads the current mode each
  tick (`rule_active_in`). A rule with no `modes` fires in every mode.
- Starter rules already ship the sensible default: `someone-at-the-door-while-out`
  carries `conditions.modes: ["away", "night"]`.

The one gap the code itself called out ("a presence detector that does not
exist yet") was automatic switching from the identity graph.

## What this adds: auto presence

- **Household members**: named people flagged `Person.is_household_member`
  (new column; settable via the person update API). The feature is inert until
  at least one person is flagged, so it never surprises an install.
- **Detector** (`services/perception/presence_mode.py`): from recent
  `person_detections`, count how many flagged members were seen in the last
  15 minutes, then `decide_mode` (pure, unit-tested):
  - nobody seen → `away`
  - a member seen again while `away` → `home`
  - never touches `night`; holds off for 10 min after a manual/agent change so
    a deliberate tap sticks.
- **Driver** (`presence_mode_sweeper.py`): a slow (120 s) loop wired into the
  API lifespan that applies changes via the same `change_mode` the API uses,
  tagged `source="auto"`, so the timeline shows "nobody home" / "someone
  arrived" with the auto source.

## Done-when (from the issue)

A household flags its members, leaves → within ~15 min the mode goes `away`
(auto) and a door rule scoped to `away` fires; someone returns → mode goes
`home` and that rule stays quiet; every transition is in the mode history /
Activity timeline. ✅ (backend)

## Deferred

- Phone-location as a mode source (the issue lists it as "later").
- Mobile one-tap control and the "silenced by mode" affordance in the rules
  list are client work; the backend already exposes the mode, its history,
  the per-rule `modes` condition, and a silenced count.

Source: `services/perception/presence_mode.py`,
`services/perception/presence_mode_sweeper.py`, `Person.is_household_member`
(migration `f7a1b2c3d4e5`), tests `tests/test_presence_mode.py`.
