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
import re
import statistics

import design
import delta
import placement
import rules
import contract.socket as socket
from contract.socket import source
from toolchain import sexp

# Hoisted out of write(), where it was built inline with __import__("pathlib")
# and named OUT while every other generator's OUT means the machine-readable
# directory. One name, one meaning: this file's only output is a document.
DOCS = pathlib.Path(__file__).resolve().parent / "docs"
# The board this file measures trace adjacency on. Read, never written: the
# only thing here that needs geometry is board_coupling(), and it needs the
# copper as laid rather than as designed -- the same argument verify.py makes
# for reading KiCad's netlist instead of design.py.
BOARD = pathlib.Path(__file__).resolve().parent / "out" / "cv-module.kicad_pcb"

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
#
# Moved to design.py, because design.rail_crosstalk() has to compare against it
# too and this file imports that one. Re-exported under the same name so every
# existing reference here still reads constraints.ISOLATION_DB.
ISOLATION_DB = design.ISOLATION_DB

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


# ---------------------------------------------------------------------------
# The same question, asked of the copper instead of the loom
# ---------------------------------------------------------------------------
#
# **Constraint 5 computes channel-to-channel coupling between two wires in a
# loom and nothing has ever computed it between two traces on the board.** The
# gap went unnoticed for as long as it did because the loom is the thing the
# spec names, and because the seed routing was never going to be shipped -- but
# trace adjacency is a property of the copper, so replacing route.py's seed
# with KiCadRoutingTools' board changed it, and no instrument in this repo
# could say by how much. Neither board had been measured.
#
# It is reported here rather than asserted in verify.py, on this project's own
# rule: a constraint with thin margin is load-bearing and verify.py must hold
# it, and one with sixty decibels of margin is good practice that should not be
# defended as though the design depended on it. This has 59.

# How close two traces have to be to be worth counting, and how finely the
# overlap is sampled. 2 mm is about five track widths, past which the coupling
# coefficient has fallen by more than 20 dB at every plausible height; 0.25 mm
# is a quarter of the shortest segment worth measuring.
COUPLING_REACH_MM = 2.0
COUPLING_STEP_MM = 0.25

# The per-channel net families, by what the coupling current flows into.
# **This split is the whole calculation**, for the reason pin_impedance()
# records: everything below is decided by the victim's impedance and not by
# the geometry, and getting it wrong is worth 62 dB.
AUDIO_FAMILIES = ("PIN", "SIN", "BUF", "IVOUT", "AOUT")
CV_FAMILIES = ("CVX",)


def _segments(board):
    """Every copper segment on a per-channel net, by (family, channel, layer).

    Read through toolchain/sexp.py, which is what verify.check_rules() uses --
    there is one reader for this format in this repository.
    """
    import re
    import collections
    tree = sexp.parse(pathlib.Path(board).read_text())
    want = re.compile(r"^(%s)(\d)$" % "|".join(AUDIO_FAMILIES + CV_FAMILIES))
    out = collections.defaultdict(list)
    for segment in sexp.find_all(tree, "segment"):
        net = sexp.find(segment, "net")
        layer = sexp.find(segment, "layer")
        if net is None or layer is None:
            continue
        match = want.match(str(net[1]))
        if not match:
            continue
        start, end = sexp.find(segment, "start"), sexp.find(segment, "end")
        out[(match.group(1), int(match.group(2)), layer[1])].append(
            (float(start[1]), float(start[2]), float(end[1]), float(end[2])))
    return out


def _overlap(a, b, reach=COUPLING_REACH_MM):
    """Length of `a` that runs within `reach` of `b`, and the mean gap there.

    Sampled along `a` rather than solved. The closed form for "the part of one
    segment within d of another" is a quartic in the general case, and the
    answer is wanted to a decibel, not to a micron -- so the approximation is
    declared instead of hidden. COUPLING_STEP_MM sets the resolution.
    """
    ax, ay, bx, by = a
    length = math.hypot(bx - ax, by - ay)
    cx, cy, dx, dy = b
    other = math.hypot(dx - cx, dy - cy)
    if length < 1e-9 or other < 1e-9:
        return 0.0, None
    steps = max(2, int(length / COUPLING_STEP_MM))
    hits, total = 0, 0.0
    for i in range(steps):
        t = (i + 0.5) / steps
        px, py = ax + (bx - ax) * t, ay + (by - ay) * t
        u = ((px - cx) * (dx - cx) + (py - cy) * (dy - cy)) / (other * other)
        u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
        gap = math.hypot(px - (cx + (dx - cx) * u), py - (cy + (dy - cy) * u))
        if gap <= reach:
            hits += 1
            total += gap
    if not hits:
        return 0.0, None
    return length * hits / steps, total / hits


