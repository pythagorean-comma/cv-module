"""Where every part sits on the board, in millimetres.

Separate from gen_pcb.py for the reason the mixer separates them: this file is
plain arithmetic and imports nothing from KiCad, so it can be read, diffed and
checked by anything -- while gen_pcb.py can only run under KiCad's own
interpreter. A placement that lives inside the thing that needs `pcbnew` is a
placement nobody can look at without KiCad.

**It is the floorplan made into coordinates, and that is the whole design of
it.** floorplan.py has been a placement *contract* for three passes -- zones,
their adjacency, and the argument for each -- with nothing to hold it to.
Every band below names the zone it implements, and check_zones() asserts that
the parts in a band are the parts floorplan.py puts in that zone. The two
cannot drift apart without one of them failing.

Two properties are checked rather than eyeballed, because they are the two that
a drawing cannot show:

  * **every part has a position**, and an unmatched reference is an error and
    not a default. The same argument floorplan.check_domains() makes about
    ground: a default answers the question silently;
  * **no two courtyards overlap**, against the estimates in SIZE. DRC on the
    real board is the authority and this is the fast version of it: the first
    placement drew 262 violations, of which 25 were courtyards and the rest
    were what a collision does to silk and mask, and finding those through
    KiCad is a minute a time where finding them here is a second.

The grid: twelve rows on a 7.62 mm pitch, two per channel. The odd row carries
that channel's audio path west to east, the even row carries its CV filter and
its envelope detector. Quad packages serve four channels each, so they sit in
their own columns spanning the rows they feed -- which is why the columns are
declared as x positions and the packages as (x, y) pairs.
"""

import re

import design
import floorplan

# The grid. 7.62 mm is three times the 2.54 the connectors use and twice the
# 3.81 an 0805 needs with clearance -- and it is the pitch at which a SOIC-14
# body (8.7 mm long, 3.9 wide) fits between two rows without its courtyard
# reaching either.
ROW_PITCH = 7.62
AUDIO_ROW_0 = 12.0
CV_ROW_0 = AUDIO_ROW_0 + design.CHANNELS * ROW_PITCH + 14.0
MARGIN = 5.0

# **The two bands are not interleaved, and the first version was.** Twelve rows
# alternating audio and CV put every quad package's body across the rows it does
# not serve: U1 spans four audio rows, which with interleaving means crossing
# three CV rows, and its footprint landed on their resistors. DRC found it 25
# times over. Separate bands cost nothing in area -- the same rows, in two
# groups -- and mean a package only ever crosses rows of its own kind.

# Courtyard estimates, width x height in the footprint's own orientation.
# Approximate, and DRC is the authority: this table exists so that a placement
# can be iterated in a second rather than in a KiCad round trip, which is the
# same reason floorplan.COURTYARD exists.
SIZE = {
    "R_0805": (2.4, 1.7), "C_0805": (2.4, 1.7), "C_1210": (4.2, 3.2),
    "D_SOD-123": (4.0, 2.0), "SOT-23": (3.4, 3.0),
    "SOIC-8": (5.4, 6.6), "SOIC-14": (9.2, 6.6), "SOIC-16": (10.4, 6.6),
    "SOIC-20W": (13.4, 10.2),
    "PinHeader_1x02": (3.2, 6.2), "PinHeader_1x05": (13.4, 6.2),
    "TestPoint": (2.2, 2.2),
}

# West to east, and the order is floorplan.ZONES' own. Each entry is a column
# of one part per channel; the comment names the zone it implements.
COLUMNS = (
    (r"^J([1-6])$", 6.0, 0, "A0"),           # the loom, on the west edge
    (r"^R([1-6])01$", 13.0, 90, "A1"),
    (r"^R([1-6])02$", 17.0, 90, "A1"),
    (r"^C([1-6])01$", 30.0, 90, "A2"),       # 1210, the wide one
    (r"^R([1-6])11$", 35.0, 90, "A2"),
    (r"^R([1-6])15$", 39.0, 90, "A2"),
    (r"^C([1-6])02$", 43.0, 90, "A2"),
    (r"^R([1-6])21$", 58.0, 90, "A4"),
    (r"^C([1-6])21$", 62.0, 90, "A4"),
    (r"^R([1-6])31$", 76.0, 90, "A4"),
    (r"^C([1-6])31$", 80.0, 90, "A4"),
    (r"^R([1-6])32$", 84.0, 90, "A4"),
    # The CV band: filter west, envelope east.
    (r"^R([1-6])41$", 13.0, 90, "C1"),
    (r"^R([1-6])42$", 17.0, 90, "C1"),
    (r"^R([1-6])43$", 21.0, 90, "C1"),
    (r"^R([1-6])44$", 25.0, 90, "C1"),
    (r"^C([1-6])41$", 29.0, 90, "C1"),
    (r"^C([1-6])42$", 33.0, 90, "C1"),
    (r"^R([1-6])51$", 52.0, 90, "A5"),
    (r"^R([1-6])52$", 56.0, 90, "A5"),
    (r"^D([1-6])51$", 60.0, 90, "A5"),
    (r"^D([1-6])52$", 65.0, 90, "A5"),
    (r"^R([1-6])53$", 70.0, 90, "A5"),
    (r"^R([1-6])54$", 74.0, 90, "A5"),
    (r"^R([1-6])55$", 78.0, 90, "A5"),
    (r"^C([1-6])51$", 82.0, 90, "A5"),
)

