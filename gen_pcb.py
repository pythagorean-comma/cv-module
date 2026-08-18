"""Build the board for the design in design.py, through KiCad's own pcbnew.

    python3 gen_pcb.py

**Run it with the ordinary interpreter; it re-runs itself under KiCad's.**
`pcbnew` is a SWIG extension that only exists inside KiCad's bundled Python, so
this file starts as a launcher and finishes as a board generator. The mixer
solves the same problem with a `build.sh`; this repo's README is a chain of
`python3 x.py &&` and keeping that shape is worth eight lines of re-exec.

**The deprecation is a schedule, not a defect**, per CLAUDE.md: there is no
official API for boards, the IPC one is PCB-focused but not shipped for this,
and the SWIG bindings are what the sibling repo's fabricated boards came out
of. When removal lands it is a problem for both repos at once.

Two things it does that are not obvious and are both the mixer's hard-won
lessons, read at the pin:

**SaveBoard() writes the project file too**, through KiCad's settings manager,
and what it writes there is KiCad's *defaults* -- so every design rule
gen_project.py sets is gone the moment this saves. The mixer's build.sh re-runs
its project generator afterwards for exactly that reason and says several hours
were spent chasing violations that were only that. This file re-runs
gen_project.py itself, after saving, and check_rules() in verify.py is what
stops the discipline from decaying into a comment.

**Footprints are placed with their library nickname restored.**
`pcbnew.FootprintLoad()` returns the footprint under its bare name; without
`SetFPIDAsString()` KiCad cannot tie it back to a library and "Update
Footprints from Library" has nothing to work from.

What this pass does and does not do:

  * places all 225 parts at placement.py's coordinates, with every pad on its
    net from design.py;
  * reserves a courtyard for each part that has no footprint because it is not
    chosen -- the three bypass relays -- on the User.Drawings layer, so the
    area is committed even though the part is not;
  * draws the outline that placement.extents() derives, and the two ground
    zones either side of the split;
  * stitches every ground pad to the plane under it, and routes everything
    else through route.py -- **which now rips the board up and re-routes it in
    a different order until nothing is missed.** This list used to end "does
    not route. Not one track", then "routes all but 23 nets"; it is 0 now, and
    verify.UNROUTED_ITEMS holds the number rather than the prose.
"""

import math
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"
BOARD = OUT / "cv-module.kicad_pcb"

# Design rules, and **they are not here any more.** They were, with a comment
# claiming "gen_project.py imports them so the two cannot disagree" -- and
# gen_project.py could not import them, because importing this file relaunches
# it under KiCad's interpreter before any constant is reachable. So it wrote
# its own copies as literals and the two agreed by hand. rules.py is the one
# copy now, it derives the routing pitch rather than asserting it, and
# verify.check_rules() reads the project and the board back off disk to hold
# all three together. That check was named in this docstring before it
# existed; see rules.py.
sys.path.insert(0, str(HERE))
import rules                                                      # noqa: E402

TRACK_MM = rules.TRACK_MM
CLEARANCE_MM = rules.CLEARANCE_MM
VIA_DIAMETER_MM = rules.VIA_DIAMETER_MM
VIA_DRILL_MM = rules.VIA_DRILL_MM
EDGE_CLEARANCE_MM = rules.EDGE_CLEARANCE_MM
ROUTE_PITCH_MM = rules.route_pitch()

# **Empty, and the reserve() machinery below is kept.** This carried a 14 x 9 mm
# envelope for each bypass relay while design.BYPASS_RELAY was None. Both
# UNSPECIFIED parts are chosen now, so all 225 parts have a footprint and
# nothing is reserved -- but a repo that defers blocks will reserve area again,
# and what is worth keeping is the mechanism rather than this instance of it.
RESERVED_MM = {}


def _relaunch():
    """Re-run this file under KiCad's bundled Python, then fix the project."""
    sys.path.insert(0, str(HERE))
    from toolchain import kicad

    interpreter = kicad.BUNDLED_PYTHON
    if interpreter is None:
        raise SystemExit(
            "pcbnew lives in KiCad's own Python and this install does not "
            "bundle one.\nOn Linux, run: python3 -c 'import pcbnew' to check, "
            "then invoke this file with whichever interpreter has it.")
    result = subprocess.run([str(interpreter), str(HERE / "gen_pcb.py")],
                            env={**os.environ, "CV_PCB_CHILD": "1"})
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    # SaveBoard() has just overwritten the project with KiCad's defaults.
    print("  re-running gen_project.py: SaveBoard() rewrote the project")
    again = subprocess.run([sys.executable, str(HERE / "gen_project.py")],
                           capture_output=True, text=True)
    if again.returncode != 0:
        raise SystemExit(again.stdout + again.stderr)


