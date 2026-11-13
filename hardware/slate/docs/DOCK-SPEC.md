# Dock-50 module standard, v0.2

A bay is a USB-C receptacle with a known footprint around it. A module is
anything with a USB-C plug that matches the footprint. The core has two bays,
top and bottom. The bottom bay is the top bay rotated 180 degrees.

## Mechanical

Looking down on a bay, front of the camera towards you. Millimetres from the
centre of the USB-C connector, along the long axis.

| Feature | Position | Host (bay) | Module |
|---|---|---|---|
| Pad | centred | 66 x 24 flat face | 66 x 24 minimum contact face |
| USB-C | 0 | Receptacle, mouth flush with the face, long axis along the pad | Plug, 6.5 mm proud |
| Peg A | -19.0 | Socket 6.3 dia x 4.6 deep | Peg 6.0 dia x 4.0, 0.8 chamfer |
| Peg B | +15.5 | same | same |
| Screw | -27.0 and +27.0 | M3 heat-set insert | 3.4 clearance hole |

The pegs are offset so a module cannot be fitted backwards. That keeps the
plug orientation fixed, which the SBU pin assignment below relies on.

Fit the plug so it floats. The module pocket is 12.8 x 6.8 mm. Dock the module
once with the plug loose, then glue the plug in place. The pegs set the
position, not your printer.

A module may be wider than the pad. The flat top of the core is 152 mm wide
and 42 mm deep. A stacking module repeats the host features on its far face.

`dock_cap.stl` is the reference male part. Print it to test fit.

## Electrical

| USB-C pin | Use |
|---|---|
| VBUS | 5 V, either direction. Bay input accepts 4.5 to 7.5 V |
| GND | Ground |
| CC1 | Role. Module pulls up (56 k to VBUS) to offer power, pulls down (5.1 k) to request it |
| D+ / D- | USB 2.0 to the Pi through the hub |
| SBU1 | I2C SDA, 3.3 V, to the always-on controller |
| SBU2 | I2C SCL, 3.3 V |

Rules:

1. **Source modules** (solar, battery, wall adapter) put 4.5 to 7.5 V on VBUS.
   It only ever feeds the charger input through a diode. It never reaches the
   5 V system rail.
2. **Sink modules** (lidar, speaker, floodlight) get 5 V from the core through
   a load switch, 1.5 A per bay. The controller can cut it to save power.
3. The core presents 5.1 k on CC by default, so a standard USB-C charger or
   power bank on a C to C cable works as a source with no extra parts.
4. I2C on SBU is only for Nurby modules. Put 1 k in series on the core side.
   Standard USB devices leave SBU alone.
5. A stacking module keeps its upstream and downstream VBUS separate, with a
   diode from upstream to downstream. A battery module must never be able to
   charge itself from its own output.

v0.1 limitation: the controller does not yet toggle roles on its own. Set each
bay to "source" or "sink" in the controller config. Automatic dual-role
detection is firmware work and needs no hardware change.

## Module ideas

| Module | Uses |
|---|---|
| Solar visor | VBUS source |
| Battery, stacking | VBUS source, pass-through charge |
| Lidar or ToF ranger | USB, or I2C on SBU |
| Large speaker or siren | USB audio |
| Floodlight | VBUS sink, I2C dimming |
| LTE modem | USB |
| mmWave presence sensor | I2C on SBU, works while the Pi sleeps |

## Added in v0.2

- **Side points.** Each side of the Slate has two M3 inserts at the same
  +/-27 mm pitch as the dock screws. `handle` and `bracket_l` fit any side
  and either dock.
- **Dock foot.** `dock_foot` is a stand-alone bay you can screw to a wall,
  ceiling or bench. Anything with a male dock stands on it.
- **Barrel.** The Barrel has a male dock on its belly and a bay on top. Both
  run across the body, so a joint under it pitches the lens up and down.
- **Orbit.** Male dock below, bay on the cradle. Cradle face is 126.5 mm
  above the host face at zero tilt. The pan-tilt connector on the mainboard
  (J13) carries two servo signals and 5 V.
