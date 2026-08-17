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
  * a second MAGND/AGND bridge is the mixer's own named failure mode,
    transplanted;
  * and a second resistor on the coupling node is the coarse pad coming back,
    which is the one change that would quietly invalidate design.pad_benefit()
    without invalidating anything a wire can see.
"""

import contextlib
import copy
import pathlib
import sys
import tempfile
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

    **VCA_ROUT_OHMS joined the list with check_gain_chain()**, and it is the
    first scalar here rather than a container. The case that needs it asks what
    happens when design.py itself drifts off the unity condition, which cannot
    be expressed in a netlist at all -- and left unrestored it would make every
    later case run against a design that is not the design.
    """
    saved = {name: copy.deepcopy(getattr(design, name))
             for name in ("NETS", "LOOM", "DEFERRED_PINS", "DEFERRED",
                          "NO_CONNECT", "VCA_ROUT_OHMS")}
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
def _(nets, values, open_pins, violations, drc, board):
    nets["V-"] = {("R901", "1"), ("R902", "1")}


@case("a second part bridges MAGND and AGND", verify.check_one_ground_bond)
def _(nets, values, open_pins, violations, drc, board):
    nets["MAGND"].add(("R999", "1"))
    nets[socket.AGND].add(("R999", "2"))


@case("a stray part hangs off AGND", verify.check_one_ground_bond)
def _(nets, values, open_pins, violations, drc, board):
    nets[socket.AGND].add(("C999", "1"))


@case("a third conductor creeps into the loom", verify.check_shield_returns)
def _(nets, values, open_pins, violations, drc, board):
    design.NETS["MAGND"].append(("J1", "3"))


@case("a shield lands on the wrong socket pin", verify.check_shield_returns)
def _(nets, values, open_pins, violations, drc, board):
    design.LOOM[4]["shield_pin"] = "1"


@case("something extra lands on SIN4", verify.check_sin_dc_by_construction)
def _(nets, values, open_pins, violations, drc, board):
    nets["SIN4"].add(("C999", "1"))


@case("something extra lands on IVOUT6", verify.check_sin_dc_by_construction)
def _(nets, values, open_pins, violations, drc, board):
    nets["IVOUT6"].add(("C999", "1"))


@case("channel 5 loses its DC servo", verify.check_sin_dc_by_construction)
def _(nets, values, open_pins, violations, drc, board):
    # Was SIN5; the servo senses IVOUT5 now, upstream of the bypass contact.
    nets["IVOUT5"].discard(("R531", "1"))


@case("the 1M envelope tap is hung on PIN2, as spec s4.1 asks",
      verify.check_pin_load)
def _(nets, values, open_pins, violations, drc, board):
    nets["PIN2"].add(("R299", "1"))


@case("R101 respecified as 4k7", verify.check_pin_load)
def _(nets, values, open_pins, violations, drc, board):
    values["R101"] = "4k7 0.1%"


@case("the socket load is not a virtual earth", verify.check_pin_load)
def _(nets, values, open_pins, violations, drc, board):
    nets["FEN6"].add(("C999", "1"))


@case("a seventh conductor leaves on the loom", verify.check_triads)
def _(nets, values, open_pins, violations, drc, board):
    nets["STRAY"] = {("J3", "4"), ("R301", "1")}


# The four faults check_gain_chain() exists for, and the first two are the pad
# coming back -- which is the specific way this board could stop being the board
# design.pad_benefit() argues about. A switched R_IN is four resistors on the
# coupling node and a contact in series with the cell's input, and both of those
# are visible here and nowhere else in the netlist.
@case("a second R_IN branch appears on CPL3, which is a pad returning",
      verify.check_gain_chain)
def _(nets, values, open_pins, violations, drc, board):
    nets["CPL3"].add(("R312", "1"))


@case("R411 fitted at a pad step's value, so the channel is not unity",
      verify.check_gain_chain)
def _(nets, values, open_pins, violations, drc, board):
    values["R411"] = "24k3 0.1%"


@case("a contact lands between R_IN and the cell's input", verify.check_gain_chain)
def _(nets, values, open_pins, violations, drc, board):
    nets["IIN2"].add(("K201", "11"))


@case("design.py itself drifts off unity: R_OUT no longer equals R_IN",
      verify.check_gain_chain)
def _(nets, values, open_pins, violations, drc, board):
    design.VCA_ROUT_OHMS = 24_300.0


# The bypass changeover, and these are the faults that make "de-energised is
# bypass" false while leaving the sheet looking finished.
@case("the servo senses downstream of the bypass contact",
      verify.check_sin_dc_by_construction)
def _(nets, values, open_pins, violations, drc, board):
    nets["IVOUT4"].discard(("R431", "1"))
    nets["SIN4"].add(("R431", "1"))


