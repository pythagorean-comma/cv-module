"""Read the schematic back through KiCad and check it against section 5.

The five constraints in `hardware-spec-v0.md` section 5 are described there as
load-bearing rather than stylistic, and CLAUDE.md says to check them
mechanically rather than by eye. This is that check.

**What it reads changed, and that change is the point of the exercise.** This
file used to read `out/cv-module.net`, written by gen_netlist.py from the same
`design.py` these checks import. Every check passed and none of them could ever
have failed for a transcription error, because there was no transcription: the
comparison was design.py against itself, laundered through a file. What it
caught was a design that violates its own constraints, which is worth having and
is not what its docstring claimed.

It now runs

    kicad-cli sch export netlist --format kicadsexpr

over `out/cv-module.kicad_sch` and reads that. Every net in it was formed by
*KiCad* out of geometry -- wire ends meeting at coordinates, pins landing
mid-wire, labels naming what they touch -- so a route that misses its target by
1.27 mm now changes the answer. That is the whole argument for synthesising a
schematic, it is what the mixer's own verify.py does, and it is the reason
`gen_sch.py` names every interior node: an unlabelled net comes out of the
export as `Net-(C141-Pad1)`, which compares by node-set and never tells you
which net moved.

`out/from-kicad.net` is a build artefact and is regenerated on every run.
`out/cv-module.net` is still written by gen_netlist.py and is still the file the
BOM and the floorplan read; it is no longer what this file checks.

What it catches:

  * a rail this module is forbidden to touch, appearing anywhere;
  * a second bond between the two grounds, which is what one stray ground
    symbol produces and what turns the star into six loops;
  * a shield landing anywhere but its own pin-3, or at both ends;
  * anything landing on SIN{n} that can put DC into the mixer's summing node;
  * a load at PIN{n} that is not the 10k the DC-block corner was computed for;
  * an audio conductor leaving the module without a declared pair and shield;
  * a pin left open on the sheet that the design has not declared open;
  * an envelope rectifier diode fitted backwards, which is the fault the mixer
    records twice and could not catch;
  * a bypass contact on the wrong pole, a coil that does not return to the one
    sink, or a servo sensing downstream of the changeover;
  * R_IN switched, loaded, revalued or no longer equal to R_OUT, which is what
    the coarse pad's deletion rests on -- see design.pad_benefit().

None of those is visible to ERC, to DRC, or to a netlist comparison against
design.py -- which is the test the mixer's own check_ground_star() docstring
applies, and the reason these are separate functions rather than assertions
buried in the generator.
"""

import json
import math
import pathlib
import subprocess
import sys

import design
import gen_project
import placement
import rules
import contract.socket as socket
from toolchain import kicad, kisim, sexp

OUT = pathlib.Path(__file__).resolve().parent / "out"
SHEET = OUT / "cv-module.kicad_sch"
NETLIST = OUT / "from-kicad.net"
ERC = OUT / "from-kicad-erc.json"
PROJECT = OUT / "cv-module.kicad_pro"
PCB = OUT / "cv-module.kicad_pcb"
DRC = OUT / "from-kicad-drc.json"


def export_netlist(schematic, destination):
    """Ask KiCad what the drawing means. Lifted from the mixer's verify.py.

    Regenerated every run rather than read from the tree, so the answer is
    always about the schematic on disk now. A stale export is the one way this
    check can go quiet without saying so.
    """
    if not schematic.exists():
        raise SystemExit(f"{schematic} does not exist -- run gen_sch.py")
    result = subprocess.run(
        [str(kicad.KICAD_CLI), "sch", "export", "netlist", "--format",
         "kicadsexpr", "-o", str(destination), str(schematic)],
        capture_output=True, text=True)
    if result.returncode != 0 or not destination.exists():
        raise SystemExit(
            f"netlist export failed:\n{result.stdout}\n{result.stderr}")
    return destination


# KiCad's own name for a pin that is on nothing. It emits one single-node net
# per open pin, so `unconnected-(U9-MODE-Pad1)` is not a net this design
# declares and is not a fault either -- it is the export's way of writing
# "open".
OPEN = "unconnected-"


def _nodes(net):
    """(ref, pin) for the real parts on one exported net.

    A `#PWR` or `#FLG` symbol names a net; it is not a part on it. The mixer's
    reader makes the same exclusion and KiCad already omits them, so this is
    belt and braces against a format that has changed before.
    """
    found = set()
    for node in sexp.find_all(net, "node"):
        ref = sexp.find(node, "ref")[1]
        if not ref.startswith("#"):
            found.add((ref, str(sexp.find(node, "pin")[1])))
    return found


def read_netlist(path):
    """net name -> set of (ref, pin), for the nets that are nets."""
    tree = sexp.parse(path.read_text())
    return {sexp.find(net, "name")[1]: _nodes(net)
            for net in sexp.find_all(sexp.find(tree, "nets"), "net")
            if not str(sexp.find(net, "name")[1]).startswith(OPEN)}


def read_open_pins(path):
    """The pins KiCad found on nothing, as a set of (ref, pin).

    Read separately from the nets rather than filtered out and forgotten,
    because it is the more interesting half of the export on a partial sheet:
    check_open_pins() holds it against design.py's own declaration, so KiCad
    and design.py have to agree about which pins are open and not merely about
    which are connected.
    """
    tree = sexp.parse(path.read_text())
    found = set()
    for net in sexp.find_all(sexp.find(tree, "nets"), "net"):
        if str(sexp.find(net, "name")[1]).startswith(OPEN):
            found |= _nodes(net)
    return found


def read_components(path):
    """reference -> value, from the emitted file."""
    tree = sexp.parse(path.read_text())
    out = {}
    for comp in sexp.find_all(sexp.find(tree, "components"), "comp"):
        out[sexp.find(comp, "ref")[1]] = sexp.find(comp, "value")[1]
    return out


def compare(actual, expected):
    """What KiCad found in the geometry is what design.py asked for, by name.

    **Compared by name, not by node-set, and the difference is the whole value
    of the change.** The node-set form -- match each net's frozenset of
    (ref, pin) and report the ones with no partner -- was what this file did
    while both sides came from design.py, and it survives a rename because it
    never reads the name. Against KiCad's export that is exactly the wrong
    trade: it reports "some net moved" twice, once as missing and once as
    unexpected, and leaves the reader to diff two sets of 500 nodes.

    By name, a wire that missed its endpoint says which net lost which pin. The
    price is that every net has to *have* a name on the sheet, which is why
    gen_sch.py labels the summing junctions and the integrator nodes that never
    leave their block. `Net-(C141-Pad1)` is what the alternative looks like, and
    it changes when a part is renumbered.

    Nets KiCad names for itself are reported separately: those are nets the
    geometry formed and design.py never declared, which is the shape of an
    accidental short between two things that were meant to be one node.
    """
    expected = {name: set(nodes) for name, nodes in expected.items()}
    problems = []
    for name in sorted(set(expected) - set(actual)):
        problems.append(
            f"{name} is in design.py and KiCad found no such net on the sheet")
    for name in sorted(set(actual) - set(expected)):
        problems.append(
            f"KiCad found net {name} = {sorted(actual[name])}, which design.py "
            f"does not declare")
    for name in sorted(set(actual) & set(expected)):
        if actual[name] == expected[name]:
            continue
        extra = sorted(actual[name] - expected[name])
        short = sorted(expected[name] - actual[name])
        problems.append(
            f"{name} carries {extra} that design.py does not put on it and is "
            f"missing {short}")
    return problems


