"""The fabrication rules, and the arithmetic that decides them.

Stdlib only and no KiCad, for the reason placement.py and route.py have none:
a rule that can only be read inside the interpreter that enforces it is a rule
nobody can check.

**This file exists because two other files each said the rules lived in the
other one.** gen_pcb.py carried the constants and said "gen_project.py imports
them so the two cannot disagree"; gen_project.py said "No board design rules
... gen_pcb.py, when it exists, is where the rules go", and wrote its own
track width, clearance and via sizes as literals in net_classes(). Neither
imported anything from the other, and neither could: importing gen_pcb.py
relaunches it under KiCad's interpreter, which is what the top of that file
does before anything else runs. So the numbers agreed by coincidence and by
one person having typed them twice.

Worse, gen_pcb.py named `check_rules()` in verify.py as the thing that "stops
the discipline from decaying into a comment", and **there was no check_rules()
in verify.py.** Nothing in this repository has ever been more exactly its own
named failure mode: a check cited and never written, holding together two
files that did not import each other, described in a docstring that read as
though somebody had already done it. There is one now, and it reads the
project and the board off disk rather than reading this module twice.

The mixer keeps its own rules in a rules.py that gen_project.py reads, and
gen_project.py here already cited that file's existence. This is that file.

---

**The fabricator, read first-hand rather than assumed.** JLCPCB's published
capabilities, https://jlcpcb.com/capabilities/pcb-capabilities, read
2026-08-17. The rows that bear on this board, quoted:

  * minimum trace width / spacing, 1 oz outer copper:
    *"Multilayer: 0.09 / 0.09 mm (3.5 / 3.5 mil). 3 mil is acceptable in BGA
    fan-outs."*
  * minimum trace width / spacing, 2 oz outer copper:
    *"Multilayer: 0.15 / 0.15 mm (6 / 6 mil)"*
  * *"Min. Via hole size/diameter: 0.15mm / 0.25mm"*
  * and the only cost note the page attaches to any of it:
    *"0.15mm hole size with any size via diameter, and 0.2mm or 0.25mm hole
    size with via diameter less than 0.45mm, will cost more."*

**What the page does not say is what the fine-line class costs**, and that is
worth being exact about, because the question this file was written to answer
is a cost question. The page prices vias and does not price trace class; the
20 % figure for 3-3.5 mil on 4-8 layer boards that circulates in third-party
guides is not on JLCPCB's own page and is not quoted here as though it were.
What the page *does* price, in capability rather than in money, is the copper
weight: **2 oz outer copper caps the class at 0.15/0.15 mm, and reaching
0.09/0.09 means 1 oz.** That is a trade this repo can state exactly, and it is
the one escape_corridor() below turns out to hinge on.
"""

import math
import pathlib
import re

# ---------------------------------------------------------------------------
# The rules as fitted
# ---------------------------------------------------------------------------

# Outer copper weight. **Decided, and it is 1 oz.** This was a declaration
# rather than a decision for five passes -- "the rules below are chosen to be
# legal at either weight ... keeping the option costs nothing", which was true
# and ended the moment something asked for 0.09 mm. The controller asked.
#
# **The decision was taken on a measurement rather than an argument**, and the
# argument it overturned was this file's own. gen_pcb.py end to end, all four
# combinations of class and via rule:
#
#     class          via rules      time     unrouted   DRC violations
#     0.25/0.20 2oz  ring of four    89 s        0            0
#     0.09/0.09 1oz  ring of four    69 s        0           56
#     0.25/0.20 2oz  corrected      454 s       10 (V5)       0
#     0.09/0.09 1oz  corrected       89 s        0            0
#
# Only the last row is a complete, DRC-clean board. The coarse class cannot
# close the 5 V rail once via_exclusion() is modelled properly and takes five
# times as long to fail; the fine one closes everything, needs no fan-out escape
# anywhere, and runs in the same 89 seconds the coarse class used to.
#
# **What 1 oz costs is current capacity and the answer is 0.33 degrees.**
# track_current(): design.coil_budget()'s 92.7 mA on 0.09 mm of 1 oz is 0.33 C
# of rise, and 4.0 C even if the borrowed IPC-2221 constant is three times out.
# Nothing else on this board is more than microamps. The figure that made this
# look like a trade was 29 A/mm2, and current density omits the surface area
# that does the cooling -- see track_current() for why that is the wrong
# instrument.
#
# **1 oz, and the reason is that nothing on this board has ever wanted 2.**
# The weight was carried as a free option for five passes -- this file's own
# words were *"the rules below are chosen to be legal at either weight ...
# keeping the option costs nothing"* -- and it was never bought against a
# requirement. It was then spent by the RP2040's QFN, which is gone.
#
# **The only number this repo has for it says 1 oz by a factor of nothing that
# matters.** track_current() puts the largest current on the board -- 92.7 mA
# of relay coil -- at **0.088 degC of rise** on 0.20 mm of 1 oz copper, against
# 0.028 degC at 2 oz. Both are noise. There is no thermal case, no current
# case, and no mechanical case anybody here has written down.
#
# **And 2 oz would now cost something real.** PCBWay's 2 oz floor is
# 0.178/0.203 mm, so a track through the 0.67 mm corridor between two SOIC
# pins needs 0.584 mm of it and leaves **0.086 mm of total slack** to spend on
# margin. At 2 oz you choose between holding margin over the process and being
# able to route between two pins of a SOIC. At 1 oz you get both. See
# TRACK_MM.
COPPER_OZ = 1

# **0.20 mm, and the constraint that picked it is the SOIC corridor rather
# than the fabricator's floor.** Two SOIC pins leave 0.67 mm of bare laminate
# between them -- escape_corridor() -- and a track through it needs
# `track + 2 x clearance`. That is the number that separates the candidates,
# and it separates them the opposite way round from the margin figures:
#
#     class        w + 2c   through a SOIC?   over PCBWay's 1 oz floor
#     0.20/0.20    0.600    yes, 0.07 spare   track +57 %, space +32 %
#     0.25/0.25    0.750    **no**            track +97 %, space +64 %
#
# So the coarser class has more margin over the process and cannot pass
# between two pins of a SOIC, on a board with a SOIC-20W, two SOIC-16, several
# SOIC-14 and a SOIC-8 on it. 0.20/0.20 holds a third to a half of margin
# everywhere *and* keeps the corridor, which is why it wins.
#
# **It is a 1 oz class and only a 1 oz class.** At 2 oz PCBWay's spacing floor
# is 0.203 mm, so 0.20 is 1.5 % under it -- close enough to read as fine and
# it is not. Said here because "0.20/0.20 on 1 oz or 2 oz" was written down
# once in this project and was wrong.
#
# The three values this has been are each right about the board they were on:
# 0.25/0.20 while every package was a SOIC and the fabricator was assumed to
# be JLCPCB, 0.09/0.09 while a 0.40 mm QFN-56 had to be reachable by a maze
# router, and 0.20/0.20 now that the controller is a 2.54 mm module, the board
# is hand-laid, and the fabricator has been asked.
TRACK_MM = 0.20

# **POWER_TRACK_MM was here at 0.5 mm for the whole life of the board and it
# is gone, because it was the one constant in this file with no argument
# beside it.** What it had was a procedure -- "this is what a rail is widened
# to when somebody widens one" -- and nobody ever did, so no copper was ever
# 0.5 mm wide. verify.check_rules() asserts the board carries exactly one
# track width, which means the only instrument that mentioned the constant
# asserted its *absence*: a declaration nothing is obliged to use cannot be
# wrong, the same way zone P and RAILS["V3V3"] could not be wrong.
#
# It was forced by a router that reads net classes and would have drawn it.
# design.power_track_verdict() is the derivation that had never been done, and
# every mechanism a wider rail could address is closed by a wide margin:
#
#   heating          0.58 C of rise at VA+'s 213 mA on 0.20 mm
#   static drop      42 mV worst case, on V5, a 5 V rail
#   crosstalk        -148.8 dB against a -54 dB requirement, and -88.8 dB
#                    even if the amplifier had NO power-supply rejection
#
# Widening to 0.5 mm buys 7.96 dB on a figure with 94.8 dB of margin. The
# Power net class survives the constant, because its other field is a colour
# and a hand-routed board is worth having the rails red in the editor.

