"""Drive KiCadRoutingTools from the constraints this repository already owns.

**The tool is a copper engine and it is not a judge of this board.** It closed
all 185 nets from scratch in minutes, and left unconfigured it would have laid
4.1 metres of signal track through both ground planes -- with its own DRC
clean, its own connectivity clean, and its own improvement gate reporting
`accept`. Every instrument agreed while the thing this board's noise argument
rests on was cut to pieces. That is this repository's oldest failure arriving
from outside it for the first time: **a check that passes and covers less than
its name.**

So the division of labour is the one this repo already has. `rules.py`,
`placement.py` and `design.py` own the constraints; the tool lays copper inside
them; `verify.py` grades the board afterwards, unchanged, because every
question it asks was always asked *of* the board.

This file is the adapter between those. It **generates** every argument the
tool is given from the file that already owns the number, so that no
fabrication constant, no coordinate and no net name is typed here a second
time. What it must not do is hold a second opinion: where a value exists
upstream it is imported, and where the tool needs it in a format of its own
this file translates rather than restates.

**Four settings are load-bearing and each was measured, not assumed:**

* **`--layers` excludes every layer that carries a pour.** `In1.Cu` and
  `In2.Cu` are entirely MAGND and MDGND on this board. The tool defaults to
  "all copper layers" and says so in one line of a two-hundred-line log.
  `routing_layers()` derives the list from the board's own zones rather than
  naming F.Cu and B.Cu, because a layer becomes a plane by being poured on and
  the pour is in `gen_pcb.py`.

* **`--fab-overrides` pins the floor to `rules.py`.** The tool's default
  4-layer floor is **0.0889 mm track and 0.10 mm clearance** -- JLCPCB's
  numbers out of `fab_tiers.py`, where this board is 0.20/0.20 at PCBWay. It
  treats the net class as a *nominal* and the tier as a floor it may escalate
  down to when a net will not otherwise close, and it did: `PIN6` came out as
  34 segments of 0.0889 mm copper, on an audio input, to rescue a route.
  Pinned, `min_clearance_used` reports 0.2 and no sub-class copper is drawn.

* **the primary's region is a keep-out, and it takes two passes.** Measured:
  with no keep-out the router puts 24 pieces of copper inside it, and
  `verify.check_isolation_gap()` catches every one. The tool's keep-out is
  absolute and applies to *every net in the run*, so a single pass with the
  region blocked fails the six primary nets that live inside it -- and the
  improvement gate then rejects and reverts the entire run. The primary nets
  are therefore **excluded from pass one and routed alone in pass two**.

* **the project file is rebuilt afterwards.** The tool rewrites the sibling
  `.kicad_pro` to match the floors it used, and unpinned it wrote
  `min_hole_clearance: 0.25 -> 0.2` and set `annular_width`,
  `solder_mask_bridge` and six more severities to `ignore`. `verify.py` grades
  DRC through `kicad-cli` against that file, so the tool can make this repo's
  own verification pass by moving its goalposts. **The defence already exists
  and is not new work:** `gen_project.py` writes the project from `rules.py`,
  and `gen_pcb.py` re-runs it after `SaveBoard()` for this identical reason.
  Note which number the tool chose -- 0.20 mm copper-to-hole is the exact
  figure `rules.hole_rules()` refused, because adopting it "would have made 49
  violations vanish with no copper moving".

**And one thing it does that `route.py` could not, which closed a question
rather than opening one.** The tool reads the project's net classes, so the
eight nets in the Power class would have come out at 0.5 mm --
`rules.POWER_TRACK_MM`, declared since the first pass with no copper ever drawn
at it, and forbidden by `verify.check_rules()`'s one-width assertion. Forcing
the question is what got it derived: `design.power_track_verdict()` prices the
widening at **7.96 dB on a figure with 94.8 dB of margin**, the constant is
deleted, and both classes declare `TRACK_MM`. So the router draws one width
because the design declares one, and this file needs no mode to arrange it.

**No third-party import lives in this file.** The tool needs numpy, scipy and
shapely; this repo needs to keep running anywhere KiCad runs. So the tool is a
subprocess with an interpreter of its own, the same arrangement `gen_pcb.py`
has with KiCad's bundled Python, and for the same reason.
"""

import argparse
import fnmatch
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "toolchain"))

import design
import kicad
import placement
import rules
import sexp
import verify

OUT = pathlib.Path(__file__).resolve().parent / "out"
BOARD = OUT / "cv-module.kicad_pcb"
PROJECT = OUT / "cv-module.kicad_pro"

# Where the working copies live. Deliberately not `out/`: everything in `out/`
# is either generated by the pipeline or is the tracked board, and a routing
# candidate is neither until somebody promotes it.
WORK = OUT / "krt-work"

# The candidate the tool writes. `--commit` is what moves it onto BOARD, so
# that a run which produced a worse board costs nothing and a run which
# produced a better one is an explicit act with a name in the shell history.
CANDIDATE = OUT / "cv-module-krt.kicad_pcb"

# **A marker rather than a layer test.** The keep-out rectangles are injected
# into a working copy and have to come back out of the routed board, and
# "everything on User.2" would also remove anything a person drew there. A
# uuid this file writes is a piece of geometry this file may delete.
KEEPOUT_UUID = "c0de0000-0000-4000-8000-0000000000"
KEEPOUT_LAYER = "User.2"


