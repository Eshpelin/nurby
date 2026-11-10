"""Nurby Slate v0.1 - parametric CAD for the open source camera.

Run:  python slate.py [out_dir]

Writes, relative to out_dir (default: the parent "slate" directory):
  print/*.stl   parts in print orientation (flat face on the bed)
  step/*.step   the same parts as editable solids, in assembly coordinates
  web/*.stl     low-poly parts in assembly coordinates, used by the web viewer

Requires CadQuery 2.4+  (pip install cadquery).

Coordinate system (assembly): X = width, Y = up when wall mounted,
Z = depth. The back of the camera sits on Z = 0 and the lens looks along +Z.
All dimensions are millimetres.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import cadquery as cq

# --------------------------------------------------------------------------
# Parameters. Change these, re-run, re-print.
# --------------------------------------------------------------------------
W, H, D = 164.0, 112.0, 42.0  # core body outer size
R = 13.0                       # corner radius
EDGE = 1.5                     # chamfer on the front and back outer edges
WALL = 2.4                     # shell wall (6 perimeters at 0.4 nozzle)
FP_T = 3.0                     # front plate thickness
SHELL_D = D - FP_T             # depth of the back shell
CLR = 0.2                      # general fit clearance

# Fasteners
INSERT_D = 4.0                 # hole for an M3 heat-set insert (4.6 OD class)
M3_CLEAR = 3.4
VESA = 75.0                    # back mounting pattern, M3 inserts

# Dock-50 module interface (see docs/DOCK-SPEC.md)
PEG_X = (-19.0, 15.5)          # asymmetric so a module cannot go on reversed
PEG_D, PEG_H = 6.0, 4.0
SCREW_X = (-27.0, 27.0)
PAD_W, PAD_HALF_DEPTH, PAD_T = 66.0, 12.0, 8.4
USBC_SLOT = (9.4, 3.7)         # receptacle shell opening
USBC_PCB = (24.0, 6.5)         # pocket for the receptacle breakout board
USBC_PLUG = (12.8, 6.8)        # floating pocket for the module's plug

# Battery: 32700 LiFePO4, two cells end to end, wired 1S2P
CELL_D, CELL_L = 32.2, 70.5
CELL_Y = -19.0                 # cell axis height in the body

# Compute: Raspberry Pi Zero footprint (65 x 30, holes 58 x 23)
PI_CENTER = (-43.5, 31.0)
PI_STANDOFF = 7.0

# Front plate layout
LENS_Y = 12.0
LENS_HOLE = 17.0
LED_X = 48.0                   # centre of each 8 LED stick (51.1 x 10.2)
SPK = (25.0, 20.5, 28.0)       # y, z, diameter. Fires through the right side wall
PIR = (-34.0, 25.5, 10.3)
MIC = (34.0, 25.5)
IR_LED = ((-17.0, LENS_Y), (17.0, LENS_Y))
VISOR = (146.0, 38.0, 1.6)     # black visor island: width, height, thickness
CAM_BOSS_DY = 19.0             # camera carrier screws above and below the lens

# Solar visor. Default pocket fits the common 6 V 2 W panel (136 x 110 x 3).
PANEL_W, PANEL_D, PANEL_T = 136.0, 110.0, 3.0
VISOR_TILT = 20.0              # degrees, front edge down
VISOR_NECK = 28.0              # height of the tray's back edge above the dock

# Battery module (two more 32700 cells, standing upright)
BM_W, BM_H = 138.0, 78.0
# Blank developer module
DM_W, DM_H = 66.0, 40.0
LID_T = 2.4


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def box(x0, x1, y0, y1, z0, z1):
    return (
        cq.Workplane("XY")
        .box(x1 - x0, y1 - y0, z1 - z0, centered=False)
        .translate((x0, y0, z0))
    )


def rbox(w, h, d, r):
    """Rounded rectangle centred on XY, extruded from Z = 0."""
    s = cq.Workplane("XY").rect(w, h).extrude(d)
    return s.edges("|Z").fillet(r) if r > 0 else s


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


# --------------------------------------------------------------------------
# Dock-50. Canonical frame: the mating face is Z = 0, centred on the origin,
# long axis X. The host (female) is below the face, the module (male) above.
# In this frame +Y points to the BACK of the camera.
# --------------------------------------------------------------------------
def dock_female_pad(back=PAD_HALF_DEPTH):
    """Solid pad behind a female dock. `back` extends it to the rear wall so
    it prints without supports."""
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
        p = cq.Workplane("XY").circle(PEG_D / 2).extrude(PEG_H + 0.1)
        p = p.faces(">Z").chamfer(0.8)
        pegs.append(p.rotate((0, 0, 0), (1, 0, 0), 180).translate((px, 0, 0.1)))
    return union(pegs)


def dock_male_cut(floor_t, plug=True):
    parts = [cyl_z(sx, 0, M3_CLEAR, -1, floor_t + 1) for sx in SCREW_X]
    if plug:
        pw, ph = USBC_PLUG
        parts.append(box(-pw / 2, pw / 2, -ph / 2, ph / 2, -1, floor_t + 1))
    return union(parts)


def to_top(s, lift=0.0):
    """Module/canonical frame -> assembly frame, on the top bay."""
    return s.rotate((0, 0, 0), (1, 0, 0), -90).translate((0, H / 2 + lift, D / 2))


def to_bottom(s):
    s = s.rotate((0, 0, 0), (1, 0, 0), -90).rotate((0, 0, 0), (0, 0, 1), 180)
    return s.translate((0, -H / 2, D / 2))


# --------------------------------------------------------------------------
# Core body
# --------------------------------------------------------------------------
def corner_points(inset=9.0):
    return [(sx * (W / 2 - inset), sy * (H / 2 - inset)) for sx in (-1, 1) for sy in (-1, 1)]


def vesa_points():
    return [(sx * VESA / 2, sy * VESA / 2) for sx in (-1, 1) for sy in (-1, 1)]


def pi_points():
    cx, cy = PI_CENTER
    return [(cx + sx * 29.0, cy + sy * 11.5) for sx in (-1, 1) for sy in (-1, 1)]


def back_shell():
    outer = rbox(W, H, SHELL_D, R).faces("<Z").chamfer(EDGE)
    inner = rbox(W - 2 * WALL, H - 2 * WALL, SHELL_D, R - WALL).translate((0, 0, WALL))
    s = outer.cut(inner)

    adds = []
    # Screw tunnels. The front plate is pulled on from the back, so no
    # fastener shows on the face.
    boss_top = SHELL_D - 7.2
    adds += [cyl_z(x, y, 10.0, 0.5, boss_top) for x, y in corner_points()]
    # Speaker guide ribs against the right wall
    sy, sz, sd = SPK
    for y0 in (sy - sd / 2 - 3, sy + sd / 2 - 3):
        adds.append(box(W / 2 - WALL - 7.6, W / 2 - WALL - 6.0, y0, y0 + 6, WALL - 0.1, WALL + 33))
    # VESA 75 mount bosses (inserts go in from the outside back)
    adds += [cyl_z(x, y, 9.0, 0.1, WALL + 6.0) for x, y in vesa_points()]
    # Pi Zero standoffs
    adds += [cyl_z(x, y, 6.0, WALL - 0.1, WALL + PI_STANDOFF) for x, y in pi_points()]
    # Battery cradle ribs
    for x in (-58.0, -22.0, 22.0, 58.0):
        adds.append(box(x - 1.5, x + 1.5, CELL_Y - 18, CELL_Y + 18, WALL - 0.1, WALL + 11))
    # Peg grid slab for the small breakout boards (right of the lens)
    adds.append(box(14, 68, 2, 46, WALL - 0.1, WALL + 1.6))
    # Dock pads, top and bottom, carried back to the rear wall
    adds.append(to_top(dock_female_pad(back=D / 2 - 0.1)))
    adds.append(to_bottom(dock_female_pad(back=D / 2 - 0.1)))
    s = s.union(union(adds))
    s = s.intersect(outer)

    cuts = []
    # Cell seats
    cell_z = WALL + 0.4 + CELL_D / 2
    cuts.append(cyl_x(CELL_Y, cell_z, CELL_D + 0.8, -78, 78))
    for x, y in corner_points():
        cuts.append(cyl_z(x, y, M3_CLEAR, -1, SHELL_D))
        cuts.append(cyl_z(x, y, 6.5, -1, boss_top - 5.0))
    # Speaker grille in the right side wall
    for i in range(-4, 5):
        for j in range(-4, 5):
            gy = i * 3.2 + (1.6 if j % 2 else 0)
            gz = j * 2.8
            if math.hypot(gy, gz) <= sd / 2 - 2.5:
                cuts.append(cyl_x(sy + gy, sz + gz, 1.8, W / 2 - WALL - 1, W / 2 + 1))
    cuts += [cyl_z(x, y, INSERT_D, -1, 6.5) for x, y in vesa_points()]
    cuts += [cyl_z(x, y, 2.2, WALL + 1, WALL + PI_STANDOFF + 1) for x, y in pi_points()]
    # Peg grid: 2 mm pilot holes on a 6 mm pitch for M2 self tapping screws
    for i in range(9):
        for j in range(8):
            gx, gy = 17 + 6 * i, 5 + 6 * j
            if math.hypot(gx - VESA / 2, gy - VESA / 2) < 7.5:
                continue
            cuts.append(cyl_z(gx, gy, 2.0, WALL + 0.2, WALL + 3))
    cuts.append(to_top(dock_female_cut()))
    cuts.append(to_bottom(dock_female_cut()))
    # Fixed USB-C charge port and battery disconnect switch on the bottom
    sw, sh = USBC_SLOT
    cuts.append(box(50 - sw / 2, 50 + sw / 2, -H / 2 - 1, -H / 2 + WALL + 1, D / 2 - sh / 2, D / 2 + sh / 2))
    cuts.append(cyl_y(-50, D / 2, 6.2, -H / 2 - 1, -H / 2 + WALL + 1))
    s = s.cut(union(cuts))

    # Divider between the two cells, added after the seat cut
    s = s.union(box(-1, 1, CELL_Y - 17, CELL_Y + 17, WALL - 0.1, WALL + 22))
    return s


def front_plate():
    z0 = SHELL_D
    p = rbox(W, H, FP_T, R).faces(">Z").chamfer(EDGE).translate((0, 0, z0))

    # Locating ring that drops inside the shell
    rw, rh = W - 2 * WALL - 2 * CLR, H - 2 * WALL - 2 * CLR
    ring = rbox(rw, rh, 1.6, R - WALL).cut(rbox(rw - 3.2, rh - 3.2, 1.6, R - WALL - 1.6))
    ring = ring.translate((0, 0, z0 - 1.6))

    adds = [ring]
    # Corner bosses that take the screws coming through from the back
    adds += [cyl_z(x, y, 8.0, z0 - 7, z0 + 0.1) for x, y in corner_points()]
    # Camera carrier bosses
    for dy in (-CAM_BOSS_DY, CAM_BOSS_DY):
        adds.append(cyl_z(0, LENS_Y + dy, 8.0, z0 - 7, z0 + 0.1))
    # LED stick pockets
    for sx in (-1, 1):
        cx = sx * LED_X
        frame = box(cx - 27.8, cx + 27.8, LENS_Y - 7.3, LENS_Y + 7.3, z0 - 3, z0 + 0.1)
        frame = frame.cut(box(cx - 25.9, cx + 25.9, LENS_Y - 5.4, LENS_Y + 5.4, z0 - 4, z0))
        adds.append(frame)
    p = p.union(union(adds))

    cuts = [cyl_z(0, LENS_Y, LENS_HOLE, z0 - 1, D + 1)]
    cuts += [cyl_z(x, y, INSERT_D, z0 - 8, z0 - 1.0) for x, y in corner_points()]
    for dy in (-CAM_BOSS_DY, CAM_BOSS_DY):
        cuts.append(cyl_z(0, LENS_Y + dy, INSERT_D, z0 - 8, z0 - 1.0))
    for sx in (-1, 1):
        cx = sx * LED_X
        cuts.append(box(cx - 24, cx + 24, LENS_Y - 3, LENS_Y + 3, z0 - 1, D + 1))
    cuts.append(cyl_z(PIR[0], PIR[1], PIR[2], z0 - 1, D + 1))
    cuts.append(cyl_z(MIC[0], MIC[1], 1.5, z0 - 1, D + 1))
    cuts += [cyl_z(x, y, 5.2, z0 - 1, D + 1) for x, y in IR_LED]
    return p.cut(union(cuts))


def visor_glass():
    """Black island that covers the lens, light bars and sensors. Print it in
    translucent smoke PETG, or cut it from 1.5 mm smoked acrylic. Bonded to
    the face with thin double sided tape."""
    vw, vh, vt = VISOR
    v = rbox(vw, vh, vt, vh / 2 - 0.05).faces(">Z").chamfer(0.6).translate((0, LENS_Y, D))
    cuts = [cyl_z(0, LENS_Y, 15.0, D - 1, D + vt + 1)]
    cuts.append(cyl_z(PIR[0], PIR[1], PIR[2], D - 1, D + vt + 1))
    cuts.append(cyl_z(MIC[0], MIC[1], 1.5, D - 1, D + vt + 1))
    return v.cut(union(cuts))


def camera_carrier():
    """Bridge that holds the sensor board behind the front plate. Default
    hole pattern is the Raspberry Pi camera one (21 x 12.5, M2). Edit the
    points below for other boards."""
    zf = SHELL_D - 7.0  # front face of the carrier sits on the plate bosses
    c = box(-13.5, 13.5, LENS_Y - 23, LENS_Y + 23, zf - 2, zf)
    posts = [(-10.5, 0.0), (10.5, 0.0), (-10.5, 12.5), (10.5, 12.5)]
    c = c.union(union([cyl_z(x, LENS_Y + y, 4.5, zf - 3.5, zf - 1.9) for x, y in posts]))
    cuts = [cyl_z(0, LENS_Y, 15.0, zf - 3, zf + 1)]
    cuts += [cyl_z(0, LENS_Y + dy, M3_CLEAR, zf - 3, zf + 1) for dy in (-CAM_BOSS_DY, CAM_BOSS_DY)]
    cuts += [cyl_z(x, LENS_Y + y, 1.8, zf - 4, zf + 1) for x, y in posts]
    return c.cut(union(cuts))


def wall_plate():
    """Sits between the wall and the camera back. Z = -6 .. 0."""
    t = 6.0
    p = rbox(95, 95, t, 6).translate((0, 0, -t))
    cuts = []
    for x, y in vesa_points():
        cuts.append(cyl_z(x, y, M3_CLEAR, -t - 1, 1))
        cuts.append(cyl_z(x, y, 6.5, -t - 1, -t + 3.2))
    # Two keyholes for wall screws. Hang, then slide down.
    for ky in (-22.0, 18.0):
        cuts.append(cyl_z(0, ky, 9.0, -t - 1, 1))
        cuts.append(box(-2.3, 2.3, ky, ky + 10, -t - 1, 1))
        cuts.append(cyl_z(0, ky + 10, 4.6, -t - 1, 1))
        cuts.append(box(-4.5, 4.5, ky, ky + 10, -t + 2.5, 1))
        cuts.append(cyl_z(0, ky + 10, 9.0, -t + 2.5, 1))
    return p.cut(union(cuts))


# --------------------------------------------------------------------------
# Modules. Module frame: dock face on Z = 0, body above, front towards -Y.
# --------------------------------------------------------------------------
def dock_cap():
    c = box(-PAD_W / 2, PAD_W / 2, -PAD_HALF_DEPTH, PAD_HALF_DEPTH, 0, 3.0)
    c = c.edges("|Z").fillet(3.0).union(dock_male_pegs())
    return c.cut(dock_male_cut(3.0, plug=False))


def solar_visor():
    foot_t = 8.0
    foot = box(-PAD_W / 2, PAD_W / 2, -PAD_HALF_DEPTH, PAD_HALF_DEPTH, 0, foot_t)
    foot = foot.edges("|Z").fillet(3.0)

    tw, td, tt = PANEL_W + 6.0, PANEL_D + 6.0, 5.0
    back_y = D / 2
    lift = foot_t + VISOR_NECK

    def place(s):
        return s.rotate((0, 0, 0), (1, 0, 0), VISOR_TILT).translate((0, back_y, lift))

    tray = box(-tw / 2, tw / 2, -td, 0, 0, tt).edges("|Z").fillet(10.0)
    pocket = box(-PANEL_W / 2 - 0.3, PANEL_W / 2 + 0.3, -td + 2.7, -2.7, tt - PANEL_T - 0.2, tt + 1)
    tray = place(tray.cut(pocket))

    neck = box(-20, 20, -PAD_HALF_DEPTH, PAD_HALF_DEPTH, foot_t - 0.1, lift + 20).edges("|Z").fillet(6.0)
    neck = neck.intersect(place(box(-300, 300, -400, 200, -400, 1.2)))

    v = foot.union(neck).union(tray).union(dock_male_pegs())
    cuts = [dock_male_cut(foot_t)]
    cuts.append(cyl_z(0, 0, 8.0, foot_t - 2, lift + 30).intersect(place(box(-300, 300, -400, 200, -400, tt - PANEL_T))))
    return v.cut(union(cuts))


def _module_shell(w, h, fillet):
    body = box(-w / 2, w / 2, -D / 2 + LID_T, D / 2, 0, h).edges("|Y").fillet(fillet)
    cavity = box(-w / 2 + WALL, w / 2 - WALL, -D / 2, D / 2 - WALL, 3.0, h - WALL)
    return body.cut(cavity)


def _module_lid(w, h, fillet, holes):
    lid = box(-w / 2, w / 2, -D / 2, -D / 2 + LID_T, 0, h).edges("|Y").fillet(fillet)
    iw0, iw1 = -w / 2 + WALL + CLR, w / 2 - WALL - CLR
    step = box(iw0, iw1, -D / 2 + LID_T - 0.1, -D / 2 + LID_T + 1.5, 3.0 + CLR, h - WALL - CLR)
    step = step.cut(box(iw0 + 1.6, iw1 - 1.6, -D / 2, D / 2, 3.0 + CLR + 1.6, h - WALL - CLR - 1.6))
    lid = lid.union(step)
    cuts = [cyl_y(x, z, M3_CLEAR, -D / 2 - 1, -D / 2 + LID_T + 2) for x, z in holes]
    return lid.cut(union(cuts))


BM_POSTS = ((-28.0, 39.0), (28.0, 39.0))
DM_POSTS = ((0.0, 30.0),)


def _posts(points):
    posts = [cyl_y(x, z, 8.0, -D / 2 + LID_T, D / 2 - WALL + 0.1) for x, z in points]
    holes = [cyl_y(x, z, INSERT_D, -D / 2, -D / 2 + LID_T + 7) for x, z in points]
    return union(posts), union(holes)


def battery_module():
    """Two upright 32700 cells either side of a central electronics bay.
    Male dock underneath, female dock on top, so modules stack."""
    s = _module_shell(BM_W, BM_H, 4.0)
    posts, post_holes = _posts(BM_POSTS)
    adds = [posts, box(-PAD_W / 2, PAD_W / 2, -PAD_HALF_DEPTH, PAD_HALF_DEPTH, 0, 5.0)]
    adds.append(dock_female_pad(back=D / 2 - 0.1).translate((0, 0, BM_H)))
    cell_x = BM_W / 2 - WALL - CELL_D / 2 - 0.6
    for sx in (-1, 1):
        for z in (20.0, 55.0):
            x0, x1 = sorted((sx * 35.0, sx * (BM_W / 2 - WALL + 0.1)))
            rib = box(x0, x1, -D / 2 + LID_T + 2, D / 2 - WALL + 0.1, z, z + 3)
            rib = rib.cut(cyl_z(sx * cell_x, 0, CELL_D + 0.8, z - 1, z + 4))
            rib = rib.cut(box(sx * cell_x - CELL_D / 2 - 0.4, sx * cell_x + CELL_D / 2 + 0.4, -D / 2, 0, z - 1, z + 4))
            adds.append(rib)
    s = s.union(union(adds)).union(dock_male_pegs())
    cuts = [dock_male_cut(5.0), dock_female_cut().translate((0, 0, BM_H)), post_holes]
    return s.cut(union(cuts))


def battery_module_lid():
    return _module_lid(BM_W, BM_H, 4.0, BM_POSTS)


def dev_module():
    """Blank module to remix: lidar, bigger speaker, floodlight, sensors."""
    s = _module_shell(DM_W, DM_H, 3.0)
    posts, post_holes = _posts(DM_POSTS)
    s = s.union(posts).union(dock_male_pegs())
    return s.cut(union([dock_male_cut(3.0), post_holes]))


def dev_module_lid():
    return _module_lid(DM_W, DM_H, 3.0, DM_POSTS)


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------
def rx(s, deg):
    return s.rotate((0, 0, 0), (1, 0, 0), deg)


def build():
    """name -> (solid in its own frame, print rotation about X, placement)"""
    module = lambda s: to_top(s)  # noqa: E731
    same = lambda s: s            # noqa: E731
    return {
        "core_back_shell": (back_shell(), 0, same),
        "core_front_plate": (front_plate(), 180, same),
        "camera_carrier": (camera_carrier(), 180, same),
        "visor_glass": (visor_glass(), 0, same),
        "wall_plate": (wall_plate(), 0, same),
        "dock_cap": (dock_cap(), 180, module),
        "module_solar_visor": (solar_visor(), 180 - VISOR_TILT, module),
        "module_battery": (battery_module(), -90, module),
        "module_battery_lid": (battery_module_lid(), 90, module),
        "module_dev_blank": (dev_module(), -90, module),
        "module_dev_blank_lid": (dev_module_lid(), 90, module),
    }


def viz():
    """Stand-ins for bought parts. Web viewer only, never printed."""
    cell_z = WALL + 0.4 + CELL_D / 2
    cells = cyl_x(CELL_Y, cell_z, CELL_D, -CELL_L - 1, -1).union(cyl_x(CELL_Y, cell_z, CELL_D, 1, CELL_L + 1))
    cx, cy = PI_CENTER
    pi = box(cx - 32.5, cx + 32.5, cy - 15, cy + 15, WALL + PI_STANDOFF, WALL + PI_STANDOFF + 1.6)
    zf = SHELL_D - 9.0
    cam = box(-12.5, 12.5, LENS_Y - 9.5, LENS_Y + 14.5, zf - 3.2, zf - 1.6)
    lens = cyl_z(0, LENS_Y, 14.0, zf - 1.6, D + VISOR[2] + 0.3)
    tt, td = 5.0, PANEL_D + 6.0
    panel = box(-PANEL_W / 2, PANEL_W / 2, -td + 3, -3, tt - PANEL_T, tt + 0.2)
    panel = panel.rotate((0, 0, 0), (1, 0, 0), VISOR_TILT).translate((0, D / 2, 8.0 + VISOR_NECK))
    cell_x = BM_W / 2 - WALL - CELL_D / 2 - 0.6
    mcells = cyl_z(-cell_x, 0, CELL_D, 4, 4 + CELL_L).union(cyl_z(cell_x, 0, CELL_D, 4, 4 + CELL_L))
    return {
        "viz_cells": cells,
        "viz_pi": pi,
        "viz_camera_board": cam,
        "viz_lens": lens,
        "viz_solar_panel": to_top(panel),
        "viz_module_cells": to_top(mcells),
    }


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    for sub in ("print", "step", "web"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    for name, solid in viz().items():
        cq.exporters.export(solid, str(out / "web" / f"{name}.stl"), tolerance=0.2, angularTolerance=0.5)

    report = []
    for name, (solid, print_rot, place) in build().items():
        shape = solid.val()
        if not shape.isValid():
            raise SystemExit(f"{name}: invalid solid")
        printable = rx(solid, print_rot) if print_rot else solid
        bb = printable.val().BoundingBox()
        printable = printable.translate((-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, -bb.zmin))
        cq.exporters.export(printable, str(out / "print" / f"{name}.stl"), tolerance=0.02, angularTolerance=0.2)
        placed = place(solid)
        cq.exporters.export(placed, str(out / "step" / f"{name}.step"))
        cq.exporters.export(placed, str(out / "web" / f"{name}.stl"), tolerance=0.15, angularTolerance=0.5)
        vol = shape.Volume() / 1000.0
        report.append((name, bb.xlen, bb.ylen, bb.zlen, vol, len(shape.Solids())))

    print(f"{'part':24} {'x':>7} {'y':>7} {'z':>7} {'cm3':>7} solids")
    for name, x, y, z, vol, n in report:
        print(f"{name:24} {x:7.1f} {y:7.1f} {z:7.1f} {vol:7.1f} {n}")


if __name__ == "__main__":
    main()