def parallel_runs(board):
    """The worst same-layer parallel run between two channels, per victim class.

    Returns the coupled length and the tightest pitch found, for audio against
    audio and for audio against the CV filter's passive node. Two channels are
    what the requirement is about, so runs within one channel are skipped.
    """
    segments = _segments(board)
    keys = sorted(segments)
    worst = {}
    for i, first in enumerate(keys):
        f1, c1, layer1 = first
        for second in keys[i + 1:]:
            f2, c2, layer2 = second
            if layer1 != layer2 or c1 == c2:
                continue
            kinds = {f1 in CV_FAMILIES, f2 in CV_FAMILIES}
            if kinds == {True}:
                continue                       # CV against CV is not the ask
            kind = "audio_cv" if True in kinds else "audio_audio"
            length, pitch = 0.0, None
            for sa in segments[first]:
                for sb in segments[second]:
                    piece, gap = _overlap(sa, sb)
                    if piece > 0.0:
                        length += piece
                        pitch = gap if pitch is None else min(pitch, gap)
            if length <= 0.0:
                continue
            name = f"{f1}{c1}/{f2}{c2}"
            if kind not in worst or length > worst[kind]["length_mm"]:
                worst[kind] = {"pair": name, "length_mm": length,
                               "pitch_mm": pitch}
    return worst


# **How much audio copper sits off its own ground plane, and it is a ratchet.**
#
# "Off MAGND" and not "over MDGND", because the boundary that matters is where
# the analogue pour *stops*: gen_pcb.build() insets both pours by half of
# placement.GROUND_GAP, so between 156.44 and 158.44 there is no reference
# plane at all, which is worse than being over the wrong one. Measuring from
# the far edge instead would score 23 mm of bare-gap copper as compliant --
# the difference between the two readings on this board, and the reason the
# name says MAGND. floorplan.CROSSING_RULE says in terms that "nothing
# audio-carrying crosses at all", and floorplan.check_crossings() cannot hold
# it: that check reads the **netlist** -- a net touching parts in both domains
# -- and where a track *goes* is a different question from where its endpoints
# are. A copper review found the gap: eleven audio nets had copper south of
# the MAGND pour, and two of them, PIN5 and SIN3, had every pad in the
# analogue half and were taken 38 mm and 19 mm into the digital one anyway.
# The router had no way to know; nothing here was asking.
#
# **What the number means.** An audio track over MDGND has its return current
# in a plane its own ground does not meet except at the star, so the loop
# closes the long way round -- which is the mechanism CROSSING_RULE exists to
# prevent, arriving through the copper rather than through the netlist.
#
# **Why it is a figure and not zero.** Nine of the eleven reach a bypass
# relay's contact, and the three relays straddle the split *by design*: their
# southern pads are at y = 161.4 and the copper has to get there. Those are
# not violations, they are the cost of a part that is deliberately on the
# line. So this is UNROUTED_ITEMS' rule applied to millimetres -- **down as
# copper is moved, up only with the nets named** -- and not an assertion of
# zero, which would be unachievable and would therefore be switched off.
AUDIO_OFF_MAGND_MM = 118.1


def audio_off_its_own_plane(board=BOARD):
    """Audio copper south of the MAGND pour, per net and in total.

    The boundary is the pour's own southern edge rather than SPLIT_Y, because
    what decides a return path is which copper is underneath: gen_pcb.build()
    insets each pour by half of placement.GROUND_GAP, so MAGND stops there and
    everything below is bare or MDGND.
    """
    edge = placement.SPLIT_Y - placement.GROUND_GAP / 2
    per_net = {}
    text = board.read_text() if hasattr(board, "read_text") else board
    pattern = re.compile(r"^(%s)\d+$" % "|".join(AUDIO_FAMILIES))
    for x0, y0, x1, y1, _w, _layer, net in _raw_segments(text):
        if not pattern.match(net):
            continue
        length = math.hypot(x1 - x0, y1 - y0)
        if not length:
            continue
        # Sampled rather than clipped: a segment may cross the edge, and the
        # part that matters is the part that is over the wrong plane.
        steps = max(2, int(length / 0.05))
        for i in range(steps):
            if y0 + (i + 0.5) / steps * (y1 - y0) > edge:
                per_net[net] = per_net.get(net, 0.0) + length / steps
    return {"edge_mm": edge, "per_net": per_net,
            "total_mm": sum(per_net.values()),
            "declared_mm": AUDIO_OFF_MAGND_MM}


