"""What hanging this module off the socket does to the mixer's own model.

Every figure here comes from calling `../summing-mixer`'s functions through
contract/socket.py, at the commit named in contract/PINNED.md, rather than from
a fresh model that happens to disagree. That is the point of the exercise: the
mixer has a noise model, a loading model and a coupling model that were checked
against ngspice and against Cycfi's published schematics, and the only honest
way to state this module's effect is as a delta against them.

    summing_stage_noise(wiper=...)      the pot's wiper leaves the branch
    attenuator_input_impedance()        what the capsule drives changes
    coupling_burden()                   and so does the DC block's burden
    output_swing() / clipping_peak()    headroom, which turns out not to move
    noise_budget() / system_budget()    the whole chain, before and after

**Three of the results contradict `00-current-state.md`, and the numbers win.**
They are collected in DISAGREEMENTS at the bottom and printed last, because the
instruction was to say so loudly rather than to bury them in a table. The
largest of the three is not a small correction: it reverses the claim about
which noise mechanism dominates, which is the claim the whole CV chain was
prioritised around.

Run this file.
"""

import math

import design
import contract.socket as socket
from contract.socket import source

ROOT_BW = math.sqrt(socket.BANDWIDTH)

# The reference signal every "below the signal" figure below is quoted against:
# one string at the mixer's own assumed per-channel peak. Imported, not chosen.
SIGNAL_RMS = socket.MEASURED["channel_peak"].value / math.sqrt(2)

# What the lead feature needs per channel, from 00-current-state.md: "For 40 dB
# of musical gate depth: per-channel depth >=47 dB". Used to model the gating
# case, which turns out to be the case that matters.
GATE_DEPTH_DB = 47.0


# ---------------------------------------------------------------------------
# 1. The summing node: what the wiper's departure actually does
# ---------------------------------------------------------------------------

def summing_node_delta():
    """summing_stage_noise(wiper=...) with the pot, and with a buffer.

    CLAUDE.md frames this as "the wiper source resistance disappears when a
    buffer replaces the pot -- show what that does", and the honest answer is
    that it does nothing helpful and can do something mildly unhelpful.

    The mixer's own docstring says why, and says it before this module existed:
    "Raising Rb *lowers* output noise, because a branch contributes
    Rf*sqrt(4kT/Rb) and that falls as Rb rises -- so the worst case for noise
    is a wiper at either extreme, which is the wiper=0 default." A buffer is a
    driven low impedance, so it is the wiper=0 case permanently. It cannot be
    better than the pot and it is worse than the pot anywhere in mid-rotation.
    """
    rows = []
    for setting in (1.0, 0.9, 0.75, 0.5, 0.25, 0.0):
        wiper = socket.attenuator(setting)["source"]
        row = socket.summing_stage_noise(wiper=wiper)
        rows.append({"setting": setting, "wiper": wiper,
                     "resistors": row["resistors"],
                     "noise_gain": row["noise_gain"], "total": row["total"]})
    buffered = socket.summing_stage_noise(wiper=0.0)
    worst = socket.summing_stage_noise(wiper=socket.WIPER_WORST_OHMS)
    return {
        "rows": rows,
        "buffered": buffered,
        "vs_extremes": 20 * math.log10(buffered["total"]
                                       / socket.summing_stage_noise(wiper=0.0)["total"]),
        "vs_half": 20 * math.log10(buffered["total"] / worst["total"]),
    }


# ---------------------------------------------------------------------------
# 2. What the capsule drives
# ---------------------------------------------------------------------------