if os.environ.get("CV_PCB_CHILD") != "1":
    _relaunch()
    raise SystemExit(0)

# ---------------------------------------------------------------------------
# From here down, this is running under KiCad's interpreter.
# ---------------------------------------------------------------------------

import pcbnew                                                    # noqa: E402

sys.path.insert(0, str(HERE))
import design as circuit                                         # noqa: E402
import placement                                                 # noqa: E402
import route                                                     # noqa: E402
from toolchain import kicad                                      # noqa: E402
from toolchain.kisch import _uuid as symbol_uuid                 # noqa: E402

FOOTPRINT_DIR = kicad.FOOTPRINT_DIR
PROJECT = "cv-module"
# The project's own footprint library, written by gen_project.py, holding the
# one land pattern KiCad does not ship. Resolved here rather than by copying
# the file into KiCad's installation, which is the same argument gen_project
# makes for `${KIPRJMOD}` in fp-lib-table: a build that writes into the
# toolchain is a build that cannot run on another machine.
PROJECT_LIBS = {"cv": HERE / "out" / "cv.pretty"}


def point(x, y):
    return pcbnew.VECTOR2I_MM(float(x), float(y))


class Board:
    """One board out of design.py, built by placing and pouring."""

    def __init__(self, layers=4):
        self.board = pcbnew.BOARD()
        self.board.SetCopperLayerCount(layers)
        self.nets = {}
        self.footprints = {}
        self.courtyards = []
        self._owner = circuit.DESIGN.pin_owner()
        for name in sorted(set(self._owner.values())):
            net = pcbnew.NETINFO_ITEM(self.board, name)
            self.board.Add(net)
            self.nets[name] = net

    def net(self, name):
        return self.nets[name]

    def place(self, ref, x, y, rotation):
        part = circuit.PARTS[ref]
        library, name = part.footprint.split(":", 1)
        directory = PROJECT_LIBS.get(library,
                                     FOOTPRINT_DIR / f"{library}.pretty")
        footprint = pcbnew.FootprintLoad(str(directory), name)
        if footprint is None:
            raise SystemExit(
                f"could not load footprint {part.footprint} for {ref} from "
                f"{directory} -- check the name against KiCad's own library, "
                f"or against gen_project.footprint_library() if the nickname "
                f"is a project one")
        self.board.Add(footprint)
        footprint.SetFPIDAsString(part.footprint)
        # The same UUID gen_sch.py derived for this symbol, so the two files
        # describe one part rather than two. Without it, "Update PCB from
        # Schematic" treats every footprint as new.
        footprint.SetPath(pcbnew.KIID_PATH(
            f"/{symbol_uuid(f'{PROJECT}:part:{ref}:1')}"))
        footprint.SetReference(ref)
        footprint.SetValue(str(part.value))
        footprint.SetPosition(point(x, y))
        # **Designators for two-pad passives go on F.Fab, not on silk.** This
        # board has 128 of them on a 4 mm pitch, and their reference text is
        # wider than the part: KiCad's DRC reported thirteen silkscreen
        # collisions on the first clean placement and every one was a
        # designator, not a part. F.Fab is where an assembly drawing reads them
        # from anyway; what silk is for is the parts a human orients by hand,
        # which is the ICs and the connectors.
        if len(list(footprint.Pads())) <= 2:
            footprint.Reference().SetLayer(pcbnew.F_Fab)
        if rotation:
            footprint.SetOrientationDegrees(float(rotation))
        move = placement.REFERENCE_MOVES.get(ref)
        if move:
            text = footprint.Reference()
            here = text.GetPosition()
            text.SetPosition(pcbnew.VECTOR2I(
                here.x + pcbnew.FromMM(move[0]),
                here.y + pcbnew.FromMM(move[1])))
        for pad in footprint.Pads():
            key = (ref, pad.GetNumber())
            if key in self._owner:
                pad.SetNet(self.net(self._owner[key]))
        self.footprints[ref] = footprint
        box = footprint.GetCourtyard(pcbnew.F_CrtYd).BBox()
        self.courtyards.append((
            ref,
            pcbnew.ToMM(box.GetLeft()), pcbnew.ToMM(box.GetTop()),
            pcbnew.ToMM(box.GetRight()), pcbnew.ToMM(box.GetBottom())))
        return footprint

    def reserve(self, ref, x, y, width, height):
        """Commit board area to a part that is not chosen yet.

        A rectangle on User.Drawings and an entry in the courtyard list, so the
        outline and the overlap check both see it. **This is design.UNSPECIFIED
        made physical**: the schematic can carry a part whose pins are known and
        whose part number is not, and so can the board -- what it cannot carry
        is a hole where nobody remembered anything goes.
        """
        left, top = x - width / 2, y - height / 2
        right, bottom = x + width / 2, y + height / 2
        corners = [(left, top), (right, top), (right, bottom), (left, bottom),
                   (left, top)]
        for start, end in zip(corners, corners[1:]):
            shape = pcbnew.PCB_SHAPE(self.board)
            shape.SetShape(pcbnew.SHAPE_T_SEGMENT)
            shape.SetStart(point(*start))
            shape.SetEnd(point(*end))
            shape.SetLayer(pcbnew.Dwgs_User)
            shape.SetWidth(pcbnew.FromMM(0.15))
            self.board.Add(shape)
        text = pcbnew.PCB_TEXT(self.board)
        text.SetText(f"{ref} reserved: see design.UNSPECIFIED")
        text.SetPosition(point(x, y))
        text.SetLayer(pcbnew.Cmts_User)
        text.SetTextSize(pcbnew.VECTOR2I_MM(1.0, 1.0))
        self.board.Add(text)
        self.courtyards.append((ref, left, top, right, bottom))

    def outline(self, rectangle):
        left, top, right, bottom = rectangle
        corners = [(left, top), (right, top), (right, bottom), (left, bottom),
                   (left, top)]
        for start, end in zip(corners, corners[1:]):
            shape = pcbnew.PCB_SHAPE(self.board)
            shape.SetShape(pcbnew.SHAPE_T_SEGMENT)
            shape.SetStart(point(*start))
            shape.SetEnd(point(*end))
            shape.SetLayer(pcbnew.Edge_Cuts)
            shape.SetWidth(pcbnew.FromMM(0.1))
            self.board.Add(shape)

    def zone(self, net, layer, rectangle, priority=0):
        """One poured rectangle.

        `priority` exists for the L the southern MDGND is poured as. **Two
        zones of one net that overlap at the same priority are a DRC error**
        -- `zones_intersect`, "intersecting zones must have distinct
        priorities" -- and KiCad is right to insist: with equal priority the
        filler has no rule for which one owns the shared copper. Same net or
        not, the overlap has to be ordered.
        """
        left, top, right, bottom = rectangle
        item = pcbnew.ZONE(self.board)
        item.SetLayer(layer)
        item.SetNet(self.net(net))
        item.SetAssignedPriority(priority)
        item.SetLocalClearance(pcbnew.FromMM(CLEARANCE_MM))
        item.SetMinThickness(pcbnew.FromMM(0.2))
        outline = item.Outline()
        outline.NewOutline()
        for x, y in ((left, top), (right, top), (right, bottom), (left, bottom)):
            outline.Append(pcbnew.FromMM(float(x)), pcbnew.FromMM(float(y)))
        self.board.Add(item)
        return item

    def pad_boxes(self):
        """{net: [(x, y, half_width, half_height, layers)]} for the router.

        **From GetBoundingBox(), not from GetSize(), and the difference is a
        rotation.** GetSize() reports the pad in the footprint's own frame, so
        a SOIC-14 turned 90 degrees hands back 1.95 x 0.6 for a pad that is
        0.6 x 1.95 on the board. The router blocked the wrong rectangle, and
        the tracks it drew ran exactly along the rows of pad edges it thought
        were 0.675 mm further away: 199 shorts and 500 clearance violations
        from one axis swap. A bounding box is in board coordinates by
        construction and cannot be got round the wrong way.

        Copper with no net -- a spare section's pin, a mounting pad -- goes in
        under the empty name, which route_all() treats as hard. It routes to
        nothing and blocks everything.
        """
        boxes = {}
        for ref, footprint in self.footprints.items():
            for pad in footprint.Pads():
                key = (ref, pad.GetNumber())
                box = pad.GetBoundingBox()
                left, top = pcbnew.ToMM(box.GetLeft()), pcbnew.ToMM(box.GetTop())
                right = pcbnew.ToMM(box.GetRight())
                bottom = pcbnew.ToMM(box.GetBottom())
                # A through-hole pad is copper on every layer; an SMD pad is
                # copper on whichever layers it is *on*. The router needs to
                # know which, because it is what decides whether reaching that
                # pad costs a via -- and, for the QFN, whether the back side is
                # free.
                #
                # **This asked the drill and assumed the rest, and a QFN's
                # thermal pad is the case where that is wrong.** KiCad's
                # _ThermalVias variants put the exposed pad on F.Cu *and* on
                # B.Cu, so pad 57 of U19 is 3.2 mm square of ground on the back
                # of the board -- and declared as front-only it was invisible
                # to the router, which laid IRQ straight across it. DRC found
                # it 64 times. The pad knows what layers it is on; asking it is
                # both shorter and true of parts nobody has fitted yet.
                if pad.GetDrillSize().x > 0:
                    layers = route.LAYERS
                else:
                    layers = tuple(
                        side for side, copper in ((route.FRONT, pcbnew.F_Cu),
                                                  (route.BACK, pcbnew.B_Cu))
                        if pad.IsOnLayer(copper))
                boxes.setdefault(self._owner.get(key, ""), []).append(
                    ((left + right) / 2, (top + bottom) / 2,
                     (right - left) / 2, (bottom - top) / 2, layers))
        return boxes

    def track(self, net, layer, points, width=None):
        for start, end in zip(points, points[1:]):
            item = pcbnew.PCB_TRACK(self.board)
            item.SetStart(point(*start))
            item.SetEnd(point(*end))
            item.SetWidth(pcbnew.FromMM(width or TRACK_MM))
            item.SetLayer(layer)
            item.SetNet(self.net(net))
            self.board.Add(item)

    def via(self, net, x, y):
        item = pcbnew.PCB_VIA(self.board)
        item.SetPosition(point(x, y))
        item.SetWidth(pcbnew.FromMM(VIA_DIAMETER_MM))
        item.SetDrill(pcbnew.FromMM(VIA_DRILL_MM))
        item.SetNet(self.net(net))
        item.SetViaType(pcbnew.VIATYPE_THROUGH)
        self.board.Add(item)

    def stitch_grounds(self):
        """A via beside every ground pad, down to the plane it belongs to.

        **The two grounds are not routed and must not be.** They are poured on
        both inner layers, so what a ground pad needs is not a track to another
        pad but a hole to the plane underneath it -- 104 pads, 104 vias, and no
        copper on the signal layers at all. Routing them instead would be a
        hundred tracks doing worse what a plane does perfectly, and every one
        of them would be a slot in the reference for the tracks that cross it.

        Three rules, and each of them is a DRC violation that happened:

        **Outward along the pad's long axis.** A pad sticks out of its body
        along its own length -- true of an 0805 and of a SOIC pin alike -- so
        that is the direction with nothing in it. Offsetting along the *body*
        axis instead sent the SSI2164's ground stub 1.1 mm sideways into its
        own V+ pin, twice.

        **The spot has to be clear of every other pad**, which is checked
        rather than assumed: the first candidate that clears everything by the
        hole clearance wins, and there are eight of them before this gives up.
        A via 0.8 mm off C711's ground pad is 0.15 mm off C712's rail pad, and
        the row is 3.5 mm apart.

        **The via has to land in its own pour.** A part that straddles the
        ground split -- the '541 and the three bypass relays do, by design --
        has analogue pins sitting over the digital plane, and a via there
        connects to nothing at all. So the spot is pulled back across the line
        into the zone that belongs to it, and the stub gets longer. That is
        what a straddling part costs, and it is cheaper than the alternative,
        which is a ground pin connected to the wrong ground.
        """
        placed, obstacles = 0, []
        # **A pad with a barrel *inside its own copper* is already stitched,
        # and this is the QFN's exposed pad.** The rule below skips a drilled
        # pad because its barrel crosses every layer; a QFN's thermal pad is an
        # SMD pad with drilled pads sitting inside it -- KiCad's _ThermalVias
        # variants are built exactly that way -- so the same argument applies
        # to it. Without this the build stops on U19.57, correctly: there is
        # nowhere beyond a 3.2 mm pad in the middle of a 56-pin package that is
        # not inside a pin row.
        #
        # **The test is overlap and not the pad number, and the difference is a
        # USB connector.** The first version of this asked whether any drilled
        # pad shared the number -- true of a thermal pad, and also true of the
        # micro-B's shield, which has four through-hole pegs and five SMD tabs
        # all numbered "SH" in different places. Two of those tabs then got no
        # stitch and no copper, and DRC reported J14's shield as unconnected to
        # itself. Same number is not same copper; overlapping boxes are.
        barrels = {}
        for ref, footprint in self.footprints.items():
            for pad in footprint.Pads():
                if pad.GetDrillSize().x > 0:
                    barrels.setdefault(ref, []).append(pad.GetBoundingBox())

        def has_barrel(ref, pad):
            box = pad.GetBoundingBox()
            return any(box.Intersects(other) for other in barrels.get(ref, ()))
        boxes = [(x, y, half_w, half_h)
                 for entries in self.pad_boxes().values()
                 for x, y, half_w, half_h, _ in entries]
        keep = VIA_DIAMETER_MM / 2 + 0.25
        for ref, footprint in self.footprints.items():
            for pad in footprint.Pads():
                key = (ref, pad.GetNumber())
                net = self._owner.get(key)
                if net not in ("MAGND", "MDGND"):
                    continue
                # **A through-hole pad is already stitched.** Its barrel
                # crosses every layer, so the plane connects to it natively and
                # a via beside it is a second hole 0.8 mm from the first --
                # which is a hole-to-hole violation, not a connection.
                if pad.GetDrillSize().x > 0 or has_barrel(ref, pad):
                    continue
                position = pad.GetPosition()
                box = pad.GetBoundingBox()
                x, y = pcbnew.ToMM(position.x), pcbnew.ToMM(position.y)
                width = pcbnew.ToMM(box.GetWidth())
                height = pcbnew.ToMM(box.GetHeight())
                body = footprint.GetPosition()
                dx, dy = x - pcbnew.ToMM(body.x), y - pcbnew.ToMM(body.y)

                if height >= width:
                    axis, half, delta = "y", height / 2, dy
                else:
                    axis, half, delta = "x", width / 2, dx
                sign = 1.0 if delta >= 0 else -1.0

                spot = None
                for reach in (0.9, 1.3, 1.7):
                    for direction in (sign, -sign):
                        step = direction * (half + reach)
                        candidate = ((x + step, y) if axis == "x"
                                     else (x, y + step))
                        candidate = self._in_pour(net, candidate)
                        if self._clear_of_pads(candidate, boxes, keep):
                            spot = candidate
                            break
                    if spot:
                        break
                if spot is None:
                    raise SystemExit(
                        f"nowhere to stitch {ref}.{pad.GetNumber()} ({net}) "
                        f"-- every candidate is inside another pad's "
                        f"clearance. Move the part in placement.py")
                self.via(net, *spot)
                self.track(net, pcbnew.F_Cu, [(x, y), spot])
                placed += 1
                # Both the via and the stub are copper the router has to see.
                # The via is through-plated so it blocks both signal layers;
                # the stub is on F.Cu alone, and saying so is worth 104 pieces
                # of back-side routing space.
                obstacles.append((route.LAYERS, spot[0], spot[1],
                                  VIA_DIAMETER_MM / 2, VIA_DIAMETER_MM / 2))
                obstacles.append((
                    (route.FRONT,), (x + spot[0]) / 2, (y + spot[1]) / 2,
                    abs(spot[0] - x) / 2 + TRACK_MM / 2,
                    abs(spot[1] - y) / 2 + TRACK_MM / 2))
        return placed, obstacles

    @staticmethod
    def _clear_of_pads(spot, boxes, keep):
        x, y = spot
        for px, py, half_w, half_h in boxes:
            if (abs(x - px) < half_w + keep and abs(y - py) < half_h + keep):
                return False
        return True

    @staticmethod
    def _in_pour(net, spot):
        """Pull a stitch spot back across the ground split into its own zone."""
        x, y = spot
        edge = placement.GROUND_GAP / 2 + 0.6
        if net == "MAGND" and y > placement.SPLIT_Y - edge:
            return (x, placement.SPLIT_Y - edge)
        if net == "MDGND" and y < placement.SPLIT_Y + edge:
            return (x, placement.SPLIT_Y + edge)
        # And the second MDGND rectangle, which is the supply band east of the
        # isolation line. A stitch anywhere in the primary's quadrant would
        # land on no plane at all -- the same fault J8's own note records, one
        # boundary later.
        if (net == "MDGND" and y > placement.ISOLATION_Y - edge
                and x < placement.ISOLATION_X + placement.ISOLATION_STITCH_MM):
            return (placement.ISOLATION_X + placement.ISOLATION_STITCH_MM, y)
        return spot

    def fill(self):
        filler = pcbnew.ZONE_FILLER(self.board)
        filler.Fill(self.board.Zones())

    def rules(self):
        settings = self.board.GetDesignSettings()
        settings.SetCopperLayerCount(4)
        settings.m_TrackMinWidth = pcbnew.FromMM(TRACK_MM)
        settings.m_ViasMinSize = pcbnew.FromMM(VIA_DIAMETER_MM)
        settings.m_MinClearance = pcbnew.FromMM(CLEARANCE_MM)
        settings.m_CopperEdgeClearance = pcbnew.FromMM(EDGE_CLEARANCE_MM)

    def save(self, path):
        self.board.BuildListOfNets()
        pcbnew.SaveBoard(str(path), self.board)


