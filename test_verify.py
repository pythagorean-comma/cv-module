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
import json
import pathlib
import sys
import tempfile
import types

import design
import rules
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
                          "NO_CONNECT", "VCA_ROUT_OHMS", "CLAMP_VF_TABLE",
                          "SUPPLY_IOUT_MA")}
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


class _Watched(set):
    """One net's members, which records a discard that removed nothing.

    **This exists because three planted faults were silently disarmed and the
    only reason anybody found out was luck.** They named the bypass relay's
    contacts as IEC numbers -- "11", "14", "A2" -- which was right while
    design.BYPASS_RELAY was None and wrong the moment a G6S was fitted, because
    its terminals are 1/12 and 9/10/8, 4/3/5. `set.discard` on a member that is
    not there is a no-op, so the mutation planted nothing, the check found
    nothing wrong, and the case reported "caught" for exactly as long as it took
    somebody to change a part for an unrelated reason.

    That is this file's own failure mode, arriving one level up. `_run` proves a
    check can fail; nothing proved the *fault* was still a fault. The naive
    version of this test -- "did the mutation change anything?" -- passes all
    forty cases and would have passed all three of those, because they also
    `add` a pin, and adding one does change the set. What separates a live plant
    from a dead one is the discard: you cannot remove what is not there, so a
    discard that removes nothing is always a mutation that has lost its target.
    """

    def __init__(self, items, log, net):
        super().__init__(items)
        self._log = log
        self._net = net

    def discard(self, item):
        if item not in self:
            self._log.append(
                f"{self._net}.discard({item!r}) removed nothing -- that pin is "
                f"not on this net, so the fault is not planted")
        super().discard(item)


def dead_mutations(clean_nets, clean_values, clean_open, clean_erc, clean_drc):
    """Every planted mutation still has a target. Returns the ones that do not.

    Deliberately not part of CASES: it is a check on the cases rather than on
    verify.py, and folding it in would make the file assert something about
    itself in the same list it uses to assert things about the design.
    """
    dead = []
    for label, _, mutate in CASES:
        log = []
        nets = {name: _Watched(members, log, name)
                for name, members in copy.deepcopy(clean_nets).items()}
        with _design_restored():
            try:
                # The real ERC and DRC objects, deep-copied. Stand-ins of the
                # wrong shape make a mutation raise, which this would then
                # report as a lost target -- a false alarm from the guard is
                # the one thing that would get the guard switched off.
                mutate(nets, dict(clean_values), set(clean_open),
                       copy.deepcopy(clean_erc), copy.deepcopy(clean_drc),
                       verify.PCB)
            except Exception as error:
                log.append(f"raised {error!r} -- a mutation that cannot run "
                           f"plants nothing")
        if log:
            dead.append((label, log))
    return dead


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


# **These three carried the relay's pin numbers as literals, and choosing the
# part silently disarmed them.** They read "11", "21", "14", "12", "A2" -- IEC
# contact numbers, correct while design.BYPASS_RELAY was None and wrong the
# moment a G6S was fitted, because its terminals are 1/12 and 9/10/8, 4/3/5. A
# mutation that names a pin the netlist no longer has does not plant a fault:
# `discard` on a missing member is a no-op and `add` puts a pin nobody checks
# onto a net, so all three cases went on passing and stopped meaning anything.
# Exactly the failure this file exists to catch, in this file.
#
# They go through RELAY_PINS now, which is the single copy of the map. A part
# change moves them with it, and a *wrong* part change fails them.
@case("channel 5 is bypassed to channel 6's pole",
      verify.check_sin_dc_by_construction)
def _(nets, values, open_pins, violations, drc, board):
    nets["SIN5"].discard(("K803", design.RELAY_PINS["COM_A"]))
    nets["SIN5"].add(("K803", design.RELAY_PINS["COM_B"]))


@case("the module reaches the wiper through the normally *closed* contact",
      verify.check_sin_dc_by_construction)
def _(nets, values, open_pins, violations, drc, board):
    nets["IVOUT1"].discard(("K801", design.RELAY_PINS["NO_A"]))
    nets["IVOUT1"].add(("K801", design.RELAY_PINS["NC_A"]))


