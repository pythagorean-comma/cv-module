"""Emit design.py as a KiCad-format netlist.

CLAUDE.md asks for SKiDL here and this does not use it. The reason was given
before any code was written and is repeated where somebody will hit it: the
mixer repo emits and re-reads KiCad s-expressions with its own `sexp.py`, has
no third-party dependencies at all -- its README makes a point of it -- and
`verify.py` there works by reading a netlist back and comparing it to
`design.py` net by net. Adding SKiDL would buy a netlist writer this file is
sixty lines without, and would cost the property that makes the upstream
verification loop possible with nothing installed.

So the s-expression writer is the mixer's own, imported read-only through
contract/socket.py at the pinned commit. Nothing is copied.

The output is `out/cv-module.net` in KiCad's `kicadsexpr` netlist shape, which
is what verify.py reads. It is not loadable by KiCad while any pin is still a
role rather than a number -- see design.check_pin_numbers() -- and the header
says so rather than leaving it to be discovered.
"""

import pathlib

import design
import contract.socket as socket

sexp = socket.MIXER_DESIGN.__dict__.get("sexp")
if sexp is None:                      # design.py does not import it; we do
    import sexp                       # noqa: E402  (MIXER is on the path)

Sym = sexp.Sym
OUT = pathlib.Path(__file__).resolve().parent / "out"
NETLIST = OUT / "cv-module.net"


def components():
    node = [Sym("components")]
    for ref, part in sorted(design.PARTS.items()):
        comp = [Sym("comp"), [Sym("ref"), ref], [Sym("value"), part.value or ""]]
        if part.footprint:
            comp.append([Sym("footprint"), part.footprint])
        if part.mpn:
            comp.append([Sym("property"), "MPN", part.mpn])
        if part.description:
            comp.append([Sym("property"), "Description", part.description])
        comp.append([Sym("property"), "InBOM", Sym("yes" if part.in_bom else "no")])
        node.append(comp)
    return node


def nets():
    node = [Sym("nets")]
    for code, name in enumerate(sorted(design.NETS), start=1):
        net = [Sym("net"), [Sym("code"), code], [Sym("name"), name]]
        for ref, pin in sorted(design.NETS[name]):
            net.append([Sym("node"), [Sym("ref"), ref], [Sym("pin"), pin]])
        node.append(net)
    return node


def document():
    unresolved = design.DESIGN.unresolved_pins()
    return [
        Sym("export"), [Sym("version"), Sym("E")],
        [Sym("design"),
         [Sym("source"), "design.py"],
         [Sym("tool"), "cv-module gen_netlist.py"],
         [Sym("sheet"),
          [Sym("title_block"),
           [Sym("title"), "cv-module: per-string CV, one channel x6"],
           [Sym("comment"), [Sym("number"), 1],
            [Sym("value"), f"mates with summing-mixer @ {socket.PIN[:7]}"]],
           [Sym("comment"), [Sym("number"), 2],
            [Sym("value"),
             f"{len(unresolved)} parts carry pin ROLES not numbers "
             f"(see design.UNSPECIFIED); not loadable by KiCad until resolved"]],
           [Sym("comment"), [Sym("number"), 3],
            [Sym("value"),
             f"deferred blocks: {', '.join(sorted(design.DEFERRED))}"]]]]],
        components(),
        nets(),
    ]


def write():
    OUT.mkdir(exist_ok=True)
    NETLIST.write_text(sexp.dumps(document()) + "\n")
    return NETLIST


if __name__ == "__main__":
    path = write()
    unresolved = design.DESIGN.unresolved_pins()
    print(f"{path.relative_to(path.parent.parent)}: "
          f"{len(design.PARTS)} parts, {len(design.NETS)} nets, "
          f"{sum(len(v) for v in design.NETS.values())} pin connections")
    if unresolved:
        print(f"  {sum(len(v) for v in unresolved.values())} pins are roles "
              f"on {len(unresolved)} unspecified parts: "
              f"{', '.join(sorted(unresolved))}")
    print(f"  deferred: {', '.join(sorted(design.DEFERRED))}")
