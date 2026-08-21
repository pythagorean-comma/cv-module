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

import math
import re

import design
import floorplan
import rules

# The grid. 7.62 mm is three times the 2.54 the connectors use and twice the
# 3.81 an 0805 needs with clearance -- and it is the pitch at which a SOIC-14
# body (8.7 mm long, 3.9 wide) fits between two rows without its courtyard
# reaching either.
# ---------------------------------------------------------------------------
# How close two parts may be, and it is a judgement rather than a standard
# ---------------------------------------------------------------------------
#
# **Declared, not derived, and saying which is the point.** This repository has
# no first-hand source for hand-assembly spacing and is not going to pretend
# otherwise: KiCad's courtyards are IPC-7351 *nominal*, which already embeds an
# assembly clearance, so courtyard-to-courtyard zero is that standard's own
# minimum -- for a machine. How much more a person with tweezers and an iron
# wants is not in any document this project has read. What follows is a
# judgement, taken deliberately, against stated operating assumptions:
#
#     average dexterity, good tools, and a digital magnification screen.
#
# **The magnification is the assumption that does the least work and it is
# worth saying so.** A microscope buys *seeing*, not *reaching*. It makes a
# 0.65 mm pin row placeable and inspectable, and it does nothing whatever
# about whether an iron tip fits between two parts. So none of the numbers
# below are relaxed by having one; they are set by what has to physically get
# in, and the screen is why the finest package on the board is a job rather
# than a problem.
#
# **What has to get in, per class, which is why one number would be wrong:**
#
#   * two passives side by side are placed with tweezers and soldered at their
#     *outer* ends, so the gap between them is a placement clearance and not an
#     iron clearance. It is the smallest figure here;
#   * an IC's pin row is drag-soldered along its length, and wants flux, braid
#     and a tip travelling beside it. Much more room, and it is the number that
#     most often gets forgotten because the *pads* look reachable;
#   * a tall part blocks a neighbour's approach *angle* rather than its
#     footprint -- you bring tweezers down at forty-odd degrees, not straight
#     down -- and hot-air rework on one reaches several millimetres of its
#     neighbours. Relays, the converter brick, the choke, the DPAK;
#   * the module is soldered at its castellations, with the iron coming in
#     **horizontally** along its edge. That is the largest clearance on the
#     board and the only one that is about a tool's whole shaft rather than
#     its tip;
#   * a through-hole part is soldered from the far side, so its top-side
#     neighbours barely matter.
#
# **Err generous, because of what being wrong costs.** Too loose is a board a
# few millimetres bigger. Too tight is discovered with a part in the tweezers
# and a fabricated board on the bench, and the fix is a re-place and a re-route
# -- so the asymmetry is total and these are rounded up rather than down.
GAP_MM = {
    "passive": 0.6,        # 0805, SOD-123, SOT-23, SOT-523
    "ic": 1.5,             # SOIC, TSSOP, SO-6L -- a drag-solder lane
    "tall": 2.0,           # relays, the TMR brick, the choke, the DPAK
    "module": 3.0,         # the Pico's castellated edges, iron in sideways
    "through_hole": 1.0,   # soldered from the other side
}
# Which class a footprint is in, longest token first for the reason
# placement.SIZE matches that way -- a substring table whose order is
# load-bearing is a table that will be wrong.
GAP_CLASS = (
    ("RaspberryPi_Pico", "module"),
    ("PinHeader", "through_hole"),
    ("TRACO", "tall"), ("Relay_", "tall"), ("L_CommonMode", "tall"),
    ("TO-252", "tall"), ("L_Bourns", "tall"),
    # **("Fuse_", "tall") was here and it was wrong the moment it was
    # used.** GAP_MM["tall"] is about a part that blocks a neighbour's
    # approach angle -- a relay, the converter brick, the choke, the
    # DPAK, all 6.5 mm and up. The fitted fuse is a 3 mm ceramic tube,
    # the height of a 1210 capacitor, placed with tweezers and soldered
    # at its outer ends: a passive, which is the default, so the row is
    # deleted rather than corrected. It cost nothing while no fuse was
    # fitted, which is exactly why it survived to be used.
    ("TSSOP", "ic"), ("SOIC", "ic"), ("SO-6L", "ic"), ("SOP-16", "ic"),
    ("TestPoint", "passive"),
)


def gap_class(ref):
    """Which assembly class a part is in. Defaults to passive."""
    footprint = design.PARTS[ref].footprint or ""
    for token, name in GAP_CLASS:
        if token in footprint:
            return name
    return "passive"


def required_gap(a, b):
    """The larger of the two parts' own requirements.

    **The larger and not the smaller, and not an average.** The gap exists so
    that a tool can reach one of the two; if either of them needs a
    drag-solder lane then the space between them is that lane, whatever the
    other one is. An 0805 pushed up against a TSSOP does not make the TSSOP
    easier to solder.
    """
    return max(GAP_MM[gap_class(a)], GAP_MM[gap_class(b)])


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

# Courtyard boxes, width x height in the footprint's own orientation, read off
# the F.CrtYd outline of each footprint this design names. This table exists so
# that a placement can be iterated in a second rather than in a KiCad round
# trip, which is the same reason floorplan.COURTYARD exists.
#
# **Centrelines, not KiCad's BBox(), and the difference decides a check.**
# GetCourtyard().BBox() comes back 0.09 mm larger in each axis on every
# footprint here -- half a 0.05 mm courtyard line on each side, plus a little
# from polygonising the corners outward. DRC's courtyards_overlap rule compares
# the outlines, so the outlines are what check_overlaps() has to compare: with
# the BBox figures it reports C701 and R901 overlapping by 0.02 mm, on a
# placement KiCad passes, because it counts one courtyard line twice.
# COURTYARD_TOLERANCE_MM below is that 0.09 written down once.
#
# **Every multi-pin entry here used to be transposed, and the word
# "approximate" was carrying it.** The table said it was estimates and that DRC
# was the authority, which is a fair thing to say about a body dimension
# rounded down by a millimetre -- and it was also being used to excuse
# SOIC-14 at (9.2, 6.6) when KiCad's courtyard is 7.49 wide and 9.25 tall. A
# rounded number is approximate. A number on the wrong axis is wrong, and no
# amount of "DRC is the authority" makes a transposed box a conservative one:
# it is smaller than the part in one direction.
#
# It survived because every consumer was transposed too. check_overlaps()
# compares these boxes against each other, so two parts modelled sideways
# collide with each other exactly as they would have upright, and the layout is
# a grid of rows and columns generous enough that the difference never crossed
# a threshold. It surfaced the first time a part had to be fitted into a gap --
# J8, below -- where the model reported a collision that does not exist and
# hid one that does.
#
# The numbers are KiCad's, to two decimals, including the courtyard line width
# that BBox() includes. check_courtyards() in gen_pcb.py is what now holds them
# there: it is the only place both this table and the real footprint exist at
# once.
SIZE = {
    "R_0805": (3.36, 1.90), "C_0805": (3.40, 1.96), "C_1210": (4.60, 3.20),
    "D_SOD-123": (4.70, 2.30), "D_SOD-123F": (4.40, 2.30),
    "SOT-23": (3.86, 3.40), "SOT-523": (2.30, 2.10),
    "Relay_DPDT_Omron_G6S-2F": (10.70, 15.30),
    "SOIC-8": (7.40, 5.40), "SOIC-14": (7.40, 9.16), "SOIC-16": (7.40, 10.40),
    # The supply's four. The first is this repo's own footprint rather than
    # KiCad's -- gen_project.footprint_library() writes it from the datasheet
    # drawing -- and gen_pcb.check_courtyards() is still what holds this row
    # against it, which matters *more* for a generated footprint and not less:
    # two files this repo controls can be wrong together.
    "TRACO_TMR-6-xxxxWI": (22.30, 9.60),
    # The inlet choke, and it is read off KiCad's own courtyard like every
    # other row here -- 10.090 x 6.590 of bounding box, less the 0.045 per
    # edge that is the outline's line width. The four-terminal chokes draw
    # that courtyard as a polyline rather than a rectangle, which turns out
    # not to matter: gen_pcb.check_courtyards() reads BBox() and KiCad builds
    # the polygon from whatever closed outline is on the layer. See
    # design.CHOKE_FP.
    "L_CommonMode_Wuerth_WE-SL2": (10.00, 6.50),
    "TSSOP-20": (7.70, 7.00),
    "TO-252-2": (11.10, 7.00), "D_SMA": (7.00, 3.50),
    # **The inlet fuse, and "Fuse_1206": (4.56, 2.26) was here instead.**
    # That entry was written when a 1206 fuse was the shape being drawn
    # around, and no fuse was ever fitted -- so a table row described a
    # part nothing had, for four passes, and could not be wrong. The part
    # that arrived is a 3 x 10.1 mm ceramic tube, near enough three times
    # the length. Read off KiCad's own F.CrtYd like every other row here.
    "Fuse_Schurter_UMT250": (11.40, 4.26),
    "SOIC-20W": (11.86, 13.30),
    "PinHeader_1x02": (3.54, 6.09), "PinHeader_1x03": (3.54, 8.62),
    "PinHeader_1x05": (3.54, 13.70),
    "TestPoint": (3.00, 3.00),
    # The controller block, every one read off KiCad's own F.CrtYd rather than
    # off a body dimension -- which is the distinction the choke's comment
    # above makes and the reason the SO-6L is 11.3 mm wide against a 10 mm
    # body: it is a creepage package and the courtyard is where the creepage
    # lives.
    "SOT-23-6": (4.10, 3.40), "SO-6L": (11.30, 4.34),
    "L_Bourns_SRN6045TA": (7.00, 6.50),
    # **The module, and it is the largest courtyard on the board by four
    # times.** 23.08 x 53.85 mm, read off Module:RaspberryPi_Pico_SMD_
    # HandSolder's own F.CrtYd -- against a 21 x 51 mm board, so a millimetre
    # of it either side is the hand-solder pad extension and the USB
    # overhang. That is 1243 mm2, where the QFN it replaces was 68.
    "RaspberryPi_Pico": (23.08, 53.85),
}