@case("a coil returns to MDGND instead of the sink", verify.check_fail_safe)
def _(nets, values, open_pins, violations, drc, board):
    nets["FSD"].discard(("K802", design.RELAY_PINS["COIL-"]))
    nets["MDGND"].add(("K802", design.RELAY_PINS["COIL-"]))


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


# **The substitution that used to be the design.** D803 was a BAT54 for the
# life of the fail-safe, and a BAT54 at the 36 mA it carries is 500 mV, which
# is +13.4 dB on a summer with 7.84 dB of headroom. Nothing could see it: the
# netlist was right, the polarity was right, ERC and DRC were silent, and
# clamp_gain() returned "fits" because it read an assumed constant rather than
# the fitted part. This is that exact board, planted.
@case("D803 goes back to a BAT54, which cannot clamp at 36 mA",
      verify.check_fail_safe)
def _(nets, values, open_pins, violations, drc, board):
    values["D803"] = "BAT54"


@case("the clamp stops fitting inside the mixer's headroom",
      verify.check_fail_safe)
def _(nets, values, open_pins, violations, drc, board):
    # Not a netlist fault at all: design.py itself drifting off the part that
    # makes the arithmetic work. Restored by _design_restored().
    design.CLAMP_VF_TABLE = ((10e-3, 0.420), (100e-3, 0.560), (1.0, 0.800))


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


# The supply. Four faults through the netlist and two through the geometry, and
# the first of the four is the one that would destroy the board: a dual-output
# converter's Com is pin 7 and its -Vout is pin 8, so swapping them makes
# +12 V and 0 V where the design wants +12 and -12. Every op-amp on the board
# then sits with its V- pin at MDGND and its V+ at 12, which works, and every
# signal that should swing below ground clips at zero -- a fault that powers
# up, passes ERC, passes DRC, and is wrong in a way no continuity test finds
# because both nets exist and both are connected.
@case("the converter's Com and -Vout are swapped", verify.check_supply)
def _(nets, values, open_pins, violations, drc, board):
    com = str(design.SUPPLY_PINS["Com"])
    neg = str(design.SUPPLY_PINS["-Vout"])
    nets["MDGND"].discard((design.SUPPLY_REF, com))
    nets["VN_RAW"].discard((design.SUPPLY_REF, neg))
    nets["MDGND"].add((design.SUPPLY_REF, neg))
    nets["VN_RAW"].add((design.SUPPLY_REF, com))


@case("a rail filter is drawn across the rail", verify.check_supply)
def _(nets, values, open_pins, violations, drc, board):
    nets["VA_RAW"].discard(("R804", "1"))
    nets["MDGND"].add(("R804", "1"))


@case("a rail filter capacitor returns to MAGND", verify.check_supply)
def _(nets, values, open_pins, violations, drc, board):
    nets["MDGND"].discard(("C811", "2"))
    nets["MAGND"].add(("C811", "2"))


@case("a secondary part hangs off the primary", verify.check_supply)
def _(nets, values, open_pins, violations, drc, board):
    nets["IGND"].add(("R902", "1"))


# **The choke's windings, and this is the one fault on the board that no
# drawing can show.** Pairing 1-2 and 4-3 instead of 1-4 and 2-3 is the same
# four wires between the same four pins: the schematic is identical to a
# reader, ERC counts the same pins, DRC sees the same copper, and the module
# powers up. What it does is put 1 mH in series with 389 mA of supply current
# instead of 3.6 kohm across the common-mode path barrier_return() bought it
# for -- and barrier_return() would go on reporting 1.1 uV at the bond,
# because it reads a constant and not a netlist.
@case("the inlet choke's windings are paired the wrong way",
      verify.check_supply)
def _(nets, values, open_pins, violations, drc, board):
    ref = design.INLET_CHOKE_REF
    out1 = str(design.INLET_CHOKE_PINS["L1_OUT"])
    in2 = str(design.INLET_CHOKE_PINS["L2_IN"])
    nets["VIN"].discard((ref, out1))
    nets["IGND_J"].discard((ref, in2))
    nets["VIN"].add((ref, in2))
    nets["IGND_J"].add((ref, out1))


