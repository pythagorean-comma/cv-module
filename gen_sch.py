"""Draw the schematic for the design in design.py.

The sheet is laid out the way `floorplan.py` lays out the board, because they
are answering the same question and disagreeing would help nobody: six audio
channel rows across the top, the six CV filters in a band beneath them, and the
shared block -- reference, logic buffer, rails and the two ground stars -- along
the bottom. One row is drawn in local coordinates and instantiated six times,
which is the mixer's own arrangement and is what makes the six channels
identical by construction rather than by proofreading.

**Why this exists at all**, given that CLAUDE.md used to say not to synthesise a
`.kicad_sch`: without a schematic, `verify.py` compares `design.py` to a netlist
written from `design.py`, which cannot catch a transcription error because there
is no transcription. With one, `kicad-cli` parses geometry -- wires meeting at
coordinates -- and the comparison becomes real. `gen_sch.py` in the mixer exists
for exactly that reason and its `verify.py` is the better for it.

Everything is drawn with real wires inside a block and travels by global label
between blocks. A wire from a loom connector on the far left to a VCA in the
middle would cross four other blocks to say something the label says better.

Run `python3 gen_sch.py`, then `verify.py --schematic` to close the loop.
"""

import pathlib

import design as circuit
import contract.socket as socket
from toolchain.kisch import Schematic

OUT = pathlib.Path(__file__).resolve().parent / "out"
SHEET = OUT / "cv-module.kicad_sch"

# 1.27 mm is eeschema's grid and every coordinate here is a multiple of it.
# Off-grid pins do not connect and the drawing does not say so.
G = 1.27


def grid(value):
    return round(value / G) * G


# **KiCad's Device:R and Device:C are drawn vertically at angle 0.** Naming the
# two orientations is not decoration: assuming angle 0 meant horizontal put
# every feedback resistor back in its amplifier's own column, which is the
# fault that merged IOUT{n} with SIN{n} on all six channels. A constant cannot
# be got backwards silently the way a bare 0 can.
VERT, HORIZ = 0, 90


# Row geometry. The audio rows are on a 38.1 mm pitch, which was set by the
# height of a relay symbol and is kept now that the relays are gone: the pitch
# has to clear _feedback()'s stepped rails and the +IN drops either side of an
# amplifier, and shrinking it is a geometry change to check rather than a
# tidy-up to make. The CV rows are tighter because an MFB stage is not tall.
#
# **A row pitch must not equal any part offset used inside the row.** CV_PITCH was
# 25.4 while C{n}42 sits at y - 25.4, which put every channel's C{n}42 exactly on
# the previous channel's row and merged all six VC nets into one. It is the least
# obvious of the geometry faults because both numbers are individually sensible
# and the collision only exists in their difference; check a new offset against
# the pitch before adding it.
AUDIO_Y0, AUDIO_PITCH = 38.1, 38.1
CV_Y0, CV_PITCH = 230 * G, 30 * G
# The envelope rows sit below the CV rows and above the shared block, on the
# same 30 * G pitch: a rectifier row is two amplifiers wide but no taller than
# an MFB stage.
ENV_Y0, ENV_PITCH = 420 * G, 30 * G
SHARED_Y = 620 * G

# Column origins along an audio row, in the order the signal runs.
# Every one is an exact multiple of G: kisch refuses anything else, because a
# pin a tenth of a millimetre off the grid does not connect and the drawing
# does not say so.
X_LOOM, X_FRONT, X_BLOCK = 20 * G, 44 * G, 88 * G
X_RIN, X_RC = 108 * G, 205 * G
X_VCA, X_IV, X_SERVO = 234 * G, 276 * G, 330 * G

# Columns along a CV row.
CX_IN, CX_INNER, CX_AMP, CX_OUT = 520 * G, 560 * G, 600 * G, 640 * G

# Columns along an envelope row, in signal order: the half-wave stage's input
# resistor, its amplifier, the two diodes, the feedback resistor, then the
# summing stage's two inputs and its amplifier.
EX_IN, EX_A, EX_DIODE = 20 * G, 60 * G, 100 * G
EX_FB, EX_SUM, EX_B = 140 * G, 180 * G, 230 * G


def register(sch):
    """Every symbol this sheet uses, from design.LIBS.

    The patch callback lives in design.py rather than here, because
    gen_project.py has to write the project library through the *same* one --
    the mixer's gen_project docstring says why: the schematic embeds its own
    copy of every symbol, so a library patched differently passes ERC, passes
    verify.py, and shows up only as a mismatch when somebody opens the project.
    """
    for lib_id, (nick, libname, symname, rename) in circuit.LIBS.items():
        sch.use(nick, libname, symname, rename=rename,
                patch=circuit.patch_symbol)


def _feedback(sch, inv, out, parts, above=True):
    """Wire one or more parts in parallel between an amplifier's -IN and output.

    Each part gets its own pair of vertical rails, stepped 2.54 mm further out
    than the last, so no two parts' routes ever share an x. Overlap *within* a
    part's own net is harmless -- both rails carry the node they start from --
    and that is the only overlap this arrangement can produce.

    Stacking two feedback parts in the amplifier's own column, which is what
    this replaces, put C{n}21's route straight through R{n}21's pins. The sheet
    looked fine; KiCad merged IOUT, SIN, SVN, SRV and CVN across all six
    channels into a single 254-node net.
    """
    for index, part in enumerate(parts):
        left = inv[0] - (index + 1) * 2.54
        right = out[0] + (index + 1) * 2.54
        one, two = part.pin("1"), part.pin("2")
        near, far = (one, two) if one[0] <= two[0] else (two, one)
        sch.wire(inv, (left, inv[1]), (left, near[1]), near)
        sch.wire(far, (right, far[1]), (right, out[1]), out)


def _r(sch, ref, x, y, angle=0):
    part = circuit.PARTS[ref]
    return sch.place(ref, "Device:R", part.value, x, y,
                     footprint=part.footprint, angle=angle)


def _c(sch, ref, x, y, angle=0):
    part = circuit.PARTS[ref]
    return sch.place(ref, "Device:C", part.value, x, y,
                     footprint=part.footprint, angle=angle)


def _gnd(sch, x, y, net="MAGND"):
    lib = "power:GNDD" if net == "MDGND" else "power:GNDA"
    return sch.power(lib, x, y, value=net)


def _drop(sch, part, pin, net, dy=7.62):
    """Take a pin down to a ground symbol. The commonest gesture on the sheet."""
    x, y = part.pin(pin)
    sch.wire((x, y), (x, y + dy))
    _gnd(sch, x, y + dy, net)


def _drop_out(sch, part, pin, net, dx=6.35, dy=6.35):
    """Route a pin clear of its neighbours, then down to ground.

    A straight drop from a pin in the middle of a package's row passes through
    the pins below it, and eeschema reads a pin sitting mid-wire as connected --
    silently. kisch.auto_junctions() refuses to render that, which is how the
    first three cases were found: the spare VCA cell's I_IN/I_OUT either side of
    its V_C, and the MAX6126's GNDS with an internally-connected pin beneath it.

    **The fourth case is worse and auto_junctions() could not see it.** An
    op-amp's +IN and -IN sit in the same column 5.08 mm apart, so dropping +IN
    to ground by 5.08 lands its *wire end* exactly on -IN -- a legal junction,
    not a stranded pin. Every I-V stage had its two inputs shorted, MAGND merged
    with IOUT1, and 34 nets collapsed into one. Nothing on the sheet looked
    wrong; only KiCad's own netlist said so, which is the entire argument for
    generating the schematic rather than stopping at design.py.
    """
    x, y = part.pin(pin)
    sch.wire((x, y), (x + dx, y), (x + dx, y + dy))
    _gnd(sch, x + dx, y + dy, net)

# The op-amp +IN drops use dx = -22.86 rather than the -5.08 that would clear
# the pin beside them. -5.08 is where _feedback() puts its second rail, so the
# two shared a column: C{n}21 ended up shorted end to end and MAGND merged into
# IOUT1 across all six channels. Offsets on this sheet have to clear each
# other, not just the pins.


def _to_inverting(sch, start, inv, net=None):
    """Bring a signal to an amplifier's -IN, and name the node.

    **An op-amp unit here draws +IN 5.08 mm ABOVE -IN in the same column**, so
    the obvious route -- along at the source part's y to the amplifier's x, then
    down into -IN -- runs the whole way through +IN. eeschema reads a pin
    sitting mid-wire as connected, so the input node acquires MAGND and the
    stage becomes a follower with its feedback grounded. It measures as broken
    and it draws as correct.

    The order is what fixes it: vertical first, in the source part's own column,
    then horizontally into -IN. That was already the front end's shape and is
    why FEN{n} was the one summing junction that formed. The servo, the CV
    filter and the reference inverter each had the two moves the other way
    round, which is 18 of the 45 breaks and all of MAGND's excess membership.

    The vertical crosses the +IN ground route on the way past. A crossing with
    no shared endpoint is deliberately not a connection -- it is the rule
    _between() implements and the rule eeschema implements -- and the front end
    has always had this one.
    """
    sch.wire(start, (start[0], inv[1]), inv)
    if net:
        sch.label(net, start[0], inv[1])


def _leave_down(sch, part, pin, dy, dx):
    """Take a pin vertically clear of its row, then sideways. Returns the end.

    The SSI2164 puts GND on pin 8 and V- on pin 9 **2.54 mm apart on the same
    y**, so any horizontal route from one runs through the other. Leaving
    vertically first, on each pin's own column, is the only way out of that --
    and it is the general answer for a pin whose neighbour shares its row.
    """
    x, y = part.pin(pin)
    sch.wire((x, y), (x, y + dy), (x + dx, y + dy))
    return (x + dx, y + dy)