def check_courtyards(board):
    """placement.SIZE agrees with the footprints KiCad actually loaded.

    **This file is the only place the two exist at once**, which is exactly why
    they were allowed to disagree. placement.py cannot import pcbnew -- that is
    the rule that keeps its arithmetic checkable -- so it carries a table of
    courtyard sizes, and that table had every multi-pin package transposed:
    SOIC-14 at (9.2, 6.6) against KiCad's 7.40 x 9.16, the 1x05 header at
    (13.4, 6.2) against 3.54 x 13.70.

    Nothing caught it because every consumer was transposed in the same way.
    check_overlaps() compares those boxes to each other, so two parts modelled
    sideways collide with each other just as they would upright; the board's
    own outline came from KiCad's boxes here and placement.main() printed a
    different one from the table, and the two numbers were 8 mm apart in
    print, on two lines of the same build log, for as long as the board has
    existed.

    KiCad's BBox() includes the courtyard line, and placement.SIZE is the
    outline centreline, so the model is expected to sit *inside* the bounding
    box by placement.COURTYARD_TOLERANCE_MM on each edge -- and by no more,
    which is the half that makes this a check rather than a bound.
    """
    problems = []
    allowed = placement.COURTYARD_TOLERANCE_MM
    for ref, left, top, right, bottom in board.courtyards:
        if ref in RESERVED_MM:
            continue
        modelled = placement.courtyard(ref)
        if modelled is None:
            problems.append(f"{ref} has a footprint and no entry in "
                            f"placement.SIZE")
            continue
        for name, mine, theirs, sign in (("left", modelled[0], left, 1),
                                         ("top", modelled[1], top, 1),
                                         ("right", modelled[2], right, -1),
                                         ("bottom", modelled[3], bottom, -1)):
            inset = sign * (mine - theirs)
            if not 0.0 <= inset <= allowed:
                problems.append(
                    f"{ref}: placement.py puts the {name} courtyard edge at "
                    f"{mine:.3f} and KiCad's footprint at {theirs:.3f}, "
                    f"{inset:+.3f} mm inside it against an allowance of "
                    f"0 to {allowed} -- check the SIZE entry, and check it is "
                    f"not on the wrong axis")
    return problems