# The other half of the same part: the choke fitted after the decoupling
# rather than before it, which is what "put the filter next to the converter"
# would produce. IGND_J then reaches C807, and the primary allow-list is what
# says which parts may touch which primary net.
@case("the choke is fitted downstream of the primary decoupling",
      verify.check_supply)
def _(nets, values, open_pins, violations, drc, board):
    nets["IGND"].discard(("C807", "2"))
    nets["IGND_J"].add(("C807", "2"))


# **The module's own star, and the fault is the tidy way to wire a DGND pin.**
@case("the ADC's DGND goes to MDGND", verify.check_module_star)
def _(nets, values, open_pins, violations, drc, board):
    pin = str(design.ENV_ADC_PINS["DGND"])
    nets["MAGND"].discard((design.ENV_ADC_REF, pin))
    nets["MDGND"].add((design.ENV_ADC_REF, pin))


@case("a second 0R bridges the two module grounds",
      verify.check_module_star)
def _(nets, values, open_pins, violations, drc, board):
    nets["MAGND"].add(("R903", "1"))
    nets["MDGND"].add(("R903", "2"))


# **The ADC's divider upside down, which is the fault that destroys the part.**
# Two resistors in a divider are two resistors in a divider whichever way
# round they are: the sheet is identical, the netlist has the same three
# nodes, and both values are already on this BOM. The ratio goes from 0.185
# to 0.815, so stage B at its rail arrives at the pin as 9.5 V against an
# absolute maximum of 3.4.
@case("the ADC's input divider is upside down", verify.check_envelope_adc)
def _(nets, values, open_pins, violations, drc, board):
    values["R356"], values["R357"] = values["R357"], values["R356"]


@case("the ADC's reference is the rail instead of VREF",
      verify.check_envelope_adc)
def _(nets, values, open_pins, violations, drc, board):
    pin = str(design.ENV_ADC_PINS["REFIN+"])
    nets["VREF"].discard((design.ENV_ADC_REF, pin))
    nets["V3V3"].add((design.ENV_ADC_REF, pin))


@case("a spare ADC channel is left floating", verify.check_envelope_adc)
def _(nets, values, open_pins, violations, drc, board):
    nets["MAGND"].discard((design.ENV_ADC_REF,
                           str(design.ENV_ADC_PINS["CH7"])))


@case("something extra loads the ADC divider", verify.check_envelope_adc)
def _(nets, values, open_pins, violations, drc, board):
    nets["ENVA2"].add(("C999", "1"))


# **Not a netlist fault at all, and it is the one that will actually happen.**
# The converter's outputs are 250 mA each and the deferred controller and ADC
# both land on VA+, one part at a time, with nothing in between to say when the
# total crossed the datasheet. Planted by shrinking the rating rather than by
# adding load, because adding load means adding parts and the fault this
# defends against is the load arriving legitimately.
@case("the converter's output rating is exceeded", verify.check_supply)
def _(nets, values, open_pins, violations, drc, board):
    design.SUPPLY_IOUT_MA = 100.0


# The board. Two checks, and the second is the one no other instrument in this
# project or KiCad itself will make.
@case("DRC reports a clearance violation", verify.check_board)
def _(nets, values, open_pins, violations, drc, board):
    drc["violations"].append({
        "type": "clearance", "severity": "error",
        "description": "Clearance violation ( clearance 0.2mm; actual 0.05mm)",
        "items": [{"description": "Pad 1 of R101"}]})


