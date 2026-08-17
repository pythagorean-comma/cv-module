"""One channel of the per-string CV module, as derived values.

Values only, in this pass. The netlist, the five constraint checks and the
board follow; this file is where every number gets its arithmetic, because a
schematic full of plausible values is worse than an incomplete one -- it looks
finished.

    from the mixer's RV{n}01 socket
      PIN{n} --[ 10k ]--+-- inverting unity front end --+-- envelope tap
       (pin 1)          |          (Rf 10k)             |
                     virtual                            +--[ 10u ]--[ pad ]--,
                      earth                                                  |
                                                          +-------------------+
                                                          |
                                                    R_IN 12k1..97k6
                                                          |
      SIN{n} <-- I-V + DC servo <-- SSI2164 <-------------+
       (pin 2)      (R_OUT 12k1)      ^  Vc
                                      |
                            2-pole MFB, 255 Hz, x0.809
                                      ^
                    +2V5 ref --> 74AHC541 --> R1 22k     R_OFF 22k <-- -2V5
                                  (Vcc = Vref)              (inverted ref)
       AGND <---------------------------------------------- channel return
       (pin 3)

Three things about the shape, because each is a departure from
`hardware-spec-v0.md` and each is derived rather than preferred.

**The front end inverts.** The spec says "buffer, unity gain", which would be a
follower. A follower leaves the module's overall polarity inverted, because the
VCA and its I-V converter invert -- and the mixer's stage 2 exists precisely to
restore absolute polarity, because this instrument's mono sum may be mixed with
the RMC piezo system. An inverting unity stage costs nothing, restores polarity,
and presents `PIN{n}` an exact 10k into a virtual earth rather than a shunt
resistor in parallel with a follower's input. See front_end().

**The coarse pad is R_IN, not a pad.** The SSI2164 is current-in, so gain is
R_OUT/R_IN and attenuation is a larger R_IN. Switching R_IN puts the relay
contacts in series with 12k1-97k6 carrying microamps, where 100 mohm of contact
resistance is a 1e-5 error -- against a passive divider, where the same contact
sits in the shunt leg and its resistance is the pad ratio. See pad_states().

**The CV chain is the datasheet's Figure 10, complemented.** Which makes the
whole CV path fail-silent by construction rather than by firmware, and makes
reference noise vanish at the loud end of the control range. See cv_filter()
and control_noise().

Nothing here has been built or measured. The numbers still open live in
MEASURED below, in the shape `../summing-mixer` uses: the value assumed, the
range the design survives, and what changes when the meter disagrees.

Everything about the fabricated mixer comes through contract/socket.py, from
the commit named in contract/PINNED.md. Nothing upstream is retyped.
"""

import math

import contract.socket as socket

CHANNELS = socket.CHANNELS

# Reused rather than reimplemented: the mixer's Assumption class, its noise
# constants and its thermal() are the same physics and the same conventions,
# and a second copy of 4kTR would be a second place to be wrong.
Assumption = socket.MIXER_DESIGN.Assumption
thermal = socket.thermal
BOLTZMANN = socket.BOLTZMANN
TEMPERATURE = socket.TEMPERATURE          # 300 K, the mixer's convention
BANDWIDTH = socket.BANDWIDTH              # 20 kHz, unweighted

ELECTRON_CHARGE = 1.602176634e-19


# ---------------------------------------------------------------------------
# What is still a guess
# ---------------------------------------------------------------------------

MEASURED = {
    # The one that decides how much the VCA's own noise matters, and it is not
    # a measurement of this module at all -- it is the mixer's, inherited.
    "noise_floor": socket.NOISE_FLOOR,

    "vca_rin": Assumption(
        value=12_100.0, units=" ohm R_IN/R_OUT at the 0 dB pad step",
        low=7_500.0, high=20_000.0,
        question="How low can R_IN go before distortion costs more than the "
                 "noise it buys? The datasheet gives a range and a direction "
                 "-- 7.5k to 100k, 'lower values will produce the best noise "
                 "performance at some cost in distortion' -- and no number.",
        sets="the VCA's output noise, and with it whether this module is "
             "audible against the six Nu capsules at all",
        when_wrong="Nothing structural: four resistors per channel and R_OUT. "
                   "How much it matters is decided entirely by the mixer's "
                   "own noise_floor assumption -- at the predicted 144 uV the "
                   "whole choice is worth 0.3 dB, and at the optimistic end "
                   "of its declared range it is worth 0.8 dB. Measure that "
                   "first; this is downstream of it."),

    "cv_corner": Assumption(
        value=254.7, units=" Hz, 2-pole", low=200.0, high=400.0,
        question="Is a 250 Hz CV filter fast enough for the gate feel? Open "
                 "question 5 in 00-current-state.md, and it is a judgement by "
                 "ear rather than a measurement.",
        sets="the anti-AM filtering, the de-click, and how the gate feels",
        when_wrong="Two capacitors per channel. The corner scales as 1/C with "
                   "the resistors fixed at the <=22k the noise budget wants, "
                   "so 400 Hz is C1 = 36n / C2 = 15n and nothing else moves. "
                   "Note the direction of the trade: faster is a worse "
                   "anti-AM filter and a sharper click, and 00-current-state "
                   "puts this block at 15-20 dB of the whole noise argument."),

    "servo_vos": Assumption(
        value=0.5e-3, units=" V, servo amplifier input offset",
        low=0.05e-3, high=3.0e-3,
        question="What input offset voltage does the servo amplifier actually "
                 "have? The residual DC on SIN{n} is this figure and almost "
                 "nothing else -- the loop drives its own offset to the "
                 "output.",
        sets="the DC this module leaves on SIN{n}, and therefore whether "
             "constraint 3 holds",
        when_wrong="See servo_residual(). What the constraint actually "
                   "protects is DC *current* through the mixer's master "
                   "wiper, and C703 turns 3 mV at SUM_OUT into 3 nA there -- "
                   "the same order as the 0.2-1.0 nA the mixer already "
                   "accepts from its own op-amp. Even the top of this range "
                   "is comfortable. If it were not, the answer is a "
                   "zero-drift part in the servo and not a series capacitor: "
                   "a capacitor would put a second high-pass within a decade "
                   "of the mixer's own 15.9 Hz, which is what its "
                   "DC_BLOCK_VALUE comment warns against."),

    "logic_law_error": Assumption(
        value=0.23e-2, units=" fractional, '541 output-impedance asymmetry",
        low=0.05e-2, high=1.0e-2,
        question="How different are the 74AHC541's output resistances high "
                 "and low, at Vcc = 2.5 V? The asymmetry is a "
                 "duty-dependent non-linearity in the control law, and the "
                 "datasheet characterises VOH/VOL at 3.3 V and 4.5 V only.",
        sets="the linearity of dB against code, and nothing else",
        when_wrong="Nothing. It is common to all six channels -- same part, "
                   "matched -- so it is a law error and not a matching error, "
                   "and 0.23 % over a 61 dB span is 0.14 dB. Calibratable in "
                   "firmware from a single measured curve if it ever matters."),
}


# ---------------------------------------------------------------------------
# The SSI2164, from the datasheet
# ---------------------------------------------------------------------------
# Rev 3.4, February 2023. Every figure below is quoted, with the page it is on,
# and ssi2164-control-port.md is the full read. Nothing here came from a
# secondary source: spec section 2 exists because the working figures did, and
# four of them were wrong.

VCA = "SSI2164"
VCA_DATASHEET = "https://www.soundsemiconductor.com/downloads/ssi2164datasheet.pdf"
VCA_REVISION = "Rev 3.4, February 2023"

# Page 2. -33 mV/dB, and the sign convention that matters: positive Vc
# attenuates, 0 V is unity, negative Vc amplifies. Unipolar positive control is
# therefore attenuate-only, which is the whole reason this design needs no
# bipolar CV -- see cv_filter().
GAIN_CONSTANT = -0.033              # V/dB
GAIN_CONSTANT_TEMPCO = -3300e-6     # per degC, page 2; PTAT, page 4

# Page 2, and this is the figure spec section 4.2 spent a resistor against.
# 9/10/11 kohm min/typ/max, formed by an on-die 9k series and 1k shunt (Figure
# 4), so the port is a *voltage* input with a 10:1 divider -- not the
# current-summing node the spec assumed. Page 11 note 2 states the consequence
# as a requirement: keep the source impedance low "to eliminate any effect of
# the wide tolerance on the 10kohm control port input impedance".
CONTROL_Z = (9_000.0, 10_000.0, 11_000.0)
CONTROL_DIVIDER = 0.1               # 1k / (9k + 1k), Figure 4 and equation (3)

# Page 2. Range and the control voltages that reach it.
GAIN_MAX_DB = 20.0
GAIN_MIN_DB = -100.0
CONTROL_FEEDTHROUGH_DB = -60.0      # typ, 0 dB -> -40 dB

# Page 2, Class AB, 20 Hz - 20 kHz unweighted, R_IN = R_OUT. Four points, and
# spec section 4.1 quoted the worst of them as "the datasheet noise condition".
# Page 4: "A 20kohm value for R_IN is recommended for most applications, but
# can range from 7.5kohm to 100kohm -- lower values will produce the best
# noise performance at some cost in distortion."
VCA_NOISE_DBU = {30_000.0: -93.0, 20_000.0: -96.0,
                 15_000.0: -98.0, 7_500.0: -101.0}
VCA_RIN_RANGE = (7_500.0, 100_000.0)

# Page 4. Input current handling is ~1 mA peak; the datasheet advises designing
# for 900 uA where R_IN is 10k or below on supplies of +/-12 V or more.
VCA_INPUT_CURRENT_MAX = 900e-6

# Page 2. Class AB, Vc = GND, per package. Spec section 1.1 sized a supply
# around 60-80 mA for the whole module; the VCAs are 5 % of that.
VCA_SUPPLY_MA = 6.0
VCA_SUPPLY_MA_MAX = 8.0
VCA_RAIL_RANGE = (4.0, 18.0)

# Page 3, Figure 1. Not optional and absent from the spec: "a 220ohm resistor
# in series with a 1200pF capacitor connected to ground ensures stable
# operation. The SSI2164 is quite tolerant of RC network selection, but
# 220ohm/1200pF has been proven to work well over a wide range of R_IN values".
VCA_RC_OHMS = 220.0
VCA_RC_FARADS = 1200e-12

# Page 4, one sentence, and it is about the lead feature rather than the noise
# budget: "An optional series-connected 10uF capacitor is recommended for
# improved control feedthrough."
#
# Control feedthrough is DC offset at I_IN multiplied by a changing gain, which
# arrives as a click on every gate transition -- at roughly 8 steps per second,
# in a feature whose entire premise is that the gating reads as a sequence of
# timbres rather than as a chopped rhythm. The spec lists the servo on the
# output side and not this on the input side; they are the same fault seen from
# the two ends of the cell.
VCA_INPUT_BLOCK = "10u/16V X7R"
VCA_INPUT_BLOCK_FARADS = 10e-6

# Page 3: "Leave open for Class AB operation." Page 5: "Class AB will yield the
# best noise performance which is achieved with Pin 1 left open." Page 6, on
# Class A: "the high quiescent current level has a severe impact on noise floor
# and control feedthrough rejection." Page 11 note 1 calls Class AB
# "(recommended)".
#
# Class A is 12 dB noisier at every R_IN (-84 dBu against -96 at 20k) and worse
# at control feedthrough, which is the binding constraint on the lead feature.
# So MODE is open and R_M is not fitted. The spec does not mention this pin.
VCA_MODE = "open"                   # Class AB
VCA_PACKAGES = 2                    # 3 + 3, see allocation() -- not 4 + 2