# Where a footprint's anchor sits inside its own courtyard, in the footprint's
# orientation. Zero for everything KiCad centres on the body, and not zero for
# a pin header, whose anchor is pad 1 at one end -- 5.08 mm for the 1x05, which
# is two thirds of its length. courtyard() centred every part on its position
# and so drew the headers 5 mm north of where they are.
ANCHOR = {"PinHeader_1x02": (0.0, 1.275), "PinHeader_1x03": (0.0, 2.54),
          "PinHeader_1x05": (0.0, 5.08),
          # The micro-B's courtyard is not centred on its anchor: the shell
          # overhangs the pads to the south by 0.59 mm.
          "USB_Micro-B": (0.0, 0.59),
          # Anchored on pad 1, the convention every Converter_DCDC footprint
          # in KiCad uses and therefore the one this one is written to.
          "TRACO_TMR-6-xxxxWI": (8.90, 1.05),
          # The DPAK's tab is pad 2 and the anchor is not the body's middle.
          "TO-252-2": (-0.84, 0.0),
          # The G6S-2F's courtyard is not quite centred on its anchor.
          "Relay_DPDT_Omron_G6S-2F": (0.0, -0.05),
          # The Pico's courtyard is 0.375 mm north of its anchor, because the
          # micro-USB overhangs the north edge and the hand-solder pads do
          # not extend past the south one.
          "RaspberryPi_Pico": (0.0, -0.375)}

# How far a box above may sit inside the bounding box KiCad computes for the
# same footprint. Not a fudge factor: it is the courtyard line, measured at
# 0.045 mm per edge on every one of the twelve footprints this design uses, and
# 0.06 is that with a little room. gen_pcb.check_courtyards() is the only place
# both numbers exist at once, and it is what would have caught the transposed
# entries the first time the board was built.
COURTYARD_TOLERANCE_MM = 0.06


# ---------------------------------------------------------------------------
# The two packers, and they are what check_courtyard_gap() failed for
# ---------------------------------------------------------------------------
#
# **Both exist because the fix for a gap violation is arithmetic and was being
# done by hand.** The last pass moved seven columns by odd amounts and got 41
# violations to 23; what it could not do is answer "and why is *that* part
# where it is", because the answer was "it was nudged until the number went
# down". These two functions are that nudging, written out: a row is laid west
# to east with each part one required_gap() from the last, and a band sits as
# far north as the band above it allows. Every coordinate they produce names
# the pair that set it.
#
# **They are deliberately not a solver.** Nothing here searches, minimises or
# scales: a chain is packed in the order it is declared, and a band is pushed
# by exactly one named neighbour. The dead ends the last pass paid for were
# both the other thing -- sweeping ROW_PITCH took 41 to 53, and a blanket
# column scale cleared violations while moving parts that were fine, which
# expresses nothing about why any of them moved.


def _extent(ref, rotation):
    """(dx, dy, width, height) of a part's courtyard about its own anchor.

    The half of courtyard() that does not need a position, so that a packer
    can ask how big a part is before deciding where to put it. Splitting it
    out is what stops the packers holding a second opinion about a footprint's
    size -- the fault gen_pcb.escape_plan() was written out of, one repo pass
    ago, where two files computed the same criterion and disagreed.
    """
    footprint = design.PARTS[ref].footprint
    if footprint is None:
        raise KeyError(f"{ref} has no footprint, so it has no extent")
    # **Longest token first, and that is not tidiness.** These are substring
    # matches, and "D_SOD-123" is a substring of "D_SOD-123F" -- so with plain
    # dict order the low-drop clamp at D803 would silently be measured as the
    # 0.3 mm wider package it replaced, and the only thing that would ever
    # have said so is gen_pcb.check_courtyards(). Matching the most specific
    # token means the table can gain a variant without its position in the
    # dict becoming load-bearing.
    for token in sorted(SIZE, key=len, reverse=True):
        if token in footprint:
            width, height = SIZE[token]
            offset = ANCHOR.get(token, (0.0, 0.0))
            break
    else:
        raise KeyError(f"{ref}: nothing in SIZE matches {footprint}")
    radians = math.radians(rotation)
    cosine, sine = math.cos(radians), math.sin(radians)
    if rotation % 180:
        width, height = height, width
    return (offset[0] * cosine + offset[1] * sine,
            -offset[0] * sine + offset[1] * cosine, width, height)


def pack_east(chain, start_x):
    """Lay a row west to east, each part one required_gap from the one before.

    `chain` is ((ref, rotation), ...) in west-to-east order and the first
    part's x is `start_x`; every other x is the previous part's east edge plus
    the gap the larger of the two classes asks for. The result is a dict, so
    the row reads as coordinates and is still a function of GAP_MM.

    **What it does not do is decide the order.** That is the design -- the
    inlet is at the west edge because it is an inlet, and the choke is next to
    it because design.supply() says the decoupling has to be on the converter
    side of it. This spaces a sequence somebody else chose.
    """
    positions, edge, previous = {}, None, None
    for ref, rotation in chain:
        dx, _, width, _ = _extent(ref, rotation)
        if previous is None:
            x = start_x
        else:
            x = edge + required_gap(previous, ref) + width / 2 - dx
        positions[ref] = x
        previous, edge = ref, x + dx + width / 2
    return positions


def east_edge_at(ref, rotation, edge_x):
    """The x that puts a part's own east courtyard edge on a given line.

    For the one class of part whose position is the *outline* rather than a
    neighbour: a receptacle has to be reachable by a plug, so what is declared
    is which line it sits on and the coordinate follows. check_edge_parts()
    is the other half and the reason this cannot be a literal -- a connector
    placed as far east as anything else is still five millimetres inside the
    board, and it draws, routes and passes DRC exactly like one that works.
    """
    dx, _, width, _ = _extent(ref, rotation)
    return edge_x - dx - width / 2


def clear_south(north, south, dx=0.0):
    """Centre-to-centre y separation two parts need, at a horizontal offset.

    Each argument is a `(ref, rotation)` pair. `dx` is how far apart the two
    courtyards already are in x, because check_courtyard_gap() measures the
    diagonal -- two parts one class apart in x need no separation in y at all,
    and the packing arithmetic has to agree with the check or it is solving a
    different problem.

    Used to stack the bands south of the relay row, one band per line, each
    naming the single pair that sets it. That the *named* pair is the binding
    one is not asserted here and does not need to be: check_courtyard_gap()
    walks every pair on the board, so a band derived from the wrong neighbour
    fails immediately and says which pair it should have been.
    """
    _, north_dy, _, north_h = _extent(*north)
    _, south_dy, _, south_h = _extent(*south)
    need = required_gap(north[0], south[0])
    reach = math.sqrt(max(need * need - dx * dx, 0.0))
    return north_dy + north_h / 2 + reach + south_h / 2 - south_dy