def audio_row(sch, n, y):
    """One channel's audio path: loom, front end, coupling, R_IN, VCA, I-V, servo.

    The order along the row is the order in the module docstring of design.py,
    and it runs left to right with one exception: IVOUT{n} leaves by label
    rather than by a wire back across the whole row. **It leaves to a relay
    contact, not to the loom** -- SIN{n} is what the mixer's wiper sees and the
    bypass changeover decides which of the two it is connected to, so the
    return path is drawn in the fail-safe block. See design.fail_safe(). There used to be a
    second, the pad's four resistors stacked vertically because a 2-bit selector
    is a column, and the two relay symbols beside them are why the row pitch is
    what it is. See design.pad_benefit().
    """
    # -- loom ------------------------------------------------------------
    j = sch.place(f"J{n}", "Connector_Generic:Conn_01x02",
                  circuit.PARTS[f"J{n}"].value, X_LOOM, y,
                  footprint=circuit.PARTS[f"J{n}"].footprint)
    for pin, net in (("1", f"PIN{n}"), ("2", f"SIN{n}")):
        x, py = j.pin(pin)
        sch.wire((x, py), (x + 5.08, py))
        sch.label(net, x + 5.08, py)

    # -- front end: inverting unity --------------------------------------
    package, unit = circuit.SECTIONS[("front", n)]
    amp = sch.place(package, "cv:OPA1644", circuit.OPAMP,
                    X_FRONT + 20.32, y, footprint=circuit.PARTS[package].footprint,
                    unit="ABCD".index(unit) + 1)
    r01 = _r(sch, f"R{n}01", X_FRONT, y - 6 * G, angle=HORIZ)
    r02 = _r(sch, f"R{n}02", X_FRONT + 20.32, y - 14 * G, angle=HORIZ)

    ax, ay = r01.pin("1")
    sch.wire((ax - 7.62, ay), (ax, ay))
    sch.label(f"PIN{n}", ax - 7.62, ay)

    inv = amp.pin(str(circuit.OPAMP_UNITS[unit][1]))
    out = amp.pin(str(circuit.OPAMP_UNITS[unit][0]))
    _to_inverting(sch, r01.pin("2"), inv, f"FEN{n}")
    _feedback(sch, inv, out, (r02,))
    ox, oy = out
    sch.wire((ox, oy), (ox + 7.62, oy))
    sch.label(f"BUF{n}", ox + 7.62, oy)
    # non-inverting to MAGND
    _drop_out(sch, amp, str(circuit.OPAMP_UNITS[unit][2]), "MAGND",
              dx=-22.86, dy=15.24)

    # -- coupling into the VCA -------------------------------------------
    c01 = _c(sch, f"C{n}01", X_BLOCK, y, angle=VERT)
    cx, cy = c01.pin("1")
    sch.wire((cx, cy - 7.62), (cx, cy))
    sch.label(f"BUF{n}", cx, cy - 7.62)
    dx, dy = c01.pin("2")
    sch.wire((dx, dy), (dx, dy + 5.08))
    sch.label(f"CPL{n}", dx, dy + 5.08)

    # -- R_IN -------------------------------------------------------------
    # Four stacked resistors and two relay symbols were here, which is what
    # made the audio rows 38.1 mm apart. See design.pad_benefit().
    r11 = _r(sch, f"R{n}11", X_RIN, y, angle=HORIZ)
    px, py = r11.pin("1")
    sch.wire((px - 5.08, py), (px, py))
    sch.label(f"CPL{n}", px - 5.08, py)
    qx, qy = r11.pin("2")
    sch.wire((qx, qy), (qx + 5.08, qy))
    sch.label(f"IIN{n}", qx + 5.08, qy)

    # -- the stability RC ------------------------------------------------
    r15 = _r(sch, f"R{n}15", X_RC, y, angle=90)
    c02 = _c(sch, f"C{n}02", X_RC + 8 * G, y + 12.7, angle=VERT)
    ex, ey = r15.pin("1")
    sch.wire((ex - 6.35, ey), (ex, ey))
    sch.label(f"IIN{n}", ex - 6.35, ey)
    bx, by = r15.pin("2")
    cx, cy = c02.pin("1")
    sch.wire((bx, by), (cx, by), (cx, cy))
    sch.label(f"RCJ{n}", cx, by)
    _drop(sch, c02, "2", "MAGND", dy=5.08)

    # -- the VCA cell ----------------------------------------------------
    vca_ref, cell = circuit.VCA_CELL[n]
    if n in (1, 4):                      # one symbol per package, at its first
        v = sch.place(vca_ref, "cv:SSI2164", circuit.VCA, X_VCA, y + 19.05,
                      footprint=circuit.PARTS[vca_ref].footprint)
        _vca_cache[vca_ref] = v
    v = _vca_cache[vca_ref]
    pins = circuit.VCA_CHANNEL_PINS[cell]
    for role, net in (("IIN", f"IIN{n}"), ("IOUT", f"IOUT{n}"),
                      ("VC", f"VC{n}")):
        px, py = v.pin(str(pins[role]))
        side = -5.08 if px < v.pin(str(circuit.VCA_PINS["GND"]))[0] else 5.08
        sch.wire((px, py), (px + side, py))
        sch.label(net, px + side, py)

    # -- I-V -------------------------------------------------------------
    package, unit = circuit.SECTIONS[("iv", n)]
    iv = sch.place(package, "cv:OPA1644", circuit.OPAMP, X_IV + 20.32, y,
                   footprint=circuit.PARTS[package].footprint,
                   unit="ABCD".index(unit) + 1)
    inv = iv.pin(str(circuit.OPAMP_UNITS[unit][1]))
    out = iv.pin(str(circuit.OPAMP_UNITS[unit][0]))
    r21 = _r(sch, f"R{n}21", X_IV + 20.32, y - 12 * G, angle=HORIZ)
    c21 = _c(sch, f"C{n}21", X_IV + 20.32, y - 18 * G, angle=HORIZ)
    sch.wire((inv[0] - 7.62, inv[1]), inv)
    sch.label(f"IOUT{n}", inv[0] - 7.62, inv[1])
    _feedback(sch, inv, out, (r21, c21))
    sch.wire(out, (out[0] + 7.62, out[1]))
    sch.label(f"IVOUT{n}", out[0] + 7.62, out[1])
    _drop_out(sch, iv, str(circuit.OPAMP_UNITS[unit][2]), "MAGND",
              dx=-22.86, dy=15.24)

    # -- servo -----------------------------------------------------------
    package, unit = circuit.SECTIONS[("servo", n)]
    sv = sch.place(package, "cv:OPA1644", circuit.OPAMP, X_SERVO + 25.4, y,
                   footprint=circuit.PARTS[package].footprint,
                   unit="ABCD".index(unit) + 1)
    r31 = _r(sch, f"R{n}31", X_SERVO, y - 6 * G, angle=HORIZ)
    c31 = _c(sch, f"C{n}31", X_SERVO + 25.4, y - 12 * G, angle=HORIZ)
    # R{n}32 sits 38 grid clear of the amplifier's *output* column, not in it.
    # At the amplifier's own x its two pins share a row with the output's
    # descent, so the route to the far pin arrived through the near one:
    # R{n}32 was shorted end to end on all six channels, which put SRV{n} and
    # IOUT{n} on one node and hid SRV{n} entirely -- the servo integrator
    # driving the node it is supposed to correct, through nothing. Trap 4 in
    # the other direction: not a part on a pin's row, a pin on a part's row.
    r32 = _r(sch, f"R{n}32", X_SERVO + 38 * G, y + 14 * G, angle=HORIZ)
    ax, ay = r31.pin("1")
    sch.wire((ax - 6.35, ay), (ax, ay))
    sch.label(f"IVOUT{n}", ax - 6.35, ay)
    inv = sv.pin(str(circuit.OPAMP_UNITS[unit][1]))
    out = sv.pin(str(circuit.OPAMP_UNITS[unit][0]))
    _to_inverting(sch, r31.pin("2"), inv, f"SVN{n}")
    _feedback(sch, inv, out, (c31,))
    # The injection resistor leaves the loop and goes back to IOUT{n} by label.
    ex, ey = r32.pin("1")
    sch.wire(out, (out[0], ey), (ex, ey))
    sch.label(f"SRV{n}", out[0], ey)
    fx, fy = r32.pin("2")
    sch.wire((fx, fy), (fx + 5.08, fy))
    sch.label(f"IOUT{n}", fx + 5.08, fy)
    _drop_out(sch, sv, str(circuit.OPAMP_UNITS[unit][2]), "MAGND",
              dx=-22.86, dy=15.24)


_vca_cache = {}


def cv_row(sch, n, y):
    """One channel's CV filter: the 2-pole MFB with the offset summed in.

    Drawn as the datasheet's Figure 10 is drawn -- two input resistors into the
    inner node, one of them from the inverted reference -- because that is what
    it is, and a reader who knows that figure should recognise this.
    """
    package, unit = circuit.SECTIONS[("cv", n)]
    amp = sch.place(package, "cv:OPA1644", circuit.OPAMP, CX_AMP, y,
                    footprint=circuit.PARTS[package].footprint,
                    unit="ABCD".index(unit) + 1)
    r41 = _r(sch, f"R{n}41", CX_IN, y - 5.08, angle=HORIZ)
    r44 = _r(sch, f"R{n}44", CX_IN, y + 5.08, angle=HORIZ)
    r43 = _r(sch, f"R{n}43", CX_INNER + 12.7, y - 5.08, angle=HORIZ)
    r42 = _r(sch, f"R{n}42", CX_INNER + 12.7, y - 17.78, angle=HORIZ)
    c41 = _c(sch, f"C{n}41", CX_INNER, y + 7.62, angle=VERT)
    c42 = _c(sch, f"C{n}42", CX_AMP, y - 25.4, angle=HORIZ)

    for part, net in ((r41, f"LOGO{n}"), (r44, "VREFN")):
        ax, ay = part.pin("1")
        sch.wire((ax - 6.35, ay), (ax, ay))
        sch.label(net, ax - 6.35, ay)

    inner = (CX_INNER, y)
    for part in (r41, r44):
        bx, by = part.pin("2")
        sch.wire((bx, by), (inner[0], by), inner)
    sch.wire(inner, c41.pin("1"))
    _drop(sch, c41, "2", "MAGND", dy=5.08)
    # The inner node gets a stub of its own to carry the name. R{n}41 and R{n}44
    # arrive at y +/- 5.08 and C{n}41 leaves downward, so 6 * G to the left at
    # the node's own y is the one direction that is clear.
    sch.wire(inner, (inner[0] - 6 * G, inner[1]))
    sch.label(f"CVX{n}", inner[0] - 6 * G, inner[1])

    inv = amp.pin(str(circuit.OPAMP_UNITS[unit][1]))
    out = amp.pin(str(circuit.OPAMP_UNITS[unit][0]))
    cx, cy = r43.pin("1")
    sch.wire(inner, (inner[0], cy), (cx, cy))
    _to_inverting(sch, r43.pin("2"), inv, f"CVN{n}")

    # R{n}42 spans the inner node to the output; C{n}42 spans -IN to the
    # output. Different left-hand nodes, so they route independently.
    ex, ey = r42.pin("1")
    fx, fy = r42.pin("2")
    sch.wire(inner, (inner[0], ey), (ex, ey))
    sch.wire((fx, fy), (out[0] + 5.08, fy), (out[0] + 5.08, out[1]), out)
    _feedback(sch, inv, out, (c42,))

    sch.wire(out, (out[0] + 10.16, out[1]))
    sch.label(f"VC{n}", out[0] + 10.16, out[1])
    _drop_out(sch, amp, str(circuit.OPAMP_UNITS[unit][2]), "MAGND",
              dx=-22.86, dy=15.24)


