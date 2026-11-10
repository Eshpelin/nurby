# Nurby open camera

An open source security camera you print and build yourself. Two bodies share
one mainboard, one battery format and one module standard:

- **Slate**: flat wall body, 164 x 146 x 42 mm, snaps onto a magnetic plate.
- **Barrel**: cylindrical body, 76 mm diameter x 172 mm, for people who want a
  camera that looks like a camera.

**Status: v0.2 reference design.** Every part builds as a valid solid and the
parts are checked against each other in software. Nothing has been printed,
wired or powered. Treat every fit, force and power number as unproven.

## What v0.2 has

| | |
|---|---|
| Battery | 32700 LiFePO4 on a removable sled. Slate takes rows of two cells: 1, 2 or 3 rows (38, 77, 115 Wh) by changing `CELL_ROWS`. Barrel takes pairs along its length (`B_PAIRS`) |
| Mount | Magnetic wall plate: three 20 x 3 mm magnet pairs hold it, two pegs carry the weight. The plate also takes VESA 75 |
| Tracker bay | Pocket for an AirTag-class tag under the compute board |
| Sensing | PIR, 24 GHz mmWave presence radar (LD2410C pocket behind the face), ambient light sensor window |
| Cameras | Two lens ports on the Slate: wide main sensor plus a close-up or barcode camera. Barrel has a main lens and a small second lens |
| Lenses | 30 mm ports closed by swappable bezels: M12, or CS-mount with a hood |
| Lights | Two RGBW bars (red and blue strobe, white flood), two 3 W flash LEDs, two 850 nm IR LEDs. Barrel uses a 16-LED ring |
| Sealing | TPU face gasket, capped docks, membrane vent. IP65 is the target, not a tested rating |
| Mounting points | Two M3 inserts on each side at the Dock-50 screw pitch, so the handle and angle bracket fit any side or either dock |
| Pan-tilt | Orbit: a two-axis joint with a dock below and a dock on its cradle. Under the Barrel it aims the camera. Under a solar panel it tracks the sun. Use two for both |
| Mainboard | Rev A placement, 68 x 42 mm, used in both bodies |

## What is here

```
cad/slate.py        Single parametric source (CadQuery). 28 printed parts.
print/*.stl         Print files, already oriented.
step/*.step         Editable solids.
web/                Viewer meshes, mainboard.json, dims.json.
docs/               BUILD, BOM, POWER, DOCK-SPEC.
```

```bash
pip install cadquery
python cad/slate.py
```

## Honest limits

- **Mainboard rev A is a placement drawing.** There is no schematic, netlist
  or Gerber set yet. The build guide still wires off-the-shelf boards.
- **Orbit is a first mechanical pass.** Both axes are direct-drive standard
  servos. The cable to the cradle is a service loop, not a slip ring. Servo
  torque against a 600 g Barrel has not been checked.
- **Pan-tilt is for the Barrel and for solar.** The Slate is a fixed body.
- **Magnet hold is unmeasured.** Do not hang it above people until it is.
- **CS-mount** has a bezel but no carrier pattern yet. Set the post pattern in
  `slate_camera_carrier` for your board.
- **Industrial use** (counting, inspection, traffic) is a hardware allowance:
  sealing, second camera, flash, brackets. No vision software ships with this.
- Always-on streaming drains a 77 Wh Slate in about 32 hours. See
  [docs/POWER.md](docs/POWER.md).

## License

Not set yet. Proposed: CERN-OHL-S v2 for hardware and CAD. Until a license
file lands here, the repo license applies.