@case("channel 5 is bypassed to channel 6's pole",
      verify.check_sin_dc_by_construction)
def _(nets, values, open_pins, violations, drc, board):
    nets["SIN5"].discard(("K803", "11"))
    nets["SIN5"].add(("K803", "21"))


@case("the module reaches the wiper through the normally *closed* contact",
      verify.check_sin_dc_by_construction)
def _(nets, values, open_pins, violations, drc, board):
    nets["IVOUT1"].discard(("K801", "14"))
    nets["IVOUT1"].add(("K801", "12"))


@case("a coil returns to MDGND instead of the sink", verify.check_fail_safe)
def _(nets, values, open_pins, violations, drc, board):
    nets["FSD"].discard(("K802", "A2"))
    nets["MDGND"].add(("K802", "A2"))


@case("a flyback diode is fitted backwards", verify.check_fail_safe)
def _(nets, values, open_pins, violations, drc, board):
    nets["FSD"].discard(("D823", "2"))
    nets["V5"].discard(("D823", "1"))
    nets["FSD"].add(("D823", "1"))
    nets["V5"].add(("D823", "2"))


@case("the pump's two diodes are swapped", verify.check_fail_safe)
def _(nets, values, open_pins, violations, drc, board):
    nets["FSAC"].discard(("D802", "2"))
    nets["FSG"].discard(("D802", "1"))
    nets["FSAC"].add(("D802", "1"))
    nets["FSG"].add(("D802", "2"))


@case("the VREFN clamp is reversed, shorting the inverted reference",
      verify.check_fail_safe)
def _(nets, values, open_pins, violations, drc, board):
    nets["VREFN"].discard(("D803", "2"))
    nets["MAGND"].discard(("D803", "1"))
    nets["VREFN"].add(("D803", "1"))
    nets["MAGND"].add(("D803", "2"))


@case("a second resistor lands on the hold node", verify.check_fail_safe)
def _(nets, values, open_pins, violations, drc, board):
    nets["FSG"].add(("R999", "1"))


# The three faults check_rectifier_polarity() exists for. The first is the
# mixer's own D801, transplanted: a diode fitted backwards, which draws
# correctly, passes ERC, and leaves the rectifier reporting nothing. It is the
# fault that repo records twice and could never catch, because both of its
# instruments compared the board against a design.py that agreed with the fault.
@case("D351 is fitted backwards, which is the mixer's own D801",
      verify.check_rectifier_polarity)
def _(nets, values, open_pins, violations, drc, board):
    nets["AOUT3"].discard(("D351", "2"))
    nets["HWN3"].discard(("D351", "1"))
    nets["AOUT3"].add(("D351", "1"))
    nets["HWN3"].add(("D351", "2"))


@case("both diodes point the same way, so one half-cycle is lost",
      verify.check_rectifier_polarity)
def _(nets, values, open_pins, violations, drc, board):
    nets["HW5"].discard(("D552", "2"))
    nets["AOUT5"].discard(("D552", "1"))
    nets["HW5"].add(("D552", "1"))
    nets["AOUT5"].add(("D552", "2"))


@case("a stray part loads the envelope summing junction",
      verify.check_rectifier_polarity)
def _(nets, values, open_pins, violations, drc, board):
    nets["ENVN2"].add(("C999", "1"))


# The two faults check_open_pins() exists for. There used to be three, and the
# first was not synthetic: every relay coil's return was wired to MDGND and its
# drive labelled out to a net that existed nowhere else, backwards for the
# open-drain sink section 4.5 specifies. Both it and the "deferred pin waits on
# a block that has landed" case named coil pins, and design.DEFERRED_PINS is
# empty now that the pad is struck -- so they are gone rather than rewritten
# around a pin that does not exist. **The check is unchanged and still holds
# both directions**; what is missing is a fault to plant in it, which is a
# thing to notice rather than to paper over with a synthetic one. The next
# deferred block that lands brings the cases back with it.
@case("a pin is left open on the sheet and declared nowhere",
      verify.check_open_pins)
def _(nets, values, open_pins, violations, drc, board):
    open_pins.add(("U9", "2"))


@case("a permanent no-connect is quietly wired up", verify.check_open_pins)
def _(nets, values, open_pins, violations, drc, board):
    open_pins.discard((design.REF_REF, str(design.REF_PINS["IC1"])))
    nets["MAGND"].add((design.REF_REF, str(design.REF_PINS["IC1"])))


# check_erc() is an allow-list, which is the one shape of check that can quietly
# become a rubber stamp -- so all three ways it must refuse are planted. An ERC
# error of any kind, a warning class nobody wrote down, and the *same* class at a
# different count, which is the case that distinguishes this from silencing the
# rule in the project file.
@case("ERC reports an error of a kind nobody expected", verify.check_erc)
def _(nets, values, open_pins, violations, drc, board):
    violations.append({"type": "pin_not_connected", "severity": "error",
                       "description": "Symbol U9 Pin 2 [I_IN1] not connected"})