def escape_plan(board):
    """Where every pad's fan-out escape would go, if the router needs one.

    **A plan for every pad, and the router decides which plans get used.** The
    condition is rules.track_offset_limit() and it is arithmetic, but the place
    it is evaluated is route.access(), which already returns None for exactly
    the pads that have no legal entry -- see the pre-pass in
    route._one_pass(). Computing the same condition a second time here was the
    first attempt and it disagreed with the router on U16's DPAK tab: the
    limit is about the distance from the *track* to the neighbouring copper,
    and evaluating it at the pad's centre line asks about one candidate cell
    when a 6 mm tab offers a hundred and a TSSOP pin offers one.

    So this file answers only the question it is the only file able to answer:
    **which way is out.** A pad sticks out of its body along its own length,
    so the escape runs along the pad's long axis, away from the footprint
    centre -- which is stitch_grounds()' rule, for the same reason, one class
    of copper along. rules.escape_reach() says how far before it may turn.

    A square pad gets no plan. There is no long axis to run along, and a pad
    whose two axes are equal is either large enough to hold a cell or too
    small for any escape to help.

    Returns {(net, pad_x, pad_y): (out_x, out_y)}.
    """
    plan = {}
    for ref, footprint in sorted(board.footprints.items()):
        body = footprint.GetPosition()
        bx, by = pcbnew.ToMM(body.x), pcbnew.ToMM(body.y)
        for pad in footprint.Pads():
            net = pad.GetNetname()
            if not net:
                continue
            # **The bounding box, and its centre, and both for the same
            # reason pad_boxes() uses it.** GetSize() is in the footprint's
            # frame and comes back transposed on a rotated part; GetPosition()
            # is the pad's anchor, which is the box centre to within KiCad's
            # nanometre and *not* to within a float comparison. Keying this on
            # the anchor while route.py keys on the box centre cost two nets:
            # ENVA1 and MISO matched, ENVA2 and MOSI missed by a nanometre, and
            # the router reported "no escape axis" for a pad 1.475 by 0.400 mm.
            # One notion of where a pad is, and it is the one the router has.
            box = pad.GetBoundingBox()
            x0, y0 = pcbnew.ToMM(box.GetLeft()), pcbnew.ToMM(box.GetTop())
            x1, y1 = pcbnew.ToMM(box.GetRight()), pcbnew.ToMM(box.GetBottom())
            width, height = x1 - x0, y1 - y0
            if width == height:
                continue
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            along_x = width > height
            reach = rules.escape_reach((width if along_x else height) / 2)
            if along_x:
                sign = 1.0 if cx >= bx else -1.0
                plan[(net, cx, cy)] = (cx + sign * reach, cy)
            else:
                sign = 1.0 if cy >= by else -1.0
                plan[(net, cx, cy)] = (cx, cy + sign * reach)
    return plan