class NotFound(Exception):
    """Raised with instructions rather than a bare path error."""


# ---------------------------------------------------------------------------
# Finding the tool, and the interpreter that can run it
# ---------------------------------------------------------------------------

_TOOL_CANDIDATES = (
    pathlib.Path.home() / "code/KiCadRoutingTools",
    pathlib.Path(__file__).resolve().parent.parent / "KiCadRoutingTools",
)


def tool_root():
    """The KiCadRoutingTools checkout, discovered the way socket.py discovers
    the mixer: an explicit override first, then the usual places.

    `$KRT_ROOT` is authoritative when set, because falling through to a default
    would quietly route against a different checkout than the one asked for and
    hide a typo in the variable -- `contract/socket.py` makes the same argument
    about `$SUMMING_MIXER` and `toolchain/kicad.py` about `$KICAD_APP`.
    """
    override = os.environ.get("KRT_ROOT")
    searched = []
    if override:
        root = pathlib.Path(override)
        if (root / "py_router/route.py").exists():
            return root
        raise NotFound(
            f"$KRT_ROOT is set to {override}, which has no py_router/route.py "
            f"beneath it.\nUnset it to search the usual locations instead.")
    for root in _TOOL_CANDIDATES:
        if (root / "py_router/route.py").exists():
            return root
        searched.append(str(root))
    raise NotFound(
        "KiCadRoutingTools was not found.\nLooked in:\n  "
        + "\n  ".join(searched)
        + "\n\nClone it from https://github.com/drandyhaas/KiCadRoutingTools "
          "and run `python build_router.py` inside it, or set\n"
          "  export KRT_ROOT=/path/to/KiCadRoutingTools")


def interpreter(root):
    """A Python that can import the tool's dependencies.

    **The tool needs numpy, scipy and shapely and this repository has none of
    them**, which is not an oversight to correct: the mixer's rule that "there
    is no requirements.txt because there is nothing to install" is what lets
    the verification loop run anywhere KiCad runs, and it survives here
    because the tool is a *subprocess*. So this looks for an interpreter that
    already has them and refuses rather than installing anything.

    Note that KiCad's own bundled 3.9 is **not** a candidate even though it is
    the interpreter `gen_pcb.py` uses: it carries `pcbnew` and none of the
    three. `route.py` parses the board with its own s-expression reader and
    never imports `pcbnew`, so the two interpreters have nothing to do with
    each other.
    """
    override = os.environ.get("KRT_PYTHON")
    candidates = [pathlib.Path(override)] if override else []
    candidates += [root / "krt-venv/bin/python",
                   root / ".venv/bin/python",
                   pathlib.Path(sys.executable)]
    for python in candidates:
        if not python.exists():
            continue
        probe = subprocess.run(
            [str(python), "-c", "import numpy, scipy, shapely"],
            capture_output=True)
        if probe.returncode == 0:
            return python
    raise NotFound(
        "no interpreter with the tool's dependencies was found.\n"
        f"Tried: {', '.join(str(c) for c in candidates)}\n\n"
        "Make one beside the tool and this file will find it:\n"
        f"  python3 -m venv {root / 'krt-venv'}\n"
        f"  {root / 'krt-venv/bin/pip'} install numpy scipy shapely\n"
        "or set $KRT_PYTHON to one that already has them.\n\n"
        "Deliberately not installed here: this repository is stdlib-only so "
        "that its own pipeline runs anywhere KiCad runs, and the tool is a "
        "subprocess precisely so that stays true.")


# ---------------------------------------------------------------------------
# The arguments, each generated from the file that owns the number
# ---------------------------------------------------------------------------

def fab_overrides():
    """The tool's fab-floor file, written from `rules.py`.

    **This is the single most load-bearing argument and it is the one nobody
    would think to pass.** `fab_tiers.py` gives a 4-layer board a "standard"
    floor of 0.0889 mm track and 0.10 mm clearance and escalates to an
    "advanced" rung below that; both are JLCPCB's published tiers, and this
    board is 0.20/0.20 at PCBWay. Supplying this file pins the floor to one
    rung and disables the escalation, which is the tool's own documented
    behaviour rather than a side effect.

    The keys are the tool's and the values are ours. `hole_to_hole` is the
    tool's name for via drill-to-drill, which is what `rules.hole_rules()`
    returns as `min_hole_to_hole`.

    **There is no key for copper-to-hole**, and that is a real gap rather than
    an omission here: the tool works to 0.20 mm internally where
    `rules.hole_rules()` says 0.25, and the two violations it leaves at U19's
    mounting holes cannot be configured away. They are 0.013 and 0.027 mm and
    a person moves them in KiCad; `verify.py` is what reports them.
    """
    holes = rules.hole_rules()
    return (
        "# Generated by krt.py from rules.py -- do not edit.\n"
        f"# {rules.FABRICATOR}, {rules.TRACK_MM}/{rules.CLEARANCE_MM} mm on "
        f"{rules.COPPER_OZ} oz.\n"
        f"track_width  = {rules.TRACK_MM}\n"
        f"clearance    = {rules.CLEARANCE_MM}\n"
        f"via_diameter = {rules.VIA_DIAMETER_MM}\n"
        f"via_drill    = {rules.VIA_DRILL_MM}\n"
        f"hole_to_hole = {holes['min_hole_to_hole']}\n"
        f"board_edge   = {rules.EDGE_CLEARANCE_MM}\n")