# ---------------------------------------------------------------------------
# Section 5
# ---------------------------------------------------------------------------

def check_no_mixer_rail_load(nets):
    """1. The module draws nothing from VREG, V+ or V-.

    The parent document's reason: "Every mA on V- costs 65 mV of rail." The
    mixer's negative rail is a 55-ohm charge pump already sagging 0.47 V under
    its own op-amp, and NEGATIVE_RAIL_DROP is that figure.

    Two halves. The obvious one is that none of those nets appears here at all.
    The one worth writing is the second: this module's own rails must not be
    *named* the same as the mixer's, because a net called "V+" in both places
    is a check that passes by spelling. design.RAILS is deliberately VA+/VA-,
    and this asserts the two vocabularies stay disjoint.
    """
    problems = []
    for rail in socket.FORBIDDEN_RAILS:
        if rail in nets:
            problems.append(
                f"{rail} appears in this module's netlist, carrying "
                f"{sorted(nets[rail])} -- constraint 1 forbids drawing "
                f"anything from it")
    collisions = sorted(set(design.RAILS) & set(socket.FORBIDDEN_RAILS))
    if collisions:
        problems.append(
            f"this module's rail names collide with the mixer's: {collisions} "
            f"-- rename, or constraint 1 is enforced by spelling")
    return problems


def check_one_ground_bond(nets):
    """2a. Exactly one bond between module audio ground and board AGND.

    The mixer holds the same shape of rule with check_ground_star() and calls
    a second bridge "what a stray ground symbol on the wrong net produces". The
    consequence here is worse than there: a second bond does not merely make a
    loop inside one board, it makes a loop that encloses the mixer's AGND pour
    and the whole length of this module's loom.

    Also checks what else touches AGND, because a bond that is correct and a
    part hanging off the same net is the same fault arriving by a different
    route.
    """
    problems = []
    parts_on = {}
    for name, nodes in nets.items():
        for ref, _ in nodes:
            parts_on.setdefault(ref, set()).add(name)

    bridges = sorted(ref for ref, names in parts_on.items()
                     if {"MAGND", socket.AGND} <= names)
    if bridges != [design.GROUND_STAR]:
        problems.append(
            f"MAGND and {socket.AGND} are bridged by {bridges or 'nothing'}, "
            f"expected exactly ['{design.GROUND_STAR}'] -- constraint 2")

    allowed = {design.GROUND_STAR, "J7"}
    found = {ref for ref, _ in nets.get(socket.AGND, ())}
    if found != allowed:
        problems.append(
            f"{socket.AGND} carries {sorted(found)}, expected {sorted(allowed)} "
            f"-- the bond and the pad it leaves on, and nothing else")
    return problems


def check_shield_returns(nets):
    """2b. Six separate returns to six pin-3s, not commoned in the module.

    **The clause this checks is not the one CLAUDE.md states, and the change is
    deliberate.** That sentence asked for six *conductors* carrying returns,
    and design.FRONT_R records the arithmetic that removed it: with a single
    bond carrying all six channels, pairwise crosstalk is 122 dB below one
    string on a 100 mm bond and 103 dB on a deliberately bad one, against a
    -54 dB requirement. Six return conductors have no mechanism here.

    What survives is the half that does: six *shields*, one per channel,
    landing on six separate pin-3s and grounded at the main-board end only.
    That is per-channel electrostatic separation in a loom that runs past a
    45 kHz charge pump, and it is what constraint 5 asks for independently.

    So this asserts the shields, and check_one_ground_bond() above asserts the
    single bond. Between them the two real properties of constraint 2 are held
    and the one with no mechanism is not.
    """
    problems = []
    for n in range(1, design.CHANNELS + 1):
        loom = design.LOOM[n]
        if loom["shield_pin"] != socket.PIN_RETURN:
            problems.append(
                f"channel {n}'s shield lands on socket pin "
                f"{loom['shield_pin']}, but the mixer at {socket.PIN[:7]} has "
                f"AGND on pin {socket.PIN_RETURN}")
        if socket.channel_socket(n).get(loom["shield_pin"]) != socket.AGND:
            problems.append(
                f"channel {n}'s shield pin is not AGND upstream")

    pins = [design.LOOM[n]["shield_pin"] for n in range(1, design.CHANNELS + 1)]
    if len(pins) != design.CHANNELS:
        problems.append("not six shields")

    # No return conductor may have crept back in: a net reaching a loom
    # connector must be one of that channel's two signals and nothing else.
    for n in range(1, design.CHANNELS + 1):
        found = {net for net, entries in design.NETS.items()
                 if any(ref == f"J{n}" for ref, _ in entries)}
        if found != set(design.LOOM[n]["conductors"]):
            problems.append(
                f"J{n} carries {sorted(found)}, expected "
                f"{sorted(design.LOOM[n]['conductors'])} -- a third conductor "
                f"in the loom is a second path to the mixer's ground")
    return problems


def check_sin_dc_by_construction(nets, values):
    """3. SIN{n} puts no more DC through the master wiper than the mixer does.

    **Restated in CLAUDE.md from "zero DC by construction", which overstated by
    three orders of magnitude.** The servo leaves 0.5 mV, which through C703 and
    R706 is 3.0 nA at the wiper against the 0.2-1.0 nA the mixer already accepts
    from U1B's own offset. See constraints.py.

    A netlist cannot measure volts, so what is checked is still the
    construction -- and **the construction moved when the bypass relay landed,
    so this check moved with it rather than being loosened to accommodate it.**
    SIN{n} used to be the I-V amplifier's own output. It is now the mixer's
    wiper on one side of a changeover contact, with the amplifier on the other:

        SIN{n}    the loom, and this channel's own relay pole
        IVOUT{n}  the I-V output, its feedback pair, the servo sense, and the
                  same relay's normally-open contact

    Anything additional on either is a path that can put DC into R{n}01 and
    from there into the mixer's summing node, where six channels' worth lands
    on the master pot's wiper.

    Two things are asserted that could not be before, and both are failures a
    drawing would not show.

    **The servo must sense IVOUT{n} and not SIN{n}.** Downstream of the contact
    the loop opens the moment the module leaves circuit, and an integrator with
    an open loop goes to a rail and stays there -- so the module would come
    back from bypass wrong rather than coming back. The old wiring is now a
    fault and test_verify.py plants it.

    **The pole must be this channel's own.** bypass_contact(n) says which, and
    a channel wired to a neighbour's pole is a board that bypasses two strings
    to one place and leaves another pair crossed. Every other instrument passes
    on it: the parts are all present, the counts are right, and ERC has nothing
    to say about which contact of a relay a net lands on.
    """
    problems = []
    for n in range(1, design.CHANNELS + 1):
        relay, com, nc, no = design.bypass_contact(n)
        for name, expected in (
                (f"SIN{n}", {f"J{n}", relay}),
                (f"IVOUT{n}", {f"R{n}21", f"C{n}21", f"R{n}31", relay,
                               design.SECTIONS[("iv", n)][0]})):
            found = {ref for ref, _ in nets.get(name, ())}
            if found != expected:
                problems.append(
                    f"{name} carries {sorted(found)}, expected "
                    f"{sorted(expected)} -- see design.fail_safe() for why "
                    f"the I-V output and the mixer's wiper are two nets")
            if design.net_dc(name) != (0.0, 0.0):
                problems.append(f"{name} is not declared 0 V DC in NET_DC")
        if (relay, com) not in nets.get(f"SIN{n}", ()):
            problems.append(
                f"SIN{n} is not on {relay}.{com}, which is the pole "
                f"design.bypass_contact({n}) assigns it")
        if (relay, no) not in nets.get(f"IVOUT{n}", ()):
            problems.append(
                f"IVOUT{n} is not on {relay}.{no} -- the module must reach the "
                f"wiper through the *normally open* contact, or de-energised "
                f"is not bypass")
        if (f"R{n}31", "1") not in nets.get(f"IVOUT{n}", ()):
            problems.append(
                f"channel {n}'s servo does not sense IVOUT{n} -- either the "
                f"VCA's own 150 nA offset current stands on the output, or "
                f"the loop is downstream of the bypass contact and opens "
                f"every time the module leaves circuit")
    return problems