# Page 11, note 1. 118 degC/W for the SOP16, and the dissipation on this
# module's own +/-12 V rails is the datasheet's own example figure.
VCA_THETA_JA = 118.0
MODULE_RAIL = 12.0


def die_rise():
    """How far above ambient the SSI2164's junction sits, degC.

    Class AB across both rails, which is 24 V x 6 mA = 144 mW -- the same
    figure page 11 works its own example from, so the 17 degC it predicts is
    reproduced here rather than quoted.
    """
    watts = 2 * MODULE_RAIL * VCA_SUPPLY_MA * 1e-3
    return VCA_THETA_JA * watts


def control_law(volts, ambient_c=25.0):
    """Gain in dB for a control voltage, at an ambient temperature.

    The law is not a design choice. Rossum's equation (3) on page 10 gives

        G = exp( -q A Vc / kT )        A = CONTROL_DIVIDER, the on-die 9k:1k

    so the constant is kT ln10 / (20 q A) volts per dB and is proportional to
    absolute temperature -- which is what GAIN_CONSTANT_TEMPCO records, and why
    the datasheet says the law is "essentially set by transistor physics".

    Referenced so that the datasheet's own -33 mV/dB is returned at its own
    stated condition (TA = 25 degC, after 60 s of operation). That is a
    2.4 % correction on the theoretical figure and it is applied rather than
    argued: the theory gives the *shape* and the part gives the scale.
    """
    kelvin = 273.15 + ambient_c + die_rise()
    reference = 273.15 + 25.0 + die_rise()
    constant = GAIN_CONSTANT * kelvin / reference
    return volts / constant


def control_constant(ambient_c=25.0):
    """V per dB at an ambient temperature. Negative, as the datasheet has it."""
    kelvin = 273.15 + ambient_c + die_rise()
    reference = 273.15 + 25.0 + die_rise()
    return GAIN_CONSTANT * kelvin / reference


def am_sensitivity():
    """d(g)/g per volt at the control port.

    Falls straight out of the law and needs no separate trust:

        d(ln G)/dVc = -q A / kT = -ln(10) / 0.66 = -3.488 per volt

    which is spec section 4.2's -3.48, confirmed. It is the number that makes
    control noise a *multiplicative* mechanism and the CV chain worth more than
    the controller.
    """
    return math.log(10) / (20 * abs(GAIN_CONSTANT))


def tempco_span(nominal_db=-40.0):
    """What a fixed control voltage does to gain across the ambient range.

    AMBIENT_C is 0-50 degC, inherited from the mixer's own DIELECTRICS comment
    through contract/socket.py rather than guessed here.

    The result is 6 dB of wander on a 40 dB gate, and the reason it is accepted
    rather than compensated is that it is *common-mode*: one die, one law, six
    channels. The lead feature is differential -- 00-current-state.md measures
    summed gain constant at 1.0500 min and max because the pattern opens
    exactly one string per step -- so a shift that moves all six identically
    does not disturb what the feature depends on.

    Compensating would mean three more parts per channel (the datasheet's
    Figure 2 NTC network) on the one node in the design where added noise is
    multiplied into the audio, or a +3300 ppm/degC resistor per channel, which
    page 10 names as the historical practice and describes as increasingly
    unbuyable. Declined, and the datasheet agrees: "low enough to be
    unimportant in most applications".

    The condition on that: the two packages must sit at the same temperature,
    or the error stops being common-mode and becomes a six-way matching error.
    That is a floorplan constraint and not a value.
    """
    volts = nominal_db * GAIN_CONSTANT
    low, high = socket.AMBIENT_C
    return {
        "volts": volts,
        "die_rise": die_rise(),
        "cold": control_law(volts, low),
        "nominal": control_law(volts, 25.0),
        "hot": control_law(volts, high),
        "span": abs(control_law(volts, low) - control_law(volts, high)),
    }


def vca_noise(rin):
    """Output noise density of one VCA channel at unity, V/rtHz.

    Interpolated log-log through VCA_NOISE_DBU, which is four measured points
    rather than a model, so this is a reading of the datasheet's graph and not
    a derivation. Two things it does not say, both recorded rather than
    smoothed over:

    The table's condition is R_IN = R_OUT. That holds only at the 0 dB pad
    step; the other three raise R_IN and leave R_OUT alone, so their noise is
    not on this curve and this function is called with the base value.

    And it is a total, not a density -- dBu over 20 Hz to 20 kHz unweighted --
    so the conversion below assumes it is flat. The datasheet publishes no
    spectrum.
    """
    points = sorted(VCA_NOISE_DBU)
    if rin <= points[0]:
        dbu = VCA_NOISE_DBU[points[0]]
    elif rin >= points[-1]:
        dbu = VCA_NOISE_DBU[points[-1]]
    else:
        lower = max(p for p in points if p <= rin)
        upper = min(p for p in points if p >= rin)
        if lower == upper:
            dbu = VCA_NOISE_DBU[lower]
        else:
            fraction = math.log(rin / lower) / math.log(upper / lower)
            dbu = (VCA_NOISE_DBU[lower]
                   + fraction * (VCA_NOISE_DBU[upper] - VCA_NOISE_DBU[lower]))
    rms = 0.7746 * 10 ** (dbu / 20)
    return {"dbu": dbu, "rms": rms, "density": rms / math.sqrt(BANDWIDTH)}


# ---------------------------------------------------------------------------
# The front end
# ---------------------------------------------------------------------------

# A single-ended inverting unity stage. Two resistors.
#
# **It was a four-resistor difference amplifier, and the reason it was is worth
# more than the circuit.** Constraint 2 in CLAUDE.md reads:
#
#     "Exactly one bond between module audio ground and board AGND. Six
#      separate returns to six pin-3s, not commoned in the module."
#
# Those halves look mutually exclusive -- six returns tied to module ground is
# six bonds in parallel -- and this file resolved them by making the return a
# *sense* line into a difference amplifier's non-inverting input, which made
# constraint 5's word "triad" exact and satisfied all five constraints
# literally. It was a good piece of reasoning about a sentence and it was
# reasoning about the wrong thing.
#
# **The clause has no mechanism.** Per-channel returns exist to prevent
# shared-impedance crosstalk: N channels' return currents through one
# conductor's impedance put each channel's signal into every other channel's
# reference. Computed for this module, with a *single* bond carrying all six:
#
#     bond wire            pairwise      all six coherent
#     24 AWG, 100 mm       -122 dB       -106 dB
#     30 AWG, 200 mm       -103 dB        -88 dB
#
# against 00-current-state.md's requirement of -54 dB per pair. Even a
# deliberately bad bond has 49 dB of margin, because the current through it is
# 35 uA per channel and the impedance is milliohms. Nothing about six returns
# is reachable from that.
#
# The other half of the constraint is real and is kept: one bond avoids a loop
# enclosing the mixer's AGND pour and the loom, which is the mixer's own
# _GROUND_RULE applied across the connector, and verify.py checks it.
#
# **How it survived is the part to keep.** The sentence was generated in an
# earlier session answering a question about power, not derived from a
# measurement or a datasheet; it was then written into CLAUDE.md under the
# heading "load-bearing constraints -- check these mechanically, not by eye",
# and being in that list is what made it unquestionable. Every instrument
# downstream agreed with it: the netlist satisfied it, verify.py asserted it,
# and test_verify.py proved the assertion could fail. All of that was true and
# none of it asked whether the requirement had a mechanism.
#
# That is this project's own recurring failure with the polarity reversed. The
# mixer's PUMP_RULES records a source cited and never read; this is a
# constraint cited and never *derived*. From the inside they look identical --
# a checked box either way -- which is why the arithmetic above is in this
# comment and not in a commit message.
#
# So: the shields are the six things that reach six pin-3s, one end only, per
# constraint 5. The audio is a twisted pair inside each. The return conductor
# and the two resistors that sensed it are gone.
#
# Rejected on the way here, recorded so it is not re-proposed:
#
#   * **A follower on a 10k shunt**, which is what spec section 4.1 asks for.
#     It leaves the module's polarity inverted, because the VCA and its I-V
#     converter invert (page 4), and the mixer's stage 2 exists to restore
#     absolute polarity because this instrument's mono sum may be mixed with
#     the RMC piezo system. It also makes PIN{n} see 10k in parallel with the
#     follower and with the envelope tap -- section 4.1's "1 Mohm series,
#     shifts the corner ~1 %" is exactly 10k || 1M, which is that tap sitting
#     on this node. An inverting stage presents R{n}01 into a virtual earth,
#     which is 10.000 kohm exactly with nothing else on it.
#
# 0.1 % thin film, for the reason the mixer gives at its own RIN: 0.1 % parts
# are thin film and thin film has no excess noise worth the name. Not for the
# tolerance -- though here the tolerance does something the mixer's does not,
# because R{n}01 *is* the socket contract.
FRONT_R = "10k 0.1%"
FRONT_R_OHMS = 10_000.0

