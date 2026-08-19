"""A maze router: pads in, polylines out, and no KiCad anywhere in it.

**Deleted for one pass and restored, and the restoration is a narrower claim
than the deletion was.** It went when the RP2040 became a Pico module, on the
reasoning that the problem it existed for -- a 0.40 mm pin pitch -- had gone
with the QFN, and that its real cost was making the *board* a function of
design.py: no question about geometry could be asked of a layout until it had
been answered in Python first. That cost was real and the rule it produced
stands:

    **the netlist is generated and authoritative; the board is hand-laid and
    verified.**

What is restored is not that rule's opposite. This file runs **once**, as a
seed -- `gen_pcb.py --seed-routing` -- and what it produces is a starting
point somebody edits in KiCad, not an output the build reproduces. Nothing
downstream consults it: verify.py asks its questions of the saved board by
reading it back, and UNROUTED_ITEMS counts what is unmade whoever left it
unmade. gen_pcb_guard.refuse_to_discard_routing() is what stops a second run
happening by accident, and it was written before this file came back.

**And the board it now runs on is inside its competence rather than at the
edge of it**, which is the other half of the argument. It closed the QFN board
at 0 unrouted and 0 DRC on a 0.23 mm grid at 0.09/0.09 -- the finest class
this project has costed. The fitted class is 0.20/0.20 on a 0.45 mm grid: two
adjacent tracks are 0.25 mm apart against the 0.20 they need, the finest pitch
left is the MCP3564's 0.65 mm TSSOP, and there are 3.7x fewer cells. Nothing
in it changed to come back.

Separate from gen_pcb.py for the reason placement.py is: this is arithmetic on
coordinates, and arithmetic that can only run inside KiCad's own interpreter is
arithmetic nobody can check. gen_pcb.py hands it pad positions and lays down
whatever it returns.

**Why a router at all, rather than waypoints.** The mixer routes by hand -- 2638
lines of explicit track waypoints, derived from real pad positions -- and that
is the right answer for a board whose six channels are one strip each and whose
author is going to look at every millimetre of it. This board is 222 footprints
on a systematic grid, and the same approach would be four thousand lines of
coordinates that nobody could re-derive after a part moved. A router is the
thing that survives placement.py changing its mind.

The algorithm is Lee's, with A* ordering: a uniform grid over the board, two
signal layers, breadth-first from the net's own copper to the next pad, and a
via wherever the path changes layer. It is the oldest routing algorithm there
is and it has the property this repo needs -- **it either finds a path or says
it did not**, and it never produces a short. Everything it cannot route is
reported by name and counted, which is what verify.UNROUTED_ITEMS holds.

On top of it, **rip-up and retry**: a route that cannot get through probes for
the nets in its way, displaces exactly those, and puts them back on the queue.
route_all() has the argument, including why the obvious cheaper version --
re-routing the whole board in a different order -- looks like it works and does
not.

Three rules make the result DRC-clean by construction rather than by luck:

  * **the grid pitch is set from the design rules**, not chosen. Two tracks on
    adjacent cells are PITCH - TRACK apart, which has to clear CLEARANCE;
  * **a via blocks its eight neighbours.** A via is wider than a track, so a
    track on the cell next door would be inside the clearance even though the
    centres are a whole pitch apart. This is the one place where the grid's
    uniformity is not enough on its own;
  * **pads block a halo** of their own, computed from the pad's size rather
    than assumed, so a track never passes closer to somebody else's copper
    than the rules allow.

The two inner layers are ground planes and nothing routes on them. That is the
stackup decision from gen_pcb.py restated as a constraint: a signal on an inner
layer is a slot cut in the reference under every trace that crosses it.
"""

import heapq
import math

# The layers this router may use. In1 and In2 are poured ground and are not
# offered, which is why this is a tuple of two and not a layer count.
FRONT, BACK = 0, 1
LAYERS = (FRONT, BACK)

# Cost of changing layer, in cells. **This was 2, and the measurement that set
# it was answering a question that no longer exists.**
#
# It was tuned against unrouted nets: 9 left 78 connections unmade, 6 left 69,
# 4 left 69 and 2 left 67, so 2 won and the comment here concluded that "cheap
# vias route better on this board". With rip-up and retry the board finishes at
# every one of those values -- 2, 4, 6, 9, 12, 16 and 24 all reach zero -- so
# completeness has stopped being the thing the number buys, and what is left is
# the count:
#
#     VIA_COST      2     4     6     9    12    16    24
#     vias        452   424   380   360   345   373   345
#
# It flattens at 12 and does not improve after. So the parameter now costs
# **345 vias instead of 452**, a quarter of the holes in the board, for no
# connection given up -- and the old conclusion was not wrong about the
# placement, it was wrong about what the placement implied. Cheap vias did
# route better while the router had one attempt per net, because a route that
# cannot get through has to go round and a via is how it goes round. Once a
# route that cannot get through can move somebody instead, it does not need
# the via, and the reason to prefer one disappears.
#
# The argument the old comment made about the geometry is still true and worth
# keeping: twelve rows of parts on a 7.62 mm pitch make the front layer a set
# of corridors that run east-west, so a route that needs to go north is better
# off dropping to the back, crossing, and coming up than threading between two
# rows. A board laid out with routing channels would prefer the opposite. What
# is no longer true is that this makes vias worth encouraging.
#
# Twelve cells is 6 mm of copper per via. Nothing on this board is fast enough
# for via inductance to be the binding consideration; it is the drill count
# that matters, and 345 on 144 nets is ordinary.
VIA_COST = 12

# Cost of turning, in cells. Nothing structural depends on it; it buys tracks
# that look deliberate rather than like a plotter fault, at no routing cost.
BEND_COST = 1

# What it costs a route to cross a track that is already down, in cells, when
# it is probing for something to rip up. 50 cells is 25 mm: a route will go a
# long way round rather than displace somebody, which is what keeps the number
# of rips small, and it will still displace somebody rather than fail. It is
# only ever paid inside a probe -- see Grid.route()'s `crossable`.
RIPUP_COST = 50

# How many times one net may be ripped up before it is left alone. This is
# what makes the loop terminate rather than trade two nets back and forth
# forever: each rip increments a counter, a net at the limit stops being
# crossable, and the work queue can therefore only grow by RIPUP_LIMIT times
# the number of nets. Four is enough here that no net has ever reached it.
RIPUP_LIMIT = 4