# **This case changed direction when the board finished routing**, and the way
# it changed is the point. It used to delete four of the sixty-seven unconnected
# items, modelling "somebody routed four nets and left the declaration at 67".
# At UNROUTED_ITEMS = 0 that mutation removed four items from an empty list and
# plants nothing at all -- it stopped being a fault without stopping being a
# case, and test_verify.py reported it MISSED on the first run after the board
# closed, which is the file doing its job.
#
# **UNROUTED_ITEMS is 10 again now** -- see the note there, and note that this
# case survives the change for the reason the old one did not: appending an item
# fails the comparison at any declared value, where deleting four only planted a
# fault while there were at least four to delete. The direction that matters is
# still this one:
# a connection that was made is no longer made. That is what a part moving, a
# net appearing, or a router regression all look like from DRC's side.
@case("a routed connection is lost and the count stays at zero",
      verify.check_board)
def _(nets, values, open_pins, violations, drc, board):
    drc["unconnected_items"].append({
        "type": "unconnected_items", "severity": "error",
        "description": "Missing connection between items",
        "items": [{"description": "Pad 2 of R101"},
                  {"description": "Pad 1 of C101"}]})


# -- the controller -------------------------------------------------------
#
# **Five checks and nine faults, and the shape of them is the shape of the
# block.** Everything in the controller is either a pin assignment nobody can
# see is wrong or a value somebody would helpfully correct back to the wrong
# one -- so the faults are a wire on a plausible pin, a part that quietly
# stops being counted, and two values that are the number a datasheet or a
# specification actually prints.

@case("the RP2040's core rail is tied to its IO rail",
      verify.check_controller)
def _(nets, values, open_pins, violations, drc, board):
    # VREG_VOUT is an *output*. On VMCU it is a 1.1 V regulator driving into
    # 3.3, which works until the part is warm.
    nets["VCORE"].discard((design.CONTROLLER_REF,
                           str(design.CONTROLLER_PINS["VREG_VOUT"])))
    nets["VMCU"].add((design.CONTROLLER_REF,
                      str(design.CONTROLLER_PINS["VREG_VOUT"])))


@case("a supply pin loses its own decoupling capacitor",
      verify.check_controller)
def _(nets, values, open_pins, violations, drc, board):
    nets["VMCU"].discard(("C823", "1"))


@case("MCLK moves to a pin with no clock output on it",
      verify.check_controller)
def _(nets, values, open_pins, violations, drc, board):
    ref = design.CONTROLLER_REF
    nets["MCLK"].discard((ref, str(design.CONTROLLER_GPIO_PINS[21])))
    nets["MCLK"].add((ref, str(design.CONTROLLER_GPIO_PINS[27])))


@case("a pull-up creeps onto QSPI_SS", verify.check_controller_periphery)
def _(nets, values, open_pins, violations, drc, board):
    # The reference design's own R2, which that document marks DNF for this
    # exact flash. A part added for luck is still a stub on the fastest bus
    # here.
    nets["QSCS"].add(("R999", "1"))


@case("the crystal's load capacitors stop being equal",
      verify.check_controller_periphery)
def _(nets, values, open_pins, violations, drc, board):
    values["C833"] = "22p/50V C0G"


@case("the crystal loses its drive resistor",
      verify.check_controller_periphery)
def _(nets, values, open_pins, violations, drc, board):
    ref = design.CRYSTAL_REF
    nets["XTAL"].discard((ref, str(design.CRYSTAL_PINS["XOUT"])))
    nets["XOUT"].add((ref, str(design.CRYSTAL_PINS["XOUT"])))


@case("the switcher is fed from behind the rail filter",
      verify.check_mcu_supply)
def _(nets, values, open_pins, violations, drc, board):
    pin = str(design.MCU_DCDC_PINS["VIN"])
    nets["VA_RAW"].discard((design.MCU_DCDC_REF, pin))
    nets["VA+"].add((design.MCU_DCDC_REF, pin))


@case("the feedback divider is swapped end for end",
      verify.check_mcu_supply)
def _(nets, values, open_pins, violations, drc, board):
    values["R850"], values["R851"] = values["R851"], values["R850"]


@case("the MIDI IN shield gets a DC path to ground", verify.check_midi)
def _(nets, values, open_pins, violations, drc, board):
    nets["MDGND"].add(("J15", "2"))