# Which rows a column's parts sit on. The audio path is on the odd row of each
# channel and everything else on the even one, so the two never share copper
# with a neighbour's row by accident.
CV_BAND_ZONES = frozenset({"C1", "A5"})

# The packages, each spanning the channels its sections serve. y is the middle
# of that span, computed rather than typed -- move a section in design.SECTIONS
# and the package follows it.
PACKAGE_X = {
    "U1": 23.0, "U2": 23.0,          # front ends, A1
    "U3": 68.0, "U4": 68.0,          # I-V, A4
    "U5": 91.0, "U6": 91.0,          # servo, A4
    "U7": 40.0, "U8": 40.0,          # CV filters, C1
    "U9": 50.0, "U10": 50.0,         # the VCAs, A3
    "U13": 89.0, "U14": 89.0,        # envelope half-wave, A5
}

# The VCAs carry no op-amp sections, so their rows come from design.VCA_CELL.

# The shared block, south of the twelve rows, and **it is arranged around the
# ground split rather than around the parts.** floorplan.py's whole boundary
# argument is that one line separates two return currents and exactly three
# things cross it; the cheapest way to make that true on copper is to put the
# line somewhere straight and keep the straddlers on it.
#
# So: analogue shared parts north of SPLIT_Y, digital south of it, and the four
# parts that genuinely span both -- the '541, the three bypass relays and the
# star R902 -- centred on the line itself.
SHARED_Y = CV_ROW_0 + design.CHANNELS * ROW_PITCH + 10.0
SPLIT_Y = SHARED_Y + 30.0
GROUND_GAP = 2.0

SHARED = {
    # Zone R, the reference and its inverter.
    "U12": (14.0, SHARED_Y, 90),
    "C801": (22.0, SHARED_Y, 90),
    "C802": (26.0, SHARED_Y, 90),
    "C803": (30.0, SHARED_Y, 90),
    "R801": (36.0, SHARED_Y, 90),
    "R802": (40.0, SHARED_Y, 90),
    # At the inverter's own output pin: what D803 clamps is that amplifier, and
    # a long run would clamp the trace instead.
    "D803": (44.0, SHARED_Y, 90),

    # Zone A0, the bond and the one bridge constraint 2 allows.
    "J7": (6.0, SHARED_Y + 10.0, 0),
    "R901": (6.0, SHARED_Y + 16.0, 90),

    # On the line: the two straddling kinds and the module's own star.
    "U11": (20.0, SPLIT_Y, 90),
    # **270, not 90, and it is the one rotation on this board that carries a
    # net each way.** design.py puts MAGND on pin 1 of both stars; at 90
    # degrees pin 1 lands *south* of the split, which is the digital pour, and
    # pin 2 lands north in the analogue one. Both stitch stubs then cross the
    # line to reach their own plane, crossing each other on the way -- the last
    # two DRC violations on the first routed board, and the only ones that were
    # a design fault rather than a router one.
    "R902": (6.0, SPLIT_Y, 270),
    "K801": (44.0, SPLIT_Y, 0),
    "K802": (62.0, SPLIT_Y, 0),
    "K803": (80.0, SPLIT_Y, 0),

    # Zone F south of the line: the pump, the sink and the flybacks. The coils
    # are north of them at the relays; nothing here carries audio.
    "C805": (40.0, SPLIT_Y + 10.0, 90),
    "D801": (44.0, SPLIT_Y + 10.0, 90),
    "D802": (48.0, SPLIT_Y + 10.0, 90),
    "C806": (52.0, SPLIT_Y + 10.0, 90),
    "R803": (56.0, SPLIT_Y + 10.0, 90),
    "Q801": (60.0, SPLIT_Y + 10.0, 0),
    "D813": (66.0, SPLIT_Y + 10.0, 90),
    "D823": (70.0, SPLIT_Y + 10.0, 90),
    "D833": (74.0, SPLIT_Y + 10.0, 90),

    # Zone D2, the connectors, on the south edge where a loom can reach them.
    "J8": (10.0, SPLIT_Y + 18.0, 0),
    "J9": (26.0, SPLIT_Y + 18.0, 0),
    "J10": (42.0, SPLIT_Y + 18.0, 0),
    "J11": (58.0, SPLIT_Y + 18.0, 0),
}

