"""Return-via stitching: a ground via beside a signal via that changes plane.

    python3 returns.py             # measure and plan; writes nothing
    python3 returns.py --commit    # write the vias into out/cv-module.kicad_pcb

**What this is for.** In1.Cu and In2.Cu carry the same two nets in the same
places, so every via on this board changes reference plane as well as signal
layer, and the return current has to transfer between the planes. The only
conductor that does that is a ground via. `constraints.return_loops()` is the
measurement -- the loop is `rules.plane_separation()` times the distance to
the nearest one -- and this file is what moves it.

**Why the copper and not the derivation.** The number is provably negligible
as a return *impedance*: 22.76 mm of In1/In2 pair is tens of nanohenries and
tens of nanovolts against a 144 uV floor. As a pickup loop for this board's own
580 kHz converter and 1.1 MHz switcher it is not derived, because the aggressor
is a current loop inside a potted brick that no datasheet draws. Stitching is
cheap and it is explicitly **not routing**: every via here goes into open
copper, so no track already laid is disturbed and nothing has to be re-routed.
`gen_pcb.stitch_grounds()` is the precedent and also the reason the figure was
what it was -- it places at ground *pads*, so nothing had ever tried to put a
stitch near a signal via.

**Where it sits in the workflow.** With `route.py` and `krt.py`, and for the
same reason: it edits the board rather than regenerating it, so it is in
neither pipeline and it writes nothing without `--commit`. Unlike either of
them it cannot destroy anything -- it only adds vias, and it adds none that
`blocker()` has not cleared.

**The three ways this could be wrong, and what each is guarded by.**

* a via that does not reach the plane -- the candidate has to sit inside the
  *filled* polygon of its own net on both inner layers, which is also what
  makes a copper test on those two layers unnecessary: the filler already kept
  every foreign clearance when it drew that boundary;
* a via too close to something -- the three distances of
  `rules.via_exclusion()` plus the two of `rules.hole_rules()`, against every
  track, pad and via on the board, and against the vias this run has already
  placed;
* a via somewhere a person cannot assemble around -- footprint keep-out areas
  and courtyards are refused outright.

KiCad's own DRC is the gate on all three and `verify.py` runs it.
"""

import argparse
import math
import pathlib
import re
import statistics
import sys
import uuid

import constraints
import placement
import rules
from toolchain import sexp

BOARD = pathlib.Path(__file__).resolve().parent / "out" / "cv-module.kicad_pcb"

# **Two passes, and the second one is not the first with a bigger number.**
# The first asks for a stitch within TIGHT_MM, which is what a return via is
# worth: the loop is the distance, so a spot 1 mm away is worth five times one
# 5 mm away. The second takes what is left -- audio vias in packed copper where
# no legal spot exists that close -- and accepts a longer one rather than
# nothing. Measured on this board, the difference between one tight pass and
# the pair is 29 vias served instead of refused.
TIGHT_MM = 2.0
WIDE_MM = 5.0

# The via geometry is the board's own, and there is only one on it.
VIA_MM = rules.VIA_DIAMETER_MM
DRILL_MM = rules.VIA_DRILL_MM
VIA_R = VIA_MM / 2

# A stitch is named by where it is, so a re-run writes the same file. KiCad's
# own generator mints a fresh UUID per item, which is the churn PDF_EPOCH's
# comment complains about one artefact along; there is no reason to inherit it
# for copper this file places deterministically.
UUID_NS = uuid.UUID("6f1f5a5e-0d7a-5c58-9f2e-4a0e1a1d0b21")


# ---------------------------------------------------------------------------
# Reading the board
# ---------------------------------------------------------------------------

