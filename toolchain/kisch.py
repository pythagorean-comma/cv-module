"""Build a KiCad schematic file.

Enough of eeschema's format to emit a real, openable, ERC-clean sheet: placed
symbols, drawn wires, junctions, global labels and power symbols. Coordinates
come from the stock symbol libraries via symlib, so wires land exactly on pin
connection points rather than on guessed offsets.

UUIDs are derived from a name hash rather than randomly, so regenerating the
project produces a byte-identical file and git diffs stay meaningful.
"""

import math
import uuid

from . import symlib
from .sexp import Sym, dumps

NAMESPACE = uuid.UUID("6f1a41d2-0f5c-5a4e-9a1c-2b7f9d3e4c58")
SCH_VERSION = 20250610  # KiCad 10's schematic format; 9.x used 20250114
GRID = 1.27             # eeschema's connection grid, 50 mil


def _uuid(key):
    return str(uuid.uuid5(NAMESPACE, key))


def _round(value):
    # Connectivity is decided by exact coordinate equality, so every number
    # that reaches the file goes through here.
    return round(value + 0.0, 2)


def _effects(size=1.27, hide=False, justify=None):
    font = [Sym("font"), [Sym("size"), size, size]]
    out = [Sym("effects"), font]
    if justify:
        out.append([Sym("justify"), Sym(justify)])
    if hide:
        out.append([Sym("hide"), Sym("yes")])
    return out


class Part:
    """A placed symbol instance."""

    def __init__(self, ref, lib_id, value, footprint, at, angle, mirror, unit, pin_map, extra):
        self.ref = ref
        self.lib_id = lib_id
        self.value = value
        self.footprint = footprint
        self.at = at
        self.angle = angle
        self.mirror = mirror
        self.unit = unit
        self.pin_map = pin_map
        self.extra = extra or {}

    def drawn_pins(self):
        """(number, position) for the pins this unit actually draws.

        Multi-unit symbols carry every pin in pin_map; only those belonging
        to the placed unit -- plus unit 0, which is common to all units --
        appear on the sheet and can make a connection.
        """
        return [(number, self.pin(number))
                for number, (_, _, unit) in self.pin_map.items()
                if unit in (0, self.unit)]

    def pin(self, number):
        """Absolute schematic coordinates of a pin's connection point."""
        px, py, _ = self.pin_map[str(number)]
        if self.mirror == "y":
            px = -px
        elif self.mirror == "x":
            py = -py
        # Symbol space has +Y up, the sheet has +Y down.
        u, v = px, -py
        a = math.radians(self.angle)
        cos_a, sin_a = math.cos(a), math.sin(a)
        x = self.at[0] + u * cos_a + v * sin_a
        y = self.at[1] - u * sin_a + v * cos_a
        return (_round(x), _round(y))