# The pull-downs sit at the controller connector, which is where their whole
# argument is: a hi-Z MCU has to read as a defined low at the pin it left.
PULLDOWN_X = 74.0
PULLDOWN_Y = SPLIT_Y + 18.0

# Designators that have to move, with the reason each one does. The mixer keeps
# the same table and for the same cause: KiCad puts a reference above the body,
# which after a 90-degree rotation is *west* of it, and west of the VCAs is the
# stability capacitor 7 mm away. Six DRC violations, all of them one text field
# on two pads.
REFERENCE_MOVES = {"U9": (8.0, 0.0), "U10": (8.0, 0.0)}

# The parts with no footprint, because they are not chosen: their area is
# reserved rather than placed. gen_pcb.py draws the rectangle.
RESERVED = {"K801": (14.0, 9.0), "K802": (14.0, 9.0),
            "K803": (14.0, 9.0)}

# Rail decoupling, two rows of twelve rather than one of twenty-four: a single
# row is 84 mm long and would set the board's width on its own.
BYPASS_X = 8.0
BYPASS_Y = SHARED_Y + 16.0


def row(n, cv=False):
    """The y of channel n's row, in the audio band or the CV/envelope band."""
    return (CV_ROW_0 if cv else AUDIO_ROW_0) + (n - 1) * ROW_PITCH


CV_ROLES = frozenset({"cv", "env_a", "env_b"})


def _package_rows(ref):
    """Every row a package's sections reach, as y values.

    Per *section*, not per channel, and that distinction is a bug this file
    already had: U6 carries servos 5 and 6 in the audio band and envelope
    summing stages 5 and 6 in the CV band, so a channel-keyed lookup saw
    channel 5 twice and kept whichever answer it read last. The package landed
    in the CV band and left its servos 60 mm away.

    A package that genuinely serves both bands -- U2, U4 and U6 do, because
    their spare sections took the envelope summing stages -- lands between
    them, which is where a part belonging to both belongs. That is the
    placement cost of filling those sections, and the alternative was two more
    OPA1644.
    """
    # "spare" is excluded, and it is not a detail: SECTIONS keys spare
    # sections (role, index), so U14's two terminated followers read as
    # channels 1 and 2 and dragged the package into the audio band -- a
    # placement decided by a loop counter. A spare has no channel, which is
    # what makes it spare.
    rows = [row(n, role in CV_ROLES)
            for (role, n), (pkg, _) in design.SECTIONS.items()
            if pkg == ref and role != "spare" and isinstance(n, int)
            and 1 <= n <= design.CHANNELS]
    rows += [row(n) for n, (pkg, _) in design.VCA_CELL.items() if pkg == ref]
    return sorted(rows)