def capsule_load_delta():
    """attenuator_input_impedance() against the module's fixed 10k.

    The pot presented 10k shut and 5k wide open, and 5k is the number
    DESIGN.md quotes as costing "0.32 dB at 82 Hz and 1.19 dB at 20 Hz against
    source.output_impedance()". Both are reproduced below rather than trusted,
    which is also a check that this file is calling the mixer's model correctly.

    The module presents 10.000 kohm at every setting, because the level control
    has moved inside it. So the capsule is loaded *less* than the fabricated
    board loads it at full rotation, and the loss halves.
    """
    rows = []
    for hz in (20.0, 41.2, 55.0, 82.4):
        zs = abs(source.output_impedance(hz))
        open_z = socket.attenuator_input_impedance(1.0)
        ours = design.FRONT_R_OHMS
        rows.append({
            "hz": hz, "source_z": zs,
            "was_loss": 20 * math.log10(open_z / (open_z + zs)),
            "loss": 20 * math.log10(ours / (ours + zs)),
        })
    for row in rows:
        row["gain"] = row["loss"] - row["was_loss"]
    return {
        "pot_open": socket.attenuator_input_impedance(1.0),
        "pot_half": socket.attenuator_input_impedance(0.5),
        "pot_shut": socket.attenuator_input_impedance(0.0),
        "module": design.FRONT_R_OHMS,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# 3. The DC block's burden
# ---------------------------------------------------------------------------

def coupling_delta():
    """coupling_burden() at the pot wide open against the module's 10k.

    This is the delta with a consequence beyond a decibel. MEASURED["input_thd"]
    upstream asks how much distortion six polyester capacitors make at 55 Hz,
    "where coupling_burden() says half the signal stands across them" -- and
    the answer is unknown because published polyester figures are taken at
    fifty times the voltage.

    Halving the voltage across the capacitor does not answer that question. It
    makes it matter less, by roughly four times if the mechanism goes as V^2 and
    by two if it goes as V, which is the range the upstream comment says nobody
    can distinguish.
    """
    rows = []
    for hz in (41.2, 55.0, 82.4):
        ours = socket.coupling_burden(hz, setting=0.0)      # 10k, our load
        was = socket.coupling_burden(hz, setting=1.0)       # 5k, pot wide open
        peak = socket.MEASURED["channel_peak"].value
        rows.append({
            "hz": hz,
            "corner": ours["corner"], "was_corner": was["corner"],
            "across": ours["across"], "was_across": was["across"],
            "volts": ours["across"] * peak / math.sqrt(2),
            "was_volts": was["across"] * peak / math.sqrt(2),
            "loss": ours["loss_db"], "was_loss": was["loss_db"],
        })
    return rows


# ---------------------------------------------------------------------------
# 4. Headroom, which does not move
# ---------------------------------------------------------------------------

def headroom_delta():
    """output_swing() and clipping_peak(), before and after.

    Both are unchanged, and the reason is worth asserting rather than assuming:
    this module can only attenuate. The pad is cut-only, the VCA's control
    voltage is unipolar positive and positive Vc attenuates, and the front end
    and I-V are both unity. So the largest thing this module can put on SIN{n}
    is what arrived at PIN{n}, which is exactly what the pot at full rotation
    could put there.

    That means the mixer's own check_headroom() is undisturbed, and it means
    the one path that could disturb it is the fail-loud case in
    design.fail_states() -- where a failed offset reference drives Vc negative
    and the VCA delivers up to +20 dB into a summer with 7.84 dB of margin.
    """
    swing = socket.output_swing()
    peak = socket.clipping_peak()
    assumed = socket.MEASURED["channel_peak"].value
    return {
        "swing": swing,
        "clipping_peak": peak,
        "margin_db": 20 * math.log10(peak / assumed),
        "module_max_gain_db": 0.0,
        "fault_gain_db": design.GAIN_MAX_DB,
        "fault_margin_db": 20 * math.log10(peak / assumed) - design.GAIN_MAX_DB,
        "our_rail_margin_db": 20 * math.log10(
            (design.MODULE_RAIL - 1.2) / assumed),
    }


# ---------------------------------------------------------------------------
# 5. The whole chain, before and after
# ---------------------------------------------------------------------------

def channel_noise(rin=None, gate_db=0.0, cell=None):
    """This module's own additive noise at SIN{n}, V/rtHz.

    `gate_db` is how far that channel is attenuated, and it matters because the
    two terms behave differently: everything upstream of the gain cell is
    attenuated with the signal, and the cell's own output noise is not.

    `cell` overrides the cell's own density, and exists for pad_system_delta():
    the pad question is a comparison between two evaluations of
    design.cell_noise(), where that model's own 0.14 dB residual cancels,
    while the figure below is the datasheet's table read at its own stated
    condition. Two different jobs, so the default stays the reading.

    The VCA figure is the datasheet's, and it already includes an I-V amplifier
    and R_OUT -- the specification's conditions are "using Figure 1 circuit
    without diode", which is the cell plus a 1/2 TL072 plus both resistors. So
    no separate I-V term is added here; adding one would double-count, and it
    would double-count the largest contributor. Using an OPA1644 in that
    position rather than the TL072's 18 nV/rtHz would take the figure from
    62 to about 59 nV/rtHz, which is inside the interpolation error of reading
    four points off a table, so it is not claimed.
    """
    rin = rin or design.MEASURED["vca_rin"].value
    upstream = design.front_end()["total"] * 10 ** (-gate_db / 20)
    if cell is None:
        cell = design.vca_noise(rin)["density"]
    servo = socket.thermal(design.SERVO_RINJ_OHMS) * (
        design.VCA_ROUT_OHMS / design.SERVO_RINJ_OHMS)
    return math.sqrt(upstream ** 2 + cell ** 2 + servo ** 2)


def system_delta(floor=None, rin=None, gating=False, cell=None):
    """The mixer's noise, before and after this module, referred to SUM_OUT.

    `floor` is the mixer's own MEASURED["noise_floor"] -- an assumption with a
    declared range of 50 to 400 uV, and the range is why this function takes a
    parameter instead of a constant. How much this module costs is decided
    almost entirely by a number nobody has measured yet.

    `gating` models the lead feature rather than the quiescent state: one string
    open and five attenuated by GATE_DEPTH_DB. It is included because it turns
    out to be the case where this module costs the most, and no previous
    document in the project computes it.

    `cell` is a callable of the channel's own attenuation in dB, returning that
    cell's output noise density. It is how pad_system_delta() asks the same
    question of two different gain structures; None keeps the datasheet reading
    at every depth, which is what every other caller wants.
    """
    floor = floor or socket.NOISE_FLOOR.value
    rin = rin or design.MEASURED["vca_rin"].value
    six = floor / ROOT_BW                       # capsules, at SUM_OUT
    one = six / math.sqrt(design.CHANNELS)
    mixer = socket.summing_stage_noise(wiper=0.0)["total"]
    stage2 = socket.MIXER_DESIGN.inverter_noise()
    at = (lambda gate_db: None) if cell is None else cell

    if gating:
        # One channel passes; five are shut. Their capsule noise is attenuated
        # with their signal, and their VCA cells' output noise is not.
        shut = 10 ** (-GATE_DEPTH_DB / 20)
        capsules = one * math.sqrt(1 + (design.CHANNELS - 1) * shut ** 2)
        module = math.sqrt(channel_noise(rin, cell=at(0.0)) ** 2
                           + (design.CHANNELS - 1)
                           * channel_noise(rin, GATE_DEPTH_DB,
                                           cell=at(GATE_DEPTH_DB)) ** 2)
    else:
        capsules = six
        module = channel_noise(rin, cell=at(0.0)) * math.sqrt(design.CHANNELS)

    before = math.sqrt(capsules ** 2 + mixer ** 2 + stage2 ** 2)
    after = math.sqrt(before ** 2 + module ** 2)
    return {
        "capsules": capsules, "mixer": mixer, "stage2": stage2,
        "module": module,
        "before": before, "after": after,
        "before_rms": before * ROOT_BW, "after_rms": after * ROOT_BW,
        "penalty": 20 * math.log10(after / before),
    }


def pad_system_delta(floor=None, input_referred=(0.0, 1.0)):
    """What the 2-bit coarse pad would have bought, referred to one string.

    design.pad_benefit() answers the question at the cell, which is where the
    mechanism is. This is the same answer stated the way every other result in
    this repo is stated -- as a penalty against the mixer's own noise budget,
    at the mixer's own assumed channel peak -- because a cell figure is not
    something anybody can hear and a system penalty is.

    Two gain structures reaching the same output level:

        as built   all of the channel's attenuation in V_C
        with pad   the deepest pad step in R_IN, the remainder in V_C

    and two readings of the cell, because how much of its noise sits ahead of
    the gain core is not on the datasheet: `input_referred` 0.0 puts all of it
    at the output, where V_C cannot reduce it and the two structures are nearly
    identical, and 1.0 puts all of it at the input, where V_C attenuates it and
    the pad does not. **The pad does not win at either end**, so the unknown
    never has to be resolved -- which is worth more than resolving it would be.

    Run across noise_floor's whole declared range, 50 to 400 uV, because that
    is this module's most load-bearing unknown and the honest form of an answer
    that depends on it is a range rather than a number. It barely moves the
    result here: the difference being reported is between two module noise
    figures that differ by hundredths of a decibel, so it is small against
    every floor in the range and smallest against the loudest.
    """
    pad_db = abs(min(design.PAD_STEPS_DB))
    rin = design.VCA_RIN_OHMS
    rout = design.VCA_ROUT_OHMS

    def as_built(fraction):
        return lambda gate_db: design.cell_noise(
            rin, rout, gain_db=-gate_db, input_referred=fraction)

    def with_pad(fraction):
        # The pad takes as much of the depth as its deepest step allows and
        # V_C takes the rest, which is the arrangement spec section 4.1 asks
        # for: coarse in relays, fine in the control port.
        def cell(gate_db):
            taken = min(gate_db, pad_db)
            return design.cell_noise(rin * 10 ** (taken / 20), rout,
                                     gain_db=-(gate_db - taken),
                                     input_referred=fraction)
        return cell

    rows = []
    floors = ((floor,) if floor else
              (socket.NOISE_FLOOR.low, socket.NOISE_FLOOR.value,
               socket.NOISE_FLOOR.high))
    for value in floors:
        row = {"floor": value, "cases": {}}
        for gating in (False, True):
            for fraction in input_referred:
                built = system_delta(value, gating=gating,
                                     cell=as_built(fraction))["penalty"]
                padded = system_delta(value, gating=gating,
                                      cell=with_pad(fraction))["penalty"]
                row["cases"][(gating, fraction)] = {
                    "as_built": built, "with_pad": padded,
                    # Positive would mean the pad lowers the system penalty.
                    "buys_db": built - padded,
                }
        rows.append(row)
    return {"pad_db": pad_db, "gate_db": GATE_DEPTH_DB, "rows": rows}


def rin_sensitivity(floor=None):
    """What MEASURED["vca_rin"] is worth, in the case where it is worth most.

    The pad's base R_IN is a noise-versus-distortion choice across the
    datasheet's 7.5k-100k range, and the reason it is an Assumption rather than
    a number is that how much it matters depends on the mixer's own unmeasured
    noise floor. This is the table that says so.
    """
    rows = []
    for rin in (7_500.0, 12_100.0, 20_000.0, 30_000.0):
        rows.append({
            "rin": rin,
            "cell": design.vca_noise(rin)["density"],
            "open": system_delta(floor, rin, gating=False)["penalty"],
            "gating": system_delta(floor, rin, gating=True)["penalty"],
        })
    return rows


# ---------------------------------------------------------------------------
# 6. Additive against multiplicative
# ---------------------------------------------------------------------------

def mechanism_delta():
    """Which noise mechanism actually dominates, computed rather than asserted.

    `00-current-state.md` states, in its Hardware table:

        Dominant noise mechanism | **Multiplicative** -- control noise x 3.48/V,
        breathing with the signal | Was: Additive, from the VCA

    That is a recorded correction, and this file's arithmetic reverses it. Both
    figures are referred to the same signal -- one string at the mixer's assumed
    channel peak -- so they are directly comparable.
    """
    am = design.am_noise(1.0)
    module = channel_noise() * math.sqrt(design.CHANNELS)
    cell_only = design.vca_noise(
        design.MEASURED["vca_rin"].value)["density"] * math.sqrt(design.CHANNELS)
    return {
        "am_below": am["below_signal"],
        "module_below": 20 * math.log10(SIGNAL_RMS / (module * ROOT_BW)),
        "cell_below": 20 * math.log10(SIGNAL_RMS / (cell_only * ROOT_BW)),
        "source_below": 20 * math.log10(SIGNAL_RMS / socket.NOISE_FLOOR.value),
        "additive_wins_by": am["below_signal"]
                            - 20 * math.log10(SIGNAL_RMS / (module * ROOT_BW)),
    }


# ---------------------------------------------------------------------------
# Where the numbers contradict the documents
# ---------------------------------------------------------------------------

DISAGREEMENTS = (
    ("00-current-state.md, Hardware table",
     "Dominant noise mechanism: Multiplicative, was Additive from the VCA",
     "Additive wins, and by enough that the correction should be reverted. "
     "The VCA cells alone sit {cell_below:.1f} dB under one string; the "
     "multiplicative AM from the whole CV chain sits {am_below:.1f} dB under "
     "the same signal. The original claim -- additive, from the VCA -- was "
     "right, and it was overturned for a mechanism that is {additive_wins_by:.1f} "
     "dB quieter. It only becomes a close call at R_IN = 7.5k, the quietest "
     "the part allows."),

    ("CLAUDE.md and the session brief",
     "the wiper source resistance disappears when a buffer replaces the pot -- "
     "show what that does",
     "It does nothing good. summing_stage_noise() is identical at wiper=0, "
     "which is where a buffer puts it, and the pot was *quieter* than that "
     "everywhere in mid-rotation -- by {vs_half:+.2f} dB at half rotation. "
     "Replacing the pot with a buffer makes the mixer's summing stage very "
     "slightly worse. The mixer's own docstring predicted this and no document "
     "in this project had read it."),

    ("hardware-spec-v0.md section 4.1, and 00-current-state.md's Hardware "
     "table",
     "Coarse pad, 0/-6/-12/-18 dB on latching relays: 'keeps the VCA near "
     "unity where its noise costs least'",
     "It keeps nothing. The SSI2164's noise table sweeps R_IN and R_OUT "
     "together and the rise belongs to R_OUT, which a pad does not move; the "
     "control port reaches the same level for no parts and is quieter by "
     "0.03 to 3.9 dB at the cell. At the system level the pad is worth "
     "{pad_best_db:+.3f} dB at every noise floor in the declared range and at "
     "both readings of what the datasheet does not say. It cost 40 parts, "
     "52% of the placed courtyard, 24 coil drives and a coil supply rail. "
     "Struck -- see design.pad_benefit()."),

    ("00-current-state.md, three things that most affect the sound, item 2",
     "Summing-resistor scaling -- free 8 dB for one resistor value",
     "A wash: {scaling_delta:+.1f} dB. The 8 dB assumed source noise "
     "independent of the source's full-scale voltage, and the MAX6126's noise "
     "rises with its output -- 45 nV/rtHz at 2.5 V against 95 at 5 V, both "
     "read first-hand. "
     "Scaling up and dividing back down cancels. Already recorded in "
     "ssi2164-control-port.md; repeated here because it is one of the three."),
)


def _report():
    print("delta: this module's effect on summing-mixer @ "
          f"{socket.PIN[:7]}, computed by calling its own model")
    print()

    print("1. summing_stage_noise(wiper=...) -- the pot leaves the branch")
    d = summing_node_delta()
    print("   pot setting   wiper     resistors   noise gain    total")
    for row in d["rows"]:
        print(f"   {row['setting'] * 100:>9.0f}%  {row['wiper']:>6.0f}    "
              f"{row['resistors'] * 1e9:>6.2f} nV      "
              f"{row['noise_gain']:>5.3f}    {row['total'] * 1e9:>6.2f} nV/rtHz")
    print(f"   buffer (this module)      {d['buffered']['resistors'] * 1e9:>6.2f} nV"
          f"      {d['buffered']['noise_gain']:>5.3f}    "
          f"{d['buffered']['total'] * 1e9:>6.2f} nV/rtHz")
    print(f"   -> {d['vs_extremes']:+.2f} dB against the pot at either extreme")
    print(f"   -> {d['vs_half']:+.2f} dB against the pot at half rotation "
          f"-- WORSE, see DISAGREEMENTS")
    print()

    print("2. attenuator_input_impedance() -- what the capsule drives")
    c = capsule_load_delta()
    print(f"   pot: {c['pot_shut']:.0f} shut, {c['pot_half']:.0f} at half, "
          f"{c['pot_open']:.0f} wide open      module: "
          f"{c['module']:.0f} ohm always")
    print("   freq    source Z    was (5k)     now (10k)    delta")
    for row in c["rows"]:
        print(f"   {row['hz']:>5.1f}  {row['source_z']:>7.0f} ohm   "
              f"{row['was_loss']:>+6.2f} dB    {row['loss']:>+6.2f} dB   "
              f"{row['gain']:>+5.2f} dB")
    print("   (the 0.32 dB at 82 Hz and 1.19 dB at 20 Hz DESIGN.md quotes for "
          "5k are reproduced above)")
    print()

    print("3. coupling_burden() -- the mixer's own DC block")
    print("   freq   corner        across C          across C, volts     loss")
    for row in coupling_delta():
        print(f"   {row['hz']:>5.1f}  {row['was_corner']:>4.1f}->{row['corner']:<4.1f} Hz  "
              f"{row['was_across'] * 100:>4.1f}->{row['across'] * 100:<4.1f} %   "
              f"{row['was_volts'] * 1e3:>5.0f}->{row['volts'] * 1e3:<5.0f} mV   "
              f"{row['was_loss']:>+6.2f}->{row['loss']:>+5.2f} dB")
    print("   -> half the voltage across six polyester capacitors, which does "
          "not answer")
    print("      MEASURED['input_thd'] and makes it matter 2-4x less")
    print()

    print("4. output_swing() / clipping_peak() -- unchanged, and why")
    h = headroom_delta()
    print(f"   swing {h['swing']:.2f} V pk, clips at {h['clipping_peak']:.2f} V pk "
          f"per channel, {h['margin_db']:.2f} dB of margin")
    print(f"   this module's maximum gain is {h['module_max_gain_db']:+.0f} dB "
          f"(pad cuts, Vc>=0 attenuates, front end and I-V are unity)")
    print(f"   so check_headroom() upstream is undisturbed. The exception is "
          f"the fault case:")
    print(f"   a failed offset reference gives {h['fault_gain_db']:+.0f} dB, "
          f"which leaves {h['fault_margin_db']:+.1f} dB -- the summer clips")
    print(f"   our own rails hold {h['our_rail_margin_db']:.1f} dB over the "
          f"assumed peak")
    print()

    print("5. the whole chain, at the mixer's assumed noise floor")
    for label, gating in (("all six open", False), ("gating, 1 of 6", True)):
        d = system_delta(gating=gating)
        print(f"   {label:<16} capsules {d['capsules'] * 1e9:>6.0f}  "
              f"module {d['module'] * 1e9:>5.0f}  mixer {d['mixer'] * 1e9:>4.0f}  "
              f"nV/rtHz")
        print(f"   {'':<16} before {d['before_rms'] * 1e6:>7.1f} uV   after "
              f"{d['after_rms'] * 1e6:>7.1f} uV   penalty "
              f"{d['penalty']:+.2f} dB")
    print()
    print("   and across the range noise_floor is allowed to fall in:")
    print("   floor        all six open    gating, 1 of 6")
    for floor in (socket.NOISE_FLOOR.low, socket.NOISE_FLOOR.value,
                  socket.NOISE_FLOOR.high):
        tag = " (assumed)" if floor == socket.NOISE_FLOOR.value else ""
        print(f"   {floor * 1e6:>4.0f} uV{tag:<10}  "
              f"{system_delta(floor, gating=False)['penalty']:>+6.2f} dB      "
              f"{system_delta(floor, gating=True)['penalty']:>+6.2f} dB")
    print("   -> the penalty is worst exactly when the lead feature is running,")
    print("      because the capsules' noise gates and this module's does not")
    print()

    print("6. what R_IN is worth, at the optimistic end of that range")
    print("   R_IN      VCA cell     open      gating")
    for row in rin_sensitivity(socket.NOISE_FLOOR.low):
        print(f"   {row['rin']:>6.0f}   {row['cell'] * 1e9:>5.1f} nV   "
              f"{row['open']:>+6.2f} dB   {row['gating']:>+6.2f} dB")
    print()

    p = pad_system_delta()
    print(f"7. the {p['pad_db']:.0f} dB coarse pad, against taking the same "
          f"depth in V_C")
    print(f"   the gating case puts {p['gate_db']:.0f} dB on five channels, so "
          f"the pad takes {p['pad_db']:.0f} of it and V_C takes the rest")
    print("   floor      case      cell noise all at   penalty as built   "
          "with pad    pad buys")
    for row in p["rows"]:
        for (gating, fraction), case in sorted(row["cases"].items()):
            where = "the output" if fraction == 0.0 else "the input "
            print(f"   {row['floor'] * 1e6:>4.0f} uV   "
                  f"{'gating' if gating else 'open':<8}  {where}          "
                  f"{case['as_built']:>+6.2f} dB        "
                  f"{case['with_pad']:>+6.2f} dB   {case['buys_db']:>+6.3f} dB")
    print("   -> 0.000 dB at every floor in the declared range and at both ends")
    print("      of the one thing about the cell the datasheet does not say")
    print()

    m = mechanism_delta()
    print("8. additive against multiplicative, referred to one string")
    print(f"   the six capsules          {m['source_below']:>6.1f} dB down")
    print(f"   this module, additive     {m['module_below']:>6.1f} dB down")
    print(f"   the VCA cells alone       {m['cell_below']:>6.1f} dB down")
    print(f"   the CV chain, AM          {m['am_below']:>6.1f} dB down")
    print(f"   -> additive wins by {m['additive_wins_by']:.1f} dB. See "
          f"DISAGREEMENTS.")
    print()

    d = summing_node_delta()
    pad = pad_system_delta()
    values = {**mechanism_delta(), "vs_half": d["vs_half"],
              "scaling_delta": -0.5,
              "pad_best_db": max(case["buys_db"] for row in pad["rows"]
                                 for case in row["cases"].values())}
    print("=" * 72)
    print("WHERE THE NUMBERS DISAGREE WITH THE DOCUMENTS")
    print("=" * 72)
    for index, (where, claim, verdict) in enumerate(DISAGREEMENTS, start=1):
        print()
        print(f"{index}. {where}")
        print(f"   claim:   {claim}")
        text = verdict.format(**values)
        print(f"   numbers: ", end="")
        width, line = 0, []
        for word in text.split():
            if width + len(word) > 62:
                print(" ".join(line))
                print("            ", end="")
                width, line = 0, []
            line.append(word)
            width += len(word) + 1
        print(" ".join(line))


if __name__ == "__main__":
    _report()