class Grid:
    """The board as cells, one plane per signal layer.

    `owner[layer][index]` is None for free, or the name of whatever occupies
    it -- a net, or the string "blocked" for board edge and keep-out. A cell
    owned by the net being routed is free to that net and blocked to every
    other, which is what lets a net's own copper be a routing target.
    """

    def __init__(self, rect, pitch, track, clearance, via_diameter,
                 via_reach=None):
        self.left, self.top, self.right, self.bottom = rect
        # rules.via_exclusion()'s three distances. Defaulted from the copper
        # rules alone so a caller that does not pass them is no worse off than
        # the hard-coded ring this replaced.
        self.via_reach = via_reach or {
            "to_track_mm": via_diameter / 2 + track / 2 + clearance,
            "to_via_mm": via_diameter + clearance,
            "to_pad_mm": via_diameter / 2 + clearance,
        }
        self._via_ring = None
        self._via_pair = None
        # Where a via may not be placed, by cell, with the nets responsible.
        self.no_via = {}
        # Where the vias actually are, so via-to-via can be asked. Kept beside
        # `owner` because a cell holding a via and a cell holding a track are
        # the same to `owner` and are not the same to this rule.
        self.placed_vias = {}
        self.pitch = pitch
        self.track = track
        self.clearance = clearance
        self.via = via_diameter
        self.columns = int((self.right - self.left) / pitch) + 1
        self.rows = int((self.bottom - self.top) / pitch) + 1
        self.owner = [[None] * (self.columns * self.rows) for _ in LAYERS]
        # Which cells are a pad's own copper. Held separately from `owner`
        # because it is a different claim: `owner` says who may route here,
        # `copper` says that no clearance rule reaches this cell at all.
        self.copper = [set() for _ in LAYERS]
        # The grid as it was before one millimetre of track was laid: pads,
        # rings, obstacles and the board edge, and nothing else. **This is what
        # makes ripping a net up exact rather than approximate**, and its
        # absence is the whole reason the first attempt at rip-up was rejected
        # as unbookkeepable. Restoring a cell is not "put back what was there
        # before I claimed it", which needs a per-claim ledger and goes wrong
        # the moment two nets claim one cell in sequence; it is "put back what
        # blocking said", which is a constant.
        self.base = None
        # **The isolation region, and it is a keep-out with an exception
        # list.** Everything else the router must not enter is "blocked" for
        # everybody -- the board edge, another net's pad ring. This one is
        # different: the primary's corner is forbidden to every net *except*
        # the primary's own, which is not something a single-owner cell can
        # say. So it is held beside `owner` and consulted in free().
        #
        # It exists because verify.check_isolation_gap() caught the router
        # putting VA+ through it. Nothing had ever told the router the region
        # was special: it is empty of pour by construction, which to a maze
        # router reads as the widest channel on the board. The check was doing
        # its job and the fix belongs one step earlier -- a rule the router
        # cannot break is worth more than a rule it is caught breaking.
        self.reserved = set()
        self.reserved_for = frozenset()

    # -- geometry ---------------------------------------------------------
    def cell_of(self, x, y):
        return (min(max(int(round((x - self.left) / self.pitch)), 0),
                    self.columns - 1),
                min(max(int(round((y - self.top) / self.pitch)), 0),
                    self.rows - 1))

    def point_of(self, column, row):
        return (round(self.left + column * self.pitch, 4),
                round(self.top + row * self.pitch, 4))

    def index(self, column, row):
        return row * self.columns + column

    def inside(self, column, row):
        return 0 <= column < self.columns and 0 <= row < self.rows

    # -- occupancy --------------------------------------------------------
    def take(self, layer, column, row, owner):
        if self.inside(column, row):
            self.owner[layer][self.index(column, row)] = owner

    def free(self, layer, column, row, net):
        if not self.inside(column, row):
            return False
        index = self.index(column, row)
        if index in self.reserved and net not in self.reserved_for:
            return False
        held = self.owner[layer][index]
        return held is None or held == net

    def reserve(self, x0, y0, x1, y1, nets):
        """Keep a rectangle for `nets` alone. See `self.reserved`."""
        self.reserved_for = frozenset(nets)
        for column in range(self.columns):
            for row in range(self.rows):
                x, y = self.point_of(column, row)
                if x0 <= x <= x1 and y0 <= y <= y1:
                    self.reserved.add(self.index(column, row))

    def _cells_within(self, x0, y0, x1, y1, reach):
        """Every cell whose *centre* lies inside a rectangle grown by `reach`.

        **The sample point, not the index, and this is the third version.**
        The first used cell_of(), which rounds to the nearest cell and so on
        the far edge of a box rounds *inwards*, leaving the first free cell up
        to half a pitch too close: those were the clearance violations reported
        at 0.15 and 0.19 mm against a 0.2 mm rule. The second replaced it with
        floor and ceiling on the range, which never leaves a cell too close and
        was the right correction in the only direction anybody was looking --
        but floor and ceiling round the *range* outwards, so it also claims a
        ring of cells up to a whole pitch beyond `reach`, whose track copper is
        demonstrably far enough away.

        On open board that costs nothing and nobody would ever see it. Between
        two SOIC pins 1.27 mm apart it is the whole of the space, which is why
        it took until a routing pass to show up. The cells are enumerated over
        the floor/ceiling range, because that is the range that cannot miss
        one, and then each is admitted on its own centre.
        """
        first = (int(math.floor((x0 - reach - self.left) / self.pitch)),
                 int(math.floor((y0 - reach - self.top) / self.pitch)))
        last = (int(math.ceil((x1 + reach - self.left) / self.pitch)),
                int(math.ceil((y1 + reach - self.top) / self.pitch)))
        for column in range(first[0], last[0] + 1):
            for row in range(first[1], last[1] + 1):
                x, y = self.point_of(column, row)
                if (x0 - reach <= x <= x1 + reach
                        and y0 - reach <= y <= y1 + reach):
                    yield column, row

    def block_box(self, layer, x0, y0, x1, y1, owner, margin=0.0):
        """Mark every cell whose track centre would be inside a rectangle."""
        reach = margin + self.clearance + self.track / 2
        for column, row in self._cells_within(x0, y0, x1, y1, reach):
            self.take(layer, column, row, owner)

    def block_pad_copper(self, layer, x0, y0, x1, y1, net):
        """A pad's own copper: hard, and **every pad's before any pad's ring**.

        A cell whose centre is inside the pad belongs to that net and to
        nothing else, and it is the one place on this board where a track has
        no clearance to satisfy -- a segment inside a pad's own copper cannot
        be too close to anything, because the pad already is not.

        **Which is why this is a separate pass from block_pad_ring().** The
        first version did both in one call, pad by pad, so a pad written later
        marked its neighbour's copper cells "blocked" on the way past: two SOIC
        pins are 1.27 mm apart and each one's clearance ring reaches 0.475 mm,
        so every pin in a row sits inside both its neighbours' rings. The pad
        lost the cells it is made of, `access()` found nothing free inside it
        and route_all() reported the net unreachable. That was IOUT1, IOUT4 and
        VREF, and from outside it looked exactly like congestion.

        **And the exemption is about the pad, while what gets drawn is a
        track.** "A cell inside the pad's copper cannot be too close to
        anything" is true of the *pad*; the router then lays a track of
        TRACK_MM through that cell, and a track wider than the pad sticks out
        of it. At 1.27 mm of pin pitch the overhang never reaches anybody. At
        0.65 mm it does: a TSSOP pad is 0.40 mm across, a track is 0.25, so a
        cell more than **(0.40 - 0.25) / 2 = 0.075 mm** off the pad's centre
        line draws copper past its edge and straight at the neighbour. DRC
        reported eight of those at 0.15 mm against a 0.2 mm rule, all at U17,
        on the first board this project has built with a fine pitch on it.

        So the box is inset by half a track before the cells are taken: what
        is claimed is not "inside the pad" but "inside the pad *with a track
        drawn through it*", which is the thing the exemption was always about.
        The cost is real and is the honest one -- some fine-pitch pads no
        longer have a cell and route_all() reports them, which is what
        rules.pad_reach() prices.
        """
        inset = self.track / 2
        x0, y0, x1, y1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
        if x1 < x0 or y1 < y0:
            return
        for column, row in self._cells_within(x0, y0, x1, y1, 0.0):
            self.take(layer, column, row, net)
            self.copper[layer].add(self.index(column, row))

    def block_pad_ring(self, layer, x0, y0, x1, y1, net):
        """The clearance halo around a pad, and it is exclusive rather than hard.

        A cell in the ring may be used by that pad's own net -- a stub has to
        leave the pad somehow -- but if it is also in *another* pad's ring,
        nobody may have it: two pads 1.27 mm apart share ring cells, and a
        track legally placed in one pad's ring is illegally close to the other.

        The first version blocked copper and halo with one call and let the
        last pad written win, which is how a track ended up 0.12 mm from a pin
        of a net it had never heard of.

        Copper is never overwritten, whoever owns it. That is what makes the
        two passes mean anything.
        """
        reach = self.clearance + self.track / 2
        for column, row in self._cells_within(x0, y0, x1, y1, reach):
            index = self.index(column, row)
            if index in self.copper[layer]:
                continue
            held = self.owner[layer][index]
            if held is None:
                self.take(layer, column, row, net)
            elif held != net:
                self.take(layer, column, row, "blocked")

    def block_escape_copper(self, layer, points, net):
        """The cells a fan-out escape's own copper sits exactly on.

        The pad equivalent is block_pad_copper(), and the difference between
        them is the difference between a pad and a track. A pad is a rectangle
        and the cells inside it are a region; an escape is a polyline of
        `track`-wide copper, and the only cells whose centres are *on* it are
        the ones its own segments pass through. In practice that is the cell
        it lands on and nothing else, because the segment along the pad's
        centre line is off-grid by construction -- being off-grid is why the
        escape exists.

        Claimed as `copper` for the same reason a pad's cells are: it stops a
        neighbour's ring from marking the cell "blocked" on the way past, and
        that cell is the one the router has to start the net at.
        """
        for column, row in self.escape_cells(points):
            index = self.index(column, row)
            if (index in self.copper[layer]
                    and self.owner[layer][index] not in (None, net)):
                continue
            self.take(layer, column, row, net)
            self.copper[layer].add(index)

    def escape_cells(self, points):
        """Every cell an escape's own copper sits on. Usually just the landing.

        Separate from block_escape_copper() because _one_pass() has to ask the
        question before it acts on it: an escape is only accepted if every cell
        it would claim is free to its own net, and claiming first and checking
        afterwards is how a "blocked" cell -- one that is inside two pads'
        clearance rings, and is blocked for exactly the reason the escape
        exists -- would get quietly handed back to the router.
        """
        for start, end in zip(points, points[1:]):
            x0, x1 = sorted((start[0], end[0]))
            y0, y1 = sorted((start[1], end[1]))
            for column, row in self._cells_within(x0, y0, x1, y1, 0.0):
                yield column, row

    def block_escape_ring(self, layer, points, net):
        """The halo around an escape, and **its reach is one track wider.**

        block_pad_ring() is handed the pad's own copper rectangle and grows it
        by `clearance + track / 2` -- the clearance itself, plus the half
        width of the track that might be laid in the cell. That is right
        because the rectangle it was given *is* the copper.

        Here the polyline is a centre line and the copper is `track` wide
        around it, so the reach is

            track / 2  +  clearance  +  track / 2   =   track + clearance

        and using block_pad_ring()'s number would leave every neighbouring
        cell half a track too close. This is the same distinction that put
        eight clearance violations on the last board, arriving from the other
        side: there, a claim about a pad was applied to a track; here, a
        reach computed for a rectangle would be applied to a line.
        """
        reach = self.track + self.clearance
        for start, end in zip(points, points[1:]):
            x0, x1 = sorted((start[0], end[0]))
            y0, y1 = sorted((start[1], end[1]))
            for column, row in self._cells_within(x0, y0, x1, y1, reach):
                index = self.index(column, row)
                if index in self.copper[layer]:
                    continue
                held = self.owner[layer][index]
                if held is None:
                    self.take(layer, column, row, net)
                elif held != net:
                    self.take(layer, column, row, "blocked")

    def escape(self, pad, out):
        """Where a fan-out escape lands, and the copper that gets it there.

        `pad` is the pad centre and `out` the point on the pad's own centre
        line beyond which the escape may turn -- rules.escape_reach() sets it
        and gen_pcb.py measures the pad. Returns `(cell, points)`.

        Two segments, and the order is the whole point:

          * **along the pad's own axis**, from the pad centre outwards. Inside
            the pin row this is the one line where a track is as safe as the
            pad it sits on, because it is where the pad is;
          * **then across, to the grid**, which is at most half a pitch and
            happens outside the package where there is nothing to be near.

        The turn is snapped to the first grid line at or beyond `out`, so the
        escape can only ever get longer than the reach it was given, never
        shorter.
        """
        px, py = pad
        ox, oy = out
        if abs(ox - px) >= abs(oy - py):
            axis, along, across = 0, ox - px, py
        else:
            axis, along, across = 1, oy - py, px
        origin = self.left if axis == 0 else self.top
        far = ox if axis == 0 else oy
        steps = (far - origin) / self.pitch
        index = int(math.ceil(steps - 1e-9) if along > 0
                    else math.floor(steps + 1e-9))
        other = int(round(((across - (self.top if axis == 0 else self.left))
                           / self.pitch)))
        column, row = (index, other) if axis == 0 else (other, index)
        if not self.inside(column, row):
            return None, []
        corner_x, corner_y = self.point_of(column, row)
        if axis == 0:
            corner = (corner_x, py)
        else:
            corner = (px, corner_y)
        return (column, row), [(px, py), corner, (corner_x, corner_y)]

    def access(self, layer, x, y, half_w, half_h, net):
        """The cell a route joins this pad at, and **it is inside the pad**.

        The stub from the pad's centre to that cell is the one piece of copper
        on this board that the grid does not govern, so the rule is that it
        never leaves the pad it belongs to: a segment inside a pad's own
        copper cannot be too close to anything, because the pad already is not.

        Letting it spiral outside cost more than it bought -- 17 shorts and 14
        hole-clearance violations from stubs crossing a neighbour on their way
        to a cell the grid said was free. If no cell inside the pad survives
        its neighbours' clearance rings, the honest answer is that this pad
        cannot be reached on this grid, and route_all() reports the net.

        **And the last line of this function used to say the opposite.** It
        ended `return (column, row) if self.free(...) else None`, with
        `(column, row)` the nearest cell to the pad *centre* -- which is
        outside the pad whenever nothing inside it is free, which is the only
        case the line ever ran in. So the one path this docstring forbids was
        the fallback, and it fired silently: the cell it returns is legal by
        the grid, and the stub to it is not governed by the grid at all.

        Nothing caught it for as long as the boards had room. check_no_shorts()
        looks for shorts and this is a clearance; the grid's own bookkeeping is
        correct, because the stub is the piece it does not own. **DRC caught
        it** -- eight violations at 0.15 mm against a 0.2 mm rule, every one a
        track beside a TSSOP pin, on the first board with a 0.65 mm pitch on
        it. The SOT-523 that has the same geometry sits in open board, so its
        stub never came near anything.

        A convenience whose safety depended on a condition nobody had written
        down, in the one function whose docstring states that condition.

        **Deleting it outright was wrong too, and Q801 is why.** A SOT-523's
        pads hold no cell in y either, and that part routed correctly on every
        board this project has built -- its neighbours are on the far side of
        the package, so its stub steps into open board. Removing the fallback
        cost FSD and FSG, two nets that had never been in any doubt.

        So the fallback stays and the condition is stated: **the stub is
        allowed outside the pad only where the copper it sweeps is free to
        this net.** _stub_is_clear() walks the cells the segment passes within
        a clearance of, which is the same test the grid applies to every other
        piece of track -- the stub stops being the one piece nobody checks.
        rules.pad_reach() is the arithmetic for which packages will fail it.
        """
        column, row = self.cell_of(x, y)
        first = (int(math.ceil((x - half_w - self.left) / self.pitch)),
                 int(math.ceil((y - half_h - self.top) / self.pitch)))
        last = (int(math.floor((x + half_w - self.left) / self.pitch)),
                int(math.floor((y + half_h - self.top) / self.pitch)))
        best, distance = None, None
        for candidate_column in range(first[0], last[0] + 1):
            for candidate_row in range(first[1], last[1] + 1):
                if not self.free(layer, candidate_column, candidate_row, net):
                    continue
                span = (abs(candidate_column - column)
                        + abs(candidate_row - row))
                if distance is None or span < distance:
                    best, distance = (candidate_column, candidate_row), span
        if best is not None:
            return best
        outside = self.cell_of(x, y)
        if (self.free(layer, *outside, net)
                and self._stub_is_clear(layer, x, y, outside, net)):
            return outside
        return None

    def _stub_is_clear(self, layer, x, y, cell, net):
        """Does the stub from a pad centre to `cell` keep its clearance?

        The stub is drawn as copper and is not laid cell by cell, so nothing
        else in this file tests it. It does not need to when it stays inside
        the pad -- a segment inside a pad's own copper cannot be too close to
        anything, because the pad already is not. Outside the pad it is
        ordinary track and has to answer the ordinary question.

        Cheap, because a stub is at most one pitch long: take the segment's
        bounding box, grow it by the same reach block_pad_ring() uses, and
        require every cell in it to be free to this net. A cell held by
        another pad's ring is exactly the 0.15 mm DRC reported.
        """
        target = self.point_of(*cell)
        reach = self.clearance + self.track / 2
        x0, x1 = sorted((x, target[0]))
        y0, y1 = sorted((y, target[1]))
        for column, row in self._cells_within(x0, y0, x1, y1, reach):
            if self.index(column, row) in self.copper[layer]:
                held = self.owner[layer][self.index(column, row)]
                if held is not None and held != net:
                    return False
                continue
            if not self.free(layer, column, row, net):
                return False
        return True

    def freeze(self):
        """Take the snapshot. Called once, after blocking and before routing."""
        self.base = [list(plane) for plane in self.owner]

    def release(self, cells):
        """Un-route these cells: back to what blocking left, not to empty.

        **And any via that stood on one goes too.** placed_vias is beside
        `owner` rather than in it, so restoring `owner` does not clear it -- and a
        via left in that dict after its net is ripped up is a phantom that
        forbids the next via for ever. It is the one piece of state here that
        rip-up has to be told about twice.
        """
        for layer, column, row in cells:
            index = self.index(column, row)
            self.owner[layer][index] = self.base[layer][index]
            self.placed_vias.pop((column, row), None)

    def block_edge(self, edge_clearance):
        """The board outline, on both layers."""
        reach = edge_clearance + self.track / 2
        for layer in LAYERS:
            for column in range(self.columns):
                for row in range(self.rows):
                    x, y = self.point_of(column, row)
                    if (x - self.left < reach or self.right - x < reach
                            or y - self.top < reach or self.bottom - y < reach):
                        self.take(layer, column, row, "blocked")

    # -- routing ----------------------------------------------------------
    # **A via is near three kinds of thing and this used to be one ring of four
    # cells.** The old constant blocked the four orthogonal neighbours and not
    # the diagonals, with a comment deriving it: a via is 0.6 mm across and a
    # track 0.25, so at one 0.5 mm pitch their copper is 0.075 mm apart -- a
    # third of the clearance, and 500 violations on the first routed board --
    # while at a diagonal it is 0.28 mm and clears. Requiring all eight was the
    # cautious version and cost 27 nets, because a SOIC pin's diagonals are
    # always somebody's clearance ring.
    #
    # All of that is true, and all of it is true **at a 0.5 mm grid on 0.25/0.20
    # copper**, stated as though it were a fact about the geometry. Routing this
    # board at 0.09/0.09 produced 56 DRC violations that the grid's own
    # bookkeeping thought were fine, in exactly the two places this ring does not
    # look: 49 between a via's hole and copper it is not connected to, and 7
    # between a via's copper and a pad's, because block_pad_ring() sizes a pad's
    # halo for the *track* that might be laid there and a via's copper reaches
    # 0.3 mm from its centre rather than 0.125.
    #
    # rules.via_exclusion() computes all three distances, each as the stricter of
    # a copper rule that shrinks with the class and a **hole** rule that does
    # not -- and the crossover is real: copper binds at the fitted class by
    # 0.10 mm and the hole rule binds at 0.09/0.09 by 0.01. They arrive through
    # the rules dict, because _one_pass() already has a parameter called `rules`.
    def _offsets(self, reach):
        """Cell offsets whose centres lie within `reach` of a cell centre."""
        span = int(math.floor(reach / self.pitch))
        found = []
        for dc in range(-span, span + 1):
            for dr in range(-span, span + 1):
                if math.hypot(dc, dr) * self.pitch <= reach + 1e-9:
                    found.append((dc, dr))
        return tuple(found)

    def via_ring(self):
        """Cells whose track copper would be inside a via's clearance."""
        if self._via_ring is None:
            self._via_ring = self._offsets(self.via_reach["to_track_mm"])
        return self._via_ring

    def via_pair(self):
        """Cells where another via would be too close, copper or hole."""
        if self._via_pair is None:
            self._via_pair = self._offsets(self.via_reach["to_via_mm"])
        return self._via_pair

    def block_pad_for_vias(self, x0, y0, x1, y1, net):
        """Cells where a *via* may not be placed because this pad is there.

        Separate from block_pad_ring() because it is a different distance about a
        different object: that halo is `clearance + track/2` and stops a track,
        and a via's copper stands 0.3 mm off its centre rather than 0.125. It is
        also not layer-specific -- a via is through-plated, so a cell that is
        illegal for it on one layer is illegal for it everywhere.

        Recorded per net rather than as a flat keep-out: a via on the same net as
        the pad may sit inside its halo, which is what a fan-out via at a pad
        does. So each cell carries the nets whose copper is near it, and a via is
        allowed only where every one of them is its own.
        """
        reach = self.via_reach["to_pad_mm"]
        for column, row in self._cells_within(x0, y0, x1, y1, reach):
            self.no_via.setdefault(self.index(column, row), set()).add(net)

    def block_no_via(self, x0, y0, x1, y1):
        """Cells where no via may go at all, whatever net it is on.

        **The one keep-out on this grid that is not about whose copper is
        near.** Everything else block_pad_for_vias() records is a clearance --
        a via on the pad's own net may sit inside its halo, which is what a
        fan-out via does. A *hole* rule is not that: two drills 0.41 mm apart
        collide whether or not the same current flows through them, and DRC
        found exactly that between a routed via and the through-hole pin it
        was serving. gen_pcb.drill_halos() is where the distance is computed.

        Recorded through the same `no_via` table under a name no net can have,
        so via_fits() refuses it without a second rule.
        """
        for column, row in self._cells_within(x0, y0, x1, y1, 0.0):
            self.no_via.setdefault(self.index(column, row), set()).add(
                "\0drill")

    def via_fits(self, column, row, net, crossable=()):
        held = self.no_via.get(self.index(column, row))
        if held and held - {net}:
            return False
        for dc, dr in self.via_pair():
            other = self.placed_vias.get((column + dc, row + dr))
            if other is not None and other != net:
                return False
        for dc, dr in self.via_ring():
            for layer in LAYERS:
                if (not self.free(layer, column + dc, row + dr, net)
                        and (layer, column + dc, row + dr) not in crossable):
                    return False
        return True

    def _neighbours(self, cell, net, crossable):
        layer, column, row = cell
        for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            yield (layer, column + dc, row + dr), 1
        if self.via_fits(column, row, net, crossable):
            yield (1 - layer, column, row), VIA_COST

    def route(self, net, sources, targets, crossable=None):
        """A* from any source cell to any target cell. None if there is none.

        Sources are the net's own copper so far, targets the pad being
        reached. Both are sets of (layer, column, row).

        `crossable` maps a cell to the net whose track is sitting on it, and
        turns this from "find a path" into "find a path, and say whose copper
        it would have to displace". Cells in it are passable at RIPUP_COST.
        A search given one is a *probe*: nothing it finds may be laid down
        until whatever it crossed has actually been ripped up.
        """
        if not sources or not targets:
            return None
        crossable = crossable or {}
        goal = {(c, r) for _, c, r in targets}

        def heuristic(cell):
            _, column, row = cell
            return min(abs(column - c) + abs(row - r) for c, r in goal)

        queue = []
        best = {}
        came = {}
        counter = 0
        for cell in sources:
            best[cell] = 0
            counter += 1
            heapq.heappush(queue, (heuristic(cell), counter, 0, cell))
        while queue:
            _, _, cost, cell = heapq.heappop(queue)
            if cell in targets:
                path = [cell]
                while cell in came:
                    cell = came[cell]
                    path.append(cell)
                return list(reversed(path))
            if cost > best.get(cell, cost):
                continue
            for step, penalty in self._neighbours(cell, net, crossable):
                layer, column, row = step
                if not self.free(layer, column, row, net):
                    if step not in crossable:
                        continue
                    penalty += RIPUP_COST
                # A bend costs, so a route that could go straight does. The
                # comparison is against where this cell was entered from,
                # which is what `came` holds.
                bend = 0
                previous = came.get(cell)
                if previous is not None and previous[0] == layer == cell[0]:
                    if ((cell[1] - previous[1], cell[2] - previous[2])
                            != (column - cell[1], row - cell[2])):
                        bend = BEND_COST
                fresh = cost + penalty + bend
                if fresh < best.get(step, 1 << 30):
                    best[step] = fresh
                    came[step] = cell
                    counter += 1
                    heapq.heappush(queue, (fresh + heuristic(step), counter,
                                           fresh, step))
        return None


