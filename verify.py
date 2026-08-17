"""Read the emitted netlist back and check it against section 5.

The five constraints in `hardware-spec-v0.md` section 5 are described there as
load-bearing rather than stylistic, and CLAUDE.md says to check them
mechanically rather than by eye. This is that check.

It reads `out/cv-module.net` -- the file, not the module that produced it --
for the reason the mixer's own verify.py exists: a design that is only ever
compared to itself proves nothing. That protection is weaker here than it is
upstream, and the weakness is worth stating plainly rather than leaving to be
discovered. Upstream, `verify.py` reads a netlist *KiCad* exported from a
schematic *KiCad* built from geometry, so it catches a wire that missed its
target by a millimetre. Here the netlist is written by gen_netlist.py from the
same `design.py` these checks import, so what this catches is a design that
violates its own constraints -- not a transcription error, because there is no
transcription yet. When a schematic exists, this file's reader points at
KiCad's export instead and the rest is unchanged.

What it does catch, today:

  * a rail this module is forbidden to touch, appearing anywhere;
  * a second bond between the two grounds, which is what one stray ground
    symbol produces and what turns the star into six loops;
  * a shield landing anywhere but its own pin-3, or at both ends;
  * anything landing on SIN{n} that can put DC into the mixer's summing node;
  * a load at PIN{n} that is not the 10k the DC-block corner was computed for;
  * an audio conductor leaving the module without a declared pair and shield.

None of those is visible to ERC, to DRC, or to a netlist comparison against
design.py -- which is the test the mixer's own check_ground_star() docstring
applies, and the reason these are separate functions rather than assertions
buried in the generator.
"""

import pathlib
import sys

import design
import contract.socket as socket

sexp = sys.modules.get("sexp")
if sexp is None:
    import sexp                       # noqa: E402  (MIXER is on the path)

NETLIST = pathlib.Path(__file__).resolve().parent / "out" / "cv-module.net"


def read_netlist(path):
    """net name -> set of (ref, pin), as the file actually says."""
    tree = sexp.parse(path.read_text())
    found = {}
    for net in sexp.find_all(sexp.find(tree, "nets"), "net"):
        name = sexp.find(net, "name")[1]
        found[name] = {(sexp.find(node, "ref")[1], str(sexp.find(node, "pin")[1]))
                       for node in sexp.find_all(net, "node")}
    return found


def read_components(path):
    """reference -> value, from the emitted file."""
    tree = sexp.parse(path.read_text())
    out = {}
    for comp in sexp.find_all(sexp.find(tree, "components"), "comp"):
        out[sexp.find(comp, "ref")[1]] = sexp.find(comp, "value")[1]
    return out


def compare(actual, expected):
    """The netlist on disk is the netlist design.py asked for, net by net."""
    problems = []
    actual_by_nodes = {frozenset(v): k for k, v in actual.items()}
    expected_by_nodes = {frozenset(v): k for k, v in expected.items()}
    for nodes, name in expected_by_nodes.items():
        if nodes not in actual_by_nodes:
            problems.append(f"net {name} not emitted as designed")
    for nodes, name in actual_by_nodes.items():
        if nodes not in expected_by_nodes:
            problems.append(f"unexpected net {name} = {sorted(nodes)}")
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


CHECKS = (
    ("1  no load on the mixer's rails", check_no_mixer_rail_load, ("nets",)),
    ("2a exactly one ground bond", check_one_ground_bond, ("nets",)),
    ("2b six shields, one per pin-3", check_shield_returns, ("nets",)),
    ("3  SIN{n} DC vs the mixer's own", check_sin_dc_by_construction,
     ("nets", "values")),
    ("4  PIN{n} load keeps the corner", check_pin_load, ("nets", "values")),
    ("5  shielded pairs, one end [practice]", check_triads, ("nets",)),
)


def main():
    if not NETLIST.exists():
        raise SystemExit(f"{NETLIST} does not exist -- run gen_netlist.py")
    nets = read_netlist(NETLIST)
    values = read_components(NETLIST)
    context = {"nets": nets, "values": values}

    print(f"verify: {NETLIST.name} against hardware-spec-v0.md section 5")
    print(f"        mixer contract at {socket.PIN[:7]}")
    print()

    problems = compare(nets, design.NETS)
    print(f"  {'netlist matches design.py':<38} "
          f"{'ok' if not problems else str(len(problems)) + ' problems'}")

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
