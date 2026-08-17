"""Test each of the five load-bearing constraints for a mechanism.

CLAUDE.md lists five constraints under "check these mechanically, not by eye".
One of them -- constraint 2's "six separate returns" -- turned out to have no
mechanism at all: it was generated in an earlier session, promoted into that
list, and then satisfied, asserted and negative-tested by every instrument
downstream without anyone asking whether the requirement was reachable from
physics. See design.FRONT_R.

Being in that list is what made it unquestionable. So this file asks the same
question of the other four, and the question is not "is the constraint
satisfied" -- verify.py already answers that -- but:

    1. is there a mechanism, and what is it?
    2. what does the arithmetic say the threshold should be?
    3. how much margin does the design have against it?

A constraint with a mechanism and thin margin is load-bearing and belongs in
that list. A constraint with a mechanism and 40 dB of margin is good practice
and does not. A constraint with no mechanism should be struck, as 2b was.

    python3 constraints.py

**The estimates here are rougher than the rest of the repo and that matters
for how they are read.** Loom capacitances are per-unit-length figures for a
geometry nobody has built; the threshold for DC through a potentiometer wiper
is not sourced at all. Where a margin comes out at 40 dB a rough estimate is
enough to settle the question. Where it came out at 2 dB it would not be, and
the one place that nearly happened is recorded below.
"""

import math
import pathlib

import design
import delta
import contract.socket as socket
from contract.socket import source

# Hoisted out of write(), where it was built inline with __import__("pathlib")
# and named OUT while every other generator's OUT means the machine-readable
# directory. One name, one meaning: this file's only output is a document.
DOCS = pathlib.Path(__file__).resolve().parent / "docs"

# ---------------------------------------------------------------------------
# Loom geometry, assumed
# ---------------------------------------------------------------------------
# Neither figure is measured. They are ordinary values for small-gauge shielded
# cable and they are stated here rather than buried in a function because the
# shielding verdict below rests on them.
LOOM_LENGTH = 0.150                 # m, module to mixer
C_WITHIN_PAIR = 50e-12              # F/m, conductor to conductor, twisted
C_BETWEEN_PAIRS = 15e-12            # F/m, pair to adjacent pair in a bundle
C_TO_AGGRESSOR = 5e-12              # F/m, loom to a nearby switching node

# The two switching aggressors the loom runs past, and their amplitudes.
AGGRESSORS = (
    ("mixer charge pump", socket.PUMP_FREQUENCY, socket.VREG_VOLTS),
    ("module DC-DC", 300e3, design.MODULE_RAIL),
)

# What the requirement is, and where it comes from: 00-current-state.md, "For
# 40 dB of musical gate depth: per-channel depth >=47 dB, per-pair isolation
# <=-54 dB. Crosstalk remains the binding constraint."
ISOLATION_DB = -54.0

SIGNAL_RMS = socket.MEASURED["channel_peak"].value / math.sqrt(2)


def pin_impedance(hz):
    """What the loom sees looking into PIN{n}, ohms.

    The number that decides the shielding verdict, and the one it is easy to
    get wrong. PIN{n} is *not* a 10 kohm node: it is the junction of this
    module's R{n}01 and the mixer's own C{n}01, and behind that capacitor is a
    Nu capsule's TLV170 output at the far end of a cable. So the node is
    R{n}01 in parallel with (the capsule's output impedance + the DC block's
    reactance), and above a few hundred hertz the capacitor is a short and the
    node is tens of ohms.

    Getting this wrong by using 10 kohm puts the crosstalk estimate at -51 dB,
    which fails the -54 dB requirement and would make shielding load-bearing.
    With the right impedance it is -113 dB. The difference is entirely which
    impedance the coupling current flows into, and it is 62 dB.
    """
    reactance = 1.0 / (2 * math.pi * hz * socket.DC_BLOCK_FARADS)
    behind = math.hypot(abs(source.output_impedance(hz)), reactance)
    return behind * design.FRONT_R_OHMS / (behind + design.FRONT_R_OHMS)