def plane_layers(board_text):
    """Every copper layer that carries a pour, read off the board.

    **Derived and not declared, because a layer becomes a plane by being
    poured on.** `gen_pcb.build()` pours MAGND and MDGND on In1.Cu and In2.Cu;
    naming those two here would be a second opinion that goes stale the day
    the stackup changes, and the failure it would cause is silent -- signal
    copper through a reference plane passes DRC, passes connectivity, and
    passes the tool's own improvement gate.
    """
    layers = set()
    for match in re.finditer(r'\(zone\b(.*?)\(polygon', board_text, re.S):
        body = match.group(1)
        if '(keepout' in body:
            continue
        for layer in re.findall(r'\(layers?\s+"([^"]+)"', body):
            if layer.endswith(".Cu"):
                layers.add(layer)
    return layers


def routing_layers(board_text):
    """The copper layers the router may use: every layer that is not a plane."""
    copper = re.search(r'\(layers\b(.*?)\n\t\)', board_text, re.S)
    all_copper = []
    if copper:
        for _number, name in re.findall(r'\((\d+)\s+"([^"]+)"\s+\w+',
                                        copper.group(1)):
            if name.endswith(".Cu"):
                all_copper.append(name)
    planes = plane_layers(board_text)
    usable = [name for name in all_copper if name not in planes]
    if not usable:
        raise NotFound(
            f"every copper layer on this board carries a pour ({sorted(planes)})"
            f" -- there is nothing left to route on")
    return usable


def analogue_half():
    """The rectangle south of the MAGND pour: where audio copper must not go.

    **The copper review's finding, as a region.** `floorplan.CROSSING_RULE`
    says in terms that *"nothing audio-carrying crosses at all"*, and
    `check_crossings()` cannot hold it: that check reads the **netlist** -- a
    net touching parts in both domains -- and a track's *path* is a different
    question from where its endpoints are. Measured on the routed board, two
    audio nets whose every pad is in the analogue half had been taken south of
    the plane edge anyway, `PIN5` for 38 mm and `SIN3` for 19 mm, running over
    MDGND with their return current unable to follow them.

    The boundary is the **pour's** southern edge and not `placement.SPLIT_Y`,
    because what matters to a return current is which copper is underneath it:
    MAGND stops at SPLIT_Y minus half the ground gap, and everything below
    that is either bare or MDGND.

    Deliberately not added to keepout_rects(): most of this board lives down
    there, and a region that is forbidden to the digital half's own nets is
    not a keep-out, it is a wall. It is passed only by --keepout-digital, and
    only for a scope that can honour it.
    """
    west, _north, east, south = placement.outline()
    return ("digital-half", west, placement.SPLIT_Y - placement.GROUND_GAP / 2,
            east, south)


def pads_in_region(board_text, patterns, region):
    """Pads of the scoped nets that fall inside a keep-out. The refusal's basis.

    **A keep-out is absolute across every net in the run** -- krt.plan()
    already records what that costs, because a single pass with the primary's
    region blocked fails the six nets that live inside it and the improvement
    gate reverts the whole thing. This asks the question before the run rather
    than after: if a net in scope has a pad in the region, the router is being
    asked to reach somewhere it may not go, and it will spend five minutes
    finding that out.
    """
    _name, left, top, right, bottom = region
    trapped = []
    for _fp, body in re.findall(r'\t\(footprint "([^"]+)"\n(.*?)\n\t\)\n',
                                board_text, re.S):
        at = re.search(r'^\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)',
                       body, re.M)
        ox, oy = float(at.group(1)), float(at.group(2))
        angle = math.radians(float(at.group(3) or 0))
        ref = re.search(r'\(property "Reference" "([^"]+)"', body).group(1)
        for pin, lx, ly, rest in re.findall(
                r'\(pad "([^"]+)"[^\n]*\n\s*\(at ([-\d.]+) ([-\d.]+)'
                r'[^\)]*\)(.*?)\n\t\t\)', body, re.S):
            found = re.search(r'\(net \d*\s*"?([^")]*)"?\)', rest)
            if not found:
                continue
            net = found.group(1)
            if not any(fnmatch.fnmatch(net, pattern) for pattern in patterns):
                continue
            lx, ly = float(lx), float(ly)
            x = ox + lx * math.cos(angle) + ly * math.sin(angle)
            y = oy - lx * math.sin(angle) + ly * math.cos(angle)
            if left <= x <= right and top <= y <= bottom:
                trapped.append((ref, pin, net))
    return trapped