# 0.20 mm, with the track, and the pair is chosen together -- see TRACK_MM,
# where the corridor arithmetic is `track + 2 x clearance` and so cannot be
# decided one value at a time. 32 % over PCBWay's 1 oz spacing floor and 122 %
# over JLCPCB's, and DRC runs against it on every build with
# verify.check_rules() holding all three files to it.
CLEARANCE_MM = 0.20

# 0.6 mm diameter on a 0.3 mm hole. **Chosen to sit outside every surcharge the
# capabilities page names**, which is the one place that page gives a price:
# a 0.3 mm hole is neither of the two sizes it calls out, and 0.6 mm is above
# the 0.45 mm diameter below which the small holes cost more. The published
# minimum is 0.25 mm on a 0.15 mm hole and this design has no reason to go
# near it.
# **0.7 mm and not 0.6, and the 0.1 mm buys margin on the one via number that
# is a function of two others.** 0.6/0.3 is a 0.150 mm annular ring against
# PCBWay's published 0.150 mm minimum -- exactly at it, on 767 vias, and
# passing every check this file had because none of them computed the ring.
# 0.7/0.3 is 0.200 mm, a third over.
#
# What it costs is a 0.05 mm larger radius of keepout around each via, on a
# board that is 3.8x the area of the one it plugs into and is about to be
# re-placed anyway. If area ever becomes the binding constraint this is a
# cheap 0.1 mm to give back, and it should be given back deliberately rather
# than by drifting.
VIA_DIAMETER_MM = 0.7
VIA_DRILL_MM = 0.3

# Copper to board edge.
EDGE_CLEARANCE_MM = 0.3

# KiCad's own coordinate quantum: it stores board geometry in nanometres, and
# route.py rounds every grid point to 0.1 um before handing it over. Two
# roundings can therefore move a spacing by 0.2 um, which is why PITCH_MARGIN
# below is not allowed to be zero.
COORDINATE_QUANTUM_MM = 1e-4

# ---------------------------------------------------------------------------
# The routing grid
# ---------------------------------------------------------------------------

# **The margin the grid pitch carries above the minimum that clears, and the
# correction it embodies.** gen_pcb.py used to declare the pitch as "the
# tightest pitch these rules allow and therefore the one that routes", at
# 0.5 mm. It is not: two tracks on adjacent cells are PITCH - TRACK apart, so
# the tightest pitch these rules allow is TRACK + CLEARANCE = 0.45 mm, and
# 0.5 mm is 0.05 mm of margin on top of it. The sentence was not a derivation
# with an arithmetic slip in it -- it was a derivation that had never been
# performed, stated in the voice of one that had, which is exactly the shape
# this repo keeps finding.
#
# **Keeping the margin is a decision and it has a measured price.** At 0.45 mm
# the router finishes on the sixth retry pass instead of the ninth, about 17
# seconds of build time, and 12 % more cells. What it gives up is all of the
# margin: two adjacent tracks would land at exactly 0.2 mm, which passes DRC
# only because DRC compares against `<` -- and which depends on the board
# origin landing on the 0.1 um lattice, since route.py's grid points are
# `origin + n * pitch` rounded to 0.1 um and two such roundings can differ by
# 0.2 um in the wrong direction. A rule that holds because the outline
# happened to come out on a round number is not a rule.
#
# 0.05 mm is 500x that quantum and 25 % of the clearance itself.
PITCH_MARGIN_MM = 0.05


def route_pitch(track=TRACK_MM, clearance=CLEARANCE_MM,
                margin=PITCH_MARGIN_MM):
    """The routing grid pitch, derived from the rules rather than chosen.

    Two tracks on adjacent cells are `pitch - track` apart edge to edge, and
    that has to clear `clearance`:

        pitch - track >= clearance
        pitch         >= track + clearance

    `margin` is what is carried above that floor, and PITCH_MARGIN_MM explains
    why it is not zero.
    """
    return track + clearance + margin


def via_neighbours(pitch=None, via=VIA_DIAMETER_MM, track=TRACK_MM,
                   clearance=CLEARANCE_MM):
    """Which cells around a via are inside the clearance, orthogonal and diagonal.

    route.py has to block some ring of cells around every via it places,
    because a via is wider than a track and the uniform grid cannot express
    that on its own. Which ring is arithmetic and it used to be a comment:

        orthogonal: pitch          - via/2 - track/2
        diagonal:   pitch * sqrt 2 - via/2 - track/2

    At the fitted rules that is 0.075 mm orthogonally, a third of the
    clearance, and 0.28 mm diagonally, which clears. Blocking all eight was the
    cautious version and it cost 27 nets, because a SOIC pin's diagonals are
    always somebody's clearance ring and so no via could ever be placed at a
    package pin.
    """
    pitch = route_pitch() if pitch is None else pitch
    reach = via / 2 + track / 2
    orthogonal = pitch - reach
    diagonal = pitch * math.sqrt(2) - reach
    return {
        "orthogonal_mm": orthogonal,
        "diagonal_mm": diagonal,
        "orthogonal_blocks": orthogonal < clearance,
        "diagonal_blocks": diagonal < clearance,
    }


# ---------------------------------------------------------------------------
# The escape corridor: the question the routing pass was left with
# ---------------------------------------------------------------------------

# Read first-hand out of KiCad's own footprint rather than off a datasheet
# drawing, because the router blocks what KiCad places and not what JEDEC
# draws. Package_SO.pretty/SOIC-14_3.9x8.7mm_P1.27mm.kicad_mod, pad 1:
#     (at -2.475 -3.81) (size 1.95 0.6)
# so the pads are 0.6 mm across on a 1.27 mm pitch, and the same numbers hold
# for the SOIC-8, SOIC-16 and SOIC-20W on this board.
SOIC_PIN_PITCH_MM = 1.27
SOIC_PAD_WIDTH_MM = 0.6


def escape_corridor(track=TRACK_MM, clearance=CLEARANCE_MM,
                    pin_pitch=SOIC_PIN_PITCH_MM, pad_width=SOIC_PAD_WIDTH_MM):
    """Can a routing cell exist *between* two pins of a SOIC? Arithmetic, not taste.

    This is the question the first routing pass ended on, and it was left as a
    choice between "a finer grid with thinner track" and "rip-up and retry"
    without either being priced. Here is the price.

        gap    = pin_pitch - pad_width                 the copper-free space
        window = gap - 2 * (clearance + track / 2)     legal track centres
        floor  = track + clearance                     the finest legal pitch

    A track centred anywhere in `window` clears both pads. But the grid's phase
    against the pads is arbitrary -- pads are placed by placement.py and the
    grid is anchored to the board outline -- so a cell only *reliably* falls in
    that window when the window is at least a whole pitch wide. Hence

        fits  <=>  window >= floor  <=>  gap >= 3 * clearance + 2 * track

    which is the whole decision in one line, and it does not mention the pitch
    at all: **no grid, however fine, buys the corridor if the class is too
    coarse, and any grid at the floor buys it if the class is fine enough.**

    At the fitted 0.25 / 0.20 the window is 0.02 mm against a 0.45 mm floor.
    That is not "a fine enough grid would find it" -- it is 4 % of the coarsest
    legal cell, and the 0.5 mm grid was never the reason.
    """
    gap = pin_pitch - pad_width
    window = gap - 2 * (clearance + track / 2)
    floor = track + clearance
    return {
        "gap_mm": gap,
        "window_mm": window,
        "floor_mm": floor,
        "fits": window >= floor,
    }


# The ADC's package, and it is the one on this board with no corridor at all.
# TSSOP-20 at 0.65 mm pitch on 0.40 x 1.475 mm pads, read off KiCad's own
# footprint: the copper-free gap between two pins is 0.25 mm, and
# escape_corridor() wants 3 x clearance + 2 x track. At the fitted class that
# is 1.10 mm and at the finest class this board could be ordered at -- 1 oz,
# 0.09/0.09 -- it is 0.45. **Neither fits, and the window is negative at both**
# (-0.40 mm and -0.02 mm), so there is not even a legal track *centre* between
# two pins, let alone a grid cell that reliably lands on one.
#
# That is a stronger statement than the SOIC's and it is not a problem: a
# 20-pin part whose pins all escape outward needs no corridor. What it needs
# is room outside the package, which is placement.SUPPLY's note at U17 and
# cost three unrouted nets to learn.
TSSOP_PIN_PITCH_MM = 0.65
TSSOP_PAD_WIDTH_MM = 0.40