def _box_gap(first, second):
    """Edge-to-edge distance between two axis-aligned boxes. 0 if they touch."""
    ax0, ay0, ax1, ay1 = first
    bx0, by0, bx1, by1 = second
    dx = max(bx0 - ax1, ax0 - bx1, 0.0)
    dy = max(by0 - ay1, ay0 - by1, 0.0)
    return math.hypot(dx, dy)


def _as_box(start, end):
    return (min(start[0], end[0]), min(start[1], end[1]),
            max(start[0], end[0]), max(start[1], end[1]))


def escape_clearances(points, net, layer, pads, obstacles, laid, track,
                      clearance):
    """Everything a proposed escape comes too close to. Empty is legal.

    **Geometric, and not a question about grid cells, because the escape is
    not on the grid.** Every other clearance test in this file asks whether a
    cell is free, which works because everything else the router draws is
    centred on a cell. The escape's first segment is deliberately off-grid --
    it is on the *pad's* centre line, which is where the grid is not -- so
    asking the grid would give the wrong answer in both directions at once.
    It would refuse the escape, because the cells beside a fine-pitch pin are
    blocked to routing and rightly so; and it would pass copper the grid does
    not own, which is exactly the class of fault that put eight violations on
    the last board.

    So this measures the copper. The escape's own half width is `track / 2`,
    a pad's copper is its box, and another escape has a half width too:

        to a pad or an obstacle:  gap >= clearance + track / 2
        to another escape:        gap >= clearance + track

    A pad of this net is not an obstruction to it, and neither is the pad the
    escape starts on -- which is the one box every escape overlaps.
    """
    problems = []
    for start, end in zip(points, points[1:]):
        box = _as_box(start, end)
        for other, entries in pads.items():
            if other == net:
                continue
            for x, y, half_w, half_h, layers in entries:
                if layer not in layers:
                    continue
                gap = _box_gap(box, (x - half_w, y - half_h,
                                     x + half_w, y + half_h))
                if gap < clearance + track / 2:
                    problems.append(
                        f"{gap:.3f} mm to {other or 'unnetted'} copper at "
                        f"({x:.2f}, {y:.2f})")
        for layers, x, y, half_w, half_h in obstacles:
            if layer not in layers:
                continue
            gap = _box_gap(box, (x - half_w, y - half_h,
                                 x + half_w, y + half_h))
            if gap < clearance + track / 2:
                problems.append(
                    f"{gap:.3f} mm to stitched copper at ({x:.2f}, {y:.2f})")
        for other, other_layer, other_points in laid:
            if other == net or other_layer != layer:
                continue
            for other_start, other_end in zip(other_points, other_points[1:]):
                gap = _box_gap(box, _as_box(other_start, other_end))
                if gap < clearance + track:
                    problems.append(
                        f"{gap:.3f} mm to the escape on {other}")
    return problems