def check_pin_load(nets, values):
    """4. PIN{n} presents 5-10 kohm, keeping the DC-block corner inside the
    15.9-31.8 Hz the fabricated design already sweeps.

    **Corrected in CLAUDE.md.** The old wording said "or the 31.8 Hz corner
    moves", and 31.8 Hz is the corner at 5 kohm -- one end of the window, so the
    sentence held at exactly one point in its own range. See constraints.py.

    Three claims, and the third is the one a netlist is uniquely able to make.

    The value is inside the window. The window is the mixer's own, and both
    ends of it are real: attenuator_input_impedance() is 10k with the pot shut
    and 5k wide open, so anything in between reproduces some position of the
    control this module replaces.

    Nothing else is on the node **except this channel's own bypass contact**. A
    second part at PIN{n} -- the 1 Mohm envelope tap spec section 4.1 puts here,
    for instance -- shifts the load and the corner with it, and the symptom is a
    tonal complaint rather than a fault.

    The contact is admitted rather than excused. It is open whenever the module
    is in circuit, so the 10.000 kohm above is what PIN{n} sees in normal
    operation; when it closes, PIN{n} and SIN{n} become one node and the mixer
    sees R{n}01 in parallel with its own RIN -- 5 kohm, which
    design.bypass_state() shows is exactly what the fabricated pot presents at
    full rotation. Both ends of the changeover are conditions the mixer was
    built for, and that is the argument for allowing the extra member here
    rather than the convenience of it.

    And the load is a resistor into a *virtual earth*, not a shunt to ground.
    That is what makes it 10.000 kohm rather than 10k in parallel with whatever
    the next stage's input happens to be, and it is checked by following
    R{n}01's far end to the front-end amplifier's inverting pin.
    """
    problems = []
    low, high = 5_000.0, 10_000.0
    for n in range(1, design.CHANNELS + 1):
        name = f"PIN{n}"
        relay, _, nc, _ = design.bypass_contact(n)
        expected = {f"J{n}", f"R{n}01", relay}
        found = {ref for ref, _ in nets.get(name, ())}
        if found != expected:
            problems.append(
                f"{name} carries {sorted(found)}, expected {sorted(expected)} "
                f"-- the loom, the socket load and this channel's own bypass "
                f"contact")
            continue
        if (relay, nc) not in nets.get(name, ()):
            problems.append(
                f"{name} is not on {relay}.{nc} -- the link back to the wiper "
                f"must be the *normally closed* contact, or the module fails "
                f"into silence rather than into bypass")
        if values.get(f"R{n}01") != design.FRONT_R:
            problems.append(
                f"R{n}01 is {values.get(f'R{n}01')!r}, expected "
                f"{design.FRONT_R!r}")
        if not low <= design.FRONT_R_OHMS <= high:
            problems.append(
                f"R{n}01 is {design.FRONT_R_OHMS:.0f} ohm, outside the "
                f"{low:.0f}-{high:.0f} window constraint 4 allows")
        # The far end must be the front end's inverting input.
        package, unit = design.SECTIONS[("front", n)]
        inverting = design.OPAMP_UNITS[unit][1]
        virtual_earth = {ref for ref, _ in nets.get(f"FEN{n}", ())}
        if (package, str(inverting)) not in nets.get(f"FEN{n}", set()):
            problems.append(
                f"R{n}01 does not reach {package}'s inverting input -- the "
                f"load is not a virtual earth and is therefore not exactly "
                f"{design.FRONT_R_OHMS:.0f} ohm")
        if virtual_earth != {f"R{n}01", f"R{n}02", package}:
            problems.append(
                f"FEN{n} carries {sorted(virtual_earth)} -- anything else on "
                f"the summing junction changes what PIN{n} sees")
    return problems


def check_triads(nets):
    """5. Audio as twisted pairs inside individual shields, shields grounded at
    the main-board end only.

    **Demoted in CLAUDE.md from load-bearing to good practice**, on 59 dB of
    margin: both loom nodes are low impedance, so the coupling the shields
    prevent is far inside the -54 dB isolation requirement. Still checked,
    because the check is nearly free and a shield bonded at both ends is a
    shorted turn whatever the margin. See constraints.py.

    A shield is not a netlist object, so this checks the declaration instead --
    the same move design.DIODE_DIRECTION makes upstream, where which way a
    diode points cannot be inferred from connectivity and so has to be written
    down and asserted.

    Two properties. Every conductor that leaves this module must belong to
    exactly one triad, so a seventh wire cannot be added without saying which
    shield it travels inside. And every shield must be declared grounded at one
    end, at the main-board end, because a shield bonded at both ends is a
    shorted turn around the loom and is worse than no shield at all.
    """
    problems = []
    declared = {}
    for n, triad in design.LOOM.items():
        if len(triad["conductors"]) != 2:
            problems.append(
                f"channel {n} declares {len(triad['conductors'])} conductors "
                f"-- a shielded pair is two; see design.FRONT_R for why it is "
                f"not three")
        for conductor in triad["conductors"]:
            if conductor in declared:
                problems.append(
                    f"{conductor} is in both triad {declared[conductor]} and "
                    f"triad {n}")
            declared[conductor] = n
        if triad["shield_ground"] != "main-board":
            problems.append(
                f"channel {n}'s shield is grounded at "
                f"{triad['shield_ground']!r}, expected 'main-board'")
        if triad["module_end"] != "floating":
            problems.append(
                f"channel {n}'s shield is terminated at the module end too -- "
                f"a shield bonded at both ends is a shorted turn")

    # Every net reaching a loom connector must be a declared conductor.
    loom = {f"J{n}" for n in range(1, design.CHANNELS + 1)}
    for name, nodes in nets.items():
        if not any(ref in loom for ref, _ in nodes):
            continue
        if name not in declared:
            problems.append(
                f"{name} leaves the module on the loom and is in no declared "
                f"triad -- see design.LOOM")
    return problems


