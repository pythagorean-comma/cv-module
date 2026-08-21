"""The board's fixings: six M3 holes, and the copper keep-out each one needs.

**Why this is its own file and not part of `gen_pcb.py`.** `gen_pcb.py` writes
a fresh board and lays no signal copper, so running it over a routed board
discards the routing -- `gen_pcb_guard.refuse_to_discard_routing()` refuses.
This adds six footprints and six rule areas to the board that is there, the way
`returns.py` adds ground stitches to it, and disturbs no copper already laid.

**Why it needs `pcbnew` where `returns.py` needed only text.** A stitch is a
via in copper that already exists. A fixing is a *hole through both reference
planes*, and an M3 screw through `In1.Cu` and `In2.Cu` -- MAGND and MDGND --
would bridge the two ground domains at every fixing. That is a second star, and
constraint 5.2 is the reason there is exactly one. So each hole needs the pours
voided around it, and a zone fill is not something a text edit can do.

Which makes the ordering matter, exactly as it does for `gen_pcb.py`:
`SaveBoard()` rewrites the sibling project with KiCad's defaults, so this
re-runs `gen_project.py` and `rules.apply_stackup()` afterwards. The mixer's
`build.sh` exists for that reason and says several hours were spent chasing
violations that were only that.

**The pattern is not decided here.** `placement.mounting_deflection()` decides
how many -- six, because four is worth nothing over two on a 233 mm board and
eight buys 5x where six buys 16x -- and `placement.mounting_holes()` decides
where, by walking each fixing along its own edge until the keep-out clears
every courtyard. This file only puts them on the board and says whether it
worked.

**And the router has to be told, or it puts the copper back.** Nothing reserved
the margin until `krt.keepout_rects()` grew its second entry, so the board as
routed had `PIN5` running 183 mm through two of the six fixings. Re-run
`krt.py` without that keep-out and it will do it again.

    python3 mounts.py             # measure and report, write nothing
    python3 mounts.py --commit    # add them
"""

import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"
PROJECT = "cv-module"
BOARD = OUT / f"{PROJECT}.kicad_pcb"

# The land pattern, and the head style is deliberately not in it. KiCad ships
# MountingHole_3.2mm_M3 plus one variant per screw head -- DIN965 countersunk,
# ISO7380 button, and so on -- and which head goes in is a decision for the
# enclosure that is drawn after this board. The plain footprint carries the
# hole; placement.MOUNTING_KEEPOUT_MM carries the clearance, as a rule area
# this file draws, so the number that matters is derived here rather than
# inherited from whichever variant somebody picked.
FOOTPRINT_LIB = "MountingHole"
FOOTPRINT_NAME = "MountingHole_3.2mm_M3"


def _relaunch(argv):
    """Re-run this file under KiCad's bundled Python, then fix the project."""
    sys.path.insert(0, str(HERE))
    from toolchain import kicad
    import rules

    interpreter = kicad.BUNDLED_PYTHON
    if interpreter is None:
        raise SystemExit(
            "pcbnew lives in KiCad's own Python and this install does not "
            "bundle one.")
    # **Two child processes on a commit, and one of them exists because of a
    # SWIG fact.** After board.Remove(), pcbnew's type registry stops
    # resolving for the rest of the *process*: GetArea() hands back raw
    # SwigPyObjects and even module-level pcbnew.FootprintLoad() comes back as
    # an object with no FootprintLoad on it. Reloading the board does not
    # clear it. So a replacement is remove-and-save in one interpreter and
    # add-and-fill in the next, which costs a second launch and nothing else.
    passes = [["--remove-only"] + argv, argv] if "--commit" in argv else [argv]
    for arguments in passes:
        result = subprocess.run(
            [str(interpreter), str(HERE / "mounts.py")] + arguments,
            env={**os.environ, "CV_MOUNTS_CHILD": "1"})
        if result.returncode != 0:
            raise SystemExit(result.returncode)
    if "--commit" not in argv:
        return
    # Both for SaveBoard()'s sake, and both are gen_pcb.py's own reasons.
    print("  re-running gen_project.py: SaveBoard() rewrote the project")
    again = subprocess.run([sys.executable, str(HERE / "gen_project.py")],
                           capture_output=True, text=True)
    if again.returncode != 0:
        raise SystemExit(again.stdout + again.stderr)
    if rules.apply_stackup(BOARD):
        print("  wrote rules.FAB_STACKUP back into the board")
    if rules.apply_thickness(BOARD):
        print("  wrote rules.FAB_FINISHED_MM back into the board")