def envelope_row(sch, n, y):
    """One channel's precision full-wave rectifier and its one-pole.

    Every node is named and every part is stubbed to its own label, which is the
    pad's old idiom and the right one here: this row has two amplifiers, two
    diodes and five resistors meeting at four nodes, and a routed version would
    be a wire crossing an op-amp input in three places. The two exceptions are
    the ones with helpers written for exactly this -- `_to_inverting()` into
    each amplifier's -IN, and `_feedback()` for the pair across the second.

    **The diodes are drawn horizontally at angle 0, which puts the cathode on
    the left**, because KiCad's Device:D is drawn with its triangle pointing
    left. design.DIODE_PINS names them so this file never has to know that; the
    labels below are keyed on "A" and "K" and the geometry follows.
    """
    package, unit = circuit.SECTIONS[("env_a", n)]
    lib, value = circuit.package_part(package)
    amp = sch.place(package, lib, value, EX_A, y,
                    footprint=circuit.PARTS[package].footprint,
                    unit="ABCD".index(unit) + 1)
    inv = amp.pin(str(circuit.OPAMP_UNITS[unit][1]))
    out = amp.pin(str(circuit.OPAMP_UNITS[unit][0]))

    r51 = _r(sch, f"R{n}51", EX_IN, y, angle=HORIZ)
    ax, ay = r51.pin("1")
    sch.wire((ax - 6.35, ay), (ax, ay))
    sch.label(f"BUF{n}", ax - 6.35, ay)
    _to_inverting(sch, r51.pin("2"), inv, f"HWN{n}")
    sch.wire(out, (out[0] + 7.62, out[1]))
    sch.label(f"AOUT{n}", out[0] + 7.62, out[1])
    _drop_out(sch, amp, str(circuit.OPAMP_UNITS[unit][2]), "MAGND",
              dx=-22.86, dy=15.24)

    # D{n}51 closes the loop on one polarity, D{n}52 passes the other out to
    # HW{n}. Their cathodes face opposite ways and that is the whole circuit:
    # at angle 0 pin 1 (K) is the left-hand pin, so the labels differ, not the
    # placement.
    for ref, left, right in ((f"D{n}51", f"HWN{n}", f"AOUT{n}"),
                             (f"D{n}52", f"AOUT{n}", f"HW{n}")):
        part = circuit.PARTS[ref]
        dy = -7.62 if ref.endswith("51") else 7.62
        d = sch.place(ref, "Device:D", part.value, EX_DIODE, y + dy,
                      footprint=part.footprint, angle=HORIZ)
        for pin, net in ((str(circuit.DIODE_PINS["K"]), left),
                         (str(circuit.DIODE_PINS["A"]), right)):
            px, py = d.pin(pin)
            side = -5.08 if px < EX_DIODE else 5.08
            sch.wire((px, py), (px + side, py))
            sch.label(net, px + side, py)

    r52 = _r(sch, f"R{n}52", EX_FB, y, angle=HORIZ)
    for pin, net in (("1", f"HWN{n}"), ("2", f"HW{n}")):
        px, py = r52.pin(pin)
        side = -5.08 if pin == "1" else 5.08
        sch.wire((px, py), (px + side, py))
        sch.label(net, px + side, py)

    # -- the summing stage ------------------------------------------------
    package, unit = circuit.SECTIONS[("env_b", n)]
    lib, value = circuit.package_part(package)
    amp = sch.place(package, lib, value, EX_B, y,
                    footprint=circuit.PARTS[package].footprint,
                    unit="ABCD".index(unit) + 1)
    inv = amp.pin(str(circuit.OPAMP_UNITS[unit][1]))
    out = amp.pin(str(circuit.OPAMP_UNITS[unit][0]))

    r53 = _r(sch, f"R{n}53", EX_SUM, y - 7.62, angle=HORIZ)
    r54 = _r(sch, f"R{n}54", EX_SUM, y, angle=HORIZ)
    for part, net in ((r53, f"BUF{n}"), (r54, f"HW{n}")):
        px, py = part.pin("1")
        sch.wire((px - 5.08, py), (px, py))
        sch.label(net, px - 5.08, py)
    # R{n}53 arrives by label; R{n}54 is the one routed into -IN, so the node
    # gets its name at that corner and everything else joins it by name.
    px, py = r53.pin("2")
    sch.wire((px, py), (px + 5.08, py))
    sch.label(f"ENVN{n}", px + 5.08, py)
    _to_inverting(sch, r54.pin("2"), inv, f"ENVN{n}")

    r55 = _r(sch, f"R{n}55", EX_B, y - 15.24, angle=HORIZ)
    c51 = _c(sch, f"C{n}51", EX_B, y - 22.86, angle=HORIZ)
    _feedback(sch, inv, out, (r55, c51))
    sch.wire(out, (out[0] + 10.16, out[1]))
    sch.label(f"ENV{n}", out[0] + 10.16, out[1])
    _drop_out(sch, amp, str(circuit.OPAMP_UNITS[unit][2]), "MAGND",
              dx=-22.86, dy=15.24)