def _order(pads):
    """Pads nearest-neighbour first, which is a cheap spanning tree.

    Not a minimum one. A proper MST would save a few millimetres of copper and
    would need the pads sorted twice; what this needs to get right is that each
    hop starts from copper the net already has, and any order does that.
    """
    remaining = list(pads)
    ordered = [remaining.pop(0)]
    while remaining:
        last = ordered[-1]
        nearest = min(remaining, key=lambda pad: (abs(pad[0] - last[0])
                                                  + abs(pad[1] - last[1])))
        remaining.remove(nearest)
        ordered.append(nearest)
    return ordered


def segments(grid, path):
    """A cell path as (layer, [(x, y), ...]) runs and (x, y) via positions."""
    runs, vias = [], []
    current_layer, points = path[0][0], [grid.point_of(path[0][1], path[0][2])]
    for layer, column, row in path[1:]:
        point = grid.point_of(column, row)
        if layer != current_layer:
            vias.append(point)
            if len(points) > 1:
                runs.append((current_layer, points))
            current_layer, points = layer, [point]
        else:
            points.append(point)
    if len(points) > 1:
        runs.append((current_layer, points))
    return runs, vias


def _connect(grid, net, entries, access, crossable=None, claim=True):
    """Join every pad of one net, pad to nearest pad. None if a hop has no path.

    Returns (tracks, vias, cells, displaced). `cells` is exactly what this net
    claimed on the grid, which is what Grid.release() needs to un-route it, and
    `displaced` is the nets a probe would have to move out of the way.

    **A failed hop releases the hops that succeeded**, so a net is either
    entirely routed or entirely absent. A half-routed net leaves copper on the
    board with no matching entry in `placed`, which is a piece of track nothing
    can ever rip up and nothing can ever account for.
    """
    crossable = crossable or {}
    tracks, vias, cells, displaced = [], [], [], set()
    first = access[(net, entries[0][0], entries[0][1])]
    reached = {(layer, first[0], first[1]) for layer in entries[0][4]}
    for x, y, _, _, layers in entries[1:]:
        column, row = access[(net, x, y)]
        targets = {(layer, column, row) for layer in layers}
        path = grid.route(net, reached, targets, crossable)
        if path is None:
            grid.release(cells)
            return None
        runs, path_vias = segments(grid, path)
        tracks.extend((net, layer, points) for layer, points in runs)
        vias.extend((net, point) for point in path_vias)
        reached.update(path)
        for layer, cell_column, cell_row in path:
            if (layer, cell_column, cell_row) in crossable:
                displaced.add(crossable[(layer, cell_column, cell_row)])
            if claim:
                grid.take(layer, cell_column, cell_row, net)
                cells.append((layer, cell_column, cell_row))
        # A via is wider than a track: its neighbours have to go too, or a
        # track one pitch away is inside the clearance with both centres
        # legally placed. This is the rule the grid cannot express.
        for point in path_vias:
            column, row = grid.cell_of(*point)
            if claim:
                grid.placed_vias[(column, row)] = net
            for dc, dr in grid.via_ring():
                for layer in LAYERS:
                    spot = (layer, column + dc, row + dr)
                    if spot in crossable:
                        displaced.add(crossable[spot])
                    if claim and grid.free(layer, column + dc, row + dr, None):
                        grid.take(layer, column + dc, row + dr, net)
                        cells.append(spot)
    return tracks, vias, cells, displaced