if os.environ.get("CV_MOUNTS_CHILD") != "1":
    _relaunch(sys.argv[1:])
    raise SystemExit(0)

# ---------------------------------------------------------------------------
# From here down, this is running under KiCad's interpreter.
# ---------------------------------------------------------------------------

import pcbnew                                                    # noqa: E402

sys.path.insert(0, str(HERE))
import placement                                                 # noqa: E402


def _mm(value):
    return pcbnew.FromMM(float(value))


def existing_fixings(board):
    """Footprints already on the board whose pads are all non-plated.

    The same discriminator `verify.check_mounting_holes()` uses, so the two
    agree by construction rather than by both being right: a fixing is a
    footprint with no electrical pad, which is why the controller module's own
    four unplated holes do not count against it.
    """
    found = []
    for footprint in board.GetFootprints():
        pads = list(footprint.Pads())
        if pads and all(pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH
                        for pad in pads):
            found.append(footprint.GetReference())
    return found


def add_keepout(board, ref, x, y, reach):
    """A copper keep-out around one fixing, on every copper layer.

    **Square, and larger than the hole by design.** The pours are what has to
    be voided -- an M3 screw through In1 and In2 bridges MAGND to MDGND, which
    is a second ground star -- and the void a bare NPTH pad produces is the
    drill plus the zone's own clearance, about 3.4 mm. What is wanted is
    placement.MOUNTING_KEEPOUT_MM, the washer's own diameter, and the only way
    to state that to the filler is a rule area.

    It disallows copper pour and nothing else: tracks and vias are already
    clear of these regions, because krt.keepout_rects() keeps the router out of
    them and check_mounting_gap() holds the courtyards. A rule area that also
    forbade tracks would turn a clean board into a DRC failure rather than
    telling anybody anything new.
    """
    zone = pcbnew.ZONE(board)
    zone.SetIsRuleArea(True)
    zone.SetDoNotAllowZoneFills(True)
    zone.SetDoNotAllowTracks(False)
    zone.SetDoNotAllowVias(False)
    zone.SetDoNotAllowPads(False)
    zone.SetDoNotAllowFootprints(False)
    layers = pcbnew.LSET()
    for layer in (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu):
        layers.addLayer(layer)
    zone.SetLayerSet(layers)
    # **Built into the zone's own outline, not handed one.** SetOutline()
    # takes ownership of a SHAPE_POLY_SET through SWIG, so a polygon created
    # as a local here is freed when this function returns and the zone is left
    # holding a dangling pointer -- which does not fail, it segfaults the
    # filler several hundred lines later. Asking the zone for its outline and
    # appending to that has no ownership question in it at all.
    outline = zone.Outline()
    outline.NewOutline()
    for dx, dy in ((-reach, -reach), (reach, -reach),
                   (reach, reach), (-reach, reach)):
        outline.Append(_mm(x + dx), _mm(y + dy))
    zone.SetZoneName(f"keepout-{ref}")
    board.Add(zone)
    return zone