# **The finest pitch this project has had to price, and it is the RP2040's.**
# Read off KiCad's own footprint rather than the datasheet drawing, for the
# reason the SOIC's numbers are:
# Package_DFN_QFN.pretty/QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm.kicad_mod, pad 1:
#     (at -3.4375 -2.6) (size 0.875 0.2)
# so 0.20 mm pads on a 0.40 mm pitch, which leaves 0.20 mm of copper-free gap
# between two pads -- exactly this board's clearance, and the reason the
# footprint itself is DRC-legal here at all. RP2040 ships in no other package.
QFN_PIN_PITCH_MM = 0.40
QFN_PAD_WIDTH_MM = 0.20

def pad_reach(pin_pitch=TSSOP_PIN_PITCH_MM, pad_width=TSSOP_PAD_WIDTH_MM,
              grid=None, clearance=CLEARANCE_MM):
    """Can a routing cell exist *inside* a pad? One line further out than
    escape_corridor(), and the answer for a TSSOP is no.

    escape_corridor() asks whether a track can pass *between* two pins. This
    asks whether a track can *start* on one. A uniform grid reaches a pad only
    if some cell centre falls inside it, and a pad narrower than the grid pitch
    holds a cell at some phases and not at others:

        holds a cell always  <=>  pad_width > grid

    and the pad cannot be made as wide as one likes, because two adjacent pads
    are two nets:

        pad_width <= pin_pitch - clearance

    Put together, **a package is reachable at every phase only if
    pin_pitch > grid + clearance**. At the fitted 0.5 mm grid and 0.2 mm
    clearance that is 0.70 mm. A SOIC's 1.27 clears it by 0.57; a TSSOP's 0.65
    misses it by 0.05, and there is nothing to be done about the 0.05 on this
    router: a wider pad breaks clearance and a finer grid breaks the copper
    weight (see escape_corridor()).

    **Nor can the stub reach out to the nearest cell.** That cell is between
    0.20 and 0.25 mm from the pad centre, so a track of TRACK_MM laid to it
    reaches within 0.075 mm of the neighbouring pad against a 0.2 mm rule.
    The excursion is not small, it is illegal.

    So what is left is choosing *which* pads lose. `phases` is how many of the
    pad rows hold a cell at the best and worst phase, and for a package whose
    pin pitch and grid share a common divisor the pattern repeats -- for 0.65
    against 0.5 the offsets are all ten multiples of 0.05, and two rows always
    land outside. design.ENV_ADC_CHANNEL spends that on the ADC's two grounded
    channels. **That is no longer load-bearing and the note is kept for the
    arithmetic**: the fan-out closes the pads that lose, so which two rows they
    are is free again. See track_offset_limit(), and route.Grid.escape() in
    the history -- route.py was deleted for a pass and this arithmetic
    outlived it; the router is back as a one-shot seed and the board is
    hand-laid either way.
    """
    grid = route_pitch() if grid is None else grid
    widest = pin_pitch - clearance
    return {
        "pin_pitch_mm": pin_pitch,
        "pad_width_mm": pad_width,
        "grid_mm": grid,
        "widest_pad_mm": widest,
        "needed_pitch_mm": grid + clearance,
        "reachable_at_every_phase": pin_pitch > grid + clearance,
        "short_by_mm": max(0.0, grid + clearance - pin_pitch),
        # What a stub to the nearest cell would leave, against the clearance.
        "stub_to_neighbour_mm": (pin_pitch - pad_width / 2 - grid / 2
                                 - TRACK_MM / 2),
        "clearance_mm": clearance,
    }


# ---------------------------------------------------------------------------
# Holes, which are a different rule from copper and do not scale with the class
# ---------------------------------------------------------------------------
#
# **These are the fabricator's own figures and they were not in this file at
# all.** gen_pcb.rules() sets the minimum track, via, copper clearance and edge
# clearance, and verify.check_rules() holds all four; nothing said anything about
# a drill, so KiCad's own defaults -- 0.25 mm on both hole rules, quoted by the
# DRC report as "board setup constraints hole clearance 0.2500 mm" -- were
# enforcing it unowned.
#
# **They were read off JLCPCB's page and the board goes to PCBWay**, which is
# docs/fabrication-class.md's own correction arriving one table along. The old
# text is kept because the reasoning in it is right and the numbers in it are
# somebody else's process:
#
#     Read first-hand from the same JLCPCB capabilities page as the class
#     above: "Via Hole-to-Hole Spacing: 0.2mm" / "Pad Hole-to-Hole Spacing:
#     0.45mm" / "Via hole to Track: 0.2mm" / "PTH to Track: 0.28mm" (0.35 mm
#     recommended).
#
# **PCBWay's, capabilities page read 2026-08-19, converted from mil.** Their
# page grades every row by difficulty and what is quoted here is the "normal
# process" column, because a board ordered at a difficulty tier is a board
# quoted at a different price:
#
#     component hole to hole   ">=16MIL"  = 0.406 mm  (14-16 medium,
#                                                      13-14 high, <13 refused)
#     via to via, dia <=0.45   ">=11MIL"  = 0.279 mm
#     inner hole to circuit,   ">=7MIL"   = 0.178 mm  (6-7 medium, 5-6 high)
#       4 layers
#
# **And the decision this settles is not the one that was open.** The open item
# read "whether to design to the fabricator's published 0.20 mm hole clearance
# rather than KiCad's 0.25 mm default" -- a question with JLCPCB's number in
# it, asked about a board going to PCBWay. Asked of the right page it does not
# survive contact: PCBWay's hole-to-hole is **0.406 mm, sixty percent stricter
# than the KiCad default the question called strict**, and their copper-to-hole
# is 0.178, looser. There was never one number to compare.
#
# **The rule stays "the stricter of published and KiCad's own", and it now
# points both ways**, which is the only reason it is worth having: 0.406 for
# hole-to-hole is the fabricator's, 0.25 for copper-to-hole is KiCad's. Neither
# costs anything at this class -- via_exclusion() below shows the copper rule
# winning all three distances -- so adopting the stricter figure is free, and
# the trap the old text names is avoided by construction rather than by
# refusing to choose: **nothing here makes a violation disappear, because the
# number that moved moved the wrong way for that.**
#
# **The point that matters is still that none of these is a function of the
# copper class.** A hole clearance is drill positioning, not etching, so taking
# the track and clearance down buys nothing here -- and at some point on the
# way down the hole rule *overtakes* the copper rule and becomes the binding
# one. via_exclusion() is where that crossover is computed rather than
# discovered.
#
# **The 0.7 mm via is above PCBWay's own qualifier and is read as a component
# hole.** Their 11 mil row says "via spacing (<=0.45mm diameter)" and this
# board's vias are 0.7; nothing on the page says what a 0.7 mm via costs, so it
# is taken as the 16 mil component-hole row. That is the reading that cannot be
# wrong in the direction that matters, and it is 0.127 mm of difference on a
# rule the copper already dominates.
HOLE_LIMITS = {
    # (component hole to hole, via to via, hole to copper), millimetres
    "JLCPCB": (0.45, 0.20, 0.20),
    "PCBWay": (16 * 0.0254, 11 * 0.0254, 7 * 0.0254),
}
# KiCad's own defaults, named as such because they are what has been in force
# and because the rule below is "the stricter of these and the fabricator's".
KICAD_HOLE_CLEARANCE_MM = 0.25
KICAD_HOLE_TO_HOLE_MM = 0.25