# West to east, and the order is floorplan.ZONES' own. Each entry is a column
# of one part per channel; the comment names the zone it implements.
# **Seven of these moved to satisfy GAP_MM, none by more than 1.1 mm, and the
# 4 mm column pitch was never the problem.** That pitch gives an 0805 2.1 mm of
# clearance. What it does not account for is that a quad package is 9.2 mm wide
# and spans two rows, so a column beside one is beside something twelve times
# its own width: R{n}02 had 0.4 mm to U1's courtyard against the 1.5 mm a
# drag-solder lane wants. Solved against check_courtyard_gap() rather than
# eyeballed, which is why they are odd numbers.
COLUMNS = (
    (r"^J([1-6])$", 6.0, 0, "A0"),           # the loom, on the west edge
    (r"^R([1-6])01$", 13.0, 90, "A1"),
    (r"^R([1-6])02$", 15.9, 90, "A1"),
    (r"^C([1-6])01$", 30.8, 90, "A2"),       # 1210, the wide one
    (r"^R([1-6])11$", 35.0, 90, "A2"),
    (r"^R([1-6])15$", 39.0, 90, "A2"),
    (r"^C([1-6])02$", 42.2, 90, "A2"),
    (r"^R([1-6])21$", 58.0, 90, "A4"),
    (r"^C([1-6])21$", 60.8, 90, "A4"),
    (r"^R([1-6])31$", 76.0, 90, "A4"),
    (r"^C([1-6])31$", 80.0, 90, "A4"),
    (r"^R([1-6])32$", 83.9, 90, "A4"),
    # The CV band: filter west, envelope east.
    (r"^R([1-6])41$", 13.0, 90, "C1"),
    (r"^R([1-6])42$", 17.0, 90, "C1"),
    (r"^R([1-6])43$", 21.0, 90, "C1"),
    (r"^R([1-6])44$", 25.0, 90, "C1"),
    (r"^C([1-6])41$", 29.0, 90, "C1"),
    (r"^C([1-6])42$", 32.8, 90, "C1"),
    (r"^R([1-6])51$", 52.0, 90, "A5"),
    (r"^R([1-6])52$", 56.0, 90, "A5"),
    (r"^D([1-6])51$", 60.0, 90, "A5"),
    (r"^D([1-6])52$", 65.0, 90, "A5"),
    (r"^R([1-6])53$", 70.0, 90, "A5"),
    (r"^R([1-6])54$", 74.0, 90, "A5"),
    (r"^R([1-6])55$", 78.0, 90, "A5"),
    (r"^C([1-6])51$", 81.8, 90, "A5"),
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

# ---------------------------------------------------------------------------
# The southern band stack: seven rows, each as far north as the one above
# allows
# ---------------------------------------------------------------------------
#
# **Everything south of the bypass relays is one stack and it was over-packed
# by seven millimetres.** The rows were placed one at a time over five passes,
# each against the parts that happened to be there, and by the time the module
# and the inlet choke were in it there were 23 courtyard-gap violations spread
# across six rows -- with no way to say which row was in the wrong place,
# because every row's y was an absolute number.
#
# Each anchor below is the row above it plus `clear_south()` of the one pair
# that binds, so the answer to "why is this row here" is the pair named on its
# own line. What that costs is board length: the stack is 3.66 mm longer than
# it was and the module goes 1.05 mm further south with it, for 109 mm2 --
# **0.5 % of a board already 3.8x the enclosure it does not fit.** Millimetres
# in y are the cheapest thing this design has, and assembly comfort is what
# they are being spent on.
#
# **The pair on each line is a claim, not an assertion, and that is deliberate.**
# check_courtyard_gap() walks all 290 parts against each other, so a row
# derived from the wrong neighbour is a failure with the right pair named in
# it. Deriving *and* asserting the same fact from the same table would be one
# instrument covering for another.
#
# **It has already earned that once.** The supply row's pair was C841 / C810
# until F801 was fitted; the fuse lengthened the row, U15 and ISOLATION_X went
# east with it, and C810 slid out from under an 0805 and under a 1210 -- which
# is 0.6 mm taller on each side. The check said "C810 and C840 are 0.00 mm
# apart" on the first run after the part went in, which is the pair, the
# distance and the direction in one line.
#
# **Reading the stack downward, with what each push actually was:**
#
#   | band     | binding pair            | moved  |
#   |----------|-------------------------|--------|
#   | failsafe | -- (the relays clear it)| 0      |
#   | pulldown | D801 / R812             | 0.03   |
#   | header   | R811 / J19              | 0.52   |
#   | panel    | J16 / R827              | 0.05   |
#   | switcher | C838 / C840             | 0.15   |
#   | supply   | C840 / C810             | 4.26   |
#   | module   | U15 / U19               | 1.65   |
#
# **The supply row's 3.66 mm is the interesting one and it is a chain of
# three.** The primary row needs 1.2 mm more than it had, so U15 moves east;
# ISOLATION_X is derived from U15's own pin 3-to-5 gap so it moves with it;
# and C810, the one declared bridge, sits on that line -- which walks it east
# into the switcher block and under C841. The band moves south to give it back
# the 0.6 mm an 0805 beside an 0805 wants. Three coordinates, one edit,
# because doing them in sequence is three placements of which two are wrong.
FAILSAFE_Y = SPLIT_Y + 10.0
PULLDOWN_Y = FAILSAFE_Y + clear_south(("D801", 90), ("R812", 90))
HEADER_Y = PULLDOWN_Y + clear_south(("R811", 90), ("J19", 0))
PANEL_Y = HEADER_Y + clear_south(("J16", 0), ("R827", 90))
SWITCHER_Y = PANEL_Y + clear_south(("C838", 90), ("C840", 90))

# Zone P, and it is the only block on this board with **two** boundaries
# through it. The ground split at SPLIT_Y separates two returns that meet at
# R902; the isolation barrier separates two returns that meet nowhere, and the
# second is a stronger statement than the first.
#
# So the band is arranged around a vertical line instead of a horizontal one.
# U15 lies along the band with its pins running west to east, primary end
# first, and ISOLATION_X falls in the 5.08 mm gap the package leaves where
# pin 4 is not -- the part's own creepage distance, used as the board's.
# Everything west of that line is referenced to IGND and has **no ground pour
# under it at all**; everything east of it is MDGND like the rest of the
# southern half. gen_pcb.build() pours the southern MDGND as two rectangles
# for exactly this reason, and verify.check_isolation() measures the gap in
# copper rather than trusting the placement.
#
# South of everything else, which is floorplan.py's "far corner from A1 and R"
# read literally: A1 is the north-west column and R crosses the middle, so the
# far corner is the south, and the band costs the board 18 mm of length it has
# plenty of. The switching part of this module is now as far from the front
# ends as the outline allows.
# **It moved 26 mm south for one pass and came straight back, and the round
# trip is worth the six lines.** The module needed 23.08 mm of a band that had
# 22.7 mm free, so the supply row was moved to make it -- which is the right
# instinct on a board that is generated and the wrong one on a board that is
# routed. Those fifteen parts carry the inlet, the isolation barrier and both
# rails, and moving them costs **11 nets and 114 connections** of re-routing,
# more than the entire controller zone it was making room for. It also moved
# ISOLATION_Y with it, so verify.check_isolation_gap() reported 656 pieces of
# primary copper outside a region that had walked away from them.
#
# The module goes in new board area instead -- see CONTROLLER below. Growing
# the outline is free here in a way that shuffling is not, which is a property
# of a hand-laid board and not of this one in particular.
#
# **And the cost that argument is built on has expired, which is worth marking
# rather than deleting.** "Moving them costs 11 nets and 114 connections of
# re-routing" was true of the board on disk at the time, which was
# `bfa4483`'s, routed. That copper is discarded by the one
# `gen_pcb.py --discard-routing` this pass runs, so for the length of this
# pass a placement move costs nothing at all -- and this row does move, 4.68
# mm east and 4.26 south, for gaps a person's iron needs. **The conclusion
# was right and its reason is dated**: the same edit made a week later, over
# hand-laid copper, is the expensive one again. A cost that depends on the
# state of an artefact somewhere else is a cost that has to be re-read, not
# quoted.
# **The row is packed west to east now and its x coordinates are a function
# of GAP_MM.** They were fourteen numbers on a 3-to-4 mm pitch, and the parts
# plus the gaps they ask for come to 91.6 mm against the 90.4 they had -- so
# six of the 23 violations were this row being 1.2 mm short of itself, in six
# different places. pack_east() lays it from the inlet, which is the one part
# whose x is a decision: J8 is at the west edge because it is the inlet.
SUPPLY_ROW = (("J8", 0), ("F801", 90), ("L801", 0), ("D804", 90),
              ("C807", 90), ("C808", 90), ("C809", 90), ("U15", 0),
              ("R804", 90), ("C811", 90), ("R805", 90), ("C812", 90),
              ("C813", 90), ("U16", 0), ("C814", 90))
INLET_X = 6.0
SUPPLY_X = pack_east(SUPPLY_ROW, INLET_X)
# Between pin 3 and pin 5, which are 5.08 mm apart because pin 4 does not
# exist. Computed rather than typed so that moving the package moves the line
# -- and this pass is the one where that mattered: the packer moved U15 4.68
# mm east and the barrier went with it.
ISOLATION_X = SUPPLY_X["U15"] + 3 * 2.54
# **C810 sits one tall-class gap north of the converter's own courtyard**, and
# that is the whole of its y. It was ISOLATION_Y + 1.5, which put it 0.77 mm
# off a 22 mm brick -- a number chosen when the barrier was drawn and never
# asked about again, on the one part that has to be exactly where it is.
ISOLATION_BRIDGE_DY = -clear_south(("C810", 0), ("U15", 0))
# The band's own row, and it is the last link of the chain the stack comment
# above describes: U15 east, ISOLATION_X east, C810 east into C841's column,
# and the band south by what an 0805 beside an 0805 asks for.
SUPPLY_Y = SWITCHER_Y + clear_south(("C840", 90), ("C810", 0)) \
    - ISOLATION_BRIDGE_DY
# **The strip the module sits in, south of everything.** U15 is 9.6 mm of
# brick and the module wants a whole iron shaft beside its castellations, so
# this is the largest single clearance on the board.
MODULE_Y = SUPPLY_Y + clear_south(("U15", 0), ("U19", 270))
# **The board's east edge, and the supply row sets it now.** outline() leaves
# MARGIN off the side an edge part faces, so the east edge is simply the
# furthest east courtyard on the board -- and fitting F801 moved that from
# U19 to C814 at the end of the packed supply row. U19 was at a literal
# x = 75.0, which was the edge until it was not: the row grew 5.9 mm and the
# module went from touching the outline to 3.8 mm inside it, which is a USB
# socket no plug reaches. Derived from the row that sets it, so the next part
# added to that row moves the module with it.
# MARGIN is on it because extents() puts it there: the outline is the
# non-edge parts plus a margin, and an edge part reaches *that* -- it does
# not set it. Leaving the margin off here is the circularity the check
# was written to break, arriving from the other side.
BOARD_EAST_X = SUPPLY_X["C814"] + _extent("C814", 90)[2] / 2 + MARGIN
# The band's northern edge. Nothing referenced to IGND sits north of this, and
# the MDGND pour stops here on the primary's side of ISOLATION_X.
ISOLATION_Y = SUPPLY_Y - 7.0
# The one part that is *meant* to cross the barrier. Declared here as well as
# in design.py because the geometric check and the netlist check are different
# claims, and this repo has been caught before by one instrument covering for
# another.
ISOLATION_BRIDGE = ("C810",)
def isolation_south():
    """The primary's region has a southern edge, and it did not use to.

    **`check_isolation_gap()` measured a quadrant: west of ISOLATION_X and
    south of ISOLATION_Y, with no bottom to it.** That was true for as long as
    the supply band was the southernmost thing on the board, which it was for
    every pass until the Pico needed a strip below it. It is not true now:
    D806 sits at x = 44, y = 221 -- 27 mm south of the supply row, in the
    digital domain, on VSYS and VMOD -- and the check reported its copper as
    *inside the primary's region*, correctly, against a region that had grown
    a tail.

    **And the pour had the same tail, which is the half that mattered.**
    gen_pcb.build() pours the southern MDGND as two overlapping rectangles so
    that the primary's corner is left bare; with no southern edge, "the
    primary's corner" was everything west of the line all the way down, so the
    module strip's western end had **no ground plane under it at all**. A
    module whose return is a plane, over board with no plane.

    The edge is one GROUND_GAP south of the southernmost primary courtyard.
    Derived rather than declared for the reason ISOLATION_X is: the row is
    packed by pack_east() and its parts move, and a boundary that has to be
    re-typed when they do is a boundary that will be wrong.
    """
    return max(courtyard(ref)[3]
               for ref in design.PRIMARY_PARTS) + GROUND_GAP


# How far east of the line a ground stitch has to be pushed to find copper.
# **Not the same number as GROUND_GAP / 2 and that is why it exists.** The pour
# starts one gap east of the line; a via placed exactly there is half its own
# diameter from the fill's edge, and the fill also keeps its clearance from the
# primary tracks running north-south beside it, so what looks like 0.6 mm of
# margin is a via sitting on an island. C810's own stitch was the one that
# found it: DRC reported a 1.6 mm track connected to nothing, which is the
# whole visible symptom of a via that landed 0.6 mm inside a boundary it needed
# to be 3 mm inside.
ISOLATION_STITCH_MM = 3.0

SUPPLY = {
    # -- primary, west of ISOLATION_X, no pour beneath ---------------------
    #
    # **The row's x comes from SUPPLY_X and its order from SUPPLY_ROW.** The
    # note this replaces said the row "moved east by 2 mm to fit L801 and the
    # board did not grow", and described where the two millimetres were taken
    # from: 2 mm out of the secondary's spacing and 2 of the 3 mm between
    # U15's east edge and R804. Both of those were gaps GAP_MM asks 2.0 for,
    # so what that pass actually did was spend the assembly clearance to avoid
    # spending board -- and it did it without an instrument, because
    # check_courtyard_gap() did not exist yet. The trade is the other way
    # round now and it is stated where it is made: this row grows east into
    # board that is free, and the band it is in grows south for the same
    # reason.
    #
    # J8 is 3 mm north of the row because a 1x02's anchor is pad 1 and the
    # part is the only through-hole one here; the choke immediately follows it
    # because design.supply() puts the decoupling on the converter's side of
    # the winding, and putting it first is worth 0 dB.
    "J8": (SUPPLY_X["J8"], SUPPLY_Y - 3.0, 0),
    # **On end, and the rotation is worth 10 mm of board width.** The fuse is
    # 3 x 10.1 mm of ceramic and the row runs west to east, so lying it along
    # the row costs 11.4 mm of row and 11 % of the board's area; standing it
    # across the row costs 4.26 mm of row and 1.95 mm of the band's northern
    # shoulder, which the stack above gives back in y. It is also what every
    # other small part in this row does -- D804 and the five capacitors are
    # all at 90 -- so the odd one out would have been the flat one.
    "F801": (SUPPLY_X["F801"], SUPPLY_Y, 90),
    "L801": (SUPPLY_X["L801"], SUPPLY_Y, 0),
    "D804": (SUPPLY_X["D804"], SUPPLY_Y, 90),
    "C807": (SUPPLY_X["C807"], SUPPLY_Y, 90),
    "C808": (SUPPLY_X["C808"], SUPPLY_Y, 90),
    "C809": (SUPPLY_X["C809"], SUPPLY_Y, 90),
    "U15": (SUPPLY_X["U15"], SUPPLY_Y, 0),
    # On the line, and the only thing that is. Offset east by half a pad so
    # that its MDGND end lands inside the pour and its IGND end does not; its
    # y is ISOLATION_BRIDGE_DY, which is the converter's courtyard and not the
    # band edge.
    "C810": (ISOLATION_X + 0.6, SUPPLY_Y + ISOLATION_BRIDGE_DY, 0),
    # -- secondary, east of the package ------------------------------------
    "R804": (SUPPLY_X["R804"], SUPPLY_Y, 90),
    "C811": (SUPPLY_X["C811"], SUPPLY_Y, 90),
    "R805": (SUPPLY_X["R805"], SUPPLY_Y, 90),
    "C812": (SUPPLY_X["C812"], SUPPLY_Y, 90),
    "C813": (SUPPLY_X["C813"], SUPPLY_Y, 90),
    "U16": (SUPPLY_X["U16"], SUPPLY_Y, 0),
    "C814": (SUPPLY_X["C814"], SUPPLY_Y, 90),
}

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
    # **5.47 and not 6.0, which is C701's west edge less a passive gap.**
    # 7.02 - GAP_MM["passive"] - 0.95 = 5.47. It comes off the x = 6.0 column
    # J7 and R902 share, which is alignment and not a requirement -- see
    # BYPASS_X for the version of this that moved the other part instead.
    "R901": (5.47, SHARED_Y + 16.0, 90),

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
    # 90 degrees, so the long axis runs east-west along the split rather
    # than across it: at 0 the body is 15.3 mm tall and reaches both the
    # bypass decoupling row to the north and the pump to the south.
    "K801": (44.0, SPLIT_Y, 90),
    "K802": (62.0, SPLIT_Y, 90),
    "K803": (80.0, SPLIT_Y, 90),

    # Zone F south of the line: the pump, the sink and the flybacks. The coils
    # are north of them at the relays; nothing here carries audio.
    "C805": (40.0, FAILSAFE_Y, 90),
    "D801": (44.0, FAILSAFE_Y, 90),
    "D802": (48.0, FAILSAFE_Y, 90),
    "C806": (52.0, FAILSAFE_Y, 90),
    "R803": (56.0, FAILSAFE_Y, 90),
    "Q801": (60.0, FAILSAFE_Y, 0),
    "D813": (66.0, FAILSAFE_Y, 90),
    "D823": (70.0, FAILSAFE_Y, 90),
    "D833": (74.0, FAILSAFE_Y, 90),

    # **J8 was here, and it moved twice for opposite reasons.** It was filed
    # with J9-J11 as a connector, was found to be a straddler carrying both
    # rails and both grounds, and was moved onto the ground split so that each
    # of its five pins landed in its own pour. It is a two-way *primary* inlet
    # now -- see design.supply() -- so it straddles nothing, and it lives in
    # SUPPLY above with the rest of the isolated side.
    #
    # The mechanism that correction turned on is worth keeping even though the
    # part it applied to is gone, because the next through-hole part in the
    # wrong pour will hit it: stitch_grounds() skips through-hole pads on the
    # correct reasoning that a barrel already crosses every layer, and a
    # barrel reaches the plane that is *under* it. A through-hole pad is
    # already stitched only if it is in its own pour.

    # Zone A6, the envelope ADC. **North of the split and it has to be**:
    # AGND and DGND are both MAGND, so every pad on U17 stitches into the
    # analogue pour, and a package straddling the line would put half of them
    # in the wrong one -- which is the fault J8 was moved for.
    #
    # East of the rail decoupling and south of the reference, which leaves the
    # ENV{n} runs coming down from the CV band into the dividers and the SPI
    # leaving south across the split. The long run is the one on a driven
    # op-amp output; the short one is the 4 kohm source into a switched
    # capacitor. See floorplan.ZONES entry A6.
    # **Rotation 0, and 7 mm of clear board west of it, and both are the
    # router's.** A TSSOP-20 is a 0.65 mm pitch on 0.40 mm pads, so
    # rules.escape_corridor() says there is no legal cell between two of its
    # pins at any class this board could be ordered at -- every pin has to
    # leave the package sideways. At rotation 0 the ten analogue pins face the
    # divider columns and the ten logic pins face away from them, which is the
    # only orientation where those two fans do not have to cross.
    #
    # The first placement had it at rotation 90 with 3.5 mm to the nearest
    # column, and the router left ENVA3, ENVA6 and SCLK unfinished: six nets
    # converging on six pins 0.65 mm apart need somewhere to fan out, and 3.5
    # mm is not it.
    # **The y is 10.21 and not 10.00, and the 0.21 is the routing grid.** A
    # TSSOP's pins are 0.65 mm apart, the router's grid is 0.5, and
    # rules.pad_reach() shows the two are incommensurable: at every phase, two
    # of the ten pin rows contain no grid cell centre at all, so no track can
    # start inside those pads. No placement removes them -- a pad wide enough
    # to always hold a cell would sit closer to its neighbour than this
    # board's own clearance rule allows -- but a placement chooses *which* two
    # rows lose, and this one gives them to AGND/DGND and to CH4/CH7. All four
    # are MAGND, which the router skips because stitch_grounds() has already
    # connected them. See design.ENV_ADC_CHANNEL.
    #
    # **The 45 um window is gone and the 0.21 is kept, and the distinction is
    # worth the two lines.** The window was the phase at which the two pin
    # rows that hold no grid cell landed on AGND/DGND and CH4/CH7 rather than
    # on a routed net, and anything added north of this package moved it. The
    # fan-out removed the constraint entirely -- route.Grid.escape() laid a
    # pad's escape on its own centre line, so a pin row with no cell in it is
    # reached anyway -- so no phase is special any more. The offset stays
    # because moving it would re-route the board for no reason, not because
    # anything depends on it.
    "U17": (70.0, SHARED_Y + 10.21, 0),
    # The three locals, each at the pin it serves: AVDD, DVDD, REFIN+. **All
    # three north of the package, and the third one moved there for a reason
    # the router found.** C819 was south, which put its run to REFIN+ -- pin 4,
    # near the north end of the west row -- straight up through the channel
    # fan, in the 3.25 mm of pin row the six ENVA{n} nets are already
    # converging into. ENVA1 and ENVA2 were what would not finish. The west
    # row arrives in order from the north now: AVDD, REFIN+, then the
    # channels, and nothing crosses anything.
    "C817": (68.0, SHARED_Y + 3.5, 90),
    "C818": (72.0, SHARED_Y + 3.5, 90),
    "C819": (76.0, SHARED_Y + 3.5, 90),
    # The rail, east of everything: its two nets are V5 and V3V3 and neither
    # of them belongs in the fan.
    "U18": (84.0, SHARED_Y + 10.0, 0),
    "C815": (84.0, SHARED_Y + 3.5, 90),
    "C816": (84.0, SHARED_Y + 16.5, 90),

    # **Zone D2 was five connectors here and it is the controller now.** J9 to
    # J13 sat on this row -- the five headers out to a controller on some other
    # board -- and the block they stood in for is in CONTROLLER below, on the
    # same band and using the same reasoning about where a loom can reach.
}

