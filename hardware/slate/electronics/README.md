# Camera carrier, rev A

The circuit that ties the camera together: battery, charger, rails, the
always-on controller, the Raspberry Pi, audio, lights and the two docks.
It is a KiCad 8 project.

| File | What it is |
|---|---|
| `slate.kicad_pro`, `slate.kicad_sch` | Project and root sheet |
| `power.kicad_sch` | Battery path, charger, input OR-ing, 3.3 V and 5 V rails, Pi rail switch |
| `controller.kicad_sch` | XIAO ESP32-C6, PCA9685 PWM expander, PIR, radar, light sensor, pan-tilt |
| `compute.kicad_sch` | Raspberry Pi 40-pin header, I2S amp and mic, IR LEDs, IR-cut, USB hub |
| `docks.kicad_sch` | Two Dock-50 ports with reverse-blocking 5 V switches, light bars, flash LEDs |
| `lib/slate.kicad_sym` | Symbols for the breakout boards and connectors |
| `out/slate-carrier-revA.pdf` | All sheets, ready to print |
| `out/svg/` | One SVG per sheet |
| `out/NETLIST.md`, `out/BOM.md` | Every net with its pins, and every part |
| `out/erc.rpt` | KiCad electrical rules check report |
| `gen_schematic.py` | The source. The circuit is one table of parts and nets |

Open `slate.kicad_pro` in KiCad 8 to browse or edit. To regenerate and
re-check from the command line:

```bash
python gen_schematic.py
kicad-cli sch erc --severity-all slate.kicad_sch
kicad-cli sch export pdf -o out/slate-carrier-revA.pdf slate.kicad_sch
```

## How it works

- **Battery to system.** Pack, 5 A fuse, switch, INA219 shunt, then the
  bq25185 charger. Its power-path output is `VSYS`, at most 4.5 V.
- **Charging.** Three sources are OR-ed through Schottky diodes into the
  charger: the charge port, the top dock and the bottom dock. A 6 V solar
  panel on a dock is just another source.
- **Rails.** `+3V3` comes from a buck-boost that is always on and idles
  under 0.1 mA. `+5V` comes from a boost that the controller can stop
  (`BOOST_OFF`). `+5V_PI` is a soft-started high-side switch (`PI_EN`).
- **Controller.** The ESP32-C6 runs from `+3V3`, watches the PIR on a
  low-power pin, reads both dock CC lines, and owns I2C.
- **PWM expander.** A PCA9685 drives four servos, two flash LEDs and the two
  dock enables. Its outputs are low at power-up, so everything starts off.
- **Docks.** Each has 5.1 k on both CC pins, a sense tap to the controller,
  I2C on SBU through 1 k, USB 2.0 from the hub, and two P-FETs source to
  source. With the pair off, a source on the dock cannot reach the 5 V rail.
- **Compute.** The Pi gets I2S audio, a UART to the controller with 1 k in
  each line, the IR LED switch and the IR-cut control.

## What has been checked, and what has not

Checked by tool:
- KiCad ERC: 0 errors, 0 warnings, with typed pins (power in, power out,
  input, output, passive), so undriven inputs and shorted outputs would show.
- KiCad's exported netlist has the same 78 nets and 90 parts as the source.

Checked against vendor pages on 2026-11-12:
- bq25185 board pads and limits, XIAO ESP32-C6 pin map, Pololu S7V8F3 and
  U3V70F5 pins, ranges and enable behaviour.

Not checked:
- **Nothing has been built or powered.** No bench measurement exists.
- Pin numbers on the box symbols are ours. Wire by the pin name printed on
  each breakout, not by our numbers. Radar, PIR and light sensor header
  order varies by vendor.
- The Raspberry Pi USB test pad names are not on the schematic. `J13` goes
  to the Pi's USB data pads or a cut micro-USB lead.
- Thermal limits, EMC, ESD protection and USB signal integrity.
- There is no PCB layout. Rev A is a schematic for a hand-wired or
  protoboard carrier. A routed board is the next step.

## Limits to respect

- Keep the 5 V rail under about 1.5 A. The charger's load path passes
  3 A peaks from the battery, and at 3.0 V a 7.5 W load is already 2.8 A.
- The charger takes at most 1 A in. A two-row pack needs about a day to
  fill from USB.
- Flash LEDs are run at about 350 mA (1 W) from a 4.7 ohm 2 W resistor.
- The radar needs the 5 V rail, so it is not a deep-sleep wake source.
  The PIR is.
- Do not charge LiFePO4 below 0 C. The charger board has a thermistor pad.