class Schematic:
    def __init__(self, project, title="", rev="", company="", date="", paper="A2"):
        self.project = project
        self.title = title
        self.rev = rev
        self.company = company
        self.date = date
        self.paper = paper
        self.uuid = _uuid(f"{project}:root")
        self.lib_symbols = {}
        self.parts = []
        self.wires = []
        self.labels = []
        self.junctions = []
        self.no_connects = []
        self.texts = []
        self._power_index = 0

    # -- library ---------------------------------------------------------
    def use(self, nick, libname, symname, rename=None, patch=None):
        """Register a symbol under `nick:name` and return its pin geometry.

        `patch` may rewrite properties; the same callback must be used when
        writing the project library or ERC flags the copies as mismatched.
        """
        name = rename or symname
        lib_id = f"{nick}:{name}"
        if lib_id not in self.lib_symbols:
            definition = symlib.flatten(libname, symname, rename=rename)
            definition = [x for x in definition]
            if patch:
                definition = patch(lib_id, definition)
            # Only the outer symbol carries the "lib:name" form; its unit
            # bodies keep the bare name, which is what KiCad expects.
            definition[1] = lib_id
            self.lib_symbols[lib_id] = definition
        return symlib.pins(self.lib_symbols[lib_id])

    # -- placement -------------------------------------------------------
    def place(self, ref, lib_id, value, x, y, footprint="", angle=0,
              mirror=None, unit=1, extra=None):
        pin_map = symlib.pins(self.lib_symbols[lib_id])
        part = Part(ref, lib_id, value, footprint, (_round(x), _round(y)),
                    angle, mirror, unit, pin_map, extra)
        self.parts.append(part)
        return part

    def power(self, lib_id, x, y, angle=0, value=None):
        """Place a power symbol (GNDA, PWR_FLAG...) and return it.

        A power symbol names its net after its Value field, so `value` is how
        a stock GNDA symbol comes to drive a net called AGND.
        """
        self._power_index += 1
        ref = f"#PWR{self._power_index:03d}"
        return self.place(ref, lib_id, value or lib_id.split(":", 1)[1],
                          x, y, angle=angle)

    # -- connectivity ----------------------------------------------------
    def wire(self, *points):
        """Draw a polyline. Points are (x, y) tuples; segments are emitted
        pairwise, which is what eeschema stores."""
        pts = [(_round(px), _round(py)) for px, py in points]
        for a, b in zip(pts, pts[1:]):
            if a != b:
                self.wires.append((a, b))

    def label(self, name, x, y, angle=0, shape="input"):
        self.labels.append((name, (_round(x), _round(y)), angle, shape))

    def no_connect(self, x, y):
        self.no_connects.append((_round(x), _round(y)))

    def text(self, body, x, y, size=1.27):
        self.texts.append((body, (_round(x), _round(y)), size))

    def auto_junctions(self):
        """Add a junction dot wherever three or more wire ends meet, or where
        a wire end lands in the middle of another wire.

        eeschema infers connectivity from geometry, but a crossing without a
        dot is deliberately *not* a connection, so getting this right is what
        makes the drawing mean what the netlist says.
        """
        ends = {}
        for a, b in self.wires:
            ends[a] = ends.get(a, 0) + 1
            ends[b] = ends.get(b, 0) + 1

        pin_points = {}
        for part in self.parts:
            for number, position in part.drawn_pins():
                pin_points.setdefault(position, []).append(f"{part.ref}.{number}")

        # Two different net names at one coordinate is one net, silently.
        #
        # A global label and a power symbol are both just a name attached to a
        # point. Land them on the same point -- by a placement arithmetic slip,
        # or because a row pitch happens to equal a drop length -- and KiCad
        # merges the nets without a word. Everything downstream still passes:
        # the sheet opens, ERC is clean, the netlist is well-formed. It is
        # simply a different circuit.
        #
        # This cost two rounds on the simulation sheet. Ground was dropped one
        # channel pitch below each row, which put it exactly on the next
        # channel's input label, and the whole ground net became IN2 -- the
        # netlist showed a bleed resistor as "R290 IN2 IN2", shorted end to
        # end. Moving the pitch put channel 6's ground on the V+ rail label
        # instead. Neither was visible on the drawing.
        named = {}
        for name, point, _, _ in self.labels:
            named.setdefault(point, set()).add(name)
        for part in self.parts:
            if part.ref.startswith("#PWR"):
                for _, position in part.drawn_pins():
                    named.setdefault(position, set()).add(part.value)
        collisions = [f"{point}: {sorted(names)}"
                      for point, names in sorted(named.items()) if len(names) > 1]
        if collisions:
            raise ValueError(
                "different net names share a coordinate, which silently merges "
                "them:\n  " + "\n  ".join(collisions))

        # KiCad connects a pin sitting on a wire *end*, but not one sitting
        # part-way along a wire -- that silently drops the connection, so
        # refuse to emit a sheet containing one.
        stranded = []
        for position, owners in pin_points.items():
            if position in ends:
                continue
            for a, b in self.wires:
                if _on_segment(position, a, b):
                    stranded.append(f"{'/'.join(owners)} at {position} lies "
                                    f"mid-wire between {a} and {b}")
                    break
        if stranded:
            raise ValueError("pins not on a wire end:\n  " + "\n  ".join(stranded))

        # eeschema's connection grid is 50 mil. Anything off it still draws,
        # but ERC flags every endpoint and the sheet becomes hard to edit by
        # hand afterwards, so treat it as an error here.
        off_grid = []
        for point in sorted(set(ends) | set(pin_points)):
            for value in point:
                if abs(value / GRID - round(value / GRID)) > 1e-6:
                    owners = pin_points.get(point) or ["wire end"]
                    off_grid.append(f"{point} ({'/'.join(owners)})")
                    break
        if off_grid:
            raise ValueError(f"{len(off_grid)} points off the {GRID} mm grid:\n  "
                             + "\n  ".join(off_grid[:20]))

        points = set()
        for point, count in ends.items():
            if count + len(pin_points.get(point, ())) >= 3:
                points.add(point)

        # A T-junction: one wire terminates part-way along another.
        for point in ends:
            for a, b in self.wires:
                if point in (a, b):
                    continue
                if _on_segment(point, a, b):
                    points.add(point)
                    break

        self.junctions = sorted(points)

    # -- output ----------------------------------------------------------
    def _symbol_node(self, part):
        x, y = part.at
        node = [Sym("symbol"),
                [Sym("lib_id"), part.lib_id],
                [Sym("at"), x, y, part.angle]]
        if part.mirror:
            node.append([Sym("mirror"), Sym(part.mirror)])
        node += [[Sym("unit"), part.unit],
                 [Sym("exclude_from_sim"), Sym("no")],
                 # A symbol that is on the board and not in the bill of
                 # materials, which is a real category and was not expressible
                 # here. Mounting holes, test pads and fiducials are features
                 # of the fabrication rather than parts to buy, and a panel
                 # control on flying leads is a part to buy that is not a
                 # placement -- and all four went into the BOM an assembly
                 # house quotes and orders from, looking exactly like the
                 # components beside them.
                 #
                 # Defaults to yes, so a design that says nothing gets what it
                 # got before.
                 [Sym("in_bom"),
                  Sym("no" if part.extra.get("in_bom") is False else "yes")],
                 [Sym("on_board"), Sym("yes")],
                 [Sym("dnp"), Sym("yes" if part.extra.get("dnp") else "no")],
                 [Sym("uuid"), _uuid(f"{self.project}:part:{part.ref}:{part.unit}")]]

        hidden_ref = part.ref.startswith("#")
        # Reference and value sit clear of the body; the exact offsets only
        # matter for looks, and these keep multi-unit parts legible.
        node.append([Sym("property"), "Reference", part.ref,
                     [Sym("at"), x, _round(y - 6.35), 0],
                     _effects(hide=hidden_ref, justify="left")])
        node.append([Sym("property"), "Value", part.value,
                     [Sym("at"), x, _round(y + 6.35), 0],
                     _effects(hide=hidden_ref, justify="left")])
        node.append([Sym("property"), "Footprint", part.footprint,
                     [Sym("at"), x, y, 0], _effects(size=0.762, hide=True)])
        node.append([Sym("property"), "Datasheet", part.extra.get("datasheet", "~"),
                     [Sym("at"), x, y, 0], _effects(hide=True)])
        for key, value in part.extra.items():
            if key in ("dnp", "datasheet", "in_bom"):
                continue
            node.append([Sym("property"), key, value,
                         [Sym("at"), x, y, 0], _effects(hide=True)])
        for number in sorted(part.pin_map, key=lambda n: (len(n), n)):
            node.append([Sym("pin"), number,
                         [Sym("uuid"), _uuid(f"{self.project}:pin:{part.ref}:{part.unit}:{number}")]])
        node.append([Sym("instances"),
                     [Sym("project"), self.project,
                      [Sym("path"), f"/{self.uuid}",
                       [Sym("reference"), part.ref],
                       [Sym("unit"), part.unit]]]])
        return node

    def render(self):
        root = [Sym("kicad_sch"),
                [Sym("version"), SCH_VERSION],
                # The project's own name, not a literal. Both siblings hard-code
                # one here and rmc-pizz-arco's still says "violet-bridge" -- a
                # different project entirely. Deriving it is what lets this file
                # be copied between repos unchanged, which is the whole premise
                # of the shared infrastructure.
                [Sym("generator"), self.project],
                [Sym("generator_version"), "10.0"],
                [Sym("uuid"), self.uuid],
                [Sym("paper"), self.paper]]

        title_block = [Sym("title_block")]
        if self.title:
            title_block.append([Sym("title"), self.title])
        if self.date:
            title_block.append([Sym("date"), self.date])
        if self.rev:
            title_block.append([Sym("rev"), self.rev])
        if self.company:
            title_block.append([Sym("company"), self.company])
        if len(title_block) > 1:
            root.append(title_block)

        lib = [Sym("lib_symbols")]
        for lib_id in sorted(self.lib_symbols):
            lib.append(self.lib_symbols[lib_id])
        root.append(lib)

        for index, (a, b) in enumerate(self.wires):
            root.append([Sym("wire"),
                         [Sym("pts"), [Sym("xy"), a[0], a[1]], [Sym("xy"), b[0], b[1]]],
                         [Sym("stroke"), [Sym("width"), 0], [Sym("type"), Sym("default")]],
                         [Sym("uuid"), _uuid(f"{self.project}:wire:{index}:{a}:{b}")]])

        for point in self.junctions:
            root.append([Sym("junction"),
                         [Sym("at"), point[0], point[1]],
                         [Sym("diameter"), 0],
                         [Sym("color"), 0, 0, 0, 0],
                         [Sym("uuid"), _uuid(f"{self.project}:junction:{point}")]])

        for point in self.no_connects:
            root.append([Sym("no_connect"),
                         [Sym("at"), point[0], point[1]],
                         [Sym("uuid"), _uuid(f"{self.project}:nc:{point}")]])

        for name, point, angle, shape in self.labels:
            justify = "left" if angle in (0, 90) else "right"
            root.append([Sym("global_label"), name,
                         [Sym("shape"), Sym(shape)],
                         [Sym("at"), point[0], point[1], angle],
                         [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]],
                          [Sym("justify"), Sym(justify)]],
                         [Sym("uuid"), _uuid(f"{self.project}:label:{name}:{point}")]])

        for body, point, size in self.texts:
            root.append([Sym("text"), body,
                         [Sym("at"), point[0], point[1], 0],
                         _effects(size=size, justify="left"),
                         [Sym("uuid"), _uuid(f"{self.project}:text:{point}:{body[:20]}")]])

        for part in self.parts:
            root.append(self._symbol_node(part))

        root.append([Sym("sheet_instances"), [Sym("path"), "/", [Sym("page"), "1"]]])
        root.append([Sym("embedded_fonts"), Sym("no")])
        return dumps(root) + "\n"

    def save(self, path):
        path.write_text(self.render())


def _on_segment(point, a, b):
    """True if `point` lies strictly between a and b on an axis-aligned wire."""
    (px, py), (ax, ay), (bx, by) = point, a, b
    if ax == bx == px:
        return min(ay, by) < py < max(ay, by)
    if ay == by == py:
        return min(ax, bx) < px < max(ax, bx)
    return False