def shared_block(sch, y):
    """Reference, logic buffer, rails, decoupling and the two ground stars."""
    # -- the reference ---------------------------------------------------
    ref = sch.place(circuit.REF_REF, "cv:MAX6126", circuit.VREF_PART,
                    48 * G, y, footprint=circuit.PARTS[circuit.REF_REF].footprint)
    P = circuit.REF_PINS
    for name, net in (("IN", "V5"), ("OUTS", "VREF"), ("OUTF", "VREF"),
                      ("NR", "VNR")):
        px, py = ref.pin(str(P[name]))
        side = 7.62 if px > ref.pin(str(P["GND"]))[0] else -7.62
        sch.wire((px, py), (px + side, py))
        sch.label(net, px + side, py)
    for name, dx in (("GND", -8.89), ("GNDS", -11.43)):
        _drop_out(sch, ref, str(P[name]), "MAGND", dx=dx, dy=12.7)

    c801 = _c(sch, "C801", 20 * G, y, angle=VERT)
    ax, ay = c801.pin("1")
    sch.wire((ax, ay - 6.35), (ax, ay))
    sch.label("VNR", ax, ay - 6.35)
    _drop(sch, c801, "2", "MAGND", dy=5.08)

    c802 = _c(sch, "C802", 88 * G, y, angle=VERT)
    bx, by = c802.pin("1")
    sch.wire((bx, by - 6.35), (bx, by))
    sch.label("VREF", bx, by - 6.35)
    _drop(sch, c802, "2", "MAGND", dy=5.08)

    # -- the reference inverter ------------------------------------------
    package, unit = circuit.SECTIONS[("refinv", 0)]
    inv = sch.place(package, "cv:OPA1644", circuit.OPAMP, 150 * G, y,
                    footprint=circuit.PARTS[package].footprint,
                    unit="ABCD".index(unit) + 1)
    # R801 was at y - 2.54, which is exactly this unit's +IN. Trap 4, and it
    # cost twice over: the route from R801 *ended* on +IN, and R802's hand-rolled
    # feedback ran vertically down the amplifier's own column and *passed
    # through* it. Either alone puts RINV on MAGND; together they made the
    # reference inverter an inverting stage with both inputs shorted, which
    # yields 0 V on VREFN and therefore no positive Vc anywhere on the board.
    # y - 6 * G clears +IN, and R802 goes through _feedback() like every other
    # amplifier on the sheet -- which is what _feedback() was written for.
    r801 = _r(sch, "R801", 120 * G, y - 6 * G, angle=HORIZ)
    r802 = _r(sch, "R802", 150 * G, y - 15.24, angle=HORIZ)
    cx, cy = r801.pin("1")
    sch.wire((cx - 6.35, cy), (cx, cy))
    sch.label("VREF", cx - 6.35, cy)
    inv_pin = inv.pin(str(circuit.OPAMP_UNITS[unit][1]))
    out_pin = inv.pin(str(circuit.OPAMP_UNITS[unit][0]))
    _to_inverting(sch, r801.pin("2"), inv_pin, "RINV")
    _feedback(sch, inv_pin, out_pin, (r802,))
    sch.wire(out_pin, (out_pin[0] + 10.16, out_pin[1]))
    sch.label("VREFN", out_pin[0] + 10.16, out_pin[1])
    _drop_out(sch, inv, str(circuit.OPAMP_UNITS[unit][2]), "MAGND",
              dx=-22.86, dy=15.24)

    # -- the logic buffer, straddling the boundary -----------------------
    logic = sch.place(circuit.LOGIC_REF, "cv:74AHC541", circuit.LOGIC,
                      240 * G, y + 5.08,
                      footprint=circuit.PARTS[circuit.LOGIC_REF].footprint)
    L = circuit.LOGIC_PINS
    body = logic.pin(str(L["GND"]))[0]
    for pin, net in ((L["VCC"], "VREF"), (L["OE1"], "OE"), (L["OE2"], "OE")):
        px, py = logic.pin(str(pin))
        if pin == L["VCC"]:
            sch.wire((px, py), (px, py - 14 * G))
            sch.label(net, px, py - 14 * G)
        else:
            # Sideways, away from the package: a vertical here runs down the
            # A-pin column and joins OE to whichever inputs it passes.
            dx = -22 * G if px <= body else 22 * G
            sch.wire((px, py), (px + dx, py))
            sch.label(net, px + dx, py)
    _drop_out(sch, logic, str(L["GND"]), "MAGND", dx=-8 * G, dy=10 * G)
    for n in range(1, circuit.CHANNELS + 1):
        px, py = logic.pin(str(circuit.LOGIC_A[n]))
        sch.wire((px, py), (px - 6.35, py))
        sch.label(f"PWM{n}", px - 6.35, py)
        qx, qy = logic.pin(str(circuit.LOGIC_Y[n]))
        sch.wire((qx, qy), (qx + 6.35, qy))
        sch.label(f"LOGO{n}", qx + 6.35, qy)
    for n, dx in ((7, -16 * G), (8, -20 * G)):
        _drop_out(sch, logic, str(circuit.LOGIC_A[n]), "MAGND",
                  dx=dx, dy=16 * G)

    # C803 at the Vcc pin supplies the PWM edges, and **the Kelvin sense pair
    # closes here**: the datasheet has OUTS join OUTF "at the point where the
    # voltage accuracy is needed", and that point is this package's Vcc, because
    # Vcc is what sets the CV full scale.
    #
    # C804's 10 uF sat beside it and is gone -- it put VREF at 2.01x the
    # MAX6126's capacitive-load stability range, and at 8 kHz it could only ever
    # have supplied 1.4% of the load step it was justified by. See
    # design.reference_load(). Note the sense closure did *not* move with it:
    # where the bulk capacitor goes and where the sense line closes are the two
    # halves of force and sense, not one decision.
    for ref_name, dx in (("C803", -4 * G),):
        cap = _c(sch, ref_name, 240 * G + dx, y + 30 * G, angle=VERT)
        px, py = cap.pin("1")
        sch.wire((px, py - 5.08), (px, py))
        sch.label("VREF", px, py - 5.08)
        _drop(sch, cap, "2", "MAGND", dy=5.08)

    sch.text("The boundary runs through U11: A-side from the digital domain, "
             "Y-side precision analogue, GND on MAGND. See floorplan.py.",
             200 * G, y - 38.1, size=2.0)

    # -- pull-downs and the controller headers ---------------------------
    #
    # **The 16 * G pitch is a floor, not a preference.** A vertical Device:R spans
    # 7.62 mm pin to pin and the ground drop below it adds 5.08, so a stack needs
    # 12.7 mm before the symbols touch at all -- and at exactly 12.7 each ground
    # symbol lands on the *next* resistor's top pin, which wires the six
    # pull-downs into a series chain and shorts all six PWM nets together. It
    # draws as six separate resistors. Anything below 20.32 is too close; this is
    # 20.32.
    for n in range(1, circuit.CHANNELS + 1):
        rr = _r(sch, f"R81{n}", 140 * G, y + 38.1 + n * 16 * G, angle=VERT)
        px, py = rr.pin("1")
        sch.wire((px, py - 5.08), (px, py))
        sch.label(f"PWM{n}", px, py - 5.08)
        _drop(sch, rr, "2", "MDGND", dy=5.08)

    # J8 is not in this loop any more: it is a two-way *primary* inlet now and
    # is drawn with the converter it feeds. See supply_block().
    #
    # **J9, J10 and J11 were drawn here and they are gone**, with J12 and J13
    # in adc_block(): five headers out to a controller on some other board.
    # The controller is on this one, in controller_block(), and the fourteen
    # nets they carried are labels into it.

    # -- the loom bond pad -----------------------------------------------
    bond = sch.place("J7", "Connector:TestPoint", "BOND", 520 * G, y + 45.72,
                     footprint=circuit.PARTS["J7"].footprint)
    px, py = bond.pin("1")
    sch.wire((px, py), (px, py + 7.62))
    sch.label(socket.AGND, px, py + 7.62)

    # -- the fail-safe: pump, sink, relays, clamp ------------------------
    #
    # Drawn as one block rather than distributed, because it *is* one: a single
    # pump holds a single FET which releases all three relays together. The
    # contacts reach their channels by label, exactly as the pad's did -- a
    # relay symbol carries its coil and its contacts on one body, so the
    # alternative would be six wires crossing the whole sheet to say what
    # three labels say.
    # **Below everything, and that is not aesthetics.** The first placement put
    # this block at y + 63.5 on the same x band as the power flags, whose row
    # sits at y + 121.92 from 640 * G eastward -- three relays landed on three
    # flags and merged SIN1 with VA+, SIN4 with MAGND and AGND with a coil.
    # kisch caught all three, which is the argument for the geometry check in
    # one line: nothing about the sheet looked wrong.
    fy = y + 152.4
    c805 = _c(sch, "C805", 660 * G, fy, angle=HORIZ)
    ax, ay = c805.pin("1")
    sch.wire((ax - 6.35, ay), (ax, ay))
    sch.label("FSDRV", ax - 6.35, ay)
    bx, by = c805.pin("2")
    sch.wire((bx, by), (bx + 6.35, by))
    sch.label("FSAC", bx + 6.35, by)

    # D801 clamps FSAC's negative half to ground, D802 charges the hold cap on
    # the positive one. Cathode is pin 1 on Device:D, so the two are drawn the
    # same way round and differ only in which net each end carries -- which is
    # the whole of a two-diode pump and the whole of what a transposition
    # would destroy.
    for ref, left, right, dy in (("D801", "FSAC", "MDGND", 10.16),
                                 ("D802", "FSG", "FSAC", -10.16)):
        part = circuit.PARTS[ref]
        d = sch.place(ref, "Device:D", part.value, 700 * G, fy + dy,
                      footprint=part.footprint, angle=HORIZ)
        for pin, net in ((str(circuit.DIODE_PINS["K"]), left),
                         (str(circuit.DIODE_PINS["A"]), right)):
            px, py = d.pin(pin)
            side = -5.08 if px < 700 * G else 5.08
            sch.wire((px, py), (px + side, py))
            if net == "MDGND":
                _gnd(sch, px + side, py, "MDGND")
            else:
                sch.label(net, px + side, py)

    for ref, x in (("C806", 740 * G), ("R803", 760 * G)):
        part = _c(sch, ref, x, fy, angle=VERT) if ref.startswith("C") \
            else _r(sch, ref, x, fy, angle=VERT)
        px, py = part.pin("1")
        sch.wire((px, py - 6.35), (px, py))
        sch.label("FSG", px, py - 6.35)
        _drop(sch, part, "2", "MDGND", dy=5.08)

    fet = sch.place(circuit.FET_REF, "cv:Q_NMOS_GSD",
                    circuit.PARTS[circuit.FET_REF].value, 800 * G, fy,
                    footprint=circuit.PARTS[circuit.FET_REF].footprint)
    gx, gy = fet.pin(str(circuit.FET_PINS["G"]))
    sch.wire((gx - 6.35, gy), (gx, gy))
    sch.label("FSG", gx - 6.35, gy)
    dx, dy = fet.pin(str(circuit.FET_PINS["D"]))
    sch.wire((dx, dy), (dx, dy - 6.35))
    sch.label("FSD", dx, dy - 6.35)
    _drop(sch, fet, str(circuit.FET_PINS["S"]), "MDGND", dy=6.35)

    for index, ref in enumerate(circuit.BYPASS_RELAY_REFS):
        k = sch.place(ref, "cv:Relay", "DPDT", (640 + 40 * index) * G,
                      fy + 45.72, footprint="")
        pins = circuit.RELAY_PINS
        wiring = [(pins["COIL+"], "VMOD"), (pins["COIL-"], "FSD")]
        for channel in (2 * index + 1, 2 * index + 2):
            _, com, nc, no = circuit.bypass_contact(channel)
            wiring += [(com, f"SIN{channel}"), (nc, f"PIN{channel}"),
                       (no, f"IVOUT{channel}")]
        # **The relay's pins point up and down, not left and right**, which is
        # the one thing about this symbol that has to be read rather than
        # assumed: the two commons are on the top edge and the four
        # normally-open/closed contacts on the bottom, 2.54 mm apart in x. A
        # horizontal stub from 12 lands exactly on 14 -- three nets merged into
        # one on the first run, on all three relays, and the sheet looked
        # right. So every stub leaves vertically, and the lengths are staggered
        # so the labels do not sit on top of each other.
        origin_y = fy + 45.72
        stagger = {"12": 7.62, "14": 12.7, "22": 17.78, "24": 22.86}
        for pin, net in wiring:
            px, py = k.pin(pin)
            run = stagger.get(pin, 7.62)
            step = -run if py < origin_y else run
            sch.wire((px, py), (px, py + step))
            sch.label(net, px, py + step)
        flyback = f"D{80 + index + 1}3"
        part = circuit.PARTS[flyback]
        d = sch.place(flyback, "Device:D", part.value,
                      (640 + 40 * index) * G, fy + 76.2,
                      footprint=part.footprint, angle=HORIZ)
        for pin, net in ((str(circuit.DIODE_PINS["K"]), "VMOD"),
                         (str(circuit.DIODE_PINS["A"]), "FSD")):
            px, py = d.pin(pin)
            side = -5.08 if px < (640 + 40 * index) * G else 5.08
            sch.wire((px, py), (px + side, py))
            sch.label(net, px + side, py)

    # The clamp on the inverted reference. One part, and it is the only answer
    # this board has to the one fail-loud path -- the pump cannot see it,
    # because a reference inverter that fails leaves the MCU healthy.
    clamp = sch.place("D803", "Device:D", circuit.PARTS["D803"].value,
                      860 * G, fy, footprint=circuit.PARTS["D803"].footprint,
                      angle=HORIZ)
    for pin, net in ((str(circuit.DIODE_PINS["K"]), "MAGND"),
                     (str(circuit.DIODE_PINS["A"]), "VREFN")):
        px, py = clamp.pin(pin)
        side = -5.08 if px < 860 * G else 5.08
        sch.wire((px, py), (px + side, py))
        if net == "MAGND":
            _gnd(sch, px + side, py, "MAGND")
        else:
            sch.label(net, px + side, py)

    sch.text("Fail-safe: any stuck MCU state collapses the pump, the FET "
             "releases, and de-energised is bypass. D803 covers the one path "
             "the pump cannot see. See design.fail_safe().",
             640 * G, fy - 15.24, size=2.0)

    # -- the two ground stars --------------------------------------------
    # **Both are drawn at 180 degrees so that pin 1 faces downward**, because
    # design.py puts MAGND on pin 1 of both and MAGND is the node underneath
    # them. Drawn at 0 they had AGND on R901 pin 1 and MDGND on R902 pin 1 --
    # the same circuit, since a 0R link is symmetric, and the first thing KiCad's
    # own netlist disagreed with design.py about once verify.py started reading
    # it. Worth fixing rather than tolerating: the comparison is pin-exact
    # because that is the check that catches a *polarised* part drawn backwards,
    # which is the fault the mixer records twice at DIODE_PINS and CAP_PINS and
    # could not catch. Loosening it to (ref) to excuse two links would give up
    # precisely the property that makes reading KiCad's export worth doing.
    star = _r(sch, circuit.GROUND_STAR, 560 * G, y + 45.72, angle=180)
    _drop(sch, star, "1", "MAGND", dy=7.62)
    ax, ay = star.pin("2")
    sch.wire((ax - 7.62, ay), (ax, ay))
    sch.label(socket.AGND, ax - 7.62, ay)

    domain = _r(sch, circuit.DOMAIN_STAR, 600 * G, y + 45.72, angle=180)
    _drop(sch, domain, "1", "MAGND", dy=7.62)
    bx, by = domain.pin("2")
    sch.wire((bx, by), (bx, by - 7.62))
    _gnd(sch, bx, by - 7.62, "MDGND")

    sch.text("R901 is THE bond, to the mixer's TP6. R902 is internal. "
             "Constraint 2 allows exactly one of the first.",
             520 * G, y + 63.5, size=2.0)

    # -- rail decoupling and op-amp power --------------------------------
    x = 20 * G
    for ref_name in sorted(circuit.PARTS, key=_sort_key):
        if not ref_name.startswith("C7"):
            continue
        part = circuit.PARTS[ref_name]
        cap = _c(sch, ref_name, x, y + 88.9, angle=VERT)
        px, py = cap.pin("1")
        sch.wire((px, py - 6.35), (px, py))
        rail = "VA+" if "V+" in part.description else "VA-"
        sch.label(rail, px, py - 6.35)
        _drop(sch, cap, "2", "MAGND", dy=5.08)
        x += 20.32

    x = 20 * G
    for package in circuit.OPAMP_PACKAGES + list(circuit.ENV_PACKAGES_REFS):
        lib, value = circuit.package_part(package)
        pwr = sch.place(package, lib, value, x, y + 121.92,
                        footprint=circuit.PARTS[package].footprint,
                        unit=circuit.OPAMP_POWER_UNIT)
        for pin, net in ((circuit.OPAMP_PINS["V+"], "VA+"),
                         (circuit.OPAMP_PINS["V-"], "VA-")):
            px, py = pwr.pin(str(pin))
            dy = -6.35 if net == "VA+" else 6.35
            sch.wire((px, py), (px, py + dy))
            sch.label(net, px, py + dy)
        x += 40.64

    # The spare sections, as followers with their inputs at MAGND. Drawn last of
    # the amplifiers and next to the power units, because they are terminations
    # rather than stages: nothing arrives and nothing leaves.
    #
    # **Three of them now and each on its own net**, which is why the label is
    # keyed on the section rather than being the bare "SPARE" it was. One net
    # across three followers is three outputs tied together, and it would have
    # drawn beautifully.
    for index, key in enumerate(circuit.SPARE_SECTIONS):
        package, unit = circuit.SECTIONS[key]
        lib, value = circuit.package_part(package)
        spare_amp = sch.place(package, lib, value, (320 + 60 * index) * G,
                              y + 121.92,
                              footprint=circuit.PARTS[package].footprint,
                              unit="ABCD".index(unit) + 1)
        inv_pin = spare_amp.pin(str(circuit.OPAMP_UNITS[unit][1]))
        out_pin = spare_amp.pin(str(circuit.OPAMP_UNITS[unit][0]))
        # No part in the loop, so _feedback() has nothing to step around:
        # straight over the top on its own column, 2.54 clear of the pins on
        # both sides.
        sch.wire(inv_pin, (inv_pin[0] - 2.54, inv_pin[1]),
                 (inv_pin[0] - 2.54, inv_pin[1] - 15.24),
                 (out_pin[0] + 2.54, inv_pin[1] - 15.24),
                 (out_pin[0] + 2.54, out_pin[1]), out_pin)
        sch.label(f"SPARE{key[1]}", inv_pin[0] - 2.54, inv_pin[1] - 15.24)
        _drop_out(sch, spare_amp, str(circuit.OPAMP_UNITS[unit][2]), "MAGND",
                  dx=-22.86, dy=15.24)

    for index, vca_ref in enumerate(circuit.VCA_PACKAGES_REFS):
        v = _vca_cache[vca_ref]
        # V+ is alone on its row and leaves sideways. V- shares a row with GND
        # 2.54 mm away, so both leave vertically first, on opposite sides.
        px, py = v.pin(str(circuit.VCA_PINS["V+"]))
        sch.wire((px, py), (px + 24 * G, py))
        sch.label("VA+", px + 24 * G, py)
        end = _leave_down(sch, v, str(circuit.VCA_PINS["V-"]), 14 * G, -20 * G)
        sch.label("VA-", *end)
        end = _leave_down(sch, v, str(circuit.VCA_PINS["GND"]), 20 * G, 12 * G)
        _gnd(sch, *end, net="MAGND")
        # MODE open is Class AB (page 3) and the spare cell's control pin may
        # float (page 5). Both are decisions, both are in design.NO_CONNECT now,
        # and no_connects() draws the flags -- they were drawn here and declared
        # nowhere, which is how the sheet came to flag two pins design.py had
        # never been asked about.
        spare = circuit.VCA_CHANNEL_PINS[circuit.VCA_SPARE_CELLS[vca_ref]]
        for role, dx in (("IIN", 8.89), ("IOUT", 11.43)):
            _drop_out(sch, v, str(spare[role]), "MAGND", dx=dx, dy=11 * G)

    # -- power flags, so ERC knows where the rails come from -------------
    #
    # VREF and VREFN are not in the list and must not be. A PWR_FLAG asserts
    # "something drives this net" on a net whose only pins are passive, which is
    # what a rail arriving on a connector looks like. VREF is driven by the
    # MAX6126's OUTF and VREFN by U8C's output -- both real drivers -- so a flag
    # there is a second driver on a driven net, and ERC said so twice.
    # **Three came off this list and two went on, and the reason is that the
    # supply is drawn.** A PWR_FLAG asserts "something drives this net" on a
    # net whose pins are all passive; put one on a net that has a real driver
    # and ERC reports two drivers, which it did for every rail the moment U15
    # and U16 appeared. V5 is driven by the regulator's output pin and MDGND by
    # the converter's Com, so both lose their flags. VA+ and VA- keep theirs,
    # which looks inconsistent and is not: they sit on the far side of R804 and
    # R805 from the pins that drive them, so the rail *net* still has nothing
    # but passives on it. And the primary side gains two, because IGND and
    # VIN_P feed power_in pins from a connector.
    # **The seventh moved from VMCU to VSYS, and the module is why.** The flag
    # was on VMCU for VA+'s exact reason: U22 drove that rail through L802, and
    # an inductor is not a driver, so the *net* had nothing but passives and
    # power inputs on it. It is now the module's own 3V3 pin that drives VMCU,
    # and that pin is a `power_out` -- so the flag became a second driver and
    # ERC said so. VSYS is where the argument moved to: U22 drives VMOD, and
    # VSYS is on the other side of D806, which is a diode and therefore
    # passive.
    #
    # **VMOD gets no flag either**, and the pair is worth reading together:
    # VMOD has U22's SW pin on it through L802 -- passive again -- but it also
    # has three relay coils and their flybacks, all passive, and no power_in
    # pin at all. ERC only complains about a net that feeds a power *input*
    # with no output on it, and VMOD feeds none: the coils are passive and
    # D806 is passive. A flag there would be asserting a driver ERC never
    # asked for.
    for index, net in enumerate(("VA+", "VA-", "IGND", "VIN_P", "VSYS",
                                 "MAGND", socket.AGND)):
        fx = 640 * G + index * 16 * G
        flag = sch.place(f"#FLG{index + 1:02d}", "power:PWR_FLAG", "PWR_FLAG",
                         fx, y + 121.92)
        px, py = flag.pin("1")
        sch.wire((px, py), (px, py + 7.62))
        if net in ("MAGND", "MDGND"):
            _gnd(sch, px, py + 7.62, net)
        else:
            sch.label(net, px, py + 7.62)


