# Nurby Slate

An open source security camera you print and build yourself. Flat slab body,
LiFePO4 battery, solar visor, USB-C module bays, and plain RTSP so it works
with Frigate, any NVR or DVR, Home Assistant, and Nurby.

**Status: v0.1 reference design.** The CAD builds clean solids and the parts
are checked against each other in software. Nobody has printed, wired or
powered one yet. Treat every fit and every power number as unproven until a
build log says otherwise.

| | |
|---|---|
| Body | 164 x 112 x 42 mm, wall mounted, VESA 75 pattern on the back |
| Compute | Raspberry Pi Zero 2 W (any Zero-footprint board fits) |
| Always-on controller | ESP32-C6: Wi-Fi control, PIR wake, lights, power switching |
| Sensor | Sony STARVIS IMX462 with switchable IR-cut, two 850 nm LEDs |
| Battery | 2 x 32700 LiFePO4, 1S2P, 38 Wh. Each battery module adds 38 Wh |
| Charging | USB-C, or solar through the top bay |
| Lights | Two 8-LED RGBW bars: red and blue strobe, or white flood |
| Audio | I2S microphone, 3 W I2S amplifier, 28 mm speaker |
| Modules | Two Dock-50 bays (top and bottom). Modules stack |
| Core cost | About $137 in single-unit parts |

## What is here

```
cad/slate.py     Parametric source (CadQuery). Edit a number, regenerate everything.
print/*.stl      Print files, already in print orientation.
step/*.step      Editable solids in assembly position.
web/*.stl        Low-poly meshes for the website viewer.
docs/BUILD.md    Print settings, wiring, pin tables, assembly, firmware bring-up.
docs/BOM.md      Parts list.
docs/POWER.md    Power budget and what "7 days" really takes.
docs/DOCK-SPEC.md  The Dock-50 module standard.
```

Regenerate after editing:

```bash
pip install cadquery
python cad/slate.py
```

## Design decisions

**Flat slab, not a bullet or dome.** A 42 mm deep plaque draws less attention,
mounts with two screws, and gives two long flat edges for module bays.

**Two brains.** A Pi cannot sleep. So an ESP32-C6 stays awake on milliwatts and
switches the Pi's 5 V rail. That one load switch is what makes week-long
battery life possible, and it is the main thing v0.1 hardware has to get right.
Firmware tuning comes later.

**Starlight first, IR second.** The IMX462 keeps colour in very low light and
is unusually sensitive in near infrared. The white LEDs in the light bars give
colour video on an event. The IR-cut filter and 850 nm LEDs cover covert,
no-light recording.

**LiFePO4, single cell voltage.** Cells in parallel need no balancing. The
chemistry tolerates heat, lasts thousands of cycles, and fails gently.

**USB-C as the module connector.** It is the one connector everyone already
owns. Any USB-C charger or power bank is a valid power module with no adapter.

**Off-the-shelf boards in v0.1.** No custom PCB yet, so anyone can build it
with a soldering iron. A single carrier board that replaces the loose
breakouts is the obvious next step.

## Known limits

- Always-on 24/7 streaming drains the 38 Wh core in under a day. See
  [docs/POWER.md](docs/POWER.md).
- In event-wake mode the Pi cold boots, so the first seconds of an event are
  lost and an NVR sees the stream come and go. Fast boot is firmware work.
- Not weather sealed. Under an eave it should be fine. No IP rating is claimed.
- Dock role detection (source or sink) is set by hand in v0.1.
- Camera board hole spacing varies by vendor. The carrier defaults to the
  Raspberry Pi camera pattern.

## License

Not set yet. Proposed: CERN-OHL-S v2 for hardware and CAD, to match the
project's AGPL software license. Until a license file lands here, the repo
license applies.