# ---------------------------------------------------------------------------
# Zone D2: the controller
# ---------------------------------------------------------------------------
# **The band between the relays and the supply, and its height is what shapes
# it.** The bypass relays are 10.7 mm tall on the split at y = 157.4, so their
# courtyards reach 162.75; the supply band's own parts start at 190. That
# leaves 27 mm of full-width board, and everything below is arranged in rows
# inside it rather than around the package -- which is the same trade the ADC's
# own block makes and for the same reason: a systematic placement is one a
# person can check.
#
# Three placements in here are load-bearing and the rest are packing:
#
#   * **the flash beside U19's QSPI row.** Minimal design section 2.2: "the
#     QSPI pins of RP2040 should be wired directly to the flash, using short
#     connections to maintain the signal integrity, and to also reduce
#     crosstalk in surrounding circuits". Those six pins are on the package's
#     north row at its west end, so the flash is immediately west of the
#     package and its own six face back;
#   * **the crystal and its two load capacitors at XIN/XOUT**, which are pins
#     20 and 21 on the south row. Section 2.3 makes this a value rather than a
#     preference: the load capacitance the crystal sees includes the tracks,
#     "we'll assume a value of 3pF for this ... Try and keep the layout as
#     short as possible", and crystal_load() spends that 3 pF;
#   * **U21's bypass within 10 mm of its pins**, which its own datasheet
#     states as a distance: "The bypass capacitor should be placed within 1 cm
#     of each pin." check_midi_bypass() below is what holds it, because a
#     placement rule with a number in it is one a check can have.
#
# The MIDI receiver is at the west end with its jack header, as far from the
# switcher as this band allows, and that is the one piece of separation here
# that is about noise rather than about length: it is the only block on the
# board whose ground is somebody else's.
# **CONTROLLER_X and CONTROLLER_Y were here and nothing read them.** They
# were the QFN's own row and column, and when the part became a module in a
# strip of new board they stopped describing anything -- 178.0 was a row with
# no part on it and 82.0 a column with no part in it, both still declared,
# both still correct-looking. That is design.RAILS' "V3V3" one file along: a
# declaration nothing is obliged to use cannot be wrong, and this repo has now
# found the same shape four times. Deleted rather than fixed, because the
# module's position is one line in CONTROLLER and does not want a constant.