# ---------------------------------------------------------------------------
# The stackup, which had never been chosen
# ---------------------------------------------------------------------------
#
# **out/cv-module.kicad_pcb carried no (stackup ...) block at all**, so KiCad's
# defaults applied and the dielectric height between an outer layer and the
# plane beneath it -- the number that sets every impedance and every coupling
# figure on this board -- was whatever KiCad happened to assume. Nothing
# noticed, because nothing asked: no net here is impedance-controlled, so the
# only consumer was constraints.board_coupling(), and it had to quote a
# *range* of heights because there was no value to quote.
#
# **PCBWay's own 4-layer table, read 2026-08-20**, the 1.6 mm construction at
# 1 oz outer copper -- which is this board's class, COPPER_OZ = 1:
#
#     L1  F.Cu    0.5 oz base, plated to 1 oz      0.0350 mm
#     PP          7628 RC46%, DK 4.74              0.1855 mm  (after lamination)
#     L2  In1.Cu  1 oz                             0.0350 mm
#     CORE        DK 4.6                           1.0300 mm
#     L3  In2.Cu  1 oz                             0.0350 mm
#     PP          7628 RC46%, DK 4.74              0.1855 mm
#     L4  B.Cu    0.5 oz base, plated to 1 oz      0.0350 mm
#
#     finished 1.61 mm +/-10 %
#
# The copper and dielectric sum to 1.541 mm; the rest is solder mask, which is
# why the published finished figure is larger than the layers add to. Quoted as
# published rather than reconciled, because a number adjusted to make an
# arithmetic check pass is no longer the fabricator's number.
#
# **Two things this settles that were being assumed.** The prepreg is DK 4.74
# and not the 4.3 that design.PCB_ER carried as "FR-4, the usual figure, not
# measured" -- the usual figure is for the laminate class, and 7628 is a
# specific glass style with a specific resin content. And h is 0.1855 mm, which
# is close to the middle of the range constraints.board_coupling() was sweeping,
# so the pessimistic end it had been quoting was 0.5 mm of prepreg that this
# fabricator does not offer in a 1.6 mm four-layer board.
FAB_STACKUP = (
    # (name, kind, thickness mm, dielectric constant or None)
    ("F.Cu",   "copper",     0.0350, None),
    ("PP1",    "prepreg",    0.1855, 4.74),
    ("In1.Cu", "copper",     0.0350, None),
    ("Core",   "core",       1.0300, 4.60),
    ("In2.Cu", "copper",     0.0350, None),
    ("PP2",    "prepreg",    0.1855, 4.74),
    ("B.Cu",   "copper",     0.0350, None),
)
FAB_FINISHED_MM = 1.61


def outer_dielectric():
    """The prepreg an outer layer references, as (thickness mm, Dk).

    Both outer layers see the same construction, which is what makes the board
    symmetric and is the reason a four-layer stackup is built this way. This is
    the `h` and `er` every microstrip figure on this board depends on, and
    before FAB_STACKUP existed there was no value to hand them.
    """
    for index, (name, kind, thickness, dk) in enumerate(FAB_STACKUP):
        if kind in ("prepreg", "core"):
            return thickness, dk
    raise AssertionError("FAB_STACKUP has no dielectric in it")


def stackup_thickness():
    """What the declared layers add to, mm. Not the finished figure."""
    return sum(row[2] for row in FAB_STACKUP)


def stackup_sexp():
    """FAB_STACKUP as the `(stackup ...)` block KiCad keeps inside `(setup)`.

    Emitted as text rather than set through `pcbnew`, and that is the point:
    **gen_pcb.py cannot run on a routed board.** It places and pours and lays
    no signal copper, so re-running it to change a piece of metadata would
    destroy the routing -- which is exactly the hazard
    gen_pcb_guard.refuse_to_discard_routing() exists to refuse. A stackup is
    not copper, so it does not need the generator that draws copper.

    So this writes a string and apply_stackup() edits the file, which works on
    a fresh board and on a hand-edited one alike. gen_pcb.py calls it after
    SaveBoard() for the same reason it re-runs gen_project.py there: KiCad's
    own save is what flattens both.
    """
    lines = ['\t\t(stackup']
    for name, kind, thickness, dk in FAB_STACKUP:
        if kind == "copper":
            lines += [f'\t\t\t(layer "{name}"',
                      '\t\t\t\t(type "copper")',
                      f'\t\t\t\t(thickness {thickness})',
                      '\t\t\t)']
        else:
            lines += [f'\t\t\t(layer "dielectric {name}"',
                      '\t\t\t\t(type "prepreg")' if kind == "prepreg"
                      else '\t\t\t\t(type "core")',
                      f'\t\t\t\t(thickness {thickness})',
                      '\t\t\t\t(material "FR4")',
                      f'\t\t\t\t(epsilon_r {dk})',
                      '\t\t\t\t(loss_tangent 0.02)',
                      '\t\t\t)']
    lines += ['\t\t\t(copper_finish "None")',
              '\t\t\t(dielectric_constraints no)',
              '\t\t)']
    return "\n".join(lines) + "\n"


_STACKUP_BLOCK = re.compile(r"\n\t\t\(stackup\n(?:.*?\n)*?\t\t\)\n")


def apply_stackup(board):
    """Put the declared stackup into a board file, replacing any it has.

    Idempotent, and it touches nothing but the `(setup ...)` block -- no
    footprint, no segment, no via, no zone. Returns True if the file changed.

    **The board had none at all**, which is how the dielectric height stayed
    unchosen through every pass: KiCad supplies defaults for a board that does
    not declare one, and a default is invisible to every check that reads what
    is written.
    """
    board = pathlib.Path(board)
    text = board.read_text()
    replacement = "\n" + stackup_sexp()
    if _STACKUP_BLOCK.search(text):
        updated = _STACKUP_BLOCK.sub(replacement, text, count=1)
    else:
        marker = "\t(setup\n"
        index = text.index(marker) + len(marker)
        updated = text[:index] + stackup_sexp() + text[index:]
    if updated == text:
        return False
    board.write_text(updated)
    return True


def hole_rules(fabricator=None):
    """The two hole numbers DRC is set to, each the stricter of two sources.

    KiCad has one hole-to-hole setting and the fabricator publishes two rows
    -- component holes and vias -- so what goes in is the stricter row, which
    is the component one on every fabricator this file carries.

        min_hole_to_hole    max(published component row, KiCad's default)
        min_hole_clearance  max(published hole-to-copper, KiCad's default)

    Returned as the project's own key names, so that gen_project.
    design_rules() spreads it and verify.check_rules() compares it key by key
    without either of them holding a second opinion about which rule is which.
    """
    pad, via, copper = HOLE_LIMITS[fabricator or FABRICATOR]
    return {
        "min_hole_to_hole": max(pad, via, KICAD_HOLE_TO_HOLE_MM),
        "min_hole_clearance": max(copper, KICAD_HOLE_CLEARANCE_MM),
    }


def via_exclusion(track=TRACK_MM, clearance=CLEARANCE_MM,
                  via=VIA_DIAMETER_MM, drill=VIA_DRILL_MM):
    """The three distances a via needs, each the stricter of copper and hole.

    route.py had one of these as a hard-coded ring of four neighbours, correct
    at a 0.5 mm grid and stated as though it were a fact about the geometry.
    These are the same question asked properly, and they are three questions
    rather than one because a via is near three kinds of thing:

        to a track's centre   via/2 + track/2 + clearance   |  drill/2 + hole
        to another via        via + clearance               |  drill + hole
        to a pad's copper     via/2 + clearance             |  drill/2 + hole

    The left column is copper and shrinks with the class; the right is drill and
    does not. Both hole figures come from hole_rules(), which is the stricter
    of the fabricator's published row and KiCad's own default -- so this
    function has no opinion of its own about which number is in force, which
    is the whole reason that lives in one place.
    """
    fitted = hole_rules()
    hole = fitted["min_hole_clearance"]
    hole_pair = fitted["min_hole_to_hole"]
    return {
        "to_track_mm": max(via / 2 + track / 2 + clearance, drill / 2 + hole),
        "to_via_mm": max(via + clearance, drill + hole_pair),
        "to_pad_mm": max(via / 2 + clearance, drill / 2 + hole),
        "hole_mm": hole,
        "copper_binds": via / 2 + clearance >= drill / 2 + hole,
    }


# ---------------------------------------------------------------------------
# The fan-out: what a track may do inside a pad it cannot land in the middle of
# ---------------------------------------------------------------------------