def keepout_rects():
    """The regions the router may not enter, from the files that own them.

    **One region today and the list is the point.** `verify.check_isolation_gap()`
    forbids non-primary copper west of `placement.ISOLATION_X` between
    `ISOLATION_Y` and `placement.isolation_south()`, and that is the rectangle
    returned here -- the same three numbers, imported, so the router is kept
    out of exactly the region the check measures. A keep-out derived from a
    second reading of the same geometry would be a second opinion, and the one
    thing worse than no keep-out is one that disagrees with the check by half a
    millimetre.

    The rectangle is deliberately the *check's* boundary and not the pour's:
    `gen_pcb.build()` insets its pours by half a ground gap, so a keep-out on
    the pour would let copper into the strip between the two and
    `check_isolation_gap()` would fail on it.

    **And the six fixings are the second entry, which is why the list was the
    point.** `placement.mounting_holes()` derives where the board is bolted
    down, and until this existed nothing told the router the margin was
    reserved -- so it used it. Measured on the board as laid: `PIN5` runs
    **76 mm** through one fixing's keep-out and **107 mm** through another,
    and it is the only net that does. A fixing's keep-out is square rather
    than round because that is what `inject_keepouts()` writes and because a
    square is the conservative shape here; the radius is
    `placement.MOUNTING_KEEPOUT_MM / 2`, the same half-diameter
    `placement.check_mounting_gap()` holds courtyards to.
    """
    west, _north, _east, _south = placement.outline()
    rects = [(
        "primary-isolation",
        west,
        placement.ISOLATION_Y,
        placement.ISOLATION_X,
        placement.isolation_south(),
    )]
    reach = placement.MOUNTING_KEEPOUT_MM / 2.0
    for ref, (x, y, _moved) in placement.mounting_holes().items():
        rects.append((f"fixing-{ref}", x - reach, y - reach,
                      x + reach, y + reach))
    return rects


# **`uniform_project()` was here and it is gone with the constant it existed
# for.** It handed the router a project flattened to one net class, because the
# Power class declared 0.5 mm and `verify.check_rules()` asserts the board
# carries exactly one width -- so every run that touched a Power net produced
# copper this repo would refuse. `design.power_track_verdict()` then priced the
# widening at 7.96 dB against 94.8 dB of margin and `rules.POWER_TRACK_MM` was
# deleted; both classes declare TRACK_MM now, so the real project already says
# what the flattened one said. A mode whose reason has gone is the thing this
# whole file is written about, so it went with it.

# ---------------------------------------------------------------------------
# Injecting and removing the keep-out geometry
# ---------------------------------------------------------------------------

def _rect_sexp(index, name, left, top, right, bottom):
    """One keep-out rectangle, in the form the tool's parser reads.

    `gr_rect` with `start` and `end` immediately following it, which is what
    `kicad_parser.parse_keepout_zones()` matches and what KiCad writes.

    `name` is not written into the file. A `gr_rect` has nowhere to put one,
    and the uuid is what `strip_keepouts()` keys on; the name exists so the run
    can say which region it blocked. Said here because an earlier draft of this
    docstring claimed the name "goes in a comment", and it did not.
    """
    return (f"\t(gr_rect\n"
            f"\t\t(start {left:.6f} {top:.6f})\n"
            f"\t\t(end {right:.6f} {bottom:.6f})\n"
            f"\t\t(stroke\n\t\t\t(width 0.05)\n\t\t\t(type dash)\n\t\t)\n"
            f"\t\t(fill no)\n"
            f"\t\t(layer \"{KEEPOUT_LAYER}\")\n"
            f"\t\t(uuid \"{KEEPOUT_UUID}{index:02d}\")\n"
            f"\t)\n")


def inject_keepouts(text, rects):
    """Append the keep-out rectangles to a board's top level.

    Text insertion rather than a parse-and-re-emit through `toolchain/sexp.py`,
    deliberately. The board is 3.2 MB and 102,909 lines of it churn whenever
    anything rewrites it wholesale; appending before the final paren changes
    exactly the bytes being added, which keeps a diff on the routed board
    readable. `strip_keepouts()` is the exact inverse.
    """
    body = text.rstrip()
    assert body.endswith(")"), "board file does not end in a closing paren"
    blocks = "".join(_rect_sexp(index, *rect)
                     for index, rect in enumerate(rects))
    return body[:-1] + blocks + ")\n"


def strip_keepouts(text):
    """Remove exactly the rectangles this file injected.

    **Keyed on the uuid and not on the layer.** Removing everything on User.2
    would also remove anything a person had drawn there, and the routed board
    is about to be promoted over the one they were working on.
    """
    pattern = (r"\t\(gr_rect\n(?:\t\t.*\n|\t\t\t.*\n)*?"
               r"\t\t\(uuid \"" + re.escape(KEEPOUT_UUID) + r"\d\d\"\)\n\t\)\n")
    return re.sub(pattern, "", text)


# ---------------------------------------------------------------------------
# The passes
# ---------------------------------------------------------------------------

def primary_patterns(negate=False):
    """The primary nets, as the tool's net patterns.

    Imported from `design.PRIMARY_NETS` rather than listed, because the set
    that defines the isolated side is the same one `verify.check_isolation_gap()`
    measures against and `floorplan.py` reports.
    """
    prefix = "!" if negate else ""
    return [f"{prefix}{net}" for net in sorted(design.PRIMARY_NETS)]