# **This case was "corrected back to CA-033's 220 ohm" and that fault was not
# one.** The claim it was planted from -- that the specification's own value
# delivers 6.6 mA into this opto, over its recommended maximum -- came from an
# arithmetic slip: it used 0.2 V for the driver's VOL where the RP2040's table
# says 0.5. At 220 ohm the real spread is 4.32 to 5.51 mA, inside the
# recommended range, so check_midi() passed and the case would have reported
# MISSED. Found by printing the numbers, which is the cheapest instrument in
# this repo and the one that keeps finding things. What is planted instead is a
# value that does leave the range, and the direction is the plausible one:
# somebody worrying the LED is under-driven and halving the resistor.
@case("the MIDI loop resistor is halved and overdrives the LED",
      verify.check_midi)
def _(nets, values, open_pins, violations, drc, board):
    values["R827"] = "100R 1%"


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

    # **The tally counts what ran, and it used to be arithmetic.** The closing
    # line said `len(CASES) + len(DRAWING_FAULTS) + 2 + 3 + 4`, with the three
    # literals standing for groups of faults planted further down -- so adding
    # a fault below without remembering to increment one of them printed a
    # number smaller than the number of lines above it, on the same screen.
    # It did exactly that on the run that added the check_rules() faults: fifty
    # planted, fifty caught, "all 50" printed with fifty-three lines above it.
    # A count of the checks that is itself unchecked is the smallest possible
    # version of this repository's own failure mode, and report() is the fix.
    missed, ran = [], []

    def report(label, found):
        ran.append(label)
        print(f"  {label:<52} {'caught' if found else '*** MISSED ***'}")
        if not found:
            missed.append(label)

    # **Before running the cases, check the cases.** A mutation that has lost
    # its target still reports "caught", because a check that finds nothing
    # wrong with an unmutated netlist is indistinguishable from one that finds
    # nothing wrong with a mutated one. This is what noticed nothing when the
    # bypass relay was chosen and three faults quietly stopped being faults.
    disarmed = dead_mutations(clean_nets, clean_values, clean_open,
                              clean_erc, clean_drc)
    report("every planted fault still has a target", not disarmed)
    for label, why in disarmed:
        print(f"      {label}")
        for line in why:
            print(f"          {line}")

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
        report(label, found)

    for label, mutate in DRAWING_FAULTS:
        nets = copy.deepcopy(clean_nets)
        mutate(nets)
        found = verify.compare(nets, design.NETS)
        report(label, found)


    # The isolation barrier's geometric half. **Planted by moving the declared
    # region rather than by editing the routed board**, and the reason is worth
    # stating because the alternative looks more honest and is not: a text
    # substitution into a routed .kicad_pcb plants a different fault every time
    # the router's output moves, so the case would drift from what its label
    # says without anybody touching it. The declaration is the stable half.
    #
    # Both directions, because they are different faults. Moving the line west
    # leaves the primary's own copper outside the region it is supposed to be
    # confined to -- a part placed on the wrong side. Moving it east puts the
    # digital pour and its tracks inside -- a plane across the barrier, which
    # is the failure design.barrier_return() is arithmetic about.
    import placement as _placement
    original_x = _placement.ISOLATION_X
    for label, moved in (
            ("primary copper outside the isolated region", original_x - 20.0),
            ("digital copper inside the isolated region", original_x + 30.0)):
        _placement.ISOLATION_X = moved
        try:
            found = verify.check_isolation_gap(verify.PCB)
        finally:
            _placement.ISOLATION_X = original_x
        report(label, found)

    # **U21's bypass distance, planted by moving the requirement.** This is
    # the one case in the file where the fault is in the threshold rather than
    # in the artefact, and the reason is that the artefact is a routed board:
    # check_midi_bypass() measures two pads on it, and the only way to make
    # that measurement fail is to move a part and re-route -- which is a
    # different board, not a planted fault. Moving the number is the same
    # move ISOLATION_X's two cases above make, and it proves the same thing:
    # the check reads the board and reports what it finds there.
    original_mm = design.MIDI_OPTO_LOCAL_MM
    design.MIDI_OPTO_LOCAL_MM = 0.5
    try:
        found = verify.check_midi_bypass(verify.PCB)
    finally:
        design.MIDI_OPTO_LOCAL_MM = original_mm
    report("U21's bypass is further away than its datasheet allows", found)

    # The router's own invariant, which is not a verify.py check and so cannot
    # be planted through CASES: gen_pcb.py runs it before it saves and refuses
    # to write a board that fails it. What is proved here is that it can fail.
    import route
    shorts = route.check_no_shorts(
        [("A", route.FRONT, [(1.0, 1.0), (1.5, 1.0)]),
         ("B", route.FRONT, [(1.5, 1.0), (2.0, 1.0)])], [], 0.5)
    label = "the router puts two nets on one point"
    report(label, shorts)

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
    report(label, found)
    planted.unlink()

    # check_rules() reads two files, so its faults are planted in copies of
    # them. **The first of these three is not hypothetical**: it is exactly the
    # state this project was in until the pass that wrote check_rules(), where
    # gen_project.py's re-run after SaveBoard() put an empty rules block over
    # the design rules gen_pcb.py had just set, and every DRC report since the
    # board existed ran with KiCad's defaults. A check whose first planted fault
    # is the bug it was written to find is a check that was needed.
    for label, path, mutate in (
            ("the project's DRC rules are emptied", verify.PROJECT,
             lambda text: json.dumps(
                 {**json.loads(text),
                  "board": {"design_settings": {"drc_exclusions": [],
                                                "rules": {}}}})),
            # **These two carried the fitted class as literals and both went
            # dead the moment it changed.** They read `'"clearance": 0.2'` and
            # `'(width 0.25)'`, which matched nothing once rules.py moved to
            # 0.09/0.09: str.replace() found no target, wrote the file back
            # unchanged, check_rules() correctly reported no problem, and this
            # file reported MISSED on both. That is the IEC relay pins again --
            # a mutation whose target is a value some other file owns -- and the
            # fix is the same shape twice: read the value from where it lives,
            # and make the harness refuse a mutation that changes nothing.
            ("a net class clearance drifts off rules.py", verify.PROJECT,
             lambda text: text.replace(f'"clearance": {rules.CLEARANCE_MM}',
                                       f'"clearance": {rules.CLEARANCE_MM / 2}')),
            ("the board carries a track of an undeclared width", verify.PCB,
             lambda text: text.replace(f'(width {rules.TRACK_MM})',
                                       f'(width {rules.TRACK_MM / 2})', 1))):
        # **A text mutation that changes nothing is a mutation with no target**,
        # which is dead_mutations()' discriminator one object along: you cannot
        # remove what is not there, and you cannot replace what does not match.
        # Checked here rather than there because these three rewrite files on
        # disk instead of the netlist, so dead_mutations() never sees them.
        original = path.read_text()
        planted = mutate(original)
        if planted == original:
            report(f"{label} [DEAD: the mutation matched nothing]", [])
            continue
        with tempfile.NamedTemporaryFile("w", suffix=path.suffix,
                                         delete=False) as handle:
            handle.write(planted)
            copy_path = pathlib.Path(handle.name)
        if path == verify.PROJECT:
            found = verify.check_rules(copy_path, verify.PCB)
        else:
            found = verify.check_rules(verify.PROJECT, copy_path)
        report(label, found)
        copy_path.unlink()

    # The declaration-only checks cannot be mutated through the netlist, so
    # they are exercised against TRIADS directly and restored afterwards.
    for field, bad in (("module_end", "grounded"),
                       ("shield_ground", "module"),
                       ("conductors", ("PIN2", "SIN2", "RET2"))):
        original = design.LOOM[2][field]
        design.LOOM[2][field] = bad
        found = verify.check_triads(clean_nets)
        label = f"triad declaration: {field} = {bad!r}"
        report(label, found)
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
        report(label, found)

    print()
    if missed:
        raise SystemExit(f"{len(missed)} checks did not fail when they should: "
                         + "; ".join(missed))
    print(f"all {len(ran)} faults caught -- the checks are checks")


if __name__ == "__main__":
    main()
