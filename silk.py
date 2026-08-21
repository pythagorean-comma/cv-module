"""The silkscreen: what the board says it is, and what plugs into it.

**The board had none.** Four Edge.Cuts lines, no board-level text of any kind,
and 29 of 296 references visible -- of which J1-J6, J8, J17 and J19 were not.
Every connector on the west edge was anonymous, including the six audio
channels and the DC inlet, so the only way to know which pin of J1 goes back
to the mixer was to read design.py.

Nothing here would ever have said so. A silkscreen is not in a netlist, so
`check_geometry()` cannot miss it; DRC only sees it when it collides with
something; and `gen_fab.py` exports `F.SilkS` whether or not there is anything
on it -- `package_layers()` would have dropped it as empty, which is the one
place the absence *nearly* surfaced. `design.check_silk()` is the instrument
now: every connector in the netlist has a name and every one of its pins has
words for what it carries.

**The text is generated, not typed.** `design.silk_legend()` walks each
connector's pins out of the netlist and pairs them with `SILK_ROLE`, so the
legend's pin order is the netlist's pin order by construction. Change which
pin carries which net and the silkscreen follows on the next run.

**And the positions are results.** Each label is tried in a preference order --
the west margin first, because that is where the loom column lives, then north,
east, south -- and the first placement that clears every courtyard, every
fixing keep-out and every label already placed is the one taken. That is
`placement.pack_east()`'s discipline: a literal coordinate cannot say why it is
where it is, and a probe can.

    python3 silk.py             # place and report, write nothing
    python3 silk.py --commit    # put it on the board

This file owns **every board-level text on F.SilkS**, which is what makes it
idempotent: a commit clears them all and redraws. Footprint references belong
to their footprints and are not touched, apart from the connectors this file
un-hides.
"""

import math
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rules      # stdlib-only, and it owns the silkscreen minimums below

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"
PROJECT = "cv-module"
BOARD = OUT / f"{PROJECT}.kicad_pcb"

# Text sizes, in millimetres. The thickness is KiCad's own 0.15 default for
# silkscreen, which is what every fabricator's minimum line width is quoted
# against -- PCBWay publishes 0.15 mm, so this is at the floor and not under
# it.
TITLE_MM = 3.0
SUBTITLE_MM = 1.8
# Sizes to try for the legend, largest first. Solved rather than chosen --
# see board_texts().
LEGEND_SIZES = tuple(s for s in (1.0, 0.9, 0.8, 0.7)
                     if s >= rules.SILK_TEXT_MIN_MM)
LEGEND_MM = LEGEND_SIZES[0]
LABEL_MM = 1.2
# Designator height. 1.0 mm is KiCad's own silk default and every one of the
# 250 two-terminal parts takes it once the position is probed.
REF_SIZES = tuple(s for s in (1.0, 0.9, 0.8, 0.7)
                  if s >= rules.SILK_TEXT_MIN_MM)
REF_MM = REF_SIZES[0]
STROKE_MM = rules.SILK_TEXT_THICKNESS_MM
# Stroke-font advance per character, as a fraction of the glyph height. KiCad's
# font is 1:1 with a bit of side bearing; 0.78 measured against a rendered
# string is close enough to keep a label inside a 4 mm margin, and every
# placement is probed afterwards anyway.
ADVANCE = 0.78
# How much clear board a label wants around it. Half the silk line width plus
# the same courtyard tolerance every other clearance here uses.
LABEL_CLEARANCE_MM = 0.3