def check_gain_chain(nets, values):
    """R_IN is one resistor, R_OUT equals it, and nothing else is on either node.

    **New with the coarse pad's deletion, and it is the netlist half of that
    decision.** design.pad_benefit() shows that switching R_IN buys nothing
    against taking the same attenuation in the control port; what makes that
    arithmetic *true of this board* is that R_IN is a single fixed resistor
    with a known value and an unloaded node either side of it. That is a
    property of connectivity and of values together, so it is checkable here
    and nowhere else.

    Modelled on the mixer's check_attenuators(), which CLAUDE.md names as the
    precedent: assert the values, then assert the *membership* of the nets on
    both sides, because "anything extra landing between them" is the fault that
    changes a number without changing a wire anybody drew on purpose.

    Four claims:

    R{n}11 is design.VCA_RIN and R{n}21 is design.VCA_ROUT, read off the
    exported netlist rather than off design.py -- so a value typed onto the
    sheet, or a pad step fitted where the fixed resistor belongs, fails here.

    The two are *equal*, which is the unity condition. A design where they
    differ is not wrong, but every noise figure in this repo is quoted at
    unity, and the datasheet's own noise table is specified at R_IN = R_OUT --
    so if they ever diverge the figures stop being readings and become
    extrapolations, which is exactly the mistake the pad was built on.

    CPL{n} carries C{n}01 and R{n}11 and nothing else. It is the coupling node,
    and a second branch on it is what a pad looks like coming back: four
    resistors to four selector contacts, all of them on this net.

    IIN{n} carries R{n}11, R{n}15 and the cell's own input pin. Anything else
    between R_IN and the gain core is either a switch, in which case the gain
    is not what design.py says, or a load, in which case the input current is
    not what pad_benefit() priced.

    **What else would pass.** ERC sees every pin connected either way. compare()
    above catches a *drawing* that disagrees with design.py, and would catch
    three of the four -- but not a design.py that has changed its own mind,
    which is the case where both sides agree and the arithmetic in
    pad_benefit() quietly stops applying to the board.
    """
    problems = []
    if design.VCA_RIN_OHMS != design.VCA_ROUT_OHMS:
        problems.append(
            f"design.py has R_IN {design.VCA_RIN_OHMS:.0f} and R_OUT "
            f"{design.VCA_ROUT_OHMS:.0f} -- not unity, and every noise figure "
            f"in this repo is quoted at the datasheet's R_IN = R_OUT")
    for n in range(1, design.CHANNELS + 1):
        for ref, expected in ((f"R{n}11", design.VCA_RIN),
                              (f"R{n}21", design.VCA_ROUT)):
            if values.get(ref) != expected:
                problems.append(
                    f"{ref} is {values.get(ref)!r}, expected {expected!r} -- "
                    f"see design.VCA_RIN, and pad_benefit() for why the pair "
                    f"is fixed and equal")
        for name, expected in (
                (f"CPL{n}", {f"C{n}01", f"R{n}11"}),
                (f"IIN{n}", {f"R{n}11", f"R{n}15",
                             design.VCA_CELL[n][0]})):
            found = {ref for ref, _ in nets.get(name, ())}
            if found != expected:
                problems.append(
                    f"{name} carries {sorted(found)}, expected "
                    f"{sorted(expected)} -- anything else in series with R_IN "
                    f"switches the gain, and anything across it loads the cell")
    return problems


def check_rectifier_polarity(nets, values):
    """Both envelope diodes point the way the rectifier needs them to.

    **The one part of this board where the drawing can be right and the circuit
    backwards, and the mixer paid for the lesson twice.** Its DIODE_PINS records
    D801 fitted cathode-to-the-inlet for the whole life of that design and says
    what was blind to it -- "a pin number can be transposed silently; 'A' and
    'K' cannot" -- and its CAP_PINS records the same fault one part class later.
    Neither was catchable there, because both instruments compared the board to
    a design.py that was itself wrong.

    Here it is catchable, and this is the check that does it: the netlist is
    KiCad's, read back from geometry, and what is asserted is the *role* of each
    pin rather than its number. D{n}51's anode belongs on the amplifier's output
    and its cathode on the summing node; D{n}52's are the other way round. Swap
    either and the rectifier still draws, still passes ERC, still matches part
    for part -- and reports nothing, because the loop closes through the wrong
    diode on both half-cycles.

    Also asserted: the two summing junctions carry exactly what design.py puts
    on them. HWN{n} is R{n}51, R{n}52, D{n}51 and the amplifier; ENVN{n} is the
    three summing resistors, the capacitor and its amplifier. Anything else on
    either is a load on a virtual earth, which changes the gain that
    envelope_filter() derives without changing anything a wire can see.
    """
    problems = []
    for n in range(1, design.CHANNELS + 1):
        expected = {
            (f"D{n}51", str(design.DIODE_PINS["A"])): f"AOUT{n}",
            (f"D{n}51", str(design.DIODE_PINS["K"])): f"HWN{n}",
            (f"D{n}52", str(design.DIODE_PINS["A"])): f"HW{n}",
            (f"D{n}52", str(design.DIODE_PINS["K"])): f"AOUT{n}",
        }
        for (ref, pin), net in sorted(expected.items()):
            found = sorted(name for name, nodes in nets.items()
                           if (ref, pin) in nodes)
            role = "anode" if pin == str(design.DIODE_PINS["A"]) else "cathode"
            if found != [net]:
                problems.append(
                    f"{ref}'s {role} is on {found or ['nothing']}, expected "
                    f"[{net!r}] -- see design.envelope(), and design.DIODE_PINS "
                    f"for why this is asserted by role and not by number")
        package_a = design.SECTIONS[("env_a", n)][0]
        package_b = design.SECTIONS[("env_b", n)][0]
        for name, want in (
                (f"HWN{n}", {f"R{n}51", f"R{n}52", f"D{n}51", package_a}),
                (f"ENVN{n}", {f"R{n}53", f"R{n}54", f"R{n}55", f"C{n}51",
                              package_b})):
            found = {ref for ref, _ in nets.get(name, ())}
            if found != want:
                problems.append(
                    f"{name} carries {sorted(found)}, expected {sorted(want)} "
                    f"-- anything else on a virtual earth changes the gain "
                    f"envelope_filter() derives")
    return problems


