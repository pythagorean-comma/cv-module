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
    print(f"  a SOIC leaves {escape_corridor()['gap_mm']:.2f} mm between pads:")
    for row in class_table():
        print(f"      {row['class']:<13} {row['track_mm']:.2f}/"
              f"{row['clearance_mm']:.2f} mm, {row['copper']:<16} "
              f"window {row['window_mm']:+.3f} mm against a "
              f"{row['floor_mm']:.2f} mm floor -- "
              f"{'a cell fits' if row['fits'] else 'no cell fits, at any pitch'}")


if __name__ == "__main__":
    main()