# ---------------------------------------------------------------------------
# Does the drawing mean what design.py says?
# ---------------------------------------------------------------------------

# The supply's own band, below everything. Its x runs the width of the sheet
# because the block is a chain -- inlet, protection, converter, rails -- and
# drawing a chain as a row is what makes the isolation barrier visible as a
# gap in the middle of it rather than as a note.
SUPPLY_SHEET_Y = SHARED_Y + 240 * G


def supply_block(sch, y):
    """The inlet, the converter, the barrier and the two derived rails.

    Drawn left to right in the order the current takes, with the barrier in
    the middle: everything left of U15 is labelled IGND and everything right
    of it MDGND, and the two never share a symbol. That is the one thing this
    sheet can say about isolation -- copper is verify.check_isolation_gap()'s
    job -- and it is worth the horizontal space, because a reader who cannot
    see where the barrier is will put something across it.
    """
    # -- primary ----------------------------------------------------------
    inlet = sch.place("J8", "Connector_Generic:Conn_01x02",
                      circuit.PARTS["J8"].value, 40 * G, y,
                      footprint=circuit.PARTS["J8"].footprint)
    for pin, net in (("1", "VIN_J"), ("2", "IGND_J")):
        px, py = inlet.pin(pin)
        sch.wire((px, py), (px + 7.62, py))
        sch.label(net, px + 7.62, py)

    # The common-mode choke, drawn with the jack side on the left and the
    # converter side on the right, which is also the order the current takes.
    # **The two windings are 1-4 and 2-3**, and the symbol is chosen for that:
    # Choke_CommonMode_FerriteCore_**1423** puts 1 and 4 on the same winding.
    # A reader cannot tell 1-4/2-3 from 1-2/4-3 by looking at four wires
    # between four pins, which is why design.INLET_CHOKE_PINS names them by
    # role and verify.check_supply() asserts the map.
    choke = sch.place(circuit.INLET_CHOKE_REF, "cv:744222",
                      circuit.INLET_CHOKE, 75 * G, y,
                      footprint=circuit.PARTS[
                          circuit.INLET_CHOKE_REF].footprint)
    for role, net, side in (("L1_IN", "VIN_J", -1), ("L2_IN", "IGND_J", -1),
                            ("L1_OUT", "VIN", 1), ("L2_OUT", "IGND", 1)):
        px, py = choke.pin(str(circuit.INLET_CHOKE_PINS[role]))
        sch.wire((px, py), (px + side * 7.62, py))
        sch.label(net, px + side * 7.62, py)

    diode = sch.place("D804", "Device:D_Schottky",
                      circuit.PARTS["D804"].value, 110 * G, y,
                      footprint=circuit.PARTS["D804"].footprint)
    for pin, net in ((str(circuit.DIODE_PINS["A"]), "VIN"),
                     (str(circuit.DIODE_PINS["K"]), "VIN_P")):
        px, py = diode.pin(pin)
        sch.wire((px, py), (px, py - 7.62))
        sch.label(net, px, py - 7.62)

    for index, ref in enumerate(("C807", "C808", "C809")):
        cap = _c(sch, ref, (140 + 24 * index) * G, y, angle=VERT)
        px, py = cap.pin("1")
        sch.wire((px, py - 5.08), (px, py))
        sch.label("VIN_P", px, py - 5.08)
        px, py = cap.pin("2")
        sch.wire((px, py), (px, py + 5.08))
        sch.label("IGND", px, py + 5.08)

    # -- the converter, and the gap through the middle of it --------------
    conv = sch.place(circuit.SUPPLY_REF, "cv:TMR6-2422WI", circuit.SUPPLY_PART,
                     260 * G, y, footprint=circuit.PARTS[circuit.SUPPLY_REF].footprint)
    for pin, net, side in (
            (circuit.SUPPLY_PINS["+Vin"], "VIN_P", -1),
            (circuit.SUPPLY_PINS["-Vin"], "IGND", -1),
            (circuit.SUPPLY_PINS["Remote"], "IGND", -1),
            (circuit.SUPPLY_PINS["+Vout"], "VA_RAW", 1),
            (circuit.SUPPLY_PINS["Com"], "MDGND", 1),
            (circuit.SUPPLY_PINS["-Vout"], "VN_RAW", 1)):
        px, py = conv.pin(str(pin))
        if net == "MDGND":
            # Com sits 2.54 mm from -Vout in the same column, so a ground drop
            # taken at the usual offset falls straight through that pin's own
            # wire end. Out twice as far first, then down -- the same move
            # _leave_down() makes for the SSI2164's GND and V- pair, and the
            # same fault it was written for.
            sch.wire((px, py), (px + side * 20.32, py),
                     (px + side * 20.32, py + 7.62))
            _gnd(sch, px + side * 20.32, py + 7.62, net)
        else:
            sch.wire((px, py), (px + side * 10.16, py))
            sch.label(net, px + side * 10.16, py)

    sch.text("The isolation barrier runs through U15: pins 1-3 are referenced "
             "to IGND, which is the inlet's 0 V and the mixer's PGND through "
             "the shared jack; pins 6-8 to MDGND. C810 is the only other part "
             "that touches both. See design.barrier_return().",
             200 * G, y - 30.48, size=2.0)

    # The Y-capacitor, drawn between the two grounds rather than beside one of
    # them, because that is what it is.
    bridge = _c(sch, "C810", 330 * G, y + 45.72, angle=VERT)
    px, py = bridge.pin("1")
    sch.wire((px, py - 5.08), (px, py))
    sch.label("IGND", px, py - 5.08)
    _drop(sch, bridge, "2", "MDGND", dy=5.08)

    # -- secondary: two rail filters and the 5 V regulator ----------------
    for ref, source, rail, cap in (("R804", "VA_RAW", "VA+", "C811"),
                                   ("R805", "VN_RAW", "VA-", "C812")):
        res = _r(sch, ref, (400 + 60 * (ref == "R805")) * G, y, angle=VERT)
        px, py = res.pin("1")
        sch.wire((px, py - 5.08), (px, py))
        sch.label(source, px, py - 5.08)
        px, py = res.pin("2")
        sch.wire((px, py), (px, py + 5.08))
        sch.label(rail, px, py + 5.08)
        shunt = _c(sch, cap, (420 + 60 * (ref == "R805")) * G, y, angle=VERT)
        px, py = shunt.pin("1")
        sch.wire((px, py - 5.08), (px, py))
        sch.label(rail, px, py - 5.08)
        _drop(sch, shunt, "2", "MDGND", dy=5.08)

    reg = sch.place(circuit.V5_REF, "cv:NCP1117-5.0", circuit.V5_PART,
                    530 * G, y, footprint=circuit.PARTS[circuit.V5_REF].footprint)
    px, py = reg.pin(str(circuit.V5_PINS["VI"]))
    sch.wire((px - 10.16, py), (px, py))
    sch.label("VA_RAW", px - 10.16, py)
    px, py = reg.pin(str(circuit.V5_PINS["VO"]))
    sch.wire((px, py), (px + 10.16, py))
    sch.label("V5", px + 10.16, py)
    _drop(sch, reg, str(circuit.V5_PINS["GND"]), "MDGND", dy=7.62)

    for ref, net in (("C813", "VA_RAW"), ("C814", "V5")):
        cap = _c(sch, ref, (560 + 24 * (ref == "C814")) * G, y + 45.72,
                 angle=VERT)
        px, py = cap.pin("1")
        sch.wire((px, py - 5.08), (px, py))
        sch.label(net, px, py - 5.08)
        _drop(sch, cap, "2", "MDGND", dy=5.08)