def check_fail_safe(nets, values):
    """De-energised is bypass, and every coil is on the one sink.

    The fail-safe's whole claim is a *state*, and states are what a netlist is
    worst at -- so what is asserted here is the connectivity that makes the
    state true, one clause at a time.

    **Every coil returns to the same drain.** Three relays released by one FET
    is what makes "the module is in circuit" a single fact; a coil wired to
    MDGND instead would hold two channels in circuit for ever, and the sheet
    would look like three identical relays.

    **Every coil has a flyback diode across it, pointing the right way.** The
    coils are the only inductance on this board and the FET is the only thing
    that switches them off; a diode reversed here is a short across V5 through
    the drain, which is a part destroyed rather than a fault heard. Asserted by
    role, per design.DIODE_PINS.

    **The pump's two diodes are the pump.** D801 clamps FSAC to MDGND and D802
    passes the positive half to the hold node, and swapping them gives a
    circuit that draws correctly and charges nothing -- so the module never
    leaves bypass and the fault reads as "the relay is dead".

    **The hold node carries the bleed and nothing else.** R803 is the fail-safe's
    actual time constant, and a second resistor on FSG changes t_off and t_on
    together without changing a part count. pump_timing() is what it would
    invalidate.

    **VREFN's clamp is present and the right way round.** It is the only answer
    to the one fail-loud path, and reversed it shorts the inverted reference to
    ground through a diode -- which is not a subtle failure, but it is one that
    looks identical on a sheet.
    """
    problems = []
    coil_low = {ref for ref, _ in nets.get("FSD", ())}
    expected = ({design.FET_REF}
                | set(design.BYPASS_RELAY_REFS)
                | {f"D{80 + i}3" for i in range(1, design.BYPASS_RELAYS + 1)})
    if coil_low != expected:
        problems.append(
            f"FSD carries {sorted(coil_low)}, expected {sorted(expected)} -- "
            f"every coil and every flyback on the one sink, or 'released' is "
            f"not one fact")

    for index in range(1, design.BYPASS_RELAYS + 1):
        ref, diode = design.BYPASS_RELAY_REFS[index - 1], f"D{80 + index}3"
        for pin, net in ((design.RELAY_PINS["COIL+"], "V5"),
                         (design.RELAY_PINS["COIL-"], "FSD")):
            if (ref, str(pin)) not in nets.get(net, ()):
                problems.append(f"{ref}.{pin} is not on {net}")
        for role, net in (("A", "FSD"), ("K", "V5")):
            if (diode, str(design.DIODE_PINS[role])) not in nets.get(net, ()):
                problems.append(
                    f"{diode}'s {'anode' if role == 'A' else 'cathode'} is not "
                    f"on {net} -- a flyback the wrong way round is a short "
                    f"across {design.BYPASS_COIL_V:.0f} V through the drain")

    for diode, anode, cathode in (("D801", "MDGND", "FSAC"),
                                  ("D802", "FSAC", "FSG"),
                                  ("D803", "VREFN", "MAGND")):
        for role, net in (("A", anode), ("K", cathode)):
            if (diode, str(design.DIODE_PINS[role])) not in nets.get(net, ()):
                problems.append(
                    f"{diode}'s {'anode' if role == 'A' else 'cathode'} is not "
                    f"on {net} -- see design.fail_safe()")

    gate = {ref for ref, _ in nets.get("FSG", ())}
    if gate != {"C806", "R803", "D802", design.FET_REF}:
        problems.append(
            f"FSG carries {sorted(gate)}, expected ['C806', 'D802', 'R803', "
            f"'{design.FET_REF}'] -- anything else on the hold node moves both "
            f"of pump_timing()'s time constants")

    # **D803 is the one part on this board chosen by a number rather than a
    # class, and this is the check that keeps it that way.** The clamp works
    # only because the fitted diode's own datasheet maximum at 36 mA is under
    # clamp_vf_ceiling(); a BAT54 sat here for the life of the design at
    # 500 mV, which is 5.5 dB over the mixer's headroom on the fault the clamp
    # exists to prevent, and nothing noticed because every instrument read the
    # same assumed constant. Read from the *netlist's* value string, so
    # substituting the part on the sheet fails here rather than at the bench.
    fitted = values.get("D803")
    if fitted != design.CLAMP_DIODE:
        problems.append(
            f"D803 is fitted as {fitted!r} and design.CLAMP_DIODE is "
            f"{design.CLAMP_DIODE!r} -- the clamp is chosen by its forward "
            f"drop at {design.clamp_current()['amps'] * 1e3:.0f} mA, not by "
            f"being a Schottky. See design.clamp_vf_ceiling()")
    verdict = design.clamp_gain()
    if not verdict["fits"]:
        problems.append(
            f"the clamp gives {verdict['clamped_db']:+.1f} dB against "
            f"{verdict['headroom_db']:.2f} dB of headroom at the mixer's "
            f"summer, so the fail-loud path still clips it")
    return problems


# What the router did not finish, pinned exactly -- for the reason
# ERC_ALLOWED's counts were: "mostly routed" is something a reader forgives,
# and a missing connection is something that has to reach zero before anybody
# orders copper.
#
# **476, then 67, then 0, and the violation count never left zero.** That last
# clause is the property, not the first: a router that trades shorts for
# finished connections is worse than one that gives up and says so.
#
# The 67 were left as a choice between a finer grid on thinner track and rip-up
# and retry, and the answer turned out to be neither on its own:
#
#   * **three of the twenty-three nets were not congestion at all.** A pad's
#     own copper cells were being marked "blocked" by its neighbour's clearance
#     ring, because two SOIC pins are closer together than one ring is wide, so
#     IOUT1, IOUT4 and VREF had no reachable cell inside their own pads. From
#     outside that is indistinguishable from a full board. route.block_pad_copper();
#   * **the finer grid was priced and refused.** rules.escape_corridor() shows
#     the corridor between two SOIC pins is 0.02 mm wide at the fitted class
#     and opens only at JLCPCB's 0.09 mm multilayer class, which is available
#     at 1 oz outer copper and not at 2 oz. No pitch buys it and no pitch is
#     needed;
#   * **rip-up and retry is what finished it**, at the pitch already fitted.
#     route.route_all() rips up the whole board and routes it again in an order
#     led by how often each net has failed, and this board closes on the ninth
#     pass.
#
# Zero is a stronger claim than 67 and a more fragile one, exactly as
# ERC_ALLOWED's emptiness is. If a part moves and one net cannot be finished,
# this is where the number goes back -- with the net named, not with the
# category filtered out.
UNROUTED_ITEMS = 0


def read_drc(board, destination):
    """Run KiCad's own DRC over the board and read the report back.

    **--severity-all, which run_erc() has always had and this had not.** The
    mixer's build.sh records the same asymmetry and calls it exactly right: the
    two ran at different severities, so "0 violations" meant two different
    things depending on which report you were reading, and on the board it
    meant the weaker one. Eighteen warnings were invisible to that gate
    upstream, among them a legend printed across a connector's pads.

    Here it turns out to have hidden nothing -- the board reports 0 violations
    at every severity, checked rather than assumed, which is the only reason
    this could be added without a fresh allow-list. That makes it free to arm
    and worth arming: a warning-severity check is still a check, and what it is
    not is a thing to run and then throw half of away.
    """
    if not board.exists():
        raise SystemExit(f"{board} does not exist -- run gen_pcb.py")
    result = subprocess.run(
        [str(kicad.KICAD_CLI), "pcb", "drc", "--severity-all", "--format",
         "json", "-o", str(destination), str(board)],
        capture_output=True, text=True)
    if not destination.exists():
        raise SystemExit(f"DRC failed:\n{result.stdout}\n{result.stderr}")
    return json.loads(destination.read_text())