def main():
    commit = "--commit" in sys.argv[1:]
    if not BOARD.exists():
        raise SystemExit(f"{BOARD} does not exist -- run gen_pcb.py")

    board = pcbnew.LoadBoard(str(BOARD))
    tracks_before = len(board.GetTracks())
    already = existing_fixings(board)
    wanted = placement.mounting_holes()
    reach = placement.MOUNTING_KEEPOUT_MM / 2.0

    print(f"mounts: {BOARD.name}")
    print(f"  {len(already)} fixings on the board, "
          f"{len(wanted)} in placement.mounting_holes()")
    # **Idempotent, and the first version was not.** It said "already fitted,
    # nothing to do", which is fine until the pattern moves -- and it moved
    # the same afternoon, when MOUNTING_KEEPOUT_MM turned out to be KiCad's
    # courtyard rather than a washer's. A writer that cannot replace what it
    # wrote can only ever be run once correctly.
    # **Removal is a separate board load, and that is a pcbnew fact rather
    # than a preference.** After board.Remove(), SWIG's type registry stops
    # resolving: GetArea() starts handing back raw SwigPyObjects with no
    # GetZoneName(), and even module-level pcbnew.FootprintLoad() comes back
    # as an object with no FootprintLoad on it. Nothing announces it -- the
    # next attribute access just fails. So a replacement is remove, save,
    # reload, add: two clean sessions instead of one poisoned one.
    removed = 0
    if "--remove-only" in sys.argv[1:]:
        if not already:
            print("  nothing to remove")
            return
        stale = [board.GetArea(i) for i in range(board.GetAreaCount())
                 if board.GetArea(i).GetZoneName().startswith("keepout-H")]
        for zone in stale:
            board.Remove(zone)
            removed += 1
        for footprint in list(board.GetFootprints()):
            if footprint.GetReference() in wanted:
                board.Remove(footprint)
                removed += 1
        pcbnew.SaveBoard(str(BOARD), board)
        print(f"  removed {removed} existing fixings and keep-outs")
        return
    if already:
        print(f"  {len(already)} already fitted and this pass replaces them")
    pattern = placement.mounting_pattern()
    print(f"  pattern {pattern['chosen']}: "
          f"{pattern['gain_4_to_6']:.0f}x stiffer than four, and four is worth "
          f"nothing over two on this board")

    # Resolved the way gen_pcb.py resolves every other footprint -- through
    # toolchain.kicad.FOOTPRINT_DIR, not through the project's library table.
    # The table needs a settings manager and a wxApp, which is a GUI thing;
    # the directory is a path, which is not.
    from toolchain import kicad
    lib_path = kicad.FOOTPRINT_DIR / f"{FOOTPRINT_LIB}.pretty"
    if not lib_path.exists():
        raise SystemExit(f"{lib_path} does not exist -- KiCad's own "
                         f"{FOOTPRINT_LIB} library is not where "
                         f"toolchain.kicad says the libraries are")

    for ref, (x, y, moved) in sorted(wanted.items()):
        footprint = pcbnew.FootprintLoad(str(lib_path), FOOTPRINT_NAME)
        if footprint is None:
            raise SystemExit(
                f"{FOOTPRINT_LIB}:{FOOTPRINT_NAME} did not load from "
                f"{lib_path}")
        footprint.SetReference(ref)
        footprint.SetPosition(pcbnew.VECTOR2I(_mm(x), _mm(y)))
        footprint.Reference().SetVisible(False)
        board.Add(footprint)
        add_keepout(board, ref, x, y, reach)
        note = f"  slid {moved:.1f} mm along its edge" if moved else ""
        print(f"    {ref}  ({x:6.2f}, {y:6.2f}){note}")

    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())

    tracks_after = len(board.GetTracks())
    if tracks_after != tracks_before:
        raise SystemExit(
            f"track count moved {tracks_before} -> {tracks_after}: this file "
            f"adds and does not disturb, so that is a bug and not a result")
    print(f"  {tracks_before} tracks and vias, unchanged")

    if not commit:
        print("\n  nothing written -- pass --commit to put these on the board")
        return

    pcbnew.SaveBoard(str(BOARD), board)
    # **Measured back, and that is the check this file exists to pass.** A
    # writer that does not read its own artefact back cannot tell "wrote it"
    # from "wrote it somewhere" -- returns.py learned that when 135 vias went
    # inside a footprint and the board still parsed.
    again = pcbnew.LoadBoard(str(BOARD))
    fitted = existing_fixings(again)
    if sorted(fitted) != sorted(wanted):
        raise SystemExit(
            f"wrote {len(wanted)} fixings and measured {len(fitted)} back: "
            f"{sorted(fitted)}")
    print(f"  wrote {len(fitted)} fixings into {BOARD.name}")
    print(f"  measured back: {', '.join(sorted(fitted))}")
    print(f"  set verify.MOUNTING_HOLES to {len(fitted)}")


if __name__ == "__main__":
    main()