@case("ERC reports a warning class that is not declared", verify.check_erc)
def _(nets, values, open_pins, violations, drc, board):
    violations.append({"type": "hier_label_mismatch", "severity": "warning",
                       "description": "Mismatch between hierarchical labels"})


@case("a seventh op-amp section goes missing", verify.check_erc)
def _(nets, values, open_pins, violations, drc, board):
    violations.append({"type": "missing_unit", "severity": "warning",
                       "description": "Symbol U8 has unplaced units [ D ]"})


# The four faults check_reference_load() exists for. The first is the one that
# was actually fitted: C804's second 10 uF, 2.01x the MAX6126's capacitive-load
# stability range, which every other instrument in this repo passed for the whole
# life of the design because none of them read a *sum*.
@case("a second 10 uF reservoir lands on VREF", verify.check_reference_load)
def _(nets, values, open_pins, violations, drc, board):
    nets["VREF"].add(("C804", "1"))
    values["C804"] = "10u/16V X7R"


@case("one oversized capacitor on VREF", verify.check_reference_load)
def _(nets, values, open_pins, violations, drc, board):
    values["C802"] = "22u/16V X7R"


@case("the required output capacitor is dropped", verify.check_reference_load)
def _(nets, values, open_pins, violations, drc, board):
    nets["VREF"].discard(("C802", "1"))
    values["C802"] = "1n/50V C0G"


@case("the drawing and design.py disagree about VREF's load",
      verify.check_reference_load)
def _(nets, values, open_pins, violations, drc, board):
    values["C803"] = "220n/50V X7R"


# The board. Two checks, and the second is the one no other instrument in this
# project or KiCad itself will make.
@case("DRC reports a clearance violation", verify.check_board)
def _(nets, values, open_pins, violations, drc, board):
    drc["violations"].append({
        "type": "clearance", "severity": "error",
        "description": "Clearance violation ( clearance 0.2mm; actual 0.05mm)",
        "items": [{"description": "Pad 1 of R101"}]})


@case("routing goes backwards and the count is not put back up",
      verify.check_board)
def _(nets, values, open_pins, violations, drc, board):
    drc["unconnected_items"] = drc["unconnected_items"][:-4]


# The router's own invariant, checked without KiCad: two nets on one point.
# gen_pcb.py runs this on every build and refuses to save if it fails, so what
# is planted here is the check itself rather than a board.
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
    clean_drc = verify.read_drc(verify.PCB, verify.DRC)

    print("test_verify: every section 5 check must be able to fail")
    print()

    missed = []
    for label, check, mutate in CASES:
        context = {"nets": copy.deepcopy(clean_nets),
                   "values": dict(clean_values),
                   "open_pins": set(clean_open),
                   "violations": copy.deepcopy(clean_erc),
                   "drc": copy.deepcopy(clean_drc),
                   "board": verify.PCB}
        with _design_restored():
            mutate(*(context[name] for name in
                     ("nets", "values", "open_pins", "violations",
                      "drc", "board")))
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

    # The router's own invariant, which is not a verify.py check and so cannot
    # be planted through CASES: gen_pcb.py runs it before it saves and refuses
    # to write a board that fails it. What is proved here is that it can fail.
    import route
    shorts = route.check_no_shorts(
        [("A", route.FRONT, [(1.0, 1.0), (1.5, 1.0)]),
         ("B", route.FRONT, [(1.5, 1.0), (2.0, 1.0)])], [], 0.5)
    label = "the router puts two nets on one point"
    print(f"  {label:<52} {'caught' if shorts else '*** MISSED ***'}")
    if not shorts:
        missed.append(label)

    # The pour overlap, which needs a *file* rather than a netlist: the whole
    # point of check_ground_split_on_the_board() is that it reads what was
    # written. So the board is copied to the scratch path with one zone moved
    # across the split, and the copy is what is checked. The real board is
    # never touched.
    import tempfile
    original = verify.PCB.read_text()
    moved = original.replace("158.44", "100.0")
    with tempfile.NamedTemporaryFile("w", suffix=".kicad_pcb",
                                     delete=False) as handle:
        handle.write(moved)
        planted = pathlib.Path(handle.name)
    found = verify.check_ground_split_on_the_board(planted)
    label = "the two ground pours overlap on an inner layer"
    print(f"  {label:<52} {'caught' if found else '*** MISSED ***'}")
    if not found:
        missed.append(label)
    planted.unlink()

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
    total = len(CASES) + len(DRAWING_FAULTS) + 2 + 3 + 4
    print(f"all {total} faults caught -- the checks are checks")


if __name__ == "__main__":
    main()