def track_offset_limit(edge_mm, track=TRACK_MM, clearance=CLEARANCE_MM):
    """How far off a pad's centre line a track through that pad may sit.

    **pad_reach() asks whether a cell lands inside the pad. This asks the
    question that actually decides, and the two are not the same** -- which is
    the whole of why verify.UNROUTED_ITEMS was eight while
    gen_pcb.check_fine_pitch_access() reported nothing. That function is gone --
    the fan-out closes the pads it used to predict, and gen_pcb.escape_plan() is
    what stands where it stood.

    A pad is copper and is allowed to sit closer to its neighbour than the
    clearance rule, because two pads are placed by the footprint and not by
    the router: a TSSOP's pads are 0.40 mm across on a 0.65 mm pitch, so the
    copper-free gap between two of them is 0.25 mm against a 0.20 mm rule. A
    *track* laid through that pad has no such licence. Its own copper is
    `track` wide wherever it is drawn, so what matters is not whether its
    centre is inside the pad but how close its edge comes to the neighbour:

        edge_mm                 pad centre line to the nearest other copper,
                                measured across the pad's short axis
        limit  = edge_mm - clearance - track / 2

    At 0.65 mm of pitch on 0.40 mm pads that is 0.45 - 0.20 - 0.125 =
    **0.125 mm**, and the routing grid offers offsets that are multiples of
    0.05 up to 0.25. So three phases in five are legal and two are not, and no
    placement removes the two -- see pad_reach() for why the pad cannot simply
    be made wider.

    **The number this replaces was 0.075 mm and it was a true statement about
    a different question.** The deleted route.Grid.block_pad_copper() inset a pad by half
    a track before claiming its cells, so that a track drawn on one of them
    stays *inside the pad's own copper* -- 0.075 mm here. That is the right
    rule for the exemption it guards (a segment inside the pad cannot be too
    close to anything, because the pad already is not), and it is stricter
    than this one by 0.05 mm. Neither is wrong; they answer "does the track
    overhang the pad" and "does the overhang reach the neighbour", and only
    the second is a design rule.
    """
    return edge_mm - clearance - track / 2


def escape_reach(half_length_mm, track=TRACK_MM, clearance=CLEARANCE_MM):
    """How far out along its own axis a fan-out escape runs before it may turn.

    An escape is fixed copper laid on the pad's own centre line, so that a pad
    whose every grid offset fails track_offset_limit() is entered at zero
    offset instead -- the thing a person drawing this by hand does without
    thinking about it. Inside the pin row it is the safest track on the board,
    because it is exactly where the pad already is. The moment it turns, it is
    ordinary track and 0.65 mm from a neighbour is not enough for one.

    So it may only turn once it is clear of the pin row, and "clear" is the
    pad's own clearance halo rather than the pad:

        half_length + clearance + track / 2      the halo route.py blocks
        half_length + clearance + track          this, one half-track further

    The extra half track is not a fudge: the escape is snapped *outward* to
    the next grid line after this point, so what the margin buys is that the
    snapped line cannot land on the halo's own boundary, where a cell is
    admitted or not depending on a floating-point comparison.
    """
    return half_length_mm + clearance + track


def fan_out_class(pin_pitch, pad_width, grid=None, track=TRACK_MM,
                  clearance=CLEARANCE_MM):
    """Which of three regimes a package's pin pitch puts it in. A ladder.

    escape_corridor() asks whether a track fits *between* two pins.
    pad_reach() asks whether a cell falls *inside* one. track_offset_limit()
    asks whether a track on that cell clears the next pin. This collects them
    into the question a package is actually chosen against, and the answer has
    three rungs and **three** conditions on the middle one:

        no escape needed        `limit >= grid / 2` -- every phase is legal,
                                because half a grid pitch is the furthest the
                                nearest grid line can ever be. **SOIC**
        an escape reaches it    `2 (edge - clearance) >= track`, so the escape
                                fits on the pad's centre line;
                                `pin_pitch >= grid`, so pins get a grid line
                                each; and the jog clears the neighbour.
                                **TSSOP**
        unreachable             any of those failing. **QFN-56**

    with `edge = pin_pitch - pad_width / 2` and `limit` from
    track_offset_limit().

    **The counting condition is the one nobody would think of.** An escape ends
    on a grid cell and may move at most half a pitch across the row to get
    there, so pins map onto grid lines in order -- and two pins closer together
    than one grid pitch have to share a line, which two nets cannot.

    **The jog condition is the one this function did not have, and its absence
    made a wrong claim about the RP2040.** The jog is `grid / 2` of ordinary
    track pointing at a neighbour `pin_pitch` away, and two tracks need
    `clearance + track` between centres:

        pin_pitch - grid / 2  >=  clearance + track

    **The fitted class fails that for the TSSOP and the four escapes on this
    board are legal anyway**, which is worth being exact about rather than
    grateful for. Adjacent pins' offsets differ by `pin_pitch mod grid` -- 0.15
    mm at 0.65 against 0.5 -- and both pins need an escape only when both
    offsets exceed the limit. At this class that is impossible with the *same*
    sign: 0.125 + 0.15 is more than the 0.25 an offset can reach. So whenever
    two adjacent pins both escape here, their jogs point **away** from each
    other, structurally rather than by luck. `same_direction` is that
    arithmetic, and where it is true the jog condition has to be met outright.

    So a package is reachable when it needs no escape at all, or when the
    escape fits, the pins get a line each, and either the jog clears or the
    arithmetic forbids two adjacent jogs pointing the same way.
    """
    grid = route_pitch() if grid is None else grid
    edge = pin_pitch - pad_width / 2
    widest = 2 * (edge - clearance)
    limit = track_offset_limit(edge, track=track, clearance=clearance)
    half = grid / 2
    step = round(pin_pitch % grid, 9)
    same_direction = (limit + step < half) or (limit < step - half)
    needs_escape = limit < half
    jog_clear = pin_pitch - half >= clearance + track
    escape_works = (widest >= track and pin_pitch >= grid
                    and (jog_clear or not same_direction))
    return {
        "pin_pitch_mm": pin_pitch,
        "pad_width_mm": pad_width,
        "grid_mm": grid,
        "edge_mm": edge,
        "offset_limit_mm": limit,
        "worst_offset_mm": half,
        "needs_escape": needs_escape,
        "lands_in_pad": not needs_escape,
        "escape_track_mm": widest,
        "escape_fits": widest >= track,
        "one_cell_per_pin": pin_pitch >= grid,
        "jog_clear": jog_clear,
        "same_direction": same_direction,
        "escape_works": escape_works,
        "reachable": not needs_escape or escape_works,
    }


# **Hole-to-hole clearance is a rule this file does not own, and that is a gap
# rather than a decision.** gen_pcb.rules() sets the minimum track, via, copper
# clearance and edge clearance through pcbnew, and verify.check_rules() holds all
# four against this module. It sets nothing for holes, so KiCad's own default --
# 0.25 mm, which the DRC report quotes as "board setup constraints hole clearance
# 0.2500 mm" -- is what has been enforcing it. That default is doing real work:
# routing this board at 0.09/0.09 produced **49 hole-clearance violations at
# 0.24 mm**, and every one of them was invisible to route.py, which models copper
# and has no concept of a drill.
#
# Two things about it are worth carrying:
#
#   * **it does not scale with the copper class.** A hole clearance is drill
#     positioning, not etching, so making the tracks finer buys nothing here. At
#     the fitted 0.5 mm grid two vias two cells apart are 1.0 mm centre to
#     centre and the rule is 0.7 mm clear; at 0.23 mm the same two cells are
#     0.46 mm and it is not. via_neighbours() computes the *copper* ring and says
#     nothing about this, which is why a finer grid needs a via lattice rule as
#     well as a via ring;
#   * **the value has not been read.** JLCPCB's capabilities page, quoted at the
#     top of this file, gives the minimum via hole and diameter and this session
#     did not find a hole-to-hole figure on it. So no constant is declared here:
#     KiCad's default is in force, it is documented as such, and reading the real
#     figure is what turns this comment into a rule. Declaring 0.25 because KiCad
#     does would be inventing a fabrication limit, which is the thing section 6 of
#     the spec forbids.
#
# The other seven violations at that class are a different fault and a router
# one: block_pad_ring() grows a pad by `clearance + track / 2`, which is right for
# a track and wrong for a **via**, whose copper is 0.3 mm from its centre rather
# than 0.125. So via_fits() can place a via on a cell that is legal for a track
# and illegal for the via that lands there -- a claim about one object applied to
# another, in the fifth place this project has found one.