def _raw_segments(text):
    """Every track segment as (x0, y0, x1, y1, width, layer, net)."""
    for a, b, c, d, w, layer, net in re.findall(
            r'\t\(segment\n\t\t\(start ([-\d.]+) ([-\d.]+)\)\n'
            r'\t\t\(end ([-\d.]+) ([-\d.]+)\)\n\t\t\(width ([\d.]+)\)\n'
            r'\t\t\(layer "([^"]+)"\)\n\t\t\(net "([^"]*)"\)', text):
        yield float(a), float(b), float(c), float(d), float(w), layer, net


def check_audio_off_its_own_plane(board=BOARD):
    """The ratchet. Raises if the figure has grown."""
    measured = audio_off_its_own_plane(board)
    if measured["total_mm"] > AUDIO_OFF_MAGND_MM + 0.05:
        worst = sorted(measured["per_net"].items(), key=lambda kv: -kv[1])
        raise AssertionError(
            f"audio copper off MAGND is {measured['total_mm']:.1f} mm and "
            f"constraints.AUDIO_OFF_MAGND_MM declares "
            f"{AUDIO_OFF_MAGND_MM:.1f} -- "
            + ", ".join(f"{net} {mm:.1f} mm" for net, mm in worst[:6])
            + ". Down as copper is moved, up only with the nets named.")
    return measured


# **Where a signal's return current crosses between the two ground planes.**
#
# In1.Cu and In2.Cu carry the same two nets in the same places -- MAGND north
# of the pour edge, MDGND south of it -- so a track that changes layer changes
# reference plane, and its return current has to transfer from one plane to the
# other. The only conductor that does that is a ground via, and the loop the
# current makes on the way is the separation between the planes times the
# distance to the nearest one. rules.plane_separation() is the first figure and
# this is the second.
#
# **What the number is not.** As a return *impedance* it does not matter and
# the arithmetic says so plainly: the worst loop on this board before any of
# this was 22.76 mm of In1/In2 pair, which is tens of nanohenries, sub-
# milliohm at 20 kHz, and tens of nanovolts against a 144 uV floor. Nothing in
# the audio band is decided here.
#
# What it is is a **pickup loop**, and this board carries two switchers of its
# own -- the converter at 580 kHz and U22 at 1.1 MHz. An emf is the loop area
# times dB/dt, and the field is the term nothing here derives: board_coupling()
# solves trace against trace, where both conductors are known, and an aggressor
# *field* needs the geometry of a current loop inside a potted brick that no
# datasheet draws. So this file states the area and the sensitivity and stops
# there, which is the honest end of the derivation.
#
# **The decision was to spend the copper rather than the derivation**, and what
# makes that cheap is that a ground stitch is not a perforation. Measured on
# the tracked board: a signal via sits in a 0.55 mm void in *both* planes --
# the filler's own clearance, and 843 of them take 3.2 % of each plane's area
# -- while a ground via sits in solid copper with no void at all. So the trade
# routing-tool.md flags, "every extra via is a hole through both reference
# planes", is a true statement about *signal* vias and does not apply to these.
# Stitching is also not routing: it disturbs no copper that is already laid.
RETURN_VIA_NETS = ("MAGND", "MDGND")


def _vias(board=BOARD):
    """Every via as (x, y, net), read through the parser and not by pattern.

    **The regex this was first written as found 151 of 994.** It was modelled
    on _raw_segments() above, which is exact for segments -- and KiCad writes a
    `(tenting ...)` field on a via that came from KiCadRoutingTools and none on
    a via that came from gen_pcb.py, so the pattern matched precisely the vias
    this repository wrote and none of the ones it did not. The giveaway was
    that the audio count came back zero, which is the failure mode this repo
    collects: a probe that reports nothing found.
    """
    tree = sexp.parse(board.read_text() if hasattr(board, "read_text")
                      else board)
    out = []
    for via in sexp.find_all(tree, "via"):
        at, net = sexp.find(via, "at"), sexp.find(via, "net")
        if at is None or net is None:
            continue
        # The net name is the last element, which reads both the two-element
        # form KiCad 10 writes and the three-element one it used to --
        # verify._board_copper()'s own correction, one artefact along.
        out.append((float(at[1]), float(at[2]), str(net[-1])))
    return out


# The declared figure, and it is a ratchet in the shape AUDIO_OFF_MAGND_MM is.
# Total plane-transfer loop area over every audio via on the board, mm^2:
# sum of (distance to the nearest ground via) x rules.plane_separation().
#
# It was **1990.6 mm** before returns.py laid a stitch, at a median separation
# of 7.39 mm and a worst of 22.76. Down as copper is laid; up only with the
# vias named in the failure message.
AUDIO_RETURN_AREA_MM2 = 370.7