def coupling_db(hz, farads, impedance, source_volts=None):
    """Capacitive coupling of a source onto a node, in dB.

    A first-order divider: the coupled voltage is source x omega C Z while
    omega C Z is small, which it is by four orders of magnitude everywhere
    below.
    """
    fraction = 2 * math.pi * hz * farads * impedance
    if source_volts is None:
        return 20 * math.log10(fraction)
    return 20 * math.log10(source_volts * fraction / SIGNAL_RMS)


# ---------------------------------------------------------------------------
# 1. The module draws nothing from VREG, V+ or V-
# ---------------------------------------------------------------------------

def constraint_1():
    """Mechanism: real. Threshold: literally unachievable, and 100x too strict.

    The mechanism is the mixer's charge pump. Its output impedance is about
    55 ohms and the rail filter adds 10, so every milliamp taken from V- costs
    65 mV of negative rail -- which is where NEGATIVE_RAIL_DROP's 0.47 V at
    7.2 mA comes from. Less rail is less headroom, and headroom is what
    check_headroom() upstream defends with 6 dB of margin.

    So the arithmetic can say what the threshold *should* be: how much current
    would this module have to draw before the mixer's own check fails?

    And then the part the constraint gets wrong. "Nothing" is not achievable,
    because the signal current this module pushes into SIN{n} is absorbed by
    the mixer's summing amplifier -- which sources it from V+ and V-. Six
    channels of it. That is not a violation to be fixed; it is what any source
    driving that node does, including the potentiometer this module replaces.

    What the constraint means, and what verify.py checks, is that no *supply*
    current is drawn -- no net of the mixer's rails appears in this module's
    netlist. That is the right check and it is free to honour, because the
    module has its own isolated supply.
    """
    cost_per_ma = 55.0 + socket.MIXER_DESIGN.RAIL_FILTER_OHMS   # ohms = mV/mA
    rail = socket.SUPPLY_RAIL
    assumed = socket.MEASURED["channel_peak"].value

    # How much current before check_headroom()'s 6 dB margin is gone.
    needed_peak = assumed * 10 ** (6.0 / 20)
    needed_swing = needed_peak * design.CHANNELS
    allowed_ma = (rail - socket.MIXER_DESIGN.OUTPUT_SWING_MARGIN
                  - needed_swing) / (cost_per_ma * 1e-3)

    # What the module unavoidably draws, indirectly, through SUM.
    signal_ua = SIGNAL_RMS / socket.RIN_OHMS * design.CHANNELS * 1e6
    sag_uv = signal_ua * cost_per_ma * 1e-3

    return {
        "cost_per_ma": cost_per_ma,
        "margin_now_db": 20 * math.log10(socket.clipping_peak() / assumed),
        "allowed_ma": allowed_ma,
        "indirect_ua": signal_ua,
        "indirect_sag_uv": sag_uv,
        "verdict": "KEEP, reword",
    }


# ---------------------------------------------------------------------------
# 3. SIN{n} carries zero DC by construction
# ---------------------------------------------------------------------------

def constraint_3():
    """Mechanism: real. Threshold: overstated by three orders of magnitude,
    and "by construction" is unachievable and undesirable.

    The mechanism is the mixer's own, and it is why DC_BLOCK = 'cap' upstream:
    DC across a potentiometer wiper is what makes a level control scratchy. DC
    on SIN{n} drives R{n}01 into the summing node, appears at SUM_OUT times six,
    and lands on the master pot.

    What the mechanism actually cares about is *current* through the wiper, and
    the mixer has already put C703 in the way -- so the only path is R706's
    1 Mohm. That turns millivolts into nanoamps, and the mixer states its own
    figure for comparison: "with the output link fitted instead the wiper sees
    R_OUT plus R_OUT_BLEED against U1B's own offset, which is 0.2 to 1.0 nA".

    So the honest threshold is a comparison rather than a limit, and the number
    is three orders of magnitude away from "zero".

    **And the threshold above which a wiper is actually audible is not sourced
    anywhere in this project.** Standard practice puts it in microamps; nothing
    here has read a figure. So what is claimed below is only that this module
    lands in the same neighbourhood as the design it plugs into, not that some
    absolute limit is met.
    """
    servo = design.servo_residual()
    theirs = (0.2e-9, 1.0e-9)
    top = design.MEASURED["servo_vos"].high
    worst_amps = top * design.CHANNELS * (socket.RF_OHMS / socket.RIN_OHMS) \
        / socket.OUT_BLEED_OHMS
    return {
        "residual_mv": servo["residual"] * 1e3,
        "wiper_na": servo["wiper_amps"] * 1e9,
        "worst_case_na": worst_amps * 1e9,
        "mixer_own_na": theirs,
        "ratio": servo["wiper_amps"] / theirs[1],
        "by_construction": False,
        "verdict": "KEEP, restate as a current",
    }