def build():
    # Before anything is placed: the rules this board is about to be built to
    # are inside what the fabricator publishes. Cheap, and it fails at the top
    # rather than at DRC.
    rules.check_fab_class()
    board = Board()
    board.rules()

    for ref in sorted(circuit.PARTS, key=lambda r: (r[0], len(r), r)):
        spot = placement.position(ref)
        if spot is None:
            raise SystemExit(f"{ref} has no position -- see placement.py")
        x, y, rotation = spot
        if ref in RESERVED_MM:
            board.reserve(ref, x, y, *RESERVED_MM[ref])
        else:
            board.place(ref, x, y, rotation)

    mismatched = check_courtyards(board)
    if mismatched:
        raise SystemExit("placement.SIZE disagrees with KiCad's footprints:\n  "
                         + "\n  ".join(mismatched[:8]))

    # **The refs go with the boxes, because placement.EDGE_PARTS needs them.**
    # A connector that mates with a cable contributes to the outline without
    # the margin every other part gets, and without the reference this call
    # cannot tell which is which -- which is exactly the bug it had: a board
    # 5 mm wider than placement.py's own report, with the USB receptacle
    # 5 mm inside an edge it is supposed to be flush with.
    rectangle = placement.extents(board.courtyards)
    board.outline(rectangle)

    # The two grounds, on both inner layers, with placement.GROUND_GAP between
    # them. Two zones on one layer with different nets fill straight through
    # each other and DRC does not object -- each is correctly connected to its
    # own net -- so the separation is geometric and verify.py is what holds it.
    left, top, right, bottom = rectangle
    inset = 0.5
    split = placement.SPLIT_Y
    half = placement.GROUND_GAP / 2
    # **MDGND is two rectangles and not one, and the second one is the
    # isolation barrier expressed as an absence.** The supply's primary side
    # is referenced to IGND -- the inlet's own 0 V, which through the shared
    # barrel jack is the mixer's PGND -- and a ground plane running under it
    # would be a plate capacitor across the barrier at exactly the frequency
    # design.barrier_return() is trying to keep out of the audio bond. So the
    # southern pour stops at placement.ISOLATION_Y across the primary's half
    # of the board and resumes east of placement.ISOLATION_X.
    #
    # There is no third zone for IGND. A pour would be the obvious thing and
    # it is wrong here for the same reason: it is 300 mm2 of copper facing the
    # MDGND plane on the layer above, which is the coupling the gap exists to
    # remove. Seven pins of primary is a routed net.
    iso_x = placement.ISOLATION_X
    iso_y = placement.ISOLATION_Y
    for layer in (pcbnew.In1_Cu, pcbnew.In2_Cu):
        board.zone("MAGND", layer,
                   (left + inset, top + inset, right - inset, split - half))
        board.zone("MDGND", layer,
                   (left + inset, split + half, right - inset, iso_y - half))
        # **The second rectangle starts at the split and not at the isolation
        # line, and the difference is one unconnected item.** Drawn as two
        # abutting-but-not-touching rectangles -- north part down to iso_y,
        # south part from iso_y -- MDGND becomes two *islands* with a 2 mm gap
        # between them, and KiCad is right to call that a missing connection:
        # a plane in two pieces is two planes. Overlapping them into an L
        # instead costs nothing, because the overlap is copper on the same net,
        # and it leaves exactly the corner that has to be empty empty.
        #
        # It cost a build to find, and what found it was DRC's unconnected
        # count rather than anything here -- which is the argument for
        # verify.UNROUTED_ITEMS being zero rather than small.
        board.zone("MDGND", layer,
                   (iso_x + half, split + half, right - inset, bottom - inset),
                   priority=1)

    stitched, stitch_copper = board.stitch_grounds()

    # Everything else, through the router. The two grounds are skipped because
    # stitch_grounds() has already given them the only connection they want.
    # **The primary's corner is reserved, and it is a keep-out with an
    # exception list.** It has no ground pour under it by construction, which
    # to a maze router reads as the widest free channel on the board -- and on
    # the build that added the ADC the router duly ran VA+ through it, twenty
    # tracks of secondary rail across the isolation barrier.
    # verify.check_isolation_gap() caught every one, which is the check doing
    # exactly its job and is still the wrong place to catch it: a rule the
    # router cannot break is worth more than a rule it is caught breaking. So
    # the region goes in as a reservation, and the five primary nets are the
    # only ones admitted.
    tracks, vias, missed, refused, escaped = route.route_all(
        rectangle, board.pad_boxes(), obstacles=stitch_copper,
        rules={"pitch": ROUTE_PITCH_MM, "track": TRACK_MM,
               "clearance": CLEARANCE_MM, "via": VIA_DIAMETER_MM,
               "edge": EDGE_CLEARANCE_MM,
               # Derived, not assumed. rules.via_exclusion() is three
               # distances -- to a track, to another via, to a pad's copper --
               # each the stricter of a copper rule that shrinks with the
               # fabrication class and a hole rule that does not. route.py used
               # to carry the first of them as a ring of four cells, correct at
               # a 0.5 mm grid and written as though it were geometry.
               "via_reach": rules.via_exclusion()},
        skip=("MAGND", "MDGND"),
        reserve=((left, iso_y, iso_x, bottom),
                 ("VIN", "VIN_J", "IGND", "IGND_J", "VIN_P")),
        escapes=escape_plan(board))
    shorts = route.check_no_shorts(tracks, vias, ROUTE_PITCH_MM)
    if shorts:
        raise SystemExit("the router shorted nets, which it cannot do if its "
                         "own bookkeeping is right:\n  "
                         + "\n  ".join(shorts[:8]))
    layers = {route.FRONT: pcbnew.F_Cu, route.BACK: pcbnew.B_Cu}
    for net, layer, points in tracks:
        board.track(net, layers[layer], points)
    for net, spot in vias:
        board.via(net, *spot)

    board.fill()
    OUT.mkdir(exist_ok=True)
    board.save(BOARD)
    return (board, rectangle, stitched, len(tracks), len(vias), missed,
            escaped, refused)