def return_loops(board=BOARD):
    """The plane-transfer loop at every audio via, and what it adds to.

    Sorted worst first, because the failure message wants to name the vias
    that moved and a mean does not identify anything.
    """
    height, _dk = rules.plane_separation()
    vias = _vias(board)
    ground = [(x, y) for x, y, net in vias if net in RETURN_VIA_NETS]
    if not ground:
        # Said rather than raised out of min(), because "no ground vias on the
        # board" is an answer to the question this function asks and an empty
        # sequence is not.
        raise AssertionError(
            f"{len(vias)} vias on the board and not one of them is on "
            f"{' or '.join(RETURN_VIA_NETS)} -- there is no return path to "
            f"measure")
    audio = re.compile(r"^(%s)\d+$" % "|".join(AUDIO_FAMILIES))
    rows = []
    for x, y, net in vias:
        if not audio.match(net):
            continue
        gap = min(math.dist((x, y), q) for q in ground)
        rows.append({"net": net, "x": x, "y": y, "gap_mm": gap,
                     "area_mm2": gap * height})
    rows.sort(key=lambda r: -r["gap_mm"])
    gaps = sorted(r["gap_mm"] for r in rows)
    return {
        "height_mm": height,
        "rows": rows,
        "ground_vias": len(ground),
        "audio_vias": len(rows),
        "worst_mm": gaps[-1] if gaps else 0.0,
        "median_mm": (statistics.median(gaps) if gaps else 0.0),
        "within_2mm": sum(1 for g in gaps if g <= 2.0),
        "total_mm2": sum(r["area_mm2"] for r in rows),
        "declared_mm2": AUDIO_RETURN_AREA_MM2,
    }


def return_sensitivity(board=BOARD, hz=None):
    """The ambient field that would put these loops at the mixer's own floor.

    **This is not a claim about the field and it is written so it cannot be
    read as one.** V = A dB/dt, so a total loop area A reaches a stated
    voltage at exactly one flux density, and that is arithmetic on numbers
    this project already owns: the area off the board, the frequency off the
    converter's datasheet, the floor out of MEASURED. What it buys is a scale
    -- it says what the copper laid here is worth without pretending to know
    the aggressor.
    """
    hz = design.SUPPLY_KHZ_TYP * 1e3 if hz is None else hz
    loops = return_loops(board)
    area_m2 = loops["total_mm2"] * 1e-6
    floor = socket.MEASURED["noise_floor"].value
    return {
        "hz": hz, "area_mm2": loops["total_mm2"], "floor_v": floor,
        "tesla_at_floor": floor / (2 * math.pi * hz * area_m2),
    }


def check_return_loops(board=BOARD):
    """The ratchet. Raises if the total loop area has grown."""
    measured = return_loops(board)
    if measured["total_mm2"] > AUDIO_RETURN_AREA_MM2 + 0.5:
        worst = measured["rows"][:6]
        raise AssertionError(
            f"the audio return loops add to {measured['total_mm2']:.1f} mm2 "
            f"and constraints.AUDIO_RETURN_AREA_MM2 declares "
            f"{AUDIO_RETURN_AREA_MM2:.1f} -- worst: "
            + ", ".join(f"{r['net']} at ({r['x']:.2f}, {r['y']:.2f}) "
                        f"{r['gap_mm']:.2f} mm" for r in worst)
            + ". Down as copper is laid, up only with the vias named.")
    return measured


# ---------------------------------------------------------------------------
# 5e. The domain crossings: what they run beside, and where their return goes
# ---------------------------------------------------------------------------
#
# **Every geometric instrument above this line is pointed at the audio nets.**
# parallel_runs() compares audio against audio and audio against the CV
# filter's passive node; audio_off_its_own_plane() and return_loops() both
# filter to AUDIO_FAMILIES; floorplan.check_crossings() reads the *netlist*,
# so it knows which signals cross the domain boundary and nothing at all about
# where or how. The class none of them covers is the one carrying the fastest
# edges on the board.
#
# So MCLK -- a continuously running 10.4 MHz clock -- could be laid 0.43 mm
# from SIN6 for 30 mm, and its return current could be sent on a 150 mm round
# trip to reach the only conductor joining the two planes, and **not one
# number in this repository would move.** Both are true of the board as laid.
#
# That is the trace-coupling finding one section up arriving one net class
# along instead of one router along: an instrument written for the victims
# that were interesting when it was written. The two functions below are the
# same measurement asked of the aggressors nobody had measured.


