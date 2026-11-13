"""Nurby Slate v0.2 - parametric CAD for the open source camera family.

Two bodies share one module standard (Dock-50), one mainboard and one
battery format:

  Slate   flat wall body, magnetic back plate
  Barrel  cylindrical body that looks like a classic camera

Run:  python slate.py [out_dir]

Writes, relative to out_dir (default: the parent "slate" directory):
  print/*.stl          parts in print orientation
  step/*.step          the same parts as editable solids
  web/*.stl            low-poly parts and bought-part stand-ins for the viewer
  web/mainboard.json   mainboard rev A placement, drawn by the website

Requires CadQuery 2.4+  (pip install cadquery). All dimensions in mm.

Frames
  Slate:   X width, Y up, Z depth. Back on Z = 0, lens looks along +Z.
  Barrel:  Z is the lens axis, Y up. Rear dome at Z = 0.
  Module:  dock face on Z = 0, body above, front towards -Y.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import cadquery as cq

V = cq.Vector

# --------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------
W, D = 164.0, 42.0
CELL_ROWS = 2                  # rows of two 32700 cells. 1 = 38 Wh, 2 = 77 Wh, 3 = 115 Wh
H = 78.0 + 34.0 * CELL_ROWS    # 146 with two rows
R = 16.0                       # corner radius
EDGE = 1.5
WALL = 2.4
FP_T = 3.0
SHELL_D = D - FP_T
CLR = 0.2
INSERT_D = 4.0                 # hole for an M3 heat-set insert
M3_CLEAR = 3.4

# Vertical zones inside the Slate body
Y0 = -H / 2
SERV_Y0 = Y0 + WALL            # service strip: charge port, bottom dock
BAT_Y0 = SERV_Y0 + 16.0        # battery rows
ELEC_Y0 = BAT_Y0 + 34.0 * CELL_ROWS
TOP_IN = H / 2 - WALL

CELL_D, CELL_L = 32.2, 70.5
CELL_Z = WALL + 0.4 + CELL_D / 2
ROW_Y = [BAT_Y0 + 17.0 + 34.0 * i for i in range(CELL_ROWS)]

# Dock-50 (docs/DOCK-SPEC.md)
PEG_X = (-19.0, 15.5)
PEG_D, PEG_H = 6.0, 4.0
SCREW_X = (-27.0, 27.0)        # also the pitch of the side mounting points
PAD_W, PAD_HALF_DEPTH, PAD_T = 66.0, 12.0, 8.4
USBC_SLOT = (9.4, 3.7)
USBC_PCB = (24.0, 6.5)
USBC_PLUG = (12.8, 6.8)

# Slate layout
PI_C = (-39.5, ELEC_Y0 + 31.0)
PI_STANDOFF = 9.5              # tall enough to hide a tracker tag underneath
TAG_D, TAG_T = 32.3, 8.2       # AirTag class tracker
MB = dict(x0=1.0, y0=ELEC_Y0 + 4.0, w=68.0, h=42.0, lift=6.0)
SPK_Y, SPK_Z, SPK_D = ELEC_Y0 + 32.0, 20.5, 28.0
MAG_D, MAG_T = 20.0, 3.0       # N52 disc magnets, one pair per point
MAG_PTS = [(0.0, ELEC_Y0 + 34.6), (-48.0, BAT_Y0 + 34.0 * (CELL_ROWS - 1)), (48.0, BAT_Y0 + 34.0 * (CELL_ROWS - 1))]
KEY_PTS = [(-22.0, ELEC_Y0 + 3.0), (22.0, ELEC_Y0 + 3.0)]  # shear pegs
SIDE_Y = (-27.0, 27.0)

# Slate face
LENS_Y = ELEC_Y0 + 17.0
LENS_X = 20.0                  # two lens ports: main and close-up/barcode
PORT_D = 30.0                  # port takes a swappable bezel: M12 or CS
LED_Y = ELEC_Y0 - 9.4          # light bars sit in front of the top cell row
LED_X = 28.0
IR_PTS = [(-8.0, LED_Y + 10.6), (8.0, LED_Y + 10.6)]
FLASH_PTS = [(-60.0, LENS_Y + 11.0), (60.0, LENS_Y + 11.0)]
PIR = (-56.0, LENS_Y - 7.0, 10.3)
RADAR = (56.0, LENS_Y - 6.0)   # LD2410C, 22 x 16, sees through the plate
ALS = (0.0, LENS_Y + 6.0)      # ambient light sensor window
MIC = (0.0, LENS_Y - 9.0)
CAM_BOSSES = [(0.0, LENS_Y + 19.0), (0.0, LENS_Y - 16.0), (-40.0, LENS_Y), (40.0, LENS_Y)]
VIS = dict(w=146.0, y0=LED_Y - 9.0, y1=LENS_Y + 20.0, r=18.0, t=1.6)

# Solar panel. Default pocket fits the common 6 V 2 W panel.
PANEL_W, PANEL_D, PANEL_T = 136.0, 110.0, 3.0
VISOR_TILT, VISOR_NECK = 20.0, 28.0

# Modules
BM_W, BM_H = 132.0, 84.0
DM_W, DM_H = 66.0, 40.0
LID_T = 2.4

# Orbit pan-tilt joint. Standard size servo: 40.5 x 20.2 x 37.2, 25T spline.
OB_W, OB_H = 84.0, 57.0
SERVO = dict(l=40.5, w=20.2, h=37.2, off=10.25, tab_z=27.5, tab_l=54.5)
ORBIT_ZT = 66.0 + SERVO["w"] / 2       # tilt axis height above the dock face
ORBIT_ARM = 42.0
ORBIT_TOP = ORBIT_ZT + ORBIT_ARM + PAD_T

# Barrel
BR = 38.0
B_PAIRS = 1                    # cell pairs along the barrel. 1 = 38 Wh, 2 = 77 Wh
BL = 100.0 + 72.0 * B_PAIRS
B_DOCK_Z = BL / 2
B_PAD_Y = BR + 1.5
B_SLED_Y = -16.6               # top of the sled plate


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def rbox(w, h, d, r):
    s = cq.Workplane("XY").rect(w, h).extrude(d)
    return s.edges("|Z").fillet(r) if r > 0 else s


def rrect(x0, x1, y0, y1, z0, z1, r):
    return rbox(x1 - x0, y1 - y0, z1 - z0, r).translate(((x0 + x1) / 2, (y0 + y1) / 2, z0))


def cyl_z(x, y, dia, z0, z1):
    return cq.Workplane("XY").circle(dia / 2).extrude(z1 - z0).translate((x, y, z0))


def cyl_y(x, z, dia, y0, y1):
    c = cq.Workplane("XY").circle(dia / 2).extrude(y1 - y0)
    return c.rotate((0, 0, 0), (1, 0, 0), -90).translate((x, y0, z))


def cyl_x(y, z, dia, x0, x1):
    c = cq.Workplane("XY").circle(dia / 2).extrude(x1 - x0)
    return c.rotate((0, 0, 0), (0, 1, 0), 90).translate((x0, y, z))


def union(parts):
    out = parts[0]
    for p in parts[1:]:
        out = out.union(p)
    return out


def soft(s, selector, r):
    """Fillet if the kernel can, otherwise leave the edge sharp."""
    try:
        return s.edges(selector).fillet(r)
    except Exception:
        return s


def rx(s, deg):
    return s.rotate((0, 0, 0), (1, 0, 0), deg)


# --------------------------------------------------------------------------
# Dock-50. Canonical frame: mating face Z = 0, long axis X, +Y to the back.
# --------------------------------------------------------------------------
def dock_female_pad(back=PAD_HALF_DEPTH):
    return box(-PAD_W / 2, PAD_W / 2, -PAD_HALF_DEPTH, back, -PAD_T, 0)


def dock_female_cut():
    parts = [cyl_z(px, 0, PEG_D + 0.3, -(PEG_H + 0.6), 1) for px in PEG_X]
    parts += [cyl_z(sx, 0, INSERT_D, -7.0, 1) for sx in SCREW_X]
    sw, sh = USBC_SLOT
    parts.append(box(-sw / 2, sw / 2, -sh / 2, sh / 2, -1.3, 1))
    pw, ph = USBC_PCB
    parts.append(box(-pw / 2, pw / 2, -ph / 2, ph / 2, -PAD_T - 1, -1.2))
    return union(parts)


def dock_male_pegs():
    pegs = []
    for px in PEG_X:
        p = cq.Workplane("XY").circle(PEG_D / 2).extrude(PEG_H + 0.1).faces(">Z").chamfer(0.8)
        pegs.append(p.rotate((0, 0, 0), (1, 0, 0), 180).translate((px, 0, 0.1)))
    return union(pegs)


def dock_male_cut(floor_t, plug=True):
    parts = [cyl_z(sx, 0, M3_CLEAR, -1, floor_t + 1) for sx in SCREW_X]
    if plug:
        pw, ph = USBC_PLUG
        parts.append(box(-pw / 2, pw / 2, -ph / 2, ph / 2, -1, floor_t + 1))
    return union(parts)


def to_top(s):
    return rx(s, -90).translate((0, H / 2, D / 2))


def to_bottom(s):
    return rx(s, -90).rotate((0, 0, 0), (0, 0, 1), 180).translate((0, -H / 2, D / 2))


def to_side(s, sign):
    """Canonical frame onto the right (+1) or left (-1) side of the Slate."""
    s = s.rotate((0, 0, 0), (0, 1, 0), 90).rotate((0, 0, 0), (1, 0, 0), 90)
    if sign < 0:
        s = s.rotate((0, 0, 0), (0, 0, 1), 180)
    return s.translate((sign * W / 2, 0, D / 2))


def to_barrel(s, y):
    """Canonical frame onto the barrel, long axis across it. y = +pad or -pad."""
    return rx(s, -90).translate((0, y, B_DOCK_Z))


# --------------------------------------------------------------------------
# Slate body
# --------------------------------------------------------------------------
def corner_points(inset=10.0):
    return [(sx * (W / 2 - inset), sy * (H / 2 - inset)) for sx in (-1, 1) for sy in (-1, 1)]


def pi_points():
    return [(PI_C[0] + sx * 29.0, PI_C[1] + sy * 11.5) for sx in (-1, 1) for sy in (-1, 1)]


def mb_points():
    return [(MB["x0"] + x, MB["y0"] + y) for x in (3.5, MB["w"] - 3.5) for y in (3.5, MB["h"] - 3.5)]


def slate_back_shell():
    outer = rbox(W, H, SHELL_D, R).faces("<Z").chamfer(EDGE)
    inner = rbox(W - 2 * WALL, H - 2 * WALL, SHELL_D, R - WALL).translate((0, 0, WALL))
    s = outer.cut(inner)

    boss_top = SHELL_D - 7.2
    adds = [cyl_z(x, y, 10.0, 0.5, boss_top) for x, y in corner_points()]
    adds += [cyl_z(x, y, 6.0, WALL - 0.1, WALL + PI_STANDOFF) for x, y in pi_points()]
    adds += [cyl_z(x, y, 6.0, WALL - 0.1, WALL + MB["lift"]) for x, y in mb_points()]
    # Magnet seats and shear key bosses
    adds += [cyl_z(x, y, MAG_D + 4.0, WALL - 0.1, WALL + 1.6) for x, y in MAG_PTS]
    adds += [cyl_z(x, y, 14.0, WALL - 0.1, WALL + 2.0) for x, y in KEY_PTS]
    # Tracker tag ring under the Pi
    adds.append(cyl_z(PI_C[0], PI_C[1], TAG_D + 3.6, WALL - 0.1, WALL + TAG_T))
    # Speaker guide ribs on the right wall
    for y0 in (SPK_Y - SPK_D / 2 - 3, SPK_Y + SPK_D / 2 - 3):
        adds.append(box(W / 2 - WALL - 7.6, W / 2 - WALL - 6.0, y0, y0 + 6, WALL - 0.1, WALL + 33))
    # Side mounting points
    for sx in (-1, 1):
        for y in SIDE_Y:
            x0, x1 = sorted((sx * (W / 2 - WALL - 6.0), sx * (W / 2 - 0.5)))
            adds.append(cyl_x(y, D / 2, 9.0, x0, x1))
    adds.append(to_top(dock_female_pad(back=D / 2 - 0.1)))
    adds.append(to_bottom(dock_female_pad(back=D / 2 - 0.1)))
    s = s.union(union(adds)).intersect(outer)

    cuts = []
    for x, y in corner_points():
        cuts.append(cyl_z(x, y, M3_CLEAR, -1, SHELL_D))
        cuts.append(cyl_z(x, y, 6.5, -1, boss_top - 5.0))
    cuts += [cyl_z(x, y, 2.2, WALL + 1, WALL + PI_STANDOFF + 1) for x, y in pi_points()]
    cuts += [cyl_z(x, y, 2.2, WALL + 1, WALL + MB["lift"] + 1) for x, y in mb_points()]
    # Magnets sit 1 mm from the outside
    cuts += [cyl_z(x, y, MAG_D + 0.3, 1.0, WALL + 2) for x, y in MAG_PTS]
    cuts += [cyl_z(x, y, 10.4, -1, 2.6) for x, y in KEY_PTS]
    cuts.append(cyl_z(PI_C[0], PI_C[1], TAG_D, WALL, WALL + TAG_T + 1))
    cuts.append(box(PI_C[0] - 5, PI_C[0] + 5, PI_C[1] - 30, PI_C[1], WALL, WALL + TAG_T + 1))  # finger notch
    for i in range(-4, 5):
        for j in range(-4, 5):
            gy, gz = i * 3.2 + (1.6 if j % 2 else 0), j * 2.8
            if math.hypot(gy, gz) <= SPK_D / 2 - 2.5:
                cuts.append(cyl_x(SPK_Y + gy, SPK_Z + gz, 1.8, W / 2 - WALL - 1, W / 2 + 1))
    for sx in (-1, 1):
        for y in SIDE_Y:
            x0, x1 = sorted((sx * (W / 2 - 7.0), sx * (W / 2 + 1)))
            cuts.append(cyl_x(y, D / 2, INSERT_D, x0, x1))
    cuts.append(to_top(dock_female_cut()))
    cuts.append(to_bottom(dock_female_cut()))
    sw, sh = USBC_SLOT
    cuts.append(box(50 - sw / 2, 50 + sw / 2, Y0 - 1, Y0 + WALL + 1, D / 2 - sh / 2, D / 2 + sh / 2))
    cuts.append(cyl_y(-50, D / 2, 6.2, Y0 - 1, Y0 + WALL + 1))   # battery switch
    cuts.append(cyl_y(-30, D / 2, 3.0, Y0 - 1, Y0 + WALL + 1))   # pressure vent, membrane inside
    return s.cut(union(cuts))


def slate_front_plate():
    z0 = SHELL_D
    p = rbox(W, H, FP_T, R).faces(">Z").chamfer(EDGE).translate((0, 0, z0))
    rw, rh = W - 2 * WALL - 2 * CLR, H - 2 * WALL - 2 * CLR
    ring = rbox(rw, rh, 1.6, R - WALL).cut(rbox(rw - 3.2, rh - 3.2, 1.6, R - WALL - 1.6))
    adds = [ring.translate((0, 0, z0 - 1.6))]
    adds += [cyl_z(x, y, 8.0, z0 - 7, z0 + 0.1) for x, y in corner_points()]
    adds += [cyl_z(x, y, 8.0, z0 - 7, z0 + 0.1) for x, y in CAM_BOSSES]
    for sx in (-1, 1):
        cx = sx * LED_X
        f = box(cx - 27.8, cx + 27.8, LED_Y - 7.3, LED_Y + 7.3, z0 - 3, z0 + 0.1)
        adds.append(f.cut(box(cx - 25.9, cx + 25.9, LED_Y - 5.4, LED_Y + 5.4, z0 - 4, z0)))
    # Radar pocket, flash seats, ambient light sensor seat
    rxc, ryc = RADAR
    adds.append(box(rxc - 12.2, rxc + 12.2, ryc - 9.2, ryc + 9.2, z0 - 3, z0 + 0.1).cut(
        box(rxc - 11.2, rxc + 11.2, ryc - 8.2, ryc + 8.2, z0 - 4, z0)))
    for x, y in FLASH_PTS:
        adds.append(cyl_z(x, y, 20.0, z0 - 2.5, z0 + 0.1).cut(cyl_z(x, y, 16.4, z0 - 3, z0)))
    p = p.union(union(adds))

    cuts = [cyl_z(sx * LENS_X, LENS_Y, PORT_D, z0 - 1, D + 1) for sx in (-1, 1)]
    cuts += [cyl_z(x, y, INSERT_D, z0 - 8, z0 - 1.0) for x, y in corner_points() + CAM_BOSSES]
    for sx in (-1, 1):
        cuts.append(box(sx * LED_X - 24, sx * LED_X + 24, LED_Y - 3, LED_Y + 3, z0 - 1, D + 1))
    cuts.append(cyl_z(PIR[0], PIR[1], PIR[2], z0 - 1, D + 1))
    cuts.append(cyl_z(ALS[0], ALS[1], 3.0, z0 - 1, D + 1))
    cuts.append(cyl_z(MIC[0], MIC[1], 1.5, z0 - 1, D + 1))
    cuts += [cyl_z(x, y, 5.2, z0 - 1, D + 1) for x, y in IR_PTS]
    cuts += [cyl_z(x, y, 9.0, z0 - 1, D + 1) for x, y in FLASH_PTS]
    return p.cut(union(cuts))


def _visor_blank():
    cy = (VIS["y0"] + VIS["y1"]) / 2
    v = rbox(VIS["w"], VIS["y1"] - VIS["y0"], VIS["t"], VIS["r"]).faces(">Z").chamfer(0.6)
    return v.translate((0, cy, D))


def slate_visor():
    """Gloss island over lenses, light bars and sensors. Smoke translucent
    PETG, or 1.5 mm smoked acrylic cut to the STEP outline."""
    t = VIS["t"]
    cuts = [cyl_z(sx * LENS_X, LENS_Y, PORT_D, D - 1, D + t + 1) for sx in (-1, 1)]
    cuts.append(cyl_z(PIR[0], PIR[1], PIR[2], D - 1, D + t + 1))
    cuts.append(cyl_z(ALS[0], ALS[1], 3.0, D - 1, D + t + 1))
    cuts.append(cyl_z(MIC[0], MIC[1], 1.5, D - 1, D + t + 1))
    cuts += [cyl_z(x, y, 9.0, D - 1, D + t + 1) for x, y in FLASH_PTS]
    return _visor_blank().cut(union(cuts))


def lens_bezel(kind="m12", x=LENS_X):
    """Plug that closes a lens port. m12 for board lenses, cs for CS-mount
    lenses, with a short hood."""
    z0, z1 = SHELL_D, D + VIS["t"]
    b = cyl_z(x, LENS_Y, PORT_D - 0.3, z0, z1).union(cyl_z(x, LENS_Y, PORT_D + 3.0, z1, z1 + 1.2))
    if kind == "cs":
        b = b.union(cyl_z(x, LENS_Y, PORT_D + 3.0, z1, z1 + 14.0))
        return b.cut(cyl_z(x, LENS_Y, 27.0, z0 - 1, z1 + 15))
    return b.cut(cyl_z(x, LENS_Y, 15.0, z0 - 1, z1 + 2))


def slate_camera_carrier():
    """Holds two sensor boards behind the lens ports. Posts follow the
    Raspberry Pi camera pattern (21 x 12.5, M2). Edit for other boards."""
    zf = SHELL_D - 7.0
    c = rrect(-44, 44, LENS_Y - 20, LENS_Y + 23, zf - 2, zf, 4)
    posts = [(sx * LENS_X + px, LENS_Y + py) for sx in (-1, 1) for px in (-10.5, 10.5) for py in (0.0, 12.5)]
    c = c.union(union([cyl_z(x, y, 4.5, zf - 3.5, zf - 1.9) for x, y in posts]))
    cuts = [cyl_z(sx * LENS_X, LENS_Y, 17.0, zf - 3, zf + 1) for sx in (-1, 1)]
    cuts += [cyl_z(x, y, M3_CLEAR, zf - 3, zf + 1) for x, y in CAM_BOSSES]
    cuts += [cyl_z(x, y, 1.8, zf - 4, zf + 1) for x, y in posts]
    cuts.append(box(-5, 5, LENS_Y - 12, LENS_Y + 12, zf - 3, zf + 1))  # sensor wiring
    return c.cut(union(cuts))


def slate_battery_sled():
    """Carries the cells as one cartridge. Add rows by changing CELL_ROWS."""
    y_lo, y_hi = BAT_Y0 + 0.5, ELEC_Y0 - 0.5
    parts = [box(x0, x0 + 1.4, y_lo, y_hi, WALL + 0.2, WALL + 24) for x0 in (-73.3, -0.7, 71.9)]
    for k in range(CELL_ROWS + 1):
        y = BAT_Y0 + 34.0 * k
        parts.append(box(-73.3, 73.3, max(y - 1, y_lo), min(y + 1, y_hi), WALL + 2, WALL + 7))
    s = union(parts)
    cuts = [cyl_x(y, CELL_Z, 11.0, -80, 80) for y in ROW_Y]                      # contact windows
    cuts += [cyl_x(y, CELL_Z, CELL_D + 0.6, x0, x1) for y in ROW_Y for x0, x1 in ((-71.9, -0.7), (0.7, 71.9))]
    return s.cut(union(cuts))


def slate_gasket():
    """Face seal between shell and front plate. Print in TPU 95A."""
    g = rbox(W, H, 0.8, R).cut(rbox(W - 2 * WALL, H - 2 * WALL, 0.8, R - WALL))
    return g.translate((0, 0, SHELL_D - 0.4))


def mag_plate():
    """Wall plate. Three magnet pairs hold the camera, two pegs take the
    weight. Screws to a wall or to any VESA 75 arm."""
    t = 6.0
    ys = [y for _, y in MAG_PTS]
    y_lo, y_hi = min(ys) - 16, max(ys) + 18
    cy = (y_lo + y_hi) / 2
    p = rrect(-62, 62, y_lo, y_hi, -t, 0, 14)
    p = p.union(union([cyl_z(x, y, 10.0, -0.1, 2.4).faces(">Z").chamfer(0.6) for x, y in KEY_PTS]))
    cuts = [cyl_z(x, y, MAG_D + 0.3, -(MAG_T + 0.1), 1) for x, y in MAG_PTS]
    for sx in (-1, 1):
        for sy in (-1, 1):
            cuts.append(cyl_z(sx * 37.5, cy + sy * 37.5, 4.5, -t - 1, 1))
            cuts.append(cyl_z(sx * 37.5, cy + sy * 37.5, 8.5, -2.5, 1))
    for ky in (cy - 20, cy + 14):
        cuts.append(cyl_z(-30, ky, 9.0, -t - 1, 1))
        cuts.append(box(-32.3, -27.7, ky, ky + 10, -t - 1, 1))
        cuts.append(box(-34.5, -25.5, ky, ky + 10, -t + 2.5, 1))
        cuts.append(cyl_z(-30, ky + 10, 9.0, -t + 2.5, 1))
    return p.cut(union(cuts))


def handle():
    """Carry handle or tie-off loop. Fits the two M3 points on any side,
    and either dock."""
    feet = union([rrect(sx - 7, sx + 7, -7, 7, 0, 22, 3) for sx in SCREW_X])
    bar = rrect(SCREW_X[0] - 7, SCREW_X[1] + 7, -7, 7, 16, 24, 3)
    h = soft(feet.union(bar), "|Y", 2.0)
    cuts = [cyl_z(sx, 0, M3_CLEAR, -1, 30) for sx in SCREW_X]
    cuts += [cyl_z(sx, 0, 6.5, 3.5, 30) for sx in SCREW_X]
    return h.cut(union(cuts))


def bracket_l():
    """Angle bracket for poles, rails and machine frames. Same two points."""
    b = rrect(-36, 36, -9, 9, 0, 5, 3).union(box(-36, 36, 4, 9, 0, 40))
    b = soft(b, "|X", 1.5)
    cuts = [cyl_z(sx, 0, M3_CLEAR, -1, 6) for sx in SCREW_X]
    for sx in (-22, 22):
        cuts.append(cyl_y(sx, 26, 5.5, 3, 10))
        cuts.append(box(sx - 2.75, sx + 2.75, 3, 10, 20, 26))
        cuts.append(cyl_y(sx, 20, 5.5, 3, 10))
    return b.cut(union(cuts))


# --------------------------------------------------------------------------
# Modules
# --------------------------------------------------------------------------
def dock_cap():
    c = box(-PAD_W / 2, PAD_W / 2, -PAD_HALF_DEPTH, PAD_HALF_DEPTH, 0, 3.0)
    c = c.edges("|Z").fillet(5.0).union(dock_male_pegs())
    return c.cut(dock_male_cut(3.0, plug=False))


def dock_foot():
    """Stand-alone host: a Dock-50 bay you can screw to a wall, ceiling,
    pole clamp or bench. Face on Z = 0, body below."""
    f = rrect(-42, 42, -21, 21, -14, 0, 10)
    cuts = [dock_female_cut(), box(-4, 4, 0, 22, -9.4, -2.0)]
    for sx in (-1, 1):
        for sy in (-1, 1):
            cuts.append(cyl_z(sx * 36, sy * 15, 4.5, -15, 1))
            cuts.append(cyl_z(sx * 36, sy * 15, 8.5, -4, 1))
    return f.cut(union(cuts))


def solar_visor():
    foot_t = 8.0
    foot = box(-PAD_W / 2, PAD_W / 2, -PAD_HALF_DEPTH, PAD_HALF_DEPTH, 0, foot_t).edges("|Z").fillet(5.0)
    tw, td, tt = PANEL_W + 6.0, PANEL_D + 6.0, 5.0
    lift = foot_t + VISOR_NECK

    def place(s):
        return s.rotate((0, 0, 0), (1, 0, 0), VISOR_TILT).translate((0, D / 2, lift))

    tray = box(-tw / 2, tw / 2, -td, 0, 0, tt).edges("|Z").fillet(14.0)
    pocket = box(-PANEL_W / 2 - 0.3, PANEL_W / 2 + 0.3, -td + 2.7, -2.7, tt - PANEL_T - 0.2, tt + 1)
    tray = place(tray.cut(pocket))
    neck = box(-20, 20, -PAD_HALF_DEPTH, PAD_HALF_DEPTH, foot_t - 0.1, lift + 20).edges("|Z").fillet(8.0)
    neck = neck.intersect(place(box(-300, 300, -400, 200, -400, 1.2)))
    v = foot.union(neck).union(tray).union(dock_male_pegs())
    wire_hole = cyl_z(0, 0, 8.0, foot_t - 2, lift + 30).intersect(place(box(-300, 300, -400, 200, -400, tt - PANEL_T)))
    return v.cut(union([dock_male_cut(foot_t), wire_hole]))


def _module_shell(w, h, fillet):
    body = box(-w / 2, w / 2, -D / 2 + LID_T, D / 2, 0, h).edges("|Y").fillet(fillet)
    return body.cut(box(-w / 2 + WALL, w / 2 - WALL, -D / 2, D / 2 - WALL, 3.0, h - WALL))


def _module_lid(w, h, fillet, holes):
    lid = box(-w / 2, w / 2, -D / 2, -D / 2 + LID_T, 0, h).edges("|Y").fillet(fillet)
    i0, i1 = -w / 2 + WALL + CLR, w / 2 - WALL - CLR
    step = box(i0, i1, -D / 2 + LID_T - 0.1, -D / 2 + LID_T + 1.5, 3.0 + CLR, h - WALL - CLR)
    step = step.cut(box(i0 + 1.6, i1 - 1.6, -D / 2, D / 2, 3.0 + CLR + 1.6, h - WALL - CLR - 1.6))
    cuts = [cyl_y(x, z, M3_CLEAR, -D / 2 - 1, -D / 2 + LID_T + 2) for x, z in holes]
    return lid.union(step).cut(union(cuts))


def _posts(points):
    posts = [cyl_y(x, z, 8.0, -D / 2 + LID_T, D / 2 - WALL + 0.1) for x, z in points]
    holes = [cyl_y(x, z, INSERT_D, -D / 2, -D / 2 + LID_T + 7) for x, z in points]
    return union(posts), union(holes)


BM_POSTS = ((-22.0, 40.0), (22.0, 40.0))
DM_POSTS = ((0.0, 30.0),)
OB_POSTS = ((31.0, 26.0), (-36.0, 9.0))


def battery_module():
    """Stacking pack: two upright cells, dock below, dock on top."""
    s = _module_shell(BM_W, BM_H, 8.0)
    posts, post_holes = _posts(BM_POSTS)
    adds = [posts, box(-30, 30, -PAD_HALF_DEPTH, PAD_HALF_DEPTH, 0, 5.0)]
    adds.append(dock_female_pad(back=D / 2 - 0.1).translate((0, 0, BM_H)))
    cx = BM_W / 2 - WALL - CELL_D / 2 - 0.6
    for sx in (-1, 1):
        for z in (20.0, 55.0):
            x0, x1 = sorted((sx * 31.0, sx * (BM_W / 2 - WALL + 0.1)))
            rib = box(x0, x1, -D / 2 + LID_T + 2, D / 2 - WALL + 0.1, z, z + 3)
            rib = rib.cut(cyl_z(sx * cx, 0, CELL_D + 0.8, z - 1, z + 4))
            adds.append(rib.cut(box(sx * cx - CELL_D / 2 - 0.4, sx * cx + CELL_D / 2 + 0.4, -D / 2, 0, z - 1, z + 4)))
    s = s.union(union(adds)).union(dock_male_pegs())
    return s.cut(union([dock_male_cut(5.0), dock_female_cut().translate((0, 0, BM_H)), post_holes]))


def battery_module_lid():
    return _module_lid(BM_W, BM_H, 8.0, BM_POSTS)


def dev_module():
    s = _module_shell(DM_W, DM_H, 6.0)
    posts, post_holes = _posts(DM_POSTS)
    return s.union(posts).union(dock_male_pegs()).cut(union([dock_male_cut(3.0), post_holes]))


def dev_module_lid():
    return _module_lid(DM_W, DM_H, 6.0, DM_POSTS)


# --------------------------------------------------------------------------
# Orbit: two-axis pan-tilt joint. Dock below, dock on the cradle, so it goes
# between any host and any module: under a Barrel camera, or under a solar
# panel so the panel follows the sun on its own.
# --------------------------------------------------------------------------
def orbit_base():
    s = _module_shell(OB_W, OB_H, 8.0)
    posts, post_holes = _posts(OB_POSTS)
    back = D / 2 - WALL + 0.1
    ledge_z0, ledge_z1 = 17.0 + SERVO["tab_z"] - 6.5, 17.0 + SERVO["tab_z"]
    adds = [posts]
    adds.append(box(-OB_W / 2 + WALL - 0.1, -31.0, -10, back, ledge_z0, ledge_z1))
    adds.append(box(10.6, 18.5, -10, back, ledge_z0, ledge_z1))
    s = s.union(union(adds)).union(dock_male_pegs())
    cuts = [dock_male_cut(3.0), post_holes]
    cuts.append(cyl_z(0, 0, 13.0, OB_H - WALL - 1, OB_H + 1))        # pan servo output
    cuts.append(cyl_z(27, 0, 10.0, OB_H - WALL - 1, OB_H + 1))       # cable to the cradle
    for x in (-SERVO["off"] - 24.5, -SERVO["off"] + 24.5):
        for y in (-5.0, 5.0):
            cuts.append(cyl_z(x, y, 2.2, ledge_z0 - 1, ledge_z1 + 1))
    return s.cut(union(cuts))


def orbit_base_lid():
    return _module_lid(OB_W, OB_H, 8.0, OB_POSTS)


def orbit_turret():
    """Rides on the pan servo horn and carries the tilt servo on its side."""
    zt = ORBIT_ZT
    parts = [cyl_z(0, 0, 44.0, OB_H + 1.0, 64.0)]
    parts.append(box(-22.5, 8.5, -31, 11, 64.0, 66.0))
    wall = box(5.5, 8.5, -38.5, 18, 64.0, 88.5).cut(box(4, 10, -30.8, 10.3, 65.8, 86.5))
    parts.append(wall)
    parts.append(box(-22.5, -19.5, -12, 12, 64.0, 88.0))
    parts.append(cyl_x(0, zt, 8.0, -29.5, -19.5))
    t = union(parts)
    cuts = [cyl_z(0, 0, 21.5, OB_H, OB_H + 3.5), cyl_z(0, 0, M3_CLEAR, OB_H, 70)]
    for y in (-SERVO["off"] - 24.5, -SERVO["off"] + 24.5):
        for z in (zt - 5, zt + 5):
            cuts.append(cyl_x(y, z, 2.2, 4, 10))
    return t.cut(union(cuts))


def orbit_cradle():
    """Swings on the tilt servo. Its bar is a Dock-50 bay."""
    zt = ORBIT_ZT
    arms = [box(24.5, 28.5, -10, 10, zt - 10, zt + ORBIT_ARM + 1), box(-33, -29, -10, 10, zt - 10, zt + ORBIT_ARM + 1)]
    bar = box(-PAD_W / 2, PAD_W / 2, -PAD_HALF_DEPTH, PAD_HALF_DEPTH, zt + ORBIT_ARM, ORBIT_TOP)
    c = soft(union(arms + [bar]), "|X", 3.0)
    cuts = [dock_female_cut().translate((0, 0, ORBIT_TOP))]
    cuts.append(cyl_x(0, zt, 8.4, -34, -28))
    cuts.append(cyl_x(0, zt, 9.0, 24, 29))
    cuts.append(cyl_x(0, zt, 21.5, 24.4, 26.5))
    return c.cut(union(cuts))


# --------------------------------------------------------------------------
# Barrel body
# --------------------------------------------------------------------------
B_FACE = dict(lens2=(0.0, -26.0), pir=(0.0, 26.0), ir=((-28.0, 0.0), (28.0, 0.0)),
              flash=((-20.0, -20.0), (20.0, -20.0)), als=(16.0, 21.0), mic=(-16.0, 21.0),
              bosses=((-21.0, 17.0), (21.0, 17.0)), ring_r=19.0)


def barrel_body():
    L = BL - FP_T
    o = cq.Workplane("XY").circle(BR).extrude(L).faces("<Z").edges().fillet(20.0)
    i = cq.Workplane("XY").circle(BR - WALL).extrude(L - WALL).faces("<Z").edges().fillet(20.0 - WALL)
    i = i.translate((0, 0, WALL))
    foot = soft(box(-33, 33, -B_PAD_Y, -17.0, B_DOCK_Z - 12, B_DOCK_Z + 12), "|Y", 5.0)
    top = soft(box(-33, 33, 17.0, B_PAD_Y, B_DOCK_Z - 12, B_DOCK_Z + 12), "|Y", 5.0)
    s = o.union(foot).union(top).cut(i)
    s = s.union(to_barrel(dock_male_pegs(), -B_PAD_Y))
    cuts = [to_barrel(dock_male_cut(24.0), -B_PAD_Y), to_barrel(dock_female_cut(), B_PAD_Y)]
    # Two radial screws hold the front cap
    for a in (-135.0, -45.0):
        c = cyl_x(0, L - 2.2, M3_CLEAR, BR - 6, BR + 1).rotate((0, 0, 0), (0, 0, 1), a)
        cuts.append(c)
    cuts.append(cyl_z(0, 30.0, 6.2, -1, 12))    # battery switch in the rear dome
    cuts.append(box(-USBC_SLOT[0] / 2, USBC_SLOT[0] / 2, -32 - USBC_SLOT[1] / 2, -32 + USBC_SLOT[1] / 2, -1, 14))
    return s.cut(union(cuts))


def barrel_front():
    L = BL - FP_T
    p = cq.Workplane("XY").circle(BR).extrude(FP_T).faces(">Z").chamfer(EDGE).translate((0, 0, L))
    rr = BR - WALL - CLR
    ring = cq.Workplane("XY").circle(rr).circle(rr - 1.8).extrude(5.0).translate((0, 0, L - 5.0))
    adds = [ring] + [cyl_z(x, y, 8.0, L - 7, L + 0.1) for x, y in B_FACE["bosses"]]
    p = p.union(union(adds))
    cuts = [cyl_z(0, 0, 17.0, L - 1, BL + 1), cyl_z(*B_FACE["lens2"], 12.0, L - 1, BL + 1)]
    for k in range(16):
        a = math.radians(k * 22.5 + 11.25)
        cuts.append(cyl_z(B_FACE["ring_r"] * math.cos(a), B_FACE["ring_r"] * math.sin(a), 3.6, L - 1, BL + 1))
    cuts.append(cyl_z(*B_FACE["pir"], 10.3, L - 1, BL + 1))
    cuts += [cyl_z(x, y, 5.2, L - 1, BL + 1) for x, y in B_FACE["ir"]]
    cuts += [cyl_z(x, y, 8.0, L - 1, BL + 1) for x, y in B_FACE["flash"]]
    cuts.append(cyl_z(*B_FACE["als"], 3.0, L - 1, BL + 1))
    cuts.append(cyl_z(*B_FACE["mic"], 1.5, L - 1, BL + 1))
    cuts += [cyl_z(x, y, INSERT_D, L - 8, L - 1.0) for x, y in B_FACE["bosses"]]
    for a in (-135.0, -45.0):
        cuts.append(cyl_x(0, L - 2.2, 2.6, rr - 3, rr + 1).rotate((0, 0, 0), (0, 0, 1), a))
    return p.cut(union(cuts))


def barrel_visor():
    v = cq.Workplane("XY").circle(BR - 3.0).extrude(VIS["t"]).faces(">Z").chamfer(0.6).translate((0, 0, BL))
    t = VIS["t"]
    cuts = [cyl_z(0, 0, 15.0, BL - 1, BL + t + 1), cyl_z(*B_FACE["lens2"], 12.0, BL - 1, BL + t + 1)]
    cuts.append(cyl_z(*B_FACE["pir"], 10.3, BL - 1, BL + t + 1))
    cuts += [cyl_z(x, y, 8.0, BL - 1, BL + t + 1) for x, y in B_FACE["flash"]]
    cuts.append(cyl_z(*B_FACE["als"], 3.0, BL - 1, BL + t + 1))
    cuts.append(cyl_z(*B_FACE["mic"], 1.5, BL - 1, BL + t + 1))
    return v.cut(union(cuts))


def barrel_carrier():
    L = BL - FP_T
    zf = L - 7.0
    c = rrect(-26, 26, -12, 22, zf - 2, zf, 4)
    posts = [(px, py) for px in (-10.5, 10.5) for py in (0.0, 12.5)]
    c = c.union(union([cyl_z(x, y, 4.5, zf - 3.5, zf - 1.9) for x, y in posts]))
    cuts = [cyl_z(0, 0, 17.0, zf - 3, zf + 1)]
    cuts += [cyl_z(x, y, M3_CLEAR, zf - 3, zf + 1) for x, y in B_FACE["bosses"]]
    cuts += [cyl_z(x, y, 1.8, zf - 4, zf + 1) for x, y in posts]
    return c.cut(union(cuts))


def barrel_sled():
    """Slides in from the front with cells and boards already wired."""
    z1 = BL - 12.0
    s = box(-30, 30, B_SLED_Y - 2.0, B_SLED_Y, 6, z1)
    walls = []
    for k in range(B_PAIRS + 1):
        z = 6.0 + k * 72.0
        walls.append(box(-30, 30, B_SLED_Y - 2.0, 9.0, z, z + 1.6))
    s = s.union(union(walls))
    bz0 = 6.0 + B_PAIRS * 72.0 + 4.0
    pts = [(x, bz0 + z) for x in (-17.5, 17.5) for z in (3.5, MB["w"] - 3.5)]
    s = s.union(union([cyl_y(x, z, 5.0, B_SLED_Y - 0.1, B_SLED_Y + 4.0) for x, z in pts]))
    cuts = [cyl_z(sx * 16.4, 0, 11.0, 0, 6.0 + B_PAIRS * 72.0 + 3) for sx in (-1, 1)]
    cuts += [cyl_y(x, z, 2.2, B_SLED_Y, B_SLED_Y + 5.0) for x, z in pts]
    return s.cut(union(cuts))


def barrel_hood():
    """Sun and rain hood. Clamped under whatever sits on the top dock."""
    z0, z1 = B_DOCK_Z - 44.0, BL + 24.0
    h = cq.Workplane("XY").circle(BR + 2.3).circle(BR + 0.3).extrude(z1 - z0).translate((0, 0, z0))
    h = h.cut(box(-80, 80, -80, -8.0, z0 - 1, z1 + 1))
    shim = box(-33, 33, B_PAD_Y, B_PAD_Y + 1.6, B_DOCK_Z - 12, B_DOCK_Z + 12)
    h = h.cut(box(-33.3, 33.3, 17.0, B_PAD_Y, B_DOCK_Z - 12.3, B_DOCK_Z + 12.3)).union(shim)
    cuts = [to_barrel(cyl_z(px, 0, PEG_D + 0.5, -1, 3), B_PAD_Y) for px in PEG_X]
    cuts += [to_barrel(cyl_z(sx, 0, M3_CLEAR, -1, 3), B_PAD_Y) for sx in SCREW_X]
    cuts.append(to_barrel(box(-7, 7, -4, 4, -1, 3), B_PAD_Y))
    return h.cut(union(cuts))


# --------------------------------------------------------------------------
# Pod. A flat solar deck over a deep round belly, a brow over a glass face
# set back inside a thin rim, and a slim neck mount.
# Frame as the Barrel: Z is the lens axis, Y up, rear at Z = 0.
# --------------------------------------------------------------------------
PW, PH = 86.0, 56.0
P_RT, P_RB = 10.0, 26.0        # tight deck corners, deep belly corners
P_TOP = 4.8                    # deck thickness, seats the panel
PF = 132.0                     # front of the face cap
P_RIM = 2.5                    # the shell runs this far past the face
P_BROW = 7.0                   # and this much further at the top
P_PANEL = (61.0, 107.0, 2.2)   # 6 V 1 W class panel: across, along, depth
P_DOCK_Z = 72.0
P_CELL_Y = -PH / 2 + WALL + 0.4 + CELL_D / 2
P_CELL_Z = 26.0
P_DECK_Y = 9.8
P_BALL = 12.0
P_FACE = dict(lens=(-17.0, -3.0), lens2=(15.0, -3.0), port=24.0, port2=15.0, pir=(31.0, -3.0), bar_y=15.0,
              ir=((31.0, 9.0), (31.0, -15.0)), mic=(10.0, -21.0), als=(30.0, 17.0),
              bosses=((0.5, -3.0), (0.5, -20.0)))


def dsection(w, h, rt, rb, depth):
    """Profile with tight top corners and wide bottom corners, centred."""
    x, y = w / 2, h / 2
    wp = (cq.Workplane("XY").moveTo(-x + rt, y).lineTo(x - rt, y).radiusArc((x, y - rt), rt)
          .lineTo(x, -y + rb).radiusArc((x - rb, -y), rb).lineTo(-x + rb, -y).radiusArc((-x, -y + rb), rb)
          .lineTo(-x, y - rt).radiusArc((-x + rt, y), rt).close())
    return wp.extrude(depth)


def pod_outer(depth):
    return dsection(PW, PH, P_RT, P_RB, depth)


def pod_inner(depth, shrink=0.0):
    """Cavity profile: thin walls, thick deck."""
    s = dsection(PW - 2 * WALL - 2 * shrink, PH - WALL - P_TOP - 2 * shrink, max(P_RT - P_TOP, 3.0) - min(shrink, 2.0),
                 P_RB - WALL - shrink, depth)
    return s.translate((0, (WALL - P_TOP) / 2, 0))


def pod_body():
    z_rim = PF + P_RIM
    o = pod_outer(z_rim + P_BROW + 2)
    try:
        o = o.faces("<Z").edges().fillet(9.0)
    except Exception:
        o = o.faces("<Z").chamfer(4.0)
    i = pod_inner(z_rim + P_BROW + 10)
    try:
        i = i.faces("<Z").edges().fillet(9.0 - WALL)
    except Exception:
        pass
    s = o.cut(i.translate((0, 0, WALL)))
    # Brow: trim the front on a slant, long at the deck and short at the belly
    slant = math.degrees(math.atan(P_BROW / PH))
    s = s.cut(box(-100, 100, -100, 100, 0, 100).rotate((0, 0, 0), (1, 0, 0), slant).translate((0, -PH / 2, z_rim)))
    # Ledge that the face cap seats on
    ledge = pod_inner(1.2).cut(pod_inner(1.2, shrink=1.2)).translate((0, 0, PF - FP_T - 1.2))
    ledge = ledge.cut(box(-17, 17, -PH / 2, -PH / 2 + 12, 0, 200))
    adds = [ledge]
    adds += [cyl_z(sx * 10.0, 0, 8.0, WALL - 0.1, WALL + 6.0) for sx in (-1, 1)]                       # neck mount
    adds += [cyl_y(0, z, 8.0, -PH / 2 + WALL - 0.1, -PH / 2 + WALL + 5.0) for z in (P_DOCK_Z - 8, P_DOCK_Z + 8)]  # saddle
    s = s.union(union(adds))
    pw, pl, pd = P_PANEL
    cuts = [box(-pw / 2 - 0.3, pw / 2 + 0.3, PH / 2 - pd, PH / 2 + 1, 10.0, 10.6 + pl)]
    cuts.append(cyl_y(0, 18.0, 6.0, PH / 2 - P_TOP - 1, PH / 2))                                        # panel leads
    cuts += [cyl_z(sx * 10.0, 0, INSERT_D, -1, 7.0) for sx in (-1, 1)]
    cuts += [cyl_y(0, z, INSERT_D, -PH / 2 - 1, -PH / 2 + 6.5) for z in (P_DOCK_Z - 8, P_DOCK_Z + 8)]
    sw, sh = USBC_SLOT
    cuts.append(box(-sw / 2, sw / 2, -PH / 2 - 1, -PH / 2 + WALL + 1, 15 - sh / 2, 15 + sh / 2))        # charge port, underside
    cuts.append(cyl_z(26.0, -10.0, 6.2, -1, WALL + 1))                                                  # battery switch
    for i_ in range(-2, 3):                                                                             # speaker, underside
        for j in range(-1, 2):
            cuts.append(cyl_y(i_ * 3.4, 113 + j * 3.4, 1.6, -PH / 2 - 1, -PH / 2 + WALL + 1))
    cuts += [cyl_y(sx * 10.0, PF - FP_T - 5.0, M3_CLEAR, -PH / 2 - 1, -PH / 2 + WALL + 1) for sx in (-1, 1)]
    return s.cut(union(cuts))


def pod_front():
    """Face cap. Drops in from the front onto the ledge, two screws from below."""
    z0 = PF - FP_T
    p = pod_inner(FP_T, shrink=0.25).translate((0, 0, z0))
    tabs = [box(sx * 10 - 3.5, sx * 10 + 3.5, -PH / 2 + WALL + 0.3, -PH / 2 + WALL + 7, z0 - 9, z0 + 0.1) for sx in (-1, 1)]
    adds = tabs + [cyl_z(x, y, 7.0, z0 - 7, z0 + 0.1) for x, y in P_FACE["bosses"]]
    p = p.union(union(adds))
    by = P_FACE["bar_y"]
    cuts = [cyl_z(*P_FACE["lens"], P_FACE["port"], z0 - 1, PF + 1), cyl_z(*P_FACE["lens2"], P_FACE["port2"], z0 - 1, PF + 1)]
    cuts.append(rrect(-24, 24, by - 1.6, by + 1.6, z0 - 1, PF + 1, 1.5))
    cuts.append(cyl_z(*P_FACE["pir"], 10.3, z0 - 1, PF + 1))
    cuts += [cyl_z(x, y, 5.2, z0 - 1, PF + 1) for x, y in P_FACE["ir"]]
    cuts.append(cyl_z(*P_FACE["mic"], 1.5, z0 - 1, PF + 1))
    cuts.append(cyl_z(*P_FACE["als"], 3.0, z0 - 1, PF + 1))
    cuts += [cyl_z(x, y, INSERT_D - 0.8, z0 - 8, z0 - 1.0) for x, y in P_FACE["bosses"]]
    cuts += [cyl_y(sx * 10.0, z0 - 5.0, 2.6, -PH / 2, -PH / 2 + WALL + 8) for sx in (-1, 1)]
    return p.cut(union(cuts))


def pod_visor():
    """One sheet of smoke glass over the whole face."""
    t = VIS["t"]
    v = pod_inner(t, shrink=0.6).faces(">Z").chamfer(0.5).translate((0, 0, PF))
    cuts = [cyl_z(*P_FACE["lens"], P_FACE["port"], PF - 1, PF + t + 1), cyl_z(*P_FACE["lens2"], P_FACE["port2"], PF - 1, PF + t + 1)]
    cuts.append(cyl_z(*P_FACE["pir"], 10.3, PF - 1, PF + t + 1))
    cuts.append(cyl_z(*P_FACE["mic"], 1.5, PF - 1, PF + t + 1))
    cuts.append(cyl_z(*P_FACE["als"], 3.0, PF - 1, PF + t + 1))
    return v.cut(union(cuts))


def pod_bezel(kind="m12"):
    """Lens ring for the main port. Sits flush with the glass. Swap for CS."""
    x, y = P_FACE["lens"]
    d = P_FACE["port"]
    z0, z1 = PF - FP_T, PF + VIS["t"]
    b = cyl_z(x, y, d - 0.3, z0, z1 + 0.4)
    if kind == "cs":
        b = b.union(cyl_z(x, y, d + 2.0, z1, z1 + 12.0))
        return b.cut(cyl_z(x, y, d - 3.0, z0 - 1, z1 + 13))
    cone = cq.Workplane("XY").circle(d / 2 - 1.4).workplane(offset=z1 + 0.4 - z0).circle(d / 2 - 1.4).loft()
    inner = cq.Workplane("XY").circle(7.6).workplane(offset=z1 + 1.4 - z0).circle(d / 2 - 1.6).loft().translate((x, y, z0 - 0.5))
    return b.cut(inner)


def pod_carrier():
    zf = PF - FP_T - 7.0
    c = box(-31, 28, -25, 10, zf - 2, zf).intersect(pod_inner(300, shrink=1.0))
    posts = [(P_FACE[k][0] + px, P_FACE[k][1] + py) for k in ("lens", "lens2") for px in (-10.5, 10.5) for py in (0.0, 12.5)]
    posts = [(x, y) for x, y in posts if abs(x - 0.5) > 5]
    c = c.union(union([cyl_z(x, y, 4.5, zf - 3.5, zf - 1.9) for x, y in posts]))
    cuts = [cyl_z(*P_FACE["lens"], 17.0, zf - 3, zf + 1), cyl_z(*P_FACE["lens2"], 15.0, zf - 3, zf + 1)]
    cuts += [cyl_z(x, y, M3_CLEAR, zf - 3, zf + 1) for x, y in P_FACE["bosses"]]
    cuts += [cyl_z(x, y, 1.8, zf - 4, zf + 1) for x, y in posts]
    return c.cut(union(cuts))


def pod_sled():
    """Deck for the boards with the two cells slung underneath, cradled by
    the belly. Slides in from the front."""
    z0, z1 = P_CELL_Z - 2.0, P_CELL_Z + CELL_L + 1.5
    deck = box(-36, 36, P_DECK_Y - 1.6, P_DECK_Y, z0, z1)
    ends = [pod_inner(1.6, shrink=0.5).translate((0, 0, z)).intersect(box(-60, 60, -60, P_DECK_Y, 0, 300)) for z in (z0, z1 - 1.6)]
    rails = [box(sx * 37.5 - 1, sx * 37.5 + 1, -2.0, P_DECK_Y, z0, z1) for sx in (-1, 1)]
    s = deck.union(union(ends + rails)).intersect(pod_inner(300, shrink=0.5))
    pts = [(-33.5 + x, z0 + 5.5 + z) for x in (0.0, 35.0) for z in (0.0, 61.0)] + [(9.0 + x, z0 + 8.5 + z) for x in (0.0, 23.0) for z in (0.0, 58.0)]
    s = s.union(union([cyl_y(x, z, 5.0, P_DECK_Y - 0.1, P_DECK_Y + 3.0) for x, z in pts]))
    cuts = [cyl_z(sx * 16.4, P_CELL_Y, 11.0, 0, 300) for sx in (-1, 1)]
    cuts += [cyl_y(x, z, 2.2, P_DECK_Y - 1, P_DECK_Y + 4.0) for x, z in pts]
    cuts.append(box(-9, 9, P_DECK_Y - 3, P_DECK_Y + 1, z0 + 28, z0 + 48))
    return s.cut(union(cuts))


def pod_saddle():
    """Optional. Bolts under the Pod and gives it a Dock-50 plug, so it can
    ride on the pan-tilt joint or a dock foot. The Pod itself stays clean."""
    y_face = -PH / 2 - 9.0
    blk = soft(box(-33, 33, y_face, -PH / 2 + 14, P_DOCK_Z - 12, P_DOCK_Z + 12), "|Y", 5.0)
    blk = blk.cut(pod_outer(300).translate((0, 0, -10)))
    pegs = rx(dock_male_pegs(), -90).translate((0, y_face, P_DOCK_Z))
    cuts = [rx(dock_male_cut(40.0, plug=False), -90).translate((0, y_face, P_DOCK_Z))]
    cuts += [cyl_y(0, z, M3_CLEAR, y_face - 1, -PH / 2 + 1) for z in (P_DOCK_Z - 8, P_DOCK_Z + 8)]
    cuts += [cyl_y(0, z, 6.5, y_face - 1, y_face + 3.5) for z in (P_DOCK_Z - 8, P_DOCK_Z + 8)]
    cuts += [cyl_y(sx, P_DOCK_Z, 6.5, y_face + 4, 0) for sx in SCREW_X]
    return blk.union(pegs).cut(union(cuts))


def mount_base():
    """Wall base, slim neck and ball."""
    b = cq.Workplane("XY").circle(27.0).extrude(2.5)
    b = b.union(cq.Workplane("XY").workplane(offset=2.4).circle(27.0).workplane(offset=8.0).circle(9.5).loft())
    b = b.union(cyl_z(0, 0, 14.0, 10.0, 30.0)).union(cq.Workplane("XY").sphere(P_BALL).translate((0, 0, 36.0)))
    cuts = []
    for k in range(3):
        a = math.radians(90 + 120 * k)
        cuts.append(cyl_z(19 * math.cos(a), 19 * math.sin(a), 4.2, -1, 12))
        cuts.append(cyl_z(19 * math.cos(a), 19 * math.sin(a), 8.0, 3.2, 12))
    return b.cut(union(cuts))


def mount_cup():
    """Screws to the back of the Pod. Four fingers grip the ball."""
    c = cq.Workplane("XY").circle(17.0).workplane(offset=22.0).circle(16.2).loft()
    cuts = [cq.Workplane("XY").sphere(P_BALL + 0.2).translate((0, 0, 4.0 + P_BALL + 0.6)), cyl_z(0, 0, 17.0, 4.0 + P_BALL, 23)]
    for a in (0, 90):
        cuts.append(box(-0.8, 0.8, -20, 20, 9.0, 23).rotate((0, 0, 0), (0, 0, 1), a + 45))
    cuts += [cyl_z(sx * 10.0, 0, M3_CLEAR, -1, 5) for sx in (-1, 1)]
    cuts += [cyl_z(sx * 10.0, 0, 6.2, 2.4, 12) for sx in (-1, 1)]
    return c.cut(union(cuts))


def mount_collar():
    """Knurled ring. Pushed down the tapered cup, it closes the fingers."""
    ring = cq.Workplane("XY").circle(21.0).extrude(11.0).faces(">Z or <Z").chamfer(1.0)
    ribs = []
    for k in range(30):
        ribs.append(cyl_z(21.6, 0, 2.6, -1, 12).rotate((0, 0, 0), (0, 0, 1), k * 12))
    ring = ring.cut(union(ribs))
    bore = cq.Workplane("XY").circle(16.9).workplane(offset=11.0).circle(16.45).loft()
    return ring.cut(bore)


# --------------------------------------------------------------------------
# Hub: desk enclosure for the processing unit. Sized by HUB for a small
# square desktop computer (127 x 127 x 50 by default), with a touchscreen
# on a sloped top. Change the numbers for another machine or panel.
# --------------------------------------------------------------------------
HUB = dict(dev_w=127.0, dev_d=127.0, dev_h=50.0, clr=1.5, wall=3.0, r=26.0, lift=7.0)
SCREEN = dict(w=121.0, h=76.0, view_w=110.0, view_h=66.0, tilt=32.0)   # 5 inch HDMI touch panel
HUB_W = HUB["dev_w"] + 2 * (HUB["clr"] + HUB["wall"])
HUB_D = HUB["dev_d"] + 2 * (HUB["clr"] + HUB["wall"])
HUB_H = HUB["wall"] + HUB["lift"] + HUB["dev_h"] + 2.0


def hub_body():
    w, lift = HUB["wall"], HUB["lift"]
    o = rbox(HUB_W, HUB_D, HUB_H, HUB["r"]).faces("<Z").chamfer(1.5)
    s = o.cut(rbox(HUB_W - 2 * w, HUB_D - 2 * w, HUB_H, HUB["r"] - w).translate((0, 0, w)))
    pads = [(-45, -45), (45, -45), (45, 45), (-45, 8)]
    s = s.union(union([cyl_z(x, y, 16.0, w - 0.1, w + lift) for x, y in pads]))
    z_dev = w + lift
    cuts = [box(-54, 54, HUB_D / 2 - w - 1, HUB_D / 2 + 1, z_dev + 5, HUB_H + 1)]          # rear ports
    cuts.append(rrect(-36, 36, -HUB_D / 2 - 1, -HUB_D / 2 + w + 1, z_dev + 6, z_dev + 24, 0))  # front ports
    cuts.append(box(-HUB_W / 2 - 1, -HUB_W / 2 + 36, HUB_D / 2 - 36, HUB_D / 2 + 1, -1, z_dev))  # power button reach
    for sx in (-1, 1):
        for i in range(-3, 4):
            x0, x1 = sorted((sx * (HUB_W / 2 - w - 1), sx * (HUB_W / 2 + 1)))
            cuts.append(box(x0, x1, i * 12 - 2.5, i * 12 + 2.5, w + 1.5, z_dev + 12))
    for i in range(-3, 4):
        cuts.append(rrect(i * 13 - 3, i * 13 + 3, -30, 30, -1, w + 1, 2.9))
    return s.cut(union(cuts))


def hub_top():
    """Lid with a sloped console for the touchscreen. The panel glass sits in
    a rebate, its cable drops through to the computer below."""
    w, th = HUB["wall"], math.radians(SCREEN["tilt"])
    outline = rbox(HUB_W, HUB_D, 200, HUB["r"])
    plate = rbox(HUB_W, HUB_D, 3.0, HUB["r"])
    lip = rbox(HUB_W - 2 * w - 0.4, HUB_D - 2 * w - 0.4, 3.0, HUB["r"] - w).cut(
        rbox(HUB_W - 2 * w - 4, HUB_D - 2 * w - 4, 3.0, HUB["r"] - w - 1.8)).translate((0, 0, -3.0))
    slope = SCREEN["h"] + 16.0
    y0 = -HUB_D / 2 + 4.0
    y1, zt = y0 + slope * math.cos(th), 3.0 + slope * math.sin(th)
    wedge = cq.Workplane("YZ").polyline([(y0, 2.9), (y1, 2.9), (y1, zt)]).close().extrude(HUB_W / 2 - 1.5, both=True)
    wedge = wedge.intersect(outline)
    inner = cq.Workplane("YZ").polyline([(y0 + 7, 2.0), (y1 - 3, 2.0), (y1 - 3, zt - 6.5)]).close().extrude(HUB_W / 2 - 4.5, both=True)
    t = plate.union(lip).union(wedge)

    def on_slope(s):
        return s.rotate((0, 0, 0), (1, 0, 0), SCREEN["tilt"]).translate((0, y0, 3.0))

    cuts = [inner, box(-HUB_W / 2 + 8, HUB_W / 2 - 8, y0 + 9, y1 - 5, -4, 3.5)]
    cuts.append(on_slope(box(-SCREEN["w"] / 2 - 0.3, SCREEN["w"] / 2 + 0.3, 8.0, 8.6 + SCREEN["h"], -1.6, 2)))
    cuts.append(on_slope(box(-SCREEN["view_w"] / 2, SCREEN["view_w"] / 2, 13.0, 13.0 + SCREEN["view_h"], -8, 2)))
    for i in range(-3, 4):
        cuts.append(rrect(i * 14 - 3, i * 14 + 3, y1 + 6, HUB_D / 2 - 12, -1, 4, 2.9))
    return t.cut(union(cuts))


# --------------------------------------------------------------------------
# Mainboard rev A. One board for both bodies. Placement in board
# coordinates, origin bottom left, mm. The website draws this list.
# --------------------------------------------------------------------------
MAINBOARD = [
    # ref, label, x, y, w, h, kind, height
    ("U1", "ESP32-C6 controller", 2.0, 23.0, 13.2, 16.6, "module", 2.4),
    ("U2", "LiFePO4 charger, MPPT", 19.0, 28.0, 5.0, 5.0, "ic", 1.0),
    ("L1", "Charger inductor", 25.0, 28.0, 6.0, 6.0, "inductor", 3.0),
    ("U3", "5 V boost", 33.0, 28.0, 5.0, 5.0, "ic", 1.0),
    ("L2", "Boost inductor", 39.0, 28.0, 6.0, 6.0, "inductor", 3.0),
    ("U4", "Fuel gauge", 47.5, 33.0, 3.0, 3.0, "ic", 0.9),
    ("U5", "USB 2.0 hub", 47.0, 25.0, 4.0, 4.0, "ic", 0.9),
    ("U6", "Class D audio amp", 54.0, 33.0, 3.0, 3.0, "ic", 0.9),
    ("Q1", "Compute rail switch", 20.0, 20.0, 3.0, 3.0, "ic", 0.9),
    ("Q2", "Top dock switch", 26.0, 20.0, 3.0, 3.0, "ic", 0.9),
    ("Q3", "Bottom dock switch", 32.0, 20.0, 3.0, 3.0, "ic", 0.9),
    ("Q4", "Light driver", 38.0, 20.0, 3.0, 3.0, "ic", 0.9),
    ("J1", "Top dock", 19.0, 36.5, 8.0, 4.0, "conn", 4.0),
    ("J2", "Bottom dock", 29.0, 36.5, 8.0, 4.0, "conn", 4.0),
    ("J3", "USB-C charge in", 39.0, 36.5, 8.0, 4.0, "conn", 4.0),
    ("J4", "Battery", 57.0, 1.5, 9.0, 6.0, "power", 6.0),
    ("J5", "Compute, 40 pin", 3.0, 1.5, 50.8, 5.1, "header", 8.5),
    ("J6", "Face board flex", 2.0, 12.0, 11.0, 3.5, "conn", 2.0),
    ("J7", "Speaker", 60.0, 26.0, 6.0, 4.5, "conn", 5.0),
    ("J8", "mmWave radar", 46.0, 12.0, 8.0, 3.5, "conn", 4.0),
    ("J9", "Light bars", 36.0, 12.0, 6.0, 3.5, "conn", 4.0),
    ("J10", "Flash LEDs", 27.0, 12.0, 6.0, 3.5, "conn", 4.0),
    ("J11", "IR LEDs", 18.0, 12.0, 6.0, 3.5, "conn", 4.0),
    ("F1", "Fuse", 58.0, 10.0, 7.0, 3.0, "passive", 2.5),
    ("J12", "Battery switch", 60.0, 16.0, 6.0, 4.5, "conn", 5.0),
    ("J13", "Pan-tilt", 57.0, 36.5, 8.0, 4.0, "conn", 4.0),
]
KIND_COLOR = {"module": "metal", "ic": "chips", "inductor": "chips", "conn": "conn", "power": "conn",
              "header": "chips", "passive": "chips"}


# --------------------------------------------------------------------------
# Stand-ins for bought parts, for the viewer. Built as loose solids and
# exported as compounds, grouped by material.
# --------------------------------------------------------------------------
def B(x0, x1, y0, y1, z0, z1):
    return cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


def C(p, direction, dia, length):
    return cq.Solid.makeCylinder(dia / 2, length, V(*p), V(*direction))


def wire(points, dia=1.5):
    out = []
    for a, b in zip(points, points[1:]):
        v = V(*b) - V(*a)
        if v.Length > 0.01:
            out.append(cq.Solid.makeCylinder(dia / 2, v.Length, V(*a), v))
    return out


class Bag(dict):
    def put(self, key, shapes):
        self.setdefault(key, []).extend(shapes if isinstance(shapes, list) else [shapes])

    def merge(self, other, fn=lambda s: s, prefix=""):
        for k, shapes in other.items():
            self.put(prefix + k, [fn(s) for s in shapes])


def board_mainboard():
    """Board frame: X along the 68 mm edge, Y along the 42 mm edge, Z up."""
    g = Bag()
    g.put("pcb", B(0, MB["w"], 0, MB["h"], 0, 1.6))
    for _ref, _label, x, y, w, h, kind, height in MAINBOARD:
        g.put(KIND_COLOR[kind], B(x, x + w, y, y + h, 1.6, 1.6 + height))
    for x in (3.5, MB["w"] - 3.5):
        for y in (3.5, MB["h"] - 3.5):
            g.put("metal", C((x, y, 1.6), (0, 0, 1), 4.5, 1.2))
    # Decoupling caps and resistors, so it reads as a populated board
    k = 0
    for x in range(18, 56, 3):
        for y in (16.3, 24.6, 34.6):
            k += 1
            if k % 3:
                g.put("chips", B(x, x + 1.6, y, y + 0.8, 1.6, 2.2))
    return g


def board_pi():
    """Raspberry Pi Zero 2 W. 65 x 30."""
    g = Bag()
    g.put("pcb", B(0, 65, 0, 30, 0, 1.4))
    g.put("metal", [B(22, 37, 9, 24, 1.4, 2.6), B(48, 60, 10, 22, 1.4, 2.4)])        # SoC can, radio can
    g.put("metal", [B(6.4, 17.6, -0.5, 7, 1.4, 4.7), B(37.4, 45.4, -0.5, 5, 1.4, 4.2),
                    B(50, 58, -0.5, 5, 1.4, 4.2), B(-1, 11, 10.5, 22.5, 1.4, 2.9)])  # HDMI, USB, power, SD
    g.put("chips", B(7.1, 57.9, 24, 29, 1.4, 4.0))                                   # header
    g.put("conn", B(62, 66, 6.5, 23.5, 1.4, 2.6))                                    # camera connector
    return g


def board_camera(cx, cy, z_back):
    g = Bag()
    g.put("pcb", B(cx - 12.5, cx + 12.5, cy - 9.5, cy + 14.5, z_back, z_back + 1.4))
    g.put("chips", B(cx - 7, cx + 7, cy - 7, cy + 7, z_back + 1.4, z_back + 6.0))
    g.put("lens", C((cx, cy, z_back + 6.0), (0, 0, 1), 14.0, 8.5))
    g.put("glass", C((cx, cy, z_back + 14.5), (0, 0, 1), 9.0, 0.4))
    g.put("conn", B(cx - 9, cx + 9, cy - 9.5, cy - 5.5, z_back - 2.2, z_back))
    return g


def cell(p, direction):
    """32700 cell with wrap, positive cap and end rings."""
    d = V(*direction).normalized()
    p0 = V(*p)
    return {
        "cells": [cq.Solid.makeCylinder(CELL_D / 2, CELL_L - 1.6, p0 + d * 0.8, d)],
        "metal": [cq.Solid.makeCylinder(CELL_D / 2 - 1.2, 0.8, p0, d),
                  cq.Solid.makeCylinder(CELL_D / 2 - 1.2, 0.8, p0 + d * (CELL_L - 0.8), d),
                  cq.Solid.makeCylinder(5.0, 1.4, p0 + d * (CELL_L - 0.2), d)],
    }


def viz_slate():
    back, front = Bag(), Bag()
    # Cells, nickel strip and pack leads
    for y in ROW_Y:
        for x0 in (-71.2, 0.7):
            for k, v in cell((x0, y, CELL_Z), (1, 0, 0)).items():
                back.put(k, v)
    y_a, y_b = ROW_Y[0], ROW_Y[-1]
    for x in (-72.6, 72.0):
        back.put("metal", B(x, x + 0.3, y_a - 4, y_b + 4, CELL_Z - 4, CELL_Z + 4))
    back.put("metal", B(-0.15, 0.15, y_a - 4, y_b + 4, CELL_Z - 4, CELL_Z + 4))
    # Protection board on the pack
    back.put("pcb", B(40, 66, y_b + 14.6, y_b + 16.2, WALL + 9, WALL + 19))
    # Mainboard and compute
    mbz = WALL + MB["lift"]
    back.merge(board_mainboard(), lambda s: s.translate(V(MB["x0"], MB["y0"], mbz)))
    piz = WALL + PI_STANDOFF
    back.merge(board_pi(), lambda s: s.translate(V(PI_C[0] - 32.5, PI_C[1] - 15, piz)))
    back.put("flex", B(PI_C[0] + 28, MB["x0"] + 4, MB["y0"] + 1.5, MB["y0"] + 6.6, piz + 4.0, piz + 4.3))
    # Tracker tag, magnets
    back.put("tag", C((PI_C[0], PI_C[1], WALL + 0.1), (0, 0, 1), 31.9, 8.0))
    back.put("metal", [C((x, y, 1.0), (0, 0, 1), MAG_D, MAG_T) for x, y in MAG_PTS])
    # Speaker on the right wall
    sx = W / 2 - WALL
    back.put("speaker", [C((sx - 0.2, SPK_Y, SPK_Z), (-1, 0, 0), SPK_D, 1.2), C((sx - 1.4, SPK_Y, SPK_Z), (-1, 0, 0), 22, 2.0)])
    back.put("metal", C((sx - 3.4, SPK_Y, SPK_Z), (-1, 0, 0), 13.0, 2.4))
    # USB-C receptacles: top dock, bottom dock, charge port
    for y, s in ((H / 2 - 1.0, -1), (Y0 + 1.0, 1)):
        back.put("metal", B(-4.5, 4.5, min(y, y + s * 7.4), max(y, y + s * 7.4), D / 2 - 1.6, D / 2 + 1.6))
        back.put("pcb", B(-11, 11, min(y + s * 4, y + s * 18), max(y + s * 4, y + s * 18), D / 2 - 2.4, D / 2 - 1.6))
    back.put("metal", B(45.5, 54.5, Y0 + 0.6, Y0 + 8.0, D / 2 - 1.6, D / 2 + 1.6))
    back.put("pcb", B(41, 59, Y0 + 4.6, Y0 + 15, D / 2 - 2.4, D / 2 - 1.6))
    back.put("metal", C((-50, Y0 + 1.0, D / 2), (0, 1, 0), 6.0, 12.0))                 # battery switch
    # Wiring. Red and black from the pack, then to docks, speaker and switch.
    j4 = (MB["x0"] + 61.5, MB["y0"] + 4.5, mbz + 7.6)
    pack = (60.0, y_b + 16.2, WALL + 14)
    back.put("wire_red", wire([pack, (60, y_b + 20, WALL + 16), (j4[0] - 1.5, j4[1] - 4, j4[2] + 2), (j4[0] - 1.5, j4[1], j4[2])], 1.8))
    back.put("wire_black", wire([(64, pack[1], pack[2]), (64, y_b + 20, WALL + 16), (j4[0] + 1.5, j4[1] - 4, j4[2] + 2), (j4[0] + 1.5, j4[1], j4[2])], 1.8))
    back.put("wire_red", wire([(72.2, y_a, CELL_Z), (76.5, y_a, CELL_Z), (76.5, y_b + 15.4, WALL + 12), (66, y_b + 15.4, WALL + 12)], 1.8))
    back.put("wire_black", wire([(-72.6, y_a, CELL_Z), (-76.5, y_a, CELL_Z), (-76.5, y_b + 18.4, WALL + 4), (40, y_b + 18.4, WALL + 4), (40, y_b + 15.4, WALL + 12)], 1.8))
    top_j = (MB["x0"] + 23, MB["y0"] + 38.5, mbz + 5.6)
    back.put("wire_white", wire([top_j, (top_j[0], top_j[1] + 3, top_j[2] + 4), (6, H / 2 - 20, D / 2 - 3)], 2.4))
    bot_j = (MB["x0"] + 33, MB["y0"] + 38.5, mbz + 5.6)
    back.put("wire_white", wire([bot_j, (bot_j[0], bot_j[1] + 4, 30), (77, bot_j[1] + 4, 30), (77, Y0 + 20, 30), (8, Y0 + 20, D / 2 - 3)], 2.4))
    chg_j = (MB["x0"] + 43, MB["y0"] + 38.5, mbz + 5.6)
    back.put("wire_white", wire([chg_j, (chg_j[0], chg_j[1] + 6, 33), (75, chg_j[1] + 6, 33), (75, Y0 + 17, 33), (56, Y0 + 15, D / 2 - 3)], 2.4))
    spk_j = (MB["x0"] + 63, MB["y0"] + 28, mbz + 6.6)
    back.put("wire_red", wire([spk_j, (spk_j[0] + 3, spk_j[1] + 2, 20), (sx - 6, SPK_Y - 2, SPK_Z)], 1.2))
    back.put("wire_black", wire([(spk_j[0], spk_j[1] + 1.5, spk_j[2]), (spk_j[0] + 3, spk_j[1] + 4, 21), (sx - 6, SPK_Y + 2, SPK_Z)], 1.2))

    # Front plate side: cameras, light bars, radar, flashes, sensors
    zb = SHELL_D - 9.0 - 3.2
    for sgn in (-1, 1):
        front.merge(board_camera(sgn * LENS_X, LENS_Y, zb))
        cx = sgn * LED_X
        front.put("pcb_white", B(cx - 25.5, cx + 25.5, LED_Y - 5.1, LED_Y + 5.1, SHELL_D - 2.8, SHELL_D - 1.6))
        front.put("leds", [B(cx - 24.9 + i * 6.4, cx - 19.9 + i * 6.4, LED_Y - 2.5, LED_Y + 2.5, SHELL_D - 1.6, SHELL_D) for i in range(8)])
    front.put("pcb", B(RADAR[0] - 11, RADAR[0] + 11, RADAR[1] - 8, RADAR[1] + 8, SHELL_D - 2.6, SHELL_D - 1.4))
    front.put("metal", B(RADAR[0] - 4, RADAR[0] + 4, RADAR[1] - 3, RADAR[1] + 3, SHELL_D - 3.8, SHELL_D - 2.6))
    for x, y in FLASH_PTS:
        front.put("metal", C((x, y, SHELL_D - 2.4), (0, 0, 1), 16.0, 1.4))
        front.put("leds", C((x, y, SHELL_D - 1.0), (0, 0, 1), 5.0, 2.6))
    front.put("leds", [C((x, y, SHELL_D - 6), (0, 0, 1), 5.0, 9.0) for x, y in IR_PTS])
    front.put("pcb", B(PIR[0] - 6, PIR[0] + 6, PIR[1] - 6, PIR[1] + 6, SHELL_D - 9, SHELL_D - 7.8))
    front.put("dome", [C((PIR[0], PIR[1], SHELL_D - 7.8), (0, 0, 1), 10.0, 10.2)])
    front.put("pcb", B(ALS[0] - 6, ALS[0] + 6, ALS[1] - 5, ALS[1] + 5, SHELL_D - 2.4, SHELL_D - 1.2))
    front.put("flex", B(-4, 4, LENS_Y - 14, LENS_Y - 9.5, zb - 2.6, zb - 2.3))
    return back, front


def viz_barrel():
    inner, face = Bag(), Bag()
    for k in range(B_PAIRS):
        for sx in (-1, 1):
            for key, v in cell((sx * 16.4, 0, 8.0 + k * 72.0), (0, 0, 1)).items():
                inner.put(key, v)
    bz0 = 6.0 + B_PAIRS * 72.0 + 4.0

    def lay(dx, dy, dz):
        # Board frame onto the sled: board X along the barrel, board Z up.
        def fn(s):
            s = s.rotate(V(0, 0, 0), V(1, 0, 0), -90).rotate(V(0, 0, 0), V(0, 1, 0), -90)
            return s.translate(V(dx, dy, dz))
        return fn

    inner.merge(board_mainboard(), lay(-21, B_SLED_Y + 4.0, bz0))
    inner.merge(board_pi(), lay(-15, B_SLED_Y + 15.0, bz0 + 1.5))
    inner.put("wire_red", wire([(-10, 14, 76), (-10, 16, bz0 + 4), (-14, B_SLED_Y + 12, bz0 + 60)], 1.8))
    inner.put("wire_black", wire([(10, 14, 76), (10, 16, bz0 + 4), (-17, B_SLED_Y + 12, bz0 + 60)], 1.8))
    inner.put("metal", B(-4.5, 4.5, B_PAD_Y - 8.4, B_PAD_Y - 1.0, B_DOCK_Z - 1.6, B_DOCK_Z + 1.6))
    inner.put("pcb", B(-11, 11, B_PAD_Y - 22, B_PAD_Y - 5, B_DOCK_Z - 2.4, B_DOCK_Z - 1.6))
    L = BL - FP_T
    face.merge(board_camera(0, 0, L - 9.0 - 3.2))
    face.put("pcb", cq.Workplane("XY").circle(22.3).circle(15.8).extrude(1.2).translate((0, 0, L - 2.8)).val())
    for k in range(16):
        a = math.radians(k * 22.5 + 11.25)
        x, y = B_FACE["ring_r"] * math.cos(a), B_FACE["ring_r"] * math.sin(a)
        face.put("leds", B(x - 2.5, x + 2.5, y - 2.5, y + 2.5, L - 1.6, L))
    face.put("lens", C((B_FACE["lens2"][0], B_FACE["lens2"][1], L - 8), (0, 0, 1), 10.0, 12.0))
    face.put("dome", C((B_FACE["pir"][0], B_FACE["pir"][1], L - 6), (0, 0, 1), 10.0, 11.0))
    return inner, face


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------
def build():
    """name -> (solid, print rotation about X, extra print rotation about Y)"""
    return {
        "slate_back_shell": (slate_back_shell(), 0, 0),
        "slate_front_plate": (slate_front_plate(), 180, 0),
        "slate_visor": (slate_visor(), 0, 0),
        "slate_camera_carrier": (slate_camera_carrier(), 180, 0),
        "slate_battery_sled": (slate_battery_sled(), 0, 0),
        "slate_gasket": (slate_gasket(), 0, 0),
        "lens_bezel_m12": (lens_bezel("m12"), 180, 0),
        "lens_bezel_cs": (lens_bezel("cs"), 180, 0),
        "mag_plate": (mag_plate(), 180, 0),
        "handle": (handle(), 0, 0),
        "bracket_l": (bracket_l(), 0, 0),
        "dock_cap": (dock_cap(), 180, 0),
        "dock_foot": (dock_foot(), 0, 0),
        "module_solar_visor": (solar_visor(), 180 - VISOR_TILT, 0),
        "module_battery": (battery_module(), -90, 0),
        "module_battery_lid": (battery_module_lid(), 90, 0),
        "module_dev_blank": (dev_module(), -90, 0),
        "module_dev_blank_lid": (dev_module_lid(), 90, 0),
        "orbit_base": (orbit_base(), -90, 0),
        "orbit_base_lid": (orbit_base_lid(), 90, 0),
        "orbit_turret": (orbit_turret(), 0, 0),
        "orbit_cradle": (orbit_cradle(), 180, 0),
        "barrel_body": (barrel_body(), 180, 0),
        "barrel_front": (barrel_front(), 180, 0),
        "barrel_visor": (barrel_visor(), 0, 0),
        "barrel_carrier": (barrel_carrier(), 180, 0),
        "barrel_sled": (barrel_sled(), -90, 0),
        "barrel_hood": (barrel_hood(), 0, 0),
        "pod_body": (pod_body(), 0, 0),
        "pod_front": (pod_front(), 180, 0),
        "pod_visor": (pod_visor(), 0, 0),
        "pod_carrier": (pod_carrier(), 180, 0),
        "pod_sled": (pod_sled(), -90, 0),
        "pod_bezel_m12": (pod_bezel("m12"), 180, 0),
        "pod_bezel_cs": (pod_bezel("cs"), 180, 0),
        "pod_saddle": (pod_saddle(), 90, 0),
        "mount_base": (mount_base(), 0, 0),
        "mount_cup": (mount_cup(), 0, 0),
        "mount_collar": (mount_collar(), 0, 0),
        "hub_body": (hub_body(), 0, 0),
        "hub_top": (hub_top(), 0, 0),
    }


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    for sub in ("print", "step", "web"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    report = []
    for name, (solid, rot_x, _rot_y) in build().items():
        shape = solid.val()
        if not shape.isValid():
            raise SystemExit(f"{name}: invalid solid")
        printable = rx(solid, rot_x) if rot_x else solid
        bb = printable.val().BoundingBox()
        printable = printable.translate((-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, -bb.zmin))
        cq.exporters.export(printable, str(out / "print" / f"{name}.stl"), tolerance=0.02, angularTolerance=0.2)
        cq.exporters.export(solid, str(out / "step" / f"{name}.step"))
        cq.exporters.export(solid, str(out / "web" / f"{name}.stl"), tolerance=0.08, angularTolerance=0.35)
        report.append((name, bb.xlen, bb.ylen, bb.zlen, shape.Volume() / 1000.0, len(shape.Solids())))

    # Viewer-only meshes
    extra = {
        "web_slate_bezels": lens_bezel("m12", LENS_X).union(lens_bezel("m12", -LENS_X)),
        "web_solar_panel": box(-PANEL_W / 2, PANEL_W / 2, -PANEL_D - 3, -3, 5.0 - PANEL_T, 5.2)
        .rotate((0, 0, 0), (1, 0, 0), VISOR_TILT).translate((0, D / 2, 8.0 + VISOR_NECK)),
    }
    for name, solid in extra.items():
        cq.exporters.export(solid, str(out / "web" / f"{name}.stl"), tolerance=0.08, angularTolerance=0.35)
    back, front = viz_slate()
    inner, face = viz_barrel()
    servo = Bag()
    servo.put("servo", [B(-SERVO["off"] - 20.25, -SERVO["off"] + 20.25, -10.1, 10.1, 17, 54.2),
                        B(-SERVO["off"] - 27.25, -SERVO["off"] + 27.25, -10.1, 10.1, 44.5, 47.0)])
    servo.put("metal", C((0, 0, 54.2), (0, 0, 1), 6.0, 4.0))
    tilt = Bag()
    zt = ORBIT_ZT
    tilt.put("servo", [B(-19.2, 18.0, -SERVO["off"] - 20.25, -SERVO["off"] + 20.25, zt - 10.1, zt + 10.1),
                       B(8.5, 11.0, -SERVO["off"] - 27.25, -SERVO["off"] + 27.25, zt - 10.1, zt + 10.1)])
    tilt.put("metal", C((18.0, 0, zt), (1, 0, 0), 6.0, 6.0))
    mb = board_mainboard()
    pod_in, pod_face = Bag(), Bag()
    for sx in (-1, 1):
        for key, v in cell((sx * 16.4, P_CELL_Y, P_CELL_Z), (0, 0, 1)).items():
            pod_in.put(key, v)

    def lay(dx, dy, dz):
        def fn(sh):
            sh = sh.rotate(V(0, 0, 0), V(1, 0, 0), -90).rotate(V(0, 0, 0), V(0, 1, 0), -90)
            return sh.translate(V(dx, dy, dz))
        return fn

    pod_in.merge(board_mainboard(), lay(-37, P_DECK_Y + 3.0, P_CELL_Z))
    pod_in.merge(board_pi(), lay(5.5, P_DECK_Y + 3.0, P_CELL_Z + 3.0))
    pod_in.put("wire_red", wire([(-12, 4, P_CELL_Z + 71), (-12, P_DECK_Y + 2, P_CELL_Z + 66), (-34, P_DECK_Y + 11, P_CELL_Z + 62)], 1.8))
    pod_in.put("wire_black", wire([(12, 4, P_CELL_Z + 71), (12, P_DECK_Y + 2, P_CELL_Z + 68), (-31, P_DECK_Y + 11, P_CELL_Z + 64)], 1.8))
    zb = PF - FP_T - 9.0 - 3.2
    pod_face.merge(board_camera(P_FACE["lens"][0], P_FACE["lens"][1], zb))
    x2, y2 = P_FACE["lens2"]
    pod_face.put("pcb", B(x2 - 9, x2 + 9, y2 - 9, y2 + 9, zb, zb + 1.4))
    pod_face.put("lens", C((x2, y2, zb + 1.4), (0, 0, 1), 12.0, PF + 0.6 - zb - 1.4))
    pod_face.put("glass", C((x2, y2, PF + 0.6), (0, 0, 1), 7.0, 0.4))
    by = P_FACE["bar_y"]
    pod_face.put("pcb_white", B(-25.5, 25.5, by - 5.1, by + 5.1, PF - FP_T - 2.8, PF - FP_T - 1.6))
    pod_face.put("leds", [B(-24.9 + i * 6.4, -19.9 + i * 6.4, by - 2.5, by + 2.5, PF - FP_T - 1.6, PF - FP_T) for i in range(8)])
    pod_face.put("dome", C((P_FACE["pir"][0], P_FACE["pir"][1], PF - 6), (0, 0, 1), 10.0, 8.6))
    pw, pl, pd = P_PANEL
    cq.exporters.export(box(-pw / 2, pw / 2, PH / 2 - pd, PH / 2 + 0.15, 10.3, 10.3 + pl), str(out / "web" / "web_pod_panel.stl"))
    hub = Bag()
    zd = HUB["wall"] + HUB["lift"]
    hub.put("alu", rbox(HUB["dev_w"], HUB["dev_d"], HUB["dev_h"], 24.0).translate((0, 0, zd)).val())
    th = SCREEN["tilt"]
    glass = box(-SCREEN["w"] / 2, SCREEN["w"] / 2, 8.3, 8.3 + SCREEN["h"], -1.5, 0.05).rotate((0, 0, 0), (1, 0, 0), th)
    hub.put("glass", glass.translate((0, -HUB_D / 2 + 4.0, HUB_H + 3.0)).val())
    ui = box(-SCREEN["view_w"] / 2, SCREEN["view_w"] / 2, 13.0, 13.0 + SCREEN["view_h"], 0.05, 0.12).rotate((0, 0, 0), (1, 0, 0), th)
    hub.put("ui", ui.translate((0, -HUB_D / 2 + 4.0, HUB_H + 3.0)).val())
    for prefix, bag in (("viz_slate_back_", back), ("viz_slate_front_", front), ("viz_barrel_in_", inner),
                        ("viz_barrel_face_", face), ("viz_orbit_pan_", servo), ("viz_orbit_tilt_", tilt),
                        ("viz_mainboard_", mb), ("viz_pod_in_", pod_in), ("viz_pod_face_", pod_face), ("viz_hub_", hub)):
        for key, shapes in bag.items():
            comp = cq.Compound.makeCompound(shapes)
            cq.exporters.export(comp, str(out / "web" / f"{prefix}{key}.stl"), tolerance=0.1, angularTolerance=0.4)

    board = {
        "name": "Slate mainboard", "rev": "A", "width": MB["w"], "height": MB["h"],
        "holes": [[x, y] for x in (3.5, MB["w"] - 3.5) for y in (3.5, MB["h"] - 3.5)],
        "parts": [dict(ref=r, label=l, x=x, y=y, w=w, h=h, kind=k) for r, l, x, y, w, h, k, _ in MAINBOARD],
    }
    (out / "web" / "mainboard.json").write_text(json.dumps(board, indent=1))
    dims = {
        "slate": {"w": W, "h": H, "d": D, "lensX": LENS_X, "lensY": LENS_Y, "ledX": LED_X, "ledY": LED_Y,
                  "flash": FLASH_PTS, "als": ALS, "visorT": VIS["t"]},
        "barrel": {"r": BR, "l": BL, "dockZ": B_DOCK_Z, "padY": B_PAD_Y, "ringR": B_FACE["ring_r"]},
        "orbit": {"zt": ORBIT_ZT, "top": ORBIT_TOP, "h": OB_H},
        "pod": {"w": PW, "h": PH, "face": PF, "rim": P_RIM, "brow": P_BROW, "dockZ": P_DOCK_Z, "saddleY": PH / 2 + 9.0, "barY": P_FACE["bar_y"], "lens": P_FACE["lens"], "lens2": P_FACE["lens2"], "port": P_FACE["port"], "ballZ": 4.0 + P_BALL + 0.6},
        "hub": {"w": HUB_W, "d": HUB_D, "h": HUB_H},
        "modules": {"batteryH": BM_H, "devH": DM_H},
    }
    (out / "web" / "dims.json").write_text(json.dumps(dims, indent=1))

    print(f"{'part':24} {'x':>7} {'y':>7} {'z':>7} {'cm3':>7} solids")
    for name, x, y, z, vol, n in report:
        print(f"{name:24} {x:7.1f} {y:7.1f} {z:7.1f} {vol:7.1f} {n}")


if __name__ == "__main__":
    main()