def coarsest_class_for(pin_pitch, pad_width, margin=PITCH_MARGIN_MM):
    """The coarsest symmetric track/clearance at which `pin_pitch` is routable.

    **Solved rather than tabulated, because the answer for the RP2040 is not in
    FAB_CLASSES and saying "the 2 oz minimum clears it" was wrong.** Two of
    fan_out_class()'s conditions clear at 0.15/0.15 and the jog condition does
    not, so the honest question is not "which listed class" but "how fine does
    it have to be", and then which copper weight that lands in.

    With `track = clearance = w` and `grid = 2w + margin`, the two ways a
    package can be reachable are

        no escape needed:  edge - w - w/2      >=  (2w + margin) / 2
        the jog clears:    pin_pitch - grid/2  >=  2w

    Both are linear in `w`, so this steps a fine ladder and returns the largest
    that satisfies either. At 0.40 mm of pitch on 0.20 mm pads the answer is
    **0.11 mm**, which is below JLCPCB's 0.15/0.15 2 oz floor and above its
    0.09/0.09 1 oz one -- so the copper weight is the price, and there is no
    intermediate class that avoids paying it.
    """
    edge = pin_pitch - pad_width / 2
    best = None
    for step in range(1, 401):
        w = step * 0.005
        grid = 2 * w + margin
        no_escape = edge - w - w / 2 >= grid / 2
        jog = pin_pitch - grid / 2 >= 2 * w
        if (no_escape or jog) and pin_pitch >= grid:
            best = w
    return {
        "width_mm": best,
        "grid_mm": None if best is None else 2 * best + margin,
        "weight": None if best is None else next(
            (weight for _, track, clearance, weight in FAB_CLASSES
             if best >= track and best >= clearance), "finer than any listed"),
    }


def grid_cost(track, clearance, margin=PITCH_MARGIN_MM):
    """How many more grid cells a class costs, against the fitted one.

    **Cells, and not time -- the two go in opposite directions and this was
    measured after being asserted the other way.** This docstring said "the
    router's work is superlinear in this", and the controller note used 4.7x the
    cells as the cost of the 1 oz class. Timed, on this board, gen_pcb.py end to
    end:

        0.25 / 0.20, grid 0.50 mm, 1.0x cells      89.0 s
        0.09 / 0.09, grid 0.23 mm, 4.7x cells      69.0 s

    **22 % faster on 4.7 times the cells.** The runtime is dominated by
    contention -- routes that fail, probe for what is in the way, rip it up and
    try again -- and not by the size of the grid. A finer grid has more cells and
    far less contention, so nets get through on the first attempt: 1457 track
    runs and 492 vias at the fine class against 1547 and 561 at the fitted one,
    and no net needed a fan-out escape at all.

    So cell count is a proxy that omits the term that dominates, which is the
    same mistake track_current() records about A/mm2 and RAIL_FILTER_ESR records
    upstream. The ratio is still worth returning -- it is what memory and the
    grid's own bookkeeping scale with -- but it is not the cost, and nothing here
    should quote it as one.
    """
    fitted = route_pitch()
    finer = route_pitch(track=track, clearance=clearance, margin=margin)
    return {"grid_mm": finer, "cells": (fitted / finer) ** 2}


# ---------------------------------------------------------------------------
# Current, and the figure of merit that was the wrong instrument
# ---------------------------------------------------------------------------

# IPC-2221's current-capacity curve, as the empirical fit everybody quotes:
#
#     I = k * dT^0.44 * A^0.725      A in square mils, dT in degrees C,
#                                    k = 0.048 external, 0.024 internal
#
# **The source is secondary and this says so.** IPC-2221 is paywalled and has
# not been read here. What was read is a set of independent third-party
# calculators that agree on the exponents and on both constants, which is
# corroboration and not a datasheet -- and CLAUDE.md records two claims in this
# project already overturned by a datasheet contradicting a research summary.
#
# It is quoted anyway, because **the conclusion survives the source being wrong
# by a lot**: dT goes as k^(-1/0.44), so a k three times smaller than this only
# multiplies the answer by 12.6, and the answer is a third of a degree. That is
# the same shape as design.controller_supply()'s efficiency bound -- an
# inequality that cannot be wrong, in place of a number that could be.
IPC_2221_K_EXTERNAL = 0.048
IPC_2221_K_INTERNAL = 0.024
IPC_2221_DT_EXPONENT = 0.44
IPC_2221_AREA_EXPONENT = 0.725
COPPER_OZ_UM = 35.0                    # one ounce, in micrometres


def track_current(amps, width_mm=TRACK_MM, oz=None, external=True):
    """What a track that width costs in temperature rise. Not amps -- degrees.

    **A/mm2 was the wrong instrument and this function exists because it was
    used.** The last pass flagged the coil nets at "29 A/mm2 on 0.09 mm of 1 oz
    copper", called it a number wanting a curve read, and put it in the way of a
    fabrication decision. Current density carries no thermal information at all:
    it divides by the cross-section, which is what carries the current, and omits
    the surface area, which is what does the cooling. A thin trace has a worse
    density and a *better* perimeter-to-area ratio, which is exactly why
    IPC-2221's exponent on area is 0.725 rather than 1.

    Asked properly -- what rise does 92.7 mA cause -- the answer at the finest
    class this board could be ordered at is **0.33 degrees**, and at the fitted
    class 0.019. The question was never close, and the figure that made it look
    close was one this repo already knows the failure mode of: RAIL_FILTER_ESR
    records a number that was not wrong so much as computed without the term
    that dominates.

    `amps` is the current in the trace, not on the rail: design.supply_load()
    puts 94.95 mA on V5 and three relay coils are 30.9 mA each, so the trunk
    beside the regulator is the worst single conductor on this board.
    """
    oz = COPPER_OZ if oz is None else oz
    thickness_mil = oz * COPPER_OZ_UM / 25.4
    area_mil2 = (width_mm / 0.0254) * thickness_mil
    k = IPC_2221_K_EXTERNAL if external else IPC_2221_K_INTERNAL
    scale = k * area_mil2 ** IPC_2221_AREA_EXPONENT
    return {
        "amps": amps,
        "width_mm": width_mm,
        "oz": oz,
        "area_mil2": area_mil2,
        "amps_at_10c": scale * 10.0 ** IPC_2221_DT_EXPONENT,
        "rise_c": (amps / scale) ** (1.0 / IPC_2221_DT_EXPONENT),
        # What the answer becomes if the borrowed constant is three times out.
        "rise_c_if_k_is_3x_out": ((amps / (scale / 3.0))
                                  ** (1.0 / IPC_2221_DT_EXPONENT)),
        "density_a_per_mm2": amps / (width_mm * oz * COPPER_OZ_UM * 1e-3),
    }


# The classes this board could be ordered at, read off the capabilities page
# above. The name is the copper weight it is available with, because that is
# the axis JLCPCB's page actually constrains.
FAB_CLASSES = (
    ("fitted", TRACK_MM, CLEARANCE_MM, "either weight"),
    ("2 oz minimum", 0.15, 0.15, "2 oz outer"),
    ("1 oz minimum", 0.09, 0.09, "1 oz outer only"),
)


def class_table():
    """escape_corridor() at every class this board could be ordered at.

    The result, and it is the reason the routing pass did not need a finer
    grid: the corridor opens only at JLCPCB's finest multilayer class, which is
    available at 1 oz outer copper and not at 2 oz. So "a finer grid with
    thinner track" is not a routing decision at all -- it is a decision to give
    up 2 oz as an option, on a board whose largest current is 120 mA of relay
    coil, in order to save a routing pass that rip-up and retry saves for
    nothing.
    """
    rows = []
    for name, track, clearance, weight in FAB_CLASSES:
        result = escape_corridor(track=track, clearance=clearance)
        rows.append({"class": name, "track_mm": track,
                     "clearance_mm": clearance, "copper": weight, **result})
    return rows