def _relaunch(argv):
    """Re-run this file under KiCad's bundled Python, then fix the project."""
    sys.path.insert(0, str(HERE))
    from toolchain import kicad
    import rules

    interpreter = kicad.BUNDLED_PYTHON
    if interpreter is None:
        raise SystemExit("pcbnew lives in KiCad's own Python and this install "
                         "does not bundle one.")
    # Two children on a commit, for mounts.py's reason: after board.Remove()
    # SWIG's type registry stops resolving for the rest of the process.
    passes = [["--remove-only"] + argv, argv] if "--commit" in argv else [argv]
    for arguments in passes:
        result = subprocess.run(
            [str(interpreter), str(HERE / "silk.py")] + arguments,
            env={**os.environ, "CV_SILK_CHILD": "1"})
        if result.returncode != 0:
            raise SystemExit(result.returncode)
    if "--commit" not in argv:
        return
    print("  re-running gen_project.py: SaveBoard() rewrote the project")
    again = subprocess.run([sys.executable, str(HERE / "gen_project.py")],
                           capture_output=True, text=True)
    if again.returncode != 0:
        raise SystemExit(again.stdout + again.stderr)
    if rules.apply_stackup(BOARD):
        print("  wrote rules.FAB_STACKUP back into the board")
    if rules.apply_thickness(BOARD):
        print("  wrote rules.FAB_FINISHED_MM back into the board")


if os.environ.get("CV_SILK_CHILD") != "1":
    _relaunch(sys.argv[1:])
    raise SystemExit(0)

# ---------------------------------------------------------------------------
# From here down, this is running under KiCad's interpreter.
# ---------------------------------------------------------------------------

import pcbnew                                                    # noqa: E402

sys.path.insert(0, str(HERE))
import design                                                    # noqa: E402
import placement                                                 # noqa: E402


def _mm(value):
    return pcbnew.FromMM(float(value))


def text_extent(text, height, rotated=False):
    """A string's bounding box in millimetres, (width, height).

    Estimated from ADVANCE rather than measured, because measuring needs the
    font engine and the font engine needs a wxApp. Every placement built on it
    is probed against the real courtyards afterwards, so an estimate that is a
    little generous costs a millimetre of position and never a collision.
    """
    width = len(text) * height * ADVANCE
    box = (width, height)
    return (box[1], box[0]) if rotated else box