def _one_pass(rect, pads, obstacles, rules, skip, first, reserve=None,
              escapes=None, no_via=()):
    """Route every net once, on a clean grid, in an order this pass is given.

    `first` is the nets to attempt before the rest; everything else follows in
    the size order below. Returns tracks, vias and the nets missed, in the
    order they were missed -- which is what the next pass promotes.
    """
    escapes = escapes or {}
    grid = Grid(rect, rules["pitch"], rules["track"], rules["clearance"],
                rules["via"], rules.get("via_reach"))
    grid.block_edge(rules["edge"])
    if reserve:
        grid.reserve(*reserve[0], reserve[1])

    # Pads block, on the front layer where they are, under the name of
    # whatever net they carry -- and **the ones carrying no net block hardest**.
    # The first routed board left them out of the grid entirely, because they
    # are not in design.NETS, and the router drove tracks straight across the
    # spare op-amp sections' pins: 199 shorting items and 200 mask bridges from
    # one missing line. A pad with no net is not an absence, it is copper.
    # **A pad is on the layers it is on, and that is not always the front.**
    # Blocking every pad on F.Cu alone did three things at once: back-side
    # tracks ran through the connectors' through-hole pads; routes started on
    # B.Cu at an SMD pad with no via under them, which is 191 tracks with an
    # unconnected end; and two nets could own the same back-side cell, because
    # neither had ever claimed it. One line, three fault classes.
    # **Copper first, for every pad, and only then the rings.** Pad by pad, the
    # ring of one pin marks the copper of the next one "blocked", because two
    # SOIC pins are closer together than one clearance ring is wide.
    for stage in (Grid.block_pad_copper, Grid.block_pad_ring):
        for net, entries in pads.items():
            owner = net if net else "blocked"
            for x, y, half_w, half_h, layers in entries:
                for layer in layers:
                    stage(grid, layer, x - half_w, y - half_h, x + half_w,
                          y + half_h, owner)
    # And the via keep-out, which is not per layer -- see block_pad_for_vias().
    for net, entries in pads.items():
        owner = net if net else "blocked"
        for x, y, half_w, half_h, _ in entries:
            grid.block_pad_for_vias(x - half_w, y - half_h, x + half_w,
                                    y + half_h, owner)
    for layers, x, y, half_w, half_h in obstacles:
        for layer in layers:
            grid.block_box(layer, x - half_w, y - half_h, x + half_w,
                           y + half_h, "blocked")
    # Plated holes, which are a via keep-out and not a clearance -- see
    # Grid.block_no_via().
    for x0, y0, x1, y1 in no_via:
        grid.block_no_via(x0, y0, x1, y1)

    # **The big nets go first and the small ones after**, which is the opposite
    # of the usual advice and is what this board wants. VA+ and VA- have
    # twenty-five pads each, spread over ten packages and a decoupling row, and
    # a net like that routed last has to reach every one of them through a
    # board that is already full. A two-pad net 4 mm long has alternatives; a
    # rail spanning 180 mm does not. Shortest-first left 21 nets unrouted, most
    # of them rails.
    #
    # `first` overrides that for the nets a previous pass could not finish, and
    # it is what route_all()'s outer loop has to say.
    rank = {net: index for index, net in enumerate(first)}
    order = sorted((net for net in pads
                    if net and net not in skip and len(pads[net]) > 1),
                   key=lambda net: (rank.get(net, len(rank)), -len(pads[net]),
                                    net))

    # **The fan-out, and it goes down before anything is routed.** A pad whose
    # every grid offset fails rules.track_offset_limit() cannot be entered by
    # the router at all -- there is no cell it can start a track on without
    # that track's own copper coming inside the clearance of the next pin
    # along. What a person drawing this by hand does instead is lay the escape
    # first, on the pad's own centre line, and pick the grid up outside the
    # package; this is that, and gen_pcb.fan_out() is what measures which pads
    # need it.
    #
    # It is the same shape as stitch_grounds() handing its 133 vias over as
    # `obstacles`, with one difference that decides the whole design: ground
    # stitching is *finished* copper and the router only has to keep away from
    # it, while an escape is copper the router has to **continue from**. So it
    # cannot be an obstacle. It is blocked in the two stages a pad is -- its
    # own cell as `copper`, then its halo as a ring -- and the cell it lands on
    # becomes that pad's entry in `access`, which is the one place the router
    # ever joins a net to a pad.
    #
    # An escape that cannot be laid legally is refused rather than laid
    # anyway, and its net is reported by name. That is the same rule the rest
    # of this file runs on: a router that gives up and says so beats one that
    # trades violations for finished connections.
    # **Which pads need one is route.access()'s own answer, not a prediction.**
    # The first version of this asked the arithmetic directly -- offset against
    # rules.track_offset_limit() -- and got two things wrong that are the same
    # thing: it measured from the pad's *centre line*, which is the only
    # candidate a narrow pad has and one of a hundred that U16's DPAK tab has,
    # so it declared the 5 V regulator's tab unreachable and refused its
    # escape. A criterion computed beside the function it is meant to agree
    # with is a second opinion, and the second opinion was wrong.
    #
    # access() already returns None for exactly the pads that have no legal
    # entry, for exactly the reason rules.track_offset_limit() states -- no
    # cell inside the pad, and _stub_is_clear() refusing the one outside it --
    # and it runs before any track is laid, so its answer is a property of the
    # placement rather than of the routing order.
    #
    # **The pre-pass is not tidiness either.** An escape's halo blocks cells,
    # so an escape laid part-way through the access loop can block a cell
    # already handed to a net that was assigned earlier -- and _connect() takes
    # its source and target cells as given rather than re-testing them, so
    # nothing downstream would notice. Every escape goes down before any pad is
    # assigned.
    needy = []
    for net in order:
        for x, y, half_w, half_h, layers in _order(pads[net]):
            if grid.access(min(layers), x, y, half_w, half_h, net) is None:
                needy.append((net, x, y, min(layers)))

    fitted, laid, refused, escaped = {}, [], {}, []
    for net, x, y, layer in needy:
        out = escapes.get((net, x, y))
        if out is None:
            refused[net] = (f"no escape plan for the pad at "
                            f"({x:.4f}, {y:.4f}) -- see "
                            f"gen_pcb.escape_plan()")
            continue
        cell, points = grid.escape((x, y), out)
        if cell is None:
            refused[net] = "the escape runs off the board"
            continue
        problems = escape_clearances(points, net, layer, pads, obstacles, laid,
                                    grid.track, grid.clearance)
        blocked = [(column, row) for column, row in grid.escape_cells(points)
                   if not grid.free(layer, column, row, net)]
        if blocked:
            problems.append(f"{len(blocked)} of the cells it lands on are not "
                            f"free to {net}")
        if problems:
            refused[net] = "; ".join(sorted(set(problems))[:3])
            continue
        laid.append((net, layer, points))
        fitted[(net, x, y)] = (layer, cell, points)
        escaped.append((net, x, y) + grid.point_of(*cell))
    for net, layer, points in laid:
        grid.block_escape_copper(layer, points, net)
    for net, layer, points in laid:
        grid.block_escape_ring(layer, points, net)

    # **Every pad gets a stub from its own centre to its access cell**, and the
    # reason is that a pad is not on the grid. cell_of() rounds, so the nearest
    # cell is up to 0.35 mm away, and the first routed board ended with 173
    # dangling tracks: routes that reached the right cell and stopped short of
    # the copper. The stub is inside the pad's own halo, so it can cross
    # nothing, and it is never ripped up -- it is a property of the pad, not of
    # any route.
    tracks, vias, missed = [], [], []
    unreachable, access, ordered = set(), {}, {}
    unreachable.update(refused)
    for net in order:
        ordered[net] = entries = _order(pads[net])
        if net in unreachable:
            continue
        for x, y, half_w, half_h, layers in entries:
            escape = fitted.get((net, x, y))
            if escape is not None:
                layer, cell, points = escape
                access[(net, x, y)] = cell
                tracks.append((net, layer, points))
                continue
            cell = grid.access(min(layers), x, y, half_w, half_h, net)
            if cell is None:
                unreachable.add(net)
                break
            access[(net, x, y)] = cell
            spot = grid.point_of(*cell)
            if spot != (x, y):
                tracks.append((net, min(layers), [(x, y), spot]))
    missed.extend(net for net in order if net in unreachable)

    # Nothing has been routed yet, so this is the grid that ripping up restores
    # to. It must be taken after every pad, every ring and every obstacle and
    # before the first track.
    grid.freeze()

    routed, placed, rips = {}, {}, {}
    queue = [net for net in order if net not in unreachable]
    while queue:
        net = queue.pop(0)
        result = _connect(grid, net, ordered[net], access)
        if result is None:
            # **Ask what is in the way, then move it.** The probe re-runs the
            # same search with every routed net's copper passable at
            # RIPUP_COST; what comes back is not a route -- it may run straight
            # through three other nets -- it is the list of nets whose copper
            # would have to go. They are ripped, re-queued, and the route is
            # attempted again on a grid where the space genuinely is free.
            #
            # Nothing is ever laid down from a probe, which is the invariant
            # that keeps this from producing a short: `claim=False` and the
            # only thing kept is `displaced`.
            crossable = {cell: other
                         for other, cells in placed.items()
                         if other != net and rips.get(other, 0) < RIPUP_LIMIT
                         for cell in cells}
            probe = _connect(grid, net, ordered[net], access, crossable,
                             claim=False)
            if probe is not None and probe[3]:
                for other in sorted(probe[3]):
                    grid.release(placed.pop(other))
                    routed.pop(other, None)
                    rips[other] = rips.get(other, 0) + 1
                    queue.append(other)
                result = _connect(grid, net, ordered[net], access)
        if result is None:
            missed.append(net)
            continue
        net_tracks, net_vias, cells, _ = result
        routed[net] = (net_tracks, net_vias)
        placed[net] = cells

    for net in order:
        if net in routed:
            net_tracks, net_vias = routed[net]
            tracks.extend(net_tracks)
            vias.extend(net_vias)
    seen, ordered_misses = set(), []
    for net in missed:
        if net not in seen and net not in routed:
            seen.add(net)
            ordered_misses.append(net)
    return tracks, vias, ordered_misses, refused, escaped


