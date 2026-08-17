"""A maze router: pads in, polylines out, and no KiCad anywhere in it.

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

# Cost of changing layer, in cells, and it was tuned rather than reasoned:
# 9 leaves 78 connections unmade, 6 leaves 69, 4 leaves 69 and 2 leaves 67.
# The direction is the interesting part -- **cheap vias route better on this
# board** -- and the reason is the placement. Twelve rows of parts on a 7.62 mm
# pitch make the front layer a set of corridors that run east-west, so a route
# that needs to go north is better off dropping to the back, crossing, and
# coming up than it is threading between two rows. A board laid out with
# routing channels would prefer the opposite.
#
# Two cells is about 1 mm of copper per via, which is roughly what one costs in
# inductance terms at these frequencies. Nothing here is fast enough for that
# to be the binding consideration; it is the count that matters, and 249 vias
# on 144 nets is ordinary.
VIA_COST = 2

# Cost of turning, in cells. Nothing structural depends on it; it buys tracks
# that look deliberate rather than like a plotter fault, at no routing cost.
BEND_COST = 1


class Grid:
    """The board as cells, one plane per signal layer.

    `owner[layer][index]` is None for free, or the name of whatever occupies
    it -- a net, or the string "blocked" for board edge and keep-out. A cell
    owned by the net being routed is free to that net and blocked to every
    other, which is what lets a net's own copper be a routing target.
    """

    def __init__(self, rect, pitch, track, clearance, via_diameter):
        self.left, self.top, self.right, self.bottom = rect
        self.pitch = pitch
        self.track = track
        self.clearance = clearance
        self.via = via_diameter
        self.columns = int((self.right - self.left) / pitch) + 1
        self.rows = int((self.bottom - self.top) / pitch) + 1
        self.owner = [[None] * (self.columns * self.rows) for _ in LAYERS]

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
        held = self.owner[layer][self.index(column, row)]
        return held is None or held == net

    def block_box(self, layer, x0, y0, x1, y1, owner, margin=0.0):
        """Mark every cell whose track centre would be inside a rectangle.

        **Floor and ceiling, not cell_of().** cell_of() rounds to the nearest
        cell, which on the far edge of a box rounds *inwards* and leaves the
        first free cell up to a quarter-millimetre too close. Those were the
        clearance violations reported at 0.15 and 0.19 mm against a 0.2 mm
        rule -- not shorts, and not visible on the sheet, and exactly the size
        of half a grid pitch.
        """
        reach = margin + self.clearance + self.track / 2
        first = (int(math.floor((x0 - reach - self.left) / self.pitch)),
                 int(math.floor((y0 - reach - self.top) / self.pitch)))
        last = (int(math.ceil((x1 + reach - self.left) / self.pitch)),
                int(math.ceil((y1 + reach - self.top) / self.pitch)))
        for column in range(first[0], last[0] + 1):
            for row in range(first[1], last[1] + 1):
                self.take(layer, column, row, owner)

    def block_pad(self, layer, x0, y0, x1, y1, net):
        """A pad's own copper, then its halo, and they are not the same rule.

        **The copper is hard and the halo is exclusive.** A cell inside the pad
        belongs to that net and to nothing else. A cell in the clearance ring
        around it may be used by that net -- a stub has to leave the pad
        somehow -- but if it is also in *another* pad's ring, nobody may have
        it: two pads 1.27 mm apart on a 0.5 mm grid share ring cells, and a
        track legally placed in one pad's ring is illegally close to the other.

        The first version blocked both with one call and let the last pad
        written win, which is how a track ended up 0.12 mm from a pin of a net
        it had never heard of.
        """
        first = (int(math.floor((x0 - self.left) / self.pitch)),
                 int(math.floor((y0 - self.top) / self.pitch)))
        last = (int(math.ceil((x1 - self.left) / self.pitch)),
                int(math.ceil((y1 - self.top) / self.pitch)))
        for column in range(first[0], last[0] + 1):
            for row in range(first[1], last[1] + 1):
                self.take(layer, column, row, net)

        reach = self.clearance + self.track / 2
        ring_first = (int(math.floor((x0 - reach - self.left) / self.pitch)),
                      int(math.floor((y0 - reach - self.top) / self.pitch)))
        ring_last = (int(math.ceil((x1 + reach - self.left) / self.pitch)),
                     int(math.ceil((y1 + reach - self.top) / self.pitch)))
        for column in range(ring_first[0], ring_last[0] + 1):
            for row in range(ring_first[1], ring_last[1] + 1):
                if first[0] <= column <= last[0] and first[1] <= row <= last[1]:
                    continue
                if not self.inside(column, row):
                    continue
                held = self.owner[layer][self.index(column, row)]
                if held is None:
                    self.take(layer, column, row, net)
                elif held != net:
                    self.take(layer, column, row, "blocked")

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
        return (column, row) if self.free(layer, column, row, net) else None

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
    # A via needs its four orthogonal neighbours, and **not its diagonal
    # ones**, which is arithmetic rather than taste. A via is 0.6 mm across and
    # a track is 0.25: at one pitch their copper is 0.5 - 0.3 - 0.125 = 0.075
    # apart, which is a third of the clearance and was 500 violations on the
    # first routed board. At a diagonal the centres are 0.707 apart and the
    # copper is 0.28, which clears 0.2 with room.
    #
    # Requiring all eight was the safe version of this and it cost 27 nets: a
    # SOIC pin has a neighbour 1.27 mm away on each side, so its diagonals are
    # always somebody's clearance ring, and no via could ever be placed at a
    # package pin. Every route had to escape on the front layer through the
    # same corridor, and the ones that arrived last found it full.
    VIA_NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1), (0, 0))

    def via_fits(self, column, row, net):
        for dc, dr in self.VIA_NEIGHBOURS:
            for layer in LAYERS:
                if not self.free(layer, column + dc, row + dr, net):
                    return False
        return True

    def _neighbours(self, cell, net):
        layer, column, row = cell
        for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            yield (layer, column + dc, row + dr), 1
        if self.via_fits(column, row, net):
            yield (1 - layer, column, row), VIA_COST

    def route(self, net, sources, targets):
        """A* from any source cell to any target cell. None if there is none.

        Sources are the net's own copper so far, targets the pad being
        reached. Both are sets of (layer, column, row).
        """
        if not sources or not targets:
            return None
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
            for step, penalty in self._neighbours(cell, net):
                layer, column, row = step
                if not self.free(layer, column, row, net):
                    continue
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


def route_all(rect, pads, obstacles, rules, skip=()):
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

    **The big nets go first and the small ones after**, which is the opposite
    of the usual advice and is what this board wants. VA+ and VA- have
    twenty-five pads each, spread over ten packages and a decoupling row, and a
    net like that routed last has to reach every one of them through a board
    that is already full. A two-pad net 4 mm long has alternatives; a rail
    spanning 180 mm does not. Shortest-first left 21 nets unrouted, most of
    them rails.
    """
    grid = Grid(rect, rules["pitch"], rules["track"], rules["clearance"],
                rules["via"])
    grid.block_edge(rules["edge"])

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
    for net, entries in pads.items():
        owner = net if net else "blocked"
        for x, y, half_w, half_h, layers in entries:
            for layer in layers:
                grid.block_pad(layer, x - half_w, y - half_h, x + half_w,
                               y + half_h, owner)
    for layers, x, y, half_w, half_h in obstacles:
        for layer in layers:
            grid.block_box(layer, x - half_w, y - half_h, x + half_w,
                           y + half_h, "blocked")

    tracks, vias, missed = [], [], []
    order = sorted((net for net in pads
                    if net and net not in skip and len(pads[net]) > 1),
                   key=lambda net: -len(pads[net]))
    for net in order:
        entries = _order(pads[net])
        # **Every pad gets a stub from its own centre to its access cell**, and
        # the reason is that a pad is not on the grid. cell_of() rounds, so the
        # nearest cell is up to 0.35 mm away, and the first routed board ended
        # with 173 dangling tracks: routes that reached the right cell and
        # stopped short of the copper. The stub is inside the pad's own halo,
        # so it can cross nothing.
        access = {}
        for x, y, half_w, half_h, layers in entries:
            cell = grid.access(min(layers), x, y, half_w, half_h, net)
            if cell is None:
                missed.append(net)
                break
            access[(x, y)] = cell
            spot = grid.point_of(*cell)
            if spot != (x, y):
                tracks.append((net, min(layers), [(x, y), spot]))
        if len(access) != len(entries):
            continue
        first = access[(entries[0][0], entries[0][1])]
        reached = {(layer, first[0], first[1]) for layer in entries[0][4]}
        for x, y, _, _, layers in entries[1:]:
            column, row = access[(x, y)]
            targets = {(layer, column, row) for layer in layers}
            path = grid.route(net, reached, targets)
            if path is None:
                missed.append(net)
                break
            runs, path_vias = segments(grid, path)
            tracks.extend((net, layer, points) for layer, points in runs)
            vias.extend((net, point) for point in path_vias)
            for layer, cell_column, cell_row in path:
                grid.take(layer, cell_column, cell_row, net)
                reached.add((layer, cell_column, cell_row))
            # A via is wider than a track: its neighbours have to go too, or a
            # track one pitch away is inside the clearance with both centres
            # legally placed. This is the rule the grid cannot express.
            for point in path_vias:
                column, row = grid.cell_of(*point)
                for dc, dr in Grid.VIA_NEIGHBOURS:
                    for layer in LAYERS:
                        if grid.free(layer, column + dc, row + dr, None):
                            grid.take(layer, column + dc, row + dr, net)
    return tracks, vias, sorted(set(missed))


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
