# Household mode

Issue #184.

One value for the whole household: `home`, `away` or `night`. Rules opt
in to a subset of modes, so the same camera can be quiet while someone is
in and loud when the house is empty. This is the difference between
"alerts all day" and "alerts that matter", and it is the reason people
stop muting the app.

## The shape of it

The current mode is an app setting, `household_mode`. That is deliberate:
the rule engine reads it once per evaluate() tick, next to the timezone,
and a setting read is cheap enough to do on every frame. The history of
changes is a separate table, `household_mode_changes`, because the
history is for people and the setting is for the engine.

A rule gates on the mode through `conditions.modes`:

```json
{ "modes": ["away", "night"] }
```

No `modes` key, or an empty list, means the rule fires in every mode.
That is what every rule written before this existed does, so nothing
changed underneath anyone.

## Where the logic lives

`shared/household_mode.py` is the one definition: the three modes, their
labels and hints, and `rule_active_in(conditions, mode)`. It has no
SQLAlchemy import, so the engine, the API, the agent tools and the
starter rules all share it. `frontend/src/lib/household-mode.ts` and
`mobile/lib/models/household_mode.dart` mirror `rule_active_in` for
rendering badges; the labels themselves are served from the API rather
than copied, so a fourth mode renders in both clients without a release.

## Failing closed

Two cases had to be decided rather than left to chance.

**A settings read that fails** falls back to `home`. Home is the quiet
mode, so a database blip makes the system less trigger-happy, never more.
Arming a household's cameras because a read timed out would be the worse
failure.

**A legacy caller that passes no mode** is not gated at all.
`_check_conditions` takes `mode=None` from `POST /rules/replay` and older
code paths, and treats that as "do not evaluate this condition" rather
than guessing the current mode. A rule test therefore returns the same
answer whatever the house happens to be doing.

## What a person sees

- **Home screen**, web and mobile: three chips, the active one marked,
  with the current mode's hint under them. Changing it is one tap.
- **"3 rules are paused while Home"**, linking to the rules list. A quiet
  rule is otherwise indistinguishable from a broken one, and that
  confusion is the main way a feature like this backfires.
- **Rules list**: a mode-gated rule carries `Only while Away or Night`,
  which becomes `Paused until Away or Night` while the current mode is
  keeping it quiet. Blue, not amber: it is a state, not a problem.
- **Rule builder**: a mode row in Conditions, defaulting to "Any mode".
- **Activity**: a `mode_change` entry, with who changed it and any note.
  This is the answer to "why was it quiet at 3pm".
- **Ask**: `get_household_snapshot` returns the mode and `list_rules`
  marks each rule `silenced_by_mode`, so the agent can answer "why didn't
  I get an alert" without guessing.

## Starters

`someone-at-the-door-while-out` is the Home/Away use case as a one-tap
starter rule, gated on `["away", "night"]`.

The plain `someone-at-the-door` starter is deliberately left ungated.
It is the first alert a new household ever sees, and they are standing at
home when they test it. A starter that silently does nothing on the day
it is created teaches people the product does not work.

## Not built

- **Automatic mode changes.** `source` already accepts `auto`, and the
  journeys and last-sighting data already know when every known member
  has left. Nothing sets it yet; a person taps the chip.
- **Phone location.** The obvious next input, and the one with the
  biggest privacy cost. Deliberately not started.
- **Per-camera modes.** One value for the house is the right first
  version. Splitting it per camera before anyone asks would be inventing
  a problem.