def crossing_signals():
    """The signals that cross the domain boundary. Read, not listed.

    floorplan.CROSSINGS already owns the list and floorplan.check_crossings()
    already holds it against the netlist, so a fourteenth crossing arrives in
    this file by being declared there rather than by somebody remembering to
    add it here. That is CROSSING_RULE's own correction applied to its
    consumer: the rule went stale because a second artefact restated it.

    Rails and grounds are dropped. A rail's coupling into audio is a supply
    question and design.rail_crosstalk() owns it; a ground plane is the return
    path rather than an aggressor.
    """
    # Imported here rather than at the top because floorplan imports design
    # and this file imports both -- a local import keeps the cycle impossible
    # rather than merely absent today.
    import floorplan
    skip = set(design.RAILS) | set(RETURN_VIA_NETS)
    return tuple(net for net in floorplan.CROSSINGS if net not in skip)


def _net_segments(board, names):
    """Copper on whole nets, keyed (net, layer). The unchannelled sibling of
    _segments(), through _raw_segments() -- which was checked against the
    parser and finds all 5081, unlike the via regex that found 151 of 994."""
    import collections
    text = board.read_text() if hasattr(board, "read_text") else board
    wanted = set(names)
    out = collections.defaultdict(list)
    for x0, y0, x1, y1, _w, layer, net in _raw_segments(text):
        if net in wanted and math.hypot(x1 - x0, y1 - y0) > 1e-6:
            out[(net, layer)].append((x0, y0, x1, y1))
    return out


# Total coupled length, over every (crossing signal, audio net) pair that runs
# within COUPLING_REACH_MM on one layer. A ratchet, in the shape
# AUDIO_OFF_MAGND_MM is: down as copper is moved, up only with the pairs named.
#
# **The number is dominated by one pair and that is the useful part.** MCLK
# against SIN6 is 30.2 mm at 0.428 mm, and MCLK is the only aggressor here
# that runs continuously rather than in bursts at the 2 kHz envelope frame.
# One `krt.py --nets "MCLK"` is what lowers this.
DIGITAL_AUDIO_MM = 244.2


def digital_audio_runs(board=BOARD):
    """Coupled length between each crossing signal and each audio net.

    Same layer, same machinery as parallel_runs(): _overlap() decides what
    counts as coupled and COUPLING_REACH_MM decides how close is close, so the
    two measurements are comparable rather than merely similar.

    **What this can and cannot price.** Through design.trace_mutual_
    capacitance() into pin_impedance() the worst pair here lands near -104 dB,
    fifty decibels inside the -54 dB requirement -- so on a steady-state
    divider it is comfortable, and that model is the whole of what board_
    coupling() does. What it does not cover is an aggressor whose *return*
    has to cross the pour gap, which is crossing_returns() below and is the
    same geometry asked the other way round. Neither function is the answer
    on its own; the pair of them is.
    """
    audio = re.compile(r"^(%s)\d+$" % "|".join(AUDIO_FAMILIES))
    text = board.read_text() if hasattr(board, "read_text") else board
    audio_nets = sorted({net for *_rest, net in _raw_segments(text)
                         if audio.match(net)})
    segments = _net_segments(text, tuple(crossing_signals()) + tuple(audio_nets))

    pairs = {}
    for (aggressor, layer_a), aggressor_segments in segments.items():
        if aggressor not in crossing_signals():
            continue
        for (victim, layer_v), victim_segments in segments.items():
            if victim not in audio_nets or layer_a != layer_v:
                continue
            length, pitch = 0.0, None
            for sa in aggressor_segments:
                for sb in victim_segments:
                    # Bounding-box reject before the sampled overlap, which is
                    # 12 point-to-segment solves and the inner loop here is
                    # thousands of pairs.
                    if (min(sa[0], sa[2]) - COUPLING_REACH_MM
                            > max(sb[0], sb[2])
                            or max(sa[0], sa[2]) + COUPLING_REACH_MM
                            < min(sb[0], sb[2])
                            or min(sa[1], sa[3]) - COUPLING_REACH_MM
                            > max(sb[1], sb[3])
                            or max(sa[1], sa[3]) + COUPLING_REACH_MM
                            < min(sb[1], sb[3])):
                        continue
                    piece, gap = _overlap(sa, sb)
                    if piece > 0.0:
                        length += piece
                        pitch = gap if pitch is None else min(pitch, gap)
            if length > 0.0:
                key = f"{aggressor}/{victim}"
                if key not in pairs or length > pairs[key]["length_mm"]:
                    pairs[key] = {"length_mm": length, "pitch_mm": pitch,
                                  "layer": layer_a}

    total = sum(row["length_mm"] for row in pairs.values())
    worst = max(pairs.items(), key=lambda kv: kv[1]["length_mm"],
                default=(None, None))
    return {"pairs": pairs, "total_mm": total,
            "worst": worst[0], "worst_row": worst[1],
            "declared_mm": DIGITAL_AUDIO_MM}