def check_board(report):
    """The board breaks no design rule, and its unrouted count is declared.

    **DRC is to the board what ERC is to the sheet, and the same argument
    applies to what it is allowed to still say.** Violations are held at zero
    -- there is no allow-list here and there should not be one, because
    everything DRC reports on a *placed* board is a placement fault and
    placement is cheap to change. The first run said 262: courtyards through
    each other, silk over pads, and one package landing on another's row.

    Unconnected items are different in kind: they are work not done rather
    than work done wrong, and the honest thing is to state the number rather
    than filter the category out. UNROUTED_ITEMS is that statement, and it has
    come down from 476 to 67 to 0 without the violation count ever leaving
    zero -- which is the property worth protecting. A router that trades shorts
    for completed connections is worse than one that gives up and says so.

    **At zero it also stops being only a declaration and starts being a
    check**, which is worth noticing rather than assuming. While the number was
    67 this compared a count against a count, and the last of the 67 was a
    MAGND pad connected to nothing that nobody could see inside the total. The
    one direction left from zero is a connection going away.
    """
    problems = []
    violations = report.get("violations", ())
    for violation in violations[:8]:
        items = "; ".join(item.get("description", "")
                          for item in violation.get("items", ()))
        problems.append(
            f"DRC [{violation.get('type')}]: {violation.get('description')} "
            f"-- {items}")
    if len(violations) > 8:
        problems.append(f"... and {len(violations) - 8} more DRC violations")

    unconnected = len(report.get("unconnected_items", ()))
    if unconnected != UNROUTED_ITEMS:
        problems.append(
            f"DRC reports {unconnected} unconnected items and "
            f"verify.UNROUTED_ITEMS declares {UNROUTED_ITEMS} -- if copper has "
            f"been routed, bring the number down with it; if a net has "
            f"appeared, it has not been routed yet")
    return problems


def check_rules(project, board):
    """The rules DRC enforces are the rules rules.py declares, read off disk.

    **This check was named in gen_pcb.py's docstring -- "check_rules() in
    verify.py is what stops the discipline from decaying into a comment" --
    for the whole life of the board, and it did not exist.** Nothing else in
    this repository has been so exactly its own stated failure mode: a source
    cited and never read is what `PUMP_RULES` upstream records, and this is a
    check cited and never written, in a sentence whose subject is the danger of
    a discipline decaying into a comment.

    What it holds, and each is a way the three files have actually disagreed:

    **The project's DRC constraints are rules.py's numbers.** They were `{}`.
    gen_pcb.py sets them through pcbnew, SaveBoard() writes them into the
    project, and then gen_pcb.py re-runs gen_project.py -- for the mixer's
    reason, that SaveBoard() flattens the project -- and gen_project.py wrote
    an empty rules block straight over them. DRC ran on KiCad's defaults, which
    are zero for every width and every non-clearance distance.

    **The net classes carry the same numbers.** gen_project.py had them as
    literals and gen_pcb.py had them as constants, in two files that cannot
    import each other, and they agreed because one person typed them twice.

    **The board's own tracks and vias are the declared widths.** Read out of
    the saved board rather than out of route.py, because what is being checked
    is what was written -- the same reason the rest of this file reads KiCad's
    netlist instead of design.py.

    **And the fabricator's published minimums**, via rules.check_fab_class(),
    so that tightening a number here cannot quietly leave the class the board
    can be ordered at.

    What this deliberately does *not* check is that the Power net class's
    0.5 mm track width appears anywhere in the copper. It does not: route.py
    draws every net at TRACK_MM, rails included, because a 0.5 mm track needs a
    0.7 mm grid and that grid does not route this board. POWER_TRACK_MM is what
    a rail is widened to by hand, and saying so here is the alternative to a
    check that would pass while meaning nothing.
    """
    problems = []
    rules.check_fab_class()

    document = json.loads(project.read_text())
    declared = gen_project.design_rules()
    found = document.get("board", {}).get("design_settings", {}).get("rules", {})
    for key, value in sorted(declared.items()):
        if key not in found:
            problems.append(
                f"the project declares no {key}, so DRC checked it against "
                f"KiCad's default of zero -- gen_project.design_rules() is "
                f"what writes it, and gen_pcb.py re-running this file after "
                f"SaveBoard() is what used to delete it")
        elif not math.isclose(float(found[key]), value, rel_tol=1e-9):
            problems.append(
                f"the project's {key} is {found[key]} and rules.py says "
                f"{value}")

    classes = {row["name"]: row
               for row in document.get("net_settings", {}).get("classes", ())}
    expected = {"Default": (rules.TRACK_MM, rules.CLEARANCE_MM),
                "Power": (rules.POWER_TRACK_MM, rules.CLEARANCE_MM)}
    for name, (track, clearance) in sorted(expected.items()):
        row = classes.get(name)
        if row is None:
            problems.append(f"the project has no {name!r} net class")
            continue
        for key, value in (("track_width", track), ("clearance", clearance),
                           ("via_diameter", rules.VIA_DIAMETER_MM),
                           ("via_drill", rules.VIA_DRILL_MM)):
            if not math.isclose(float(row.get(key, 0.0)), value, rel_tol=1e-9):
                problems.append(
                    f"net class {name!r} has {key} {row.get(key)} and rules.py "
                    f"says {value}")

    tree = sexp.parse(board.read_text())
    widths = set()
    for segment in sexp.find_all(tree, "segment"):
        widths.add(round(float(sexp.find(segment, "width")[1]), 6))
    if widths - {round(rules.TRACK_MM, 6)}:
        problems.append(
            f"the board carries tracks {sorted(widths)} mm wide and rules.py "
            f"declares {rules.TRACK_MM} mm -- route.py draws one width")
    via_sizes = set()
    for via in sexp.find_all(tree, "via"):
        size = sexp.find(via, "size")
        drill = sexp.find(via, "drill")
        via_sizes.add((round(float(size[1]), 6), round(float(drill[1]), 6)))
    if via_sizes - {(round(rules.VIA_DIAMETER_MM, 6),
                     round(rules.VIA_DRILL_MM, 6))}:
        problems.append(
            f"the board carries vias {sorted(via_sizes)} and rules.py declares "
            f"{rules.VIA_DIAMETER_MM}/{rules.VIA_DRILL_MM} mm")
    return problems