class Placer:
    """Where a label can go, given everything already on the board.

    Holds the courtyards, the fixing keep-outs and every label placed so far,
    so the tenth label is checked against the first nine as well as against the
    parts. A placer that only checked the parts would let two legends overlap
    and report success.
    """

    def __init__(self):
        self.left, self.top, self.right, self.bottom = placement.outline()
        self.blocked = []
        self.claimed = set()
        for ref in sorted(design.PARTS):
            box = placement.courtyard(ref)
            if box:
                self.blocked.append(box)
        reach = placement.mounting_reach_mm()
        for ref, (x, y, _moved) in placement.mounting_holes().items():
            self.blocked.append((x - reach, y - reach, x + reach, y + reach))

    def claim_existing_silk(self, board):
        """Every piece of silkscreen already on the board, before anything is
        placed.

        **The first version of this file did not do this and DRC found 28
        overlaps.** It knew about courtyards and about the labels it had
        placed itself, which is two of the three things on F.SilkS: the third
        is the silk that footprints bring with them -- part outlines, polarity
        marks, pin-1 dots -- and the references that were already legible and
        are not re-placed. A placer that claims space as it goes is only
        correct if it starts from everything that is already there.

        The same mistake in miniature as the one this file exists to fix: a
        check of the parts, on a layer whose subject is not the parts.
        """
        for footprint in board.GetFootprints():
            for item in footprint.GraphicalItems():
                if item.GetLayer() != pcbnew.F_SilkS:
                    continue
                box = item.GetBoundingBox()
                self.blocked.append((
                    pcbnew.ToMM(box.GetLeft()), pcbnew.ToMM(box.GetTop()),
                    pcbnew.ToMM(box.GetRight()), pcbnew.ToMM(box.GetBottom())))
            text = footprint.Reference()
            if text.GetLayer() != pcbnew.F_SilkS or not text.IsVisible():
                continue
            ref = footprint.GetReference()
            box = placement.courtyard(ref)
            here = (pcbnew.ToMM(text.GetPosition().x),
                    pcbnew.ToMM(text.GetPosition().y))
            if box and box[0] < here[0] < box[2] and box[1] < here[1] < box[3]:
                continue                    # illegible: this pass will move it
            self.claimed.add(ref)
            tbox = text.GetBoundingBox()
            self.blocked.append((
                pcbnew.ToMM(tbox.GetLeft()), pcbnew.ToMM(tbox.GetTop()),
                pcbnew.ToMM(tbox.GetRight()), pcbnew.ToMM(tbox.GetBottom())))

    def fits_box(self, box):
        """Does this box, grown by the silk clearance, hit anything?"""
        pad = LABEL_CLEARANCE_MM
        a, b, c, d = box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad
        if a < self.left or c > self.right or b < self.top or d > self.bottom:
            return False
        return not any(a < g and e < c and b < i and f < d
                       for e, f, g, i in self.blocked)

    def fits(self, cx, cy, width, height):
        return self.fits_box((cx - width / 2, cy - height / 2,
                              cx + width / 2, cy + height / 2))

    def take_box(self, box):
        self.blocked.append(tuple(box))

    def take(self, cx, cy, width, height):
        self.take_box((cx - width / 2, cy - height / 2,
                       cx + width / 2, cy + height / 2))

    def place_item(self, item, candidates):
        """Put a live text where it fits, asking KiCad for its real extent.

        **The estimate was not good enough and DRC said so.** text_extent()
        multiplies a character count by ADVANCE, which is close and not exact,
        and the first version placed everything on it: 28 silkscreen overlaps,
        then 8 after the placer learned about the silk already on the board.
        The remainder were the estimate itself -- a stroke font's advance is
        per glyph, not an average, and `R827` is not `C704` wide.

        So a candidate is *tried*: the item is moved there, KiCad is asked for
        its bounding box, and the box is what the clearance test sees. That is
        the same move as measuring the board back after writing it, one item
        at a time, and it removes the estimate from the answer rather than
        tightening it.
        """
        for x, y, angle in candidates:
            item.SetTextAngle(pcbnew.EDA_ANGLE(angle, pcbnew.DEGREES_T))
            item.SetPosition(pcbnew.VECTOR2I(_mm(x), _mm(y)))
            raw = item.GetBoundingBox()
            box = (pcbnew.ToMM(raw.GetLeft()), pcbnew.ToMM(raw.GetTop()),
                   pcbnew.ToMM(raw.GetRight()), pcbnew.ToMM(raw.GetBottom()))
            if self.fits_box(box):
                self.take_box(box)
                return (x, y, angle)
        return None

    def candidates(self, ref, text, height, prefer_short=False):
        """Where a label beside `ref` could go, in preference order."""
        box = placement.courtyard(ref)
        if not box:
            return []
        a, b, c, d = box
        cx, cy = (a + c) / 2, (b + d) / 2
        sides = ((("N", (0, -1)), ("S", (0, 1)), ("E", (1, 0)), ("W", (-1, 0)))
                 if prefer_short else
                 (("W", (-1, 0)), ("N", (0, -1)), ("E", (1, 0)), ("S", (0, 1))))
        out = []
        for angle in ((0, 90) if prefer_short else (90, 0)):
            width, height_mm = text_extent(text, height, rotated=(angle == 90))
            for _side, (dx, dy) in sides:
                reach = ((c - a) / 2 if dx else (d - b) / 2)
                span = (width if dx else height_mm)
                for step in [i * 0.2 for i in range(1, 36)]:
                    out.append((cx + dx * (reach + span / 2 + step),
                                cy + dy * (reach + span / 2 + step), angle))
        return out

    def beside(self, ref, text, height, prefer_short=False):
        """A label beside one connector, in the first place it will go.

        West first: the loom column and the inlet both live on the west edge
        and the margin there is 5 mm of clear board that nothing else wants.
        Rotated, because a 90 degree label is bounded by the *row* pitch in
        the direction that is tight and by open margin in the direction that
        is not -- which is what lets "DC IN 12-18V" sit in 4 mm of width.
        """
        box = placement.courtyard(ref)
        if not box:
            return None
        a, b, c, d = box
        cx, cy = (a + c) / 2, (b + d) / 2
        sides = ((("N", (0, -1)), ("S", (0, 1)), ("E", (1, 0)), ("W", (-1, 0)))
                 if prefer_short else
                 (("W", (-1, 0)), ("N", (0, -1)), ("E", (1, 0)), ("S", (0, 1))))
        for angle in ((0, 90) if prefer_short else (90, 0)):
            width, height_mm = text_extent(text, height, rotated=(angle == 90))
            for side, (dx, dy) in sides:
                reach = ((c - a) / 2 if dx else (d - b) / 2)
                span = (width if dx else height_mm)
                for step in [i * 0.25 for i in range(1, 40)]:
                    px = cx + dx * (reach + span / 2 + step)
                    py = cy + dy * (reach + span / 2 + step)
                    if self.fits(px, py, width, height_mm):
                        self.take(px, py, width, height_mm)
                        return px, py, angle, side
        return None


