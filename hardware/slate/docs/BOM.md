# Bill of materials

> This table is the v0.1 single-row Slate. v0.2 adds two more cells, a second
> camera, mmWave radar, a light sensor, two flash LEDs, six magnets and, for
> the pan-tilt joint, two standard servos. The current list with prices is
> `slateData.ts` in the landing page repo, about $179 for the core.

Rough single-unit street prices in USD. Generic parts, buy from any supplier.
The website reads the same list from `slateData.ts` in the landing page repo.
Keep the two in sync.

## Compute and vision

| Part | Qty | Unit $ | Notes |
|---|---|---|---|
| Raspberry Pi Zero 2 W | 1 | 15 | Any Zero-footprint board fits the standoffs |
| IMX462 STARVIS camera with IR-cut | 1 | 24 | Pi CSI module, 2 MP starlight sensor, plus 22-pin Zero cable |
| microSD, high endurance, 32 GB | 1 | 8 | |

## Power

| Part | Qty | Unit $ | Notes |
|---|---|---|---|
| 32700 LiFePO4 cell, 6 Ah, solder tabs | 2 | 6 | Wired 1S2P, 38 Wh |
| 1S LiFePO4 protection board | 1 | 2 | 3.65 V over-charge, 2.0 to 2.5 V cut-off, 5 A or more |
| LiFePO4 charger with input power-point control | 1 | 8 | bq25185 class board, set to 3.6 V, takes USB or solar |
| 5 V 3 A boost converter | 1 | 6 | Synchronous, low quiescent current |
| INA219 current and voltage monitor | 1 | 2 | Coulomb counting |
| Load switch board | 3 | 2 | One for the Pi rail, one per dock |
| Inline fuse 5 A and 6 mm latching switch | 1 | 2 | Battery disconnect |

## Sentinel and sensing

| Part | Qty | Unit $ | Notes |
|---|---|---|---|
| Seeed XIAO ESP32-C6 | 1 | 6 | Always-on controller, Wi-Fi 6 and BLE |
| AM312 PIR sensor | 1 | 2 | Wakes the Pi |

## Audio and light

| Part | Qty | Unit $ | Notes |
|---|---|---|---|
| INMP441 I2S microphone | 1 | 3 | |
| MAX98357A I2S amplifier | 1 | 5 | |
| 28 mm speaker, 4 ohm 3 W | 1 | 2 | |
| SK6812 RGBW stick, 8 LEDs | 2 | 6 | Red and blue strobe, plus white flood |
| 850 nm IR LED, 5 mm | 2 | 1 | With resistor and a logic MOSFET |

## Docks and hardware

| Part | Qty | Unit $ | Notes |
|---|---|---|---|
| USB-C receptacle breakout | 3 | 1 | Two docks and the charge port |
| USB 2.0 hub breakout, 4 port | 1 | 4 | Pi data to both docks |
| M3 heat-set inserts | 14 | 0.15 | 4.6 mm outer diameter class |
| Screw kit | 1 | 4 | M3 x 8, M3 x 12, M2.5 x 6, M2 x 5 self tapping |
| Filament, ASA or PETG | 1 | 7 | About 300 g for the core |

**Core camera: about $137.**

## Solar visor (optional, about $10)

| Part | Qty | Unit $ | Notes |
|---|---|---|---|
| 6 V 2 W solar panel, 136 x 110 mm | 1 | 9 | Pocket is parametric, up to 6 W |
| USB-C plug breakout | 1 | 1 | |

## Battery module (optional, about $30)

| Part | Qty | Unit $ | Notes |
|---|---|---|---|
| 32700 LiFePO4 cell, 6 Ah | 2 | 6 | |
| Protection, charger and boost boards | 1 | 16 | Same parts as the core |
| USB-C plug and receptacle breakouts | 1 | 2 | Pass-through so modules stack |
