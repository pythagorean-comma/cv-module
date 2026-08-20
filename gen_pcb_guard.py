"""gen_pcb.py's write guard, importable without KiCad.

**Split out for one reason and it is test_verify.py's.** gen_pcb.py relaunches
itself under KiCad's bundled interpreter and imports `pcbnew` at module scope,
so nothing running under the project's own Python can import it -- which would
have made the guard the one invariant in this repository that cannot be shown
to fail. It is the same argument placement.py makes for not importing KiCad: a
rule that can only be exercised inside the thing that needs `pcbnew` is a rule
nobody can check.
"""

import pathlib
import re
import sys

GROUND_NETS = frozenset({"MAGND", "MDGND"})


def refuse_to_discard_routing(board, argv=None, out_name=None):
    """Stop, if the board on disk has hand-routed copper on it.

    **This exists because documenting the hazard was not enough, and the proof
    is that the same pass that documented it left the trigger in the run
    order.** gen_pcb.py's docstring, CLAUDE.md and README.md all say that
    re-running that file destroys hand-routed copper -- and both of those files
    also carried a one-line pipeline with `python3 gen_pcb.py` in the middle of
    it, which anybody following the documented workflow would have pasted
    straight into a terminal.

    That is this repository's own named failure mode wearing a new hat: **a
    rule that is written down and not enforced.** A rule the tool cannot break
    is worth more than a rule it is caught breaking, which is the argument
    gen_pcb.py already makes about the router and the isolation region.

    **What counts as hand-routed is a net name and not a count.** Everything
    gen_pcb.py lays by default is a ground stitch -- a via and a stub on MAGND
    or MDGND -- so a segment on any other net is copper somebody else put
    there. That is exact in both directions: a freshly generated board has
    none, and a board with one routed net has one. A threshold on the segment
    count would have been the obvious thing and it would have had to be
    re-tuned every time the stitch count moved.

    **`--seed-routing` puts signal copper on the board and this still refuses
    it afterwards, which is the behaviour that is wanted and not an
    oversight.** The seed is laid once and is a starting point somebody edits;
    from the moment it lands, the board carries copper that re-running would
    destroy, and whether the first pass of it came from route.py or from a
    person is not a distinction this guard should be able to draw. It is
    deliberately not told which -- "the board has copper on it" is the whole
    question, and a guard that exempted the router's own output would exempt
    exactly the board most likely to have been edited since.

    `--discard-routing` is the way past it, spelled so that nobody types it by
    accident and so that it appears in a shell history as what it was.
    """
    board = pathlib.Path(board)
    argv = sys.argv[1:] if argv is None else argv
    if "--discard-routing" in argv or not board.exists():
        return
    signal = set()
    for match in re.finditer(r'\(segment\b(?:[^()]|\([^()]*\))*\)',
                             board.read_text()):
        net = re.search(r'\(net "?([^")\s]+)"?\)', match.group(0))
        if net and net.group(1) not in GROUND_NETS:
            signal.add(net.group(1))
    if not signal:
        return
    raise SystemExit(
        f"{out_name or board.name} carries hand-routed copper on "
        f"{len(signal)} nets ({', '.join(sorted(signal)[:6])}"
        f"{', ...' if len(signal) > 6 else ''}).\n"
        f"\n"
        f"gen_pcb.py writes a fresh board -- placed, poured and stitched -- "
        f"so writing it would discard every one of those tracks. There is no "
        f"undo.\n"
        f"\n"
        f"  * to move a *netlist* change onto the routed board, use KiCad's\n"
        f"    Tools -> Update PCB from Schematic against "
        f"out/cv-module.kicad_sch;\n"
        f"  * to start the layout again from placement.py, deliberately:\n"
        f"        python3 gen_pcb.py --discard-routing\n"
        f"    adding --seed-routing runs route.py once for a first pass of\n"
        f"    copper to adjust, which is what the handover board was made\n"
        f"    with. Either way the tracks above are gone.\n")