ADC_SHEET_Y = SUPPLY_SHEET_Y + 150 * G


def adc_block(sch, y):
    """The envelope ADC, its 3.3 V rail and the six input networks.

    Drawn as its own block rather than folded into shared_block(), because it
    is its own zone on the board -- floorplan.ZONES entry A6 -- and the sheet
    reads better when the two agree about what a block is.

    **Two of the ADC's pins are drawn on the wrong side and it is the least
    bad of the options.** The borrowed symbol is the ADS131M04's, which has
    eight analogue pins on its left column; the MCP3564 has ten, so CH6 and
    CH7 land in the right-hand column with the logic. They are the two spare
    channels, grounded, which is the pair it costs least to have there -- and
    the alternative was to draw a 20-pin rectangle from scratch, which is a
    second place for a pin map to be wrong. See design.LIBS.
    """
    P = circuit.ENV_ADC_PINS
    adc = sch.place(circuit.ENV_ADC_REF, "cv:MCP3564", circuit.ENV_ADC,
                    260 * G, y,
                    footprint=circuit.PARTS[circuit.ENV_ADC_REF].footprint)

    # -- the six input networks, west of the package ----------------------
    #
    # One row per channel, each row a divider and its capacitor. ENV{n} comes
    # in from the envelope rows above; ENVA{n} is the node between them and is
    # what the ADC pin sees.
    for n in range(1, circuit.CHANNELS + 1):
        row = y - 40 * G + (n - 1) * 20 * G
        top = _r(sch, f"R{n}56", 40 * G, row, angle=HORIZ)
        px, py = top.pin("1")
        sch.wire((px - 6.35, py), (px, py))
        sch.label(f"ENV{n}", px - 6.35, py)
        node = top.pin("2")
        sch.wire(node, (node[0] + 6.35, node[1]))
        sch.label(f"ENVA{n}", node[0] + 6.35, node[1])
        # The lower leg and the capacitor, each in its own column so that
        # neither drop lands on the other's wire end.
        bot = _r(sch, f"R{n}57", 70 * G, row + 6 * G, angle=VERT)
        bx, by = bot.pin("1")
        sch.wire((bx, by - 6.35), (bx, by))
        sch.label(f"ENVA{n}", bx, by - 6.35)
        _drop(sch, bot, "2", "MAGND", dy=5.08)
        cap = _c(sch, f"C{n}52", 90 * G, row + 6 * G, angle=VERT)
        cx, cy = cap.pin("1")
        sch.wire((cx, cy - 6.35), (cx, cy))
        sch.label(f"ENVA{n}", cx, cy - 6.35)
        _drop(sch, cap, "2", "MAGND", dy=5.08)

    # -- the analogue side of the package ---------------------------------
    for n in range(1, circuit.CHANNELS + 1):
        px, py = adc.pin(str(P[circuit.ENV_ADC_CHANNEL[n]]))
        sch.wire((px, py), (px - 10.16, py))
        sch.label(f"ENVA{n}", px - 10.16, py)
    px, py = adc.pin(str(P["REFIN+"]))
    sch.wire((px, py), (px - 10.16, py))
    sch.label("VREF", px - 10.16, py)
    # REFIN- goes to MAGND, and it goes out further than the labels above
    # before it drops: a ground symbol in that column would sit on the pin
    # below it. DS20006181C note 3 -- "REFIN- must be connected to ground for
    # single-ended measurements".
    _drop_out(sch, adc, str(P["REFIN-"]), "MAGND", dx=-20.32, dy=-12.7)

    # -- the two grounded spares, one on each row --------------------------
    #
    # **The offsets are per-pin because the pair could move.** CH4 and CH7 sit
    # one on each row, so one offset each clears everything. The CH6/CH7 pair
    # design.ENV_ADC_CHANNEL records having tried puts them adjacent on the east
    # row, where two drops of the same dx would share a column and one's wire
    # end would land on the other's leg -- the fault _drop_out()'s own docstring
    # records at the op-amp inputs. It needed +20.32 and +27.94, and that is
    # why this reads the pair rather than the pin numbers.
    for name, dx, dy in ((circuit.ENV_ADC_GROUNDED[0], -20.32, 15.24),
                         (circuit.ENV_ADC_GROUNDED[1], 20.32, -15.24)):
        _drop_out(sch, adc, str(P[name]), "MAGND", dx=dx, dy=dy)

    # -- supplies ---------------------------------------------------------
    #
    # AVDD and DVDD are one net and AGND and DGND are one net: DS20006181C
    # section 7.3's second scheme, and the only one compatible with this board
    # having exactly one analogue/digital star. See design.envelope_adc().
    for name in ("AVDD", "DVDD"):
        px, py = adc.pin(str(P[name]))
        sch.wire((px, py), (px, py - 10.16))
        sch.label("V3V3", px, py - 10.16)
    for name, dx in (("AGND", -7.62), ("DGND", 7.62)):
        _drop_out(sch, adc, str(P[name]), "MAGND", dx=dx, dy=10.16)

    # -- the six logic signals --------------------------------------------
    for name, net in (("CS", "CS"), ("SCK", "SCLK"), ("SDI", "MOSI"),
                      ("SDO", "MISO"), ("IRQ", "IRQ"), ("MCLK", "MCLK")):
        px, py = adc.pin(str(P[name]))
        sch.wire((px, py), (px + 10.16, py))
        sch.label(net, px + 10.16, py)

    # -- the 3.3 V rail ---------------------------------------------------
    reg = sch.place(circuit.V3V3_REF, "cv:MCP1700-3.3", circuit.V3V3_PART,
                    380 * G, y - 30 * G,
                    footprint=circuit.PARTS[circuit.V3V3_REF].footprint)
    px, py = reg.pin(str(circuit.V5_PINS["VI"]))
    sch.wire((px - 10.16, py), (px, py))
    sch.label("V5", px - 10.16, py)
    px, py = reg.pin(str(circuit.V5_PINS["VO"]))
    sch.wire((px, py), (px + 10.16, py))
    sch.label("V3V3", px + 10.16, py)
    _drop(sch, reg, str(circuit.V5_PINS["GND"]), "MAGND", dy=7.62)

    for ref_name, net, dx in (("C815", "V5", 0), ("C816", "V3V3", 30 * G),
                              ("C817", "V3V3", 60 * G),
                              ("C818", "V3V3", 90 * G),
                              ("C819", "VREF", 120 * G)):
        cap = _c(sch, ref_name, 380 * G + dx, y + 10 * G, angle=VERT)
        cx, cy = cap.pin("1")
        sch.wire((cx, cy - 6.35), (cx, cy))
        sch.label(net, cx, cy - 6.35)
        _drop(sch, cap, "2", "MAGND", dy=5.08)

    # J12 and J13 were here -- two 5-way headers carrying the ADC's six logic
    # signals out to a deferred controller. They are gone with the deferral;
    # the six are labels into controller_block() now.

    sch.text("The envelope ADC. AGND and DGND are one net here and both are "
             "MAGND -- DS20006181C section 7.3's second scheme, and the only "
             "one compatible with this board having exactly one "
             "analogue/digital star. Six logic signals leave for the "
             "controller and no analogue trace crosses the boundary; MCLK is "
             "one of the six because the part's own RC oscillator cannot hold "
             "2 kHz on six channels -- see design.envelope_adc_clock().",
             200 * G, y - 60 * G, size=2.0)


CONTROLLER_SHEET_Y = ADC_SHEET_Y + 200 * G


def _label_out(sch, part, pin, net, dx=0.0, dy=0.0):
    """Take a pin clear of the package and name it there.

    The commonest gesture in the controller block, for the same reason
    _drop_out() is the commonest one elsewhere: a QFN symbol has four rows of
    pins 2.54 mm apart, so every wire has to leave along its own pin's axis
    before anything else happens to it.
    """
    x, y = part.pin(str(pin))
    sch.wire((x, y), (x + dx, y + dy))
    if net in ("MAGND", "MDGND"):
        _gnd(sch, x + dx, y + dy, net)
    else:
        sch.label(net, x + dx, y + dy)