# ---------------------------------------------------------------------------
# Whose limits, and it was the wrong fabricator's for the whole life of the file
# ---------------------------------------------------------------------------
#
# **This file read JLCPCB's page first-hand and never asked whether JLCPCB is
# where the board goes. It is not; the sibling projects go to PCBWay.** That
# is a source read carefully and applied to the wrong thing, which is a
# different fault from the one STYLE.md rule 10 is about and is just as
# expensive: every number below was checked, quoted and enforced, and the
# comparison it was enforcing was against a process nobody is buying.
#
# PCBWay's own capabilities page, https://www.pcbway.com/capabilities.html,
# read 2026-08-19. Its outer-layer table is by copper *thickness*, and the
# rows that bear on this board, converted from mil at 0.0254:
#
#     35 um = 1 oz   normal >= 5/6 mil   = 0.127 / 0.152 mm
#                    medium >= 5/5 mil   = 0.127 / 0.127 mm
#     70 um = 2 oz   normal >= 7/8 mil   = 0.178 / 0.203 mm
#                    medium >= 6/7 mil   = 0.152 / 0.178 mm
#
# with a headline "Standard PCB" row giving *"Min Trace"* and *"Min Spacing"*
# as *"0.1mm/4mil"* with no copper weight attached. **Those two disagree and
# the disagreement is not resolved here**: 0.1 mm is finer than the 1 oz row
# allows, so one of them is a marketing summary and the other is process
# engineering, and which is which is not something this page says. The
# by-weight table is the one enforced, because it is the one that distinguishes
# the thing this board's decision turns on.
#
# **What follows is that the fitted 0.09/0.09 is not manufacturable at PCBWay
# at any copper weight.** It is 29 % under the 1 oz track minimum and 41 %
# under the spacing. The only 3.5 mil entry on the page is at 18 um -- half an
# ounce -- and is qualified *"or parts 3.5/3.5mil"*. So check_fab_class()
# raises, and it is right to: the 55,854 segments on this board are at a class
# the target fabricator does not offer.
FABRICATOR = "PCBWay"
# name -> {oz: (min track mm, min clearance mm)}, from the pages above.
FAB_LIMITS = {
    "JLCPCB": {1: (0.09, 0.09), 2: (0.15, 0.15)},
    "PCBWay": {1: (0.127, 0.152), 2: (0.178, 0.203)},
}
# PCBWay: *"Min Width of Annular Ring: 0.15mm(6mil)"*. JLCPCB's page gives the
# via as a diameter/hole pair rather than a ring, and 0.25/0.15 is a 0.05 mm
# ring, so its published floor is the looser of the two and PCBWay binds again.
ANNULAR_RING_MM = {"JLCPCB": 0.05, "PCBWay": 0.15}
# The smallest hole either will drill, and they agree: PCBWay's page says
# "Min drill size is 0.15mm" and JLCPCB's table bottoms out at the same
# figure. One constant rather than a table, because a table with two equal
# rows invites somebody to believe the rows were read separately.
MIN_DRILL_MM = 0.15


def check_fab_class(fabricator=None):
    """Every fitted rule is inside the fabricator's published minimum. Raises."""
    fabricator = fabricator or FABRICATOR
    limits = FAB_LIMITS[fabricator]
    track_floor, space_floor = limits.get(COPPER_OZ, limits[1])
    if TRACK_MM < track_floor:
        raise AssertionError(
            f"TRACK_MM is {TRACK_MM} mm and {fabricator}'s published minimum "
            f"at {COPPER_OZ} oz is {track_floor} mm -- see the reading at the "
            f"top of this file. The fitted class was chosen against JLCPCB's "
            f"table and the target is {fabricator}")
    if CLEARANCE_MM < space_floor:
        raise AssertionError(
            f"CLEARANCE_MM is {CLEARANCE_MM} mm against a published "
            f"{space_floor} mm at {COPPER_OZ} oz ({fabricator})")
    # **The annular ring, which nothing checked and which was sitting exactly
    # on PCBWay's floor.** Their page gives *"Min Width of Annular Ring:
    # 0.15mm(6mil)"*, and a 0.6 mm via on a 0.3 mm drill is (0.6 - 0.3) / 2 =
    # 0.150 mm -- the floor, to three decimal places, on 767 vias. That is the
    # kind of number that is invisible precisely because it passes: the old
    # check asked whether the diameter and the drill each cleared their own
    # minimum and never asked about the quantity that is a function of both.
    ring = (VIA_DIAMETER_MM - VIA_DRILL_MM) / 2
    if ring < ANNULAR_RING_MM[fabricator]:
        raise AssertionError(
            f"the via's annular ring is {ring:.3f} mm "
            f"(({VIA_DIAMETER_MM} - {VIA_DRILL_MM}) / 2) against "
            f"{fabricator}'s published {ANNULAR_RING_MM[fabricator]} mm")
    # **Both fabricators publish 0.15 mm as the smallest drill**, so this one
    # is not conditional. The 0.25 mm via diameter beside it was JLCPCB's, and
    # PCBWay's page gives the via as a range from 0.15 mm with the ring rule
    # above doing the real work -- which it does: a 0.15 mm drill needs a
    # 0.45 mm pad to make 0.15 mm of ring.
    if VIA_DRILL_MM < MIN_DRILL_MM:
        raise AssertionError(
            f"a {VIA_DRILL_MM} mm drill is below the {MIN_DRILL_MM} mm both "
            f"fabricators publish as their smallest")
    # **JLCPCB's, and it applies when the board goes there.** Their page names
    # two drill/diameter combinations as surcharges; PCBWay's says nothing of
    # the kind, so asserting it against a PCBWay board would be this file's
    # own wrong-page fault repeated on purpose.
    if (fabricator == "JLCPCB" and VIA_DRILL_MM in (0.2, 0.25)
            and VIA_DIAMETER_MM < 0.45):
        raise AssertionError(
            f"a {VIA_DRILL_MM} mm hole with a {VIA_DIAMETER_MM} mm via is one "
            f"of the two combinations JLCPCB's capabilities page says will "
            f"cost more -- if that is intended, say so here")
    if route_pitch() - TRACK_MM < CLEARANCE_MM:
        raise AssertionError(
            f"the routing pitch {route_pitch()} mm puts two adjacent tracks "
            f"{route_pitch() - TRACK_MM} mm apart against a {CLEARANCE_MM} mm "
            f"clearance")


def write():
    """docs/rules.md, so the fabricator reading is a document and not a print.

    Same shape as constraints.py's and floorplan.py's: the prose is generated
    from the functions, so it cannot drift from them. What a person wants off
    this page is the one decision -- whether this board needs a finer class --
    and the table is the answer.
    """
    import contextlib
    import io
    import pathlib
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _report()
    docs = pathlib.Path(__file__).resolve().parent / "docs"
    docs.mkdir(exist_ok=True)
    rows = "\n".join(
        f"| {row['class']} | {row['track_mm']:.2f} / {row['clearance_mm']:.2f} "
        f"| {row['copper']} | {row['window_mm']:+.3f} mm | {row['floor_mm']:.2f}"
        f" mm | {'yes' if row['fits'] else '**no**, at any pitch'} |"
        for row in class_table())
    path = docs / "rules.md"
    path.write_text(
        "# Design rules, and the fabrication class behind them\n\n"
        f"Generated by `rules.py`. Every number is read from "
        f"{FABRICATOR}'s published capabilities page or derived from the two "
        f"that are fitted; the quotations and the date read are in that "
        f"file's docstring.\n\n"
        "**This sentence said JLCPCB for four passes after the board moved to "
        "PCBWay** — in a generated document whose own body quotes PCBWay's "
        "figures three lines below it. A header is prose and the table is "
        "data, and only the data was ever regenerated against the constant "
        "that changed. It reads `FABRICATOR` now.\n\n"
        "## The stackup\n\n"
        f"{FABRICATOR}'s own 4-layer {FAB_FINISHED_MM} mm construction at "
        f"{COPPER_OZ} oz outer copper, which is this board's class. It had "
        "never been chosen: the board carried no `(stackup ...)` block at all, "
        "so KiCad's defaults were in force and the dielectric height — the "
        "number every impedance and coupling figure depends on — was whatever "
        "KiCad assumed. `verify.check_stackup()` is what holds it now.\n\n"
        "| layer | kind | thickness mm | Dk |\n|---|---|---|---|\n"
        + "".join(f"| {name} | {kind} | {thickness} | "
                  f"{dk if dk else '—'} |\n"
                  for name, kind, thickness, dk in FAB_STACKUP)
        + f"\nThe layers sum to {stackup_thickness():.3f} mm against a "
        f"published finished {FAB_FINISHED_MM} mm; the difference is solder "
        "mask. Quoted as published rather than reconciled, because a number "
        "adjusted to make an arithmetic check pass is no longer the "
        f"fabricator's number. An outer layer references "
        f"{outer_dielectric()[0]} mm of prepreg at Dk {outer_dielectric()[1]}."
        "\n\n"
        "```\n" + buffer.getvalue().rstrip() + "\n```\n\n"
        "## Does a routing cell fit between two SOIC pins?\n\n"
        "The question the routing pass was left with, and the reason the "
        "answer turned out not to be a finer grid. A SOIC pad is 0.6 mm across "
        "on a 1.27 mm pitch, so there is 0.67 mm of copper-free space between "
        "two pins. A cell reliably falls in it only when the legal window is "
        "at least one grid pitch wide, and the finest legal pitch is "
        "`track + clearance` — so the test reduces to "
        "`gap >= 3 x clearance + 2 x track`, which does not mention the pitch "
        "at all.\n\n"
        "| class | track / clearance | copper | window | pitch floor | a cell "
        "fits |\n|---|---|---|---|---|---|\n" + rows + "\n\n"
        "**So the corridor opens only at JLCPCB's finest multilayer class, "
        "which is available at 1 oz outer copper and not at 2 oz.** That is "
        "not a routing decision, it is a decision to give up 2 oz as an "
        "option -- and both are history: route.py runs once as a seed and the "
        "board is "
        "hand-laid. `route_all()` finished it without a finer grid, by ripping "
        "up and re-routing the nets that are in the way, so this board is "
        "ordered at the fitted class.\n")
    return path


