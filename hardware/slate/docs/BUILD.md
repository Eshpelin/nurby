# Build guide, v0.1

Untested. This is the intended build. Expect to adjust.

## Print

| Setting | Value |
|---|---|
| Material | ASA in direct sun. PETG under cover. Not PLA |
| Layer | 0.2 mm |
| Walls | 4 |
| Infill | 25% |
| Supports | None for the core. The solar visor needs support under its dock foot |
| Bed | 180 x 180 mm is enough |

Files in `print/` are already oriented. Print two `dock_cap`.

Light colours run cooler. Print the lens hood and front plate in black to cut
glare around the lens.

## Heat-set inserts (M3)

- 4 in the front corners of the back shell
- 4 in the back, from the outside (VESA 75)
- 2 in each dock pad, from the outside
- 2 in the front plate bosses, for the camera carrier
- Battery module: 2 for the lid, 2 in its top dock. Dev module: 1 for the lid

## Power tree

```
USB-C charge port ──┐
Top bay VBUS ──|>|──┼──> charger (LiFePO4, 3.6 V) ──> protection board ──> cells 1S2P
Bottom bay VBUS ─|>|┘                │                      │
                                     └── load output ───────┴──> fuse 5 A ──> switch
                                                                      │
                                                    ┌─────────────────┤
                                              3.3 V to controller   5 V boost (3 A)
                                              (its own regulator)     │
                                    ┌───────────────┬─────────────────┼──────────────┐
                              load switch       load switch       load switch     LED bars
                              (Pi rail)         (top bay out)     (bottom bay out)
```

Build and test in this order. Do not connect the Pi until step 4 passes.

1. Solder the two cells in parallel with 18 AWG wire. Fit the protection board.
2. Add fuse and switch. Measure 3.2 to 3.4 V after the switch.
3. Wire charger and boost. Set the charger to LiFePO4 (3.6 V) before first use.
4. Measure 5.0 to 5.2 V at the boost output with a 1 A load.
5. Plug USB-C in. Confirm charge current. Stop if anything is warm.

## Controller pins (XIAO ESP32-C6)

Confirm low-power wake capability of each pin against the board's pinout
before soldering.

| Pin | Net | Notes |
|---|---|---|
| D0 | PIR out | Wake source |
| D1 | CC sense, top bay | ADC |
| D2 | CC sense, bottom bay | ADC |
| D3 | PI_EN | Pi rail load switch, pulled low |
| D4 / D5 | I2C SDA / SCL | INA219, SBU on both bays |
| D6 / D7 | UART TX / RX | To the Pi, 3.3 V |
| D8 | LED data | Both RGBW bars in one chain, 16 pixels |
| D9 | BAY_TOP_EN | 5 V out to the top bay |
| D10 | BAY_BOT_EN | 5 V out to the bottom bay |

## Pi pins

| GPIO | Net |
|---|---|
| 14 / 15 | UART to the controller |
| 18 / 19 | I2S bit clock / word select (mic and amp share) |
| 20 | I2S data in, from the INMP441 |
| 21 | I2S data out, to the MAX98357A |
| 23 | IR-cut filter control |
| 24 | IR LED MOSFET gate |
| 25 | Amplifier shutdown |
| 5 V, GND header pins | Power from the Pi rail load switch |
| USB data port | To the hub, then both bays |

## Assembly order

1. Cells into the cradle, tabs outward, a foam strip on top.
2. Pi on its four standoffs with M2.5 screws. Ports face down.
3. Controller, charger, boost, hub and monitor on the peg grid with M2 screws.
4. USB-C breakouts into the dock pockets and the charge port. Receptacle mouth
   flush with the outer face. Epoxy the board edges.
5. Camera board on the back of the carrier, lens through the hole. Carrier
   onto the front plate bosses.
6. Light bars, PIR, mic and speaker into their pockets. A dab of silicone each.
7. Close the front plate with four M3 x 8. Glue the lens hood.
8. Wall plate on the back with four M3 x 12, heads on the wall side. Hang on
   two wall screws and slide down.

## Firmware bring-up

Enough to see a picture. Not the final firmware.

`/boot/firmware/config.txt`:

```
camera_auto_detect=0
dtoverlay=imx462
dtoverlay=googlevoicehat-soundcard
enable_uart=1
```

Some IMX462 boards need `dtoverlay=imx462,clock-frequency=74250000`. Check the
vendor page for yours.

Install MediaMTX, then in `mediamtx.yml`:

```yaml
paths:
  cam:
    source: rpiCamera
    rpiCameraWidth: 1920
    rpiCameraHeight: 1080
    rpiCameraFPS: 15
    rpiCameraBitrate: 2000000
```

The stream is then at `rtsp://<host>:8554/cam`. Add that URL to Frigate, your
NVR, or Nurby. ONVIF discovery, two-way audio and the controller firmware are
the next firmware milestones.

## Safety

- Fit the fuse and the protection board. Both, always.
- Do not charge LiFePO4 below 0 C.
- Do not mount in a spot that traps heat behind glass.
- Disconnect the battery switch before opening the case.