CONTROLLER = {
    # -- the module, in a strip of new board south of the supply row --------
    #
    # **1243 mm2 of courtyard, and where it goes was decided by what it would
    # have had to displace.** At 90 or 270 degrees it is 53.85 x 23.08 mm; the
    # digital half of the existing outline is 50.5 mm tall, so there is no
    # vertical placement that fits east of anything. Putting it in the
    # controller band meant moving the supply row, which costs more re-routing
    # than the module's own zone -- see SUPPLY_Y. So the board grows south by
    # 26 mm and the module goes in the strip, entirely inside the digital
    # domain and clear of every piece of copper already laid.
    #
    # **270 and not 90**: at 90 the module's north edge -- the one its USB
    # overhangs -- faces west, so what ends up flush with the board's east
    # edge is the other end, three underside debug pads. DRC found that as
    # three 0.29 mm edge-clearance violations against a 0.30 mm rule, and
    # check_edge_parts() could not have, because it asks whether the courtyard
    # reaches the outline and both rotations do.
    "U19": (east_edge_at("U19", 270, BOARD_EAST_X), MODULE_Y, 270),
    # The ORing diode, on the module's own side of the run from U22.
    "D806": (44.0, MODULE_Y, 90),

    # -- the reset link ----------------------------------------------------
    "J19": (38.0, HEADER_Y, 0),

    # -- the 5 V switcher, exactly where it already is ---------------------
    #
    # **Not moved, and that is the point.** These eight parts are on the
    # committed board at these coordinates with their copper around them; the
    # block's nets -- MSW, MCB, MFB -- are unchanged by the module, and what
    # did change is a rail's name and a new run from VMOD to the three relay
    # coils. Re-siting the switcher to sit beside the module would have been
    # tidier on the sheet and would have cost eight parts' worth of routing
    # for nothing.
    "U22": (58.0, SWITCHER_Y, 0),
    "L802": (66.0, SWITCHER_Y, 0),
    "C840": (52.0, SWITCHER_Y, 90),
    "C841": (48.0, SWITCHER_Y, 90),
    # U22's own input capacitor, so it is in the switcher band and 4.5 mm
    # north of it rather than on the panel row it happened to share a y
    # with. The two bands no longer move together and a bypass that stayed
    # behind would be a bypass at whatever distance the stack left it.
    "C842": (58.0, SWITCHER_Y - 4.5, 90),
    # 73.1 and not 73.0: the choke is a tall part and wants 2.0 mm, and at
    # 73.0 it had 1.90.
    "C843": (73.1, SWITCHER_Y, 90),
    "R850": (77.0, SWITCHER_Y, 90),
    "R851": (80.0, SWITCHER_Y, 90),

    # -- the panel headers, on the south edge where a loom can reach them --
    "J15": (14.0, HEADER_Y, 0),
    "J16": (20.0, HEADER_Y, 0),
    "J17": (26.0, HEADER_Y, 0),
    "J18": (32.0, HEADER_Y, 0),

    # -- the MIDI receiver, west, on somebody else's ground ---------------
    "U21": (14.0, PANEL_Y + 1.0, 0),
    # South of U21 rather than north: DRC's silkscreen check found the
    # reference field of U21 clipped by this pad's solder mask, which is a
    # legibility fault rather than an electrical one and is still a fault --
    # a designator that cannot be read is a part somebody fits by counting.
    # Its own datasheet distance is what constrains it: "within 1 cm of each
    # pin", and check_midi_bypass() holds that.
    #
    # **It was at x = 10 and 4.5 mm south, and both numbers were nearly wrong
    # at once.** 4.5 mm put its courtyard 0.63 mm from the opto's, against
    # the 1.5 an SO-6L's pin row wants; and the pins this capacitor is for --
    # 6 and 4, VCC and GND -- are both on the package's *east* face at
    # x = 18.75, so from x = 10 the far one measured **9.99 mm against a
    # 10.0 mm limit**. check_midi_bypass() passed by ten microns and would
    # have failed on any southward move made to fix the courtyard. Two
    # constraints on one part, pulling opposite ways, with only one of them
    # instrumented.
    #
    # So it goes on the pins' own x, where the datasheet's distance is 5.7 mm
    # rather than 9.99, and one ic-class gap south of the courtyard, which is
    # what clear_south() returns.
    "C835": (18.75, PANEL_Y + 1.0 + clear_south(("U21", 0), ("C835", 90)), 90),
    # 22.15 and not 22.0: the first part east of the opto is beside an ic
    # and wants a drag-solder lane, which is 1.5 mm and was 1.40.
    "R827": (22.15, PANEL_Y, 90),
    "D805": (25.0, PANEL_Y, 90),
    "C836": (28.0, PANEL_Y, 90),
    "R828": (31.0, PANEL_Y, 90),
    "R829": (34.0, PANEL_Y, 90),

    # -- the panel networks -----------------------------------------------
    "R830": (37.0, PANEL_Y, 90),
    "R831": (40.0, PANEL_Y, 90),
    "C837": (43.0, PANEL_Y, 90),
    "R832": (46.0, PANEL_Y, 90),
    "R833": (49.0, PANEL_Y, 90),
    "C838": (52.0, PANEL_Y, 90),
}


# The ADC's six input networks: three columns of one part per channel, on
# their own row pitch rather than the board's 7.62 mm one. They are per-channel
# parts in a shared block, which is a shape COLUMNS cannot express -- COLUMNS
# rows are the twelve of the two bands -- so they get their own rule in
# position() and their own constants here.
ADC_INPUT_X = ((r"^R([1-6])56$", 50.0), (r"^R([1-6])57$", 54.0),
               (r"^C([1-6])52$", 58.0))
ADC_ROW_0 = SHARED_Y
# 3.6 mm and not 4.0: an 0805 on its side is 3.36 mm of courtyard, so this is
# 0.24 mm of clearance between rows and it takes 2 mm out of the vertical
# spread the six ENVA{n} nets have to fan across. The fan is the one congested
# thing in this block -- six tracks from a 18 mm column into 3.25 mm of pin
# row -- and every millimetre of spread removed is one it does not have to
# turn through.
# **4.0 and it was 3.6, which put an 0805's courtyards 0.20 mm apart.** A
# rotated 0805 is 3.4 mm of courtyard, so this pitch *is* the gap plus the
# part; at 3.6 the gap was 0.20 mm and GAP_MM["passive"] asks for 0.6. The
# constant that looked like a routing choice was an assembly one.
ADC_ROW_PITCH = 4.0