def controller_block(sch, y):
    """The Pico, DIN MIDI, the panel and U22.

    **Drawn as one block because it is one zone** -- floorplan.ZONES entry D2 --
    and the sheet and the board agree about what a block is, which is the rule
    adc_block()'s own docstring states.

    **Four sub-blocks became one part.** The crystal, the QSPI flash, the USB
    receptacle with its two 27 ohm terminations and its VBUS divider, and
    twelve decoupling capacitors are all inside the module now. What is left on
    this sheet is the module, the things that are specific to *this* box --
    MIDI, the footswitch, the pedal -- and the switcher that feeds it.

    Two things about the geometry rather than the circuit:

      * **the seven ground pins are one point on the symbol.** KiCad stacks
        them the way it stacked the QFN's six IOVDD pins, so one wire and one
        drop carry all seven. The netlist still names each, which is what
        placement.py and the board need;
      * **the three power pins leave north and the two supply nets are not the
        same net.** VSYS goes in and 3V3 comes out, and drawing them as one
        rail is exactly the mistake pico_backdrive() exists to refuse. They are
        labelled separately and the labels are 5.08 mm apart on the symbol, so
        each leaves along its own axis before it turns.
    """
    P = circuit.CONTROLLER_MODULE_PINS
    mcu = sch.place(circuit.CONTROLLER_REF, "MCU_Module:RaspberryPi_Pico",
                    circuit.CONTROLLER, 300 * G, y,
                    footprint=circuit.PARTS[circuit.CONTROLLER_REF].footprint)

    # -- the GPIO, east and west --------------------------------------------
    #
    # The symbol puts GPIO0-15 down the west side and GPIO16-22 and the three
    # ADC pins down the east, which is the module's own pin order. So which
    # way a net leaves is a property of the symbol rather than a choice, and
    # the map is read rather than restated.
    west = {P[name] for name in P if name.startswith("GPIO")
            and P[name] <= 20}
    for row in circuit.controller_pin_map():
        _label_out(sch, mcu, row["pin"], row["net"],
                   dx=-15.24 if row["pin"] in west else 15.24)

    # -- supplies, north; the seven grounds, south --------------------------
    #
    # Staggered lengths, because the three north pins are 5.08 mm apart and a
    # label anchor landing on a neighbour's wire is a merge.
    for index, (name, net) in enumerate((("VSYS", "VSYS"), ("3V3", "VMCU"))):
        _label_out(sch, mcu, P[name], net, dy=-(12.7 + index * 7.62))
    _drop(sch, mcu, str(circuit.CONTROLLER_MODULE_GND_PINS[0]), "MDGND",
          dy=7.62)
    # AGND leaves east along its own axis first: it is the bottom pin of that
    # column and its neighbour is 5.08 mm above it.
    _drop_out(sch, mcu, str(P["AGND"]), "MDGND", dx=10.16, dy=7.62)
    # RUN, west, to the reset link.
    _label_out(sch, mcu, P["RUN"], "RUN", dx=-20.32)

    # -- the ORing diode ----------------------------------------------------
    diode = sch.place("D806", "Device:D_Schottky", circuit.CLAMP_DIODE,
                      200 * G, y - 60 * G,
                      footprint=circuit.PARTS["D806"].footprint, angle=HORIZ)
    for pin, net in ((str(circuit.DIODE_PINS["A"]), "VMOD"),
                     (str(circuit.DIODE_PINS["K"]), "VSYS")):
        px, py = diode.pin(pin)
        side = -6.35 if px < 200 * G else 6.35
        sch.wire((px, py), (px + side, py))
        sch.label(net, px + side, py)

    # -- DIN MIDI ----------------------------------------------------------
    O = circuit.MIDI_OPTO_PINS
    opto = sch.place(circuit.MIDI_OPTO_REF, "Isolator:TLP2761",
                     circuit.MIDI_OPTO, 460 * G, y + 40 * G,
                     footprint=circuit.PARTS[circuit.MIDI_OPTO_REF].footprint)
    for name, net, dx in (("A", "MINA", -12.7), ("K", "MINK", -12.7),
                          ("VO", "MIDI_RX", 12.7)):
        _label_out(sch, opto, O[name], net, dx=dx)
    _label_out(sch, opto, O["VCC"], "VMCU", dx=20.32)
    _drop_out(sch, opto, str(O["GND"]), "MDGND", dx=7.62, dy=10.16)
    cap = _c(sch, "C835", 520 * G, y + 40 * G, angle=VERT)
    cx, cy = cap.pin("1")
    sch.wire((cx, cy - 6.35), (cx, cy))
    sch.label("VMCU", cx, cy - 6.35)
    _drop(sch, cap, "2", "MDGND", dy=5.08)
    res = _r(sch, "R827", 400 * G, y + 30 * G, angle=HORIZ)
    for pin, net, side in (("1", "MINJ", -6.35), ("2", "MINA", 6.35)):
        px, py = res.pin(pin)
        sch.wire((px, py), (px + side, py))
        sch.label(net, px + side, py)
    diode = sch.place("D805", "Device:D", circuit.MIDI_IN_DIODE,
                      400 * G, y + 50 * G,
                      footprint=circuit.PARTS["D805"].footprint, angle=HORIZ)
    for pin, net in ((str(circuit.DIODE_PINS["K"]), "MINA"),
                     (str(circuit.DIODE_PINS["A"]), "MINK")):
        px, py = diode.pin(pin)
        side = -6.35 if px < 400 * G else 6.35
        sch.wire((px, py), (px + side, py))
        sch.label(net, px + side, py)
    cap = _c(sch, "C836", 360 * G, y + 70 * G, angle=VERT)
    cx, cy = cap.pin("1")
    sch.wire((cx, cy - 6.35), (cx, cy))
    sch.label("MINSH", cx, cy - 6.35)
    _drop(sch, cap, "2", "MDGND", dy=5.08)
    for ref, left, right, dy in (("R828", "VMCU", "MOUTV", 0),
                                 ("R829", "MIDI_TX", "MOUTD", 14)):
        res = _r(sch, ref, 400 * G, y + 90 * G + dy * G, angle=HORIZ)
        for pin, net, side in (("1", left, -6.35), ("2", right, 6.35)):
            px, py = res.pin(pin)
            sch.wire((px, py), (px + side, py))
            sch.label(net, px + side, py)

    # -- the panel: tap and expression -------------------------------------
    for ref, left, right, ypos in (("R830", "VMCU", "TAPJ", 120),
                                   ("R831", "TAPJ", "TAP", 134),
                                   ("R832", "VMCU", "EXPRV", 158),
                                   ("R833", "EXPRW", "EXPR", 172)):
        res = _r(sch, ref, 400 * G, y + ypos * G, angle=HORIZ)
        for pin, net, side in (("1", left, -6.35), ("2", right, 6.35)):
            px, py = res.pin(pin)
            sch.wire((px, py), (px + side, py))
            sch.label(net, px + side, py)
    for ref, net, ypos in (("C837", "TAP", 134), ("C838", "EXPR", 172)):
        cap = _c(sch, ref, 460 * G, y + ypos * G, angle=VERT)
        cx, cy = cap.pin("1")
        sch.wire((cx, cy - 6.35), (cx, cy))
        sch.label(net, cx, cy - 6.35)
        _drop(sch, cap, "2", "MDGND", dy=5.08)

    # -- the connectors ----------------------------------------------------
    for ref_name, x, ypos in (("J15", 250 * G, 110), ("J16", 300 * G, 110),
                              ("J17", 250 * G, 150), ("J18", 300 * G, 150),
                              ("J19", 200 * G, 110)):
        part = circuit.PARTS[ref_name]
        pins = _conn_nets(ref_name)
        lib = ("Connector_Generic:Conn_01x02" if len(pins) == 2
               else "Connector_Generic:Conn_01x03")
        conn = sch.place(ref_name, lib, part.value, x, y + ypos * G,
                         footprint=part.footprint)
        for pin, net in sorted(pins.items(), key=lambda kv: int(kv[0])):
            px, py = conn.pin(pin)
            sch.wire((px, py), (px + 7.62, py))
            if net in ("MAGND", "MDGND"):
                _gnd(sch, px + 7.62, py, net)
            else:
                sch.label(net, px + 7.62, py)
    # ~~R825, R826, J20.~~ The RUN pull-up is on the die, BOOTSEL is a button
    # on the module, and the debug pads are on its underside -- see the reset
    # comment in design.controller().

    # -- the 5 V switcher --------------------------------------------------
    Q = circuit.MCU_DCDC_PINS
    reg = sch.place(circuit.MCU_DCDC_REF, "cv:TPS560430XF", circuit.MCU_DCDC,
                    620 * G, y - 30 * G,
                    footprint=circuit.PARTS[circuit.MCU_DCDC_REF].footprint)
    for name, net, dx, dy in (("VIN", "VA_RAW", -12.7, 0),
                              ("EN", "VA_RAW", -20.32, 0),
                              ("FB", "MFB", -12.7, 0),
                              ("SW", "MSW", 12.7, 0),
                              ("CB", "MCB", 12.7, 0)):
        _label_out(sch, reg, Q[name], net, dx=dx, dy=dy)
    _drop_out(sch, reg, str(Q["GND"]), "MDGND", dx=-7.62, dy=12.7)
    ind = sch.place("L802", "Device:L", circuit.MCU_DCDC_L,
                    700 * G, y - 30 * G,
                    footprint=circuit.PARTS["L802"].footprint, angle=HORIZ)
    for pin, net, side in (("1", "MSW", -6.35), ("2", "VMOD", 6.35)):
        px, py = ind.pin(pin)
        sch.wire((px, py), (px + side, py))
        sch.label(net, px + side, py)
    for ref, net, x in (("C840", "VA_RAW", 600), ("C841", "VA_RAW", 624),
                        ("C843", "VMOD", 700)):
        cap = _c(sch, ref, x * G, y - 5 * G, angle=VERT)
        cx, cy = cap.pin("1")
        sch.wire((cx, cy - 6.35), (cx, cy))
        sch.label(net, cx, cy - 6.35)
        _drop(sch, cap, "2", "MDGND", dy=5.08)
    cap = _c(sch, "C842", 660 * G, y - 55 * G, angle=HORIZ)
    for pin, net, side in (("1", "MCB", -6.35), ("2", "MSW", 6.35)):
        px, py = cap.pin(pin)
        sch.wire((px, py), (px + side, py))
        sch.label(net, px + side, py)
    for ref, top, bottom, x in (("R850", "VMOD", "MFB", 620),):
        res = _r(sch, ref, x * G, y + 20 * G, angle=VERT)
        px, py = res.pin("1")
        sch.wire((px, py - 6.35), (px, py))
        sch.label(top, px, py - 6.35)
        px, py = res.pin("2")
        sch.wire((px, py), (px, py + 6.35))
        sch.label(bottom, px, py + 6.35)
    res = _r(sch, "R851", 650 * G, y + 20 * G, angle=VERT)
    px, py = res.pin("1")
    sch.wire((px, py - 6.35), (px, py))
    sch.label("MFB", px, py - 6.35)
    _drop(sch, res, "2", "MDGND", dy=5.08)

    sch.text("The controller. Three 3.3 V and 5 V nets on this sheet and no "
             "two of them are one: V3V3 is the ADC's, linear from V5; VMOD is "
             "U22's switched 5 V, carrying the module and the relay coils; "
             "VMCU is the module's own 3.3 V, made on it by an RT6150 out of "
             "VSYS and brought back out on pin 36. V5 is what is left of the "
             "linear rail -- the reference and the ADC's LDO. U22's input is "
             "ahead of R804 so that its ripple meets the same pole the "
             "converter's own does. MINA/MINK/MINJ are on the far side of U21 "
             "and belong to whatever is sending: CA-033 forbids a DC path "
             "from them to this board's ground.",
             150 * G, y - 110 * G, size=2.0)

def _between(point, a, b):
    """Is `point` strictly inside the segment a-b, collinear with it?

    eeschema's rule, and the whole reason this file needs a checker: a wire
    *end* landing part-way along another wire is a connection. Two wires merely
    crossing, neither of them ending there, is not.
    """
    (px, py), (ax, ay), (bx, by) = point, a, b
    if (px, py) in (a, b):
        return False
    cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    if abs(cross) > 1e-6:
        return False
    dot = (px - ax) * (bx - ax) + (py - ay) * (by - ay)
    length = (bx - ax) ** 2 + (by - ay) ** 2
    return 0 < dot < length


