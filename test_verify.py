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

import contextlib
import copy
import sys
import types

import design
import verify
import contract.socket as socket


@contextlib.contextmanager
def _design_restored():
    """Put design.py back the way it was after a case that mutates it.

    Some faults are not expressible in the netlist -- a shield declared bonded
    at both ends, a pin declared as waiting for a block that has landed -- so
    those cases reach into `design` itself. They were not being undone. It did
    not show, because every check reads a different part of the module and the
    cases happened not to overlap; adding one that compares against design.NETS
    made it show immediately, since the third-conductor case leaves ('J1', '3')
    on MAGND and every later comparison then disagrees about MAGND.

    A test harness whose fixtures leak is the same failure this file exists to
    catch, one level up: it passes, and it stops meaning what its name says.
    """
    saved = {name: copy.deepcopy(getattr(design, name))
             for name in ("NETS", "LOOM", "DEFERRED_PINS", "DEFERRED",
                          "NO_CONNECT")}
    try:
        yield
    finally:
        for name, value in saved.items():
            current = getattr(design, name)
            if isinstance(current, dict):
                # In place, not rebound: design.NETS *is* design.DESIGN.nets and
                # rebinding the name would leave the object everything else
                # holds a reference to still mutated.
                current.clear()
                current.update(value)
            else:
                setattr(design, name, value)


def _run(check, context):
    for label, function, args in verify.CHECKS:
        if function is check:
            return function(*[context[a] for a in args])
    raise KeyError(check)


CASES = []


def case(label, check):
    def register(mutate):
        CASES.append((label, check, mutate))
        return mutate
    return register


@case("mixer V- appears in the netlist", verify.check_no_mixer_rail_load)
def _(nets, values, open_pins, violations):
    nets["V-"] = {("R901", "1"), ("R902", "1")}


@case("a second part bridges MAGND and AGND", verify.check_one_ground_bond)
def _(nets, values, open_pins, violations):
    nets["MAGND"].add(("R999", "1"))
    nets[socket.AGND].add(("R999", "2"))


@case("a stray part hangs off AGND", verify.check_one_ground_bond)
def _(nets, values, open_pins, violations):
    nets[socket.AGND].add(("C999", "1"))


@case("a third conductor creeps into the loom", verify.check_shield_returns)
def _(nets, values, open_pins, violations):
    design.NETS["MAGND"].append(("J1", "3"))


@case("a shield lands on the wrong socket pin", verify.check_shield_returns)
def _(nets, values, open_pins, violations):
    design.LOOM[4]["shield_pin"] = "1"


@case("something extra lands on SIN4", verify.check_sin_dc_by_construction)
def _(nets, values, open_pins, violations):
    nets["SIN4"].add(("C999", "1"))


@case("channel 5 loses its DC servo", verify.check_sin_dc_by_construction)
def _(nets, values, open_pins, violations):
    nets["SIN5"].discard(("R531", "1"))


@case("the 1M envelope tap is hung on PIN2, as spec s4.1 asks",
      verify.check_pin_load)
def _(nets, values, open_pins, violations):
    nets["PIN2"].add(("R299", "1"))


@case("R101 respecified as 4k7", verify.check_pin_load)
def _(nets, values, open_pins, violations):
    values["R101"] = "4k7 0.1%"


@case("the socket load is not a virtual earth", verify.check_pin_load)
def _(nets, values, open_pins, violations):
    nets["FEN6"].add(("C999", "1"))


@case("a seventh conductor leaves on the loom", verify.check_triads)
def _(nets, values, open_pins, violations):
    nets["STRAY"] = {("J3", "4"), ("R301", "1")}


# The three faults check_open_pins() exists for, and the first is not synthetic:
# it is what this sheet did for its whole life. Every relay coil's return was
# wired to MDGND and its drive labelled out to a net that existed nowhere else,
# which no check here looked at, and which is backwards for the open-drain sink
# section 4.5 specifies. See design.DEFERRED_PINS.
@case("a deferred coil return is quietly wired to MDGND",
      verify.check_open_pins)
def _(nets, values, open_pins, violations):
    open_pins.discard(("K101", "A2"))
    nets["MDGND"].add(("K101", "A2"))


@case("a pin is left open on the sheet and declared nowhere",
      verify.check_open_pins)
def _(nets, values, open_pins, violations):
    open_pins.add(("U9", "2"))


@case("a deferred pin waits on a block that has landed",
      verify.check_open_pins)
def _(nets, values, open_pins, violations):
    design.DEFERRED_PINS[("K101", "A1")] = "relay drive (landed)"


# check_erc() is an allow-list, which is the one shape of check that can quietly
# become a rubber stamp -- so all three ways it must refuse are planted. An ERC
# error of any kind, a warning class nobody wrote down, and the *same* class at a
# different count, which is the case that distinguishes this from silencing the
# rule in the project file.
@case("ERC reports an error of a kind nobody expected", verify.check_erc)
def _(nets, values, open_pins, violations):
    violations.append({"type": "pin_not_connected", "severity": "error",
                       "description": "Symbol U9 Pin 2 [I_IN1] not connected"})


@case("ERC reports a warning class that is not declared", verify.check_erc)
def _(nets, values, open_pins, violations):
    violations.append({"type": "hier_label_mismatch", "severity": "warning",
                       "description": "Mismatch between hierarchical labels"})


@case("a seventh op-amp section goes missing", verify.check_erc)
def _(nets, values, open_pins, violations):
    violations.append({"type": "missing_unit", "severity": "warning",
                       "description": "Symbol U8 has unplaced units [ D ]"})