def _rotate(dx, dy, degrees):
    """A footprint-local offset in board coordinates.

    **The sign is KiCad's and getting it wrong is silent.** The board's y axis
    points down, and a footprint's stated rotation turns its pads the other way
    round from the textbook matrix -- so a `+90` footprint whose pads were
    placed with `+90` here comes out mirrored through its own centre. Nothing
    complains: the pads are still pads, still the right size, still in a
    plausible row. It was found by KiCad's DRC naming a pad this file thought
    was 2.5 mm away, and confirmed against a track endpoint, which is absolute
    and needs no convention at all.
    """
    r = math.radians(-degrees)
    return (dx * math.cos(r) - dy * math.sin(r),
            dx * math.sin(r) + dy * math.cos(r))


def _reference(footprint):
    for prop in sexp.find_all(footprint, "property"):
        if str(prop[1]) == "Reference":
            return str(prop[2])
    return "?"


def read(board=BOARD):
    """Everything this file needs off the board, in one pass of the parser."""
    tree = sexp.parse(board.read_text())
    out = {"vias": [], "segments": [], "pads": [], "courtyards": [],
           "keepouts": [], "pours": {}}
    for via in sexp.find_all(tree, "via"):
        at, net = sexp.find(via, "at"), sexp.find(via, "net")
        out["vias"].append((float(at[1]), float(at[2]),
                            float(sexp.find(via, "drill")[1]),
                            str(net[-1]) if net is not None else ""))
    for seg in sexp.find_all(tree, "segment"):
        a, b = sexp.find(seg, "start"), sexp.find(seg, "end")
        net = sexp.find(seg, "net")
        out["segments"].append((float(a[1]), float(a[2]),
                                float(b[1]), float(b[2]),
                                float(sexp.find(seg, "width")[1]),
                                str(sexp.find(seg, "layer")[1]),
                                str(net[-1]) if net is not None else ""))
    for fp in sexp.find_all(tree, "footprint"):
        at = sexp.find(fp, "at")
        fx, fy = float(at[1]), float(at[2])
        rot = float(at[3]) if len(at) > 3 else 0.0
        ref = _reference(fp)
        for pad in sexp.find_all(fp, "pad"):
            pat = sexp.find(pad, "at")
            size = sexp.find(pad, "size")
            spin = float(pat[3]) if len(pat) > 3 else 0.0
            drill = sexp.find(pad, "drill")
            hole = 0.0
            if drill is not None:
                for token in drill[1:]:
                    try:
                        hole = float(token)
                        break
                    except (TypeError, ValueError):
                        continue
            net = sexp.find(pad, "net")
            dx, dy = _rotate(float(pat[1]), float(pat[2]), rot)
            # **The pad's own angle is absolute and the footprint's is not
            # added to it.** Measured across this board: 725 pads read 90 on a
            # 90-degree footprint and 89 read 270 on a -90 one, which is the
            # footprint's own angle written out again rather than a relative
            # zero. Adding the two transposes every rotated pad's box -- 0.7
            # for 0.5125 on an 0805 -- which is small enough to look right and
            # is exactly the size of the clearances being checked.
            cos = abs(math.cos(math.radians(spin)))
            sin = abs(math.sin(math.radians(spin)))
            w, h = float(size[1]), float(size[2])
            out["pads"].append((fx + dx, fy + dy,
                                (w * cos + h * sin) / 2,
                                (w * sin + h * cos) / 2, hole,
                                str(net[-1]) if net is not None else "", ref))
        xs, ys = [], []
        for kind in ("fp_line", "fp_rect", "fp_poly", "fp_circle"):
            for item in sexp.find_all(fp, kind):
                layer = sexp.find(item, "layer")
                if layer is None or not str(layer[1]).endswith("CrtYd"):
                    continue
                for tag in ("start", "end", "center", "xy"):
                    for point in sexp.find_all(item, tag):
                        px, py = _rotate(float(point[1]), float(point[2]), rot)
                        xs.append(fx + px)
                        ys.append(fy + py)
        if xs:
            out["courtyards"].append((min(xs), min(ys), max(xs), max(ys), ref))
        # **A footprint can carry a keep-out and this board has ten of them.**
        # gen_pcb.keepouts() records why: the Pico's own underside test pads.
        for zone in sexp.find_all(fp, "zone"):
            keep = sexp.find(zone, "keepout")
            if keep is None:
                continue
            rule = sexp.find(keep, "vias")
            if rule is None or str(rule[1]) != "not_allowed":
                continue
            points = sexp.find(sexp.find(zone, "polygon"), "pts")
            xs, ys = [], []
            for point in sexp.find_all(points, "xy"):
                px, py = _rotate(float(point[1]), float(point[2]), rot)
                xs.append(fx + px)
                ys.append(fy + py)
            if xs:
                out["keepouts"].append((min(xs), min(ys), max(xs), max(ys)))
    for zone in sexp.find_all(tree, "zone"):
        net = str(sexp.find(zone, "net")[1])
        layer = str(sexp.find(zone, "layer")[1])
        for fill in sexp.find_all(zone, "filled_polygon"):
            points = sexp.find(fill, "pts")
            poly = [(float(p[1]), float(p[2]))
                    for p in sexp.find_all(points, "xy")]
            if poly:
                out["pours"].setdefault((net, layer), []).append(poly)
    return out


