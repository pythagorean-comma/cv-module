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


def check_module_star(nets):
    """Exactly one part bridges MAGND and MDGND, and it is R902.

    **The module's own star, which had no check until a part arrived that
    could break it.** check_one_ground_bond() holds the bond to the *mixer*
    and constraint 5.2 is about that one; this is the boundary inside this
    board, the one floorplan.py's whole zone argument is built on, and until
    now nothing asserted it. It survived unasserted because no part had two
    ground pins: the '541 and the relays straddle the line in *signals*, and
    their grounds are all MAGND.

    The envelope ADC is the first part with an AGND pin and a DGND pin, and
    its own datasheet offers two ways to wire them. Section 7.3's first scheme
    -- two supplies, two grounds, joined at their own star -- is the textbook
    one and is wrong here, because this board already has a star and a second
    one is a second join between two domains. The second scheme, "consider the
    MCP3561/2/4 as an analog component, and therefore, connect AVDD to DVDD
    and AGND to DGND", is what design.envelope_adc() draws.

    **The fault it exists for draws correctly and measures correctly.** DGND
    to MDGND is what a careful person does with a pin called DGND; it looks
    tidier than the alternative, ERC is silent because both are ground nets,
    DRC is silent because both pours exist, and the board works. What it makes
    is a second conductor between the two returns, in parallel with R902 and
    tens of millimetres away from it -- so the two enclose a loop, and every
    milliamp of digital return current that finds it flows past six analogue
    channels on its way home. That is the failure the split exists to prevent,
    arriving through the one pin that invites it.
    """
    parts_on = {}
    for name, nodes in nets.items():
        for ref, _ in nodes:
            parts_on.setdefault(ref, set()).add(name)
    bridges = sorted(ref for ref, names in parts_on.items()
                     if {"MAGND", "MDGND"} <= names)
    if bridges == [design.DOMAIN_STAR]:
        return []
    return [f"MAGND and MDGND are bridged by {bridges or 'nothing'}, expected "
            f"exactly ['{design.DOMAIN_STAR}'] -- a second bridge is a loop "
            f"between the two returns, and floorplan.CROSSING_RULE is about "
            f"what may cross it, not about how many joins there are"]


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