def plan(scope, layers, whole_board):
    """The passes to run, in order, as (name, patterns, keepout, gate) tuples.

    **Three passes for a whole board, and the middle one is a rescue.** Each
    was forced by a measurement rather than chosen:

    *Why the primary nets are separate.* The tool's keep-out is absolute and
    applies to every net in a run, so the six nets that live *inside* the
    primary's region cannot be routed while it is active. Left to fail they
    take the whole run with them -- the improvement gate sees six nets go open,
    rejects, and reverts the board to its input, so a naive single pass
    produces no copper at all. Measured, and the revert is correct behaviour.

    *Why there is a rescue at all.* Excluding the primary nets by pattern, the
    keep-out pass **still** lost one net -- `BUF2`, whose five parts sit at
    y = 17..81 mm against a keep-out at y = 194..209 mm. **113 mm apart, and it
    never wanted that corner.** Blocking the supply corner displaced copper
    that congested the CV band a board-length away. That is
    `ENV_ADC_CHANNEL`'s finding a second time, with a keep-out in place of an
    escape: *an escape's copper is not free and it is not spent where it is
    laid.* Nothing here predicts which net it will be; the router is the only
    instrument that knows, so the rescue reads the answer off the run rather
    than carrying a list.

    *Why the first pass runs with the gate off.* `--max-ripup` is not the
    lever -- a run at 12 returned exactly the run at the default, and the tool
    had already said so in its first rejection: *"re-running it with MORE rip
    authority cannot help: change the approach (thinner track / finer grid /
    different layers), or accept the open nets and report them."* A source
    cited and never read, inside the file written about instruments agreeing
    with each other. Of its three approaches two are shut here -- the spare
    layers are reference planes and the track width is the fabrication class --
    so what is left is the third. Accepting the open nets means the pass has to
    be *allowed* to leave them, which is what `gate=False` buys, and
    `plan_gate()` is where the refusal moves to.

    *And why the rescue may drop the keep-out.* A net the keep-out broke is
    not, in general, a net that wants the region -- BUF2 is a board-length from
    it. So the rescue routes without it and `verify.check_isolation_gap()` is
    what says whether that was true, which is the same division this whole file
    is built on: the router lays copper, an instrument that already exists
    grades it. If a rescued net *did* use the region the check fails by name
    and the candidate is not promoted.
    """
    primary = set(design.PRIMARY_NETS)
    if not whole_board:
        # **A scoped run gets the keep-out too, and the first version of this
        # did not.** The reasoning was "a run that does not touch the supply
        # has nothing to keep out of the supply's corner", which confuses where
        # a net's *pads* are with where its *copper* may go. Re-routing the
        # single net RUN -- whose pads are nowhere near the barrier -- took it
        # straight through the primary's region, ten pieces of copper, and
        # check_isolation_gap() named every one. That is BUF2's finding with
        # the sign reversed: a keep-out's effect is not confined to the nets
        # near it, and neither is its absence.
        #
        # Only nets that belong inside the region may ignore it, which is a
        # property of the net and not of the run.
        inside = set(scope) <= primary
        return [("route", list(scope), not inside, True)]
    return [("secondary", [*scope, *primary_patterns(negate=True)],
             True, False),
            ("primary", primary_patterns(), False, True)]


def run_pass(python, root, source, target, arguments, extra, gate=True):
    """One invocation of the tool, with its output streamed through.

    **`gate=False` is how a pass is allowed to leave nets for the next one.**
    The tool's improvement gate compares connectivity across the whole board
    and reverts any run that leaves a net open -- which is right for a run that
    is the whole job, and wrong for the first of three passes that deliberately
    defers what it could not reach. `plan_gate()` is where the comparison moves
    to: the plan's output has to be no worse than the plan's input, and that is
    a different claim from each pass being no worse than its own.
    """
    command = [str(python), str(root / "py_router/route.py"),
               str(source), str(target), "--nets", *arguments,
               "--force-reroute", *extra]
    print(f"  $ {' '.join(command[1:])}", flush=True)
    environment = dict(os.environ)
    if not gate:
        environment["KICAD_IMPROVEMENT_GATE"] = "0"
    finished = subprocess.run(command, capture_output=True, text=True,
                              env=environment)
    # **The whole output is kept and only the tail is printed.** A pass emits
    # a few hundred lines and the interesting ones -- the fab-floor warning,
    # the blocking analysis, the run-scoped summary -- are not all at the end.
    # Printing the tail and keeping nothing is how the first version of this
    # file lost the summary that would have shown its own reporting bug.
    log = target.with_suffix(".log")
    log.write_text((finished.stdout or "") + (finished.stderr or ""))
    sys.stdout.write(finished.stdout[-4000:] if finished.stdout else "")
    if finished.returncode != 0:
        sys.stderr.write(finished.stderr[-4000:] if finished.stderr else "")
        raise SystemExit(f"route.py exited {finished.returncode}")
    return finished.stdout


def verdicts(output):
    """The tool's own machine-readable lines, as dicts.

    **A run emits several `JSON_SUMMARY` lines and only one of them is about
    the run.** `scope: "run"` is the pass; `scope: "reconciliation-subset"` is
    a retry of the nets the pass could not reach on its first attempt. Taking
    the last one -- which the first version of this function did -- reported
    the keep-out pass as *"routed 0, failed 1"* when it had routed 176 nets and
    deferred one. The decision it fed was still right, because the rescue reads
    `failed_single` and the final subset's list is the final state; the number
    printed beside it was wrong, and a number that is wrong in the direction of
    "nothing worked" is one somebody acts on.

    So: the counts come from the run-scoped summary and `failed_single` comes
    from the last, which are two different questions -- *what did this pass
    do* and *what is still open* -- that happened to share a field.

    `JSON_IMPROVEMENT_GATE` is a separate line and there is one of it.
    """
    summaries = []
    gate = {}
    for line in output.splitlines():
        if line.startswith("JSON_SUMMARY:"):
            summaries.append(json.loads(line[len("JSON_SUMMARY:"):]))
        elif line.startswith("JSON_IMPROVEMENT_GATE:"):
            gate = json.loads(line[len("JSON_IMPROVEMENT_GATE:"):])
    if not summaries:
        return {"summary": {}, "gate": gate, "still_open": []}
    scoped = [row for row in summaries if row.get("scope") == "run"]
    return {"summary": scoped[-1] if scoped else summaries[-1],
            "gate": gate,
            "still_open": list(summaries[-1].get("failed_single", ()))}


