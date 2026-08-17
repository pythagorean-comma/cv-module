"""Prove that verify.py's checks can fail.

The failure this repo's sibling keeps recording about itself is not a wrong
number -- it is **a check that is believed to cover more than it does**. Every
instance in `../summing-mixer` has the same shape: `check_voltage_ratings()`
stopping one parameter short, `rail_filter_rejection()` omitting the term that
dominates, `check_assumptions()` covering one entry out of six. In each case
the check ran, passed, and meant less than its name.

A green verify.py is therefore not evidence on its own. This file mutates the
netlist into each of the specific faults section 5 exists to prevent and
asserts that the corresponding check notices. If a check ever stops failing
here, it has stopped being a check.

    python3 test_verify.py

Every mutation below is a real fault rather than a synthetic one:

  * the 1 Mohm envelope tap on PIN{n} is what spec section 4.1 actually
    specifies, and it is caught -- see front_end() for why it moved;
  * a return tied to MAGND is the obvious way somebody "tidies up" six
    unconnected-looking sense resistors;
  * a shield bonded at both ends is what happens when a loom is made by
    somebody who was not told;
  * and a second MAGND/AGND bridge is the mixer's own named failure mode,
    transplanted.
"""

import copy

import design
import verify
import contract.socket as socket


def _run(check, nets, values):
    wants = {"nets": nets, "values": values}
    for label, function, args in verify.CHECKS:
        if function is check:
            return function(*[wants[a] for a in args])
    raise KeyError(check)


CASES = []


def case(label, check):
    def register(mutate):
        CASES.append((label, check, mutate))
        return mutate
    return register


@case("mixer V- appears in the netlist", verify.check_no_mixer_rail_load)
def _(nets, values):
    nets["V-"] = {("R901", "1"), ("R902", "1")}


@case("a second part bridges MAGND and AGND", verify.check_one_ground_bond)
def _(nets, values):
    nets["MAGND"].add(("R999", "1"))
    nets[socket.AGND].add(("R999", "2"))


@case("a stray part hangs off AGND", verify.check_one_ground_bond)
def _(nets, values):
    nets[socket.AGND].add(("C999", "1"))


@case("a third conductor creeps into the loom", verify.check_shield_returns)
def _(nets, values):
    design.NETS["MAGND"].append(("J1", "3"))


@case("a shield lands on the wrong socket pin", verify.check_shield_returns)
def _(nets, values):
    design.LOOM[4]["shield_pin"] = "1"


@case("something extra lands on SIN4", verify.check_sin_dc_by_construction)
def _(nets, values):
    nets["SIN4"].add(("C999", "1"))


@case("channel 5 loses its DC servo", verify.check_sin_dc_by_construction)
def _(nets, values):
    nets["SIN5"].discard(("R531", "1"))


@case("the 1M envelope tap is hung on PIN2, as spec s4.1 asks",
      verify.check_pin_load)
def _(nets, values):
    nets["PIN2"].add(("R299", "1"))


@case("R101 respecified as 4k7", verify.check_pin_load)
def _(nets, values):
    values["R101"] = "4k7 0.1%"


@case("the socket load is not a virtual earth", verify.check_pin_load)
def _(nets, values):
    nets["FEN6"].add(("C999", "1"))


@case("a seventh conductor leaves on the loom", verify.check_triads)
def _(nets, values):
    nets["STRAY"] = {("J3", "4"), ("R301", "1")}


def main():
    socket.check_no_shadowing()
    if not verify.NETLIST.exists():
        raise SystemExit(f"{verify.NETLIST} does not exist -- run gen_netlist.py")
    clean_nets = verify.read_netlist(verify.NETLIST)
    clean_values = verify.read_components(verify.NETLIST)

    print("test_verify: every section 5 check must be able to fail")
    print()

    missed = []
    for label, check, mutate in CASES:
        nets = copy.deepcopy(clean_nets)
        values = dict(clean_values)
        mutate(nets, values)
        found = _run(check, nets, values)
        print(f"  {label:<52} {'caught' if found else '*** MISSED ***'}")
        if not found:
            missed.append(label)

    # The declaration-only checks cannot be mutated through the netlist, so
    # they are exercised against TRIADS directly and restored afterwards.
    for field, bad in (("module_end", "grounded"),
                       ("shield_ground", "module"),
                       ("conductors", ("PIN2", "SIN2", "RET2"))):
        original = design.LOOM[2][field]
        design.LOOM[2][field] = bad
        found = verify.check_triads(clean_nets)
        label = f"triad declaration: {field} = {bad!r}"
        print(f"  {label:<52} {'caught' if found else '*** MISSED ***'}")
        if not found:
            missed.append(label)
        design.LOOM[2][field] = original

    print()
    if missed:
        raise SystemExit(f"{len(missed)} checks did not fail when they should: "
                         + "; ".join(missed))
    print(f"all {len(CASES) + 3} faults caught -- the checks are checks")


if __name__ == "__main__":
    main()