def check_pad_geometry(data, board=BOARD):
    """Every netted pad should have copper of its own net landing inside it.

    **This exists because two rotation conventions were wrong at once and
    nothing here could tell.** The pads were still pads, still the right size,
    still in a plausible row -- they were mirrored through their footprint's
    centre and their boxes transposed, which on an 0805 is 0.7 mm for 0.5125.
    That is small enough to look right and exactly the size of the clearances
    this file checks. KiCad's DRC found it, by naming a pad 2.5 mm from where
    this file had put it.

    The instrument is an *independent* coordinate: a track endpoint is
    absolute and carries no convention at all, so a pad that agrees with one
    is a pad in the right place. Ground pads are the honest exception -- the
    plane connects them and no track has to reach them -- so a miss is
    reported with its distance rather than raising, and the count is what a
    reader compares.
    """
    ends = {}
    for x0, y0, x1, y1, _w, _layer, net in data["segments"]:
        ends.setdefault(net, []).extend([(x0, y0), (x1, y1)])
    for x, y, _drill, net in data["vias"]:
        ends.setdefault(net, []).append((x, y))
    landed, missed, unrouted = 0, [], 0
    for x, y, half_w, half_h, _hole, net, ref in data["pads"]:
        if not net:
            continue
        points = ends.get(net)
        if not points:
            unrouted += 1
            continue
        if any(abs(px - x) <= half_w + 0.01 and abs(py - y) <= half_h + 0.01
               for px, py in points):
            landed += 1
        else:
            near = min(points, key=lambda p: math.dist(p, (x, y)))
            missed.append((ref, net, math.dist(near, (x, y))))
    return {"landed": landed, "missed": missed, "unrouted": unrouted}


# ---------------------------------------------------------------------------
# Where a via may go
# ---------------------------------------------------------------------------