def check_digital_audio_runs(board=BOARD):
    """The ratchet. Raises if a crossing signal has moved closer to audio."""
    measured = digital_audio_runs(board)
    if measured["total_mm"] > DIGITAL_AUDIO_MM + 0.05:
        worst = sorted(measured["pairs"].items(),
                       key=lambda kv: -kv[1]["length_mm"])
        raise AssertionError(
            f"crossing signals run {measured['total_mm']:.1f} mm alongside "
            f"audio and constraints.DIGITAL_AUDIO_MM declares "
            f"{DIGITAL_AUDIO_MM:.1f} -- "
            + ", ".join(f"{pair} {row['length_mm']:.1f} mm at "
                        f"{row['pitch_mm']:.2f}" for pair, row in worst[:4])
            + ". Down as copper is moved, up only with the pairs named.")
    return measured


# How far a crossing signal's return current has to travel to find a conductor
# between the two ground planes, in millimetres, worst case. A ratchet.
#
# **Why it is a large number and not a small one.** In1.Cu and In2.Cu are both
# split at the same y, so a signal that crosses the boundary has no return
# path underneath it at all: the current has to run along one pour's edge to a
# part that bridges the domains, cross, and run back. Today exactly one part
# does that -- R902, at the west edge -- and the envelope ADC's bundle crosses
# at the east one.
#
# Lowering it is a stitching capacitor on the split, not a re-route. That adds
# no DC path, so R902 stays the module's only DC star and constraint 5.2 --
# which is about R901 and the *mixer* -- is untouched either way. What it does
# need is for verify.check_ground_star() to learn the difference between a DC
# bridge and an AC one, because today it holds "exactly one MAGND/MDGND part"
# and would refuse the fix.
CROSSING_RETURN_MM = 75.6


def domain_bridges():
    """Every part with a pin on MAGND and a pin on MDGND, and where it sits.

    Derived from the netlist rather than listed, so a stitching capacitor
    appears here by being drawn. That is the difference between this and the
    declaration it replaces: verify.check_ground_star() names R902, and a
    named part cannot tell you that a second one would have helped.
    """
    magnd = {ref for ref, _pin in design.NETS.get("MAGND", ())}
    mdgnd = {ref for ref, _pin in design.NETS.get("MDGND", ())}
    out = {}
    for ref in sorted(magnd & mdgnd):
        try:
            x, y, *_rotation = placement.position(ref)
        except Exception:                       # not placed is not a bridge
            continue
        out[ref] = (x, y)
    return out


def crossing_returns(board=BOARD):
    """Where each crossing signal cuts the pour gap, and how far its return is.

    The gap is the two pour edges, SPLIT_Y +- GROUND_GAP/2 -- the same pair
    audio_off_its_own_plane() measures from, for the same reason: between them
    there is no reference plane at all, so a track that spans them has nothing
    underneath it and its return current is somewhere else entirely.

    The distance reported is to the nearest domain_bridges() part, measured in
    the plane rather than through it. It is a lower bound on the return's path
    and an upper bound on nothing -- the current also has to get back, so the
    loop is about twice this.
    """
    edge = placement.SPLIT_Y
    signals = crossing_signals()
    segments = _net_segments(board, signals)
    bridges = domain_bridges()

    per_net = {}
    for (net, layer), rows in segments.items():
        for x0, y0, x1, y1 in rows:
            if (y0 - edge) * (y1 - edge) > 0:
                continue                        # both ends the same side
            t = 0.5 if y1 == y0 else (edge - y0) / (y1 - y0)
            at_x = x0 + t * (x1 - x0)
            nearest, distance = None, math.inf
            for ref, (bx, by) in bridges.items():
                gap = math.hypot(at_x - bx, edge - by)
                if gap < distance:
                    nearest, distance = ref, gap
            row = {"x_mm": at_x, "layer": layer,
                   "nearest": nearest, "distance_mm": distance}
            if net not in per_net or distance > per_net[net]["distance_mm"]:
                per_net[net] = row

    worst = max(per_net.items(), key=lambda kv: kv[1]["distance_mm"],
                default=(None, {"distance_mm": 0.0}))
    return {"edge_mm": edge, "bridges": bridges, "per_net": per_net,
            "worst": worst[0], "worst_mm": worst[1]["distance_mm"],
            "declared_mm": CROSSING_RETURN_MM}


def check_crossing_returns(board=BOARD):
    """The ratchet. Raises if a crossing's return path has got longer."""
    measured = crossing_returns(board)
    if measured["worst_mm"] > CROSSING_RETURN_MM + 0.05:
        worst = sorted(measured["per_net"].items(),
                       key=lambda kv: -kv[1]["distance_mm"])
        raise AssertionError(
            f"the worst crossing return is {measured['worst_mm']:.1f} mm and "
            f"constraints.CROSSING_RETURN_MM declares "
            f"{CROSSING_RETURN_MM:.1f} -- "
            + ", ".join(f"{net} at x={row['x_mm']:.1f} is "
                        f"{row['distance_mm']:.1f} mm from {row['nearest']}"
                        for net, row in worst[:4])
            + ". Down as bridges are added, up only with the nets named.")
    return measured