def main():
    # **The class check is reported rather than raised through, and only
    # here.** check_fab_class() still raises for every caller that is about to
    # write copper -- gen_pcb.py calls it before it places anything. This file
    # writes the *document* that explains the fitted class, and dying before
    # the explanation is written is the one place the raise makes the problem
    # harder to read rather than easier. It still exits non-zero.
    failure = None
    try:
        check_fab_class()
    except AssertionError as error:
        failure = error
    _report()
    if failure:
        print()
        print(f"  ** the fitted class is not manufacturable at "
              f"{FABRICATOR} **")
        print(f"     {failure}")
        print(f"     docs/fabrication-class.md has the decision this reopens")
    path = write()
    print()
    print(f"wrote {path.relative_to(path.parent.parent)}")
    if failure:
        raise SystemExit(1)


def _report():
    pitch = route_pitch()
    print(f"rules: {TRACK_MM} mm track, {CLEARANCE_MM} mm clearance, "
          f"{VIA_DIAMETER_MM}/{VIA_DRILL_MM} mm via, {COPPER_OZ} oz outer")
    print(f"  routing pitch {pitch} mm = track + clearance + "
          f"{PITCH_MARGIN_MM} mm margin; adjacent tracks "
          f"{pitch - TRACK_MM:.2f} mm apart against {CLEARANCE_MM} mm")
    holes = hole_rules()
    exclusion = via_exclusion()
    pad, via_row, copper = HOLE_LIMITS[FABRICATOR]
    print(f"  holes: {holes['min_hole_to_hole']:.3f} mm hole to hole and "
          f"{holes['min_hole_clearance']:.3f} mm hole to copper, each the "
          f"stricter of {FABRICATOR}'s published figure and KiCad's default")
    print(f"      {FABRICATOR} publishes {pad:.3f} / {via_row:.3f} / "
          f"{copper:.3f} mm (component hole, via, hole to copper) against "
          f"KiCad's {KICAD_HOLE_TO_HOLE_MM} / {KICAD_HOLE_CLEARANCE_MM} -- so "
          f"the fabricator is stricter on one and looser on the other, and "
          f"the open question that asked which of two numbers to take had "
          f"the wrong page's number in it")
    print(f"      and neither binds: a via needs "
          f"{exclusion['to_track_mm']:.3f} / {exclusion['to_via_mm']:.3f} / "
          f"{exclusion['to_pad_mm']:.3f} mm to a track, a via and a pad, and "
          f"copper sets all three at this class")
    ring = via_neighbours()
    print(f"  a via clears a track by {ring['orthogonal_mm']:.3f} mm "
          f"orthogonally ({'blocks' if ring['orthogonal_blocks'] else 'clears'})"
          f" and {ring['diagonal_mm']:.3f} mm diagonally "
          f"({'blocks' if ring['diagonal_blocks'] else 'clears'})")
    tssop = escape_corridor(pin_pitch=TSSOP_PIN_PITCH_MM,
                            pad_width=TSSOP_PAD_WIDTH_MM)
    finest = escape_corridor(track=FAB_CLASSES[-1][1],
                             clearance=FAB_CLASSES[-1][2],
                             pin_pitch=TSSOP_PIN_PITCH_MM,
                             pad_width=TSSOP_PAD_WIDTH_MM)
    print(f"  a TSSOP leaves {tssop['gap_mm']:.2f} mm and its window is "
          f"{tssop['window_mm']:+.2f} mm -- {finest['window_mm']:+.2f} at the "
          f"finest class -- so no track centre exists between two of its pins "
          f"and every pin escapes outward")
    reach = pad_reach()
    print(f"  and no cell inside one either: a pad holds a cell at every "
          f"phase only above {reach['needed_pitch_mm']:.2f} mm of pitch, and "
          f"a TSSOP is {reach['short_by_mm'] * 1e3:.0f} um under it -- "
          f"see rules.pad_reach(); route.Grid.escape() was what did something "
          f"about it")
    print(f"  what closes it is the fan-out, and it is a ladder with three "
          f"rungs rather than a threshold:")
    for name, pitch_mm, pad_mm in (("SOIC", SOIC_PIN_PITCH_MM,
                                    SOIC_PAD_WIDTH_MM),
                                   ("TSSOP", TSSOP_PIN_PITCH_MM,
                                    TSSOP_PAD_WIDTH_MM),
                                   ("QFN-56", QFN_PIN_PITCH_MM,
                                    QFN_PAD_WIDTH_MM)):
        rung = fan_out_class(pitch_mm, pad_mm)
        if not rung["needs_escape"]:
            verdict = "a track starts inside the pad at every phase"
        elif rung["reachable"]:
            verdict = ("an escape reaches it, and adjacent jogs are forced "
                       "apart" if not rung["jog_clear"]
                       else "an escape reaches it")
        else:
            why = []
            if not rung["escape_fits"]:
                why.append(f"escape wants {rung['escape_track_mm']:.2f} mm")
            if not rung["one_cell_per_pin"]:
                why.append("two pins per grid line")
            if not rung["jog_clear"] and rung["same_direction"]:
                why.append(f"the jog comes "
                           f"{pitch_mm - rung['worst_offset_mm']:.3f} mm to a "
                           f"neighbour against "
                           f"{CLEARANCE_MM + TRACK_MM:.2f}")
            verdict = "unreachable -- " + "; ".join(why)
        print(f"      {name:<7} {pitch_mm:.2f} mm pitch on {pad_mm:.2f} mm "
              f"pads, {rung['edge_mm']:.3f} mm to the next edge, offset limit "
              f"{rung['offset_limit_mm']:+.3f} against a "
              f"{rung['worst_offset_mm']:.3f} mm worst phase -- {verdict}")
    solved = coarsest_class_for(QFN_PIN_PITCH_MM, QFN_PAD_WIDTH_MM)
    cost = grid_cost(solved["width_mm"], solved["width_mm"])
    print(f"  and the coil nets are not the objection to a finer class -- "
          f"A/mm2 was the wrong instrument:")
    for width, oz in ((TRACK_MM, COPPER_OZ), (0.15, 2), (0.09, 1)):
        row = track_current(0.0927, width_mm=width, oz=oz)
        print(f"      {width:.2f} mm at {oz} oz  {row['density_a_per_mm2']:>6.1f}"
              f" A/mm2, and {row['rise_c']:.3f} C of rise at 92.7 mA "
              f"({row['amps_at_10c'] * 1e3:.0f} mA would be 10 C; "
              f"{row['rise_c_if_k_is_3x_out']:.1f} C if the borrowed constant "
              f"is 3x out)")
    print(f"  a 0.40 mm pitch needs {solved['width_mm']:.2f}/"
          f"{solved['width_mm']:.2f} mm or finer -- a {solved['grid_mm']:.2f} mm "
          f"grid, {cost['cells']:.1f}x the cells -- which is below the 2 oz "
          f"floor of 0.15, so the copper weight is the price and no listed "
          f"class avoids it")
    print(f"  a SOIC leaves {escape_corridor()['gap_mm']:.2f} mm between pads:")
    for row in class_table():
        print(f"      {row['class']:<13} {row['track_mm']:.2f}/"
              f"{row['clearance_mm']:.2f} mm, {row['copper']:<16} "
              f"window {row['window_mm']:+.3f} mm against a "
              f"{row['floor_mm']:.2f} mm floor -- "
              f"{'a cell fits' if row['fits'] else 'no cell fits, at any pitch'}")


if __name__ == "__main__":
    main()