def connectivity(sch):
    """Nets as the *geometry* forms them: net name -> {(ref, pin)}.

    Built the way eeschema builds them -- union the ends of every wire, union
    any endpoint or pin that lands mid-way along another wire, then name each
    component from whatever labels and power symbols sit on it. Nothing here
    reads design.NETS, which is the point: this is what the sheet says, and
    check_against_design() is where the two are made to agree.
    """
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in sch.wires:
        union(a, b)

    anchors = {a for a, _ in sch.wires} | {b for _, b in sch.wires}
    for part in sch.parts:
        for _, position in part.drawn_pins():
            anchors.add(position)
    for _, point, _, _ in sch.labels:
        anchors.add(point)

    for point in anchors:
        for a, b in sch.wires:
            if _between(point, a, b):
                union(point, a)

    names, pins = {}, {}
    for part in sch.parts:
        for number, position in part.drawn_pins():
            root = find(position)
            if part.ref.startswith("#PWR"):
                names.setdefault(root, set()).add(part.value)
            elif part.ref.startswith("#FLG"):
                pass
            else:
                pins.setdefault(root, set()).add((part.ref, str(number)))
    for name, point, _, _ in sch.labels:
        names.setdefault(find(point), set()).add(name)

    return names, pins


def merge_points(sch):
    """Where two named nets first touch, as coordinates.

    connectivity() says *that* two nets are one; this says *where*, which is
    the only form of the answer anybody can act on. It replays the same unions
    one at a time and records the point at which a component already carrying
    one name acquires a second.

    Naming the coordinate is what turned this from guesswork into a fix. Three
    rounds were spent moving offsets by hand and watching the merge relocate
    from IOUT1 to OE to PIN1, because the report said which nets were joined
    and never where.
    """
    parent, label_of = {}, {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for name, point, _, _ in sch.labels:
        label_of.setdefault(point, set()).add(name)
    for part in sch.parts:
        if part.ref.startswith("#PWR"):
            for _, position in part.drawn_pins():
                label_of.setdefault(position, set()).add(part.value)

    carried, found = {}, {}
    for point, names in label_of.items():
        carried[find(point)] = set(names)

    def union(a, b, where):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        left, right = carried.get(ra, set()), carried.get(rb, set())
        parent[ra] = rb
        merged = left | right
        carried[rb] = merged
        if left and right and left != right:
            found.setdefault(frozenset(merged), []).append(where)

    for a, b in sch.wires:
        union(a, b, a)
    anchors = ({a for a, _ in sch.wires} | {b for _, b in sch.wires}
               | {q for part in sch.parts for _, q in part.drawn_pins()}
               | set(label_of))
    for point in anchors:
        for a, b in sch.wires:
            if _between(point, a, b):
                union(point, a, point)
    return found


def check_against_design(sch):
    """Every net design.py asks for is the net the geometry forms.

    Two failures, and the second is the one this exists for.

    A component carrying more than one net name is a *merge*: two nets touching
    somewhere on the sheet. The message names both and the coordinates of every
    pin caught in it, because the useful question is always "where", and diffing
    KiCad's exported netlist afterwards answers only "what".

    A net design.py declares that the geometry did not form is a *break*.

    Compared by reference rather than by (ref, pin) for the membership test,
    which is the mixer's own rule at check_summing_node(): "which pin of a
    two-pin part faces the node is a drawing convenience". A resistor drawn the
    other way round is the same circuit.
    """
    names, pins = connectivity(sch)
    problems = []

    culprits = merge_points(sch)
    for root, labels in sorted(names.items(), key=lambda kv: sorted(kv[1])):
        if len(labels) > 1:
            caught = sorted(pins.get(root, ()))
            where = culprits.get(frozenset(labels), [])
            problems.append(
                f"MERGE: {sorted(labels)} are one net on the sheet at "
                f"{where[:2] or 'an unlocated point'}, carrying "
                f"{len(caught)} pins -- e.g. {caught[:4]}")

    drawn = {}
    for root, labels in names.items():
        for label in labels:
            drawn.setdefault(label, set()).update(
                ref for ref, _ in pins.get(root, ()))
    for net, entries in sorted(circuit.NETS.items()):
        want = {ref for ref, _ in entries}
        got = drawn.get(net)
        if got is None:
            problems.append(f"BREAK: {net} is not formed on the sheet at all")
        elif got != want:
            problems.append(
                f"BREAK: {net} carries {sorted(got)}, design.py says "
                f"{sorted(want)}")
    return problems


def check_pins_accounted(sch):
    """Every pin drawn is on a net, or flagged, or declared deferred.

    **This is the check that was missing, and its absence is why 24 invented
    coil nets survived.** check_against_design() walks design.NETS and asks
    whether the geometry forms each one. Nothing walked the other way -- from
    the pins that exist to what became of them -- so a pin the design had never
    been asked about could be wired to anything at all, and every instrument
    downstream agreed: the netlist was well formed, the comparison passed
    because MDGND is not compared pin by pin, and ERC said `isolated_pin_label`
    in a warning nobody read.

    The same shape as the struck constraint in CLAUDE.md. Not a wrong check --
    a check whose name promised the drawing matched design.py while it compared
    only the half of the drawing design.py already knew about.

    Three legitimate fates, and they are different claims:

      * on a net design.py declares -- the ordinary case;
      * in design.NO_CONNECT -- open on the finished board, with a reason;
      * in design.DEFERRED_PINS -- open in *this* netlist and not in the
        finished one, naming the DEFERRED block that will connect it.

    Anything else is a STRANDED pin. Reported rather than fatal, for the same
    reason a break is: an unconnected pin is what ERC exists to find and it
    announces itself. A merge does not.
    """
    names, _ = connectivity(sch)
    named = set()
    for root, labels in names.items():
        named.update(labels)

    owner = {}
    for net, entries in circuit.NETS.items():
        for entry in entries:
            owner[(entry[0], str(entry[1]))] = net
    flagged = {(ref, str(pin)) for ref, pin in circuit.NO_CONNECT}
    deferred = {(ref, str(pin)) for ref, pin in circuit.DEFERRED_PINS}

    problems = []
    for part in sch.parts:
        if part.ref.startswith("#"):
            continue
        for number, _ in part.drawn_pins():
            entry = (part.ref, str(number))
            if entry in owner or entry in flagged or entry in deferred:
                continue
            problems.append(
                f"STRANDED: {part.ref}.{number} is drawn on the sheet and is "
                f"on no net in design.NETS, in no NO_CONNECT and in no "
                f"DEFERRED_PINS -- say which of the three it is")
    for entry in sorted(getattr(sch, "_undrawn_flags", ())):
        problems.append(
            f"STRANDED: {entry} is declared open in design.py and its pin is "
            f"not drawn on the sheet, so nothing carries the flag")
    return problems


def _conn_nets(ref):
    return {pin: net for net, entries in circuit.NETS.items()
            for r, pin in entries if r == ref}


def _sort_key(ref):
    head = "".join(c for c in ref if c.isalpha())
    tail = "".join(c for c in ref if c.isdigit())
    return head, int(tail or 0)


def no_connects(sch):
    """One flag per pin design.py declares open, and not one more.

    Both directions of drift are the same mistake and this closes both. A pin
    flagged on the sheet and declared nowhere is the drawing deciding something
    for the design -- the two VCA MODE pins and the two spare control pins were
    exactly that. A pin declared open and not flagged is an ERC error that a
    reader has to interpret.

    DEFERRED_PINS is flagged alongside NO_CONNECT and that is the compromise
    KiCad forces: the file format has no way to say "connected by a block that
    is not drawn yet". design.DEFERRED_PINS is that sentence, check_deferred()
    in verify.py is what refuses to let it be forgotten, and neither of them is
    the flag itself.
    """
    drawn = {}
    for part in sch.parts:
        for number, position in part.drawn_pins():
            drawn[(part.ref, str(number))] = position
    undrawn = []
    for ref, pin in tuple(circuit.NO_CONNECT) + tuple(circuit.DEFERRED_PINS):
        position = drawn.get((ref, str(pin)))
        if position is None:
            undrawn.append(f"{ref}.{pin}")
        else:
            sch.no_connect(*position)
    return undrawn


def build():
    sch = Schematic(
        "cv-module",
        title="cv-module: per-string CV generation, six channels",
        rev="spike",
        company=f"mates with summing-mixer @ {socket.PIN[:7]}",
        paper="A0")
    register(sch)
    for n in range(1, circuit.CHANNELS + 1):
        audio_row(sch, n, AUDIO_Y0 + (n - 1) * AUDIO_PITCH)
    for n in range(1, circuit.CHANNELS + 1):
        cv_row(sch, n, CV_Y0 + (n - 1) * CV_PITCH)
    for n in range(1, circuit.CHANNELS + 1):
        envelope_row(sch, n, ENV_Y0 + (n - 1) * ENV_PITCH)
    shared_block(sch, SHARED_Y)
    supply_block(sch, SUPPLY_SHEET_Y)
    adc_block(sch, ADC_SHEET_Y)
    controller_block(sch, CONTROLLER_SHEET_Y)
    sch._undrawn_flags = no_connects(sch)
    sch.auto_junctions()
    return sch


def report(sch):
    """Print the comparison, and say which half of it is fatal.

    **A merge and a break are not the same severity and are not treated as
    such.** A merge is two nets touching: the sheet looks right, ERC passes, the
    netlist is well-formed, and the circuit is different -- the first run of
    this file merged 34 nets into one and nothing but this comparison said so.
    A break is a missing wire, which this check, KiCad's ERC and anybody reading
    the sheet all notice.

    So merges fail the build and breaks are reported loudly and let through.
    That is the same asymmetry design.check_stuffing() records upstream:
    "populating both shorts out the capacitor, which is a fault that measures as
    working; populating neither opens the channel, which at least announces
    itself."
    """
    problems = check_against_design(sch) + check_pins_accounted(sch)
    merges = [p for p in problems if p.startswith("MERGE")]
    breaks = [p for p in problems if p.startswith("BREAK")]
    stranded = [p for p in problems if p.startswith("STRANDED")]
    print(f"  {len(merges)} merges (fatal), {len(breaks)} breaks, "
          f"{len(stranded)} stranded pins")
    for group in (merges, breaks, stranded):
        for problem in group[:8]:
            print(f"    {problem}")
        if len(group) > 8:
            print(f"    ... and {len(group) - 8} more of the same kind")
    return merges, breaks + stranded


def main():
    OUT.mkdir(exist_ok=True)
    sch = build()
    sch.save(SHEET)
    print(f"{SHEET.name}: {len(sch.parts)} symbols, {len(sch.wires)} wires, "
          f"{len(sch.labels)} labels, {len(sch.junctions)} junctions")
    drawn = {p.ref for p in sch.parts if not p.ref.startswith("#")}
    missing = sorted(set(circuit.PARTS) - drawn, key=_sort_key)
    if missing:
        print(f"  NOT DRAWN: {missing}")
    merges, breaks = report(sch)
    if merges:
        raise SystemExit(f"{len(merges)} merges: two nets touch on the sheet, "
                         f"which is a different circuit that passes every "
                         f"other check")
    if breaks:
        print(f"  the sheet is saved and incomplete: {len(breaks)} nets in "
              f"design.py are not formed by the geometry yet")
    return sch


if __name__ == "__main__":
    main()