# The four faults check_reference_load() exists for. The first is the one that
# was actually fitted: C804's second 10 uF, 2.01x the MAX6126's capacitive-load
# stability range, which every other instrument in this repo passed for the whole
# life of the design because none of them read a *sum*.
@case("a second 10 uF reservoir lands on VREF", verify.check_reference_load)
def _(nets, values, open_pins, violations):
    nets["VREF"].add(("C804", "1"))
    values["C804"] = "10u/16V X7R"


@case("one oversized capacitor on VREF", verify.check_reference_load)
def _(nets, values, open_pins, violations):
    values["C802"] = "22u/16V X7R"


@case("the required output capacitor is dropped", verify.check_reference_load)
def _(nets, values, open_pins, violations):
    nets["VREF"].discard(("C802", "1"))
    values["C802"] = "1n/50V C0G"


@case("the drawing and design.py disagree about VREF's load",
      verify.check_reference_load)
def _(nets, values, open_pins, violations):
    values["C803"] = "220n/50V X7R"


# And the comparison itself, which is the reason this file's netlist now comes
# out of KiCad. Each of these three is a *drawing* fault rather than a design
# fault, and none of them was reachable before: while both sides of compare()
# came from design.py there was nothing for a wire to miss.
DRAWING_FAULTS = (
    ("a wire misses its endpoint: IOUT3 loses the VCA",
     lambda nets: nets["IOUT3"].discard(("U9", "12"))),
    ("two nets touch: SIN2 acquires IOUT2's amplifier input",
     lambda nets: nets["SIN2"].add(("U3", "6"))),
    ("an interior node lost its label and KiCad named it",
     lambda nets: nets.__setitem__("Net-(C141-Pad1)", nets.pop("CVX1"))),
)


def main():
    socket.check_no_mixer_imports()
    if not verify.NETLIST.exists():
        raise SystemExit(f"{verify.NETLIST} does not exist -- run gen_sch.py, "
                         f"then verify.py")
    clean_nets = verify.read_netlist(verify.NETLIST)
    clean_values = verify.read_components(verify.NETLIST)
    clean_open = verify.read_open_pins(verify.NETLIST)
    clean_erc = verify.run_erc(verify.SHEET, verify.ERC)

    print("test_verify: every section 5 check must be able to fail")
    print()

    missed = []
    for label, check, mutate in CASES:
        context = {"nets": copy.deepcopy(clean_nets),
                   "values": dict(clean_values),
                   "open_pins": set(clean_open),
                   "violations": copy.deepcopy(clean_erc)}
        with _design_restored():
            mutate(*(context[name] for name in
                     ("nets", "values", "open_pins", "violations")))
            found = _run(check, context)
        print(f"  {label:<52} {'caught' if found else '*** MISSED ***'}")
        if not found:
            missed.append(label)

    for label, mutate in DRAWING_FAULTS:
        nets = copy.deepcopy(clean_nets)
        mutate(nets)
        found = verify.compare(nets, design.NETS)
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

    # And the contract. Nothing here may be exercised by modifying a mixer file:
    # CLAUDE.md's first rule is that nothing under that path is ever written, and
    # a test that breaks the rule it is testing under is not a test worth having.
    # So the process state is perturbed instead, and the mixer is never touched.
    #
    # **These three replaced three that tested a guard that no longer exists.**
    # check_pin() used to assert that six mixer files read off disk were clean and
    # equal to the pin. They are copies in toolchain/ now, so there is nothing to
    # keep clean, and what is asserted instead is the mechanism: the mixer's root
    # is not on sys.path, and nothing loaded came from a file underneath it.
    def _sys_path_polluted():
        sys.path.append(str(socket.MIXER))
        try:
            socket.check_pin()
        finally:
            sys.path.remove(str(socket.MIXER))

    def _module_from_the_mixer():
        planted = types.ModuleType("sexp")
        planted.__file__ = str(socket.MIXER / "sexp.py")
        sys.modules["planted_sexp"] = planted
        try:
            socket.check_no_mixer_imports()
        finally:
            del sys.modules["planted_sexp"]

    def _pinned_marker_missing():
        # The exemption is by marker, not by name. Strip the marker off the
        # pinned design module and the check must object to it like any other.
        module = sys.modules["mixer_design"]
        marker = module.__pinned__
        del module.__pinned__
        try:
            socket.check_no_mixer_imports()
        finally:
            module.__pinned__ = marker

    def _hash_is_not_a_commit():
        original = socket._git
        socket._git = lambda *args: ("blob\n" if args[0] == "cat-file" else "\n")
        try:
            socket.check_pin()
        finally:
            socket._git = original

    for label, provoke in (
            ("contract: the mixer's root is on sys.path", _sys_path_polluted),
            ("contract: a module was loaded from the mixer repo",
             _module_from_the_mixer),
            ("contract: a pinned module lost its provenance marker",
             _pinned_marker_missing),
            ("contract: the pinned hash is not a commit", _hash_is_not_a_commit)):
        try:
            provoke()
            found = []
        except SystemExit:
            found = ["raised"]
        print(f"  {label:<52} {'caught' if found else '*** MISSED ***'}")
        if not found:
            missed.append(label)

    print()
    if missed:
        raise SystemExit(f"{len(missed)} checks did not fail when they should: "
                         + "; ".join(missed))
    total = len(CASES) + len(DRAWING_FAULTS) + 3 + 4
    print(f"all {total} faults caught -- the checks are checks")


if __name__ == "__main__":
    main()