def check_envelope_adc(nets, values):
    """The ADC sees a divided signal, its own reference, and one ground.

    Four claims, and the first is the one that decides whether the part
    survives its first hard-picked string.

    **The divider is the right way up, and it is checked by arithmetic rather
    than by reference.** R{n}56 and R{n}57 are two resistors in a potential
    divider, and swapped they are still two resistors in a potential divider:
    the sheet is identical, the netlist has the same parts on the same three
    nodes, and every value string is one the BOM already carries. What changes
    is the ratio, from 0.185 to 0.815 -- so the 11.65 V that stage B can
    produce arrives at the pin as 9.5 V instead of 2.15, against an absolute
    maximum of AVDD + 0.1. That is a destroyed part rather than a wrong
    reading, and no instrument other than this one computes the number. So
    this reads the *values KiCad exported* and does the division, which is
    what makes it a check on the board rather than a restatement of
    design.envelope_adc_input().

    **ENVA{n} carries exactly three parts and the converter.** Anything else
    on it is a load on a divider whose ratio the whole protection argument
    rests on.

    **The reference is VREF and not the rail.** REFIN+ on V3V3 would work,
    would read, and would make the envelope's full scale an LDO's tolerance
    instead of a 2.5 V reference -- and it would quietly falsify
    floorplan.CROSSING_RULE's "the ADC's own reference is VREF", which is a
    sentence this design chose a part to honour.

    **And the two spare channels are grounded.** CH6 and CH7 are analogue
    inputs inside a multiplexer the firmware can be told to scan; left open
    they are floating nodes that read as noise, and DS20006181C's own note
    asks for AGND on an unconnected pin.
    """
    problems = []
    ref = design.ENV_ADC_REF
    P = design.ENV_ADC_PINS
    expected = {str(P["REFIN+"]): "VREF", str(P["REFIN-"]): "MAGND",
                str(P["AGND"]): "MAGND", str(P["DGND"]): "MAGND",
                str(P["AVDD"]): "V3V3", str(P["DVDD"]): "V3V3",
                str(P["SCK"]): "SCLK", str(P["SDI"]): "MOSI",
                str(P["SDO"]): "MISO", str(P["CS"]): "CS",
                str(P["MCLK"]): "MCLK", str(P["IRQ"]): "IRQ"}
    for name in design.ENV_ADC_GROUNDED:
        expected[str(P[name])] = "MAGND"
    for n in range(1, design.CHANNELS + 1):
        expected[str(P[design.ENV_ADC_CHANNEL[n]])] = f"ENVA{n}"
    found = {pin: net for net, entries in nets.items()
             for part, pin in entries if part == ref}
    for pin, net in sorted(expected.items(), key=lambda kv: int(kv[0])):
        if found.get(pin) != net:
            problems.append(
                f"{ref}.{pin} is on {found.get(pin)!r} and should be {net!r} "
                f"-- the pin map is design.ENV_ADC_PINS, page 3 of "
                f"DS20006181C")

    ceiling = design.RAILS["V3V3"] + design.ENV_ADC_INPUT_MARGIN
    swing = design.MODULE_RAIL - design.OPAMP_SWING_HEADROOM
    for n in range(1, design.CHANNELS + 1):
        node = f"ENVA{n}"
        want = {f"R{n}56", f"R{n}57", f"C{n}52", ref}
        carried = {part for part, _ in nets.get(node, ())}
        if carried != want:
            problems.append(
                f"{node} carries {sorted(carried)}, expected {sorted(want)} "
                f"-- anything else on it moves the ratio the ADC's absolute "
                f"input rating depends on")
        top_ends = {name for name, entries in nets.items()
                    if any(part == f"R{n}56" for part, _ in entries)}
        bottom_ends = {name for name, entries in nets.items()
                       if any(part == f"R{n}57" for part, _ in entries)}
        if top_ends != {f"ENV{n}", node} or bottom_ends != {node, "MAGND"}:
            problems.append(
                f"the channel {n} divider spans {sorted(top_ends)} and "
                f"{sorted(bottom_ends)}, expected {sorted({f'ENV{n}', node})} "
                f"and {sorted({node, 'MAGND'})}")
            continue
        try:
            top = kisim.magnitude(values[f"R{n}56"])
            bottom = kisim.magnitude(values[f"R{n}57"])
        except Exception as error:
            problems.append(
                f"channel {n}'s divider values do not parse ({error!r}) -- "
                f"the absolute input rating cannot be checked")
            continue
        at_pin = swing * bottom / (top + bottom)
        if at_pin > ceiling:
            problems.append(
                f"channel {n} presents {at_pin:.2f} V at {ref}."
                f"{P[design.ENV_ADC_CHANNEL[n]]} when stage B is at its rail "
                f"({swing:.2f} V), against an absolute maximum of "
                f"{ceiling:.2f} V -- see design.envelope_adc_input(); the "
                f"divider is the protection and it is the only protection")
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
    role, per design.diode_pins() -- which asks the part's own footprint which
    of the two pin maps it is on, because three of the diodes here are SOT-23
    and one is SOD-123F, and a check that names one map is a check that goes
    stale the day a package moves.

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
        for pin, net in ((design.RELAY_PINS["COIL+"], "VMOD"),
                         (design.RELAY_PINS["COIL-"], "FSD")):
            if (ref, str(pin)) not in nets.get(net, ()):
                problems.append(f"{ref}.{pin} is not on {net}")
        for role, net in (("A", "FSD"), ("K", "VMOD")):
            if (diode, str(design.diode_pins(diode)[role])) not in nets.get(net, ()):
                problems.append(
                    f"{diode}'s {'anode' if role == 'A' else 'cathode'} is not "
                    f"on {net} -- a flyback the wrong way round is a short "
                    f"across {design.BYPASS_COIL_V:.0f} V through the drain")

    for diode, anode, cathode in (("D801", "MDGND", "FSAC"),
                                  ("D802", "FSAC", "FSG"),
                                  ("D803", "VREFN", "MAGND")):
        for role, net in (("A", anode), ("K", cathode)):
            if (diode, str(design.diode_pins(diode)[role])) not in nets.get(net, ()):
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
#
# **It went to eight and it is back to zero, and the route between those two
# numbers is the most useful thing in this file's history.** Both ends are at
# the envelope ADC, and what happened in between was one symptom read four ways.
#
# The four nets were ENVA1, ENVA2, MISO and MOSI -- two channel dividers into
# CH0 and CH1, two SPI lines into SDO and SDI. The symptom was unrouted nets at
# a package, and it read first as congestion, then as too little room, then as
# the wrong rotation; three placements were tried and the count went 4, 3, 2.
# Then **DRC** reported eight clearance violations at 0.15 mm against a 0.2 mm
# rule, and the real fault was visible: the router had been *drawing* the
# connections it could not legally make, through cells exempted from clearance
# because they are a pad's own copper. The exemption is about the pad and what
# gets drawn is a track. route.Grid.block_pad_copper() is where that is now
# recorded, and inseting the exemption by half a track is what took the count
# from "six connections drawn wrong" to "eight connections unmade and named".
#
# **What closed it is a fan-out pass**, and three things about it are worth
# carrying past a compaction:
#
#   * **the escape is fixed copper on the pad's own centre line**, laid before
#     route_all() runs, turning for the grid only once it is clear of the pin
#     row. Inside the row it is the safest track on the board, because it is
#     exactly where the pad already is. route.Grid.escape();
#   * **which pads get one is route.access()'s own answer**, not a prediction.
#     The first attempt computed rules.track_offset_limit() a second time
#     beside the function it had to agree with, and the second opinion was
#     wrong -- it measured from the pad's *centre line*, which is the only
#     candidate a TSSOP pin has and one of a hundred an NCP1117's DPAK tab has,
#     so it declared the 5 V regulator unreachable and refused its escape;
#   * **there is a third box, and three boxes were three answers.** The pad's
#     bounding box says a cell is within 0.200 mm of the centre line; inset by
#     half a track it says 0.075; the clearance to the next pin says 0.125. The
#     check that existed to predict this number measured the first, access()
#     used the second, and DRC uses the third -- so the check passed on four
#     pads the router then refused, and this constant was eight while the
#     instrument written to explain it reported nothing.
#
# **Four escapes, all at U17, and no net given up.** 1547 track runs and 561
# vias, against 1489 and 516 with the four nets unmade -- so the escapes did
# not just close their own pads, they freed enough room for the rest of the fan
# to take shorter paths. DRC stayed at zero throughout.
#
# **And the thing the fan-out cannot reach is now arithmetic rather than a
# surprise.** rules.fan_out_class() is a ladder: above `grid + clearance` of
# pitch a track starts inside the pad; between `grid` and that, an escape
# reaches it; below `grid`, two pins have to share one grid line and nothing
# this router draws gets there. The RP2040's 0.40 mm QFN-56 is the third rung
# and design.controller_package() is where that is priced.
# **It is 10 and every one is V5, and the number went up because the router
# started modelling a rule it had always broken.** Correcting via clearance --
# rules.via_exclusion(), three distances rather than a ring of four cells -- costs
# the fitted class the 5 V rail and 5x the routing time. Measured, all four
# combinations, gen_pcb.py end to end:
#
#     class          via rules      time     unrouted   DRC violations
#     0.25/0.20 2oz  ring of four    89 s        0            0
#     0.09/0.09 1oz  ring of four    69 s        0           56
#     0.25/0.20 2oz  corrected      454 s       10 (V5)       0
#     0.09/0.09 1oz  corrected       89 s        0            0
#
# **The board that used to close was closing on geometry the router had no rule
# for**, and DRC agreed because the two illegal cases -- a via inside the annulus
# 0.325 to 0.5 mm from a foreign pad, and two vias on diagonal cells 0.707 mm
# apart against a 0.8 mm requirement -- were never attempted at that grid. They
# were latent, not absent. So this number going from 0 to 10 is the router
# becoming honest, and the rule this file runs on says it may: **down as copper is
# laid, up only with the nets named.** V5 is the name.
#
# **And the last row is the class decision, answered by measurement.** Only
# 0.09/0.09 gives a complete DRC-clean board once via clearance is modelled, and
# it does it in 89 s with no fan-out escape anywhere. That is a fabrication
# decision -- 0.09/0.09 is 1 oz outer copper only -- so it is not taken here;
# rules.COPPER_OZ and the two constants above it are the one-line change, and
# design.controller_package() carries what it buys.
# **Back to 0, and the way it got there is the record worth keeping.** It was 10
# in the two hours between the via rules being corrected and the fabrication
# class being decided -- V5, the 5 V rail, which the coarse class could not close
# once route.py stopped placing vias it had no rule for. The table above is why
# the class moved; rules.COPPER_OZ carries the decision.
# ======================================================================
# **And then the router was deleted, so this number means something else.**
#
# Everything above is the record of a generated board and it is kept whole,
# because it is where six real findings came from and because the arithmetic
# in it is still true. What is no longer true is its subject. gen_pcb.py places
# and pours and lays no signal copper; the board is routed elsewhere -- by
# route.py once as a seed, by KiCadRoutingTools through krt.py, or by a person
# in KiCad -- and out/cv-module.kicad_pcb in this repository is whatever state
# that copper has reached. Every net on it today was laid by the tool.
#
# **So the declaration below is a progress marker, and the check around it is
# a ratchet.** It comes down as copper is laid and it may not go up without the
# reason being written here, which is exactly the rule this number has always
# run on, applied to a person instead of to a router:
#
#     **down as copper is laid, up only with the nets named.**
#
# **Zero, and the board it counts is the seeded one.** `gen_pcb.py
# --discard-routing --seed-routing` was run once: 290 footprints, 151 ground
# stitches, 1652 track runs and 595 vias, **0 unconnected items and 0 DRC
# violations**. The stale bfa4483 board this number used to describe is gone,
# and with it check_board_is_the_design()'s failure -- the board is the design
# for the first time.
#
# **Zero at the start of hand-routing is not the same claim as zero at the end
# of it, and the ratchet is what keeps the two apart.** What is on disk is a
# *seed*: legal, closed, and laid by a maze router that optimises path cost
# and knows nothing about which nets are audio, where a return current wants
# to go, or which of two equal paths runs beside the switcher. Every one of
# those is a reason to move copper, and moving copper can leave a connection
# open. So this number may go up -- and only with the nets named here, which
# is the rule it has always run on:
#
#     **down as copper is laid, up only with the nets named.**
#
# **It is still the gate on fabrication.** design.DEFERRED and
# design.UNSPECIFIED are both empty, every part has a footprint, and
# gen_plots.orderable() reads both -- and now this as well, which is the one
# thing between this repository and a gerber set.
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

    **This paragraph used to excuse a width that no longer exists.** It read:
    the Power class's 0.5 mm "does not appear anywhere in the copper ...
    POWER_TRACK_MM is what a rail is widened to by hand". That was a fact about
    *route.py* -- which could not draw 0.5 mm on its grid -- written where it
    reads as a fact about the board, which is the shape floorplan.CROSSING_RULE
    records one artefact along. A router that reads net classes arrived and
    would have drawn it, and design.power_track_verdict() then priced the
    widening at 7.96 dB against 94.8 dB of margin. The constant is gone; both
    classes declare TRACK_MM, and the assertion below that the board carries
    exactly one width is now a check on something rather than an excuse.
    """
    problems = []
    # **Reported, not raised.** rules.check_fab_class() raises, because every
    # other caller is about to write copper and should stop. A check in this
    # file returns a list, and one that throws takes the whole run with it --
    # which is what it did the moment rules.FABRICATOR became PCBWay and the
    # fitted 0.09/0.09 stopped being manufacturable: verify.py and
    # test_verify.py both died on an AssertionError instead of reporting a
    # finding, so 84 planted faults went unproven because of one true fact.
    try:
        rules.check_fab_class()
    except AssertionError as error:
        problems.append(f"{error} -- docs/fabrication-class.md is the "
                        f"decision this reopens")

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
                "Power": (rules.TRACK_MM, rules.CLEARANCE_MM)}
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


def check_stackup(board):
    """The board's stackup is rules.FAB_STACKUP, layer by layer.

    **The board had no stackup at all for the whole life of the design**, which
    is how the dielectric height stayed unchosen: KiCad supplies defaults for a
    board that does not declare one, and a default is invisible to every check
    that reads what is written. Nothing failed, because nothing asked -- no net
    here is impedance-controlled, so the only consumer was
    constraints.board_coupling(), which could not quote a height and swept a
    range instead.

    That is this repository's own recurring shape one more time: a value that
    exists only as somebody else's default cannot be wrong, the way
    RAILS["V3V3"] with no net could not be wrong and zone P with no parts could
    not be wrong. The fix is the same each time -- make it real, then check it.

    Compared by thickness and dielectric constant rather than by name, because
    the names are this file's own invention and the numbers are PCBWay's.
    """
    if not board.exists():
        raise SystemExit(f"{board} does not exist -- run gen_pcb.py")
    tree = sexp.parse(board.read_text())
    setup = sexp.find(tree, "setup")
    stackup = sexp.find(setup, "stackup") if setup is not None else None
    if stackup is None:
        return ["the board declares no stackup, so KiCad's defaults are in "
                "force and rules.FAB_STACKUP is not what will be built -- "
                "rules.apply_stackup() is what writes it"]
    found = []
    for layer in sexp.find_all(stackup, "layer"):
        thickness = sexp.find(layer, "thickness")
        if thickness is None:
            continue
        epsilon = sexp.find(layer, "epsilon_r")
        found.append((round(float(thickness[1]), 6),
                      round(float(epsilon[1]), 6) if epsilon else None))
    declared = [(round(row[2], 6), round(row[3], 6) if row[3] else None)
                for row in rules.FAB_STACKUP]
    problems = []
    if found != declared:
        problems.append(
            f"the board's stackup is {found} and rules.FAB_STACKUP declares "
            f"{declared} -- run rules.apply_stackup(); the dielectric height "
            f"is what every coupling figure on this board is computed at")
    # **And the summary field, which is a third thickness and was nobody's.**
    # `(general (thickness ...))` is what KiCad puts in the job file as
    # `BoardThickness`, so it is the figure a CAM operator is handed -- and it
    # sat at KiCad's own 1.6 while the layer table said one thing and
    # FAB_FINISHED_MM said another. Held separately from the layer rows above
    # because it is a different claim: the rows are the construction, this is
    # the finished figure the fabricator publishes for it, and the two do not
    # sum to each other because this repository has no solder-mask thickness.
    # KiCad's Board Setup recomputes this field from the stackup, so this is
    # the check that catches the dialogue having been opened.
    general = sexp.find(tree, "general")
    stated = sexp.find(general, "thickness") if general is not None else None
    if stated is None:
        problems.append("the board has no (general (thickness ...)) field, so "
                        "the job file's BoardThickness is whatever KiCad "
                        "defaults to -- rules.apply_thickness() writes it")
    elif round(float(stated[1]), 6) != round(rules.FAB_FINISHED_MM, 6):
        problems.append(
            f"the board states a finished thickness of {float(stated[1]):g} mm "
            f"and rules.FAB_FINISHED_MM is {rules.FAB_FINISHED_MM:g} -- this "
            f"is the number gen_fab.py puts in the job file, so it is what a "
            f"fabricator builds to. rules.apply_thickness() writes it")
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
        # **Rule areas are skipped, and they are not an edge case any more.**
        # A keep-out has no net and no fill -- mounts.py draws one around each
        # of the six fixings so the pours are voided where a screw passes
        # through both planes, which would otherwise bridge MAGND to MDGND at
        # every fixing and give the module six ground stars instead of one.
        # This check is about where *poured copper* is, so a zone with no net
        # is not its subject. It read net[1] unconditionally until the first
        # board-level rule area existed, and then it did not fail -- it raised
        # a TypeError, which is the loud version and the lucky one.
        if net is None or sexp.find(zone, "keepout") is not None:
            continue
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
# **Empty, and it stayed empty through the module.** The one thing that tried
# to get in here was MCU_Module:RaspberryPi_Pico typing its GND and AGND pins
# as `power_out`, which put two power outputs on MDGND against the converter's
# Com. That is a symbol modelling a module as a source of ground where this
# board uses it as a load, so it is corrected in design.patch_symbol() rather
# than declared here -- and the distinction is worth keeping: this dict is for
# residue a build is expected to carry, not for a fault with a tidy
# explanation.
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


# The primary side's nets, as a set, so that "primary" is one list in one
# place rather than a pattern each check invents. IGND is the reference and
# the other three are the inlet chain ahead of the converter.
# **VIN_J and IGND_J are here because L801 is a part and not a wire.** The
# choke splits the inlet pair into a jack side and a converter side, and both
# are primary: a check that named only the converter side would let the whole
# inlet chain be re-routed out of the isolated region without complaining.
# VIN_F is the same argument once more for F801, which splits the live
# conductor again.
#
# **It lives in design.py now and this is the name that reads it**, because
# gen_pcb.py needs the same list to reserve the primary's corner from the
# router and the two files cannot import each other. Kept as a module-level
# name here rather than spelled design.PRIMARY_NETS at each use, so that what
# moved is where the list is declared and not which checks consult it.
PRIMARY_NETS = design.PRIMARY_NETS

# How far non-primary copper has to stay out of the primary's region. Not a
# creepage figure -- at 20 V across a barrier rated 1600 VDC, creepage is not
# what is short. It is the pour gap placement.GROUND_GAP already uses, asserted
# from the other side: the point is that the region is *empty*, and a millimetre
# is enough to make "empty" mean something a saved board can be measured for.
ISOLATION_MM = 1.0


def check_supply(nets, values):
    """The converter is wired as its own pinout table says, and is not overrun.

    Three claims, and the third is the one a netlist can make that a datasheet
    cannot.

    **The pin map**, against design.SUPPLY_PINS, which is page 4 of the TMR 6WI
    datasheet. A dual-output SIP-8 has no pin 4 and its Com is pin 7 -- put the
    output pair on 6 and 7 instead of 6 and 8 and the board makes +12 V and 0 V
    where it should make +12 and -12, which is a fault that draws correctly, is
    the right part, and destroys every op-amp on the board the first time it is
    powered.

    **The rail filters exist and are in the right order**: R804 between the
    converter's own +Vout and VA+, not across it, with its capacitor on VA+.
    A filter drawn the other way round is a short from the rail to ground
    through 4.7 ohm, which is 2.5 A and a fire.

    **And the load is inside the part.** supply_fit() computes what the two
    outputs must deliver from what is actually on the netlist, so this asserts
    it against the datasheet's own 250 mA rather than against a remembered
    figure -- which is the check that stops being true silently as the deferred
    controller and ADC land on VA+ one part at a time.

    **A fourth now: the choke's windings, which is the one fault on this
    board that a netlist can see and a drawing cannot.** L801 has two
    windings, 1-4 and 2-3, and the inlet pair goes in at 1/2. Pair them 1-2
    and 4-3 instead and the schematic is the same four wires between the same
    four pins, ERC is silent, DRC is silent, the board works -- and the part
    is now 1 mH in series with 387 mA of supply current instead of 3.6 kohm
    across the common-mode path it was bought for. barrier_return() would go
    on reporting 1.1 uV at the bond, because it reads a constant and not the
    netlist. That is the same shape as the mixer's own DIODE_PINS: a part
    whose *connection order* carries the whole of its purpose.
    """
    problems = []
    ref = design.SUPPLY_REF
    expected = {
        str(design.SUPPLY_PINS["-Vin"]): "IGND",
        str(design.SUPPLY_PINS["+Vin"]): "VIN_P",
        str(design.SUPPLY_PINS["Remote"]): "IGND",
        str(design.SUPPLY_PINS["+Vout"]): "VA_RAW",
        str(design.SUPPLY_PINS["Com"]): "MDGND",
        str(design.SUPPLY_PINS["-Vout"]): "VN_RAW",
    }
    found = {pin: net for net, entries in nets.items()
             for part, pin in entries if part == ref}
    for pin, net in sorted(expected.items(), key=lambda kv: int(kv[0])):
        if found.get(pin) != net:
            problems.append(
                f"{ref}.{pin} is on {found.get(pin)!r} and should be {net!r} "
                f"-- the pin map is design.SUPPLY_PINS, from page 4 of the "
                f"datasheet, and pin 4 does not exist")

    for resistor, source, rail, shunt in (("R804", "VA_RAW", "VA+", "C811"),
                                          ("R805", "VN_RAW", "VA-", "C812")):
        ends = {net for net, entries in nets.items()
                if any(part == resistor for part, _ in entries)}
        if ends != {source, rail}:
            problems.append(
                f"{resistor} sits between {sorted(ends)} and should be "
                f"between {source} and {rail} -- a rail filter across the "
                f"rail is 4.7 ohm from the supply to ground")
        shunt_nets = {net for net, entries in nets.items()
                      if any(part == shunt for part, _ in entries)}
        if shunt_nets != {rail, "MDGND"}:
            problems.append(
                f"{shunt} sits between {sorted(shunt_nets)} and should be "
                f"between {rail} and MDGND -- on the filtered side, and "
                f"returning to the digital pour because this is switching "
                f"return current")

    choke = design.INLET_CHOKE_REF
    choke_expected = {
        str(design.INLET_CHOKE_PINS["L1_IN"]): "VIN_F",
        str(design.INLET_CHOKE_PINS["L1_OUT"]): "VIN",
        str(design.INLET_CHOKE_PINS["L2_IN"]): "IGND_J",
        str(design.INLET_CHOKE_PINS["L2_OUT"]): "IGND",
    }
    choke_found = {pin: net for net, entries in nets.items()
                   for part, pin in entries if part == choke}
    for pin, net in sorted(choke_expected.items(), key=lambda kv: int(kv[0])):
        if choke_found.get(pin) != net:
            problems.append(
                f"{choke}.{pin} is on {choke_found.get(pin)!r} and should be "
                f"{net!r} -- the windings are 1-4 and 2-3 (744222 datasheet, "
                f"Schematic), and pairing them 1-2/4-3 puts the choke in "
                f"series with the supply current instead of across the "
                f"common-mode path")

    # **Only the jack and the choke may touch the jack side**, which is the
    # "L801 goes first" claim made checkable. Everything else on the primary
    # -- the protection diode, the three decoupling capacitors, the converter
    # -- belongs on the converter side of the winding. Fitted the other way
    # round, with the capacitors ahead of the choke, they common the inlet
    # pair in front of it and the common-mode current never sees 1 mH: the
    # part is present, correct, the right value, and worth 0 dB.
    # design.barrier_return() would go on reporting 1.1 uV either way, because
    # it reads a constant and not a netlist.
    #
    # **This is the check the planted fault found missing.** The primary
    # allow-list below says which parts may touch a primary net and says
    # nothing about *which* primary net, so moving C807 across the winding
    # changed nothing any instrument could see.
    #
    # **F801 is the one part added to that side and it is allowed by name.**
    # The mechanism is *commoning*, not presence: a fuse is a two-terminal
    # element in one leg and shunts nothing across the pair, so it can sit in
    # front of the winding where a capacitor cannot. The allow-list is per net
    # rather than shared for the same reason -- the fuse belongs on the live
    # conductor and a fuse in the return would be a different circuit.
    inlet_side = {"VIN_J": {"J8", design.INLET_FUSE_REF},
                  "VIN_F": {design.INLET_FUSE_REF, choke},
                  "IGND_J": {"J8", choke}}
    for net, allowed in sorted(inlet_side.items()):
        strangers = sorted({part for part, _ in nets.get(net, ())} - allowed)
        if strangers:
            problems.append(
                f"{net} is on the jack side of {choke} and reaches "
                f"{strangers} -- only {sorted(allowed)} may, or the "
                f"choke's own decoupling shorts the pair in front of it and "
                f"the common-mode current never sees the winding")

    fit = design.supply_fit()
    for label, current in (("+Vout", fit["positive_ma"]),
                           ("-Vout", fit["negative_ma"])):
        if current > design.SUPPLY_IOUT_MA:
            problems.append(
                f"the converter's {label} is asked for {current:.1f} mA "
                f"against the datasheet's {design.SUPPLY_IOUT_MA:.0f} mA -- "
                f"see design.supply_fit()")
    if fit["watts"] > design.SUPPLY_WATTS:
        problems.append(
            f"the converter is asked for {fit['watts']:.2f} W against "
            f"{design.SUPPLY_WATTS:.0f} W")

    # The barrier, on the netlist. floorplan.check_isolation() makes the same
    # claim from the part side; this one makes it from the net side, and the
    # two fail differently: that one catches a part filed in the wrong domain,
    # this one catches a net that reaches across whatever its parts are called.
    for net in sorted(PRIMARY_NETS):
        entries = nets.get(net, ())
        strangers = sorted({part for part, _ in entries}
                           - set(design.ISOLATION_BRIDGE) - {ref}
                           - set(design.PRIMARY_PARTS))
        if strangers:
            problems.append(
                f"{net} is a primary net and reaches {strangers} -- only the "
                f"inlet chain, the converter and "
                f"{sorted(design.ISOLATION_BRIDGE)} may touch it")
    return problems


def _board_copper(board):
    """Every piece of copper on the saved board, as (net, ref, x, y).

    Pads carry their part's reference so that the declared barrier bridge can
    be excluded by name; tracks and vias have no part and carry None.
    """
    tree = sexp.parse(board.read_text())
    items = []
    for footprint in sexp.find_all(tree, "footprint"):
        at = sexp.find(footprint, "at")
        origin = (float(at[1]), float(at[2]))
        angle = math.radians(float(at[3]) if len(at) > 3 else 0.0)
        reference = ""
        for prop in sexp.find_all(footprint, "property"):
            if prop[1] == "Reference":
                reference = str(prop[2])
        for pad in sexp.find_all(footprint, "pad"):
            net = sexp.find(pad, "net")
            # **This skipped every pad on every board this repo has ever
            # built, and it took a second caller to find out.** The guard read
            # `len(net) < 3` with a comment saying KiCad writes
            # `(net 12 "MDGND")` on a pad and `(net "MDGND")` on a segment --
            # and the boards in this repo, including every committed one, write
            # `(net "MDGND")` on *both*. So the guard was true for every pad,
            # `items` was tracks and vias only, and check_isolation_gap() --
            # whose whole subject is where parts are -- was measuring copper
            # the router laid and nothing that was placed.
            #
            # It reported nothing wrong, which was true, and it is the third
            # variant of this repo's own failure: a check that passes because
            # what it looks for is not there to be found. Nothing else would
            # have said so; it was found by writing a second function that
            # needed pads and getting an empty list.
            #
            # Both forms are read now, and the name is the last element either
            # way. A pad with no net entry at all is still skipped, because
            # that is a pad on nothing.
            if net is None or len(net) < 2:
                continue
            local = sexp.find(pad, "at")
            lx, ly = float(local[1]), float(local[2])
            x = origin[0] + lx * math.cos(angle) + ly * math.sin(angle)
            y = origin[1] - lx * math.sin(angle) + ly * math.cos(angle)
            items.append((str(net[-1]), reference, x, y))
    # **Tracks and vias name their net; pads number it and name it.** KiCad 10
    # writes `(net "MDGND")` on a segment and `(net 12 "MDGND")` on a pad, so a
    # single accessor for both is wrong in one of the two places. Reading index
    # 1 of a pad's entry gives the number, which matches no net name, and every
    # pad then reads as being on a net called "12" -- a check that measures
    # nothing while reporting nothing.
    for segment in sexp.find_all(tree, "segment"):
        net = str(sexp.find(segment, "net")[1])
        for end in ("start", "end"):
            point = sexp.find(segment, end)
            items.append((net, None, float(point[1]), float(point[2])))
    for via in sexp.find_all(tree, "via"):
        net = str(sexp.find(via, "net")[1])
        point = sexp.find(via, "at")
        items.append((net, None, float(point[1]), float(point[2])))
    return items


def check_board_is_the_design(board):
    """The saved board holds exactly the parts design.py declares.

    **This is the instrument the hand-laid workflow needs and did not have,
    and the gap it fills was created by this pass.** Until gen_pcb.py stopped
    generating copper, the board could not drift from design.py: it was
    rewritten from it on every build, so "does the board match" was not a
    question anybody could ask wrongly. Now the board is a hand-edited file
    that survives across netlist changes, and the only thing that moves a
    netlist change onto it is a person remembering to run KiCad's **Update PCB
    from Schematic**.

    **What made it worth writing is that nothing else here would notice.**
    check_geometry() compares design.py to KiCad's export *from the
    schematic*, and the schematic is generated -- so a board that is three
    netlist revisions old passes it, every constraint check, and ERC. DRC runs
    on the board and reports against the board's own embedded netlist, which
    is the stale one, so it agrees with itself. Every green tick in this file
    would be green and the board would be for a different circuit.

    That is this repository's named failure mode arriving through a door the
    pass opened: a check believed to cover more than it does. The three that
    read the board -- this, check_isolation_gap() and
    check_ground_split_on_the_board() -- are now the only things standing
    between a stale board and a fabrication package.

    Refs **and land patterns**. Positions are deliberately not compared:
    placement.py is advisory once a person is laying the board out, and a check
    that fires every time somebody nudges a part is a check that gets switched
    off.

    **The footprint half is new and it was refs-only for a pass, which is a
    gap this repository walked straight into.** Five BAT54s moved from SOD-123
    to SOT-23 in design.py -- a two-pad land to a three-pad one, because the
    part had never been in SOD-123 -- and every check in this file stayed
    green: the refs had not changed, the netlist comes from the generated
    sheet, and DRC agrees with the board's own stale embedded netlist. The
    board would have gone to a fabricator with two-pad lands for three-lead
    parts, which is the fault the change was made to fix, now invisible.

    A ref is not a part. A part is a ref, a value and a land, and the land is
    the half that decides whether the thing in the bag can be soldered to the
    thing on the board.
    """
    problems = []
    tree = sexp.parse(board.read_text())
    on_board = set()
    lands = {}
    for footprint in sexp.find_all(tree, "footprint"):
        library = str(footprint[1])
        # **Board fixings are not the design's parts and never will be.** They
        # have no pins, no net, no BOM line and no symbol -- a mounting hole
        # is mechanical, and a netlist has nothing to say about one. Excluded
        # here by the same all-NPTH test check_mounting_holes() uses, so the
        # two agree by construction rather than by both being maintained; that
        # check is what holds them against placement.mounting_holes(), and
        # this one would otherwise report six parts "on the board and not in
        # design.py" for ever.
        pads = list(sexp.find_all(footprint, "pad"))
        if pads and all(len(pad) > 2 and str(pad[2]).startswith("np_")
                        for pad in pads):
            continue
        for prop in sexp.find_all(footprint, "property"):
            if prop[1] == "Reference":
                on_board.add(str(prop[2]))
                lands[str(prop[2])] = library
    declared = set(design.PARTS)
    missing = sorted(declared - on_board)
    extra = sorted(on_board - declared)
    if missing:
        problems.append(
            f"{len(missing)} parts are in design.py and not on the board "
            f"({', '.join(missing[:12])}"
            f"{', ...' if len(missing) > 12 else ''}) -- run KiCad's Update "
            f"PCB from Schematic against out/cv-module.kicad_sch")
    if extra:
        problems.append(
            f"{len(extra)} parts are on the board and not in design.py "
            f"({', '.join(extra[:12])}{', ...' if len(extra) > 12 else ''}) "
            f"-- the same sync, and note it will leave their copper behind: "
            f"a track whose part has gone keeps its net and stops being "
            f"anybody's subject")

    # **The board writes a lib_id and design.py writes a library path.** KiCad
    # puts `cv:TRACO_...` or `Diode_SMD:D_SOD-123` on a footprint, and
    # design.py names the same thing the same way, so these compare directly --
    # except for the project's own library, whose nickname is the one thing the
    # two spell differently. Compared on the part after the colon for that
    # reason, which is exact here because no two land patterns in this design
    # share a name across libraries.
    wrong = []
    for ref in sorted(declared & on_board):
        want = (design.PARTS[ref].footprint or "").split(":")[-1]
        got = lands[ref].split(":")[-1]
        if want and want != got:
            wrong.append(f"{ref} is on {got} and design.py says {want}")
    if wrong:
        problems.append(
            f"{len(wrong)} parts are on the wrong land pattern "
            f"({'; '.join(wrong[:6])}{', ...' if len(wrong) > 6 else ''}) -- "
            f"the same sync, KiCad's Update PCB from Schematic, and the copper "
            f"at those pads has to be re-laid because the pads have moved")
    return problems


def check_isolation_gap(board):
    """The primary's quadrant of the board holds nothing but the primary.

    **The geometric half of the isolation barrier, and it is a containment
    test rather than a distance one on purpose.** A minimum-separation check
    over every pair of copper items answers "is anything too close", which is
    a question DRC already answers for clearance and answers wrongly here --
    DRC does not know that IGND is special, so 0.20 mm satisfies it and 0.20 mm
    is not a barrier. What this asserts instead is the thing the layout is
    actually built on: primary copper lives west of placement.ISOLATION_X and
    south of ISOLATION_Y, nothing else goes there, and gen_pcb pours the
    southern MDGND as two rectangles so that no plane crosses it.

    That is a stronger claim and a cheaper one. It also fails in the direction
    that matters: a router that took one MDGND track through the primary's
    corner to save two millimetres would pass a distance check at every point
    and still put a ground plane's worth of coupling across a 50 pF barrier.

    The declared bridge is excluded by *reference*, from
    design.ISOLATION_BRIDGE, and the converter is excluded because its package
    is the barrier. Everything else is measured.
    """
    if not board.exists():
        raise SystemExit(f"{board} does not exist -- run gen_pcb.py")
    iso_x = placement.ISOLATION_X
    iso_y = placement.ISOLATION_Y
    # **The region has a southern edge and it did not use to**, which is
    # placement.isolation_south()'s own note: this was a quadrant with no
    # bottom, true only while the supply band was the southernmost thing on
    # the board. It stopped being that when the Pico got a strip below it, and
    # this check duly reported D806's VSYS and VMOD copper -- 27 mm south, in
    # the digital domain -- as inside the primary's region. It was right about
    # the region and the region was wrong.
    iso_south = placement.isolation_south()
    allowed = set(design.ISOLATION_BRIDGE) | {design.SUPPLY_REF}
    problems = []
    seen = 0
    for net, reference, x, y in _board_copper(board):
        if net in PRIMARY_NETS:
            seen += 1
            if (x > iso_x + ISOLATION_MM or y < iso_y - ISOLATION_MM
                    or y > iso_south + ISOLATION_MM):
                problems.append(
                    f"{net} has copper at ({x:.2f}, {y:.2f}), outside the "
                    f"primary's region (x <= {iso_x:.2f}, "
                    f"{iso_y:.2f} <= y <= {iso_south:.2f}) "
                    f"-- the isolated side is a place on this board, not a "
                    f"set of net names")
        elif reference not in allowed:
            if (x < iso_x - ISOLATION_MM and y > iso_y + ISOLATION_MM
                    and y < iso_south - ISOLATION_MM):
                problems.append(
                    f"{net} has copper at ({x:.2f}, {y:.2f}), inside the "
                    f"primary's region -- only {sorted(allowed)} may be "
                    f"there, and a plane or a track through it is a "
                    f"capacitor across the barrier")
    if not seen:
        problems.append(
            "no primary copper found on the board at all, which means this "
            "check passed by measuring nothing")
    return problems

def check_controller(nets, values):
    """The controller's pins carry what CONTROLLER_MAP says, and its supplies
    are the ones its own datasheet asks for.

    **Every pin on this part looks the same and that is the whole reason this
    check exists.** A QFN-56 with fourteen identical pins a side is a part
    where SCLK on GPIO14 draws exactly like SCLK on GPIO18, and only one of
    them is a pin SPI0's clock can leave by. design.Design.check_controller_
    functions() holds the *assignment* against the datasheet's Table 2; this
    holds the **board** against the assignment, which is the other half and
    the one that catches a wire rather than a table.

    Four claims:

      * **every net in CONTROLLER_MAP is on the pin the map names**, read out
        of KiCad's own netlist;
      * **the supplies are the single-3.3 V scheme of section 2.9.7.1.** All
        six IOVDD, USB_VDD, ADC_AVDD and VREG_VIN on VMCU; both DVDD and
        VREG_VOUT on VCORE and on nothing else. **VREG_VOUT is the one worth
        naming**: it is an output, and tying it to VMCU is a regulator driving
        into a rail 2.2 V above its own -- a part that would work until it did
        not;
      * **TESTEN is grounded**, which Table 619 gives as the pin's entire
        description, and the exposed pad with it;
      * **every supply pin has its own capacitor.** Section 2.9 says "close to
        each of the chip's IOVDD pins", and the reference design's own
        compromise -- one capacitor shared between pins 48 and 49 -- is
        explained there by a two-layer board this one is not. Counted rather
        than assumed, because twelve capacitors on one rail is exactly the
        kind of thing that quietly becomes eleven.
    """
    problems = []
    ref = design.CONTROLLER_REF
    found = {pin: net for net, entries in nets.items()
             for part, pin in entries if part == ref}

    for row in design.controller_pin_map():
        pin = str(row["pin"])
        if found.get(pin) != row["net"]:
            problems.append(
                f"{ref}.{pin} ({row['name']}) is on {found.get(pin)!r} and "
                f"CONTROLLER_MAP says {row['net']!r} for {row['function']} -- "
                f"the assignment is checkable because Table 2 is transcribed; "
                f"the wire is checkable because this is KiCad's netlist")

    # **The supplies, and the module made this list shorter and sharper.**
    # The QFN's version of this asked about eleven pins on the single-3.3 V
    # scheme of RP2040 section 2.9.7.1 -- six IOVDD, two DVDD, VREG_VIN,
    # VREG_VOUT, USB_VDD, ADC_AVDD -- and every one of those is now behind
    # castellations, decided by somebody else's layout and unreachable from
    # this netlist. What is left is three pins and their *directions*, which
    # is the claim that matters:
    #
    #   * **VSYS is an input and it is on VMOD**, this board's switched 5 V,
    #     through D806. On VMCU it would be the module's own output feeding
    #     its own input, and design.pico_backdrive() is where the arrangement
    #     that looks like that is refused;
    #   * **3V3 is an output and it is on VMCU**, which is where every 3.3 V
    #     part on this board hangs;
    #   * **AGND is on MDGND**, which the Pico datasheet allows in one
    #     sentence and only for an application that does not need the ADC to
    #     be quiet -- see design.controller().
    P = design.CONTROLLER_MODULE_PINS
    expected = {str(P["VSYS"]): "VSYS", str(P["3V3"]): "VMCU",
                str(P["AGND"]): "MDGND"}
    for pin in design.CONTROLLER_MODULE_GND_PINS:
        expected[str(pin)] = "MDGND"
    for pin, net in sorted(expected.items(), key=lambda kv: int(kv[0])):
        if found.get(pin) != net:
            problems.append(
                f"{ref}.{pin} is on {found.get(pin)!r} and should be {net!r} "
                f"-- Pico datasheet section 2.1, and see design.controller()")

    # **The three pins this board deliberately does not drive have to stay
    # undriven**, which is the other half of the same claim and is not covered
    # by check_open_pins(): that one asks whether a flag exists, and this asks
    # whether a *wire* has appeared. 3V3_EN is the one that matters -- driven
    # low it disables the module's converter into a rail this board is not
    # making, and driven high it fights a 100 kOhm pull-up for no reason.
    for name in ("3V3_EN", "VBUS", "ADC_VREF"):
        pin = str(P[name])
        if found.get(pin) is not None:
            problems.append(
                f"{ref}.{pin} ({name}) has acquired {found[pin]!r} -- it is in "
                f"design.NO_CONNECT with a reason, and for 3V3_EN the reason "
                f"is that pulling it low turns the module's own 3.3 V off")

    # **A count that used to be twelve capacitors and is now zero.** The
    # module carries its own decoupling -- Pico datasheet section 1, "power
    # supplies and decoupling" -- so a capacitor at U19 would be a second
    # opinion about somebody else's layout, sitting 2.54 mm further from the
    # die than theirs. The assertion is that there is *none*, because "we
    # added one for luck" is exactly how a board acquires a part nobody can
    # argue for.
    strays = sorted({part for net in ("VMCU", "VSYS")
                     for part, _ in nets.get(net, ())
                     if part.startswith("C") and 820 <= int(part[1:]) <= 834})
    if strays:
        problems.append(
            f"{strays} decouple the module's own supply pins -- the module "
            f"carries that decoupling and these would be a second opinion "
            f"about a layout this repo did not do")
    return problems


def check_controller_periphery(nets, values):
    """The module's own supply path: the ORing diode and where VSYS comes from.

    ~~The flash, the crystal and USB are wired the way their own documents
    say.~~ **All three are inside the module and this check has a different
    subject.** What it used to hold was the QSPI bus going straight across,
    the crystal's drive resistor being in series with XOUT rather than across
    it, and both USB lines carrying their 27 ohm. Every one of those was a
    claim about copper between the RP2040 and a part the Pico already has --
    laid out once by Raspberry Pi and reproduced identically forty million
    times, which is a stronger guarantee than a check here could make.

    What replaces it is the one piece of that path this board still owns, and
    it is the piece with a hazard in it:

      * **VSYS comes from VMOD through D806 and through nothing else.** The
        diode is not there for its drop -- see design.controller() -- it is
        there so that a USB cable plugged into an *unpowered* board cannot
        reach VA_RAW. Without it the path is VBUS, the module's own D1, VSYS,
        U22's output, L802, U22's SW pin, and the high-side body diode into
        VIN: a USB host on this board's twelve-volt rail. That is four parts
        deep and every one of them is doing what it is supposed to;
      * **the diode points the right way**, which is the fault DIODE_PINS
        records twice at D801 and C808 and which no other instrument here can
        see. Backwards, it is a short from VSYS to VMOD in the direction that
        matters and the board works until a cable is plugged in;
      * **nothing else is on VSYS.** A decoupling capacitor there would be the
        module's job, and anything else is a load on the wrong side of the
        diode.
    """
    problems = []
    mcu = design.CONTROLLER_REF
    P = design.CONTROLLER_MODULE_PINS
    want = {(mcu, str(P["VSYS"])), ("D806", str(design.DIODE_PINS["K"]))}
    carried = set(nets.get("VSYS", ()))
    if carried != want:
        problems.append(
            f"VSYS carries {sorted(carried)}, expected {sorted(want)} -- the "
            f"module's input and the cathode of D806, and nothing else")
    anode = {part for part, pin in nets.get("VMOD", ())
             if (part, pin) == ("D806", str(design.DIODE_PINS["A"]))}
    if not anode:
        problems.append(
            "D806's anode is not on VMOD -- reversed, the diode stops being "
            "an ORing diode and becomes a path from a USB host to VA_RAW "
            "through U22's high-side body diode")
    return problems


def check_mcu_supply(nets, values):
    """The controller's rail is a switcher, and it is fed from the right node.

    **The one thing here that would work and be wrong is the input node.**
    U22's VIN on VA+ instead of VA_RAW draws a 1.1 MHz pulse train *through*
    R804 -- the rail filter -- so the filter's own resistor develops the
    switcher's input ripple straight onto the rail the six channels share.
    Nothing downstream would notice: the netlist is well formed, the part
    works, DRC passes, and the board hums at a frequency nobody is listening
    for. design.mcu_dcdc_injection() is the arithmetic and this is the wire.

    Also checked: EN tied to VIN, which the datasheet's section 8.3.3 gives as
    the way to make the part self-starting and which is not a default -- "The
    EN pin is an input and cannot be left open or floating"; the feedback
    divider's two resistors, against the equation-7 arithmetic in
    design.mcu_dcdc_output(), because a divider swapped end for end is still a
    divider and puts 12 V into a 3.63 V absolute maximum; and that VMCU
    carries the parts mcu_rail_load() counts, which is what makes the supply
    budget a statement about this board.
    """
    problems = []
    ref = design.MCU_DCDC_REF
    Q = design.MCU_DCDC_PINS
    found = {pin: net for net, entries in nets.items()
             for part, pin in entries if part == ref}
    expected = {str(Q["VIN"]): "VA_RAW", str(Q["EN"]): "VA_RAW",
                str(Q["GND"]): "MDGND", str(Q["SW"]): "MSW",
                str(Q["CB"]): "MCB", str(Q["FB"]): "MFB"}
    for pin, net in sorted(expected.items(), key=lambda kv: int(kv[0])):
        if found.get(pin) != net:
            problems.append(
                f"{ref}.{pin} is on {found.get(pin)!r} and should be {net!r} "
                f"-- VIN is VA_RAW and not VA+, which is the difference "
                f"between the rail filter standing between this switcher and "
                f"the audio rail and it standing behind it")

    top = {part for part, _ in nets.get("VMOD", ()) if part == "R850"}
    bottom = {part for part, _ in nets.get("MFB", ())}
    if not top or bottom != {ref, "R850", "R851"}:
        problems.append(
            f"the feedback divider is R850 on VMOD and MFB and R851 on MFB "
            f"and MDGND; MFB carries {sorted(bottom)} and VMOD "
            f"{'has' if top else 'does not have'} R850")
    else:
        try:
            rfbt = kisim.magnitude(values["R850"])
            rfbb = kisim.magnitude(values["R851"])
        except Exception as error:
            problems.append(f"the feedback divider does not parse: {error!r}")
            rfbt = rfbb = None
        if rfbt and rfbb:
            volts = design.mcu_dcdc_output(rfbt, rfbb)
            if abs(volts["volts"] - design.RAILS["VMOD"]) > 0.1:
                problems.append(
                    f"R850/R851 = {values['R850']}/{values['R851']} sets VMOD "
                    f"to {volts['volts']:.2f} V, not "
                    f"{design.RAILS['VMOD']:.1f} -- equation 7, and the "
                    f"module's own ceiling on VSYS is "
                    f"{design.CONTROLLER_VSYS_RANGE[1]:.1f} V")

    # **The net this counts is VMCU and the budget it protects is now two
    # conversions away**, which is worth a sentence rather than a rename: the
    # parts on VMCU are what the module has to deliver, mcu_chain() turns that
    # into what U22 has to deliver, and supply_fit() turns *that* into the
    # converter's +Vout. A part added to VMCU silently is still a part the
    # 250 mA does not know about; it now costs about 1.4 times as much.
    counted = {part for part, _ in nets.get("VMCU", ())}
    declared = set(design.mcu_rail_load()["parts"])
    if counted != declared:
        problems.append(
            f"VMCU carries {sorted(counted - declared)} that "
            f"mcu_rail_load() does not count and misses "
            f"{sorted(declared - counted)} -- the supply budget is counted "
            f"off this net, so a part added to it silently is a part the "
            f"converter's 250 mA does not know about")
    return problems


def check_midi(nets, values):
    """The MIDI receiver breaks the loop, and nothing but the shield capacitor
    crosses it.

    **This is constraint 5.2's argument arriving from a different direction.**
    CA-033 requires the receiver to be opto-isolated and forbids a DC path
    from the MIDI IN jack's pin 2 or shield to the receiver's ground -- for
    the same reason this module has exactly one bond to the mixer: a second
    conductor to another box's ground is a loop through the audio ground. So
    the check is the same shape as check_isolation_gap()'s netlist half: the
    only thing allowed to touch both sides is the declared bridge.

    Three claims:

      * **the loop side reaches nothing of ours.** MINJ, MINA and MINK carry
        only J15, R827, D805 and the opto's own two pins;
      * **the shield's only path is C836**, which is CA-033's own optional
        capacitor and the reason it is a capacitor;
      * **the loop resistor keeps the current inside the opto's own range at
        both kinds of transmitter.** Checked by computing it rather than by
        comparing the value, because what matters is the current: design.
        midi_loop() runs all four corners -- 5 V and 3.3 V transmitters, VF at
        both extremes -- against the TLP2761's recommended 2 to 6 mA. CA-033's
        own 220 ohm passes that test with 9 % of headroom at one end; 390 is
        fitted because it centres the spread, and *this* check is what stops
        the value drifting far enough to leave the range in either direction.
    """
    problems = []
    opto = design.MIDI_OPTO_REF
    O = design.MIDI_OPTO_PINS
    ours = {"MDGND", "VMCU", "MAGND"}
    isolated = {
        "MINJ": {("J15", "1"), ("R827", "1")},
        "MINA": {("R827", "2"), ("D805", str(design.DIODE_PINS["K"])),
                 (opto, str(O["A"]))},
        "MINK": {("J15", "3"), ("D805", str(design.DIODE_PINS["A"])),
                 (opto, str(O["K"]))},
        "MINSH": {("J15", "2"), ("C836", "1")},
    }
    for net, want in sorted(isolated.items()):
        carried = {(part, pin) for part, pin in nets.get(net, ())}
        if carried != want:
            problems.append(
                f"{net} carries {sorted(carried)}, expected {sorted(want)} -- "
                f"CA-033: 'Pin 2 of the MIDI In connector shall not have any "
                f"DC path to the receiver's ground'")
    for net in ours:
        for part, _ in nets.get(net, ()):
            if part in ("J15", "R827", "D805"):
                problems.append(
                    f"{part} is on {net}, which is this board's ground -- it "
                    f"belongs to the transmitter's, on the far side of {opto}")
    expected = {str(O["VCC"]): "VMCU", str(O["GND"]): "MDGND",
                str(O["VO"]): "MIDI_RX"}
    found = {pin: net for net, entries in nets.items()
             for part, pin in entries if part == opto}
    for pin, net in sorted(expected.items(), key=lambda kv: int(kv[0])):
        if found.get(pin) != net:
            problems.append(
                f"{opto}.{pin} is on {found.get(pin)!r} and should be {net!r}")
    try:
        ohms = kisim.magnitude(values["R827"])
    except Exception as error:
        problems.append(f"R827 does not parse: {error!r}")
        return problems
    loop = design.midi_loop(ohms)
    if not loop["inside"]:
        problems.append(
            f"R827 = {values['R827']} puts {loop['low_ma']:.2f}-"
            f"{loop['high_ma']:.2f} mA through {opto}'s LED across the two "
            f"transmitters CA-033 allows, against a recommended "
            f"{loop['recommended'][0]:.0f}-{loop['recommended'][1]:.0f} mA -- "
            f"see design.midi_loop(), and note that CA-033's own 220 ohm is "
            f"one of the values that fails this")
    return problems


def check_midi_bypass(board):
    """U21's bypass capacitor is within the distance its datasheet states.

    **A placement rule with a number in it, so it gets a check.** The TLP2761's
    own note is not the usual decoupling advice: "A ceramic capacitor (0.1 uF)
    should be connected between pin 6 and pin 4 to stabilize the operation of a
    high-gain linear amplifier. Otherwise, this photocoupler may not switch
    properly. The bypass capacitor should be placed within 1 cm of each pin."
    That is a condition of operation with a distance attached, and a distance
    is a thing the board can be measured for -- unlike "close to the pin",
    which every other capacitor on this board has to settle for.

    Measured pad to pad off the saved board, through the same reader
    check_isolation_gap() uses. **Not through pcbnew**, which is the mistake
    the first version made: verify.py runs under the ordinary interpreter and
    `import pcbnew` fails there, so a check written that way is a check that
    raises rather than one that measures -- and it did, after every other
    check had passed.
    """
    if not board.exists():
        raise SystemExit(f"{board} does not exist -- run gen_pcb.py")
    pads = {}
    for net, reference, x, y in _board_copper(board):
        if reference:
            pads.setdefault(reference, []).append((net, x, y))
    problems = []
    opto = design.MIDI_OPTO_REF
    cap = [(x, y) for net, x, y in pads.get("C835", ())]
    supply = [(x, y) for net, x, y in pads.get(opto, ()) if net == "VMCU"]
    ground = [(x, y) for net, x, y in pads.get(opto, ()) if net == "MDGND"]
    if not cap or not supply or not ground:
        return [f"cannot measure C835 against {opto}: the board carries "
                f"{len(cap)} capacitor pads, {len(supply)} VMCU pads and "
                f"{len(ground)} MDGND pads on it"]
    for name, pins in (("VCC", supply), ("GND", ground)):
        distance = min(math.dist(pad, end) for pad in pins for end in cap)
        if distance > design.MIDI_OPTO_LOCAL_MM:
            problems.append(
                f"C835 is {distance:.1f} mm from {opto}'s {name} pad and its "
                f"datasheet asks for {design.MIDI_OPTO_LOCAL_MM:.0f} mm -- "
                f"'otherwise, this photocoupler may not switch properly'")
    return problems


# How many fixings **the board has**, in the shape UNROUTED_ITEMS is: a
# declared measure of how far the artefact is from the design, held against
# the board by the check below and gated on by gen_plots.orderable(). It is 0.
# Up as fixings are laid, and only with the pattern they were laid to.
#
# The only four unplated holes in the fabrication package belong to the
# Raspberry Pi Pico's own footprint, so a 106.9 x 233.1 mm board carrying a
# 21.8 x 9.1 x 11.2 mm converter brick, three relays and a soldered-down
# module has nothing to bolt it to anything.
#
# **Nothing here could have said so.** gen_fab.check_holes() counts the drill
# file against the board's own vias and pads and agrees with it exactly -- a
# package can be a perfect package of a board with no fixings in it.
# placement.check_placed() holds the parts the netlist declares, and a
# mounting hole is not in a netlist. The repo does carry an argument *about*
# mounting holes -- MOUNTING_IS_ISOLATED, quoting the mixer's own "four plated
# holes would be four more bridges between AGND and PGND" -- so the reasoning
# arrived from upstream at the pinned commit and the holes did not. An
# inherited argument with nothing to apply it to.
#
# **What the design asks for is placement.mounting_holes(), and it is six.**
# That was briefly written here as underivable, on the grounds that where
# fixings go is a property of an enclosure this repository does not have. The
# dependency runs the other way: the enclosure is bespoke and is drawn *after*
# this board, so the pattern is an input to it. Section 6 forbids inventing a
# value and requires deriving one that can be derived, and this one can --
# from the board's own span, thickness and courtyards. See
# placement.mounting_deflection().
MOUNTING_HOLES = 6


def check_mounting_holes(board):
    """The board's fixings, counted off the board, held against MOUNTING_HOLES.

    A fixing is a footprint whose pads are *all* non-plated: that is what
    distinguishes a mounting hole from a through-hole part, and it is why the
    Pico's own four NPTH do not count -- it has 40 electrical pads as well.

    Held in both directions, like every other ratchet here. Going up needs the
    declaration moved, which is the point at which somebody has to say where
    they went and against which enclosure.
    """
    if not board.exists():
        raise SystemExit(f"{board} does not exist -- run gen_pcb.py")
    tree = sexp.parse(board.read_text())
    fixings = []
    for footprint in sexp.find_all(tree, "footprint"):
        pads = list(sexp.find_all(footprint, "pad"))
        if not pads:
            continue
        if all(len(pad) > 2 and str(pad[2]).startswith("np_") for pad in pads):
            reference = None
            for prop in sexp.find_all(footprint, "property"):
                if len(prop) > 2 and str(prop[1]) == "Reference":
                    reference = str(prop[2])
            fixings.append(reference)
    if len(fixings) != MOUNTING_HOLES:
        return [f"the board carries {len(fixings)} board fixings "
                f"({', '.join(sorted(f for f in fixings if f)) or 'none'}) "
                f"and verify.MOUNTING_HOLES declares {MOUNTING_HOLES}. Up "
                f"only with the enclosure they were placed against -- see "
                f"gen_plots.orderable(), which refuses a package at zero"]
    return []


# How many parts have no designator on the silkscreen. A ratchet, in
# UNROUTED_ITEMS' shape: down as room is found, up only with the parts named.
#
# **It is 6 and they are named.** silk.py places 245 designators at 1.0 mm and
# 25 more shrunk to rules.SILK_TEXT_MIN_MM; six sit in copper too tight to
# take one at any legal size, and R656 is among them -- the ADC's input
# column, which this repo already records as the narrowest place on the board,
# where a ground stitch once missed that same resistor by 0.03 mm.
#
# The alternative was to fail the run, and 250 parts labelled with six named
# is a better board than none labelled. What this stops is the six quietly
# becoming sixty the next time somebody packs a row.
SILK_UNLABELLED = 6


def silk_reference_faults(board):
    """Silk designators printed under the part they name, and the unlabelled.

    **Two things nothing here could see, and the first one shipped.** U9 and
    U10 -- the two SSI2164s, the parts this whole board exists to drive -- had
    their designators printed *inside their own footprints*, so they would
    have been invisible the moment the chips went on. placement.REFERENCE_MOVES
    put them there: KiCad places a SOIC's reference above the body, a 90-degree
    rotation turns that to the west onto a neighbour, and the fix was an 8 mm
    nudge east that landed the text in the middle of a package 10.4 mm long.

    The comment beside that dict is exactly right and exactly one part short:
    *"a silkscreen offset is a number about two parts' positions, and it goes
    stale when either of them moves."* Two parts -- the label's owner and the
    neighbour it was moved off. It never asked about the third thing in the
    picture, which is the part the label is naming. DRC does not object,
    because silk on your own package body collides with nothing.
    """
    tree = sexp.parse(board.read_text())
    inside, unlabelled = [], []
    for footprint in sexp.find_all(tree, "footprint"):
        origin = sexp.find(footprint, "at")
        ox, oy = float(origin[1]), float(origin[2])
        # **Negated, and this is the fault returns.py already wrote down.**
        # The board's y axis points down, so a footprint's angle turns its
        # children the *other* way -- returns._rotate() takes the same minus
        # sign for the same reason, after KiCad's DRC found every rotated
        # footprint's pads mirrored. Written with the sign the wrong way here
        # first, and it reported U19's designator as printed inside the Pico
        # when it sits 0.6 mm clear of it: a check that invents a fault is
        # worse than no check, because somebody moves a part to satisfy it.
        angle = math.radians(-(float(origin[3]) if len(origin) > 3 else 0.0))
        ref = layer = None
        local = (0.0, 0.0)
        for prop in sexp.find_all(footprint, "property"):
            if len(prop) > 2 and str(prop[1]) == "Reference":
                ref = str(prop[2])
                found = sexp.find(prop, "layer")
                layer = str(found[1]) if found is not None else ""
                spot = sexp.find(prop, "at")
                if spot is not None:
                    local = (float(spot[1]), float(spot[2]))
        if ref is None or ref not in design.PARTS:
            continue
        box = placement.courtyard(ref)
        if not box:
            continue
        if "SilkS" not in layer:
            if ref not in design.SILK_NAME:
                unlabelled.append(ref)
            continue
        x = ox + local[0] * math.cos(angle) - local[1] * math.sin(angle)
        y = oy + local[0] * math.sin(angle) + local[1] * math.cos(angle)
        if box[0] < x < box[2] and box[1] < y < box[3]:
            inside.append(ref)
    return {"inside_own_part": sorted(inside),
            "unlabelled": sorted(unlabelled)}


def check_silkscreen(board):
    """The board says what it is, and every connector on it is named.

    Two halves, and the second is the one that could not have been asked
    before. `design.check_silk()` holds the *data*: every connector in the
    netlist has a SILK_NAME and every one of its pins has words in SILK_ROLE,
    so a legend cannot be drawn with a gap in it. This then reads the **board**
    and asserts the text is actually on `F.SilkS`.

    **The board had none of it and nothing here noticed for the life of the
    design.** A silkscreen is not in a netlist, so check_geometry() cannot miss
    it. DRC only sees it when it collides with something, and there was nothing
    to collide. gen_fab.package_layers() exports a layer and drops it if it
    draws nothing -- which is the one place the absence nearly surfaced, and it
    did not, because 29 footprint references were enough to keep F.SilkS
    non-empty. A layer that is not blank is not a layer that says anything.

    Names rather than positions, for check_board_is_the_design()'s reason: a
    check that fires when somebody nudges a legend is a check that gets
    switched off. What must not drift is *which* words are on the board.
    """
    problems = list(design.check_silk())
    if not board.exists():
        raise SystemExit(f"{board} does not exist -- run gen_pcb.py")
    tree = sexp.parse(board.read_text())
    on_silk = set()
    for text in sexp.find_all(tree, "gr_text"):
        layer = sexp.find(text, "layer")
        if layer is not None and "Silk" in str(layer[1]):
            on_silk.add(str(text[1]))

    wanted = {design.BOARD_OWNER, design.BOARD_NAME + "   " + design.BOARD_REV}
    wanted |= set(design.SILK_NAME.values())
    missing = sorted(wanted - on_silk)
    if missing:
        problems.append(
            f"{len(missing)} silk texts the design declares are not on the "
            f"board ({', '.join(missing[:6])}"
            f"{', ...' if len(missing) > 6 else ''}) -- run silk.py --commit")
    if not on_silk:
        problems.append(
            "the board carries no board-level silkscreen text at all: no "
            "title, no attribution, no connector legend")

    faults = silk_reference_faults(board)
    if faults["inside_own_part"]:
        problems.append(
            f"{len(faults['inside_own_part'])} silk designators are printed "
            f"inside the part they name and will be invisible once it is "
            f"fitted ({', '.join(faults['inside_own_part'][:8])}) -- see "
            f"silk_reference_faults()")
    if len(faults["unlabelled"]) != SILK_UNLABELLED:
        problems.append(
            f"{len(faults['unlabelled'])} parts have no silk designator and "
            f"verify.SILK_UNLABELLED declares {SILK_UNLABELLED} "
            f"({', '.join(faults['unlabelled'][:8])}) -- down as room is "
            f"found, up only with the parts named")
    return problems


CHECKS = (
    ("1  no load on the mixer's rails", check_no_mixer_rail_load, ("nets",)),
    ("2a exactly one ground bond", check_one_ground_bond, ("nets",)),
    ("2b six shields, one per pin-3", check_shield_returns, ("nets",)),
    ("2c one MAGND/MDGND star, and it is R902", check_module_star, ("nets",)),
    ("3  SIN{n} DC vs the mixer's own", check_sin_dc_by_construction,
     ("nets", "values")),
    ("4  PIN{n} load keeps the corner", check_pin_load, ("nets", "values")),
    ("5  shielded pairs, one end [practice]", check_triads, ("nets",)),
    ("   R_IN fixed, equal to R_OUT, unloaded", check_gain_chain,
     ("nets", "values")),
    ("   envelope diodes point the right way", check_rectifier_polarity,
     ("nets", "values")),
    ("   de-energised is bypass", check_fail_safe, ("nets", "values")),
    ("   the ADC cannot be overdriven", check_envelope_adc,
     ("nets", "values")),
    ("   open pins are the declared ones", check_open_pins, ("open_pins",)),
    ("   ERC finds only declared residue", check_erc, ("violations",)),
    ("   VREF load inside the MAX6126's range", check_reference_load,
     ("nets", "values")),
    ("   DRC clean, unrouted count declared", check_board, ("drc",)),
    ("   the board holds the design's parts", check_board_is_the_design,
     ("board",)),
    ("   the two pours do not overlap", check_ground_split_on_the_board,
     ("board",)),
    ("   the stackup is rules.py's stackup", check_stackup, ("board",)),
    ("   DRC's rules are rules.py's rules", check_rules, ("project", "board")),
    ("   the converter is wired and not overrun", check_supply,
     ("nets", "values")),
    ("   nothing but the primary in its region", check_isolation_gap,
     ("board",)),
    ("   the controller's pins are the map's", check_controller,
     ("nets", "values")),
    ("   the module is fed on VSYS, through D806", check_controller_periphery,
     ("nets", "values")),
    ("   the 5 V switcher is fed from VA_RAW", check_mcu_supply,
     ("nets", "values")),
    ("   MIDI in is isolated, and by one part", check_midi,
     ("nets", "values")),
    ("   U21's bypass is inside its 10 mm", check_midi_bypass, ("board",)),
    ("   the board's fixings are declared", check_mounting_holes, ("board",)),
    ("   the silk names every connector", check_silkscreen, ("board",)),
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