def main():
    (board, rectangle, stitched, tracks, vias, missed, escaped,
     refused) = build()
    left, top, right, bottom = rectangle
    width, height = right - left, bottom - top
    print(f"{BOARD.name}: {len(board.footprints)} footprints, "
          f"{len(RESERVED_MM)} reserved, {len(board.nets)} nets")
    print(f"  outline {width:.1f} x {height:.1f} mm = {width * height:.0f} mm2, "
          f"four layers, ground split at y = {placement.SPLIT_Y:.1f}")
    print(f"  {stitched} ground pads stitched to the planes, "
          f"{tracks} track runs and {vias} vias routed")
    print(f"  {len(escaped)} fine-pitch escapes laid before the router ran, "
          f"{len(refused)} refused -- see rules.track_offset_limit()")
    for net, pad_x, pad_y, land_x, land_y in escaped:
        print(f"      {net} leaves its pad at ({pad_x:.3f}, {pad_y:.3f}) "
              f"and picks the grid up at ({land_x:.2f}, {land_y:.2f})")
    for net, why in sorted(refused.items()):
        print(f"      REFUSED {net}: {why}")
    if missed:
        print(f"  {len(missed)} nets the router could not finish, and they are "
              f"named rather than counted:")
        for index in range(0, len(missed), 6):
            print(f"      {', '.join(missed[index:index + 6])}")


if __name__ == "__main__":
    main()