# ---------------------------------------------------------------------------
# 4. PIN{n} sees ~5-10 kohm, or the 31.8 Hz DC-block corner moves
# ---------------------------------------------------------------------------

def constraint_4():
    """Mechanism: real and computed by the mixer itself. The number in the
    sentence is wrong, and the sentence is self-contradictory.

    coupling_burden() is the mixer's own function and the corner is
    1/(2 pi C Z), so this is the most solidly grounded of the five.

    But 31.8 Hz is the corner at **5 kohm**, which is one end of the permitted
    range, not the range. Anywhere else in 5-10 kohm the corner is somewhere
    else -- 15.9 Hz at the top. So "5-10 kohm, or the 31.8 Hz corner moves"
    cannot be satisfied except at exactly one point in its own window.

    What it should say is that the corner must stay inside the 15.9-31.8 Hz the
    fabricated design already sweeps as its potentiometer turns, which any value
    in 5-10 kohm does by construction. That version is true, checkable, and
    what verify.check_pin_load() implements.

    The trade the constraint does not mention is subsonic rejection. DESIGN.md
    chose 1 uF over 2u2 specifically to reject bow pressure, body movement and
    handling, and quantified it at 5 Hz. Choosing the top of the window gives
    part of that back.
    """
    rows = []
    for ohms in (5_000.0, design.FRONT_R_OHMS):
        corner = 1.0 / (2 * math.pi * socket.DC_BLOCK_FARADS * ohms)
        at_5 = 20 * math.log10(5.0 / math.hypot(5.0, corner))
        at_55 = 20 * math.log10(55.0 / math.hypot(55.0, corner))
        rows.append({"ohms": ohms, "corner": corner,
                     "at_5hz": at_5, "at_55hz": at_55})
    return {
        "rows": rows,
        "subsonic_given_back": rows[1]["at_5hz"] - rows[0]["at_5hz"],
        "bass_recovered": rows[1]["at_55hz"] - rows[0]["at_55hz"],
        "stated_corner": 31.8,
        "our_corner": rows[1]["corner"],
        "verdict": "KEEP, fix the number",
    }


# ---------------------------------------------------------------------------
# 5. Individually-shielded twisted triads, shields at the main-board end only
# ---------------------------------------------------------------------------

def constraint_5():
    """Mechanism: real in kind, but 44 dB of margin. Good practice, not
    load-bearing -- and the first estimate said the opposite.

    Three couplings matter and all three are computed against the same
    requirement, -54 dB per pair.

    **The near miss is worth recording.** Computing channel-to-channel coupling
    with PIN{n} treated as a 10 kohm node gives -52 dB at 20 kHz, which fails.
    That is wrong: PIN{n} is R{n}01 in parallel with the mixer's own DC block
    and the capsule behind it, which is tens of ohms at 20 kHz. The correct
    figure is -113 dB. One impedance, 62 dB, and the difference between
    "shielding is mandatory" and "shielding is cheap insurance".

    The third coupling is one no constraint mentions. This loom carries a
    channel's input and its output in the same twisted pair, and the module is
    non-inverting end to end -- two inversions, deliberately, to restore the
    polarity the mixer's stage 2 exists for. So conductor-to-conductor coupling
    inside the pair is *positive* feedback around the channel. It is 103 dB down
    for the same reason, and it would not be if PIN{n} were the high-impedance
    node it looks like.
    """
    hz = 20_000.0
    z = pin_impedance(hz)
    between = C_BETWEEN_PAIRS * LOOM_LENGTH
    within = C_WITHIN_PAIR * LOOM_LENGTH

    crosstalk = coupling_db(hz, between, z, SIGNAL_RMS)
    feedback = coupling_db(hz, within, z, SIGNAL_RMS)
    naive = coupling_db(hz, between, design.FRONT_R_OHMS, SIGNAL_RMS)

    pickup = []
    for name, freq, volts in AGGRESSORS:
        pickup.append({
            "name": name, "hz": freq,
            "db": coupling_db(freq, C_TO_AGGRESSOR * LOOM_LENGTH,
                              pin_impedance(freq), volts),
        })

    return {
        "pin_z_20k": z,
        "crosstalk": crosstalk,
        "naive_crosstalk": naive,
        "feedback": feedback,
        "pickup": pickup,
        "requirement": ISOLATION_DB,
        "margin": ISOLATION_DB - crosstalk,
        "verdict": "KEEP as practice, demote from the list",
    }