def legend_lines():
    """The connector legend, generated from the netlist.

    One line per connector, in the order design.silk_connectors() returns
    them, with the pin roles read through design.silk_legend(). The six audio
    channels collapse to one line because they say the same thing six times --
    which is the same reason SILK_ROLE is keyed on the family.
    """
    lines = [f"{design.BOARD_NAME} - CONNECTORS"]
    audio = [ref for ref in design.silk_connectors()
             if design.SILK_NAME.get(ref, "").startswith("CH")]
    if audio:
        _name, rows = design.silk_legend(audio[0])
        first = design.SILK_NAME[audio[0]]
        last = design.SILK_NAME[audio[-1]]
        pins = "  ".join(f"{pin} {role}" for pin, _net, role in rows)
        lines.append(f"{first}-{last}  {pins}")
    for ref in design.silk_connectors():
        if ref in audio:
            continue
        name, rows = design.silk_legend(ref)
        pins = "  ".join(f"{pin} {role}" for pin, _net, role in rows)
        lines.append(f"{name}  {pins}")
    # The one fact about the inlet that is not a pin role: which conductor of
    # a Boss-standard barrel it is. design.py's own J8 comment records that
    # the mixer's instruction beside that connector was backwards for the life
    # of that design, which is the reason it is on the board this time.
    lines.append("DC IN is the shared jack: sleeve +, centre 0V")
    return lines


def make_text(board, string, size, angle=0):
    """One F.SilkS text, made but not yet positioned."""
    item = pcbnew.PCB_TEXT(board)
    item.SetText(string)
    item.SetLayer(pcbnew.F_SilkS)
    item.SetTextSize(pcbnew.VECTOR2I(_mm(size), _mm(size)))
    item.SetTextThickness(_mm(STROKE_MM))
    item.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    item.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
    item.SetTextAngle(pcbnew.EDA_ANGLE(angle, pcbnew.DEGREES_T))
    return item


def board_texts(board, placer):
    """The title block, the connector legend and a name beside each connector.

    Every item is created, added and then *placed by trial* -- see
    Placer.place_item(), which asks KiCad for the real bounding box rather
    than estimating one. The title band and the legend block are the only two
    seeds in this file, and both are refused rather than trusted if they do
    not fit.
    """
    out = []

    # -- the title band, 91 x 11.25 mm of clear board across the middle -----
    band_cx, band_cy = 52.7, 117.9
    for string, size, offset in (
            (design.BOARD_OWNER, TITLE_MM, -2.6),
            (f"{design.BOARD_NAME}   {design.BOARD_REV}", SUBTITLE_MM, 2.4)):
        item = make_text(board, string, size)
        board.Add(item)
        if placer.place_item(item, [(band_cx, band_cy + offset, 0)]) is None:
            raise SystemExit(
                f"the title band will not take {string!r} at {size} mm")
        out.append(item)

    # -- the connector legend, in the south-west block ---------------------
    #
    # **The size is solved for, not chosen.** The block is 35.5 mm wide and
    # the longest line is 38 characters; the first version fixed 1.0 mm from
    # an estimate and the trial refused it, because a stroke font's real
    # advance is per glyph. So this tries the sizes in order and takes the
    # largest that fits every line -- which is a measurement of the block
    # rather than a preference about type.
    lines = legend_lines()
    for size in LEGEND_SIZES:
        mark = len(placer.blocked)
        attempt, ok = [], True
        for index, line in enumerate(lines):
            width, _height = text_extent(line, size)
            item = make_text(board, line, size)
            spot = placer.place_item(
                item, [(8.0 + width / 2 + nudge, 210.0 + index * (size * 1.7 + 2 * LABEL_CLEARANCE_MM + 0.2), 0)
                       for nudge in (0.0, 1.0, 2.0, -1.0)])
            if spot is None:
                ok = False
                break
            attempt.append(item)
        if ok:
            for item in attempt:
                board.Add(item)
            out.extend(attempt)
            print(f"  legend at {size} mm, {len(lines)} lines")
            break
        del placer.blocked[mark:]
    else:
        raise SystemExit(
            f"the legend block will not take {len(lines)} lines at any of "
            f"{LEGEND_SIZES} mm -- shorten design.SILK_ROLE or move the block")

    # -- one name beside each connector ------------------------------------
    for ref in design.silk_connectors():
        name = design.SILK_NAME[ref]
        item = make_text(board, name, LABEL_MM)
        board.Add(item)
        spot = placer.place_item(
            item, placer.candidates(ref, name, LABEL_MM))
        if spot is None:
            raise SystemExit(f"nowhere to put {name} beside {ref}")
        out.append(item)
    return out