def refill_zones(board):
    """Re-pour the zones, through KiCad, before anything grades the board.

    **This is the step whose absence made the tool unusable, and nothing this
    file checked could see it.** `route.py` copies the input board's
    `filled_polygon` data through untouched, so a routed board carries pours
    that were filled around the *old* via positions: every new via sits in
    solid plane copper with no antipad, at 0.0000 mm clearance. Measured on
    this board -- **503 clearance and 204 hole-clearance violations, all of
    them a via against MDGND on In1.Cu or In2.Cu, and every one gone after a
    refill.**

    Why nothing caught it is the part to keep. `check_connected.py` passes,
    because a via shorted to a plane it should clear is *more* connected, not
    less. The improvement gate passes for the same reason. And
    `check_planes_intact()` passes because it reads **segments**, and these are
    **vias** -- a check that was written to say the planes are unbroken and
    that examines one of the two things that can break them. That is this
    repo's oldest failure inside the function written for it, which is now the
    third time this project has recorded exactly that shape.

    `--save-board` requires `--refill-zones`; both are KiCad's own, so the
    pour is the one KiCad would compute rather than one this file models.
    """
    finished = subprocess.run(
        [str(kicad.KICAD_CLI), "pcb", "drc", "--refill-zones", "--save-board",
         "--format", "json", "-o", str(board.with_suffix(".drc.json")),
         str(board)],
        capture_output=True, text=True)
    if finished.returncode not in (0, 5):     # 5 = violations found, not a crash
        raise SystemExit(
            f"zone refill failed ({finished.returncode}):\n{finished.stderr[-2000:]}")


def plan_gate(python, root, board):
    """Is every net on this board connected?

    **The gate the passes gave up, put back at the level it belongs to.** Run
    through the tool's own `check_connected.py` rather than reimplemented here:
    a third opinion about what "connected" means is exactly the thing this repo
    keeps finding, and that checker is the one whose model the router itself
    was graded against. It exits 0 for a fully connected board.

    This is what makes `gate=False` on the deferring passes safe. It is not a
    weaker claim than the per-pass gate -- it is the same claim, made once,
    about the artefact that is actually going to be promoted.
    """
    finished = subprocess.run(
        [str(python), str(root / "py_router/check_connected.py"), str(board)],
        capture_output=True, text=True)
    # The checker names each offender as `  MCLK (net 72):` under its issue
    # heading. Parsed rather than taken from the exit code alone, because "the
    # board has an open net" and "which net" are the difference between a
    # refusal somebody can act on and one they have to reproduce.
    open_nets = re.findall(r"^\s+(\S+) \(net \d+\):$", finished.stdout,
                           re.M)
    return finished.returncode == 0, open_nets[:8]


# ---------------------------------------------------------------------------
# What this file checks, which is only what verify.py cannot
# ---------------------------------------------------------------------------

def check_planes_intact(board):
    """No signal copper on any layer that carries a pour.

    **This is the one check here that exists because nothing else in this
    repository has it**, and it is the finding that made this file necessary.
    `verify.check_rules()` reads track widths and via sizes, and
    `check_ground_split_on_the_board()` reads where the two pours are -- but
    nothing asks which *layer* a segment is on, because until now nothing could
    put one there: `route.py` was handed two layers and had no way to use a
    third.

    A track on In1.Cu is a slot in the reference plane directly under the
    audio it is returning. DRC does not object, because the zone filler simply
    flows around it with clearance; connectivity does not object, because the
    net is connected; and the coupling it creates is the thing
    `barrier_return()` spends a 2 x 1 mH choke to keep out of the audio bond.
    Measured: the tool's default run laid 4106 mm of it.

    **What this does NOT cover, said here because the name overclaimed it for
    one pass: vias.** A via through a plane is legitimate -- it takes an
    antipad and the return current goes round -- so it is not a fault to be
    listed here. But it *is* the other thing that can break a plane, and this
    function passed a board carrying 503 via-to-plane clearance violations
    while reporting "planes intact". The violations were real and the cause
    was a stale pour; `refill_zones()` is the fix and DRC is the instrument.
    A check named for the plane that reads only one of the two things that
    perforate it is this repo's own oldest failure, and it happened inside the
    function written to catch it.
    """
    text = board.read_text()
    planes = plane_layers(text)
    problems = []
    offenders = {}
    # **Through toolchain/sexp.py and not a regex of this file's own.** The
    # first version of this check scanned for `(segment ... (layer ...))` with
    # a hand-written pattern, and it reported zero problems on a board carrying
    # 4106 mm of exactly the fault it exists to find. A check that passes and
    # covers nothing is the failure this whole file is written about, and it
    # arrived inside the function written to catch it. verify.check_rules()
    # already reads segments this way; there is one parser for this format in
    # this repository and it is not here.
    for segment in sexp.find_all(sexp.parse(text), "segment"):
        layer = sexp.find(segment, "layer")
        net = sexp.find(segment, "net")
        if layer is None or layer[1] not in planes:
            continue
        offenders.setdefault(layer[1], set()).add(
            str(net[1]) if net is not None else "?")
    for layer in sorted(offenders):
        nets = sorted(offenders[layer])
        problems.append(
            f"{layer} carries a pour and {len(nets)} net(s) of signal copper "
            f"({', '.join(nets[:6])}{'...' if len(nets) > 6 else ''}) -- a "
            f"track through a reference plane is a slot in the return path, "
            f"and DRC has no opinion about it")
    return problems


