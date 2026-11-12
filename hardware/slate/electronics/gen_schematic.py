"""Nurby camera carrier, rev A. Generates the KiCad 8 schematic set.

The circuit is described once, as parts and nets, in CIRCUIT below. This
script lays it out and writes:

  slate.kicad_sch            root sheet
  power.kicad_sch            battery, charger, rails, compute rail switch
  controller.kicad_sch       always-on controller, PWM expander, sensors
  compute.kicad_sch          Raspberry Pi header, audio, IR, USB hub
  docks.kicad_sch            two Dock-50 ports, light bar, flash LEDs
  out/NETLIST.md, out/BOM.md human-readable net and part lists

Then check and plot it with KiCad itself (see README.md):

  kicad-cli sch erc slate.kicad_sch
  kicad-cli sch export pdf slate.kicad_sch

Connections are made with global net labels on short stubs, so a net name
means the same thing on every sheet.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
STOCK = json.loads((HERE / "lib" / "stock_symbols.json").read_text())
PROJECT = "slate"
G = 2.54
STUB = 2 * G


def uid(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "nurby-slate-carrier/" + key))


def snap(v: float) -> float:
    return round(round(v / G) * G, 4)


FONT = "(effects (font (size 1.27 1.27)))"
HIDE = "(effects (font (size 1.27 1.27)) hide)"

# --------------------------------------------------------------------------
# Symbols
# --------------------------------------------------------------------------
PIN_TYPES = {"P": "power_in", "O": "power_out", "i": "input", "o": "output", "b": "bidirectional", "p": "passive"}


class Sym:
    def __init__(self, lib_id, block, pins, half_w, half_h):
        self.lib_id, self.block, self.pins, self.half_w, self.half_h = lib_id, block, pins, half_w, half_h
        self.by_name = {p["name"]: n for n, p in pins.items() if p["name"] not in ("~", "")}


def stock(lib_id, half_w, half_h):
    raw = STOCK[lib_id]
    name = lib_id.split(":")[1]
    block = raw.replace(f'(symbol "{name}"', f'(symbol "{lib_id}"', 1)
    pins = {}
    pat = r'\(pin\s+(\w+)\s+(\w+)\s*\(at\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\)\s*\(length\s+([-\d.]+)\).*?\(name\s+"([^"]*)".*?\(number\s+"([^"]+)"'
    for typ, _shape, x, y, a, _l, pname, num in re.findall(pat, raw, re.S):
        pins[num] = dict(x=float(x), y=float(y), a=int(a), name=pname, type=typ)
    return Sym(lib_id, block, pins, half_w, half_h)


def custom(name, left, right, prefix="U", width=10 * G):
    """Box symbol. left/right are lists of (number, pin name, type letter)."""
    rows = max(len(left), len(right))
    top = math.ceil(rows / 2) * G
    hw = width / 2
    pins, lines = {}, []
    for side, items in (("L", left), ("R", right)):
        for i, (num, pname, t) in enumerate(items):
            y = top - G - i * G
            x, a = (-hw - G, 0) if side == "L" else (hw + G, 180)
            pins[str(num)] = dict(x=x, y=y, a=a, name=pname, type=PIN_TYPES[t])
            lines.append(
                f'(pin {PIN_TYPES[t]} line (at {x:.2f} {y:.2f} {a}) (length {G}) '
                f'(name "{pname}" {FONT}) (number "{num}" {FONT}))'
            )
    bottom = top - G - rows * G
    block = (
        f'(symbol "slate:{name}" (exclude_from_sim no) (in_bom yes) (on_board yes)\n'
        f'  (property "Reference" "{prefix}" (at 0 {top + 1.5:.2f} 0) {FONT})\n'
        f'  (property "Value" "{name}" (at 0 {bottom - 1.5:.2f} 0) {FONT})\n'
        f'  (property "Footprint" "" (at 0 0 0) {HIDE})\n'
        f'  (property "Datasheet" "" (at 0 0 0) {HIDE})\n'
        f'  (symbol "{name}_0_1" (rectangle (start {-hw:.2f} {top:.2f}) (end {hw:.2f} {bottom:.2f}) '
        f"(stroke (width 0.254) (type default)) (fill (type background))))\n"
        f'  (symbol "{name}_1_1"\n    ' + "\n    ".join(lines) + "))"
    )
    return Sym(f"slate:{name}", block, pins, hw + G, max(top, -bottom))


def conn(name, pin_names):
    return custom(name, [(i + 1, n, "p") for i, n in enumerate(pin_names)], [], prefix="J", width=6 * G)


def pi_header():
    use = {
        1: ("3V3", "O"), 2: ("5V", "P"), 4: ("5V", "P"), 3: ("GPIO2", "b"), 5: ("GPIO3", "b"), 7: ("GPIO4", "b"),
        8: ("GPIO14/TXD", "b"), 10: ("GPIO15/RXD", "b"), 11: ("GPIO17", "b"), 12: ("GPIO18/PCM_CLK", "b"),
        13: ("GPIO27", "b"), 15: ("GPIO22", "b"), 16: ("GPIO23", "b"), 17: ("3V3", "p"), 18: ("GPIO24", "b"),
        19: ("GPIO10", "b"), 21: ("GPIO9", "b"), 22: ("GPIO25", "b"), 23: ("GPIO11", "b"), 24: ("GPIO8", "b"),
        26: ("GPIO7", "b"), 27: ("ID_SD", "b"), 28: ("ID_SC", "b"), 29: ("GPIO5", "b"), 31: ("GPIO6", "b"),
        32: ("GPIO12", "b"), 33: ("GPIO13", "b"), 35: ("GPIO19/PCM_FS", "b"), 36: ("GPIO16", "b"),
        37: ("GPIO26", "b"), 38: ("GPIO20/PCM_DIN", "b"), 40: ("GPIO21/PCM_DOUT", "b"),
    }
    for g in (6, 9, 14, 20, 25, 30, 34, 39):
        use[g] = ("GND", "P")
    left = [(n, f"{use[n][0]}", use[n][1]) for n in range(1, 40, 2)]
    right = [(n, f"{use[n][0]}", use[n][1]) for n in range(2, 41, 2)]
    # pin names must be unique for lookup by name, so qualify repeats
    seen = {}
    def uniq(items):
        out = []
        for n, nm, t in items:
            seen[nm] = seen.get(nm, 0) + 1
            out.append((n, nm if seen[nm] == 1 else f"{nm}.{n}", t))
        return out
    return custom("RaspberryPi_40pin", uniq(left), uniq(right), prefix="J", width=22 * G)


SYMS = {
    "R": stock("Device:R", 3.81, 1.5), "C": stock("Device:C", 3.81, 2.0), "CP": stock("Device:C_Polarized", 3.81, 2.0),
    "D": stock("Device:D_Schottky", 3.81, 1.5), "F": stock("Device:Fuse", 3.81, 1.5),
    "PMOS": stock("Device:Q_PMOS_GSD", 5.08, 5.08), "NMOS": stock("Device:Q_NMOS_GSD", 5.08, 5.08),
    "BUF": stock("74xGxx:74LVC1G125", 15.24, 10.16), "FLAG": stock("power:PWR_FLAG", 1.5, 2.5),
    "XIAO": custom("XIAO_ESP32C6", [(1, "D0", "b"), (2, "D1", "b"), (3, "D2", "b"), (4, "D3", "b"), (5, "D4/SDA", "b"),
                                    (6, "D5/SCL", "b"), (7, "D6/TX", "b")],
                   [(14, "5V", "p"), (13, "GND", "P"), (12, "3V3", "P"), (11, "D10", "b"), (10, "D9", "b"),
                    (9, "D8", "b"), (8, "D7/RX", "b")], width=10 * G),
    "CHG": custom("bq25185_Charger", [(1, "DCIN", "P"), (2, "GND", "P"), (3, "/CE", "i")],
                  [(4, "LOAD", "O"), (5, "BATT", "p"), (6, "S1", "p"), (7, "S2", "p")]),
    "REG3": custom("S7V8F3_3V3", [(2, "VIN", "P"), (3, "GND", "P"), (1, "SHDN", "i")], [(4, "VOUT", "O")]),
    "REG5": custom("U3V70F5_5V", [(1, "VIN", "P"), (2, "GND", "P"), (4, "ENABLE", "i")], [(3, "VOUT", "O")]),
    "INA": custom("INA219", [(1, "VCC", "P"), (2, "GND", "P"), (3, "SCL", "i"), (4, "SDA", "b")],
                  [(5, "VIN+", "p"), (6, "VIN-", "p")]),
    "PCA": custom("PCA9685_PWM", [(1, "GND", "P"), (2, "OE", "i"), (3, "SCL", "i"), (4, "SDA", "b"), (5, "VCC", "P"),
                                  (6, "V+", "P")], [(7 + i, f"PWM{i}", "o") for i in range(9)]),
    "PI": pi_header(),
    "AMP": custom("MAX98357A", [(1, "LRC", "i"), (2, "BCLK", "i"), (3, "DIN", "i"), (4, "GAIN", "i"), (5, "SD", "i"),
                                (6, "GND", "P"), (7, "VIN", "P")], [(8, "OUT+", "p"), (9, "OUT-", "p")]),
    "MIC": custom("INMP441", [(1, "L/R", "i"), (2, "WS", "i"), (3, "SCK", "i"), (5, "VDD", "P"), (6, "GND", "P")],
                  [(4, "SD", "o")]),
    "HUB": custom("USB2_Hub", [(1, "VCC", "P"), (2, "GND", "P"), (3, "UP_D+", "b"), (4, "UP_D-", "b")],
                  [(5, "DN1_D+", "b"), (6, "DN1_D-", "b"), (7, "DN2_D+", "b"), (8, "DN2_D-", "b")]),
    "USBC": custom("USB_C_Receptacle", [(1, "VBUS", "p"), (2, "GND", "p"), (3, "CC1", "p"), (4, "CC2", "p")],
                   [(5, "D+", "p"), (6, "D-", "p"), (7, "SBU1", "p"), (8, "SBU2", "p")], prefix="J"),
    "J_BAT": conn("Battery_1S2P", ["BAT+", "BAT-"]), "J_SW": conn("Battery_Switch", ["A", "B"]),
    "J_PIR": conn("PIR_AM312", ["VCC", "OUT", "GND"]), "J_RADAR": conn("Radar_LD2410C", ["VCC", "GND", "OUT", "TX", "RX"]),
    "J_ALS": conn("ALS_BH1750", ["VCC", "GND", "SCL", "SDA"]), "J_PT": conn("PanTilt_Servos", ["5V", "GND", "PAN", "TILT"]),
    "J_SPK": conn("Speaker_4R", ["SPK+", "SPK-"]), "J_IR": conn("IR_LEDs_2x850nm", ["A", "K"]),
    "J_IRCUT": conn("IR_Cut_Filter", ["CTRL", "GND"]), "J_PIUSB": conn("Pi_USB_Pads", ["D+", "D-", "GND"]),
    "J_BAR": conn("Light_Bars_SK6812", ["5V", "DIN", "GND"]), "J_FL": conn("Flash_LED_1W", ["A", "K"]),
}

# --------------------------------------------------------------------------
# Circuit. (ref, symbol, value, {pin: net}, note for the BOM)
# Pins are named for box symbols and numbered for stock symbols.
# FETs: 1 gate, 2 source, 3 drain. Schottky: 1 cathode, 2 anode.
# --------------------------------------------------------------------------
def R(ref, value, a, b, note=""):
    return (ref, "R", value, {"1": a, "2": b}, note)


def C(ref, value, a, b, pol=False, note=""):
    return (ref, "CP" if pol else "C", value, {"1": a, "2": b}, note)


def flag(ref, net):
    return (ref, "FLAG", "PWR_FLAG", {"1": net}, "")


def dock(n, tag, r0, q0, c0, hub_port):
    """One Dock-50 port: USB-C, CC pull-downs and sense, I2C on SBU, and a
    back-to-back P-FET pair so 5 V can be sent out but never flows back in."""
    t = tag
    return [
        (f"J{n}", "USBC", f"Dock {t}", {"VBUS": f"VBUS_{t}", "GND": "GND", "CC1": f"CC_{t}", "CC2": f"CC2_{t}",
                                        "D+": f"DOCK_{t}_DP", "D-": f"DOCK_{t}_DM", "SBU1": f"SBU1_{t}", "SBU2": f"SBU2_{t}"},
         "USB-C 2.0 receptacle, 16 pin"),
        R(f"R{r0}", "5.1k", f"CC_{t}", "GND"), R(f"R{r0 + 1}", "5.1k", f"CC2_{t}", "GND"),
        R(f"R{r0 + 2}", "10k", f"CC_{t}", f"CC_{t}_SENSE"), C(f"C{c0}", "100n", f"CC_{t}_SENSE", "GND"),
        R(f"R{r0 + 3}", "1k", f"SBU1_{t}", "SDA"), R(f"R{r0 + 4}", "1k", f"SBU2_{t}", "SCL"),
        (f"Q{q0}", "PMOS", "AO3401A", {"1": f"GATE_{t}", "2": f"SWMID_{t}", "3": "+5V"}, "P-MOSFET SOT-23, 30 V 4 A"),
        (f"Q{q0 + 1}", "PMOS", "AO3401A", {"1": f"GATE_{t}", "2": f"SWMID_{t}", "3": f"VBUS_{t}"}, "P-MOSFET SOT-23"),
        R(f"R{r0 + 5}", "100k", f"GATE_{t}", f"SWMID_{t}"),
        (f"Q{q0 + 2}", "NMOS", "2N7002", {"1": f"DOCK_{t}_EN", "2": "GND", "3": f"GATE_{t}"}, "N-MOSFET SOT-23"),
        R(f"R{r0 + 6}", "100k", f"DOCK_{t}_EN", "GND"),
    ]


def flash(n, r0, q, j):
    return [
        (f"J{j}", "J_FL", f"Flash {n}", {"A": "+5V", "K": f"FL{n}_K"}, "1 W white LED, 350 mA"),
        R(f"R{r0}", "4.7R 2W", f"FL{n}_K", f"FL{n}_D", "sets about 350 mA"),
        (f"Q{q}", "NMOS", "AO3400A", {"1": f"FL{n}_G", "2": "GND", "3": f"FL{n}_D"}, "N-MOSFET SOT-23, 30 V 5 A"),
        R(f"R{r0 + 1}", "100R", f"FLASH{n}_PWM", f"FL{n}_G"), R(f"R{r0 + 2}", "100k", f"FL{n}_G", "GND"),
    ]


CIRCUIT = {
    "power": ("Power: battery, charger, rails", [
        ("Battery path", [
            ("J1", "J_BAT", "Battery", {"BAT+": "VBAT_RAW", "BAT-": "GND"}, "1S LiFePO4 pack with protection board"),
            ("F1", "F", "5A", {"1": "VBAT_RAW", "2": "VBAT_F"}, "blade or 1812 fuse"),
            ("J2", "J_SW", "Switch", {"A": "VBAT_F", "B": "VBAT_SW"}, "6 mm latching switch"),
            ("U1", "INA", "INA219", {"VCC": "+3V3", "GND": "GND", "SCL": "SCL", "SDA": "SDA", "VIN+": "VBAT_SW", "VIN-": "VBATT"},
             "current and voltage monitor breakout"),
        ]),
        ("Charger and input OR-ing", [
            ("U2", "CHG", "bq25185", {"DCIN": "CHG_IN", "GND": "GND", "/CE": "GND", "LOAD": "VSYS", "BATT": "VBATT"},
             "Adafruit 6091, set to LiFePO4 3.65 V, 1 A"),
            ("D1", "D", "SS34", {"1": "CHG_IN", "2": "VBUS_T"}, "Schottky 3 A 40 V"),
            ("D2", "D", "SS34", {"1": "CHG_IN", "2": "VBUS_B"}, ""),
            ("D3", "D", "SS34", {"1": "CHG_IN", "2": "VBUS_CHG"}, ""),
            C("C1", "47u 25V", "CHG_IN", "GND", pol=True), C("C2", "470u 10V", "VSYS", "GND", pol=True),
            ("J3", "USBC", "Charge port", {"VBUS": "VBUS_CHG", "GND": "GND", "CC1": "CHG_CC1", "CC2": "CHG_CC2"}, "USB-C receptacle"),
            R("R5", "5.1k", "CHG_CC1", "GND"), R("R6", "5.1k", "CHG_CC2", "GND"),
            flag("FLG1", "CHG_IN"), flag("FLG2", "GND"),
        ]),
        ("Rails", [
            ("U3", "REG3", "S7V8F3", {"VIN": "VSYS", "GND": "GND", "VOUT": "+3V3"}, "Pololu 2122, always on, under 0.1 mA idle"),
            C("C3", "10u", "+3V3", "GND"),
            ("U4", "REG5", "U3V70F5", {"VIN": "VSYS", "GND": "GND", "VOUT": "+5V", "ENABLE": "BOOST_EN"}, "Pololu 2891"),
            C("C4", "470u 10V", "+5V", "GND", pol=True),
            ("Q1", "NMOS", "2N7002", {"1": "BOOST_OFF", "2": "GND", "3": "BOOST_EN"}, "pulls ENABLE low to stop the 5 V rail"),
            R("R1", "100k", "BOOST_OFF", "GND"),
        ]),
        ("Compute rail switch, soft start", [
            ("Q2", "PMOS", "AO3401A", {"1": "PI_GATE", "2": "+5V", "3": "+5V_PI"}, "high side switch for the Pi"),
            R("R2", "100k", "PI_GATE", "+5V"), C("C5", "100n", "PI_GATE", "+5V"),
            R("R3", "10k", "PI_GATE", "PI_GATE_DRV"),
            ("Q3", "NMOS", "2N7002", {"1": "PI_EN", "2": "GND", "3": "PI_GATE_DRV"}, ""),
            R("R4", "100k", "PI_EN", "GND"), C("C6", "220u 10V", "+5V_PI", "GND", pol=True), flag("FLG3", "+5V_PI"),
        ]),
    ]),
    "controller": ("Controller: always-on MCU, PWM, sensors", [
        ("Always-on controller", [
            ("U5", "XIAO", "XIAO ESP32-C6", {"D0": "PIR_OUT", "D1": "CC_T_SENSE", "D2": "CC_B_SENSE", "D3": "PI_EN",
                                              "D4/SDA": "SDA", "D5/SCL": "SCL", "D6/TX": "ESP_TX", "D7/RX": "ESP_RX",
                                              "D8": "LED_DATA", "D9": "BOOST_OFF", "D10": "RADAR_OUT", "3V3": "+3V3", "GND": "GND"},
             "Seeed XIAO ESP32-C6, fed on its 3V3 pin"),
            C("C7", "100n", "+3V3", "GND"), R("R7", "4.7k", "SDA", "+3V3"), R("R8", "4.7k", "SCL", "+3V3"),
            R("R9", "1k", "ESP_TX", "PI_RXD", "limits back-feed into an unpowered Pi"),
            R("R10", "1k", "PI_TXD", "ESP_RX"),
        ]),
        ("PWM expander", [
            ("U6", "PCA", "PCA9685", {"GND": "GND", "OE": "GND", "SCL": "SCL", "SDA": "SDA", "VCC": "+3V3", "V+": "+5V",
                                      "PWM0": "SERVO1_PAN", "PWM1": "SERVO1_TILT", "PWM2": "SERVO2_PAN", "PWM3": "SERVO2_TILT",
                                      "PWM4": "FLASH1_PWM", "PWM5": "FLASH2_PWM", "PWM6": "DOCK_T_EN", "PWM7": "DOCK_B_EN"},
             "16 channel I2C PWM breakout, outputs low at power-up"),
            ("J7", "J_PT", "Pan-tilt, camera", {"5V": "+5V", "GND": "GND", "PAN": "SERVO1_PAN", "TILT": "SERVO1_TILT"}, "two servos"),
            ("J8", "J_PT", "Pan-tilt, solar", {"5V": "+5V", "GND": "GND", "PAN": "SERVO2_PAN", "TILT": "SERVO2_TILT"}, "two servos"),
        ]),
        ("Sensors", [
            ("J4", "J_PIR", "PIR", {"VCC": "+3V3", "OUT": "PIR_OUT", "GND": "GND"}, "AM312"),
            ("J5", "J_RADAR", "mmWave radar", {"VCC": "+5V", "GND": "GND", "OUT": "RADAR_OUT"}, "HLK-LD2410C, 3.3 V logic"),
            ("J6", "J_ALS", "Light sensor", {"VCC": "+3V3", "GND": "GND", "SCL": "SCL", "SDA": "SDA"}, "BH1750"),
        ]),
    ]),
    "compute": ("Compute: Raspberry Pi, audio, IR, USB", [
        ("Raspberry Pi Zero 2 W", [
            ("J9", "PI", "Pi 40 pin", {"3V3": "+3V3_PI", "5V": "+5V_PI", "5V.4": "+5V_PI", "GND": "GND", "GND.6": "GND",
                                        "GND.14": "GND", "GND.20": "GND", "GND.25": "GND", "GND.30": "GND", "GND.34": "GND",
                                        "GND.39": "GND", "GPIO14/TXD": "PI_TXD", "GPIO15/RXD": "PI_RXD",
                                        "GPIO18/PCM_CLK": "I2S_BCLK", "GPIO19/PCM_FS": "I2S_LRCLK", "GPIO20/PCM_DIN": "I2S_MIC",
                                        "GPIO21/PCM_DOUT": "I2S_AMP", "GPIO23": "IRCUT", "GPIO24": "IR_EN", "GPIO25": "AMP_SD"},
             "2x20 socket"),
        ]),
        ("Audio", [
            ("U7", "AMP", "MAX98357A", {"LRC": "I2S_LRCLK", "BCLK": "I2S_BCLK", "DIN": "I2S_AMP", "SD": "AMP_SD", "GND": "GND",
                                        "VIN": "+5V_PI", "OUT+": "SPK_P", "OUT-": "SPK_N"}, "I2S class D amplifier breakout"),
            ("J10", "J_SPK", "Speaker", {"SPK+": "SPK_P", "SPK-": "SPK_N"}, "28 mm 4 ohm 3 W"),
            ("U8", "MIC", "INMP441", {"L/R": "GND", "WS": "I2S_LRCLK", "SCK": "I2S_BCLK", "SD": "I2S_MIC", "VDD": "+3V3_PI", "GND": "GND"},
             "I2S microphone breakout"),
            C("C8", "100u 10V", "+5V_PI", "GND", pol=True),
        ]),
        ("IR illumination and filter", [
            R("R13", "22R 0.5W", "+5V_PI", "IR_A", "about 90 mA through two LEDs in series"),
            ("J11", "J_IR", "IR LEDs", {"A": "IR_A", "K": "IR_K"}, "two 850 nm LEDs in series"),
            ("Q4", "NMOS", "AO3400A", {"1": "IR_G", "2": "GND", "3": "IR_K"}, ""),
            R("R11", "100R", "IR_EN", "IR_G"), R("R12", "100k", "IR_G", "GND"),
            ("J12", "J_IRCUT", "IR-cut", {"CTRL": "IRCUT", "GND": "GND"}, "camera board filter control"),
        ]),
        ("USB to the docks", [
            ("U9", "HUB", "USB 2.0 hub", {"VCC": "+5V_PI", "GND": "GND", "UP_D+": "PI_USB_DP", "UP_D-": "PI_USB_DM",
                                          "DN1_D+": "DOCK_T_DP", "DN1_D-": "DOCK_T_DM", "DN2_D+": "DOCK_B_DP", "DN2_D-": "DOCK_B_DM"},
             "4 port hub breakout"),
            ("J13", "J_PIUSB", "Pi USB pads", {"D+": "PI_USB_DP", "D-": "PI_USB_DM", "GND": "GND"}, "to the Pi's USB data pads"),
        ]),
    ]),
    "docks": ("Docks and lights", [
        ("Dock, top", dock(14, "T", 14, 5, 9, 1)),
        ("Dock, bottom", dock(15, "B", 21, 8, 10, 2)),
        ("Light bars", [
            ("U10", "BUF", "74AHCT1G125", {"1": "GND", "2": "LED_DATA", "3": "GND", "4": "LED_Y", "5": "+5V"}, "3.3 V to 5 V level shifter"),
            C("C11", "100n", "+5V", "GND"), R("R28", "330R", "LED_Y", "LED_DIN"),
            ("J16", "J_BAR", "Light bars", {"5V": "+5V", "DIN": "LED_DIN", "GND": "GND"}, "two 8 LED SK6812 RGBW sticks, chained"),
            C("C12", "1000u 10V", "+5V", "GND", pol=True),
        ]),
        ("Flash LEDs", flash(1, 29, 11, 17) + flash(2, 32, 12, 18)),
    ]),
}

# --------------------------------------------------------------------------
# Writer
# --------------------------------------------------------------------------
HORIZONTAL = {"R", "C", "CP", "F"}       # stock two-pin parts drawn on their side
CELL = {"R": (56, 16), "C": (56, 16), "CP": (56, 16), "F": (56, 16), "D": (56, 16), "FLAG": (30, 22),
        "PMOS": (58, 44), "NMOS": (58, 44), "BUF": (84, 50)}


def pin_xy(sym, num, x, y, rot):
    p = sym.pins[num]
    if rot == 0:
        px, py, out = x + p["x"], y - p["y"], p["a"] + 180
    else:  # 90
        px, py, out = x - p["y"], y - p["x"], p["a"] + 270
    out %= 360
    return round(px, 4), round(py, 4), out


LABEL = {0: (0, "left"), 180: (180, "right"), 90: (90, "left"), 270: (270, "right")}


def sheet_text(key, title, groups, root_uuid, sheet_uuid, page, paper="A3"):
    path = f"/{root_uuid}/{sheet_uuid}"
    used, body, nets = {}, [], {}
    width = 594.0 if paper == "A2" else 420.0
    x0, y0 = 25.0, 30.0
    cx, cy, row_h = x0, y0, 0.0
    for gname, parts in groups:
        if cx > x0:
            cx, cy, row_h = x0, cy + row_h + 10, 0.0
        body.append(f'(text "{gname}" (exclude_from_sim no) (at {cx:.2f} {cy - 4:.2f} 0) '
                    f'(effects (font (size 2.2 2.2) bold) (justify left bottom)) (uuid "{uid(key + gname)}"))')
        cy += 4
        for ref, sk, value, pins, _note in parts:
            sym = SYMS[sk]
            used[sym.lib_id] = sym
            rot = 90 if sk in HORIZONTAL else 0
            w, h = CELL.get(sk, (2 * sym.half_w + 78, 2 * sym.half_h + 14))
            if cx + w > width - 15:
                cx, cy, row_h = x0, cy + row_h + 6, 0.0
            x, y = snap(cx + w / 2), snap(cy + h / 2)
            row_h = max(row_h, h)
            cx += w
            numbered = {(sym.by_name.get(k, k)): v for k, v in pins.items()}
            for k in numbered:
                if k not in sym.pins:
                    raise SystemExit(f"{ref}: no pin {k} on {sk}")
            ref_at = (x, snap(y - sym.half_h - 2 * G)) if sk not in ("PMOS", "NMOS") else (x + 9, y - 2)
            val_at = (x, snap(y + sym.half_h + 2 * G)) if sk not in ("PMOS", "NMOS") else (x + 9, y + 2)
            if rot == 90:
                ref_at, val_at = (x, y - 3.4), (x, y + 3.8)
            fa = 90 if rot == 90 else 0
            hide_ref = " hide" if sk == "FLAG" else ""
            pin_lines = " ".join(f'(pin "{n}" (uuid "{uid(key + ref + n)}"))' for n in sym.pins)
            body.append(
                f'(symbol (lib_id "{sym.lib_id}") (at {x} {y} {rot}) (unit 1) (exclude_from_sim no) (in_bom yes) '
                f'(on_board yes) (dnp no) (uuid "{uid(key + ref)}")\n'
                f'  (property "Reference" "{ref}" (at {ref_at[0]:.2f} {ref_at[1]:.2f} {fa}) (effects (font (size 1.27 1.27)){hide_ref}))\n'
                f'  (property "Value" "{value}" (at {val_at[0]:.2f} {val_at[1]:.2f} {fa}) (effects (font (size 1.27 1.27)){hide_ref}))\n'
                f'  (property "Footprint" "" (at {x} {y} 0) {HIDE})\n'
                f'  (property "Datasheet" "" (at {x} {y} 0) {HIDE})\n'
                f"  {pin_lines}\n"
                f'  (instances (project "{PROJECT}" (path "{path}" (reference "{ref}") (unit 1)))))'
            )
            for num in sym.pins:
                px, py, out = pin_xy(sym, num, x, y, rot)
                net = numbered.get(num)
                if net is None:
                    body.append(f'(no_connect (at {px} {py}) (uuid "{uid(key + ref + num + "nc")}"))')
                    continue
                nets.setdefault(net, []).append(f"{ref}.{sym.pins[num]['name'] if sym.pins[num]['name'] not in ('~', '') else num}")
                ex = round(px + STUB * math.cos(math.radians(out)), 4)
                ey = round(py - STUB * math.sin(math.radians(out)), 4)
                ang, just = LABEL[out]
                body.append(f'(wire (pts (xy {px} {py}) (xy {ex} {ey})) (stroke (width 0) (type default)) '
                            f'(uuid "{uid(key + ref + num + "w")}"))')
                body.append(
                    f'(global_label "{net}" (shape passive) (at {ex} {ey} {ang}) (fields_autoplaced yes) '
                    f'(effects (font (size 1.27 1.27)) (justify {just})) (uuid "{uid(key + ref + num + "l")}")\n'
                    f'  (property "Intersheetrefs" "${{INTERSHEET_REFS}}" (at 0 0 0) {HIDE}))'
                )
    libs = "\n".join(s.block for s in used.values())
    text = (
        f'(kicad_sch (version 20231120) (generator "slate_gen") (generator_version "8.0") (uuid "{sheet_uuid}") (paper "{paper}")\n'
        f'(title_block (title "{title}") (rev "A") (company "Nurby open camera") (comment 1 "Carrier board, generated by gen_schematic.py"))\n'
        f"(lib_symbols\n{libs}\n)\n" + "\n".join(body) + "\n)\n"
    )
    return text, nets


def main():
    root_uuid = uid("root")
    all_nets, boxes, bom = {}, [], []
    for page, (key, (title, groups)) in enumerate(CIRCUIT.items(), start=2):
        su = uid("sheet-" + key)
        text, nets = sheet_text(key, title, groups, root_uuid, su, page, paper="A2" if key in ("docks", "power") else "A3")
        (HERE / f"{key}.kicad_sch").write_text(text)
        for n, pins in nets.items():
            all_nets.setdefault(n, []).extend(pins)
        for _g, parts in groups:
            bom += [(r, v, note, key) for r, _s, v, _p, note in parts if not r.startswith("FLG")]
        bx, by = 30 + (page - 2) * 62, 40
        boxes.append(
            f'(sheet (at {bx} {by}) (size 50 22) (fields_autoplaced yes) (stroke (width 0.1524) (type solid)) '
            f'(fill (color 0 0 0 0.0)) (uuid "{su}")\n'
            f'  (property "Sheetname" "{title.split(":")[0]}" (at {bx} {by - 0.8} 0) (effects (font (size 1.6 1.6)) (justify left bottom)))\n'
            f'  (property "Sheetfile" "{key}.kicad_sch" (at {bx} {by + 22.8} 0) (effects (font (size 1.27 1.27)) (justify left top)))\n'
            f'  (instances (project "{PROJECT}" (path "/{root_uuid}" (page "{page}")))))'
        )
    notes = [
        "NURBY CAMERA CARRIER, REV A",
        "",
        "1. Battery is a 1S LiFePO4 pack, 3.2 V nominal, behind its own protection board.",
        "2. VSYS comes from the charger's power path and never exceeds 4.5 V.",
        "3. +3V3 is always on and feeds the controller. +5V is made on demand: BOOST_OFF high stops it.",
        "4. +5V_PI is switched by Q2. PI_EN high starts the Pi. R3 and C5 slow the edge to limit inrush.",
        "5. Each dock can take power in through a Schottky (D1, D2) or send 5 V out through a",
        "   back-to-back P-FET pair. With the pair off, an external source cannot reach the 5 V rail.",
        "6. Dock CC pins carry 5.1 k pull-downs, so an ordinary USB-C charger will supply power.",
        "7. I2C runs out to each dock on SBU1 (SDA) and SBU2 (SCL) through 1 k.",
        "8. UART between controller and Pi has 1 k in each line so a sleeping Pi is not back-fed.",
        "9. Keep the 5 V rail under about 1.5 A total. The charger's load path is good for 3 A peaks.",
    ]
    note_text = "\\n".join(notes)
    root = (
        f'(kicad_sch (version 20231120) (generator "slate_gen") (generator_version "8.0") (uuid "{root_uuid}") (paper "A4")\n'
        f'(title_block (title "Nurby camera carrier") (rev "A") (company "Nurby open camera"))\n(lib_symbols)\n'
        f'(text "{note_text}" (exclude_from_sim no) (at 30 80 0) (effects (font (size 2 2)) (justify left top)) (uuid "{uid("notes")}"))\n'
        + "\n".join(boxes)
        + '\n(sheet_instances (path "/" (page "1")))\n)\n'
    )
    (HERE / f"{PROJECT}.kicad_sch").write_text(root)

    # Project library, so the box symbols can be edited in KiCad
    blocks = [sym.block.replace('(symbol "slate:', '(symbol "', 1) for sym in SYMS.values() if sym.lib_id.startswith("slate:")]
    (HERE / "lib" / "slate.kicad_sym").write_text(
        '(kicad_symbol_lib (version 20231120) (generator "slate_gen") (generator_version "8.0")\n' + "\n".join(blocks) + "\n)\n")
    (HERE / "sym-lib-table").write_text(
        '(sym_lib_table\n  (version 7)\n  (lib (name "slate")(type "KiCad")(uri "${KIPRJMOD}/lib/slate.kicad_sym")(options "")(descr "Nurby carrier modules"))\n)\n')
    pro = HERE / f"{PROJECT}.kicad_pro"
    if not pro.exists():
        pro.write_text(json.dumps({"meta": {"filename": f"{PROJECT}.kicad_pro", "version": 1}}, indent=2) + "\n")
    (HERE / "out").mkdir(exist_ok=True)
    (HERE / "out" / "nets.json").write_text(json.dumps({k: sorted(v) for k, v in sorted(all_nets.items())}, indent=1))

    out = HERE / "out"
    out.mkdir(exist_ok=True)
    lines = ["# Netlist, carrier rev A", "", "Generated by `gen_schematic.py`. One line per net.", "", "| Net | Pins |", "|---|---|"]
    for n in sorted(all_nets):
        lines.append(f"| `{n}` | {', '.join(sorted(all_nets[n]))} |")
    (out / "NETLIST.md").write_text("\n".join(lines) + "\n")
    lines = ["# Parts, carrier rev A", "", "| Ref | Value | Sheet | Notes |", "|---|---|---|---|"]
    key = lambda r: (re.sub(r"\d", "", r[0]), int(re.sub(r"\D", "", r[0]) or 0))  # noqa: E731
    for r, v, note, sheet in sorted(bom, key=key):
        lines.append(f"| {r} | {v} | {sheet} | {note} |")
    (out / "BOM.md").write_text("\n".join(lines) + "\n")
    single = {n: p for n, p in all_nets.items() if len(p) < 2}
    print(f"sheets {len(CIRCUIT)}, parts {len(bom)}, nets {len(all_nets)}")
    if single:
        raise SystemExit(f"nets with a single pin: {single}")


if __name__ == "__main__":
    main()