VERDICTS = """
| # | constraint | mechanism | margin | verdict |
|---|---|---|---|---|
| 1 | draws nothing from VREG/V+/V- | real: 65 mV of rail per mA | ~100x | **keep, reword** -- "nothing" is unachievable, since the mixer's summer sources this module's signal current from its own rails. What is meant, and what is checked, is no *supply* current. |
| 2a | exactly one AGND bond | real: a loop enclosing the mixer's pour and the loom | n/a, binary | **keep** -- the mixer's own `_GROUND_RULE` across the connector. |
| 2b | six separate returns, not commoned | **none** | 49 dB | **struck.** See `design.FRONT_R`. |
| 3 | SIN{n} zero DC by construction | real: DC through the master wiper | ~3x the mixer's own | **keep, restate as a current.** "Zero" overstates by three orders of magnitude and "by construction" is unachievable -- a servo is feedback, and the capacitor that would be construction puts a second pole beside the mixer's own. |
| 4 | PIN{n} sees 5-10 kohm | real, and computed by `coupling_burden()` upstream | n/a | **keep, fix the number.** 31.8 Hz is the corner at 5 kohm, so the sentence is unsatisfiable anywhere else in its own window. |
| 5 | individually-shielded triads, one end | real in kind | 59 dB | **keep as practice, demote from the list.** Both loom nodes are low impedance, so the coupling the shields prevent is 59 dB inside the requirement. |

**One of five had no mechanism. Two more have the mechanism and the wrong
number. One is unsatisfiable as written. One is sound.**

That is not an argument against having the list. It is an argument for the list
being derived rather than drafted -- and for the distinction the exercise turns
on: a constraint with thin margin is load-bearing, a constraint with 59 dB of
margin is good practice, and the two do not want the same treatment. Both were
in the same list, checked with the same rigour, and only one of them was worth
it.
"""


