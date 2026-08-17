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
  * a pin left open on the sheet that the design has not declared open.

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
import contract.socket as socket
from toolchain import kicad, kisim, sexp

OUT = pathlib.Path(__file__).resolve().parent / "out"
SHEET = OUT / "cv-module.kicad_sch"
NETLIST = OUT / "from-kicad.net"
ERC = OUT / "from-kicad-erc.json"


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
# per open pin, so `unconnected-(K101-PadA1)` is not a net this design declares
# and is not a fault either -- it is the export's way of writing "open".
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
    construction: exactly the I-V amplifier,
    its feedback pair, the servo's sense resistor and the loom -- and nothing
    else. Anything additional on this net is a path that can put DC into
    R{n}01 and from there into the mixer's summing node, where six channels'
    worth lands on the master pot's wiper.

    The servo is checked for by name because its absence is the whole failure:
    without it the SSI2164's own +/-150 nA output offset current through R_OUT
    sits on this net permanently, and nothing else in the module would notice.
    """
    problems = []
    for n in range(1, design.CHANNELS + 1):
        name = f"SIN{n}"
        expected = {f"J{n}", f"R{n}21", f"C{n}21", f"R{n}31",
                    design.SECTIONS[("iv", n)][0]}
        found = {ref for ref, _ in nets.get(name, ())}
        if found != expected:
            problems.append(
                f"{name} carries {sorted(found)}, expected {sorted(expected)} "
                f"-- I-V output, its feedback pair, the servo sense and the "
                f"loom")
        if design.net_dc(name) != (0.0, 0.0):
            problems.append(f"{name} is not declared 0 V DC in NET_DC")
        if f"R{n}31" not in found:
            problems.append(
                f"channel {n} has no DC servo sensing {name} -- the VCA's own "
                f"150 nA offset current would stand on it")
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

    Nothing else is on the node. A second part at PIN{n} -- the 1 Mohm envelope
    tap spec section 4.1 puts here, for instance -- shifts the load and the
    corner with it, and the symptom is a tonal complaint rather than a fault.

    And the load is a resistor into a *virtual earth*, not a shunt to ground.
    That is what makes it 10.000 kohm rather than 10k in parallel with whatever
    the next stage's input happens to be, and it is checked by following
    R{n}01's far end to the front-end amplifier's inverting pin.
    """
    problems = []
    low, high = 5_000.0, 10_000.0
    for n in range(1, design.CHANNELS + 1):
        name = f"PIN{n}"
        expected = {f"J{n}", f"R{n}01"}
        found = {ref for ref, _ in nets.get(name, ())}
        if found != expected:
            problems.append(
                f"{name} carries {sorted(found)}, expected {sorted(expected)} "
                f"-- the loom and the socket load only")
            continue
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
# because some of what ERC reports on a half-drawn board is true: three of these
# say six op-amp sections are not placed, and six op-amp sections are in fact not
# placed. The choice is between silencing those rules in the project file, where
# nobody would ever see them again, and writing down what is expected so that the
# *seventh* one fails the build. Pinning the count is what makes this stricter
# than "ignore missing_unit" -- placing the rectifiers wrong, or leaving a
# seventh section unplaced, moves the number and this stops.
#
# What it does not do is tolerate errors. Any violation at error severity fails
# regardless of type, because there is no error in this list and there should
# never be one: the four that were here (two power-flag conflicts, the spare
# cells' grounded outputs, two unconnected '541 outputs) were all real, and all
# four were fixed rather than listed.
ERC_ALLOWED = {
    "missing_unit": (
        3, "U2, U4 and U6 each have C and D unplaced. Those are the six "
           "sections design.OPAMP_NEEDED counts for the six envelope "
           "rectifiers, and the rectifier is in design.DEFERRED because its "
           "time constant is not derivable from the spec. Drawing them with "
           "no-connect flags would assert they are unused, which is the "
           "opposite of true, so the warning stands and says so."),
    "missing_input_pin": (
        3, "the same six sections, reported once per package from the other "
           "direction. Not an independent fact and counted separately because "
           "ERC counts it separately."),
}


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

    Then two things about the declarations themselves. Every deferred pin names
    a block that is still in design.DEFERRED, so the relay driver landing cannot
    leave 48 pins still declared as waiting for it. And no pin is in both
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
    ("   open pins are the declared ones", check_open_pins, ("open_pins",)),
    ("   ERC finds only declared residue", check_erc, ("violations",)),
    ("   VREF load inside the MAX6126's range", check_reference_load,
     ("nets", "values")),
)


def main():
    export_netlist(SHEET, NETLIST)
    nets = read_netlist(NETLIST)
    values = read_components(NETLIST)
    context = {"nets": nets, "values": values,
               "open_pins": read_open_pins(NETLIST),
               "violations": run_erc(SHEET, ERC)}

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