def check_ground_split_on_the_board(board):
    """The two ground pours do not overlap, which DRC will not tell you.

    **STYLE.md names this one and the mixer's verify.py holds the same
    property.** Two zones on one layer with different nets fill straight
    through each other and DRC says nothing -- each zone is, after all,
    correctly connected to its own net. What you get is MAGND and MDGND shorted
    over whatever area they share, a board that measures as one ground, and a
    hum whose cause is invisible in every file the project produces.

    So it is geometry: read the zone outlines back out of the saved board and
    assert that no MAGND rectangle intersects an MDGND one, on the same layer.
    Read from the file rather than from placement.py, because what matters is
    what was written -- the same reason verify.py reads KiCad's netlist rather
    than design.py's.
    """
    tree = sexp.parse(board.read_text())
    zones = []
    for zone in sexp.find_all(tree, "zone"):
        net = sexp.find(zone, "net")
        layer = sexp.find(zone, "layer")
        points = sexp.find(sexp.find(zone, "polygon"), "pts")
        corners = [(float(xy[1]), float(xy[2]))
                   for xy in sexp.find_all(points, "xy")]
        xs = [x for x, _ in corners]
        ys = [y for _, y in corners]
        zones.append((str(net[1]), str(layer[1]),
                      (min(xs), min(ys), max(xs), max(ys))))

    problems = []
    if not zones:
        problems.append("the board carries no ground zones at all")
    for index, (net, layer, box) in enumerate(zones):
        for other, other_layer, box2 in zones[index + 1:]:
            if layer != other_layer or net == other:
                continue
            if (box[0] < box2[2] and box2[0] < box[2]
                    and box[1] < box2[3] and box2[1] < box[3]):
                problems.append(
                    f"{net} and {other} overlap on {layer}: {box} against "
                    f"{box2} -- two zones on one layer fill through each "
                    f"other and DRC will not say a word")
    gap = design.CHANNELS and placement.GROUND_GAP
    for net, layer, box in zones:
        if net not in ("MAGND", "MDGND"):
            problems.append(
                f"a zone on {layer} belongs to {net}, which is not one of the "
                f"two grounds -- a pour on a signal net is a plane nobody "
                f"asked for")
    return problems


def check_reference_load(nets, values):
    """What KiCad found on VREF is a capacitive load the MAX6126 is qualified for.

    First-hand from the pinned datasheet (19-2647 Rev 8): page 4 gives a
    "Capacitive-Load Stability Range" of 0.1 to 10 uF, qualified "no sustained
    oscillations", and page 16 states it as a requirement -- "The MAX6126
    requires an output capacitor between 0.1uF and 10uF" -- then recommends "a
    10uF capacitor in parallel with a 0.1uF capacitor" for switching loads.

    **The fault this exists for was fitted and shipped in the netlist for the
    whole life of the design: 20.1 uF, two 10 uF reservoirs, 2x the qualified
    load.** Nothing could see it, and the reason is worth keeping. The value
    strings were correct, so a BOM check passed. Each capacitor was individually
    reasonable, so reading the schematic passed. ERC counts pins and not farads.
    The netlist comparison proves the drawing matches design.py, and design.py
    was what was wrong -- which is the shape the mixer records twice, at
    DIODE_PINS and CAP_PINS. What was missing was any check that read a *sum*.

    Deliberately reads the exported netlist and its component values rather than
    design.reference_load(), for the reason the rest of this file was repointed
    at KiCad: a check that reads the same module it is checking cannot catch a
    fourth capacitor drawn onto VREF. design.classify_reference_load() holds the
    datasheet's topology and this feeds it what KiCad actually parsed.
    """
    problems = []
    fitted = {}
    for ref, _ in nets.get("VREF", ()):
        if not ref.startswith("C"):
            continue
        value = values.get(ref)
        if value is None:
            problems.append(f"{ref} is on VREF and the netlist gives no value")
            continue
        try:
            fitted[ref] = kisim.magnitude(value)
        except Exception:
            problems.append(
                f"{ref} on VREF has value {value!r}, which does not parse as a "
                f"capacitance -- the stability range cannot be checked")
    if not fitted:
        return problems + ["VREF carries no capacitor at all"]

    verdict = design.classify_reference_load(fitted)
    problems.extend(verdict["problems"])

    # And the design's own numbers must agree with the drawing's, so the two
    # cannot drift apart quietly in either direction.
    #
    # Compared with a tolerance, not with `!=`. The two totals are the same
    # 10.1 uF arrived at by different arithmetic -- these from parsing "10u" and
    # "100n" out of the netlist, design.py's from adding two float constants --
    # and they differ in the sixteenth digit. Exact float equality reported a
    # disagreement between two numbers that print identically, which is the
    # second time the same trap has bitten in this one check: see
    # design.classify_reference_load() for the first, on the 0.1 uF boundary.
    # 1e-9 relative is far tighter than any capacitor and far looser than float
    # noise.
    intended = design.reference_load()
    if not math.isclose(verdict["total_farads"], intended["total_farads"],
                        rel_tol=1e-9):
        problems.append(
            f"KiCad found {verdict['total_farads'] * 1e9:.1f} nF on VREF and "
            f"design.reference_load() intends "
            f"{intended['total_farads'] * 1e9:.1f} nF")
    return problems


def run_erc(schematic, destination):
    """KiCad's own electrical rules check, as JSON. Regenerated every run."""
    result = subprocess.run(
        [str(kicad.KICAD_CLI), "sch", "erc", "--severity-all", "--format",
         "json", "-o", str(destination), str(schematic)],
        capture_output=True, text=True)
    if not destination.exists():
        raise SystemExit(f"erc failed:\n{result.stdout}\n{result.stderr}")
    report = json.loads(destination.read_text())
    return [violation for sheet in report.get("sheets", ())
            for violation in sheet.get("violations", ())]


# The ERC violations this sheet is expected to still have, with the reason for
# each and the exact count. Anything outside this table fails, and so does a
# different count of anything inside it.
#
# **This is an allow-list and it is worth being uncomfortable about, so here is
# the argument.** "ERC clean" on a half-drawn board cannot mean zero violations,
# because some of what ERC reports on a half-drawn board is true. The choice is
# between silencing those rules in the project file, where nobody would ever see
# them again, and writing down what is expected so that the *next* one fails the
# build. Pinning the count is what makes this stricter than "ignore
# missing_unit": one more unplaced section moves the number and this stops.
#
# What it does not do is tolerate errors. Any violation at error severity fails
# regardless of type, because there is no error in this list and there should
# never be one: the four that were here (two power-flag conflicts, the spare
# cells' grounded outputs, two unconnected '541 outputs) were all real, and all
# four were fixed rather than listed.
#
# **It is empty, and emptying it is the check earning its keep.** It carried two
# entries -- `missing_unit` and `missing_input_pin`, three of each -- both
# describing the same six op-amp sections: U2, U4 and U6 C and D, reserved for
# the envelope rectifier and not drawn. The rectifier is drawn now and those six
# sections carry its summing stages, so the warnings are gone. Because the counts
# were pinned rather than the classes silenced, this file *failed* on the next
# run instead of passing quietly with a stale excuse, and the message it printed
# was the instruction: "if that is because the block landed, delete the entry".
#
# Zero errors and zero warnings is a stronger claim than the six-warning version
# and a more fragile one. The next deferred block to land will probably reopen
# this table; what matters when it does is that the count goes back in with it.
ERC_ALLOWED = {}