def _report():
    print("Testing the five constraints for a mechanism")
    print(f"requirement for isolation: {ISOLATION_DB:.0f} dB per pair "
          f"(docs/00-current-state.md)")
    print("numbered as hardware-spec-v0.md section 5 numbers them, which is "
          "also")
    print("what verify.py prints and what every 'constraint N' in design.py "
          "means")
    print()

    c = constraint_1()
    print("1. the module draws nothing from VREG, V+ or V-")
    print(f"   mechanism   {c['cost_per_ma']:.0f} mV of negative rail per mA "
          f"(55 ohm pump + 10 ohm filter)")
    print(f"   headroom    {c['margin_now_db']:.2f} dB now, against the 6 dB "
          f"check_headroom() demands")
    print(f"   threshold   {c['allowed_ma']:.1f} mA could be drawn before that "
          f"check fails")
    print(f"   but         {c['indirect_ua']:.0f} uA IS drawn indirectly -- the "
          f"mixer's summer sources our")
    print(f"               signal current from its own rails, so 'nothing' is "
          f"unachievable ({c['indirect_sag_uv']:.1f} uV of sag)")
    print(f"   verdict     {c['verdict']}")
    print()

    # Constraint 2 has no block below and the gap is deliberate: 2a is binary --
    # either one part bridges the two grounds or it does not, so there is no
    # margin to compute -- and 2b is struck, with its arithmetic in
    # design.FRONT_R rather than here. Said out loud because a reader who sees
    # 1, 3, 4, 5 cannot tell a deliberate gap from a forgotten one.
    print("2. exactly one AGND bond, and six separate returns")
    print("   2a is binary and has no margin to compute: verify.py holds it")
    print("   2b is struck for having no mechanism -- see design.FRONT_R and "
          "the table")
    print()

    c = constraint_3()
    print("3. SIN{n} carries zero DC by construction")
    print(f"   mechanism   DC through the master pot wiper, via C703 and "
          f"R706's 1M")
    print(f"   ours        {c['residual_mv']:.2f} mV residual -> "
          f"{c['wiper_na']:.1f} nA at the wiper")
    print(f"   worst case  {c['worst_case_na']:.1f} nA at the top of "
          f"servo_vos's declared range")
    print(f"   theirs      {c['mixer_own_na'][0] * 1e9:.1f} to "
          f"{c['mixer_own_na'][1] * 1e9:.1f} nA from U1B's own offset")
    print(f"   so          {c['ratio']:.0f}x the mixer's own worst case, and "
          f"the absolute threshold is unsourced")
    print(f"   verdict     {c['verdict']}")
    print()

    c = constraint_4()
    print("4. PIN{n} sees ~5-10 kohm, or the 31.8 Hz DC-block corner moves")
    print("   load      corner     at 5 Hz    at 55 Hz")
    for row in c["rows"]:
        print(f"   {row['ohms']:>6.0f}  {row['corner']:>6.2f} Hz  "
              f"{row['at_5hz']:>+7.2f} dB  {row['at_55hz']:>+7.2f} dB")
    print(f"   the sentence names {c['stated_corner']} Hz, which is the 5k end; "
          f"we are at {c['our_corner']:.1f} Hz")
    print(f"   so it is unsatisfiable anywhere in 5-10k except at exactly 5k")
    print(f"   choosing the top gives back {c['subsonic_given_back']:+.2f} dB "
          f"of subsonic rejection")
    print(f"   and recovers {c['bass_recovered']:+.2f} dB at 55 Hz")
    print(f"   verdict     {c['verdict']}")
    print()

    c = constraint_5()
    print("5. individually-shielded twisted triads, shields at one end")
    print(f"   PIN(n) impedance at 20 kHz  {c['pin_z_20k']:.0f} ohm  "
          f"-- NOT 10k: see pin_impedance()")
    print(f"   channel-to-channel          {c['crosstalk']:>7.1f} dB   "
          f"({c['margin']:.0f} dB inside the requirement)")
    print(f"   the same, computed at 10k   {c['naive_crosstalk']:>7.1f} dB   "
          f"<- the near miss: this FAILS -54 dB")
    print(f"   input-to-output in one pair {c['feedback']:>7.1f} dB   "
          f"positive feedback, and nothing mentions it")
    for row in c["pickup"]:
        print(f"   {row['name']:<27} {row['db']:>7.1f} dB   "
              f"at {row['hz'] / 1e3:.0f} kHz")
    print(f"   verdict     {c['verdict']}")
    print()
    print(VERDICTS.strip())


def write():
    """docs/constraints.md, so the verdicts are a document and not a print."""
    import io, contextlib
    DOCS.mkdir(exist_ok=True)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _report()
    body = buffer.getvalue()
    head, _, table = body.partition("| # | constraint")
    path = DOCS / "constraints.md"
    path.write_text(
        "# The five constraints, tested for a mechanism\n\n"
        "Generated by `constraints.py`. The question is not whether each "
        "constraint is satisfied — `verify.py` answers that — but whether it "
        "has a mechanism, what the arithmetic says its threshold should be, "
        "and how much margin the design has.\n\n"
        "```\n" + head.rstrip() + "\n```\n\n"
        + "| # | constraint" + table)
    return path


if __name__ == "__main__":
    _report()
    print()
    print(f"wrote {write().relative_to(write().parent.parent)}")
