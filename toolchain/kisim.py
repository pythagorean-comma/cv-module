"""Annotate a generated schematic so KiCad's built-in simulator can run it.

The mechanics only. What to simulate, and how the sheet is laid out, belongs in
each project's own gen_sim.py -- this file is the part that is the same whatever
the circuit is, and it is copied between repositories unchanged, like kicad.py,
sexp.py and symlib.py.

**There is nothing to install.** KiCad ships ngspice. A sheet carrying the
`Sim.*` fields written here opens in the schematic editor and simulates from
Inspect -> Simulator. See docs/simulating.md for the things that are not code:
the vendor-model licence problem, the convergence options large-signal runs
need, and the two ways a simulation returns confident wrong answers.

Three rules are baked in here rather than left to be rediscovered, because each
one produces a plausible result rather than an error:

  * **Ground is node 0 and nothing else.** ground() returns Simulation_SPICE's
    "0" symbol. A power:GNDA symbol yields a net named AGND, which leaves the
    circuit floating with no reference -- and floating circuits simulate, they
    just answer the wrong question.
  * **Values must be numbers.** These projects write "10k 0.1%", "2u2 film",
    "100p C0G". None of that parses as SPICE. magnitude() reduces both this
    convention and prose's ("10 kΩ", "2.2 µF") to a float.
  * **Large-signal runs need CONVERGENCE_OPTIONS.** Without them a vendor
    macromodel driven into a rail stalls and returns a flat zero, which reads
    exactly like clipping and is not.
"""

import re

# Every simulation sheet needs these, whatever the circuit. Merge into the
# project's own library registry before calling Schematic.use() on each.
#
# Simulation_SPICE is a stock KiCad library of SPICE primitives -- sources,
# behavioural elements, and the ground symbol that actually means node 0.
LIBS = {
    "Simulation_SPICE:0": ("Simulation_SPICE", "Simulation_SPICE", "0", None),
    "Simulation_SPICE:VDC": ("Simulation_SPICE", "Simulation_SPICE", "VDC", None),
    "Simulation_SPICE:VSIN": ("Simulation_SPICE", "Simulation_SPICE", "VSIN", None),
    "Simulation_SPICE:VPULSE": ("Simulation_SPICE", "Simulation_SPICE", "VPULSE", None),
    "Device:R": ("Device", "Device", "R", None),
    "Device:C": ("Device", "Device", "C", None),
}

# Not optional for anything that drives an output near a rail.
#
# TI's macromodels stall when the output is pinned: ngspice reports "Timestep
# too small" from inside the amplifier and returns 0.000 V. That looks like
# clipping, reads like a successful result, and is a failed solve. Gear
# integration and relaxed tolerances get through it.
#
# Measured on summing-mixer: a six-channel overdrive returned 0.000 V without
# these and -8.337 V with them.
CONVERGENCE_OPTIONS = (
    ".options reltol=0.003 abstol=1e-9 vntol=1e-6 itl4=500 method=gear")

_MULTIPLIER = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3,
               "": 1.0, "k": 1e3, "K": 1e3, "M": 1e6}


def magnitude(text):
    """Parse an engineering value, in either convention these projects use.

    "10k 0.1%", "2u2 film", "100p C0G" and "100R" are how design.py writes
    them; "10 kΩ", "100 pF", "2.2 µF" and "100 Ω" are how the documents do.
    Both reduce to a number in base units, so nothing downstream has to care
    which wrote it.

    Used by two callers that look unrelated and are not: the SPICE writer here,
    and the check that documentation has not drifted from design.py. One parser
    for both, because a value is a value.
    """
    embedded = re.match(r"\s*(\d+)([pnuµmRkKM])(\d+)\b", text)   # 4k7, 2u2, 1k5
    if embedded:
        whole, prefix, fraction = embedded.groups()
        return float(f"{whole}.{fraction}") * _MULTIPLIER.get(prefix, 1.0)
    plain = re.match(r"\s*([\d.]+)\s*([pnuµmkKM])?\s*[ΩF]?", text)
    if not plain:
        raise ValueError(f"cannot read {text!r} as a value")
    number, prefix = plain.groups()
    return float(number) * _MULTIPLIER[prefix or ""]


