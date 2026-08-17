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
  * **does not route.** Not one track. The unconnected count is reported and
    verify.check_board() holds it against design.py's own net count, so
    "unrouted" is a number this repo states rather than a thing somebody
    notices later.
"""

import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"
BOARD = OUT / "cv-module.kicad_pcb"

# Design rules. Ordinary two-ounce-capable JLCPCB-class numbers rather than
# anything clever: this board's constraint is area and part count, not track
# width. They are here rather than in gen_project.py because the board is what
# they govern, and gen_project.py imports them so the two cannot disagree.
TRACK_MM = 0.25
POWER_TRACK_MM = 0.5
CLEARANCE_MM = 0.2
VIA_DIAMETER_MM = 0.6
VIA_DRILL_MM = 0.3
EDGE_CLEARANCE_MM = 0.3

# The routing grid, and it is derived rather than chosen: two tracks on
# adjacent cells are PITCH - TRACK apart edge to edge, which has to clear
# CLEARANCE. 0.5 - 0.25 = 0.25 against 0.2, which is the tightest pitch these
# rules allow and therefore the one that routes.
ROUTE_PITCH_MM = 0.5

# A signal DPDT relay's envelope, and the only reason it is a number here is
# that design.BYPASS_RELAY is None. 14 x 9 mm is what floorplan.py used for the
# coarse pad's relays before they were struck; it is an envelope for the class
# and it is reserved rather than placed.
RESERVED_MM = {"K801": (14.0, 9.0), "K802": (14.0, 9.0), "K803": (14.0, 9.0)}


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
        footprint = pcbnew.FootprintLoad(
            str(FOOTPRINT_DIR / f"{library}.pretty"), name)
        if footprint is None:
            raise SystemExit(
                f"could not load footprint {part.footprint} for {ref} -- "
                f"check the name against KiCad's own library")
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

    def zone(self, net, layer, rectangle):
        left, top, right, bottom = rectangle
        item = pcbnew.ZONE(self.board)
        item.SetLayer(layer)
        item.SetNet(self.net(net))
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
                # copper on one. The router needs to know which, because it is
                # what decides whether reaching that pad costs a via.
                layers = (route.LAYERS if pad.GetDrillSize().x > 0
                          else (route.FRONT,))
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
                if pad.GetDrillSize().x > 0:
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


def build():
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

    rectangle = placement.extents([
        ((left + right) / 2, (top + bottom) / 2, right - left, bottom - top)
        for _, left, top, right, bottom in board.courtyards])
    board.outline(rectangle)

    # The two grounds, on both inner layers, with placement.GROUND_GAP between
    # them. Two zones on one layer with different nets fill straight through
    # each other and DRC does not object -- each is correctly connected to its
    # own net -- so the separation is geometric and verify.py is what holds it.
    left, top, right, bottom = rectangle
    inset = 0.5
    split = placement.SPLIT_Y
    half = placement.GROUND_GAP / 2
    for layer in (pcbnew.In1_Cu, pcbnew.In2_Cu):
        board.zone("MAGND", layer,
                   (left + inset, top + inset, right - inset, split - half))
        board.zone("MDGND", layer,
                   (left + inset, split + half, right - inset, bottom - inset))

    stitched, stitch_copper = board.stitch_grounds()

    # Everything else, through the router. The two grounds are skipped because
    # stitch_grounds() has already given them the only connection they want.
    tracks, vias, missed = route.route_all(
        rectangle, board.pad_boxes(), obstacles=stitch_copper,
        rules={"pitch": ROUTE_PITCH_MM, "track": TRACK_MM,
               "clearance": CLEARANCE_MM, "via": VIA_DIAMETER_MM,
               "edge": EDGE_CLEARANCE_MM},
        skip=("MAGND", "MDGND"))
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
    return board, rectangle, stitched, len(tracks), len(vias), missed


def main():
    board, rectangle, stitched, tracks, vias, missed = build()
    left, top, right, bottom = rectangle
    width, height = right - left, bottom - top
    print(f"{BOARD.name}: {len(board.footprints)} footprints, "
          f"{len(RESERVED_MM)} reserved, {len(board.nets)} nets")
    print(f"  outline {width:.1f} x {height:.1f} mm = {width * height:.0f} mm2, "
          f"four layers, ground split at y = {placement.SPLIT_Y:.1f}")
    print(f"  {stitched} ground pads stitched to the planes, "
          f"{tracks} track runs and {vias} vias routed")
    if missed:
        print(f"  {len(missed)} nets the router could not finish, and they are "
              f"named rather than counted:")
        for index in range(0, len(missed), 6):
            print(f"      {', '.join(missed[index:index + 6])}")


if __name__ == "__main__":
    main()