def check_project_is_ours(project):
    """The project file still says what `rules.py` says.

    A thin restatement of `verify.check_rules()`'s first half, run here for
    timing rather than for coverage: the tool rewrites the sibling project on
    its way out, and this catches it immediately rather than at the end of the
    next pipeline run. `verify.py` remains the authority.
    """
    import gen_project
    document = json.loads(project.read_text())
    found = document.get("board", {}).get("design_settings", {}).get("rules", {})
    problems = []
    for key, value in sorted(gen_project.design_rules().items()):
        if key not in found:
            problems.append(f"the project no longer declares {key}")
        elif abs(float(found[key]) - value) > 1e-9:
            problems.append(
                f"the project's {key} is {found[key]} and rules.py says "
                f"{value} -- the router rewrote it; gen_project.py puts it back")
    severities = document.get("board", {}).get("design_settings", {}).get(
        "rule_severities", {})
    ignored = sorted(k for k, v in severities.items() if v == "ignore")
    if ignored:
        problems.append(
            f"DRC severities {ignored} are set to 'ignore' -- the router "
            f"writes these, and verify.py runs kicad-cli against this file")
    return problems


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Route this board with KiCadRoutingTools, under the "
                    "constraints rules.py, placement.py and design.py own.")
    parser.add_argument("--nets", nargs="+", default=None, metavar="PATTERN",
                        help="net patterns to route. Default: every net, in "
                             "two passes with the primary's region kept out")
    parser.add_argument("--keepout-digital", action="store_true",
                        help="keep this run out of everything south of the "
                             "MAGND pour. For audio nets whose pads are all "
                             "in the analogue half; refuses if any net in "
                             "scope has a pad in the region")
    parser.add_argument("--commit", action="store_true",
                        help="move the routed candidate onto out/"
                             "cv-module.kicad_pcb and re-run gen_project.py")
    parser.add_argument("--preview", action="store_true",
                        help="report what would change and write no board")
    parser.add_argument("--max-ripup", type=int, default=None, metavar="N",
                        help="how many blockers the router may rip at once. "
                             "Left at the tool's own default: raising it does "
                             "NOT rescue the keep-out pass, measured -- "
                             "see plan()")
    parser.add_argument("--keep-work", action="store_true",
                        help="leave out/krt-work/ in place for inspection")
    args = parser.parse_args(argv)

    root = tool_root()
    python = interpreter(root)
    print(f"tool        {root}")
    print(f"interpreter {python}")

    if not BOARD.exists():
        raise SystemExit(f"{BOARD} does not exist -- run gen_pcb.py")

    text = BOARD.read_text()
    layers = routing_layers(text)
    planes = plane_layers(text)
    print(f"planes      {sorted(planes)} -- excluded from routing")
    print(f"routing on  {layers}")

    # A scoped run is somebody touching up a region and the region is theirs;
    # a whole-board run is the two-pass plan. The keep-out follows the scope
    # for that reason rather than being a flag: a run that does not touch the
    # supply has nothing to keep out of the supply's corner.
    whole_board = args.nets is None
    scope = args.nets or ["*"]
    rects = keepout_rects()
    if args.keepout_digital:
        region = analogue_half()
        trapped = pads_in_region(text, scope, region)
        if trapped:
            raise SystemExit(
                f"--keepout-digital would strand "
                f"{len(trapped)} pad(s) it cannot reach: "
                + ", ".join(f"{ref}.{pin} [{net}]"
                            for ref, pin, net in trapped[:8])
                + ("..." if len(trapped) > 8 else "")
                + "\n\nThe tool's keep-out is absolute across every net in a "
                  "run, so a net with a pad inside the region cannot be "
                  "routed with it on. Nine of this board's audio nets reach a "
                  "relay contact at y = 161.4 and are in exactly that "
                  "position; PIN5 and SIN3 are not. Narrow the scope.")
        rects = rects + [region]

    WORK.mkdir(parents=True, exist_ok=True)
    source = WORK / "cv-module.kicad_pcb"
    # Injected always: a scoped run needs the region blocked too, and the
    # rectangles are inert unless a pass passes --keepout.
    source.write_text(inject_keepouts(text, rects))

    (WORK / "cv-module.kicad_pro").write_text(PROJECT.read_text())
    overrides = WORK / "fab-floor.txt"
    overrides.write_text(fab_overrides())
    print(f"fab floor   {rules.TRACK_MM}/{rules.CLEARANCE_MM} mm, vias "
          f"{rules.VIA_DIAMETER_MM}/{rules.VIA_DRILL_MM} mm, pinned")
    for name, left, top, right, bottom in rects:
        print(f"keep-out    {name}: x {left:.2f}..{right:.2f}, "
              f"y {top:.2f}..{bottom:.2f}")

    extra = ["--fab-overrides", str(overrides)]
    if args.max_ripup is not None:
        extra += ["--max-ripup", str(args.max_ripup)]
    if args.preview:
        extra.append("--preview")

    current = source
    step = 0
    passes = plan(scope, layers, whole_board=whole_board)
    layer_args = ["--layers", *layers]

    def execute(name, patterns, keepout, gate):
        """Run one pass, print its verdict, and return the nets it could not
        reach. Refuses on a gated rejection, because a gated pass that is
        rejected has written nothing and re-running it cannot help."""
        nonlocal current, step
        step += 1
        target = WORK / f"pass{step}.kicad_pcb"
        shutil.copy(WORK / "cv-module.kicad_pro",
                    target.with_suffix(".kicad_pro"))
        print(f"\n-- pass {step}: {name} " + "-" * 40)
        arguments = [*patterns, *layer_args] + (["--keepout"] if keepout else [])
        output = run_pass(python, root, current, target, arguments, extra,
                          gate=gate)
        report = verdicts(output)
        summary, verdict = report["summary"], report["gate"]
        failed = report["still_open"]
        print(f"   routed {summary.get('successful', '?')}, "
              f"failed {summary.get('failed', '?')}, "
              f"min clearance {summary.get('min_clearance_used', '?')} mm, "
              f"gate {verdict.get('verdict', 'off' if not gate else '?')}")
        if gate and verdict.get("verdict") == "reject":
            raise SystemExit(
                f"pass {step} ({name}) was rejected by the tool's improvement "
                f"gate -- it broke {verdict.get('lost')} and the board was "
                f"reverted. Nothing was written.")
        if failed:
            print(f"   deferred: {', '.join(failed)}")
        current = target
        return failed

    for name, patterns, keepout, gate in passes:
        deferred = execute(name, patterns, keepout, gate)
        # **The rescue, and it is derived rather than listed.** A net the
        # keep-out broke is not in general a net that wants the region, so it
        # is retried with the keep-out off -- and check_isolation_gap() below
        # is what says whether dropping it was true for this net rather than
        # true in general.
        if deferred and keepout:
            execute(f"rescue ({len(deferred)})", deferred, False, True)

    if args.preview:
        print("\npreview only -- no board written")
        return 0

    final = strip_keepouts(current.read_text())
    CANDIDATE.write_text(final)
    # Before anything grades it: the pours in that file were filled around the
    # *input* board's vias. See refill_zones().
    shutil.copy(PROJECT, CANDIDATE.with_suffix(".kicad_pro"))
    refill_zones(CANDIDATE)
    print(f"\ncandidate   {CANDIDATE}  (zones refilled)")

    problems = check_planes_intact(CANDIDATE)
    for problem in problems:
        print(f"  PLANE  {problem}")
    if not problems:
        print(f"  planes intact: no signal copper on {sorted(planes)}")

    connected, open_nets = plan_gate(python, root, CANDIDATE)
    if connected:
        print("  every net connected (the tool's own check_connected.py)")
    else:
        problems.append(
            "the candidate has unconnected nets: "
            + ("; ".join(open_nets) if open_nets else "see check_connected.py"))
        print(f"  GATE   {problems[-1]}")

    # **The rescue's own check, and it is verify.py's rather than this file's.**
    # The rescue pass drops the keep-out on the theory that a net the keep-out
    # broke did not want the region. That is a theory about each net, and this
    # is where it is tested -- by the instrument that already owns the
    # question, against the same three coordinates the keep-out was built from.
    isolation = verify.check_isolation_gap(CANDIDATE)
    if isolation:
        problems.extend(isolation)
        for problem in isolation[:4]:
            print(f"  ISOLATION  {problem}")
        print(f"  ISOLATION  ({len(isolation)} in total)")
    else:
        print("  primary's region clear")

    # **Enforced rather than reported, and gen_pcb_guard is the precedent.**
    # "A rule the tool cannot break is worth more than a rule it is caught
    # breaking" is that file's own argument, made after documenting a hazard in
    # three places and leaving the trigger in the run order. Signal copper on a
    # reference plane is the fault this whole file exists to prevent, and every
    # other instrument on this board passes a board that has it -- so printing
    # it and committing anyway would be the same mistake with better prose.
    if problems and args.commit:
        raise SystemExit(
            f"refusing to commit: {len(problems)} problem(s) above. The "
            f"candidate is left in place. Signal copper on a reference plane, "
            f"an open net and copper in the primary's region are each a fault "
            f"that some other instrument on this board passes.")

    if args.commit:
        shutil.copy(CANDIDATE, BOARD)
        print(f"committed   {BOARD}")
        # **The one mandatory post-step.** SaveBoard() flattening the project
        # is why gen_pcb.py re-runs this; the router rewriting it is the same
        # failure with a different cause and the same fix.
        subprocess.run([sys.executable, "gen_project.py"], check=True,
                       cwd=pathlib.Path(__file__).resolve().parent)
        for problem in check_project_is_ours(PROJECT):
            print(f"  PROJECT  {problem}")
        print("\nrun `python3 verify.py` -- it is the authority on this board, "
              "and nothing above replaces it")
    else:
        print("\nnot committed. Inspect it, then re-run with --commit")

    if not args.keep_work:
        shutil.rmtree(WORK, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