def check_erc(violations):
    """KiCad's ERC finds nothing but the residue this file declares.

    Runs on every build rather than by hand, because the report was unreadable
    until this pass and unreadable checks stop being read. Before the project
    file existed it carried 583 violations, 539 of them one per symbol saying
    the library configuration was missing -- and the three real errors hiding in
    that were a pin type stated wrong, a power flag on a driven net, and two
    unconnected outputs.
    """
    problems = []
    counts = {}
    for violation in violations:
        kind = violation.get("type", "?")
        counts[kind] = counts.get(kind, 0) + 1
        if violation.get("severity") == "error":
            problems.append(
                f"ERC error [{kind}]: {violation.get('description')} -- no ERC "
                f"error is expected on this sheet, and none is listed in "
                f"ERC_ALLOWED")

    for kind, seen in sorted(counts.items()):
        if kind not in ERC_ALLOWED:
            problems.append(
                f"ERC reports {seen} x [{kind}], which ERC_ALLOWED does not "
                f"declare -- fix it, or write down why it is expected")
            continue
        expected, _ = ERC_ALLOWED[kind]
        if seen != expected:
            problems.append(
                f"ERC reports {seen} x [{kind}] and ERC_ALLOWED expects "
                f"{expected} -- the residue moved, so something changed that "
                f"the reason no longer covers")
    for kind, (expected, _) in sorted(ERC_ALLOWED.items()):
        if kind not in counts:
            problems.append(
                f"ERC_ALLOWED expects {expected} x [{kind}] and ERC reports "
                f"none -- if that is because the block landed, delete the entry")
    return problems


def check_open_pins(open_pins):
    """The pins KiCad found open are exactly the pins design.py declares open.

    **The check that stops a no-connect flag from meaning more than it should.**
    KiCad has two states for a pin, connected and flagged open, so a coil
    waiting on a driver that is not drawn yet has to borrow the flag that means
    "open on the finished board". design.NO_CONNECT and design.DEFERRED_PINS are
    what distinguish them; this is what makes the distinction load-bearing.

    Held as an equality in both directions, which is what makes it worth
    running. A pin open on the sheet and declared nowhere is a forgotten wire --
    the sheet flagged two VCA MODE pins and two spare control pins for its whole
    life without design.py being asked. A pin declared open and not open in
    KiCad's netlist is the opposite fault and is the one that actually happened:
    every coil return was quietly wired to MDGND while the design said nothing
    about coils at all, and each of those pins would fail here.

    **design.DEFERRED_PINS is empty as of the coarse pad's deletion**, since all
    48 entries were that pad's relay coils. The check is unchanged and both
    directions still hold; what it has lost is a planted fault for its third
    clause, which test_verify.py says out loud rather than replacing with a
    synthetic one.

    Then two things about the declarations themselves. Every deferred pin names
    a block that is still in design.DEFERRED, so a block landing cannot leave
    pins still declared as waiting for it. And no pin is in both
    tuples, because "open on the finished board" and "not connected yet" are
    contradictory claims and a pin holding both says nothing.
    """
    problems = []
    permanent = {(ref, str(pin)) for ref, pin in design.NO_CONNECT}
    deferred = {(ref, str(pin)) for ref, pin in design.DEFERRED_PINS}
    declared = permanent | deferred

    for ref, pin in sorted(open_pins - declared):
        problems.append(
            f"KiCad found {ref}.{pin} on nothing, and design.py declares it "
            f"neither in NO_CONNECT nor in DEFERRED_PINS -- which of the two "
            f"is it")
    for ref, pin in sorted(declared - open_pins):
        problems.append(
            f"design.py declares {ref}.{pin} open and KiCad did not find it "
            f"open -- something on the sheet connects a pin the design says is "
            f"not connected")

    for (ref, pin), block in sorted(design.DEFERRED_PINS.items()):
        if block not in design.DEFERRED:
            problems.append(
                f"{ref}.{pin} waits on {block!r}, which is not in "
                f"design.DEFERRED -- either that block landed and this pin was "
                f"not connected with it, or the name is a typo")

    both = sorted(permanent & deferred)
    if both:
        problems.append(
            f"{both} are in both NO_CONNECT and DEFERRED_PINS -- open on the "
            f"finished board and not connected yet are different claims")
    return problems


CHECKS = (
    ("1  no load on the mixer's rails", check_no_mixer_rail_load, ("nets",)),
    ("2a exactly one ground bond", check_one_ground_bond, ("nets",)),
    ("2b six shields, one per pin-3", check_shield_returns, ("nets",)),
    ("3  SIN{n} DC vs the mixer's own", check_sin_dc_by_construction,
     ("nets", "values")),
    ("4  PIN{n} load keeps the corner", check_pin_load, ("nets", "values")),
    ("5  shielded pairs, one end [practice]", check_triads, ("nets",)),
    ("   R_IN fixed, equal to R_OUT, unloaded", check_gain_chain,
     ("nets", "values")),
    ("   envelope diodes point the right way", check_rectifier_polarity,
     ("nets", "values")),
    ("   de-energised is bypass", check_fail_safe, ("nets", "values")),
    ("   open pins are the declared ones", check_open_pins, ("open_pins",)),
    ("   ERC finds only declared residue", check_erc, ("violations",)),
    ("   VREF load inside the MAX6126's range", check_reference_load,
     ("nets", "values")),
    ("   DRC clean, unrouted count declared", check_board, ("drc",)),
    ("   the two pours do not overlap", check_ground_split_on_the_board,
     ("board",)),
    ("   DRC's rules are rules.py's rules", check_rules, ("project", "board")),
)


def main():
    export_netlist(SHEET, NETLIST)
    nets = read_netlist(NETLIST)
    values = read_components(NETLIST)
    context = {"nets": nets, "values": values,
               "open_pins": read_open_pins(NETLIST),
               "violations": run_erc(SHEET, ERC),
               "drc": read_drc(PCB, DRC),
               "board": PCB, "project": PROJECT}

    print(f"verify: {SHEET.name} -> {NETLIST.name}, against "
          f"hardware-spec-v0.md section 5")
    print(f"        KiCad {kicad.version()}, mixer contract at {socket.PIN[:7]}")
    print()

    problems = compare(nets, design.NETS)
    print(f"  {'KiCad geometry matches design.py':<38} "
          f"{'ok' if not problems else str(len(problems)) + ' problems'}")
    for problem in problems[:8]:
        print(f"      {problem}")

    failures = list(problems)
    for label, function, wants in CHECKS:
        found = function(*[context[w] for w in wants])
        failures.extend(found)
        print(f"  {label:<38} {'ok' if not found else str(len(found)) + ' FAIL'}")
        for problem in found:
            print(f"      {problem}")

    print()
    unresolved = design.DESIGN.unresolved_pins()
    if unresolved:
        print(f"  {sum(len(v) for v in unresolved.values())} pins are still "
              f"roles on {len(unresolved)} parts declared in "
              f"design.UNSPECIFIED:")
        for value, reason in sorted(design.UNSPECIFIED.items(),
                                    key=lambda kv: str(kv[0])):
            print(f"      {value}: {reason}")
    if design.DEFERRED:
        print(f"  {len(design.DEFERRED)} blocks deferred, so section 5 is "
              f"checked against a partial board:")
        for block, reason in sorted(design.DEFERRED.items()):
            print(f"      {block}: {reason}")

    print()
    if failures:
        raise SystemExit(f"{len(failures)} problems")
    print("all five constraints hold on what is drawn so far")


if __name__ == "__main__":
    main()