class Buckets:
    """A uniform grid over segments, so a nearby-items query is not a scan."""

    def __init__(self, cell=2.0):
        self.cell, self.cells = cell, {}

    def add(self, x0, y0, x1, y1, payload):
        c = self.cell
        for i in range(int(min(x0, x1) // c), int(max(x0, x1) // c) + 1):
            for j in range(int(min(y0, y1) // c), int(max(y0, y1) // c) + 1):
                self.cells.setdefault((i, j), []).append(
                    (x0, y0, x1, y1, payload))

    def near(self, x, y, reach):
        c = self.cell
        found = []
        for i in range(int((x - reach) // c), int((x + reach) // c) + 1):
            for j in range(int((y - reach) // c), int((y + reach) // c) + 1):
                found.extend(self.cells.get((i, j), ()))
        return found


def segment_distance(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    span = dx * dx + dy * dy
    if span < 1e-12:
        return math.hypot(px - x0, py - y0)
    t = ((px - x0) * dx + (py - y0) * dy) / span
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return math.hypot(px - (x0 + dx * t), py - (y0 + dy * t))


class Pour:
    """One net's filled copper on one layer: inside-ness and edge distance."""

    def __init__(self, polygons):
        self.polygons = polygons
        self.edges = Buckets()
        # **The slits are not copper boundaries and they outnumber the ones
        # that are.** KiCad flattens a polygon-with-holes into a single ring by
        # cutting a zero-width channel out to each hole, so every slit edge
        # appears twice, once in each direction -- and a distance-to-boundary
        # query then answers 0.038 mm for a via sitting in solid copper.
        # Measured before this: 76 of the 151 stitches gen_pcb.py placed were
        # refused by their own pour. A slit is exactly a pair of coincident
        # opposed edges, so it is removed exactly rather than by a tolerance.
        listed = []
        for polygon in polygons:
            for k in range(len(polygon)):
                listed.append((polygon[k], polygon[(k + 1) % len(polygon)]))
        seen = set(listed)
        self.slits = 0
        for a, b in listed:
            if (b, a) in seen:
                self.slits += 1
                continue
            self.edges.add(a[0], a[1], b[0], b[1], None)

    def inside(self, x, y):
        hit = False
        for polygon in self.polygons:
            n = len(polygon)
            for k in range(n):
                x0, y0 = polygon[k]
                x1, y1 = polygon[(k + 1) % n]
                if (y0 > y) != (y1 > y):
                    if x0 + (y - y0) * (x1 - x0) / (y1 - y0) > x:
                        hit = not hit
        return hit

    def holds(self, x, y, reach):
        """True if a disc of `reach` at (x, y) is inside this copper."""
        for x0, y0, x1, y1, _ in self.edges.near(x, y, reach):
            if segment_distance(x, y, x0, y0, x1, y1) < reach:
                return False
        return self.inside(x, y)


class Space:
    """The board as obstacles, and one question: may a via go here?"""

    def __init__(self, board=BOARD):
        data = read(board)
        self.exclusion = rules.via_exclusion()
        self.holes = rules.hole_rules()
        self.same_via = DRILL_MM + self.holes["min_hole_to_hole"]
        self.cross_via = self.exclusion["to_via_mm"]
        self.vias = data["vias"]
        self.pours = {key: Pour(value) for key, value in data["pours"].items()}
        self.tracks = {}
        for x0, y0, x1, y1, width, layer, net in data["segments"]:
            if layer not in ("F.Cu", "B.Cu"):
                continue
            self.tracks.setdefault(layer, Buckets()).add(
                x0, y0, x1, y1, (width, net))
        self.via_grid = Buckets()
        for x, y, drill, net in self.vias:
            self.via_grid.add(x, y, x, y, (drill, net))
        self.pad_grid = Buckets()
        for x, y, half_w, half_h, hole, net, ref in data["pads"]:
            self.pad_grid.add(x - half_w, y - half_h, x + half_w, y + half_h,
                              (half_w, half_h, hole, net, ref))
        self.keep_grid = Buckets()
        for box in data["keepouts"]:
            self.keep_grid.add(*box, None)
        self.court_grid = Buckets()
        for x0, y0, x1, y1, ref in data["courtyards"]:
            self.court_grid.add(x0, y0, x1, y1, ref)

    def blocker(self, x, y, net, laid=()):
        """What stops a `net` via at (x, y), as a sentence, or None."""
        # 1. **The planes, and the clearance is already in the boundary.**
        # The filler drew that outline CLEARANCE_MM back from every foreign
        # item, so a via whose copper just touches it is already clear of
        # whatever made the void. Asking for VIA_R + clearance asks 0.55 mm
        # where the rule is 0.35, and on this board that is the difference
        # between a stitch beside a signal via and no stitch at all: a signal
        # via's antipad is 0.55 mm and the via-to-via rule is 0.9.
        for layer in ("In1.Cu", "In2.Cu"):
            pour = self.pours.get((net, layer))
            if pour is None or not pour.holds(x, y, VIA_R):
                return f"no {net} copper to land on at {layer}"
        # 2. Tracks on the two signal layers. Same net keeps no clearance --
        # it is the same conductor -- and the hole rule is to foreign copper.
        for layer, grid in self.tracks.items():
            for x0, y0, x1, y1, (width, other) in grid.near(x, y, 1.5):
                if other == net:
                    continue
                gap = segment_distance(x, y, x0, y0, x1, y1)
                need = max(VIA_R + width / 2 + rules.CLEARANCE_MM,
                           DRILL_MM / 2 + self.holes["min_hole_clearance"]
                           + width / 2)
                if gap < need - 1e-9:
                    return (f"a {other} track on {layer}, {gap:.2f} mm "
                            f"against {need:.2f}")
        # 3. Vias, and the net decides which of the two rules -- the same two
        # distances gen_pcb.stitch_grounds() keeps, and for its reasons.
        for x0, y0, _x1, _y1, (drill, other) in self.via_grid.near(x, y, 2.0):
            gap = math.hypot(x - x0, y - y0)
            need = self.same_via if other == net else self.cross_via
            if gap < need - 1e-9:
                return (f"the {other} via at ({x0:.2f}, {y0:.2f}), "
                        f"{gap:.2f} mm against {need:.2f}")
        for x0, y0, other in laid:
            gap = math.hypot(x - x0, y - y0)
            need = self.same_via if other == net else self.cross_via
            if gap < need - 1e-9:
                return (f"a stitch this run placed at ({x0:.2f}, {y0:.2f}), "
                        f"{gap:.2f} mm against {need:.2f}")
        # 4. Pads: copper to a foreign one, hole to hole to a drilled one.
        for x0, y0, x1, y1, (half_w, half_h, hole, other, ref) in \
                self.pad_grid.near(x, y, 2.5):
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            gap = math.hypot(max(0.0, abs(x - cx) - half_w),
                             max(0.0, abs(y - cy) - half_h))
            if other != net and gap < self.exclusion["to_pad_mm"] - 1e-9:
                return (f"{ref}'s {other} pad, {gap:.2f} mm against "
                        f"{self.exclusion['to_pad_mm']:.2f}")
            if hole > 0.0:
                centres = math.hypot(x - cx, y - cy)
                need = (hole / 2 + self.holes["min_hole_to_hole"]
                        + DRILL_MM / 2)
                if centres < need - 1e-9:
                    return (f"{ref}'s drilled pad, {centres:.2f} mm against "
                            f"{need:.2f}")
        # 5. Places a person needs kept clear.
        for x0, y0, x1, y1, _ in self.keep_grid.near(x, y, 1.0):
            if x0 - VIA_R <= x <= x1 + VIA_R and y0 - VIA_R <= y <= y1 + VIA_R:
                return "a footprint keep-out"
        for x0, y0, x1, y1, ref in self.court_grid.near(x, y, 1.0):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return f"{ref}'s courtyard"
        return None


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

AUDIO = re.compile(r"^(%s)\d+$" % "|".join(constraints.AUDIO_FAMILIES))
MAGND_EDGE = placement.SPLIT_Y - placement.GROUND_GAP / 2


def _ground_for(y):
    """Which plane an audio via at this y is over.

    **MAGND wherever there is MAGND**, because a stitch is a transfer point and
    a transfer point in the digital plane invites audio return current into it.
    South of the pour edge there is no MAGND to land on -- that is what
    `constraints.audio_off_its_own_plane()` measures and what the three bypass
    relays cost by design -- and MDGND there is not a second bond: In1 and In2
    are the same net at that point already, so the stitch closes a local loop
    and creates no path the copper did not have.
    """
    return "MAGND" if y < MAGND_EDGE else "MDGND"


def plan(space, tight=TIGHT_MM, wide=WIDE_MM):
    """Where to put a stitch, nearest legal spot first.

    The objective is proximity and not coverage, because what a return via is
    worth is set by how close it is: the loop is the distance. Coverage is the
    tie-break inside one ring, and it is what keeps the count down where the
    audio vias arrive in clusters.
    """
    targets = [(x, y, net) for x, y, _d, net in space.vias if AUDIO.match(net)]
    ground = [(x, y) for x, y, _d, net in space.vias
              if net in constraints.RETURN_VIA_NETS]
    have = [min(math.dist((t[0], t[1]), g) for g in ground) for t in targets]
    laid, refused = [], []
    for reach in (tight, wide):
        stuck = set()
        while True:
            open_ = [i for i in range(len(targets))
                     if have[i] > reach and i not in stuck]
            if not open_:
                break
            seed = max(open_, key=lambda i: have[i])
            sx, sy, snet = targets[seed]
            net = _ground_for(sy)
            best = None
            steps = range(int(VIA_MM * 100 + 20), int(reach * 100) + 1, 20)
            for radius in (step / 100 for step in steps):
                for degrees in range(0, 360, 6):
                    x = sx + radius * math.cos(math.radians(degrees))
                    y = sy + radius * math.sin(math.radians(degrees))
                    if _ground_for(y) != net:
                        continue
                    if space.blocker(x, y, net, laid):
                        continue
                    gain = sum(1 for i in open_
                               if math.dist((x, y), targets[i][:2]) <= reach)
                    if best is None or -gain < best[0]:
                        best = (-gain, (x, y))
                if best is not None:
                    break
            if best is None:
                stuck.add(seed)
                if reach == wide:
                    refused.append((snet, sx, sy, have[seed]))
                continue
            x, y = best[1]
            laid.append((x, y, net))
            for i, target in enumerate(targets):
                have[i] = min(have[i], math.dist((x, y), target[:2]))
    return laid, refused


# ---------------------------------------------------------------------------
# Writing it
# ---------------------------------------------------------------------------

def as_sexp(x, y, net):
    """One via, in the shape KiCad writes and gen_pcb.py's own vias have."""
    name = uuid.uuid5(UUID_NS, f"{net}:{x:.4f},{y:.4f}")
    return ("\t(via\n"
            f"\t\t(at {x:g} {y:g})\n"
            f"\t\t(size {VIA_MM:g})\n"
            f"\t\t(drill {DRILL_MM:g})\n"
            '\t\t(layers "F.Cu" "B.Cu")\n'
            f'\t\t(net "{net}")\n'
            f'\t\t(uuid "{name}")\n'
            "\t)\n")


def commit(laid, board=BOARD):
    """Insert the vias ahead of the first zone, where the track section ends.

    Text, not `pcbnew`. Two reasons and both are this repo's own: `SaveBoard()`
    rewrites the project file with KiCad's defaults -- the fault `gen_project.py`
    has to run after `gen_pcb.py` for -- and it re-mints every UUID on the
    board, which is the 102,909-line churn `PDF_EPOCH`'s comment describes. A
    via is seven lines of s-expression; neither price is worth paying for it.

    **No zone refill is needed and that is a property of what is being added.**
    A same-net via inside a same-net pour takes no void: the filler carves for
    foreign copper only, which is measured -- a signal via sits in a 0.55 mm
    hole in both planes and a ground via sits in solid copper. The connection
    *is* the overlap.
    """
    text = board.read_text()
    # **The newline is load-bearing and its absence put 135 vias inside a
    # footprint.** `"\t(zone\n"` is a substring of `"\t\t(zone\n"`, so the
    # first match in this file is one of the Pico's own keep-out zones, 60,000
    # lines above the first top-level one. The board still parsed, KiCad would
    # still have opened it, and the vias were nowhere -- the only thing that
    # said so is that this file measures the board back after writing it and
    # got the number it started with.
    marker = "\n\t(zone\n"
    at = text.index(marker) + 1
    board.write_text(text[:at] + "".join(as_sexp(*via) for via in laid)
                     + text[at:])
    return len(laid)


def _report(laid, refused, before, after):
    print("Return-via stitching -- a ground via where a signal changes plane")
    print(f"  plane separation      {before['height_mm']:.2f} mm "
          f"(rules.plane_separation())")
    print(f"  audio vias            {before['audio_vias']}")
    print()
    print("                        before    after")
    print(f"  ground vias         {before['ground_vias']:8d} {after['ground_vias']:8d}")
    print(f"  worst separation    {before['worst_mm']:8.2f} {after['worst_mm']:8.2f}  mm")
    print(f"  median separation   {before['median_mm']:8.2f} {after['median_mm']:8.2f}  mm")
    print(f"  within 2 mm         {before['within_2mm']:8d} {after['within_2mm']:8d}")
    print(f"  total loop area     {before['total_mm2']:8.1f} {after['total_mm2']:8.1f}  mm2")
    print()
    print(f"  {len(laid)} stitches, {len(refused)} audio vias with no legal "
          f"spot inside {WIDE_MM:.0f} mm")
    for net, x, y, gap in refused[:8]:
        print(f"    {net:<8} ({x:7.2f}, {y:7.2f})  nearest ground via "
              f"{gap:.2f} mm")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commit", action="store_true",
                        help="write the vias into the tracked board")
    parser.add_argument("--tight", type=float, default=TIGHT_MM)
    parser.add_argument("--wide", type=float, default=WIDE_MM)
    args = parser.parse_args(argv)

    before = constraints.return_loops(BOARD)
    geometry = check_pad_geometry(read(BOARD))
    print(f"  pad geometry: {geometry['landed']} pads with same-net copper "
          f"landing inside, {len(geometry['missed'])} without "
          f"({geometry['unrouted']} on nets with no copper at all)")
    for ref, net, gap in geometry["missed"][:6]:
        print(f"    {ref:<6} {net:<8} nearest {net} copper {gap:.2f} mm away")
    space = Space(BOARD)
    laid, refused = plan(space, args.tight, args.wide)
    # The prediction, computed the same way the board will be measured.
    ground = ([(x, y) for x, y, _d, net in space.vias
               if net in constraints.RETURN_VIA_NETS]
              + [(x, y) for x, y, _n in laid])
    height = before["height_mm"]
    gaps = sorted(min(math.dist((row["x"], row["y"]), g) for g in ground)
                  for row in before["rows"])
    after = {"ground_vias": len(ground), "worst_mm": gaps[-1],
             "median_mm": statistics.median(gaps),
             "within_2mm": sum(1 for g in gaps if g <= 2.0),
             "total_mm2": sum(gaps) * height}
    _report(laid, refused, before, after)
    if not args.commit:
        print()
        print("  nothing written -- pass --commit to put these on the board")
        return 0
    print()
    print(f"  wrote {commit(laid)} vias into {BOARD.name}")
    # **Measured back, and the prediction is checked against it.** Not
    # ceremony: the first version of commit() inserted every via inside a
    # footprint, and this is the only line that noticed. A write that reports
    # success and changes nothing is the failure this repository collects.
    measured = constraints.return_loops(BOARD)
    if abs(measured["total_mm2"] - after["total_mm2"]) > 0.5:
        raise SystemExit(
            f"the board reads back at {measured['total_mm2']:.1f} mm2 and "
            f"the plan predicted {after['total_mm2']:.1f} -- the vias are not "
            f"where this file thinks it put them")
    print(f"  measured back: {measured['total_mm2']:.1f} mm2, worst "
          f"{measured['worst_mm']:.2f} mm, median "
          f"{measured['median_mm']:.2f} mm")
    print(f"  set constraints.AUDIO_RETURN_AREA_MM2 to "
          f"{measured['total_mm2']:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
