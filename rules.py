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

# ---------------------------------------------------------------------------
# The rules as fitted
# ---------------------------------------------------------------------------

# Outer copper weight. **The rules below are chosen to be legal at either
# weight**, which is why this is a declaration and not yet a decision: nothing
# on this board needs 2 oz -- design.coil_budget()'s 75-120 mA of relay coil is
# the largest current anywhere on it and 0.25 mm of 1 oz carries that with a
# rise of a few degrees -- but keeping the option costs nothing while the
# fitted class is three times the 2 oz minimum. It stops costing nothing the
# moment anything asks for 0.09 mm; see escape_corridor().
COPPER_OZ = 2

# 0.25 mm against JLCPCB's 0.15 mm minimum at 2 oz: 1.7x the published floor.
# This board's constraint is area and part count, not track width, and a track
# three thou wider than it needs to be is free everywhere except between two
# pins of a SOIC -- which is the one place it turned out to matter, and the
# place escape_corridor() shows it does not matter enough to move.
TRACK_MM = 0.25

# The rails and both grounds, per the Power net class. Not used by the router,
# which draws every signal at TRACK_MM; this is what a rail is widened to when
# somebody widens one, and it is declared here so gen_project.py and the board
# cannot disagree about it.
POWER_TRACK_MM = 0.5

# 0.2 mm against 0.15 mm published at 2 oz. The margin is deliberate and it is
# the same argument as the track: 0.05 mm is 33 % of the fabricator's floor and
# it is free.
CLEARANCE_MM = 0.2

# 0.6 mm diameter on a 0.3 mm hole. **Chosen to sit outside every surcharge the
# capabilities page names**, which is the one place that page gives a price:
# a 0.3 mm hole is neither of the two sizes it calls out, and 0.6 mm is above
# the 0.45 mm diameter below which the small holes cost more. The published
# minimum is 0.25 mm on a 0.15 mm hole and this design has no reason to go
# near it.
VIA_DIAMETER_MM = 0.6
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
    are is free again. See track_offset_limit() and route.Grid.escape().
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
    a different question.** route.Grid.block_pad_copper() insets a pad by half
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

    Quoted rather than guessed because the first draft of the controller note
    said "four times the cells" for a class that costs 2.0x, and 4.7x for the
    one that actually clears. The router's work is superlinear in this.
    """
    fitted = route_pitch()
    finer = route_pitch(track=track, clearance=clearance, margin=margin)
    return {"grid_mm": finer, "cells": (fitted / finer) ** 2}


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


def check_fab_class():
    """Every fitted rule is inside the fabricator's published minimum. Raises."""
    limits = {"2 oz outer": 0.15, "1 oz outer only": 0.09}
    floor = limits["2 oz outer"] if COPPER_OZ == 2 else limits["1 oz outer only"]
    if TRACK_MM < floor:
        raise AssertionError(
            f"TRACK_MM is {TRACK_MM} mm and JLCPCB's published minimum at "
            f"{COPPER_OZ} oz is {floor} mm -- see the reading at the top of "
            f"this file, and note that reaching 0.09 mm means 1 oz")
    if CLEARANCE_MM < floor:
        raise AssertionError(
            f"CLEARANCE_MM is {CLEARANCE_MM} mm against a published "
            f"{floor} mm at {COPPER_OZ} oz")
    if VIA_DIAMETER_MM < 0.25 or VIA_DRILL_MM < 0.15:
        raise AssertionError(
            f"via {VIA_DIAMETER_MM}/{VIA_DRILL_MM} mm is below the published "
            f"0.25/0.15 mm minimum")
    if VIA_DRILL_MM in (0.2, 0.25) and VIA_DIAMETER_MM < 0.45:
        raise AssertionError(
            f"a {VIA_DRILL_MM} mm hole with a {VIA_DIAMETER_MM} mm via is one "
            f"of the two combinations the capabilities page says will cost "
            f"more -- if that is intended, say so here")
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
        "Generated by `rules.py`. Every number is read from JLCPCB's published "
        "capabilities page or derived from the two that are fitted; the "
        "quotations and the date read are in that file's docstring.\n\n"
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
        "option. `route.route_all()` finishes the board without it, by ripping "
        "up and re-routing the nets that are in the way, so this board is "
        "ordered at the fitted class.\n")
    return path


def main():
    check_fab_class()
    _report()
    path = write()
    print()
    print(f"wrote {path.relative_to(path.parent.parent)}")


def _report():
    pitch = route_pitch()
    print(f"rules: {TRACK_MM} mm track, {CLEARANCE_MM} mm clearance, "
          f"{VIA_DIAMETER_MM}/{VIA_DRILL_MM} mm via, {COPPER_OZ} oz outer")
    print(f"  routing pitch {pitch} mm = track + clearance + "
          f"{PITCH_MARGIN_MM} mm margin; adjacent tracks "
          f"{pitch - TRACK_MM:.2f} mm apart against {CLEARANCE_MM} mm")
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
          f"see rules.pad_reach(), and route.Grid.escape() for what is done "
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
