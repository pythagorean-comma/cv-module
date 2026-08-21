"""Read symbols out of KiCad's stock libraries.

Two jobs. First, flatten a symbol into a self-contained definition, because a
schematic's `lib_symbols` block cannot rely on a parent that lives in some
other file -- and a lot of the stock parts are derived (CD4066BM extends
CD4066BE). Second, report where each pin's connection point sits, so wires can
be drawn to real coordinates instead of guessed ones.
"""

import copy

from . import kicad
from .sexp import Sym, find, find_all, parse

SYMBOL_DIR = kicad.SYMBOL_DIR
FOOTPRINT_DIR = kicad.FOOTPRINT_DIR

_library_cache = {}


def _library(name):
    """Parse a .kicad_sym file once and keep it around."""
    if name not in _library_cache:
        path = SYMBOL_DIR / f"{name}.kicad_sym"
        _library_cache[name] = parse(path.read_text())
    return _library_cache[name]


def _raw_symbol(libname, symname):
    for sym in find_all(_library(libname), "symbol"):
        if sym[1] == symname:
            return sym
    raise KeyError(f"{libname}:{symname} not found")


def _properties(symbol):
    return {p[1]: p[2] for p in find_all(symbol, "property")}


def flatten(libname, symname, rename=None):
    """Return a self-contained copy of a symbol, resolving `extends`.

    `rename` gives the flattened symbol a new name; its unit sub-symbols are
    renamed to match, which KiCad requires (unit bodies must be called
    <symbol>_<unit>_<style>).

    **"Copy" was a claim this function did not honour, and it took two lib_ids
    borrowing one symbol to find out.** Every list built below is shallow --
    `[x for x in symbol[2:]]` copies the outer list and shares every unit body,
    and a unit body is where the pins are. So a caller that renumbers a pin on
    a flattened symbol renumbers it inside `_library_cache`, and the *next*
    flatten of the same source returns the mutated one.

    Nothing showed for as long as each borrowed symbol had one borrower. The
    day cv-module borrowed Device:D twice -- once as itself and once as a
    SOT-23 BAT54 with its pins renumbered onto the package -- the generic diode
    lost pin 2, and six envelope rectifier diodes drawn with it failed with a
    KeyError. That is the good version of this failure: it stopped the build.
    The bad version is a repin or a property edit, which mutates the cache just
    as silently and changes a symbol somebody else is using.

    A deep copy, taken before anything is merged, so the cache is read-only to
    every caller by construction rather than by everybody remembering.
    """
    symbol = copy.deepcopy(_raw_symbol(libname, symname))
    parent_ref = find(symbol, "extends")

    if parent_ref is None:
        merged = [x for x in symbol[2:]]
        own_properties = {}
    else:
        parent = copy.deepcopy(_raw_symbol(libname, parent_ref[1]))
        # Take the parent's body (units, pin_names, flags) but let the child's
        # properties win -- that is exactly what `extends` means.
        merged = [x for x in parent[2:] if not (isinstance(x, list) and str(x[0]) == "property")]
        own_properties = _properties(symbol)
        parent_properties = _properties(parent)
        parent_properties.update(own_properties)
        props = [p for p in find_all(parent, "property")]
        rebuilt = []
        for p in props:
            p = [x for x in p]
            p[2] = parent_properties.get(p[1], p[2])
            rebuilt.append(p)
        for key, value in own_properties.items():
            if key not in parent_properties or all(p[1] != key for p in props):
                rebuilt.append([Sym("property"), key, value, [Sym("at"), 0, 0, 0],
                                [Sym("hide"), Sym("yes")]])
        merged = rebuilt + merged

    new_name = rename or symname
    out = [Sym("symbol"), new_name]
    source_name = parent_ref[1] if parent_ref is not None else symname
    for item in merged:
        if isinstance(item, list) and str(item[0]) == "symbol":
            item = [x for x in item]
            item[1] = str(item[1]).replace(source_name, new_name, 1)
        out.append(item)

    # Keep Value in step with the new name, or the schematic shows the old part.
    for item in out:
        if isinstance(item, list) and str(item[0]) == "property" and item[1] == "Value":
            item[2] = new_name
    return out


def pins(symbol):
    """Map pin number -> (x, y, unit) in symbol-local millimetres.

    Symbol space has Y increasing upwards; the schematic writer flips it.
    """
    found = {}
    for unit_body in find_all(symbol, "symbol"):
        # Unit bodies are named <symbol>_<unit>_<bodystyle>.
        parts = str(unit_body[1]).rsplit("_", 2)
        unit = int(parts[1]) if len(parts) == 3 and parts[1].isdigit() else 1
        for pin in find_all(unit_body, "pin"):
            at = find(pin, "at")
            number = find(pin, "number")[1]
            found[number] = (float(at[1]), float(at[2]), unit)
    return found


def properties(libname, symname):
    return _properties(_raw_symbol(libname, symname))