def main():
    commit = "--commit" in sys.argv[1:]
    if not BOARD.exists():
        raise SystemExit(f"{BOARD} does not exist -- run gen_pcb.py")

    problems = design.check_silk()
    if problems:
        raise SystemExit("design.check_silk(): " + "; ".join(problems))

    board = pcbnew.LoadBoard(str(BOARD))
    existing = [item for item in board.GetDrawings()
                if item.GetClass() == "PCB_TEXT"
                and item.GetLayer() == pcbnew.F_SilkS]

    print(f"silk: {BOARD.name}")
    if "--remove-only" in sys.argv[1:]:
        if not existing:
            print("  no board-level silk text to remove")
            return
        for item in existing:
            board.Remove(item)
        # **And the designators go back to F.Fab**, or this file is only
        # correct the first time it is run: the placement pass skips a
        # reference that is already legible on silk, so a bad placement
        # committed once would never be re-tried. Demoted by the same rule
        # gen_pcb.py demotes on -- the terminals the *design* connects, which
        # is a fact about the circuit rather than about a land pattern -- so
        # the baseline this file starts from is the one gen_pcb.py would have
        # written.
        demoted = 0
        for footprint in board.GetFootprints():
            ref = footprint.GetReference()
            if ref in design.SILK_NAME:
                continue
            connected = sum(1 for net, conns in design.NETS.items()
                            for part, _pin in conns if part == ref)
            if connected <= 2 and footprint.Reference().GetLayer() == \
                    pcbnew.F_SilkS:
                footprint.Reference().SetLayer(pcbnew.F_Fab)
                demoted += 1
        pcbnew.SaveBoard(str(BOARD), board)
        print(f"  removed {len(existing)} board-level silk texts, "
              f"demoted {demoted} designators to F.Fab")
        return
    if existing:
        print(f"  {len(existing)} board-level silk texts, replaced by this pass")

    tracks_before = len(board.GetTracks())
    placer = Placer()
    placer.claim_existing_silk(board)
    texts = board_texts(board, placer)
    # -- the designators -----------------------------------------------
    #
    # **250 of the 296 references were on F.Fab and the reason had expired.**
    # gen_pcb.py demotes any part the design connects two terminals to,
    # because "a 0805's designator is wider than the part: KiCad's DRC
    # reported thirteen silkscreen collisions on the first clean placement and
    # every one was a designator". Every word of that was true, and it was
    # true of a designator placed at the footprint's own *fixed offset* --
    # KiCad puts it a set distance above the body and takes no view on what is
    # there. Measured against a probe instead, **all 250 fit at 1.0 mm**.
    #
    # So this is the same shape as "hand-laid and verified" and
    # floorplan.CROSSING_RULE one more time: a rule written in terms of how it
    # was being satisfied, outliving the method. What silk is for is the board
    # somebody is holding with an iron, and on a hand-built prototype an
    # unlabelled 0805 is the thing that costs the hour.
    #
    # The connectors keep their names instead of their designators and that is
    # unchanged: "J1" identifies a BOM line and a CPL row, both of which are
    # files, while "CH1" is what somebody holding a loom needs, and there is
    # room in 4 mm of west margin for one of them.
    moved, promoted, shrunk, unlabelled = [], [], [], []
    for footprint in board.GetFootprints():
        ref = footprint.GetReference()
        if ref in design.SILK_NAME or ref in placement.mounting_holes():
            continue
        text = footprint.Reference()
        box = placement.courtyard(ref)
        if not box:
            continue
        on_silk = text.GetLayer() == pcbnew.F_SilkS
        if ref in placer.claimed:
            continue                        # already legible, space reserved
        text.SetLayer(pcbnew.F_SilkS)
        text.SetTextThickness(_mm(STROKE_MM))
        # **A cramped designator shrinks rather than failing the run.** The
        # sizes are tried largest first and the smallest is still above every
        # fabricator's floor; what is not acceptable is a part with no label,
        # because that is the state this whole pass exists to leave behind.
        spot = None
        for size in REF_SIZES:
            text.SetTextSize(pcbnew.VECTOR2I(_mm(size), _mm(size)))
            spot = placer.place_item(
                text, placer.candidates(ref, ref, size, prefer_short=True))
            if spot is not None:
                if size != REF_MM:
                    shrunk.append(f"{ref}@{size}")
                break
        if spot is None:
            # **Left on F.Fab and named, rather than failing the run.** A few
            # parts are in copper too tight to take a designator at any legal
            # size -- R656 sits in the ADC's input column, which is the
            # narrowest place on this board and already the subject of a
            # ground stitch that missed it by 0.03 mm. 250 parts labelled and
            # six named as unlabelled is a better board than none labelled,
            # and verify.SILK_UNLABELLED is the ratchet that stops the six
            # quietly becoming sixty.
            text.SetLayer(pcbnew.F_Fab)
            text.SetTextSize(pcbnew.VECTOR2I(_mm(REF_MM), _mm(REF_MM)))
            unlabelled.append(ref)
            continue
        (moved if on_silk else promoted).append(ref)

    on_fab = sum(1 for footprint in board.GetFootprints()
                 if footprint.GetReference() in design.SILK_NAME
                 and footprint.Reference().GetLayer() != pcbnew.F_SilkS)

    tracks_after = len(board.GetTracks())
    if tracks_after != tracks_before:
        raise SystemExit(
            f"track count moved {tracks_before} -> {tracks_after}: this file "
            f"draws on the legend layer and must not touch copper")

    print(f"  {len(texts)} texts: {design.BOARD_OWNER}, "
          f"{design.BOARD_NAME} {design.BOARD_REV}, "
          f"{len(legend_lines())} legend lines, "
          f"{len(design.silk_connectors())} connector names")
    print(f"  {len(promoted)} designators promoted from F.Fab to silk, "
          f"{len(moved)} already on silk and re-placed"
          + (f" ({', '.join(moved)})" if moved else "")
          + (f"; {len(shrunk)} shrunk to fit: {', '.join(shrunk[:8])}"
             if shrunk else ""))
    if unlabelled:
        print(f"  {len(unlabelled)} left on F.Fab -- no legible spot at any "
              f"size: {', '.join(unlabelled)}")
    print(f"  {on_fab} connector references left on F.Fab -- the name is "
          f"what a person plugs into, the designator is what the CPL says")
    print(f"  {tracks_before} tracks and vias, unchanged")
    if not commit:
        for item in texts[:6]:
            here = item.GetPosition()
            print(f"    ({pcbnew.ToMM(here.x):6.1f},"
                  f"{pcbnew.ToMM(here.y):6.1f})  {item.GetText()}")
        print("\n  nothing written -- pass --commit to put this on the board")
        return

    pcbnew.SaveBoard(str(BOARD), board)
    again = pcbnew.LoadBoard(str(BOARD))
    written = [item for item in again.GetDrawings()
               if item.GetClass() == "PCB_TEXT"
               and item.GetLayer() == pcbnew.F_SilkS]
    if len(written) != len(texts):
        raise SystemExit(f"wrote {len(texts)} texts and measured "
                         f"{len(written)} back")
    print(f"  wrote {len(written)} silk texts into {BOARD.name}")


if __name__ == "__main__":
    main()