# The pull-downs sit at the controller connector, which is where their whole
# argument is: a hi-Z MCU has to read as a defined low at the pin it left.
# **The six PWM pull-downs moved with the thing they belong to.** They were at
# x = 74 on the connector row, because design.py put them "on MDGND and at the
# connector" -- their job is to define what the *driving* side's pin is doing,
# and the driving side used to be a ribbon arriving at J9-J11. It is U19 now,
# so they sit between the package and the '541 on the row above the panel
# headers, which is the same sentence with the connector replaced by the part.
PULLDOWN_X = 40.0

# Designators that have to move, with the reason each one does. The mixer keeps
# the same table and for the same cause: KiCad puts a reference above the body,
# which after a 90-degree rotation is *west* of it, and west of the VCAs is the
# stability capacitor 7 mm away. Six DRC violations, all of them one text field
# on two pads.
# **U15's is not the same kind of collision and it is worth the distinction.**
# The VCAs' reference lands on a neighbour because a 90-degree rotation puts
# KiCad's above-the-body text to the west. U15 is not rotated: its reference is
# where the footprint puts it, above its own body, and what is there is C810 --
# which has to be there, because it is the one part that sits on the isolation
# line. So this move is the barrier's cost in silkscreen, and moving the
# capacitor instead would be moving the thing that is placed for a reason.
# **U15's is -6.0 and it was -4.0**, which put the field on C840's pad once
# the band stack moved the switcher row: DRC's silkscreen check found it,
# on the first board this repo built with the reference already moved once
# for the same reason. A silkscreen offset is a number about two parts'
# positions, and it goes stale when either of them moves.
REFERENCE_MOVES = {"U9": (8.0, 0.0), "U10": (8.0, 0.0), "U15": (0.0, -6.0)}

# **Empty, and that is the whole of choosing the last two parts.** This held a
# 14 x 9 mm envelope for each of the three bypass relays, because
# design.BYPASS_RELAY was None and an unchosen part still needs its area
# committed. The G6S-2F is 10.70 x 15.30, so the guess was 1 mm out in one axis
# and 6 mm out in the other -- turned 90 degrees it is 15.30 wide, and the
# three still clear each other on the 18 mm spacing below because the guess was
# wrong in the direction that had room.
RESERVED = {}

