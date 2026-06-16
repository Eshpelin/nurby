# Real traffic-signal test fixtures

Drop real photos here to validate the signal-detection pipeline
(`services/perception/traffic_signal.py`) against actual pixels instead of
synthetic frames. `tests/test_traffic_signal_photo.py` auto-discovers them
and skips cleanly when the folder is empty, so this stays optional.

## Layout

One folder per signal/camera. Each folder needs:

```
tests/fixtures/signals/<name>/
  lamps.json        # where the three lamps are in these images
  red.jpg           # the signal photographed while RED is lit
  amber.jpg         # ... while AMBER is lit
  green.jpg         # ... while GREEN is lit
  red_test1.jpg     # (optional) held-out shots for stricter validation
  green_test1.png   # (optional) named "<state>_test*.<ext>"
```

All images for one signal must share the same framing (same camera, same
crop) so the lamp points line up.

`lamps.json`:

```json
{
  "lamps": [
    { "color": "red",   "point": [x, y], "r": 8 },
    { "color": "amber", "point": [x, y], "r": 8 },
    { "color": "green", "point": [x, y], "r": 8 }
  ]
}
```

`point` is the lamp centre in pixels; `r` is the sample-patch half-size.

## What the test asserts

1. It calibrates from `red/amber/green.jpg` (each lamp's brightness per state).
2. Closed loop: each calibration image must classify back to its own state.
3. Any `*_test*` images must classify to the state in their filename.

## Licensing

Only commit images you own or that are public-domain / CC0. Do not commit
copyrighted photos pulled from the web.