def spice(text):
    """A design.py value as a number SPICE will accept."""
    return f"{magnitude(text):.6g}"


def as_value(quantity, unit="R"):
    """A float back into the value string style these projects place.

    The inverse of magnitude(), for numbers that come from a model of something
    -- a source impedance, a coupling capacitor -- rather than from a BOM.
    """
    if unit == "F":
        return (f"{quantity * 1e6:g}u" if quantity >= 1e-6
                else f"{quantity * 1e9:g}n" if quantity >= 1e-9
                else f"{quantity * 1e12:g}p")
    return f"{quantity / 1000:g}k" if quantity >= 1000 else f"{quantity:g}R"


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------

def place(sch, ref, lib_id, value, x, y, angle=0, mirror=None, sim=None):
    """Place a symbol carrying its simulation fields."""
    return sch.place(ref, lib_id, value, x, y, angle=angle, mirror=mirror,
                     extra=sim or None)


def resistor(sch, ref, value, x, y, angle=0):
    return place(sch, ref, "Device:R", value, x, y, angle=angle,
                 sim={"Sim.Device": "R", "Sim.Params": f"r={spice(value)}"})


def capacitor(sch, ref, value, x, y, angle=0):
    return place(sch, ref, "Device:C", value, x, y, angle=angle,
                 sim={"Sim.Device": "C", "Sim.Params": f"c={spice(value)}"})


def potentiometer(sch, ref, lib_id, value, x, y, position=0.0, angle=0):
    """A pot, with the wiper position stated.

    `position` runs from the r0 terminal, which on KiCad's R_Potentiometer is
    pin 1. So 0 is the wiper at pin 1 and 1 is the wiper at pin 3 -- and
    getting it backwards is silent, because a fully-attenuated output is a
    perfectly good simulation of nothing. Checked rather than assumed: 0.5
    returns -6.03 dB, which is what a divider at half travel should do.
    """
    return place(sch, ref, lib_id, value, x, y, angle=angle, sim={
        "Sim.Device": "R", "Sim.Type": "POT",
        "Sim.Params": f"r={spice(value)} pos={position:g}"})


def subckt(sch, ref, lib_id, value, x, y, model, library, pins,
           angle=0, mirror=None):
    """Place a part backed by a vendor subcircuit.

    `pins` maps this symbol's pin numbers to the subcircuit's node names, in
    the subcircuit's own order -- e.g. "1=IN+ 3=IN- 5=VCC 2=VEE 4=OUT".

    `library` is a bare filename, resolved against the project directory. It is
    tempting to use ${KIPRJMOD}; kicad-cli does not load the project file, so
    the variable comes out empty and the include points at /. The GUI, which is
    how these sheets are meant to be driven, resolves a bare name correctly.

    A dual or quad symbol cannot carry a single-amplifier model. Borrow a
    single-amp body and rename it, the way design.LIBS already borrows symbols
    for the fabrication schematic.
    """
    return place(sch, ref, lib_id, value, x, y, angle=angle, mirror=mirror,
                 sim={"Sim.Device": "SUBCKT", "Sim.Name": model,
                      "Sim.Library": library, "Sim.Pins": pins})


def ground(sch, x, y):
    """SPICE's node 0, and never a power symbol.

    power:GNDA yields a net called AGND. Nothing ties that to node 0, so the
    circuit floats -- and a floating circuit does not error, it returns
    numbers. On summing-mixer the symptom was an output 58 dB down that should
    have been unity.
    """
    return sch.power("Simulation_SPICE:0", x, y, value="0")


def source(sch, ref, kind, label, x, y, params):
    """A stimulus source from the stock Simulation_SPICE library.

    `kind` is "VDC", "VSIN" or "VPULSE"; `params` is the Sim.Params string,
    e.g. "dc=0 ampl=1 f=1k ac=1" for a VSIN.

    A source placed straight onto a node pins that node to its own value,
    because an ideal source has no output impedance. That is fine for driving
    something and useless for measuring crosstalk into it -- see
    docs/simulating.md. If the measurement involves what happens *at* an
    undriven input, model the real source behind it.
    """
    return place(sch, ref, f"Simulation_SPICE:{kind}", label, x, y, sim={
        "Sim.Device": "V", "Sim.Type": kind[1:], "Sim.Params": params})