# Rail decoupling, two rows of twelve rather than one of twenty-four: a single
# row is 84 mm long and would set the board's width on its own.
# **8.0, and it was moved to 8.6 for one build and moved back.** R901 and
# C701 were 0.07 mm apart -- the tightest pair on the board -- and the first
# fix moved the 24-capacitor field east by 0.6 mm, with the reason written
# down as *"the field moves rather than the star, because the star is on the
# west column with J7 and R902 and the field is 24 parts with nothing east of
# them for 1.5 mm."*
#
# **The last clause was false and gen_pcb.stitch_grounds() is what said so.**
# There is something east of them: the ADC's own input column at x = 50, and
# every one of those 24 capacitors needs a ground stitch beside its pad. The
# eastern column's stitch landed **0.57 mm from R656 against the 0.60 it
# needs** -- 0.03 mm -- and its fallback collided with the previous
# capacitor's stitch. The build stopped, correctly, at C724.
#
# So the star moves and the field does not. That is this repo's oldest fault
# in a new place: the fix asked what the two parts in the violation needed and
# not what the rest of the row already had, and it was written as a claim
# about the row -- which made it checkable, and it was checked, by a
# generator, three edits later.
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

    if ref in SUPPLY:
        return SUPPLY[ref]

    if ref in CONTROLLER:
        return CONTROLLER[ref]

    for pattern, x in ADC_INPUT_X:
        found = re.match(pattern, ref)
        if found:
            return (x, ADC_ROW_0 + (int(found.group(1)) - 1) * ADC_ROW_PITCH,
                    90)

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

    gen_pcb.py draws the same rectangle from the footprints KiCad actually
    loads, and the two agreeing is worth something: it means this file can be
    reasoned about without KiCad, which is the reason it exists. **They agree
    because they are the same function** -- this hands extents() its own boxes
    and gen_pcb.py hands it KiCad's.

    That was not true for one build and the symptom is the useful part. This
    grew an EDGE_PARTS rule and extents() did not, so placement.py reported a
    101.9 mm board with the USB connector flush on its east edge and gen_pcb.py
    drew a 107.0 mm one with the connector 5 mm inside it. Both files were
    self-consistent, both printed a number, and the numbers were different --
    which is only visible if somebody reads two lines of output that are 20
    minutes apart.
    """
    return extents([(ref, *box) for ref, box in
                    ((ref, courtyard(ref)) for ref in sorted(design.PARTS))
                    if box])


def area():
    left, top, right, bottom = outline()
    return (right - left) * (bottom - top)


def extents(courtyards):
    """The board outline a set of courtyards implies, plus a margin.

    Derived rather than declared: a rectangle typed in by hand is a rectangle
    that stops being true the first time a part moves, and this repo has spent
    two passes on the consequences of exactly that in floorplan.py.

    Takes `(ref, left, top, right, bottom)` so that **EDGE_PARTS can contribute
    without the margin**, which is what makes "at the edge" expressible at all.
    MARGIN is clear board around a part; a connector a cable plugs into wants
    none of it on the side it faces, and adding it anyway is what made the
    first attempt at this circular -- the connector pushed the outline out by
    five millimetres and then failed to reach it, for ever.

    **On the side it faces, and this used to be all four.** EDGE_PARTS declares
    a side -- `{"U19": "east"}` -- and the first version read that declaration
    only in check_edge_parts(); here it dropped the margin on every edge the
    part happened to be extreme on. The module is 53.85 mm long and it is the
    southernmost thing on the board as well as the easternmost, so its
    *south* edge became the board's south edge too, and its twenty castellated
    pads sat exactly on the cut line: **DRC reported 20 pads and 4 stitch vias
    at 0.000 mm of edge clearance**, and four of those vias were outside the
    outline entirely.

    Nothing here could have caught it, which is the part worth keeping. The
    declaration was right, the check that reads it was right, and the geometry
    was wrong on the three sides nobody had declared anything about -- the
    board drew, poured and passed placement.py. It took a router laying copper
    at the module and KiCad measuring the result.
    """
    sides = ("west", "north", "east", "south")
    reach = []
    for ref, left, top, right, bottom in courtyards:
        facing = EDGE_PARTS.get(ref)
        margins = [0.0 if facing == side else MARGIN for side in sides]
        reach.append((left - margins[0], top - margins[1],
                      right + margins[2], bottom + margins[3]))
    return (round(min(b[0] for b in reach), 2),
            round(min(b[1] for b in reach), 2),
            round(max(b[2] for b in reach), 2),
            round(max(b[3] for b in reach), 2))


def check_placed():
    """Every part has a position, and an unmatched reference is an error."""
    return [f"{ref} has no position in placement.py -- add it to a column, to "
            f"SHARED, or say why it is not on the board"
            for ref in sorted(design.PARTS) if position(ref) is None]


def courtyard(ref):
    """(left, top, right, bottom) for one part, from SIZE, ANCHOR and rotation.

    `position()` gives the *anchor*, which is what gen_pcb.py hands
    SetPosition(), and for most footprints that is the middle of the body. For
    a pin header it is pad 1, so the box has to be offset -- and the offset
    turns with the part. KiCad's convention, measured rather than assumed:
    local (x, y) at angle a lands at (x cos a + y sin a, -x sin a + y cos a),
    so pad 3 of a 1x05 at local (0, 5.08) is at (+5.08, 0) when the part is
    rotated 90 and (-5.08, 0) at 270.
    """
    spot = position(ref)
    if spot is None:
        return None
    x, y, rotation = spot
    if design.PARTS[ref].footprint is None:
        width, height = RESERVED.get(ref, (14.0, 9.0))
        if rotation % 180:
            width, height = height, width
        return (x - width / 2, y - height / 2,
                x + width / 2, y + height / 2)
    try:
        dx, dy, width, height = _extent(ref, rotation)
    except KeyError:
        return None
    return (x + dx - width / 2, y + dy - height / 2,
            x + dx + width / 2, y + dy + height / 2)


# Parts that must sit on the board's edge rather than inside it, with the
# side each faces. A part in here is one whose whole purpose is to be reached
# from outside the enclosure.
# ---------------------------------------------------------------------------
# Board fixings, and the dependency runs the other way round
# ---------------------------------------------------------------------------
#
# **The enclosure is bespoke and is drawn after this board, so the fixing
# pattern is an *input* to it and not an output of it.** That is worth stating
# because the opposite was assumed once, and the assumption made the holes
# look underivable: if the enclosure decides where they go, nothing here can
# choose them, and hardware-spec-v0.md section 6 forbids guessing. Inverted,
# section 6 says the opposite -- a value that *can* be derived should be, and
# this one can, from the board's own geometry and nothing else.
#
# The mixer targeted a 1590J because it was a standard size and its own board
# fits one. This board does not fit any standard enclosure, which is why the
# enclosure became bespoke -- and a bespoke enclosure is drawn to whatever
# pattern is decided here.

# M3 clearance, and the washer/boss diameter that has to be clear of copper
# and courtyard. Both are the ordinary metric hardware sizes rather than a
# derivation; what is derived below is how many and where.
MOUNTING_DRILL_MM = 3.2
# **KiCad's own courtyard for the fitted land, and it is not the number this
# file first derived.** An M3 washer wants about 6.5 mm of clearance, which is
# what this said -- and `MountingHole_3.2mm_M3` draws its F.CrtYd circle at
# `(end 3.45 0)`, a **6.9 mm** diameter, read first-hand from the library file.
# DRC grades against the courtyard, so the land pattern's number binds and
# ours does not: at 6.5 the board came back with two courtyard overlaps,
# H901 against R102 and H906 against U19, on positions this file had just
# certified as clear.
#
# That is `check_courtyards()`'s own finding arriving at a part this repo
# placed rather than one it routed -- a number derived here against a claim
# about a footprint that arrives from a library. The rule it leaves: when a
# clearance is going to be judged by DRC, take it from the land pattern and
# not from the hardware.
MOUNTING_KEEPOUT_MM = 6.9
# How far the hole centre sits in from the board edge. Set so the keep-out
# lands inside the outline with room rather than on it: 4.0 - 6.5/2 leaves
# 0.75 mm of board outside the washer.
MOUNTING_INSET_MM = 4.0

# Borrowed, and flagged as borrowed in the style rules.track_current() uses
# for its IPC-2221 constants: neither is measured here and neither is the
# fabricator's. E for woven-glass FR-4 in the plane of the laminate, and its
# density. **The decision they feed survives a wide error in both**, because
# deflection goes as the fourth power of the span -- three times out in either
# constant moves the acceleration figure by three and does not reorder the
# patterns at all, which is this repository's own test for whether a borrowed
# number may be used.
FR4_MODULUS_PA = 20e9
FR4_DENSITY_KG_M3 = 1900.0


def mounting_reach_mm():
    """How far a fixing's centre has to be from anything, in millimetres.

    Half the keep-out, **plus COURTYARD_TOLERANCE_MM** -- and the tolerance is
    not decoration. KiCad's DRC compares courtyard *outlines*, and an outline
    is a stroked polygon: the mounting hole's is 0.05 mm wide and so is the
    part's, so two courtyards whose nominal edges are 46 um apart overlap by
    4 um once both strokes are counted. That is exactly what happened -- H906
    cleared U19 by 0.046 mm on this file's own arithmetic and DRC reported
    them overlapping.

    The same 0.06 mm check_courtyards() already uses, for the same reason.
    """
    return MOUNTING_KEEPOUT_MM / 2.0 + COURTYARD_TOLERANCE_MM


def mounting_deflection(supports):
    """Mid-span sag per g, for a board carried on `supports` fixings.

    The board as a uniformly loaded beam along its **long** axis, which is the
    one that bends: width and thickness set the second moment, and the span
    between fixings sets everything else. Thickness is rules.FAB_FINISHED_MM,
    so this moves if the stackup does.

    **It reports sag per g and the acceleration that reaches a millimetre; it
    claims nothing about what acceleration a pedal on a stage floor sees.**
    That is return_sensitivity()'s discipline reused -- state the field at
    which the thing matters and refuse to invent the field.

    The result that decides the pattern: two fixings and four give the *same*
    answer, because four means one at each corner and the corners on the long
    axis are still the full length apart. On a 233 mm board, corner-only
    fixing buys nothing over fixing the two ends.
    """
    x0, y0, x1, y1 = outline()
    width = (x1 - x0) / 1000.0
    length = (y1 - y0) / 1000.0
    thickness = rules.FAB_FINISHED_MM / 1000.0
    second_moment = width * thickness ** 3 / 12.0
    mass = width * length * thickness * FR4_DENSITY_KG_M3
    # Fixings pair up along the long edges, so n of them give n/2 - 1 spans --
    # and never fewer than one, which is the two-and-four case above.
    spans = max((supports // 2) - 1, 1)
    span = length / spans
    load = mass * 9.81 / length                     # N/m at 1 g
    sag = 5 * load * span ** 4 / (384 * FR4_MODULUS_PA * second_moment)
    return {"supports": supports, "spans": spans, "span_mm": span * 1000.0,
            "bare_mass_g": mass * 1000.0,
            "sag_per_g_mm": sag * 1000.0,
            "g_at_1mm": 1e-3 / sag if sag else math.inf}


def mounting_pattern():
    """How many fixings, decided by mounting_deflection() rather than by habit.

    Six. The step from four to six is a factor of 16 in stiffness for two
    holes, because it halves a span that enters to the fourth power; the step
    from six to eight is a factor of five for two more, on a board that is
    already at ninety-odd g before it sags a millimetre. Four is not a
    candidate at all -- see mounting_deflection()'s own note.
    """
    rows = {n: mounting_deflection(n) for n in (2, 4, 6, 8)}
    return {"chosen": 6, "rows": rows,
            "gain_4_to_6": rows[4]["sag_per_g_mm"] / rows[6]["sag_per_g_mm"],
            "gain_6_to_8": rows[6]["sag_per_g_mm"] / rows[8]["sag_per_g_mm"]}


def mounting_holes():
    """Where the six fixings go, walked along the edge rather than declared.

    Each starts at its nominal position -- the four corners and the middle of
    each long edge, inset by MOUNTING_INSET_MM -- and slides along its own
    edge until the keep-out clears every courtyard on the board. The position
    is therefore a *result*, in the shape pack_east() and clear_south() are:
    a literal coordinate cannot say why it is where it is, and a walk can.

    Returns {ref: (x, y, moved_mm)}. `moved_mm` is what the nominal position
    cost, and two of them are not zero:

      * **H901, at the north-west corner, is blocked by J1** -- the first of
        the six loom connectors, whose column runs down the west edge from
        y = 12. It slides east along the north edge.
      * **H904 has no south-east corner to be in.** U19 is EDGE_PARTS' one
        entry, deliberately at the east edge for its USB, and it is the
        southernmost thing on the board as well -- the same two-sided fact
        that grew the primary's isolation region a tail. So the south edge's
        eastern fixing sits west of the module, and the corner itself is
        unsupported. Whether to grow the board rather than accept that is a
        decision and not a derivation, so this reports the distance instead of
        taking it.
    """
    x0, y0, x1, y1 = outline()
    need = mounting_reach_mm()
    boxes = []
    for ref in sorted(design.PARTS):
        box = courtyard(ref)
        if box:
            boxes.append(box)

    def clear_of_parts(px, py):
        worst = math.inf
        for a, b, c, d in boxes:
            dx = max(a - px, 0.0, px - c)
            dy = max(b - py, 0.0, py - d)
            worst = min(worst, math.hypot(dx, dy))
        return worst

    inset = MOUNTING_INSET_MM
    nominal = (
        ("H901", x0 + inset, y0 + inset, (1.0, 0.0)),      # NW, slides east
        ("H902", x1 - inset, y0 + inset, (-1.0, 0.0)),     # NE, slides west
        ("H903", x0 + inset, (y0 + y1) / 2, (0.0, 1.0)),   # W mid
        ("H904", x1 - inset, (y0 + y1) / 2, (0.0, 1.0)),   # E mid
        ("H905", x0 + inset, y1 - inset, (1.0, 0.0)),      # SW, slides east
        ("H906", x1 - inset, y1 - inset, (-1.0, 0.0)),     # SE, slides west
    )
    out = {}
    for ref, nx, ny, (dx, dy) in nominal:
        px, py, moved = nx, ny, 0.0
        while clear_of_parts(px, py) < need and moved < 60.0:
            moved += 0.1
            px, py = nx + dx * moved, ny + dy * moved
        out[ref] = (round(px, 2), round(py, 2), round(moved, 2))
    return out


def mounting_reach():
    """How far each board corner is from the nearest fixing.

    The half of the pattern the span arithmetic does not cover. mounting_
    deflection() models the board as a beam between supports; a corner that
    has slid its fixing away is a *cantilever*, and the reach is what decides
    whether that matters.

    **The south-east corner is the one to look at, and it carries the USB
    connector.** U19 is EDGE_PARTS' one entry, at the east edge so its socket
    is reachable, and it is the southernmost thing on the board as well -- so
    H906 slides west past it and the east edge has no southern fixing at all.
    A plug pushed into that socket is a force applied at the free end of a
    cantilever, and the reach is how long the cantilever is.

    Reported rather than resolved: the answers are to grow the board, to move
    the module, or to accept it, and all three are decisions.
    """
    x0, y0, x1, y1 = outline()
    holes = mounting_holes()
    out = {}
    for name, (cx, cy) in (("NW", (x0, y0)), ("NE", (x1, y0)),
                           ("SW", (x0, y1)), ("SE", (x1, y1))):
        best, where = math.inf, None
        for ref, (px, py, _moved) in holes.items():
            gap = math.hypot(cx - px, cy - py)
            if gap < best:
                best, where = gap, ref
        out[name] = {"corner": (round(cx, 2), round(cy, 2)),
                     "nearest": where, "reach_mm": round(best, 1)}
    return out


def check_mounting_gap():
    """Every fixing's keep-out clears every courtyard. Raises with the pair.

    check_courtyard_gap()'s sibling, and separate because a fixing is not a
    part: it has no pins, it is not in the netlist, and it is placed by a walk
    rather than by a band. What it shares is the property that matters -- the
    position is a claim, and the claim is checked against all 290 parts rather
    than against the neighbour it was derived from.
    """
    need = mounting_reach_mm()
    problems = []
    for ref, (px, py, _moved) in mounting_holes().items():
        for other in sorted(design.PARTS):
            box = courtyard(other)
            if not box:
                continue
            a, b, c, d = box
            gap = math.hypot(max(a - px, 0.0, px - c), max(b - py, 0.0, py - d))
            if gap < need - 1e-6:
                problems.append(
                    f"{ref} at ({px:.2f}, {py:.2f}) is {gap:.2f} mm from "
                    f"{other} and its keep-out needs {need:.2f}")
    if problems:
        raise AssertionError("; ".join(problems[:6]))
    return mounting_holes()


EDGE_PARTS = {"U19": "east"}


def check_courtyard_gap():
    """No two parts are closer than their assembly class allows.

    **The companion to check_overlaps(), and the distinction is the whole
    reason both exist.** That one asks whether two courtyards intersect, which
    is a question about whether the board is *manufacturable*; this asks
    whether there is room for a tool between them, which is a question about
    whether it is *assemblable*. A board can pass the first and be miserable to
    build, and this repo had 33 parts under 0.5 mm and no instrument that
    mentioned it.

    GAP_MM is where the numbers are and it says plainly that they are a
    judgement rather than a reading.
    """
    problems = []
    boxes = {ref: courtyard(ref) for ref in design.PARTS}
    refs = sorted(r for r in boxes if boxes[r])
    for index, ref in enumerate(refs):
        for other in refs[index + 1:]:
            ax0, ay0, ax1, ay1 = boxes[ref]
            bx0, by0, bx1, by1 = boxes[other]
            dx = max(bx0 - ax1, ax0 - bx1, 0.0)
            dy = max(by0 - ay1, ay0 - by1, 0.0)
            gap = (dx * dx + dy * dy) ** 0.5
            need = required_gap(ref, other)
            if gap < need - 1e-9:
                problems.append(
                    f"{ref} ({gap_class(ref)}) and {other} "
                    f"({gap_class(other)}) are {gap:.2f} mm apart and the "
                    f"larger class wants {need:.1f} -- see GAP_MM")
    return problems


def check_edge_parts():
    """An edge connector's courtyard reaches the outline, to within a hair.

    **The check that the USB connector needed and nothing had.** Everything
    else on this board is placed relative to its neighbours and outline() adds
    MARGIN around the lot, so "at the edge" is not a thing a position can say
    -- a part placed as far east as anything else is still 5 mm inside the
    board. A receptacle there is a receptacle no plug reaches, and it draws,
    routes and passes DRC exactly like one that works.

    The tolerance is a tenth of a millimetre: this is a placement, not a
    fabrication drawing, and the connector's own overhang is the fabricator's
    business.
    """
    left, top, right, bottom = outline()
    edges = {"east": (2, right), "west": (0, left),
             "north": (1, top), "south": (3, bottom)}
    problems = []
    for ref, side in sorted(EDGE_PARTS.items()):
        box = courtyard(ref)
        index, edge = edges[side]
        if box is None or abs(box[index] - edge) > 0.1:
            problems.append(
                f"{ref} is meant to be on the {side} edge and its courtyard "
                f"reaches {box[index]:.2f} against an outline at {edge:.2f} "
                f"-- a connector that mates with a cable has to be at the "
                f"edge, not merely nearest to it")
    return problems


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


# Which parts implement the zones COLUMNS does not name. **The per-channel
# columns already carry their zone tag; these are the blocks**, and until this
# existed the only record of what was in zone P or zone D2 was prose in
# floorplan.ZONES and a dict in this file that did not say which zone it was.
#
# That gap is the one design.supply() records: floorplan.py had a zone P on this
# board while design.py described J8 as a secondary inlet from somewhere else,
# both were consumed, and nothing compared them -- because "the parts in zone P"
# was not a thing any file could be asked for. This is that question, answered
# by a table, and check_zone_occupancy() is what asks it.
ZONE_PARTS = {
    "A0": (r"^J[1-7]$", r"^R901$"),
    "A1": (r"^U[12]$",),
    "A3": (r"^U9$", r"^U10$"),
    "A4": (r"^U[3-6]$",),
    "A5": (r"^U1[34]$",),
    "A6": (r"^U1[78]$", r"^C81[5-9]$", r"^R[1-6]5[67]$", r"^C[1-6]52$"),
    "C1": (r"^U[78]$",),
    "R": (r"^U12$", r"^C80[123]$", r"^R80[12]$", r"^D803$", r"^C7\d\d$"),
    "D1": (r"^U11$", r"^R81[1-6]$"),
    "D2": tuple(f"^{ref}$" for ref in sorted(CONTROLLER)),
    "F": (r"^K80[1-3]$", r"^C80[56]$", r"^D80[12]$", r"^D8[123]3$",
          r"^R803$", r"^Q801$", r"^R902$"),
    "P": tuple(f"^{ref}$" for ref in sorted(SUPPLY)),
}


def check_zone_occupancy():
    """Every zone floorplan.py declares holds parts, and every part is in one.

    **The instrument design.supply() named and nobody had written.** Its
    comment says "`floorplan.check_zone_occupancy()` is the instrument that
    would have said so and it is new here" -- and it was not new, it was
    absent: a named check that does not exist, in a paragraph about two
    artefacts disagreeing because nothing compared them. Found by grepping for
    the name while drawing the last zone.

    **It lives here and not in floorplan.py**, which is why the name in that
    comment is now this one. floorplan.py cannot import this file: placement.py
    imports *it*, for the domain table, and a cycle is not worth having to keep
    a function on the side that reads better. The question is "what is placed
    where", and that is this file's subject.

    Two directions, and the second is the one that would have caught zone P:

      * **a zone with no parts** is a declaration nothing is obliged to honour
        -- the failure design.RAILS' V3V3 entry is the other example of, and
        the reason a deferred block is dangerous rather than merely incomplete;
      * **a part in no zone** is a part the floorplan does not describe, which
        is how a decoupling capacitor ends up grounded to whatever was closest.
    """
    problems = []
    covered = {}
    zones = {tag for tag, _, _, _, _ in floorplan.ZONES}
    patterns = dict(ZONE_PARTS)
    for pattern, _, _, zone in COLUMNS:
        patterns.setdefault(zone, ())
        patterns[zone] = patterns[zone] + (pattern,)
    for zone in sorted(zones):
        if zone not in patterns:
            problems.append(
                f"floorplan.ZONES declares zone {zone} and nothing in "
                f"placement.py implements it -- either place something there "
                f"or stop declaring it")
            continue
        found = [ref for ref in sorted(design.PARTS)
                 if any(re.match(p, ref) for p in patterns[zone])]
        if not found:
            problems.append(
                f"zone {zone} holds no part on this board -- a zone with "
                f"nothing in it is a claim no check can reach")
        for ref in found:
            covered.setdefault(ref, []).append(zone)
    stale = sorted(set(patterns) - zones)
    if stale:
        problems.append(
            f"placement.py places parts in {stale}, which floorplan.ZONES "
            f"does not declare")
    homeless = sorted(set(design.PARTS) - set(covered))
    if homeless:
        problems.append(
            f"{len(homeless)} parts are in no zone at all ({homeless[:6]}) -- "
            f"the floorplan is supposed to describe the whole board")
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
    problems = (check_placed() + check_zones() + check_overlaps()
                + check_edge_parts() + check_zone_occupancy()
              + check_courtyard_gap())
    print(f"  every part has a position              "
          f"{'ok' if not check_placed() else 'FAIL'}")
    print(f"  columns agree with floorplan zones     "
          f"{'ok' if not check_zones() else 'FAIL'}")
    overlaps = check_overlaps()
    print(f"  no two courtyards overlap              "
          f"{'ok' if not overlaps else str(len(overlaps)) + ' FAIL'}")
    print(f"  edge connectors reach the outline      "
          f"{'ok' if not check_edge_parts() else 'FAIL'}")
    tight = check_courtyard_gap()
    print(f"  room for an iron between parts         "
          f"{'ok' if not tight else str(len(tight)) + ' FAIL'}")
    for line in tight[:8]:
        print(f"      {line}")
    if len(tight) > 8:
        print(f"      ... and {len(tight) - 8} more")
    print(f"  every zone holds parts, every part a zone "
          f"{'ok' if not check_zone_occupancy() else 'FAIL'}")
    for problem in problems[:12]:
        print(f"      {problem}")
    if len(problems) > 12:
        print(f"      ... and {len(problems) - 12} more")
    left, top, right, bottom = outline()
    print(f"  {len(design.PARTS)} parts, {design.CHANNELS} rows per band on a "
          f"{ROW_PITCH} mm pitch, shared block at y = {SHARED_Y:.1f}")
    print(f"  outline {right - left:.1f} x {bottom - top:.1f} mm = "
          f"{area():.0f} mm2")
    check_mounting_gap()
    pattern = mounting_pattern()
    print(f"  fixing keep-outs clear every courtyard ok")
    print(f"  fixings {pattern['chosen']}: 4 is worth nothing over 2 on a "
          f"{bottom - top:.0f} mm board, 6 is {pattern['gain_4_to_6']:.0f}x "
          f"stiffer than 4, and 8 only {pattern['gain_6_to_8']:.1f}x more")
    for supports, row in sorted(pattern["rows"].items()):
        print(f"     {supports}  span {row['span_mm']:6.1f} mm  "
              f"{row['sag_per_g_mm']:6.3f} mm/g  1 mm of sag at "
              f"{row['g_at_1mm']:6.1f} g")
    for ref, (x, y, moved) in mounting_holes().items():
        print(f"     {ref}  ({x:6.2f}, {y:6.2f})"
              + (f"  slid {moved:.1f} mm along its edge" if moved else ""))
    for name, row in mounting_reach().items():
        print(f"     {name} corner {row['reach_mm']:5.1f} mm from "
              f"{row['nearest']}"
              + ("   <- and it carries the USB socket" if name == "SE" else ""))
    if problems:
        raise SystemExit(f"{len(problems)} problems")


if __name__ == "__main__":
    main()
