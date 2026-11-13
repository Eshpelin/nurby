# Power budget

All figures are design estimates. Published Pi Zero 2 W idle numbers range
from 0.6 W to 1.4 W, and nobody has measured this build. Replace these with
bench numbers as soon as one exists.

## Assumptions

| Item | Value |
|---|---|
| One cell row | 2 x 32700 LiFePO4, 3.2 V x 12 Ah = 38.4 Wh. The v0.2 Slate ships with two rows (76.8 Wh), so double the single-row runtimes below |
| Usable fraction | 85% (boost efficiency, cut-off margin) = 32.6 Wh |
| Pi recording 1080p with Wi-Fi | 2.0 W |
| ESP32-C6 holding a Wi-Fi link in light sleep | 20 mW |
| ESP32-C6 deep sleep, PIR wake only | under 1 mW |
| Pi cold boot | 20 s on stock Raspberry Pi OS Lite |
| Solar derate | 65% of nameplate x peak sun hours |

## The 7 day target

Seven days at 2.0 W continuous is 336 Wh. That is about 21 cells. It is not a
battery camera workload on this compute board.

Seven days is realistic when the Pi is off between events:

| Mode | Daily use | Core only (38 Wh) | Plus 1 module (77 Wh) | Plus 2 modules (115 Wh) |
|---|---|---|---|---|
| Always-on RTSP | 48.5 Wh | 16 hours | 32 hours | 2 days |
| Event wake, 50 events of 30 s | 1.9 Wh | 17 days | 35 days | 52 days |
| Event wake, 200 events of 30 s | 6.0 Wh | 5.4 days | 11 days | 16 days |

Event energy: `events x (boot + clip) x 2.0 W / 3600`, plus 0.48 Wh a day for
the controller.

## Solar

| Panel | Harvest at 3 sun hours | Covers |
|---|---|---|
| 2 W (default visor pocket) | 3.9 Wh a day | Event mode up to about 120 events a day |
| 3.5 W | 6.8 Wh a day | Event mode, heavy traffic |
| 6 W | 11.7 Wh a day | Event mode with large margin, or about 5.8 hours of streaming a day |

Always-on streaming from solar alone needs roughly a 25 W panel in good sun.
Use USB-C wall power for that case and let the battery ride through outages.

## What the hardware must provide (v0.1 scope)

1. A load switch on the Pi's 5 V rail, driven by the controller.
2. A wake source on a low-power pin (PIR).
3. A charger with input power-point control, so a small panel is not dragged
   into collapse and a USB charger works on the same input.
4. Coulomb counting. LiFePO4 voltage is nearly flat from 90% to 20%.
5. A hard low-voltage cut-off in the protection board.

## Where the next gains are (firmware and v0.2)

- Fast boot. A trimmed image should reach a stream in under 8 s.
- A lower power compute option. Camera SoCs with a hardware encoder draw a
  fraction of the Pi's power while streaming, which could make always-on plus
  solar practical. Unmeasured, worth a spike.
- Pre-roll from a low-power sensor so the start of an event is not lost.