def position(ref):
    """(x, y, rotation) for one reference, or None if nothing claims it."""
    for pattern, x, rotation, zone in COLUMNS:
        found = re.match(pattern, ref)
        if found:
            return (x, row(int(found.group(1)), zone in CV_BAND_ZONES),
                    rotation)

    if ref in PACKAGE_X:
        rows = _package_rows(ref)
        if not rows:                      # nothing per-channel: shared only
            return (PACKAGE_X[ref], row(3), 90)
        # **A package that reaches both bands goes in the gap between them,
        # not at the average of its rows.** The average is inside one band or
        # the other, on a row it does not serve, and it lands on that row's
        # parts -- which is what U4 and U6 did. The gap is 21.6 mm and a
        # SOIC-14 on its side is 9.2, so the middle of it clears both.
        if rows[0] < CV_ROW_0 <= rows[-1]:
            top = row(design.CHANNELS)
            return (PACKAGE_X[ref], round((top + CV_ROW_0) / 2, 2), 90)
        return (PACKAGE_X[ref], round((rows[0] + rows[-1]) / 2, 2), 90)

    if ref in SHARED:
        return SHARED[ref]

    found = re.match(r"^R81([1-6])$", ref)
    if found:
        return (PULLDOWN_X + 4.0 * (int(found.group(1)) - 1), PULLDOWN_Y, 90)

    found = re.match(r"^C7(\d\d)$", ref)
    if found:
        index = int(found.group(1)) - 1
        return (BYPASS_X + 3.5 * (index % 12),
                BYPASS_Y + 4.0 * (index // 12), 90)

    return None


def outline():
    """The board rectangle this placement implies, from SIZE alone.

    gen_pcb.py computes the same thing from the footprints KiCad actually
    loads, and the two agreeing is worth something: it means this file can be
    reasoned about without KiCad, which is the reason it exists.
    """
    boxes = [courtyard(ref) for ref in sorted(design.PARTS)]
    boxes = [box for box in boxes if box]
    return (round(min(b[0] for b in boxes) - MARGIN, 2),
            round(min(b[1] for b in boxes) - MARGIN, 2),
            round(max(b[2] for b in boxes) + MARGIN, 2),
            round(max(b[3] for b in boxes) + MARGIN, 2))


def area():
    left, top, right, bottom = outline()
    return (right - left) * (bottom - top)


def extents(courtyards):
    """The board outline the placement implies, plus a margin.

    Derived rather than declared: a rectangle typed in by hand is a rectangle
    that stops being true the first time a part moves, and this repo has spent
    two passes on the consequences of exactly that in floorplan.py.
    """
    xs = [x for x, y, w, h in courtyards]
    ys = [y for x, y, w, h in courtyards]
    right = max(x + w / 2 for x, y, w, h in courtyards)
    bottom = max(y + h / 2 for x, y, w, h in courtyards)
    left = min(x - w / 2 for x, y, w, h in courtyards)
    top = min(y - h / 2 for x, y, w, h in courtyards)
    return (round(left - MARGIN, 2), round(top - MARGIN, 2),
            round(right + MARGIN, 2), round(bottom + MARGIN, 2))


def check_placed():
    """Every part has a position, and an unmatched reference is an error."""
    return [f"{ref} has no position in placement.py -- add it to a column, to "
            f"SHARED, or say why it is not on the board"
            for ref in sorted(design.PARTS) if position(ref) is None]


def courtyard(ref):
    """(left, top, right, bottom) for one part, from SIZE and its rotation."""
    spot = position(ref)
    if spot is None:
        return None
    x, y, rotation = spot
    footprint = design.PARTS[ref].footprint
    if footprint is None:
        width, height = RESERVED.get(ref, (14.0, 9.0))
    else:
        for token, size in SIZE.items():
            if token in footprint:
                width, height = size
                break
        else:
            return None
    if rotation % 180:
        width, height = height, width
    return (x - width / 2, y - height / 2, x + width / 2, y + height / 2)


def check_overlaps():
    """No two courtyards overlap, against the estimates in SIZE."""
    problems = []
    boxes = [(ref, courtyard(ref)) for ref in sorted(design.PARTS)]
    boxes = [(ref, box) for ref, box in boxes if box]
    for index, (ref, box) in enumerate(boxes):
        for other, box2 in boxes[index + 1:]:
            if (box[0] < box2[2] and box2[0] < box[2]
                    and box[1] < box2[3] and box2[1] < box[3]):
                problems.append(
                    f"{ref} and {other} overlap: "
                    f"{tuple(round(v, 1) for v in box)} against "
                    f"{tuple(round(v, 1) for v in box2)}")
    return problems


def check_zones():
    """Every column's parts are in the ground domain its zone declares.

    The check that ties this file to floorplan.py rather than leaving them to
    agree by good intentions. A column that implements zone A5 must contain
    parts floorplan.DOMAINS puts in the analogue domain; if somebody moves a
    part between blocks in design.py and not here, the two disagree and this
    says which.
    """
    problems = []
    domains = {tag: domain for tag, _, domain, _, _ in floorplan.ZONES}
    for pattern, _, _, zone in COLUMNS:
        if zone not in domains:
            problems.append(f"column {pattern} names zone {zone}, which is not "
                            f"in floorplan.ZONES")
            continue
        for ref in sorted(design.PARTS):
            if not re.match(pattern, ref):
                continue
            actual = floorplan.domain_of(ref)
            if domains[zone] != "STRADDLE" and actual != domains[zone]:
                problems.append(
                    f"{ref} is placed in zone {zone} ({domains[zone]}) and "
                    f"floorplan.py puts it on {actual}")
    return problems


def main():
    print("placement")
    problems = check_placed() + check_zones() + check_overlaps()
    print(f"  every part has a position              "
          f"{'ok' if not check_placed() else 'FAIL'}")
    print(f"  columns agree with floorplan zones     "
          f"{'ok' if not check_zones() else 'FAIL'}")
    overlaps = check_overlaps()
    print(f"  no two courtyards overlap              "
          f"{'ok' if not overlaps else str(len(overlaps)) + ' FAIL'}")
    for problem in problems[:12]:
        print(f"      {problem}")
    if len(problems) > 12:
        print(f"      ... and {len(problems) - 12} more")
    left, top, right, bottom = outline()
    print(f"  {len(design.PARTS)} parts, {design.CHANNELS} rows per band on a "
          f"{ROW_PITCH} mm pitch, shared block at y = {SHARED_Y:.1f}")
    print(f"  outline {right - left:.1f} x {bottom - top:.1f} mm = "
          f"{area():.0f} mm2")
    if problems:
        raise SystemExit(f"{len(problems)} problems")


if __name__ == "__main__":
    main()