# How many times the whole board may be routed from scratch, each pass a
# complete legal route in a different order. **This board finishes on the
# first**, so the number is a fallback rather than a mechanism -- see
# route_all() for the measurement that demoted it, and note that the loop stops
# the moment a pass finishes, so three unused passes cost nothing.
RETRY_PASSES = 4


def route_all(rect, pads, obstacles, rules, skip=(), reserve=None,
              escapes=None, no_via=()):
    """Route every net in `pads`. Returns tracks, vias and what was missed.

    `pads` is {net: [(x, y, half_width, half_height, layers), ...]} in
    millimetres and
    `obstacles` is [(layers, x, y, half_width, half_height)] for copper that
    belongs to nobody the router may route -- **which is where the ground
    stitching goes.** Skipping the two ground nets is not the same as their
    copper not being there: 104 vias and 104 stubs are on the board before this
    runs, and the first routed version was not told, so tracks went through
    them. 198 shorts, every one against a ground via.

    `skip` is the nets that reach their copper another way.

    **Rip-up and retry, which this file used to say it did not do.** The
    twenty-three nets it could not finish were left as a choice between that
    and a finer grid on thinner track. The finer grid is priced in
    rules.escape_corridor() and refused: no legal pitch at any class this board
    would order puts a cell between two SOIC pins, and the one that would costs
    a copper weight. So the answer was the routing side, and it took two goes
    to find the right instrument.

    **Reordering was the first go, and it is worth keeping because it is a
    good-looking wrong answer.** Rip up the whole board, route it again with
    the nets that failed promoted to the front, keep the best result: every
    pass is a complete legal route on a clean grid, so nothing can short, and
    it needs no bookkeeping at all. It works, up to a point -- 19 nets, then 7,
    then 3 -- and then it random-walks: 8, 7, 3, 2, 2, 0 for one board, and for
    the board that exists after J8 moved, twenty passes hovering between 1 and
    8 without ever closing. The reason is visible once stated. Promoting the
    nets that failed remembers *who* lost and nothing about *where*, and after
    a few passes almost every net has lost once, so the order it produces is
    close to arbitrary. Both promotion rules that were tried -- most recent
    first, and most often first -- have the same defect and differ only in how
    long they take to develop it. RETRY_PASSES is what is left of it, and it is
    a fallback now.

    **What works is displacing the nets that are actually in the way**, which
    is rip-up as the literature means it. When a route fails, the same search
    runs again with every routed net's copper passable at RIPUP_COST; the
    probe's path names the nets whose copper is in the way; those are ripped
    up, put back on the queue, and the route is tried again on a grid where
    the space is genuinely free. It finishes this board on the first pass, in
    a fifth of the time twelve reordering passes took, with nothing missed.

    **The ledger objection that had ruled this out dissolves in one line.**
    Ripping one net must not un-route the net that took its place, which
    sounds like it needs a per-claim record of what every cell was before every
    claim -- and a wrong record there is a grid that disagrees with the copper,
    which is a short, which is the one thing this router must never produce.
    But nothing needs to be remembered: a cell being released goes back to what
    *blocking* said, and blocking is a constant. Grid.freeze() takes that
    snapshot once, and Grid.release() is three lines. The difficulty was
    entirely in having framed the question as "what was here before" instead of
    "what is here when nothing is routed".

    Two invariants carry the safety, and they are worth stating because they
    are what stand in for the ledger:

      * **a probe never lays anything down.** `claim=False`, and the only thing
        kept from it is the set of displaced nets -- the path it found runs
        through other people's copper and is thrown away;
      * **a net is entirely routed or entirely absent.** _connect() releases
        its own cells if a later hop fails, so `placed` and the copper always
        describe the same board.

    check_no_shorts() is the assertion that both held, and it runs on every
    build.
    """
    best = None
    first, tally = [], {}
    for _ in range(RETRY_PASSES):
        result = _one_pass(rect, pads, obstacles, rules, skip, first, reserve,
                           escapes, no_via)
        if best is None or len(result[2]) < len(best[2]):
            best = result
        if not result[2]:
            break
        for net in result[2]:
            tally[net] = tally.get(net, 0) + 1
        # Sorted by name within a count, so a pass is reproducible: two runs of
        # this file on one board must lay down the same copper.
        first = [net for net, _ in sorted(tally.items(),
                                          key=lambda item: (-item[1], item[0]))]
    return best[0], best[1], sorted(best[2]), best[3], best[4]


def check_no_shorts(tracks, vias, pitch):
    """No two nets occupy the same point. The router's own invariant.

    A maze router cannot short two nets if its grid bookkeeping is right, so
    this is not defence in depth -- it is the assertion that the bookkeeping
    *is* right, made cheaply enough to run on every build. DRC says the same
    thing about the finished board; this says it about the thing that produced
    it, which is the difference between finding out that a board is wrong and
    finding out which line made it wrong.
    """
    seen = {}
    problems = []
    for net, layer, points in tracks:
        for x, y in points:
            key = (layer, round(x / pitch), round(y / pitch))
            if seen.setdefault(key, net) != net:
                problems.append(
                    f"{net} and {seen[key]} share a point at {(x, y)} on "
                    f"layer {layer}")
    for net, (x, y) in vias:
        for layer in LAYERS:
            key = (layer, round(x / pitch), round(y / pitch))
            if seen.setdefault(key, net) != net:
                problems.append(
                    f"via on {net} lands on {seen[key]} at {(x, y)}")
    return problems