# OPA1644, named in spec section 4.2 for the CV filter. Used throughout rather
# than introducing a second part.
#
# 31 sections: 6 front ends, 6 I-V, 6 servos, 6 CV filters, 6 envelope
# rectifiers and one reference inverter. Eight quads, one spare. The servo and
# rectifier sections do not need a 3.3 nV/rtHz JFET part and a cheaper quad
# would serve; that is a BOM optimisation and not a design change, and it is
# left until the BOM is costed.
OPAMP = "OPA1644"
OPAMP_EN = 3.3e-9
OPAMP_SECTIONS = 4
OPAMP_NEEDED = 6 * 5 + 1
OPAMP_QUADS = -(-OPAMP_NEEDED // OPAMP_SECTIONS)


def front_end():
    """The inverting unity stage: what PIN{n} sees, and what it costs.

    **The socket load is R{n}01 exactly** -- 10.000 kohm into a virtual earth,
    at the top of constraint 4's 5-10 kohm window, with nothing else on the
    node. The corner it makes with the mixer's DC block is computed from the
    mixer's own DC_BLOCK_FARADS.

    **The corner is 15.9 Hz, which is the shut end of the mixer's own range**
    and not the 31.8 Hz spec section 4.1 claims for a 10k load. 31.8 Hz was the
    pot wide open, where RIN hung on the top of the track and the load was 5k.
    So this module presents the mixer's DC block an easier load than the
    fabricated worst case, and buys about 1.0 dB at 55 Hz -- see
    dc_block_delta(). It also admits proportionally more subsonic energy, which
    is the direction 1 uF was chosen against, and that is recorded as an
    assumption rather than resolved.

    **Noise** is 19 nV/rtHz, against 27 for the difference amplifier this
    replaced. Six of them power-sum at the mixer's summing node and land 26 dB
    under the six Nu capsules, so the front end is not where this module's
    noise comes from -- the VCA cell is, at 62 nV/rtHz.
    """
    corner = 1.0 / (2 * math.pi * socket.DC_BLOCK_FARADS * FRONT_R_OHMS)
    gain = 1.0
    noise_gain = 1 + gain
    e_res = math.hypot(thermal(FRONT_R_OHMS) * gain, thermal(FRONT_R_OHMS))
    total = math.hypot(e_res, OPAMP_EN * noise_gain)
    return {
        "socket_ohms": FRONT_R_OHMS,
        "corner": corner,
        "noise_gain": noise_gain,
        "resistors": e_res,
        "total": total,
        "six_channels": total * math.sqrt(CHANNELS),
    }


def dc_block_delta():
    """What this module does to the mixer's own input coupling, per channel.

    Called rather than reasoned about: coupling_burden() is the mixer's
    function and this is the same question asked with a different load. The
    pot presented 10k shut and 5k wide open; this module presents 10k always,
    which is the shut end -- so the burden across C{n}01 falls and the loss at
    the bottom of the instrument falls with it.
    """
    rows = []
    for hz in (41.2, 55.0, 82.4):
        # setting=0.0 is the pot shut, which is the 10k this module replicates;
        # setting=1.0 is wide open at 5k, the fabricated worst case.
        ours = socket.coupling_burden(hz, setting=0.0)
        worst = socket.coupling_burden(hz, setting=1.0)
        rows.append({
            "hz": hz,
            "corner": ours["corner"],
            "across": ours["across"],
            "loss_db": ours["loss_db"],
            "was_loss_db": worst["loss_db"],
            "gain_db": ours["loss_db"] - worst["loss_db"],
        })
    return rows


# ---------------------------------------------------------------------------
# The coarse pad, which is R_IN
# ---------------------------------------------------------------------------

# 0 / -6 / -12 / -18 dB in two bits, per spec section 4.1, and section 4.5's
# "12 coils (six 2-bit pads)" fixes the count at two dual-coil latching relays
# per channel.
PAD_STEPS_DB = (0.0, -6.0, -12.0, -18.0)

# The four R_IN values, E96, and the base is MEASURED["vca_rin"].
#
# Why the pad is R_IN and not a pad. The SSI2164 is a current-in device, so
# channel gain is R_OUT/R_IN and 6 dB of attenuation is twice the input
# resistor. That puts the relay contacts in series with 12k1 to 97k6 carrying
# at most 100 uA, where a contact's 100 mohm is a 1e-5 error and its
# degradation over a decade is still nothing. A passive divider ahead of a
# fixed R_IN puts the same contact in the shunt leg, where its resistance *is*
# the pad ratio and its drift is a level shift -- on a switch that operates
# every time the player changes a preset.
#
# 12k1 rather than the datasheet's recommended 20k because the top step has to
# stay inside the part. 20k doubles three times to 160k, and page 4's range
# stops at 100k; 12k1 doubles to 96k8 and clears it. It is also the quieter end
# of the recommendation, and the direction the datasheet gives is that lower is
# quieter at some cost in distortion.
VCA_RIN_STEPS = (12_100.0, 24_300.0, 48_700.0, 97_600.0)

# R_OUT is fixed and equals the base R_IN, so the 0 dB step is exactly unity
# and every other step is attenuation. Unity is where spec section 4.1 wants
# the cell -- "keeps the VCA near unity where its noise costs least".
VCA_ROUT = "12k1 0.1%"
VCA_ROUT_OHMS = 12_100.0

# Across R_OUT at the I-V converter. Page 4: "Many op-amps require a feedback
# capacitor to preserve phase margin. A value of 100pF will suffice in most
# cases; larger values can be used to reduce high-frequency noise at the
# expense of bandwidth."
IV_CF = "100p/50V C0G"
IV_CF_FARADS = 100e-12

# Dual-coil latching, two changeover poles, dry signal-level contacts, and a
# 3-10 ms coil pulse per spec section 4.5. **The part is not chosen here**: the
# spec names the drive (TPIC6B595) and the one-shot (74LVC1G123) and does not
# name the relay, and section 6 says not to invent one. See ASSUMPTIONS.md.
PAD_RELAYS_PER_CHANNEL = 2
PAD_RELAY = None


def pad_states():
    """The four pad steps, as they actually come out of E96 resistors.

    Accuracy is irrelevant here and the arithmetic is reported anyway, because
    "coarse" is a claim about what the step is for and not permission to skip
    checking it. What does matter is the two right-hand columns: the input
    current the VCA sees at the mixer's own clipping_peak(), against the 900 uA
    page 4 advises designing to, and whether each step stays inside the
    7.5k-100k the part is specified over.
    """
    base = VCA_RIN_STEPS[0]
    peak = socket.clipping_peak()
    rows = []
    for rin in VCA_RIN_STEPS:
        rows.append({
            "rin": rin,
            "db": 20 * math.log10(VCA_ROUT_OHMS / rin),
            "current": peak / rin,
            "in_range": VCA_RIN_RANGE[0] <= rin <= VCA_RIN_RANGE[1],
            "block_corner": 1.0 / (2 * math.pi * VCA_INPUT_BLOCK_FARADS * rin),
        })
    return {"base": base, "peak": peak, "steps": rows,
            "headroom_ratio": VCA_INPUT_CURRENT_MAX / (peak / base)}


def allocation():
    """Why the six channels go 3 + 3 across two quads and not 4 + 2.

    Not in the spec, and it follows from what the datasheet establishes.
    Crosstalk is the binding constraint on the lead feature -- 00-current-state
    puts it at <=-54 dB per pair -- and separation is a within-die property.

    The failure mode is a chord in which five shut strings each leak a copy of
    one open string, and copies of one source voltage-sum at +20 log(5) =
    +14 dB. So the arrangement to prefer minimises the *worst* string's
    exposure, not the average: 4 + 2 gives four strings three die-mates each,
    3 + 3 gives every string two.

    Leaves one spare channel per package. Page 5 offers two uses and this
    design takes neither: paralleling for 3 dB would make two strings quieter
    than the other four, which is a matching error introduced on purpose. They
    are grounded, per the same page, unless feature 12's compressor sidechain
    wants them.
    """
    per_package = CHANNELS // VCA_PACKAGES
    return {"packages": VCA_PACKAGES, "per_package": per_package,
            "die_mates": per_package - 1,
            "spare": VCA_PACKAGES * 4 - CHANNELS,
            "alternative_die_mates": 3}


# ---------------------------------------------------------------------------
# The DC servo, and constraint 3
# ---------------------------------------------------------------------------

# An integrator sensing the I-V converter's output and injecting correction
# current back into its summing node. ~1 Hz, per spec section 4.1.
#
# Why a servo and not a series capacitor. Constraint 3 says SIN{n} carries zero
# DC "by construction", and a capacitor is the more literal reading. It is also
# the wrong answer: SIN{n} faces R{n}01's 10k into a virtual earth, so a 1.6 Hz
# corner needs 10 uF, which is an electrolytic in the audio path -- and it puts
# a second high-pass within a decade of the mixer's own 15.9 Hz, which is
# exactly what DC_BLOCK_VALUE's comment warns produces "a phase response nobody
# predicted".
SERVO_R = "1M 1%"
SERVO_R_OHMS = 1_000_000.0
SERVO_C = "150n/50V X7R"
SERVO_C_FARADS = 150e-9
SERVO_RINJ = "1M 1%"
SERVO_RINJ_OHMS = 1_000_000.0

# Page 2, and it is the reason the servo is not optional: +/-150 nA typical
# output offset current with the input grounded. Through R_OUT that is a DC
# voltage at the I-V output whether or not any op-amp in the module has an
# offset at all.
VCA_OFFSET_CURRENT = 150e-9


def servo_residual():
    """What DC is left on SIN{n}, and what it costs at the far end.

    Three numbers, and the third is the one that decides whether constraint 3
    is met in the sense that matters.

    Uncorrected offset is the VCA's own output offset current through R_OUT,
    plus the I-V amplifier's. The loop nulls it, and what it cannot null is its
    own input offset: the integrator drives until its inverting input matches
    its non-inverting one, so the residual at the I-V output is
    MEASURED["servo_vos"] and very little else. A servo does not make DC small,
    it makes DC somebody else's offset.

    Then the consequence, computed through the mixer rather than asserted.
    Residual DC on SIN{n} drives R{n}01 into the summing node, so it appears at
    SUM_OUT multiplied by RF/RIN per channel and summed over six -- and lands
    on the master pot's wiper, which is the node the mixer chose DC_BLOCK =
    'cap' to protect. C703 blocks the wiper's DC path, leaving only R706's
    1 Mohm, so what actually flows through the track is volts/1M.

    The mixer already accepts 0.2 to 1.0 nA there from U1B's own offset. This
    has to land in the same neighbourhood, and it does.
    """
    corner = 1.0 / (2 * math.pi * SERVO_R_OHMS * SERVO_C_FARADS)
    # Loop gain at DC is the integrator's, attenuated by the injection ratio;
    # the audio-band high-pass this puts in the signal path sits where that
    # product falls to unity.
    injection = VCA_ROUT_OHMS / SERVO_RINJ_OHMS
    highpass = injection / (2 * math.pi * SERVO_R_OHMS * SERVO_C_FARADS)
    uncorrected = VCA_OFFSET_CURRENT * VCA_ROUT_OHMS
    residual = MEASURED["servo_vos"].value
    # Correction range: how much output offset the loop can pull out before the
    # integrator runs into its own rail.
    authority = MODULE_RAIL * injection
    # Through the mixer's own summer: each SIN{n} reaches SUM through R{n}01
    # and is multiplied by RF/RIN, then stage 2 inverts at unity. Read from the
    # contract rather than assumed to be one -- RF_TABLE exists because the
    # mixer's channel_peak measurement can still move it.
    summer_gain = socket.RF_OHMS / socket.RIN_OHMS
    at_sum_out = residual * CHANNELS * summer_gain
    wiper_amps = at_sum_out / socket.OUT_BLEED_OHMS   # R706, the mixer's bleed
    return {
        "corner": corner,
        "highpass": highpass,
        "uncorrected": uncorrected,
        "residual": residual,
        "authority": authority,
        "at_sum_out": at_sum_out,
        "wiper_amps": wiper_amps,
    }


# ---------------------------------------------------------------------------
# The CV chain -- ranked first of the three things that most affect the sound
# ---------------------------------------------------------------------------

# The reference, and 2.5 V is now a derived number rather than a preference.
#
# Spec section 4.2 names "MAX6126A25 with the 0.1 uF NR cap (35 nV/rtHz)" in
# one row and "source at 0-5 V" in the next, which are different parts. Two
# findings settle it.
#
# The 35 nV/rtHz belongs to the 2.048 V option. MAX6126 noise scales with
# output voltage: with the 0.1 uF NR capacitor fitted it is 35 nV/rtHz at
# 2.048 V, **45 at 2.5 V**, 80 at 4.096 V and 95 at 5.0 V.
#
# And the 5 V version cannot be driven. A 74AHC541 at Vcc = 5 V needs
# VIH = 0.7 Vcc = 3.5 V and an RP2040 GPIO delivers 3.3 V. The AHCT part whose
# threshold is a fixed TTL 2 V only runs at 4.5-5.5 V, so it forces the 5 V
# rail back. At 2.5 V the plain AHC is comfortable -- VIH ~1.75 V against a
# 3.3 V drive -- and its inputs are rated 0-5.5 V independent of Vcc, so
# over-driving is inside recommended operating conditions rather than tolerated.
#
# That is also the answer to open question 4 in 00-current-state.md, with a
# bound nobody had written down: **VREF <= 3.3/0.7 = 4.71 V, or the logic
# family has to change.**
VREF = 2.5
VREF_PART = "MAX6126A25"
VREF_NOISE = 45e-9                  # V/rtHz at 1 kHz, with C_NR fitted
VREF_NR_CAP = "100n/50V C0G"
VREF_MAX_FOR_AHC = 3.3 / 0.7

# The inverted reference, which spec section 4.2 does not have and the
# datasheet's Figure 10 requires.
#
# An inverting stage fed only from positive sources produces a negative output,
# so positive Vc -- attenuation -- is unreachable without a negative-referred
# offset current. Figure 10 draws it from the -12 V rail; page 11 note 3 says
# not to, because an unregulated rail's noise and drift inject straight into Vc
# and get multiplied by 3.488 per volt into AM. So it is the +2.5 V reference
# inverted through one unity stage, shared by all six channels.
#
# Unity, and with R_OFF = R1 the cancellation at the loud end is exact by
# construction rather than by trim -- see cv_filter().
VREF_INV_R = "10k 0.1%"
VREF_INV_R_OHMS = 10_000.0

# The logic buffer, powered from the reference. Vcc = VREF, which is what makes
# the PWM's high level a precision voltage instead of a rail.
LOGIC = "74AHC541"
LOGIC_PULLDOWN = "100k 1%"          # so a hi-Z MCU is a defined low: see below
PWM_BITS = 12
PWM_CARRIER = 30_500.0              # 12-bit at 125 MHz, spec section 4.2
FRAME_RATE = 8_000.0                # spec section 4.3

# The 2-pole multiple-feedback low-pass, and the block 00-current-state.md
# ranks first of three:
#
#   "A 2-pole 200-400 Hz low-pass on every CV, as an inverting MFB stage that
#    also injects the offset and buffers the DAC from the 2164's 10k divider.
#    ~15-20 dB."
#
# Topology, standard MFB (R1 in, R2 feedback, R3 to the virtual earth, C1 from
# the inner node to ground, C2 across R2):
#
#     gain  = -R2/R1
#     w0^2  = 1 / (R2 R3 C1 C2)
#     w0/Q  = (1/C1) (1/R1 + 1/R2 + 1/R3)
#
# Resistors <= 22k, from spec section 4.2, and that ceiling wants restating
# because the reason given for it does not survive. The spec says 22k "so their
# Johnson noise (19 nV/rtHz) stays ~13 dB under the source" -- and 19 nV/rtHz
# is right, thermal(22k) is 19.1 -- but 13 dB under the source assumed a 5 V
# reference at 95 nV/rtHz. Against the 2.5 V part's 45 it is 7.5 dB, and
# against the filter's *total* it is less than that. The ceiling is kept
# anyway, and control_noise() is where the conclusion is re-established on
# different grounds: what matters is AM noise against the additive floor, and
# there the margin is 24 dB.
CV_R1 = "22k 1%"                    # from the '541
CV_R1_OHMS = 22_000.0
CV_R2 = "17k8 1%"                   # feedback: sets the gain and the span
CV_R2_OHMS = 17_800.0
CV_R3 = "17k8 1%"                   # inner node to the virtual earth
CV_R3_OHMS = 17_800.0
CV_C1 = "56n/50V X7R"
CV_C1_FARADS = 56e-9
CV_C2 = "22n/50V X7R"
CV_C2_FARADS = 22e-9

# The offset injection resistor, and it equals R1 for a reason worth stating.
#
# Vc must be 0 at the loud end, where the '541 is sitting at VREF. With an
# inverted reference of the same magnitude, exact cancellation needs the two
# input resistors equal -- so R_OFF = R1 is not a chosen value, it is the
# condition. Everything then falls out as Vc = (R2/R1) x VREF x D, which is the
# result cv_filter() is really about.
CV_ROFF = "22k 1%"
CV_ROFF_OHMS = 22_000.0


def cv_filter():
    """The CV filter, its span, and the two properties that come free.

    The corner and Q are what the standard values actually produce, not what
    was aimed at: 250 Hz and Bessel Q = 0.577 were the targets, and E96
    resistors with 56n/22n land at 255 Hz and Q = 0.568. Bessel rather than
    Butterworth because this filter doubles as the de-click and a control
    signal wants minimal overshoot, not maximal flatness.

    **The transfer function collapses to Vc = (R2/R1) x VREF x D.**

    With R_OFF = R1 and the offset taken from an inverted copy of the same
    reference that powers the '541, and with the firmware emitting the
    complement (1 - D) so that code 0 is loudest:

        Vsrc = (1 - D) x VREF
        Vc   = -(R2/R1) Vsrc - (R2/R_OFF)(-VREF)
             =  (R2/R1) VREF [ 1 - (1 - D) ]
             =  (R2/R1) VREF D

    Two things follow and neither is in the spec.

    **Reference noise is multiplied by D.** It appears in both input paths with
    opposite signs and cancels to the extent the duty cycle is small -- so at
    the loud end, where AM would be audible, the reference contributes nothing,
    and at the shut end, where it contributes fully, the channel is silent.
    Spec section 4.2's cryptic "code-near-zero is both loudest and quietest"
    turns out to have a mechanism. See control_noise().

    **The CV chain is fail-silent by construction.** D = 0 at the '541 output
    -- PWM idling low, a hi-Z MCU into the pull-downs, or the '541's own
    outputs disabled -- leaves only the offset current, so Vc goes to full
    attenuation. Spec section 4.5 warns that "PWM outputs idling low" is
    fail-loud, and that is true of a direct drive and false of this one. The
    hazard it asks for an explicit hardware answer to is answered by the
    topology.
    """
    gain = CV_R2_OHMS / CV_R1_OHMS
    w0 = 1.0 / math.sqrt(CV_R2_OHMS * CV_R3_OHMS * CV_C1_FARADS * CV_C2_FARADS)
    w0_over_q = (1.0 / CV_C1_FARADS) * (1.0 / CV_R1_OHMS + 1.0 / CV_R2_OHMS
                                        + 1.0 / CV_R3_OHMS)
    span = gain * VREF
    return {
        "gain": gain,
        "f0": w0 / (2 * math.pi),
        "q": w0 / w0_over_q,
        "span": span,
        "depth_db": abs(span / GAIN_CONSTANT),
        "step_db": abs(span / GAIN_CONSTANT) / (2 ** PWM_BITS - 1),
        "exact_cancellation": CV_ROFF_OHMS == CV_R1_OHMS,
    }


def pwm_ripple():
    """Carrier residue at the control port, and what it is worth in dB of gain.

    The PWM fundamental is worst at 50 % duty, where a square wave of amplitude
    VREF has a fundamental of 2 VREF / pi. Two poles at f0 attenuate it by
    (f/f0)^2, then the filter's own gain scales it.

    Spec section 4.2 claims 128 uV and 0.0039 dB. This comes out lower, and the
    difference is that the spec's figure appears to assume a single pole's worth
    of the second one or a different duty; the arithmetic is here so the two can
    be compared rather than reconciled by assertion.
    """
    filt = cv_filter()
    fundamental = 2 * VREF / math.pi
    attenuation = (PWM_CARRIER / filt["f0"]) ** 2
    at_port = fundamental / attenuation * filt["gain"]
    gain_error = am_sensitivity() * at_port
    return {
        "fundamental": fundamental,
        "attenuation_db": 20 * math.log10(attenuation),
        "at_port": at_port,
        "gain_error": gain_error,
        "gain_error_db": 8.685889638 * gain_error,
    }


def control_noise(duty=1.0):
    """Everything that lands on Vc, at a given duty cycle, V/rtHz.

    `duty` is D: 0 is loudest and 1 is full attenuation, which is the polarity
    this design uses. It is a parameter because the reference term scales with
    it -- see cv_filter() -- and that is the single most useful thing about the
    topology.

    Four contributors:

    * the reference, through both input paths, coefficient (R2/R1) x D;
    * the inverting stage that makes the negative reference, whose own added
      noise does *not* cancel and is therefore the floor at D = 0;
    * the filter's four resistors, each amplified by R2 over its own value;
    * the filter amplifier's voltage noise times the stage's noise gain.
    """
    gain = CV_R2_OHMS / CV_R1_OHMS

    reference = VREF_NOISE * gain * duty

    inverter_own = math.hypot(
        math.hypot(thermal(VREF_INV_R_OHMS), thermal(VREF_INV_R_OHMS)),
        OPAMP_EN * 2)
    inverter = inverter_own * gain

    resistors = math.sqrt(
        (thermal(CV_R1_OHMS) * CV_R2_OHMS / CV_R1_OHMS) ** 2
        + (thermal(CV_ROFF_OHMS) * CV_R2_OHMS / CV_ROFF_OHMS) ** 2
        + (thermal(CV_R3_OHMS) * CV_R2_OHMS / CV_R3_OHMS) ** 2
        + thermal(CV_R2_OHMS) ** 2)

    shunt = 1.0 / (1.0 / CV_R1_OHMS + 1.0 / CV_ROFF_OHMS + 1.0 / CV_R3_OHMS)
    noise_gain = 1 + CV_R2_OHMS / shunt
    amplifier = OPAMP_EN * noise_gain

    total = math.sqrt(reference ** 2 + inverter ** 2
                      + resistors ** 2 + amplifier ** 2)
    return {
        "duty": duty,
        "reference": reference,
        "inverter": inverter,
        "resistors": resistors,
        "amplifier": amplifier,
        "noise_gain": noise_gain,
        "total": total,
    }


def am_noise(duty=1.0):
    """Control noise as multiplicative AM, and how far under the signal it is.

    The mechanism 00-current-state.md identifies as dominant: control noise is
    multiplied into the audio at am_sensitivity() per volt, so it breathes with
    the signal instead of sitting under it.

    Referred to the additive floor the box already has, which is the comparison
    that decides whether the <=22k filter resistors are good enough. The
    signal is one string at the mixer's own assumed channel peak; the additive
    floor is its noise_floor assumption. Both come through contract/socket.py.
    """
    control = control_noise(duty)["total"]
    fractional = am_sensitivity() * control * math.sqrt(BANDWIDTH)
    signal_rms = socket.MEASURED["channel_peak"].value / math.sqrt(2)
    additive = socket.NOISE_FLOOR.value
    return {
        "fractional": fractional,
        "db_rms": 8.685889638 * fractional,
        "below_signal": -20 * math.log10(fractional),
        "additive_below_signal": 20 * math.log10(signal_rms / additive),
        "margin": -20 * math.log10(fractional)
                  - 20 * math.log10(signal_rms / additive),
    }


def fail_states():
    """Where Vc goes when something breaks, and the one case that is loud.

    The table spec section 4.5 asks for, computed from cv_filter() rather than
    asserted. Every row but the last is silent because the only current left at
    the summing node is the offset, and the offset comes from neither the MCU
    nor the reference that feeds the '541.

    The last row is the single fail-loud path in the CV chain and it is
    recorded here rather than fixed: the mitigation belongs with the shared
    fail-safe blocks, and the bypass relay's AC-coupled charge pump covers it
    at the audio level in the meantime.
    """
    filt = cv_filter()
    full = filt["span"]
    rows = [
        ("PWM idling low, D = 0 at the '541", full),
        ("MCU hi-Z, inputs held by pull-downs", full),
        ("'541 outputs disabled (OE high)", full),
        ("reference dead, VREF = 0 at the '541 only", full),
    ]
    # If the inverted reference fails positive, the offset current reverses and
    # drives Vc negative, which is gain rather than attenuation.
    loud = -(filt["gain"] / CV_ROFF_OHMS * CV_R1_OHMS) * MODULE_RAIL
    rows.append(("inverted reference fails to +rail", loud))
    return [{"state": s, "vc": v,
             "db": max(min(control_law(v), GAIN_MAX_DB), GAIN_MIN_DB)}
            for s, v in rows]


# ---------------------------------------------------------------------------
# Pin maps -- read, not asserted
# ---------------------------------------------------------------------------
# Named rather than numbered at every connect site, which is the mixer's own
# hard-won convention. Its DIODE_PINS comment says why: D801 was wired
# cathode-to-the-inlet for the whole life of that design, and "a pin number can
# be transposed silently; 'A' and 'K' cannot". Every map below was read off the
# datasheet's own pin-configuration table in this session.

# SSI2164, 16-lead SOP, datasheet page 1. Four channels; x is 1-4.
VCA_PINS = {"MODE": 1, "GND": 8, "V-": 9, "V+": 16}
VCA_CHANNEL_PINS = {
    1: {"IIN": 2, "VC": 3, "IOUT": 4},
    2: {"IIN": 7, "VC": 6, "IOUT": 5},
    3: {"IIN": 10, "VC": 11, "IOUT": 12},
    4: {"IIN": 15, "VC": 14, "IOUT": 13},
}

# OPA1644, 14-pin SOIC/TSSOP, SBOS484D page 5. (out, -in, +in) per section.
OPAMP_PINS = {"V+": 4, "V-": 11}
OPAMP_UNITS = {"A": (1, 2, 3), "B": (7, 6, 5), "C": (8, 9, 10),
               "D": (14, 13, 12)}

# SN74AHC541, 20-pin, SCLS261Q page 3. A_n is pin n+1 and Y_n is pin 19-n, so
# the channel order reverses across the package -- worth knowing before the
# layout, because A1 and Y1 are diagonally opposite corners while A8 and Y8 are
# adjacent. TI put inputs and outputs on opposite sides deliberately ("to
# facilitate printed circuit board layout"), which is what lets this part
# straddle the analogue/digital boundary with the digital side on one row.
LOGIC_PINS = {"OE1": 1, "GND": 10, "OE2": 19, "VCC": 20}
LOGIC_A = {n: n + 1 for n in range(1, 9)}
LOGIC_Y = {n: 19 - n for n in range(1, 9)}

# The pad relay. **The part is still not chosen and the pins now are**, and the
# distinction is the whole of this comment.
#
# These are IEC 60947 contact numbers, which is a standard rather than a part:
# tens are the pole and units are the function, so 11/12/14 is pole 1 as
# common / normally-closed / normally-open, 21/22/24 is pole 2, and A1-A2 and
# B1-B2 are the set and reset coils of a two-coil latching relay. KiCad's
# generic Relay_DPDT_Latching_2coil carries exactly this and nothing
# part-specific, which is what makes it safe to draw with.
#
# So what is committed to here is not a relay but a *constraint on which relay
# may be fitted*: it has to follow IEC contact numbering. Plenty of signal
# relays do and plenty do not -- Panasonic's TQ2 numbers its pins sequentially
# round the package -- so this is a real filter on that BOM line rather than
# paperwork, and ASSUMPTIONS.md records it as one.
RELAY_PINS = {"SET+": "A1", "SET-": "A2", "RESET+": "B1", "RESET-": "B2",
              "COM_A": "11", "NC_A": "12", "NO_A": "14",
              "COM_B": "21", "NC_B": "22", "NO_B": "24"}

# MAX6126, 8-pin SO. Read from a text mirror of the datasheet rather than from
# Analog Devices' own PDF, which timed out repeatedly -- the same provenance as
# its noise figures, and recorded as such in ASSUMPTIONS.md.
#
# **It is a Kelvin-sensed part, which is not how spec section 4.2 assumes it is
# wired.** OUTF *forces* and OUTS *senses*, and the datasheet says to "short
# OUTF to OUTS as close to the load as possible"; GNDS is the matching ground
# sense, "connect to ground connection at load". That is four connections where
# the spec implies two, and it decides where the reference sits relative to the
# '541 -- the sense pair has to close at the load, which is C804, not at the
# package.
#
# Pins 5 and 8 are internally connected and the datasheet says to connect
# nothing to them.
REF_PINS = {"NR": 1, "IN": 2, "GND": 3, "GNDS": 4,
            "IC1": 5, "OUTS": 6, "OUTF": 7, "IC2": 8}


# ---------------------------------------------------------------------------
# Footprints and order codes
# ---------------------------------------------------------------------------

# lib_id -> (nickname, stock library, symbol, rename), the mixer's LIBS shape.
#
# Three parts are borrowed and the third is the interesting one. TL074 is a
# 14-pin quad whose numbering is identical to the OPA1644's -- checked pin by
# pin against SBOS484D -- so it stands in and is renamed, exactly as the mixer
# borrows OPA1612AxD under its catalogue name. Relay_DPDT_Latching_2coil is
# generic by construction and that is the point: it carries IEC contact
# numbering and nothing part-specific.
#
# The MAX6126 has no stock symbol at all. ADR4525 -- which spec section 4.2
# names as this design's own second source -- is an 8-pin SOIC reference whose
# IN and OUT already fall on pins 2 and 6, so it is borrowed and repinned to
# REF_PINS. Same move as the mixer's ICL7660 -> ICL7660S, with more pins.
LIBS = {
    "Device:R": ("Device", "Device", "R", None),
    "Device:C": ("Device", "Device", "C", None),
    "Connector_Generic:Conn_01x02": ("Connector_Generic", "Connector_Generic",
                                     "Conn_01x02", None),
    "Connector_Generic:Conn_01x03": ("Connector_Generic", "Connector_Generic",
                                     "Conn_01x03", None),
    "Connector_Generic:Conn_01x05": ("Connector_Generic", "Connector_Generic",
                                     "Conn_01x05", None),
    "Connector:TestPoint": ("Connector", "Connector", "TestPoint", None),
    "cv:OPA1644": ("cv", "Amplifier_Operational", "TL074", "OPA1644"),
    "cv:SSI2164": ("cv", "Audio", "SSI2164", None),
    "cv:74AHC541": ("cv", "74xx", "74AHC541", None),
    "cv:MAX6126": ("cv", "Reference_Voltage", "ADR4525", "MAX6126"),
    "cv:Relay": ("cv", "Relay", "Relay_DPDT_Latching_2coil", "Relay"),
    "power:GNDA": ("power", "power", "GNDA", None),
    "power:GNDD": ("power", "power", "GNDD", None),
    "power:PWR_FLAG": ("power", "power", "PWR_FLAG", None),
}

# Which unit of the quad carries the supply pins. TL074 puts the four
# amplifiers on units 1-4 and V+/V- alone on unit 5.
OPAMP_POWER_UNIT = 5

R_FP = "Resistor_SMD:R_0805_2012Metric"
C_FP = "Capacitor_SMD:C_0805_2012Metric"
C_FILM_FP = "Capacitor_SMD:C_1210_3225Metric"
SOIC8_FP = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
SOIC14_FP = "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm"
SOP16_FP = "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"
SOIC20_FP = "Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm"
LOOM_FP = socket.CHANNEL_POT_FP          # the mixer's own 1x03, mirrored
PAD_FP = "TestPoint:TestPoint_Pad_D2.0mm"

# Every value string that names a buyable part. The relay, the reference, the
# DC-DC, the MCU and the ADC are deliberately absent and are declared in
# UNSPECIFIED below, so check_orderable() can tell "not yet chosen" from
# "forgotten".
ORDER_CODES = {
    "10k 0.1%":       "ERA6AEB103V",
    "12k1 0.1%":      "ERA6AEB1212V",
    "24k3 0.1%":      "ERA6AEB2432V",
    "48k7 0.1%":      "ERA6AEB4872V",
    "97k6 0.1%":      "ERA6AEB9762V",
    "22k 1%":         "RC0805FR-0722KL",
    "17k8 1%":        "RC0805FR-0717K8L",
    "220R 1%":        "RC0805FR-07220RL",
    "1M 1%":          "RC0805FR-071ML",
    "100k 1%":        "RC0805FR-07100KL",
    "0R":             "RC0805JR-070RL",
    "100p/50V C0G":   "GRM2165C1H101JA01D",
    "1200p/50V C0G":  "GRM2165C1H122JA01D",
    "22n/50V X7R":    "GRM216R71H223KA01D",
    "56n/50V X7R":    "GRM216R71H563KA01D",
    "150n/50V X7R":   "GRM216R71H154KA01D",
    "100n/50V X7R":   "GRM216R71H104KA01D",
    "100n/50V C0G":   "GRM2195C1H104JA01D",
    "10u/16V X7R":    "GRM21BR61C106KE15L",
    OPAMP:            "OPA1644AIDR",
    VCA:              "SSI2164S-RT",
    LOGIC:            "SN74AHC541DWR",
    # 8-pin SO, A grade, 2.5 V. The "+" suffix is the lead-free marker in
    # Maxim's scheme and is part of the order code, not decoration.
    VREF_PART:        "MAX6126AASA25+",
}

# Parts and blocks this pass does not place, each with the reason. Declared so
# that "deferred" and "missed" are different states a check can distinguish --
# the same argument design.NO_CONNECT makes upstream about floating pins.
UNSPECIFIED = {
    PAD_RELAY: "dual-coil latching DPDT: not named in the spec (section 4.5 "
               "names the driver and the one-shot only), and section 6 says "
               "not to invent one. Its *pins* are now known -- see RELAY_PINS "
               "-- because IEC 60947 contact numbering is a standard and not "
               "a part. What the schematic commits to is that whatever relay "
               "is fitted follows it.",
}

# Pins deliberately left unconnected, declared beside the circuit rather than
# buried in the checker -- the mixer's NO_CONNECT, same argument.
REF_REF = "U12"
NO_CONNECT = tuple(
    (REF_REF, str(REF_PINS[name])) for name in ("IC1", "IC2")
) + tuple(
    # K{n}01 selects a branch and needs one pole; its second is spare. Declared
    # rather than left floating, the same argument design.NO_CONNECT makes
    # upstream about the stacking jacks' switch contacts.
    (f"K{n}01", RELAY_PINS[role])
    for n in range(1, CHANNELS + 1)
    for role in ("COM_B", "NC_B", "NO_B")
)
DEFERRED = {
    "envelope rectifier": "the smoothing time constant is not derivable -- "
                          "spec section 4.4 gives a sampling rate and no "
                          "attack/release target. The tap net BUF{n} exists "
                          "and is driven; the rectifier hangs off it.",
    "controller": "RP2040 and its QSPI flash, crystal, USB and MIDI: shared "
                  "block, and the scope statement puts shared blocks after "
                  "one channel is complete.",
    "envelope ADC": "ADS131M08 or MCP3564, undecided in spec section 4.4.",
    "relay drive": "2 x TPIC6B595 plus the 74LVC1G123 one-shot, section 4.5.",
    "bypass relay and fail-safe": "the AC-coupled charge pump, section 4.5.",
    "supply": "isolated DC-DC at >=300 kHz per section 1.1; the topology is "
              "decided and the part is not.",
}


# ---------------------------------------------------------------------------
# Netlist
# ---------------------------------------------------------------------------
# The mixer's Part/Design shape without its two-board machinery: this is one
# PCB plus a loom. Its check() runs this module's own invariants; verify.py
# reads the emitted netlist back and checks section 5 against it, which is the
# same relationship design.py and verify.py have upstream.

class Part:
    def __init__(self, ref, value, footprint, description="", units=1,
                 mpn="", in_bom=True):
        self.ref = ref
        self.value = value
        self.footprint = footprint
        self.description = description
        self.units = units
        self.mpn = mpn or ORDER_CODES.get(value, "")
        self.in_bom = in_bom


class Design:
    def __init__(self):
        self.parts = {}
        self.nets = {}

    def add(self, part):
        assert part.ref not in self.parts, f"duplicate reference {part.ref}"
        self.parts[part.ref] = part
        return part

    def connect(self, net, *pins):
        entries = self.nets.setdefault(net, [])
        for ref, pin in pins:
            assert ref in self.parts, f"{net}: unknown part {ref}"
            entry = (ref, str(pin))
            assert entry not in entries, f"{net}: {ref}.{pin} attached twice"
            entries.append(entry)

    def pin_owner(self):
        owner = {}
        for net, entries in self.nets.items():
            for entry in entries:
                assert entry not in owner, (
                    f"{entry} on both {owner[entry]} and {net}")
                owner[entry] = net
        return owner

    def nets_of(self, ref):
        return {net for net, entries in self.nets.items()
                for r, _ in entries if r == ref}

    def check(self):
        self.pin_owner()
        for net, entries in self.nets.items():
            assert len(entries) >= 2, f"net {net} has only {entries}"
        self.check_net_potentials()
        self.check_pin_numbers()
        self.check_orderable()

    def check_net_potentials(self):
        """Every net declares what DC potential it sits at.

        Inherited wholesale from the mixer's NET_DC, and for its stated reason:
        "a new net is a question -- what potential does this sit at? -- and a
        design that cannot answer it does not build."

        It earns its keep twice here. Constraint 3 is a claim about DC on
        SIN{n}, so a table of DC potentials is the thing that expresses it; and
        the CV domain has nets at +2.5, -2.5 and 0 which is exactly where a
        capacitor gets fitted backwards.
        """
        undeclared = sorted(set(self.nets) - set(NET_DC))
        if undeclared:
            raise AssertionError(
                f"{', '.join(undeclared)} have no entry in NET_DC -- say what "
                f"potential the net sits at before hanging a part off it")

    def check_pin_numbers(self):
        """No part may reach the netlist with an unresolved pin number.

        RELAY_PINS is all None because the relay is not chosen. That is a
        legitimate state for a design to be in and it is not a legitimate state
        for a *board* to be in, so the two are separated here rather than
        conflated: a pin written as a role -- `<COM_A>` -- is allowed only on a
        part that UNSPECIFIED names and explains, and is an error anywhere
        else.

        The failure this stops is the one section 6 of the spec is about. A
        plausible pin number on an unchosen relay looks exactly like a read one,
        and every check downstream would agree with it. Roles cannot be
        mistaken for readings.
        """
        strays = sorted(
            f"{ref}.{pin}" for (ref, pin) in self.pin_owner()
            if pin.startswith("<")
            and self.parts[ref].value not in UNSPECIFIED)
        if strays:
            raise AssertionError(
                f"pin roles on parts that are not declared unspecified: "
                f"{strays} -- read the datasheet or add the part to "
                f"UNSPECIFIED with a reason")

    def unresolved_pins(self):
        """Every pin still written as a role, by part. Reported, not raised."""
        out = {}
        for ref, pin in sorted(self.pin_owner()):
            if pin.startswith("<"):
                out.setdefault(ref, []).append(pin.strip("<>"))
        return out

    def check_orderable(self):
        """Every part on the BOM names a buyable part, or is declared unbuyable.

        The mixer's own check, and its argument transfers unchanged: "an
        assembly house substitutes on value". What is added here is the second
        state -- a part that is deliberately not chosen yet -- because this repo
        is a spike and the mixer was going out for assembly.
        """
        missing = sorted(
            ref for ref, part in self.parts.items()
            if part.in_bom and not part.mpn
            and part.value not in UNSPECIFIED)
        if missing:
            raise AssertionError(
                f"no manufacturer's part number for {missing} -- ORDER_CODES "
                f"is where the answer goes, UNSPECIFIED is where 'not chosen "
                f"yet' goes")


def _resistor(design, ref, value, net_a, net_b, description=""):
    design.add(Part(ref, value, R_FP, description=description))
    design.connect(net_a, (ref, 1))
    design.connect(net_b, (ref, 2))


def _capacitor(design, ref, value, net_a, net_b, description="",
               footprint=C_FP):
    design.add(Part(ref, value, footprint, description=description))
    design.connect(net_a, (ref, 1))
    design.connect(net_b, (ref, 2))


# Which op-amp section does which job. Eight quads, and the grouping is by
# *block* rather than by channel, for two reasons: the CV filter's input is a
# 30.5 kHz square wave and has no business sharing a die with an audio front
# end, and putting all six of one kind together is what lets the floorplan keep
# the analogue rows straight. U8's spare section takes the reference inverter.
#
# Provisional: this is the one table in the file that the floorplan may move.
SECTIONS = {}
for _n in range(1, CHANNELS + 1):
    SECTIONS[("front", _n)] = (f"U{1 + (_n - 1) // 4}", "ABCD"[(_n - 1) % 4])
    SECTIONS[("iv", _n)] = (f"U{3 + (_n - 1) // 4}", "ABCD"[(_n - 1) % 4])
    SECTIONS[("servo", _n)] = (f"U{5 + (_n - 1) // 4}", "ABCD"[(_n - 1) % 4])
    SECTIONS[("cv", _n)] = (f"U{7 + (_n - 1) // 4}", "ABCD"[(_n - 1) % 4])
SECTIONS[("refinv", 0)] = ("U8", "C")
OPAMP_PACKAGES = sorted({pkg for pkg, _ in SECTIONS.values()},
                        key=lambda r: int(r[1:]))

# Which SSI2164 and which of its four cells carries channel n. 3 + 3, per
# allocation(): every string gets two die-mates instead of one string getting
# three and another getting one.
VCA_PACKAGES_REFS = ("U9", "U10")
VCA_CELL = {n: (VCA_PACKAGES_REFS[(n - 1) // 3], ((n - 1) % 3) + 1)
            for n in range(1, CHANNELS + 1)}
VCA_SPARE_CELLS = {ref: 4 for ref in VCA_PACKAGES_REFS}

LOGIC_REF = "U11"


# Every net, and what DC it sits at. Single numbers where a net has one,
# (low, high) where it swings -- the mixer's convention, and net_dc() below
# reads either.
#
# The audio nets are 0 V by construction and that is the whole of constraint 3
# stated as data: SIN{n} appears here as 0.0 and check_sin_dc() in verify.py is
# what holds it.
RAILS = {"VA+": MODULE_RAIL, "VA-": -MODULE_RAIL, "V5": 5.0, "V3V3": 3.3}
NET_DC = {
    "MAGND": 0.0, "MDGND": 0.0, socket.AGND: 0.0,
    "VREF": VREF, "VREFN": -VREF,
    "OE": (0.0, 3.3),
    **RAILS,
}
for _n in range(1, CHANNELS + 1):
    NET_DC.update({
        f"PIN{_n}": 0.0, f"SIN{_n}": 0.0,
        f"FEN{_n}": 0.0, f"BUF{_n}": 0.0,
        f"PADI{_n}": 0.0, f"IIN{_n}": 0.0, f"RCJ{_n}": 0.0,
        f"IOUT{_n}": 0.0, f"SVN{_n}": 0.0, f"SRV{_n}": (-MODULE_RAIL,
                                                        MODULE_RAIL),
        f"CVX{_n}": (0.0, VREF), f"CVN{_n}": 0.0,
        f"VC{_n}": (0.0, VREF), f"LOGO{_n}": (0.0, VREF),
        f"PWM{_n}": (0.0, 3.3),
    })
    NET_DC.update({f"PS{_n}{letter}": 0.0 for letter in "ABCD"})
    # The two selector nodes between the relays. Audio, and DC-free because
    # C{n}01 is upstream of the whole pad.
    NET_DC.update({f"PSEL{_n}X": 0.0, f"PSEL{_n}Y": 0.0})

# The reference inverter's virtual earth, held at MAGND by feedback.
NET_DC["RINV"] = 0.0
# The reference's noise-reduction pin. Declared as a range rather than a number
# because the MAX6126's pin map has not been read in this session -- see
# UNSPECIFIED -- so what this node actually sits at is not known here. It is
# bounded by the rails it lives between, which is enough for the polarity and
# rating checks and is not enough to call it settled.
NET_DC["VNR"] = (0.0, VREF)


def net_dc(net):
    volts = NET_DC[net]
    return volts if isinstance(volts, tuple) else (volts, volts)


# The loom, declared rather than drawn, because a shield is not a netlist
# object and constraint 5 is a claim about one.
#
# A twisted pair per channel inside an individual shield, the shield landing on
# that channel's own socket pin 3 at the main-board end and cut back here. So
# six shields reach six pin-3s and none of them is commoned in the module --
# which is the part of constraint 2 that survives its own arithmetic, and the
# part that has a mechanism: per-channel electrostatic separation in a loom
# running past a 45 kHz charge pump.
#
# verify.py asserts that every conductor leaving this module appears in exactly
# one pair and that every shield lands at exactly one end.
LOOM = {
    n: {"conductors": (f"PIN{n}", f"SIN{n}"),
        "socket_pins": (socket.PIN_TOP, socket.PIN_WIPER),
        "shield_pin": socket.PIN_RETURN,
        "shield_ground": "main-board",
        "module_end": "floating"}
    for n in range(1, CHANNELS + 1)
}

# The single bond, and where it lands. TP6 is the mixer's own AGND test pad and
# its comment calls it "the *only* correct one, given the ground rule" -- so it
# is the mixer's designated AGND reference point, which is exactly what a
# ground bond wants. The six shields terminate at the same node.
#
# Its coordinates are not in fab/mechanical-summing-mixer.json (test pads are
# not tall parts) and have to be read off the board before the loom is made.
# See ASSUMPTIONS.md.
BOND_TO = "TP6"
GROUND_STAR = "R901"          # MAGND <-> AGND, the one bridge
DOMAIN_STAR = "R902"          # MAGND <-> MDGND, inside the module


def channel(design, n):
    """One channel, end to end. Six of these and the shared blocks are the board.

    The order is the signal: socket, difference amplifier, coupling, pad, VCA,
    I-V, servo, back to the socket. The CV filter is built alongside because it
    lands on the same VCA cell.
    """
    package, unit = SECTIONS[("front", n)]
    out, inverting, non_inverting = OPAMP_UNITS[unit]

    # The loom connector. Three ways, mirroring the mixer's own RV{n}01 order
    # so a builder reads the same 1/2/3 at both ends. Pin 3 is RET{n} and not
    # ground: see FRONT_R.
    design.add(Part(f"J{n}", f"CH{n}", socket.CONN_FP[2], in_bom=True,
                    mpn=socket.CONN_MPN[2],
                    description=(
                        f"Shielded twisted pair to mixer RV{n}01: "
                        f"1=PIN{n} (socket pin {socket.PIN_TOP}), "
                        f"2=SIN{n} (socket pin {socket.PIN_WIPER}); "
                        f"shield to socket pin {socket.PIN_RETURN} at the "
                        f"main-board end only, cut back here")))
    design.connect(f"PIN{n}", (f"J{n}", 1))
    design.connect(f"SIN{n}", (f"J{n}", 2))

    # Two matched 10k. R{n}01 is the socket contract and R{n}02 sets unity.
    _resistor(design, f"R{n}01", FRONT_R, f"PIN{n}", f"FEN{n}",
              description=f"Channel {n} socket load -- constraint 4")
    _resistor(design, f"R{n}02", FRONT_R, f"FEN{n}", f"BUF{n}",
              description=f"Channel {n} front-end feedback")
    design.connect(f"BUF{n}", (package, out))
    design.connect(f"FEN{n}", (package, inverting))
    design.connect("MAGND", (package, non_inverting))

    # Input coupling into the VCA, datasheet page 4, "recommended for improved
    # control feedthrough". Its corner moves with the pad step -- 1.3 Hz at
    # 12k1 down to 0.16 Hz at 97k6 -- and both are far below anything audible.
    _capacitor(design, f"C{n}01", VCA_INPUT_BLOCK, f"BUF{n}", f"PADI{n}",
               footprint=C_FILM_FP,
               description=f"Channel {n} VCA input block -- control feedthrough")

    # The coarse pad: four input resistors and a 2-bit relay selector.
    for index, (letter, ohms) in enumerate(zip("ABCD", VCA_RIN_STEPS)):
        value = {12_100.0: "12k1 0.1%", 24_300.0: "24k3 0.1%",
                 48_700.0: "48k7 0.1%", 97_600.0: "97k6 0.1%"}[ohms]
        _resistor(design, f"R{n}1{index + 1}", value,
                  f"PADI{n}", f"PS{n}{letter}",
                  description=f"Channel {n} R_IN, "
                              f"{PAD_STEPS_DB[index]:+.0f} dB step")

    # Two dual-coil latching DPDT relays as a binary 4:1 selector. K{n}01
    # chooses the branch and K{n}02 chooses within it, so two bits address four
    # resistors and no state can connect two at once.
    for index in (1, 2):
        design.add(Part(f"K{n}0{index}", PAD_RELAY, None, units=1,
                        description=(
                            f"Channel {n} pad bit {index - 1}, dual-coil "
                            f"latching DPDT; contacts carry <=102 uA")))
    design.connect(f"IIN{n}", (f"K{n}01", RELAY_PINS["COM_A"]))
    design.connect(f"PSEL{n}X", (f"K{n}01", RELAY_PINS["NC_A"]), (f"K{n}02", RELAY_PINS["COM_A"]))
    design.connect(f"PSEL{n}Y", (f"K{n}01", RELAY_PINS["NO_A"]), (f"K{n}02", RELAY_PINS["COM_B"]))
    design.connect(f"PS{n}A", (f"K{n}02", RELAY_PINS["NC_A"]))
    design.connect(f"PS{n}B", (f"K{n}02", RELAY_PINS["NO_A"]))
    design.connect(f"PS{n}C", (f"K{n}02", RELAY_PINS["NC_B"]))
    design.connect(f"PS{n}D", (f"K{n}02", RELAY_PINS["NO_B"]))

    # The stability network, datasheet page 3 Figure 1. Not optional and not in
    # the spec.
    _resistor(design, f"R{n}15", "220R 1%", f"IIN{n}", f"RCJ{n}",
              description=f"Channel {n} VCA input RC -- stability")
    _capacitor(design, f"C{n}02", "1200p/50V C0G", f"RCJ{n}", "MAGND",
               description=f"Channel {n} VCA input RC -- stability")

    # The gain cell.
    vca_ref, cell = VCA_CELL[n]
    pins = VCA_CHANNEL_PINS[cell]
    design.connect(f"IIN{n}", (vca_ref, pins["IIN"]))
    design.connect(f"IOUT{n}", (vca_ref, pins["IOUT"]))
    design.connect(f"VC{n}", (vca_ref, pins["VC"]))

    # I-V, holding IOUT at virtual earth. Its output *is* SIN{n}.
    package, unit = SECTIONS[("iv", n)]
    out, inverting, non_inverting = OPAMP_UNITS[unit]
    _resistor(design, f"R{n}21", VCA_ROUT, f"IOUT{n}", f"SIN{n}",
              description=f"Channel {n} I-V -- unity at the 0 dB pad step")
    _capacitor(design, f"C{n}21", IV_CF, f"IOUT{n}", f"SIN{n}",
               description=f"Channel {n} I-V compensation")
    design.connect(f"SIN{n}", (package, out))
    design.connect(f"IOUT{n}", (package, inverting))
    design.connect("MAGND", (package, non_inverting))

    # The DC servo, sensing SIN{n} and injecting into IOUT{n}.
    package, unit = SECTIONS[("servo", n)]
    out, inverting, non_inverting = OPAMP_UNITS[unit]
    _resistor(design, f"R{n}31", SERVO_R, f"SIN{n}", f"SVN{n}",
              description=f"Channel {n} servo sense")
    _capacitor(design, f"C{n}31", SERVO_C, f"SVN{n}", f"SRV{n}",
               description=f"Channel {n} servo integrator")
    _resistor(design, f"R{n}32", SERVO_RINJ, f"SRV{n}", f"IOUT{n}",
              description=f"Channel {n} servo injection")
    design.connect(f"SRV{n}", (package, out))
    design.connect(f"SVN{n}", (package, inverting))
    design.connect("MAGND", (package, non_inverting))

    # The CV filter: 2-pole MFB with the offset summed at the inner node, which
    # is the datasheet's Figure 10 arrangement. R{n}44 from VREFN is what makes
    # positive Vc reachable at all, and R{n}44 == R{n}41 is the cancellation
    # condition rather than a chosen value.
    package, unit = SECTIONS[("cv", n)]
    out, inverting, non_inverting = OPAMP_UNITS[unit]
    _resistor(design, f"R{n}41", CV_R1, f"LOGO{n}", f"CVX{n}",
              description=f"Channel {n} CV input")
    _resistor(design, f"R{n}42", CV_R2, f"CVX{n}", f"VC{n}",
              description=f"Channel {n} CV feedback -- sets the span")
    _resistor(design, f"R{n}43", CV_R3, f"CVX{n}", f"CVN{n}",
              description=f"Channel {n} CV inner")
    _resistor(design, f"R{n}44", CV_ROFF, "VREFN", f"CVX{n}",
              description=f"Channel {n} CV offset -- = R{n}41 by construction")
    _capacitor(design, f"C{n}41", CV_C1, f"CVX{n}", "MAGND",
               description=f"Channel {n} CV pole 1")
    _capacitor(design, f"C{n}42", CV_C2, f"CVN{n}", f"VC{n}",
               description=f"Channel {n} CV pole 2")
    design.connect(f"VC{n}", (package, out))
    design.connect(f"CVN{n}", (package, inverting))
    design.connect("MAGND", (package, non_inverting))


def shared(design):
    """The reference, the logic buffer, the amplifiers and the two ground stars.

    Everything else -- controller, ADC, relay drive, fail-safe, supply -- is in
    DEFERRED with a reason. What is here is the minimum the six channels need
    in order for section 5 to be checkable at all.
    """
    # Rail decoupling, in its own 700 series with a flat counter.
    #
    # It was C9{index}1 keyed on the package number, which is fine up to U9 and
    # produces C9101 at U10 -- a reference that reads as either C9-10-1 or
    # C91-01 and matches neither the 900-series grounding pattern nor anything
    # else. Caught by floorplan.check_domains(), which is a ground-domain check
    # rather than a naming one; it had no entry because no pattern could have
    # one. A reference scheme that cannot be pattern-matched is a reference
    # scheme with no invariants, which is how a decoupling capacitor ends up
    # grounded to whatever was closest.
    bypass = iter(range(701, 799))

    for ref in OPAMP_PACKAGES:
        design.add(Part(ref, OPAMP, SOIC14_FP,
                        units=len(OPAMP_UNITS),
                        description="Quad JFET, front end / I-V / servo / CV"))
        design.connect("VA+", (ref, OPAMP_PINS["V+"]))
        design.connect("VA-", (ref, OPAMP_PINS["V-"]))
        _capacitor(design, f"C{next(bypass)}", "100n/50V X7R", "VA+", "MAGND",
                   description=f"{ref} V+ bypass")
        _capacitor(design, f"C{next(bypass)}", "100n/50V X7R", "VA-", "MAGND",
                   description=f"{ref} V- bypass")

    for ref in VCA_PACKAGES_REFS:
        design.add(Part(ref, VCA, SOP16_FP, description="Quad VCA, Class AB"))
        design.connect("VA+", (ref, VCA_PINS["V+"]))
        design.connect("VA-", (ref, VCA_PINS["V-"]))
        # "Connect to analog signal ground with short, low inductance trace."
        # This pin is also the MAGND star point -- see floorplan.py.
        design.connect("MAGND", (ref, VCA_PINS["GND"]))
        # Page 3: "Recommend 100nF local decoupling capacitor placed as close
        # to package as possible with a low inductance trace to ground."
        _capacitor(design, f"C{next(bypass)}", "100n/50V X7R", "VA+", "MAGND",
                   description=f"{ref} V+ decoupling -- at the package")
        _capacitor(design, f"C{next(bypass)}", "100n/50V X7R", "VA-", "MAGND",
                   description=f"{ref} V- decoupling -- at the package")
        # MODE open is Class AB, and the spare cell's input and output are
        # grounded per page 5. Its control pin may float.
        spare = VCA_CHANNEL_PINS[VCA_SPARE_CELLS[ref]]
        design.connect("MAGND", (ref, spare["IIN"]), (ref, spare["IOUT"]))

    # The reference inverter, in U8's spare section. Two matched 10k, and its
    # own noise is the CV chain's floor at the loud end -- see control_noise().
    package, unit = SECTIONS[("refinv", 0)]
    out, inverting, non_inverting = OPAMP_UNITS[unit]
    _resistor(design, "R801", VREF_INV_R, "VREF", "RINV",
              description="Reference inverter input")
    _resistor(design, "R802", VREF_INV_R, "RINV", "VREFN",
              description="Reference inverter feedback")
    design.connect("VREFN", (package, out))
    design.connect("RINV", (package, inverting))
    design.connect("MAGND", (package, non_inverting))

    # The reference itself. Pins by role, because its map has not been read.
    design.add(Part(REF_REF, VREF_PART, SOIC8_FP,
                    description="2.5 V band-gap reference, 45 nV/rtHz with "
                                "C_NR; Kelvin-sensed, OUTF/OUTS shorted at "
                                "C804; also feeds the ADC"))
    design.connect("V5", (REF_REF, REF_PINS["IN"]))
    # OUTF forces and OUTS senses, shorted at the load: the datasheet's own
    # instruction, and the reason this is two pins on one net rather than one.
    design.connect("VREF", (REF_REF, REF_PINS["OUTF"]),
                   (REF_REF, REF_PINS["OUTS"]))
    # GND and GNDS both to the analogue ground, the sense leg at the load.
    design.connect("MAGND", (REF_REF, REF_PINS["GND"]),
                   (REF_REF, REF_PINS["GNDS"]))
    _capacitor(design, "C801", VREF_NR_CAP, "VNR", "MAGND",
               description="Reference noise reduction -- 75 -> 45 nV/rtHz")
    design.connect("VNR", (REF_REF, REF_PINS["NR"]))
    _capacitor(design, "C802", "10u/16V X7R", "VREF", "MAGND",
               footprint=C_FILM_FP, description="Reference reservoir")

    # The logic buffer, powered from the reference.
    #
    # **Its GND pin is on MAGND and not MDGND, and this is not a preference.**
    # It was MDGND for one revision and that was wrong by 40 dB.
    #
    # This part's outputs are a precision voltage, not a logic level: Vcc is
    # the reference, so a high is VREF and the CV filter turns the difference
    # between VREF and this output into Vc. That difference is referenced to
    # whatever this chip calls ground. Put its GND on the digital domain and
    # every millivolt between MDGND and MAGND appears in series with the
    # control voltage, multiplied by R2/R1 and then by am_sensitivity() into
    # audible AM:
    #
    #     0.1 mV of MDGND-MAGND offset -> AM 71 dB below the signal
    #     1.0 mV                       -> AM 51 dB
    #    10.0 mV                       -> AM 31 dB
    #
    # against the reference's own contribution at 91.7 dB. One millivolt of
    # digital ground noise would therefore be the dominant AM source in the
    # design by forty decibels, and nothing in the netlist or in any check
    # would have said so -- it is a ground-domain assignment, and the two nets
    # are both called ground.
    #
    # The crossing goes on the *input* side instead, where it is harmless: a
    # logic input only has to clear VIH relative to its own supply, and a 3.3 V
    # drive against a 1.75 V threshold tolerates about 1.5 V of ground offset.
    # So the boundary runs through this package -- which is exactly what TI
    # built it for, with inputs and outputs on opposite sides "to facilitate
    # printed circuit board layout".
    design.add(Part(LOGIC_REF, LOGIC, SOIC20_FP,
                    description="Octal buffer, Vcc = VREF, GND = MAGND: its "
                                "outputs are a precision voltage, so it sits "
                                "in the analogue domain and straddles the "
                                "boundary"))
    design.connect("VREF", (LOGIC_REF, LOGIC_PINS["VCC"]))
    design.connect("MAGND", (LOGIC_REF, LOGIC_PINS["GND"]))
    design.connect("OE", (LOGIC_REF, LOGIC_PINS["OE1"]),
                   (LOGIC_REF, LOGIC_PINS["OE2"]))
    _capacitor(design, "C803", "100n/50V X7R", "VREF", "MAGND",
               description="'541 local decoupling -- at the package")
    _capacitor(design, "C804", "10u/16V X7R", "VREF", "MAGND",
               footprint=C_FILM_FP,
               description="'541 charge reservoir -- keeps the switching "
                           "transient off the reference")
    for n in range(1, CHANNELS + 1):
        design.connect(f"PWM{n}", (LOGIC_REF, LOGIC_A[n]))
        design.connect(f"LOGO{n}", (LOGIC_REF, LOGIC_Y[n]))
        # The pull-downs that turn a hi-Z MCU into a defined logic low, which
        # is what makes fail_states()' second row silent rather than undefined.
        # On MDGND and at the connector, because they belong to the driving
        # side: their job is to define what the MCU's pin is doing, and the
        # '541's threshold tolerates the ground offset between them.
        _resistor(design, f"R81{n}", LOGIC_PULLDOWN, f"PWM{n}", "MDGND",
                  description=f"Channel {n} PWM pull-down -- fail-silent")
    # The two unused inputs must not float: page 4, note 1, "All unused inputs
    # of the device must be held at Vcc or GND to ensure proper device
    # operation." Held at this package's own ground.
    for n in (7, 8):
        design.connect("MAGND", (LOGIC_REF, LOGIC_A[n]))

    # Where the deferred blocks meet this one. Not placeholders: these are the
    # real interfaces, and declaring them is what lets check() insist every net
    # has two ends while the controller and the supply are still DEFERRED. When
    # those blocks land they replace these headers rather than joining them.
    design.add(Part("J8", "PWR", socket.CONN_FP[5], mpn=socket.CONN_MPN[5],
                    description="From the isolated DC-DC (DEFERRED): "
                                "1=VA+, 2=VA-, 3=MAGND, 4=V5, 5=MDGND"))
    for pin, net in ((1, "VA+"), (2, "VA-"), (3, "MAGND"),
                     (4, "V5"), (5, "MDGND")):
        design.connect(net, ("J8", pin))

    design.add(Part("J9", "CTRL", socket.CONN_FP[5], mpn=socket.CONN_MPN[5],
                    description="From the RP2040 (DEFERRED): 6 x PWM, OE, and "
                                "MDGND between every pair -- the same "
                                "GND-between-signals rule design.LINK_FP "
                                "makes upstream"))
    # Nine ways would be needed for a ground between every pair; two 5-way
    # connectors keep the mixer's own part. Pins alternate signal and ground.
    for pin, net in ((1, "MDGND"), (2, "PWM1"), (3, "MDGND"),
                     (4, "PWM2"), (5, "MDGND")):
        design.connect(net, ("J9", pin))
    design.add(Part("J10", "CTRL2", socket.CONN_FP[5], mpn=socket.CONN_MPN[5],
                    description="From the RP2040 (DEFERRED), continued"))
    for pin, net in ((1, "PWM3"), (2, "MDGND"), (3, "PWM4"),
                     (4, "MDGND"), (5, "PWM5")):
        design.connect(net, ("J10", pin))
    design.add(Part("J11", "CTRL3", socket.CONN_FP[3], mpn=socket.CONN_MPN[3],
                    description="From the RP2040 (DEFERRED), continued: "
                                "1=PWM6, 2=MDGND, 3=OE"))
    for pin, net in ((1, "PWM6"), (2, "MDGND"), (3, "OE")):
        design.connect(net, ("J11", pin))

    # The two stars. R901 is the one bridge constraint 2 allows; R902 is the
    # module's own analogue/digital join, entirely inside the module and not a
    # bond to anything of the mixer's.
    _resistor(design, GROUND_STAR, "0R", "MAGND", socket.AGND,
              description=f"THE bond: module audio ground to mixer AGND at "
                          f"{BOND_TO} -- constraint 2, exactly one")
    _resistor(design, DOMAIN_STAR, "0R", "MAGND", "MDGND",
              description="Module analogue/digital star -- internal, not a "
                          "bond to the mixer")
    design.add(Part("J7", "BOND", PAD_FP, in_bom=False,
                    description=f"Solder pad: single ground bond to the "
                                f"mixer's {BOND_TO}, and the six triad "
                                f"shields land here too"))
    design.connect(socket.AGND, ("J7", 1))


def build():
    design = Design()
    shared(design)
    for n in range(1, CHANNELS + 1):
        channel(design, n)
    design.check()
    return design


DESIGN = build()
PARTS = DESIGN.parts
NETS = DESIGN.nets


def _report():
    """Every value with its arithmetic. Run this file."""
    print(f"cv-module, one channel, against summing-mixer @ "
          f"{socket.PIN[:7]}")
    print(f"{VCA} {VCA_REVISION}")
    print()

    print("the control law")
    print(f"  gain constant        {GAIN_CONSTANT * 1e3:>8.1f} mV/dB "
          f"(datasheet, TA = 25 C)")
    print(f"  die rise             {die_rise():>8.1f} C   "
          f"(118 C/W x {2 * MODULE_RAIL * VCA_SUPPLY_MA:.0f} mW)")
    print(f"  dg/g per volt        {am_sensitivity():>8.3f} /V  "
          f"(spec says 3.48)")
    t = tempco_span()
    print(f"  a -40 dB gate at {t['volts']:.3f} V wanders "
          f"{t['cold']:.1f} .. {t['hot']:.1f} dB over "
          f"{socket.AMBIENT_C[0]:.0f}-{socket.AMBIENT_C[1]:.0f} C ambient "
          f"({t['span']:.1f} dB)")
    print(f"  common-mode across all six, so not compensated -- see "
          f"tempco_span()")
    print()

    print("front end, inverting unity (see FRONT_R on why not a difference amp)")
    f = front_end()
    print(f"  PIN(n) sees          {f['socket_ohms']:>8.0f} ohm  "
          f"(constraint 4 wants 5k-10k)")
    print(f"  with DC_BLOCK        {f['corner']:>8.2f} Hz   "
          f"(mixer: 15.9 shut, 31.8 wide open)")
    print(f"  noise gain           {f['noise_gain']:>8.1f}")
    print(f"  own noise            {f['total'] * 1e9:>8.1f} nV/rtHz, "
          f"x6 -> {f['six_channels'] * 1e9:.0f}")
    print(f"  op-amp sections      {OPAMP_NEEDED:>8d}     -> "
          f"{OPAMP_QUADS} x {OPAMP}")
    print()

    print("  what that does to the mixer's own DC block, via coupling_burden()")
    print("    freq    corner    across C   loss     was (5k)   delta")
    for row in dc_block_delta():
        print(f"    {row['hz']:>5.1f}  {row['corner']:>6.2f} Hz  "
              f"{row['across'] * 100:>7.1f} %  {row['loss_db']:>+6.2f}   "
              f"{row['was_loss_db']:>+6.2f}    {row['gain_db']:>+5.2f} dB")
    print()

    print("coarse pad = R_IN, two dual-coil latching relays per channel")
    p = pad_states()
    print(f"  step      R_IN     I_IN at {p['peak']:.2f} V pk    in 7k5-100k?"
          f"   10u corner")
    for row in p["steps"]:
        print(f"  {row['db']:+6.2f} dB  {row['rin']:>6.0f}  "
              f"{row['current'] * 1e6:>8.1f} uA        "
              f"{'yes' if row['in_range'] else 'NO ':>10}     "
              f"{row['block_corner']:>6.2f} Hz")
    print(f"  R_OUT {VCA_ROUT_OHMS:.0f} fixed, so 0 dB is exactly unity")
    print(f"  input-current headroom {p['headroom_ratio']:.0f}x against the "
          f"900 uA page 4 advises")
    a = allocation()
    print(f"  {a['packages']} packages, {a['per_package']} channels each: "
          f"{a['die_mates']} die-mates per string against "
          f"{a['alternative_die_mates']} at 4+2, {a['spare']} spare grounded")
    print()

    print("VCA noise, Class AB, at the 0 dB step")
    v = vca_noise(VCA_RIN_STEPS[0])
    print(f"  R_IN/OUT {VCA_RIN_STEPS[0]:.0f}      {v['dbu']:>6.1f} dBu  "
          f"{v['rms'] * 1e6:>6.2f} uV rms  {v['density'] * 1e9:>5.1f} nV/rtHz")
    for rin in sorted(VCA_NOISE_DBU):
        row = vca_noise(rin)
        print(f"    datasheet {rin:>6.0f}  {row['dbu']:>6.1f} dBu"
              f"                  {row['density'] * 1e9:>5.1f}")
    print()

    print("DC servo, and constraint 3")
    s = servo_residual()
    print(f"  integrator corner    {s['corner']:>8.2f} Hz")
    print(f"  high-pass it imposes {s['highpass']:>8.4f} Hz  "
          f"(vs the mixer's 15.9)")
    print(f"  uncorrected offset   {s['uncorrected'] * 1e3:>8.2f} mV  "
          f"(150 nA x R_OUT)")
    print(f"  correction authority {s['authority'] * 1e3:>8.0f} mV")
    print(f"  residual on SIN(n)   {s['residual'] * 1e3:>8.2f} mV  "
          f"(= the servo's own Vos)")
    print(f"  -> at SUM_OUT        {s['at_sum_out'] * 1e3:>8.2f} mV  "
          f"(x6 channels)")
    print(f"  -> master wiper      {s['wiper_amps'] * 1e9:>8.1f} nA  "
          f"through C703/R706; the mixer accepts 0.2-1.0 nA")
    print()

    print("CV chain -- the block ranked first of three")
    c = cv_filter()
    print(f"  reference            {VREF:>8.2f} V   {VREF_PART}, "
          f"{VREF_NOISE * 1e9:.0f} nV/rtHz with C_NR")
    print(f"  VREF ceiling for AHC {VREF_MAX_FOR_AHC:>8.2f} V   "
          f"(3.3 V GPIO / 0.7 Vcc)")
    print(f"  filter gain          {c['gain']:>8.4f}     "
          f"= R2/R1, and R_OFF = R1 so cancellation is exact: "
          f"{c['exact_cancellation']}")
    print(f"  corner               {c['f0']:>8.1f} Hz  Q = {c['q']:.3f} "
          f"(Bessel is 0.577)")
    print(f"  Vc span              {c['span']:>8.3f} V   -> "
          f"{c['depth_db']:.1f} dB of depth, {c['step_db'] * 1e3:.1f} mdB/LSB "
          f"at {PWM_BITS} bits")
    r = pwm_ripple()
    print(f"  carrier {PWM_CARRIER / 1e3:.1f} kHz down {-r['attenuation_db']:.0f} dB "
          f"-> {r['at_port'] * 1e6:.0f} uV at Vc = "
          f"{r['gain_error_db'] * 1e3:.2f} mdB of gain")
    print()

    print("  control noise at Vc, nV/rtHz")
    print("    duty   reference  inverter  resistors  amplifier   total   "
          "AM below signal")
    for duty in (0.0, 0.25, 0.5, 1.0):
        n = control_noise(duty)
        m = am_noise(duty)
        print(f"    {duty:>4.2f}   {n['reference'] * 1e9:>9.1f}  "
              f"{n['inverter'] * 1e9:>8.1f}  {n['resistors'] * 1e9:>9.1f}  "
              f"{n['amplifier'] * 1e9:>9.1f}  {n['total'] * 1e9:>6.1f}   "
              f"{m['below_signal']:>6.1f} dB")
    m = am_noise(1.0)
    print(f"  additive floor is {m['additive_below_signal']:.1f} dB under the "
          f"same signal, so AM has {m['margin']:.1f} dB of margin")
    print(f"  (that is why <=22k filter resistors survive -- the spec's "
          f"'13 dB under the source' assumed a 5 V reference)")
    print()

    print("fail states, from cv_filter()")
    for row in fail_states():
        print(f"  {row['state']:<44} Vc = {row['vc']:>+7.2f} V  "
              f"-> {row['db']:>+7.1f} dB")
    print()

    print("assumptions still open here")
    for name, assumption in sorted(MEASURED.items()):
        print(f"  {name:<16} {assumption!r}")


if __name__ == "__main__":
    _report()