def board_coupling(board=BOARD, hz=20_000.0):
    """Channel-to-channel coupling through the copper, at every declared height.

    Capacitive and inductive both, because for a *low impedance* victim -- and
    every audio node on this board is one -- the inductive term is usually the
    one that bites. Here it does not, and the reason is that the aggressor
    current is 123 uA into a 10 kohm front end rather than amps.

    The victim impedances are the two that exist. `pin_impedance()` is the loom
    node, tens of ohms; `design.cv_node_impedance()` is CVX{n}, the MFB
    filter's passive internal node and the only per-channel net on the board
    with no active pin on it -- 4.9 kohm resistive, shunted by C1 to 142 ohm at
    exactly the frequency where the coupling would otherwise peak.
    """
    runs = parallel_runs(board)
    peak = socket.clipping_peak()
    current = peak / socket.RIN_OHMS
    rows = []
    for kind, impedance in (("audio_audio", pin_impedance(hz)),
                            ("audio_cv", design.cv_node_impedance(hz))):
        if kind not in runs:
            continue
        run = runs[kind]
        for height in design.PCB_H_SWEEP:
            farads = design.trace_mutual_capacitance(
                run["pitch_mm"], height) * run["length_mm"]
            henries = design.trace_mutual_inductance(
                run["pitch_mm"], height) * run["length_mm"]
            induced = 2 * math.pi * hz * henries * current
            rows.append({
                "kind": kind, "pair": run["pair"],
                "length_mm": run["length_mm"], "pitch_mm": run["pitch_mm"],
                "height_mm": height, "ohms": impedance,
                "capacitive_db": coupling_db(hz, farads, impedance),
                "inductive_db": 20 * math.log10(induced / peak),
            })
    # **The answer is at the declared height; the sweep is what it was worth.**
    # Before rules.FAB_STACKUP existed this had to quote the worst of a range,
    # because no height had been chosen. It is quoted at PCBWay's own 0.1855 mm
    # now, and the sweep is kept beside it so the sensitivity stays visible --
    # a figure that depends on an input the fabricator supplies should say so.
    declared = [r for r in rows if r["height_mm"] == design.PCB_H_MM]
    capacitive = max(r["capacitive_db"] for r in declared)
    swept = max(r["capacitive_db"] for r in rows)
    # What impedance the victim would need for the worst geometry to fail. The
    # bound that makes the rest of this robust: it is the impedance, not the
    # copper, that decides the answer, and nothing here is near it.
    worst = max(declared, key=lambda r: r["capacitive_db"])
    farads = design.trace_mutual_capacitance(
        worst["pitch_mm"], worst["height_mm"]) * worst["length_mm"]
    fails_at = 10 ** (ISOLATION_DB / 20) / (2 * math.pi * hz * farads)
    return {
        "rows": rows,
        "declared_h_mm": design.PCB_H_MM,
        "worst_db": capacitive,
        "worst_swept_db": swept,
        "height_costs_db": swept - capacitive,
        "margin_db": ISOLATION_DB - capacitive,
        "fails_at_ohms": fails_at,
        "verdict": ("good practice, not load-bearing"
                    if ISOLATION_DB - capacitive > 20 else "load-bearing"),
    }


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

    if BOARD.exists():
        b = board_coupling()
        print("5b. the same coupling, between two traces on the board")
        print("    constraint 5 asks this of the loom; nothing asked it of "
              "the copper")
        for row in b["rows"]:
            if row["height_mm"] != design.PCB_H_MM:
                continue
            print(f"   {row['pair']:<16} {row['length_mm']:6.1f} mm at "
                  f"{row['pitch_mm']:.2f} mm pitch, into {row['ohms']:.0f} ohm")
        print(f"   capacitive, at h = {b['declared_h_mm']:.4f} mm "
              f"{b['worst_db']:>7.1f} dB   "
              f"({b['margin_db']:.0f} dB inside the requirement)")
        print(f"   the same across the sweep   {b['worst_swept_db']:>7.1f} dB   "
              f"the height is worth {b['height_costs_db']:.1f} dB, and "
              f"rules.FAB_STACKUP is what settled it")
        off = check_audio_off_its_own_plane()
        print()
        print("5c. audio copper that is not over its own ground plane")
        print("    CROSSING_RULE says nothing audio-carrying crosses; "
              "check_crossings() reads the netlist and cannot see a track's "
              "path")
        for net, mm in sorted(off["per_net"].items(), key=lambda kv: -kv[1]):
            print(f"   {net:<16} {mm:6.1f} mm past y = {off['edge_mm']:.2f}")
        print(f"   total {off['total_mm']:>6.1f} mm against "
              f"{off['declared_mm']:.1f} declared -- a ratchet, and every "
              f"millimetre of it reaches a relay contact at y = 161.4")
        print(f"   was  {211.9:>6.1f} mm before the copper review and "
              f"{144.1:.1f} after it: PIN5 and SIN3 had every pad in the "
              f"analogue half and were routed through the digital one anyway")
        print(f"   then SIN2 came back as a detour rather than a necessity -- "
              f"33.5 mm to reach a relay pad 5 mm past the pour edge, re-laid "
              f"by krt.py --nets at 7.6")
        print()
        loops = check_return_loops()
        field = return_sensitivity()
        print("5d. where an audio signal changes reference plane")
        print("    In1 and In2 carry the same nets in the same places, so "
              "every via changes plane as well as layer and the return "
              "current has to transfer")
        print(f"   audio vias      {loops['audio_vias']:>6d}   against "
              f"{loops['ground_vias']} ground vias")
        print(f"   worst gap       {loops['worst_mm']:>6.2f} mm  "
              f"median {loops['median_mm']:.2f}, "
              f"{loops['within_2mm']} of {loops['audio_vias']} within 2 mm")
        print(f"   loop area       {loops['total_mm2']:>6.1f} mm2 against "
              f"{loops['declared_mm2']:.1f} declared -- a ratchet, at "
              f"{loops['height_mm']:.2f} mm of plane separation")
        print(f"   was            {1990.6:>6.1f} mm2 before returns.py, at a "
              f"median of 7.39 mm and a worst of 22.76")
        print(f"   not an impedance: {loops['worst_mm']:.2f} mm of In1/In2 "
              f"pair is tens of nH, and tens of nV at 20 kHz")
        print(f"   as a pickup loop it reaches the mixer's "
              f"{field['floor_v'] * 1e6:.0f} uV floor at "
              f"{field['tesla_at_floor'] * 1e9:.1f} nT of "
              f"{field['hz'] / 1e3:.0f} kHz field")
        print(f"   the field is the term nothing here derives -- "
              f"board_coupling() solves trace against trace, and an aggressor "
              f"inside a potted brick has no drawing")
        print()
        runs = check_digital_audio_runs()
        rets = check_crossing_returns()
        print("5e. the domain crossings, as aggressors and as return paths")
        print("    every measurement above this line filters to the audio "
              "nets; check_crossings() reads the netlist and knows which "
              "signals cross and nothing about where")
        for pair, row in sorted(runs["pairs"].items(),
                                key=lambda kv: -kv[1]["length_mm"])[:4]:
            print(f"   {pair:<16} {row['length_mm']:6.1f} mm at "
                  f"{row['pitch_mm']:.3f} mm pitch on {row['layer']}")
        print(f"   total {runs['total_mm']:>6.1f} mm against "
              f"{runs['declared_mm']:.1f} declared -- a ratchet, and "
              f"{runs['worst']} is the one aggressor that runs continuously")
        print(f"   priced as board_coupling() prices the others it is ~50 dB "
              f"inside the requirement; what that model does not carry is the "
              f"return path below")
        print(f"   bridges between the planes: "
              f"{', '.join(f'{r} at x={x:.1f}' for r, (x, _y) in rets['bridges'].items())}")
        for net, row in sorted(rets["per_net"].items(),
                               key=lambda kv: -kv[1]["distance_mm"])[:4]:
            print(f"   {net:<16} crosses at x = {row['x_mm']:6.1f}, "
                  f"{row['distance_mm']:5.1f} mm from {row['nearest']}")
        print(f"   worst {rets['worst_mm']:>6.1f} mm against "
              f"{rets['declared_mm']:.1f} declared -- so the return loop is "
              f"about twice it, and PWM1-6 are absent because U11 straddles "
              f"the split by design")
        print()
        induced = max(r["inductive_db"] for r in b["rows"])
        print(f"   inductive, the same        {induced:>7.1f} dB   "
              f"computed, not dismissed: a stiff node still takes a series emf")
        print(f"   would fail at              {b['fails_at_ohms']:>7.0f} ohm  "
              f"<- the impedance decides it; the loom node is "
              f"{pin_impedance(20_000.0):.0f}")
        print(f"   verdict     {b['verdict']}")
        print()
    else:
        print("5b. board coupling not measured -- no board at "
              f"{BOARD.name}; run gen_pcb.py")
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
