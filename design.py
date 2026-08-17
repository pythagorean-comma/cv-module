"""One channel of the per-string CV module, as derived values.

Values only, in this pass. The netlist, the five constraint checks and the
board follow; this file is where every number gets its arithmetic, because a
schematic full of plausible values is worse than an incomplete one -- it looks
finished.

    from the mixer's RV{n}01 socket
      PIN{n} --[ 10k ]--+-- inverting unity front end --+-- envelope tap
       (pin 1)          |          (Rf 10k)             |
                     virtual                            +--[ 10u ]--,
                      earth                                         |
                                                             R_IN 12k1
                                                                    |
      SIN{n} <-- I-V + DC servo <-- SSI2164 <----------------------+
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

**There is no coarse pad.** Spec section 4.1 asks for 0/-6/-12/-18 dB on
latching relays to "keep the VCA near unity where its noise costs least", and
the SSI2164's noise does not work that way: its table sweeps R_IN and R_OUT
together, and vca_cell_fit() shows the rise belongs to R_OUT, which a pad does
not move. Against the control port -- which reaches the same level for no parts
-- the pad is 0.03 to 3.9 dB *worse* on noise and no better on distortion.
Thirty-six parts, 52 % of the placed courtyard, two thirds of the BOM and a
coil supply rail RAILS never had, struck. See pad_benefit(), and VCA_RIN for
what is left.

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
        value=12_100.0, units=" ohm, R_IN = R_OUT, one fixed pair per channel",
        low=7_500.0, high=20_000.0,
        question="How low can R_IN go before distortion costs more than the "
                 "noise it buys? The datasheet gives a range and a direction "
                 "-- 7.5k to 100k, 'lower values will produce the best noise "
                 "performance at some cost in distortion' -- and no number. "
                 "The one figure it does give is the level dependence: "
                 "0.05 % at 0.775 V rms and 0.025 % 17 dB below that.",
        sets="the VCA's output noise, and with it whether this module is "
             "audible against the six Nu capsules at all",
        when_wrong="Nothing structural: two resistors per channel, and the "
                   "coarse pad's deletion means the top of the range is no "
                   "longer bounded by anything but the part. "
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
#
# **The conditions line above the whole specification table was read this
# session and it is the half that decides the coarse pad.** Verbatim, page 2:
# "V_S = +/-15V, V_IN = 0.775V_RMS, f = 1kHz, A_V = 0dB, Class AB, T_A = 25C;
# using Figure 1 circuit without diode". Three things follow:
#
#   * the parameter is **R_IN/OUT** -- both resistors, moved together. The
#     table is neither an R_IN sweep nor an R_OUT sweep, so on its own it
#     cannot say which of the two the rise belongs to. That question is the
#     whole of the pad's case and nothing in this repo had asked it; see
#     vca_cell_fit() and cell_noise();
#   * **A_V = 0 dB**, so every row is at unity and the table says nothing
#     about noise against control voltage either;
#   * **"Figure 1 circuit"** is the cell plus a 1/2 TL072 and both resistors,
#     so these figures already contain an I-V amplifier -- which is what
#     vca_cell_fit() finds sitting underneath them as a fixed term.
VCA_NOISE_DBU = {30_000.0: -93.0, 20_000.0: -96.0,
                 15_000.0: -98.0, 7_500.0: -101.0}
VCA_NOISE_CONDITION = "R_IN/OUT together, A_V = 0 dB, Figure 1 without diode"
VCA_RIN_RANGE = (7_500.0, 100_000.0)

# The amplifier inside that condition. Page 3, Figure 1: the I_OUT pin is held
# at virtual earth by "1/2 TL072", whose datasheet noise is 18 nV/rtHz at
# 1 kHz. Declared because vca_cell_fit() has to say what the fixed term it
# finds is the same size as: 34.7 nV against 2 x 18 = 36.
VCA_MEASURE_AMP_EN = 18e-9

# Page 2, the THD rows, under the same conditions line -- so V_IN is 0.775 V
# rms throughout and the only thing that changes down the column is A_V. Class
# AB, 80 kHz measurement bandwidth. Read first-hand this session:
#
#     A_V = 0 dB                    0.05  %
#     A_V = 0 dB, V_IN = -17 dBu    0.025 %
#     A_V = +20 dB                  0.20  %
#     A_V = -20 dB                  0.045 %
#
# **The -20 dB row is the one the pad existed to avoid needing, and it is
# better than the unity row.** It is measured with the full 0.775 V still
# arriving at R_IN and the cell attenuating by 20 dB in the control port --
# exactly the case the pad was there to keep the design out of. The part is not
# worse there. See pad_benefit(), which is where this table is spent.
#
# The second row is the level dependence, and it is the one real effect: a
# 17 dB smaller input halves the distortion. It belongs to the signal level and
# not to the gain setting, which is why a pad -- attenuating before the cell --
# can move it and a control voltage cannot.
# Keyed (A_V in dB, V_IN in volts rms) and valued as a *fraction*, not as the
# percent the datasheet prints -- STYLE.md rule 9, the unit belongs in the
# identifier and not in a comment.
VCA_THD_FRACTION = {(0.0, 0.775): 5.0e-4, (0.0, 0.1095): 2.5e-4,
                    (20.0, 0.775): 2.0e-3, (-20.0, 0.775): 4.5e-4}

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


def vca_noise(rin_out):
    """Output noise density of one VCA channel at unity, V/rtHz.

    Interpolated log-log through VCA_NOISE_DBU, which is four measured points
    rather than a model, so this is a reading of the datasheet's table and not
    a derivation.

    **The argument is R_IN/OUT and not R_IN, and that is a correction.** The
    parameter was called `rin` and the docstring said the table's condition
    "holds only at the 0 dB pad step" -- which was true, and was then used as
    though the curve were an R_IN dependence with R_OUT along for the ride. It
    is not: cell_noise() splits the same four points into a current at the
    cell's output and a fixed voltage there, and the rise belongs to **R_OUT**.
    Calling this with a padded R_IN answered a question the table cannot be
    asked. Nothing did -- the pad's four steps were never costed at all, which
    is how the error survived; see pad_benefit().

    With the pad gone, R_IN = R_OUT by construction on every channel, so this
    function is now called at the datasheet's own stated condition rather than
    extrapolated away from it.

    It is a total, not a density -- dBu over 20 Hz to 20 kHz unweighted -- so
    the conversion below assumes it is flat. The datasheet publishes no
    spectrum.
    """
    points = sorted(VCA_NOISE_DBU)
    if rin_out <= points[0]:
        dbu = VCA_NOISE_DBU[points[0]]
    elif rin_out >= points[-1]:
        dbu = VCA_NOISE_DBU[points[-1]]
    else:
        lower = max(p for p in points if p <= rin_out)
        upper = min(p for p in points if p >= rin_out)
        if lower == upper:
            dbu = VCA_NOISE_DBU[lower]
        else:
            fraction = math.log(rin_out / lower) / math.log(upper / lower)
            dbu = (VCA_NOISE_DBU[lower]
                   + fraction * (VCA_NOISE_DBU[upper] - VCA_NOISE_DBU[lower]))
    rms = 0.7746 * 10 ** (dbu / 20)
    return {"dbu": dbu, "rms": rms, "density": rms / math.sqrt(BANDWIDTH)}


def vca_cell_fit():
    """Split the datasheet's four noise points into a current and a voltage.

    The table sweeps R_IN and R_OUT together, so it cannot say on its own
    which resistor the rise belongs to -- and that is the question the coarse
    pad's whole case rests on, because the pad raises R_IN and leaves R_OUT
    alone. This is the arithmetic that separates them.

    Two of the four terms are computed rather than fitted, from the mixer's own
    thermal(), because they are known:

        R_IN's Johnson current through the cell at unity, into R_OUT
                        sqrt(4kT/R_IN) x R_OUT
        R_OUT's own Johnson voltage
                        sqrt(4kT x R_OUT)

    and at the table's condition R_IN = R_OUT = R those are equal, so together
    they are 2.4kT.R of noise power. What is left is two unknowns, and the
    model is linear in R^2:

        e^2 - 2.4kT.R  =  i_cell^2 . R^2  +  e_fixed^2

    so an ordinary least squares in x = R^2 gives both with no search, no
    iteration and no third-party package.

    **The distinction is the whole decision.** `i_cell` is a *current* at the
    cell's output, so it is multiplied by R_OUT and the pad cannot touch it.
    `e_fixed` is a *voltage* there and depends on neither resistor. Nothing in
    the model rises with R_IN at all; the only R_IN term, its Johnson current,
    *falls* as R_IN grows.

    Two corroborations, neither of them proof:

    **e_fixed comes out at 34.7 nV/rtHz, and the measuring amplifier is a
    TL072 at 18.** VCA_MEASURE_AMP_EN, at a noise gain of 2, is 36 -- so the
    fixed term is the size of the op-amp the datasheet measured through, which
    is a thing the conditions line says is in there. It is not proof that it is
    *only* that: an output-stage voltage noise inside the cell would sit in the
    same place and four points cannot separate them. Everything downstream
    therefore keeps the pessimistic reading and leaves the term in.

    **i_cell comes out at 3.8 pA/rtHz, which is full shot noise on 44 uA.**
    Page 6 describes Class AB as class A at low signal levels and Figure 5 puts
    the class A/B transition current at about 10 uA at the smallest mode
    current it plots, with MODE open below that. So the fit implies a core
    idling at a few times its own transition current, which is the right order
    of magnitude and is all a plausibility check can say.

    One thing the datasheet contradicts itself about, recorded rather than
    reconciled. Page 8's ULTRA-LOW NOISE VCA paragraph says paralleling four
    channels with R_IN/OUT divided by four improves output noise by exactly
    6 dB, "-97dBu for a single channel to -103dBu". Every term in the model
    above scales by 6 dB under that transformation *except* e_fixed, which is
    the op-amp and does not move -- so a full 6 dB requires the fixed term to
    be negligible, and the table's own curvature requires it to be 34.7 nV.
    They cannot both be exact. The table is a specification and the paragraph
    is prose with round numbers, so the table wins here; it is worth knowing
    that the part's own document disagrees by two or three decibels about this.
    """
    fourkt = 4 * BOLTZMANN * TEMPERATURE
    rows = []
    for r, dbu in sorted(VCA_NOISE_DBU.items()):
        measured = vca_noise(r)["density"]
        rows.append((r, measured, measured ** 2 - 2 * fourkt * r))

    # Least squares of y = a.x + b with x = R^2, y = the residual power above.
    n = len(rows)
    xs = [r ** 2 for r, _, _ in rows]
    ys = [y for _, _, y in rows]
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    variance = sum((x - mean_x) ** 2 for x in xs)
    slope = covariance / variance
    intercept = mean_y - slope * mean_x
    assert slope > 0 and intercept > 0, (
        f"the two-term model does not fit: i_cell^2 = {slope:g}, "
        f"e_fixed^2 = {intercept:g} -- a negative term means the split is "
        f"wrong, not that the numbers are")

    i_cell, e_fixed = math.sqrt(slope), math.sqrt(intercept)
    residuals = [(r, 20 * math.log10(
        math.sqrt(slope * r ** 2 + intercept + 2 * fourkt * r) / measured))
        for r, measured, _ in rows]
    return {
        "i_cell": i_cell,
        "e_fixed": e_fixed,
        "amp_at_noise_gain_2": 2 * VCA_MEASURE_AMP_EN,
        "shot_equivalent_amps": i_cell ** 2 / (2 * ELECTRON_CHARGE),
        "residuals_db": residuals,
        "rms_db": math.sqrt(sum(d ** 2 for _, d in residuals) / n),
    }


def cell_noise(rin, rout, gain_db=0.0, input_referred=0.0, e_fixed=None):
    """One cell's output noise density at any R_IN, R_OUT and gain, V/rtHz.

    The model vca_cell_fit() establishes, evaluated away from the condition it
    was fitted at. At rin == rout and gain_db == 0 it reproduces the
    datasheet's own four points to better than 0.2 dB, which is the only claim
    it can make on its own authority.

        e_out^2 = R_OUT^2 [ g^2 (i_in^2 + 4kT/R_IN) + i_out^2 ]
                  + 4kT R_OUT + e_fixed^2

    `input_referred` is the fraction of i_cell's *power* that sits ahead of the
    gain core and is therefore attenuated with the signal by g. **It is not
    known and cannot be got from the datasheet**, so it is a parameter with no
    default worth defending: 0.0 puts all of the cell's noise at the output,
    where the control voltage cannot reduce it, and 1.0 puts all of it at the
    input. Both ends are computed wherever the answer might depend on it, and
    the pad's case is dead at both -- which is why the split never had to be
    resolved. Page 6's account of the core favours somewhere in between: V_C
    "steers the signal current from one side of each differential pair to the
    other", and what is steered away from I_OUT is signal and noise alike.

    `e_fixed` defaults to the fit, which attributes the whole R-independent
    term to the cell and is the pessimistic reading. The design's own I-V
    amplifier is an OPA1644 at 3.3 nV/rtHz rather than the TL072 the table was
    measured through; if the term really is the amplifier, one channel is about
    2 dB quieter than every figure this repo quotes. Not claimed, because four
    points cannot tell an op-amp from an output stage.
    """
    fit = vca_cell_fit()
    if e_fixed is None:
        e_fixed = fit["e_fixed"]
    g = 10 ** (gain_db / 20)
    i_in_squared = fit["i_cell"] ** 2 * input_referred
    i_out_squared = fit["i_cell"] ** 2 * (1 - input_referred)
    fourkt = 4 * BOLTZMANN * TEMPERATURE
    return math.sqrt(
        rout ** 2 * (g ** 2 * (i_in_squared + fourkt / rin) + i_out_squared)
        + fourkt * rout + e_fixed ** 2)


# ---------------------------------------------------------------------------
# The front end
# ---------------------------------------------------------------------------

# A single-ended inverting unity stage. Two resistors.
#
# **It was a four-resistor difference amplifier, and the reason it was is worth
# more than the circuit.** Constraint 2 -- spec section 5, item 2 -- reads:
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
# R_IN and R_OUT -- and the 2-bit coarse pad, which has been struck
# ---------------------------------------------------------------------------

# **The coarse pad is gone. Thirty-six parts, 52 % of the placed courtyard, two
# thirds of the BOM, twenty-four coil drives and a coil supply rail RAILS never
# had -- deleted, because what it buys is between nothing and less than
# nothing.** pad_benefit() is the arithmetic and it is short; this is why it was
# never run.
#
# The brief that asked the question called it 40 parts. It is 36 -- twelve
# relays and twenty-four resistors -- of which six resistors come back as the
# fixed R_IN, so the netlist goes from 188 parts and 138 nets to 158 and 102.
#
# What was here: 0 / -6 / -12 / -18 dB in two bits, four E96 input resistors
# per channel selected by two dual-coil latching relays, from spec section 4.1
# ("Coarse pad ... Latching relays. Keeps the VCA near unity where its noise
# costs least") and section 4.5's "12 coils (six 2-bit pads)".
#
# **The claim it rests on is that a VCA is noisier away from unity, and the
# SSI2164 is not.** Its noise table sweeps *R_IN/OUT* -- both resistors
# together -- and vca_cell_fit() splits those four points into a current at
# the cell's output and a fixed voltage there. A current is multiplied by
# R_OUT. The pad raises R_IN and leaves R_OUT alone, so it moves the cell's
# noise by 0.2 dB, in the direction of *less*, and only because R_IN's own
# Johnson current falls. The rise from 62 to 123 nV/rtHz that the pad was
# implicitly costed against belongs to R_OUT and the pad never touches it.
#
# The datasheet says the same thing about distortion, which is the other reading
# of "where its noise costs least": VCA_THD_FRACTION's A_V = -20 dB row is
# measured at full input and is *lower* than the unity row.
#
# The comparison that decides it is not "the pad against nothing" -- the module
# has to reach the same output level either way -- it is **the pad against the
# control port**, which can attenuate the same 18 dB with no parts at all. At
# the cell that comparison is between -0.03 and -3.9 dB: the pad is never
# quieter, and against the datasheet's own THD rows it is not less distorted
# either, because A_V = -20 dB measures *better* than A_V = 0 dB at full input.
#
# **How it survived is the usual shape and the instrument is new.** It was not
# an unchecked constraint this time -- it was an `Assumption` whose "if it is
# wrong" clause cancelled its own consequence. ASSUMPTIONS.md carried "the
# datasheet's noise figures apply at pad steps other than 0 dB", answered with
# "the pad steps are noisier than modelled -- but they are used when the source
# is hot, so the signal is larger by the same amount", and closed with "it does
# not change a component value". Every clause of that is wrong: the steps are
# not noisier, the source is not hotter (the module's input is whatever arrives
# at PIN{n}, and the pad is cut-only), and it changes forty. An assumption
# whose consequence is written as self-cancelling is an assumption nobody will
# ever compute, which is the same failure as a check that covers less than its
# name -- one level further out, where nothing is instrumented at all.
#
# Kept from it, because they are true and were the good part of the reasoning:
# a pad on this part belongs at R_IN rather than in a divider (the SSI2164 is
# current-in, so contacts in series with 12k1 carry ~100 uA and 100 mohm of
# contact resistance is a 1e-5 error, where the same contact in a divider's
# shunt leg *is* the pad ratio); and if a coarse range switch is ever wanted
# for a reason that is not noise, that is where it goes.
#
# R_IN, and the argument for it has changed even though the number has not.
#
# 12k1 was forced: the top pad step had to stay inside the part, 20k doubles
# three times to 160k and page 4's range stops at 100k, 12k1 doubles to 96k8
# and clears it. **That constraint is gone with the pad**, so R_IN is now free
# across the datasheet's whole 7.5k-100k and the choice is the one page 4
# actually describes -- "lower values will produce the best noise performance
# at some cost in distortion" -- with no number attached to either side.
#
# It stays at 12k1 on this argument: at the mixer's own clipping_peak() the
# input current is 102 uA against the 900 uA page 4 advises designing to, so
# nothing at this end of the range is near a limit, and 12k1 is 2.9 dB quieter
# than the recommended 20k. 7.5k would be 2.1 dB quieter again and is the one
# place the distortion cost might bite, which is exactly what
# MEASURED["vca_rin"] is an Assumption about. The value here is that
# assumption's, not a second copy of it.
VCA_RIN = "12k1 0.1%"
VCA_RIN_OHMS = MEASURED["vca_rin"].value

# R_OUT equals R_IN. That is the unity condition rather than a chosen value --
# the SSI2164 is current-in/current-out, so channel gain is R_OUT/R_IN -- and
# it is written as the equality so the two cannot drift apart.
VCA_ROUT = VCA_RIN
VCA_ROUT_OHMS = VCA_RIN_OHMS

# Across R_OUT at the I-V converter. Page 4: "Many op-amps require a feedback
# capacitor to preserve phase margin. A value of 100pF will suffice in most
# cases; larger values can be used to reduce high-frequency noise at the
# expense of bandwidth."
IV_CF = "100p/50V C0G"
IV_CF_FARADS = 100e-12

# The pad steps that were here, kept as data because pad_benefit() has to be
# able to price the thing that was deleted. Not fitted anywhere: no netlist, no
# footprint, no BOM line. Exact ratios rather than the E96 values that were
# actually drawn (24k3, 48k7, 97k6), because there are no parts to name any
# more and the difference is under 1.5 %.
PAD_STEPS_DB = (0.0, -6.0, -12.0, -18.0)
PAD_STEPS_RIN = tuple(VCA_RIN_OHMS * 10 ** (-db / 20) for db in PAD_STEPS_DB)


def vca_input():
    """What the cell's input sees, with one fixed R_IN and nothing switching.

    Three things, and the middle one is the reason the pad was never needed for
    headroom either: the input current at the mixer's own clipping_peak()
    against the 900 uA page 4 advises designing to, whether R_IN sits inside
    the 7.5k-100k the part is specified over, and the corner the 10 uF control-
    feedthrough capacitor makes with it.

    The corner used to move with the pad step -- 1.32 Hz at 12k1 down to
    0.16 Hz at 97k6 -- and is now one number.
    """
    peak = socket.clipping_peak()
    return {
        "rin": VCA_RIN_OHMS,
        "rout": VCA_ROUT_OHMS,
        "gain_db": 20 * math.log10(VCA_ROUT_OHMS / VCA_RIN_OHMS),
        "peak": peak,
        "current": peak / VCA_RIN_OHMS,
        "in_range": VCA_RIN_RANGE[0] <= VCA_RIN_OHMS <= VCA_RIN_RANGE[1],
        "block_corner": 1.0 / (2 * math.pi * VCA_INPUT_BLOCK_FARADS
                               * VCA_RIN_OHMS),
        "headroom_ratio": VCA_INPUT_CURRENT_MAX / (peak / VCA_RIN_OHMS),
        # Both stated as "quieter by", positive, against the datasheet's own
        # recommendation and against the quiet end of its range.
        "quieter_than_recommended_db": 20 * math.log10(
            vca_noise(20_000.0)["density"] / vca_noise(VCA_RIN_OHMS)["density"]),
        "quietest_would_gain_db": 20 * math.log10(
            vca_noise(VCA_RIN_OHMS)["density"]
            / vca_noise(VCA_RIN_RANGE[0])["density"]),
    }


def pad_benefit():
    """What the 2-bit coarse pad buys. The answer is nothing, and here is why.

    Spec section 4.1 gives the pad one job -- "Keeps the VCA near unity where
    its noise costs least" -- and 00-current-state.md carries it through five
    documents as "Coarse switched passive pad (latching relays) + VCA near
    unity. Unchanged". Neither computes it, and the cost is forty parts.

    **The comparison has to be against the control port, not against nothing.**
    The module must reach the same output level either way, so the alternative
    to 18 dB of pad is 18 dB more attenuation in V_C -- which is free, already
    drawn, and has 61.3 dB of span against a 47 dB requirement. Everything
    except the cell is identical between the two routes, and that is worth
    stating because it is what lets the whole question be settled at the cell:

      * the front end is upstream of R_IN, so its noise is divided by the pad
        ratio in the pad route and by the gain in the control route -- the same
        number both times;
      * the servo injects at the I-V summing node, downstream of both;
      * the input current the cell handles differs, and that is the one real
        asymmetry. It is priced below, from the datasheet's own THD rows.

    So what is left is the cell, and the cell is cell_noise(). The pad holds
    R_OUT and raises R_IN; the control port holds both and lowers g. Two rows
    per step because `input_referred` is unknown -- at 0.0 the cell's noise is
    all at its output and the control port cannot reduce it, at 1.0 it is all
    at the input and attenuates fully. **The pad loses at both ends**, by 0.03
    to 3.9 dB at the -18 dB step, so the split never has to be resolved.

    Distortion, which is the other thing "near unity" might have meant, from
    VCA_THD_FRACTION. A_V = -20 dB at full input is 0.045 % against unity's 0.050 %:
    the control port is *not* the distorting way to attenuate. What does move
    distortion is input level -- 0.025 % at -17 dBu -- and that is the one
    thing the pad genuinely does, since it divides the current the cell
    handles. It is worth about half the THD of a channel that is 18 dB down in
    the mix, which is -66 dBc becoming -70 dBc on a signal already 18 dB below
    the rest. Not forty parts.

    Two smaller things the pad would have bought, priced so they are not
    rediscovered as arguments:

    **Tempco.** The -3300 ppm/degC gain constant makes drift proportional to
    the dB taken in V_C, so 18 dB of pad removes 18 dB of it -- 2.9 dB of
    wander over the 0-50 C ambient. tempco_span() already declines to
    compensate a larger figure than that on the ground that it is common-mode
    across one die, and the lead feature is differential in a way that a
    per-channel *static* offset is not.

    **Control feedthrough**, which is -60 dB for a 0 to -40 dB change and is
    the binding constraint on the gating feature. It is a property of the
    *change* in V_C, and the pad cannot help with it: relays cannot switch per
    step of an 8-per-second pattern, so every dB of gating is in V_C whether or
    not a pad sets the static level.
    """
    rows = []
    for db, rin in zip(PAD_STEPS_DB, PAD_STEPS_RIN):
        pad = cell_noise(rin, VCA_ROUT_OHMS)
        control = {f: cell_noise(VCA_RIN_OHMS, VCA_ROUT_OHMS, gain_db=db,
                                 input_referred=f) for f in (0.0, 1.0)}
        rows.append({
            "db": db, "rin": rin,
            "pad_cell": pad,
            "control_cell": control,
            # Positive would mean the pad is quieter. Neither end is.
            "benefit_db": {f: 20 * math.log10(control[f] / pad)
                           for f in control},
            "pad_current": socket.clipping_peak() / rin,
            "control_current": socket.clipping_peak() / VCA_RIN_OHMS,
        })
    return {
        "rows": rows,
        "thd_unity": VCA_THD_FRACTION[(0.0, 0.775)],
        "thd_attenuated": VCA_THD_FRACTION[(-20.0, 0.775)],
        "thd_low_level": VCA_THD_FRACTION[(0.0, 0.1095)],
        "cv_span_db": cv_filter()["depth_db"],
        "deepest_step_db": min(PAD_STEPS_DB),
        "tempco_saved_db": abs(tempco_span(min(PAD_STEPS_DB))["span"]),
    }


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
# The 35 nV/rtHz belongs to the 2.048 V option. MAX6126 noise rises with output
# voltage: with the 0.1 uF NR capacitor fitted it is 35 nV/rtHz at 2.048 V,
# **45 at 2.5 V**, 80 at 4.096 V and 95 at 5.0 V.
#
# **All four are now confirmed first-hand** from Maxim's own PDF -- 19-2647
# Rev 8, the per-voltage electrical tables, one page each -- where they had been
# read from a text mirror. Every figure the mirror gave was right, which is worth
# stating as plainly as a correction would have been. The e_OUT rows also give the
# unbypassed figures, so what the NR capacitor buys is exact: 60 -> 35 at
# 2.048 V, **75 -> 45 at 2.5 V**, 120 -> 80 at 4.096 V, 145 -> 95 at 5.0 V.
#
# One correction to the wording rather than the numbers: "scales with output
# voltage" is loose. 2.5 V and 2.8 V both read 75 -> 45, so the family steps
# rather than scales, and the parts share tables across adjacent voltages. The
# conclusion is unaffected -- 45 against 95 is 2.11x for a 2.0x change in
# full scale, so scaling up and dividing back down still cancels -- but the
# mechanism is a lookup and not a proportionality, and a proportionality is the
# kind of thing that gets extrapolated later.
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

# **The NR capacitor costs 20 ms of turn-on time, and that lands on the
# fail-safe rather than on the noise budget.** First-hand from the pinned
# datasheet's own electrical table for the 2.5 V part (page 4): turn-on settling
# to 0.01% of final value is 1 ms with C_NR = 0 and **20 ms with C_NR = 0.1 uF**,
# a 20x penalty for the 75 -> 45 nV/rtHz the capacitor buys. Page 16 says the
# same thing in prose: "A noise reduction capacitor of 0.1uF increases the
# turn-on time to 20ms."
#
# Why it matters here and not in an ordinary reference application: **the '541's
# Vcc *is* VREF**, so for those 20 ms the whole CV chain's full scale is ramping
# from zero. Positive Vc attenuates, so a CV of zero is *unity gain*, and spec
# section 4.5 already names this shape of fault -- "a DAC's POR to zero scale =
# 0 V = unity gain = fail-loud ... Same applies to PWM outputs idling low."
#
# 20 ms is four times the ~5 ms a relay needs to transfer, which is the figure
# section 4.5 quotes, so the bypass relay can be held bypassed across it. That
# makes this a **sequencing requirement rather than a hazard**: the fail-safe
# must not release bypass until VREF has settled, and the number it has to wait
# for is this one. Recorded here because the fail-safe is DEFERRED and this is
# the kind of constant that gets rediscovered by a bang in a speaker.
VREF_TURN_ON_S = 20e-3
VREF_TURN_ON_NO_NR_S = 1e-3

# The datasheet's stability range for whatever hangs on OUTF, page 4:
# "Capacitive-Load Stability Range ... No sustained oscillations ... 0.1 to 10 uF".
# Page 16 states it as a requirement rather than a range -- "The MAX6126 requires
# an output capacitor between 0.1uF and 10uF" -- and then recommends "a 10uF
# capacitor in parallel with a 0.1uF capacitor" for loads that switch, which is
# 10.1 uF and so slightly over its own ceiling. Read together, the 10 uF bounds
# the *bulk* capacitor and not the summed total including local decouplers.
#
# reference_load() computes what is fitted and verify.check_reference_load()
# holds it against the range, read off the *exported netlist* rather than off
# these constants -- so a fourth capacitor drawn onto VREF fails even though
# nothing here changed.
VREF_CLOAD_MIN_F = 0.1e-6
VREF_CLOAD_MAX_F = 10e-6

# The capacitors on VREF, as value/float pairs -- STYLE.md rule 2, and they were
# inline literals in shared() until reference_load() needed to add them up. That
# is the rule earning its keep rather than being obeyed: the total was not a
# number anybody had, because the values were only ever strings sitting in
# separate calls, and the total was **20.1 uF against a 10 uF ceiling**.
#
# **C804 was here and has been deleted. `LOGIC_BULK` was its value pair.**
#
# It was a second 10 uF, at the '541 rather than at the reference, and it is what
# put the total at 2.01x the datasheet's capacitive-load stability range. Its
# justification -- floorplan.REFERENCE_PLACEMENT, which has been corrected --
# was "the reservoir the steady 684 uA comes out of, so U12's own loop never
# sees the load step when six channels change duty at the 8 kHz frame rate".
#
# **A capacitor cannot do that at 8 kHz, and no value of it could.** A load step
# divides between the reservoir and the part's own output impedance by
# impedance, and at 8 kHz those are 1.99 ohm and 0.028 ohm -- the max
# load-regulation figure, 28 uV/mA. The reservoir supplies 1.4% of the step and
# the reference supplies the rest; 10 uF only becomes the stiffer of the two
# above 568 kHz. The clause described a mechanism that runs the other way.
#
# It also did not need doing. reference_load() carries the arithmetic: the step
# is 19 uV on VREF, which is -143 dB of AM after the CV filter's 59.9 dB at
# 8 kHz, against a -54 dB requirement.
#
# **What survives is the sense decision, and it was never the same question.**
# "Locate the output capacitor as close to OUTF as possible" and "bring a line
# from OUTS to join the line from OUTF, at the point where the voltage accuracy
# is needed" are the two halves of force and sense, not a choice between two
# places to put a capacitor -- the bulk capacitor stabilises the amplifier at its
# output, the sense line closes at the load so the loop corrects the drop in
# between. Reading them as a trade-off is what made this look undecidable for a
# session; they are complementary and the answer is forced. The sense pair still
# closes at the '541, now at C803.
VREF_RESERVOIR = "10u/16V X7R"          # C802, at OUTF: the required output cap
VREF_RESERVOIR_FARADS = 10e-6
LOGIC_LOCAL = "100n/50V X7R"            # C803, at the Vcc pin, where OUTS meets OUTF
LOGIC_LOCAL_FARADS = 100e-9

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

# Which SSI2164 and which of its four cells carries channel n. 3 + 3, per
# allocation(): every string gets two die-mates instead of one string getting
# three and another getting one.
#
# Declared beside the pin map rather than beside SECTIONS, where it used to sit,
# because NO_CONNECT names the spare cell's control pin and NO_CONNECT is
# earlier in the file. Which is a small thing and worth a sentence: a constant's
# position in a module is a dependency edge, and this one only pointed the wrong
# way because nothing had asked the question yet.
VCA_PACKAGES_REFS = ("U9", "U10")
VCA_CELL = {n: (VCA_PACKAGES_REFS[(n - 1) // 3], ((n - 1) % 3) + 1)
            for n in range(1, CHANNELS + 1)}
VCA_SPARE_CELLS = {ref: 4 for ref in VCA_PACKAGES_REFS}

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
LOGIC_REF = "U11"

# **RELAY_PINS was here and is deleted with the pad it belonged to.** It held
# the IEC 60947 contact numbers -- 11/12/14 for pole 1 as common /
# normally-closed / normally-open, 21/22/24 for pole 2, A1-A2 and B1-B2 for the
# set and reset coils of a dual-coil latching part -- and what it committed the
# design to was not a relay but a *constraint on which relay could be fitted*,
# since plenty of signal relays follow that numbering and plenty do not
# (Panasonic's TQ2 numbers sequentially round the package).
#
# It was good work on a part that should not be on this board, and the note
# survives it for one reason: **the deferred bypass relay will face the same
# question**, and it is worth knowing that a pin map can be pinned before a
# part is chosen, by naming the standard rather than the manufacturer. The
# numbers themselves are not carried forward, because the bypass relay is a
# different animal -- one pole, held de-energised at power-up per section 4.5 --
# and a pin map copied from a dual-coil latching DPDT would be a reading that
# nobody read.
#
# MAX6126, 8-pin SO/uMAX. **Read first-hand from Maxim's own PDF** -- document
# 19-2647, Rev 8, 6/16 -- page 1's Pin Configuration and page 16's Pin
# Description table. Analog Devices' own URL still times out; the copy that
# resolved is Digi-Key's mirror of the same document, and it is the PDF rather
# than a scrape of it:
#
#   https://media.digikey.com/pdf/Data%20Sheets/Maxim%20PDFs/MAX6126_Rev8_1-5-117.pdf
#
# **This map was previously read from a text mirror, and the mirror was right.**
# Every one of the eight is confirmed. That is worth writing down rather than
# quietly upgrading the provenance, because the interesting part is what the
# repo said about it in the meantime: three separate comments and the whole
# ASSUMPTIONS.md entry said the map "has not been read" and that U12's pins were
# still roles like `<VIN>`, long after this dict held numbers. The stale claims
# outnumbered the true one 3:1 and no check could see the difference, because a
# comment is not an instrument. See gen_assumptions.py for the entry that
# replaced it.
#
# Verbatim, page 16:
#
#   1     NR      "Noise Reduction. Connect a 0.1uF capacitor to NR. Leave
#                  unconnected if not used."
#   2     IN      "Positive Power-Supply Input"
#   3     GND     "Ground"
#   4     GNDS    "Ground-Sense Connection. Connect to ground connection at
#                  load."
#   5, 8  I.C.    "Internally Connected. Do not connect anything to these pins."
#   6     OUTS    "Voltage Reference Sense Output"
#   7     OUTF    "Voltage Reference Force Output. Short OUTF to OUTS as close
#                  to the load as possible. Bypass OUTF with a capacitor
#                  (0.1uF to 10uF) to GND."
#
# **It is a Kelvin-sensed part, which is not how spec section 4.2 assumes it is
# wired.** OUTF *forces* and OUTS *senses*; GNDS is the matching ground sense.
# That is four connections where the spec implies two, and it decides where the
# reference sits relative to the '541 -- the sense pair has to close at the load,
# which is C803 at the '541's Vcc pin, not at the package. The datasheet is
# explicit about the ground leg too, page 16: "Connect the load to ground and
# bring a connection from GNDS to exactly the same point."
#
# **This is a separate question from where the bulk capacitor goes, and reading
# the two as one is what stalled the C804 decision.** "Locate the output
# capacitor as close to OUTF as possible" is about loop stability at the
# amplifier; closing OUTS at the load is about correcting the IR drop in the
# trace between them -- 97 mohm x 682 uA = 66 uV here, the largest error in the
# block and the only one force and sense removes. Both, at different places, is
# the arrangement. See VREF_RESERVOIR.
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
    "power:GNDA": ("power", "power", "GNDA", None),
    "power:GNDD": ("power", "power", "GNDD", None),
    "power:PWR_FLAG": ("power", "power", "PWR_FLAG", None),
}

# Which unit of the quad carries the supply pins. TL074 puts the four
# amplifiers on units 1-4 and V+/V- alone on unit 5.
OPAMP_POWER_UNIT = 5


def _set_property(definition, key, value):
    for item in definition:
        if (isinstance(item, list) and str(item[0]) == "property"
                and item[1] == key):
            item[2] = value


def _repin(definition, number, kind, name=None):
    """Change a pin's electrical type, and its name if given, in place.

    Lifted in shape from the mixer's own `_repin`, which exists because the
    ICL7660S differs from the ICL7660 by one pin. Walks unit bodies rather than
    the top level, because that is where pins live once a symbol is flattened.
    """
    for unit in definition:
        if not (isinstance(unit, list) and str(unit[0]) == "symbol"):
            continue
        for pin in unit:
            if not (isinstance(pin, list) and str(pin[0]) == "pin"):
                continue
            if not any(isinstance(x, list) and str(x[0]) == "number"
                       and str(x[1]) == str(number) for x in pin):
                continue
            pin[1] = type(pin[1])(kind)
            for item in list(pin):
                if isinstance(item, list) and str(item[0]) == "name" and name:
                    item[1] = name
                elif isinstance(item, list) and str(item[0]) == "hide":
                    pin.remove(item)


def patch_symbol(lib_id, definition):
    """Correct a borrowed symbol's properties and pin types, in place.

    Lives here rather than in gen_sch.py because gen_project.py writes the
    project library through the same function, and the mixer's own
    gen_project.symbol_library() says why: the schematic embeds a copy of every
    symbol, so a library patched differently passes ERC, passes verify.py, and
    surfaces only as a mismatched library when a human opens the project.

    Three parts, and two of the three pin-type corrections were found by ERC
    rather than by reading -- which is the argument for running ERC on a
    half-drawn sheet instead of waiting for it to be finished.

    **MAX6126 OUTF is a power output, not an output.** It was `output`, and
    that is wrong by exactly the thing that makes this design unusual: the
    '541's Vcc runs off the reference, so OUTF is the pin that powers a chip.
    Declared as a plain output, ERC reported the '541's Vcc as an input power
    pin driven by nothing, and the previous answer to that was a PWR_FLAG on
    VREF -- a second driver on a driven net, which ERC also objected to. One
    pin type states the fact and both complaints go.

    **SSI2164 I_OUT is passive, not an output.** A Blackmer core's output is a
    current into a virtual earth: it cannot drive a voltage, and page 5's
    instruction for an unused channel is to *ground* input and output, which is
    not something a voltage output tolerates. As `output` it made the two spare
    cells' grounded I_OUT4 pins a two-driver conflict with each other and with
    MAGND's own power flag. `passive` is what the pin is.
    """
    if lib_id.endswith(":OPA1644"):
        _set_property(definition, "Datasheet",
                      "https://www.ti.com/lit/ds/symlink/opa1644.pdf")
        _set_property(definition, "Description",
                      "Quad JFET audio op-amp, 3.3 nV/rtHz, SOIC-14")
    elif lib_id.endswith(":MAX6126"):
        # The URL that was here pointed at Analog Devices' product page, which
        # nothing in this project has ever successfully fetched -- ORDER_CODES'
        # own rule is that a datasheet URL is one that "has been fetched and seen
        # to resolve", and by that rule it did not qualify. This one did, and it
        # is the document REF_PINS was read from.
        _set_property(definition, "Datasheet",
                      "https://media.digikey.com/pdf/Data%20Sheets/"
                      "Maxim%20PDFs/MAX6126_Rev8_1-5-117.pdf")
        _set_property(definition, "Description",
                      "2.5 V ultra-low-noise reference, Kelvin-sensed, SOIC-8")
        for name, kind in (("NR", "passive"), ("GND", "power_in"),
                           ("GNDS", "passive"), ("OUTS", "passive"),
                           ("OUTF", "power_out"), ("IN", "power_in")):
            _repin(definition, REF_PINS[name], kind, name=name)
    elif lib_id.endswith(":SSI2164"):
        _set_property(definition, "Description",
                      "Quad current-in/current-out VCA, Blackmer core, SOP-16")
        for cell in VCA_CHANNEL_PINS.values():
            _repin(definition, cell["IOUT"], "passive")
    return definition

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
# **Empty, and it is the pad's deletion that emptied it.** Its one entry was
# the dual-coil latching relay: a part the spec asks for by function, does not
# name, and section 6 forbids inventing. The dict and the two checks that read
# it stay, because the deferred blocks will refill it -- the DC-DC, the ADC and
# the bypass relay are all named by function and not by part -- and because an
# empty declaration is a different statement from a missing one.
UNSPECIFIED = {}

# Pins deliberately left unconnected, declared beside the circuit rather than
# buried in the checker -- the mixer's NO_CONNECT, same argument.
REF_REF = "U12"
NO_CONNECT = tuple(
    (REF_REF, str(REF_PINS[name])) for name in ("IC1", "IC2")
) + tuple(
    # The '541's two unused *outputs*. Its unused inputs are held at MAGND
    # below, per page 4 note 1, and an output cannot be: tying a driven output
    # to ground is a short through the driver. So the inputs get a potential and
    # the outputs get a flag, which is the only pairing that is right at both
    # ends. Found by ERC, which is the one instrument that looks at pins rather
    # than at nets and is why it is worth running on a partial sheet.
    (LOGIC_REF, str(LOGIC_Y[n])) for n in (7, 8)
) + tuple(
    # MODE open is Class AB -- SSI2164 page 3, and it is a decision, not an
    # omission. The spare cell's control pin may float: page 5, "Control pins
    # can be left open or grounded", where the same sentence requires its input
    # and output to be *grounded*, which they are.
    #
    # Both were flagged on the schematic and declared nowhere. That is the same
    # drift as the invented coil nets with the sign reversed -- the drawing
    # deciding something for the design -- and it is why the flags are now
    # emitted from this tuple rather than written where the part is placed.
    (ref, str(pin))
    for ref in VCA_PACKAGES_REFS
    for pin in (VCA_PINS["MODE"], VCA_CHANNEL_PINS[VCA_SPARE_CELLS[ref]]["VC"])
)

# Pins this pass does not connect *and must not be read as finished*.
#
# **A no-connect flag and a deferred connection are different claims and the
# sheet cannot tell them apart.** KiCad has exactly two states for a pin --
# connected, or flagged unconnected -- so a coil pin waiting on a driver that is
# not drawn yet has to borrow the flag that means "deliberately open". That is
# the shape of mistake this repository keeps finding: an instrument that passes
# while covering less than its name. NO_CONNECT above is permanent and this is
# not, and the two are separated here so that a check can count the second and
# a build can refuse to fabricate while it is non-empty.
#
# **It is empty now, and what emptied it is the pad going rather than the relay
# driver landing.** All 48 entries were the twelve relays' 24 coils. The
# distinction the dict exists to make is unchanged and check_open_pins() still
# holds it in both directions -- a pin open on the sheet and declared nowhere is
# a forgotten wire either way.
#
# Two things it recorded are worth keeping, because they are what the pad's
# removal makes moot and they should not come back with the next relay.
#
# The sheet wired every coil's SET-/RESET- to MDGND and labelled SET+/RESET+ out
# to nets that existed nowhere else -- 24 global labels on 24 one-pin nets,
# which KiCad reported as `isolated_pin_label` and nothing here read. It was
# wrong twice: the coil nets were invented in the *drawing*, which is the one
# direction STYLE.md rule 1 forbids, and a grounded low side is backwards for
# the open-drain sink section 4.5 specifies -- a sink drives the coil's low
# side, so the low side belongs to the driver's drain and the high side to a
# coil supply. A relay that never transfers, from a sheet that draws as correct.
#
# And section 4.5's coil count never closed. "12 coils (six 2-bit pads)" driven
# by "2 x TPIC6B595" is 16 outputs; twelve coils means twelve *single*-coil
# latching relays, which latch by reversing coil polarity and need a bridge
# rather than a sink. With the dual-coil part section 4.1 asks for it is 24
# coils and 3 x TPIC6B595 exactly. **That contradiction is now resolved by
# subtraction rather than by choosing a side**, and the coil supply rail that
# RAILS never had is not needed after all.
DEFERRED_PINS = {}
DEFERRED = {
    "envelope rectifier": "the smoothing time constant is not derivable -- "
                          "spec section 4.4 gives a sampling rate and no "
                          "attack/release target. The tap net BUF{n} exists "
                          "and is driven; the rectifier hangs off it.",
    "controller": "RP2040 and its QSPI flash, crystal, USB and MIDI: shared "
                  "block, and the scope statement puts shared blocks after "
                  "one channel is complete.",
    "envelope ADC": "ADS131M08 or MCP3564, undecided in spec section 4.4.",
    # "relay drive" was here -- 2 x TPIC6B595 and the 74LVC1G123 one-shot,
    # section 4.5. It existed only to drive the coarse pad's coils and goes
    # with it. Section 4.5 calls the one-shot's absence "the
    # highest-probability field failure in the design", which was true and is
    # now a failure this board cannot have.
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

        A part whose pins are still roles rather than numbers is a legitimate
        state for a *design* to be in and not for a *board*, so the two are
        separated here rather than conflated: a pin written as a role --
        `<COM_A>` -- is allowed only on a part that UNSPECIFIED names and
        explains, and is an error anywhere else.

        **Nothing triggers it at the moment**, because the pad relay was the
        only unspecified part and it is gone. That is a check with nothing to
        catch rather than a check that cannot fail: the deferred DC-DC, ADC and
        bypass relay are all named by function, and the first one drawn brings
        the state back.

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
# The one genuinely spare section, and it needs terminating rather than leaving.
# OPAMP_NEEDED counts 31 of the 32 available; six of the seven that this pass
# does not draw are U2/U4/U6 C and D, reserved above for the six envelope
# rectifiers and DEFERRED with them. U8 D is the remainder, and an unused JFET
# section with floating inputs is not neutral: it sits against a rail, draws
# more than its share of the supply and couples back through the die it shares
# with the reference inverter and two CV filters. Wired as a unity follower with
# its input at MAGND, which is the standard answer and costs no parts.
SECTIONS[("spare", 0)] = ("U8", "D")
OPAMP_PACKAGES = sorted({pkg for pkg, _ in SECTIONS.values()},
                        key=lambda r: int(r[1:]))


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
        f"CPL{_n}": 0.0, f"IIN{_n}": 0.0, f"RCJ{_n}": 0.0,
        f"IOUT{_n}": 0.0, f"SVN{_n}": 0.0, f"SRV{_n}": (-MODULE_RAIL,
                                                        MODULE_RAIL),
        f"CVX{_n}": (0.0, VREF), f"CVN{_n}": 0.0,
        f"VC{_n}": (0.0, VREF), f"LOGO{_n}": (0.0, VREF),
        f"PWM{_n}": (0.0, 3.3),
    })
    # PS{n}A-D and PSEL{n}X/Y were here: the pad's four resistor tails and the
    # two selector nodes between its relays. Six nets a channel, thirty-six in
    # all, gone with it.

# The reference inverter's virtual earth, held at MAGND by feedback.
NET_DC["RINV"] = 0.0
# The spare section's own output, shorted to its own inverting input. 0 V
# because its non-inverting input is at MAGND and it is a follower.
NET_DC["SPARE"] = 0.0
# The reference's noise-reduction pin. Still a range rather than a number, and
# **the reason has been corrected**: it said "because the MAX6126's pin map has
# not been read in this session -- see UNSPECIFIED", which was wrong twice over.
# The map had been read (see REF_PINS, now confirmed first-hand), and the
# MAX6126 is not in UNSPECIFIED and never has been in this form -- that
# cross-reference pointed at nothing, which is the kind of dangling citation
# STYLE.md rule 10 is about.
#
# The range is right for a different and better reason. The datasheet describes
# NR functionally -- "Noise Reduction. Connect a 0.1uF capacitor to NR" -- and
# **publishes no voltage for it at all.** It is an internal node brought out to
# be bypassed, so what it sits at is not a fact the datasheet offers, and
# bounding it by the rails it lives between is the honest declaration. That is
# enough for the polarity and rating checks C801 needs and it is not a reading.
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

    The order is the signal: socket, front end, coupling, R_IN, VCA, I-V,
    servo, back to the socket. The CV filter is built alongside because it
    lands on the same VCA cell.
    """
    package, unit = SECTIONS[("front", n)]
    out, inverting, non_inverting = OPAMP_UNITS[unit]

    # The loom connector. **Two ways, and it used to say three.** The comment
    # here read "three ways, mirroring the mixer's own RV{n}01 order so a
    # builder reads the same 1/2/3 at both ends. Pin 3 is RET{n} and not
    # ground", which described the difference-amplifier front end that went with
    # constraint 2's struck second sentence -- see FRONT_R. There is no RET{n}.
    # The pair is PIN{n} and SIN{n}; the mixer's pin 3 takes the shield, which
    # lands at that end only and has no pin here.
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
    # control feedthrough". Its corner with R_IN is 1.32 Hz and used to move
    # with the pad step, down to 0.16 Hz at 97k6; it is one number now.
    _capacitor(design, f"C{n}01", VCA_INPUT_BLOCK, f"BUF{n}", f"CPL{n}",
               footprint=C_FILM_FP,
               description=f"Channel {n} VCA input block -- control feedthrough")

    # R_IN. One resistor, and the four-plus-two-relays that were here are in
    # pad_benefit(). CPL{n} is the coupling node -- it was PADI{n}, the pad's
    # input, and a net named after a block that no longer exists is a fossil
    # the next reader has to date.
    _resistor(design, f"R{n}11", VCA_RIN, f"CPL{n}", f"IIN{n}",
              description=f"Channel {n} R_IN -- unity with R{n}21")

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

    Everything else -- controller, ADC, envelope rectifier, fail-safe, supply --
    is in DEFERRED with a reason. What is here is the minimum the six channels
    need in order for section 5 to be checkable at all. The relay drive was a
    sixth and is not deferred but deleted, with the pad it drove.
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

    # The spare section, terminated. See SECTIONS[("spare", 0)] for why an
    # unused JFET section is not free. Output to its own inverting input, input
    # at MAGND: a follower sitting at 0 V, with no external part.
    package, unit = SECTIONS[("spare", 0)]
    out, inverting, non_inverting = OPAMP_UNITS[unit]
    design.connect("SPARE", (package, out), (package, inverting))
    design.connect("MAGND", (package, non_inverting))

    # The reference itself. Pins by number, from REF_PINS, which is now confirmed
    # against Maxim's own PDF -- this line said "Pins by role, because its map has
    # not been read" while every connection below was already a number.
    design.add(Part(REF_REF, VREF_PART, SOIC8_FP,
                    description="2.5 V band-gap reference, 45 nV/rtHz with "
                                "C_NR; Kelvin-sensed, OUTF/OUTS shorted at "
                                "C803; also feeds the ADC"))
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
    _capacitor(design, "C802", VREF_RESERVOIR, "VREF", "MAGND",
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
    # The only capacitor at the '541, and the only one that has a job a capacitor
    # can do: the PWM edges. Six arriving together dump 630 pC into it for 6.3 mV
    # of sag, which the CV filter puts 83.1 dB down -- -116 dB of AM, or -132 dB
    # with the phase stagger spec section 4.2 asks for. It has to be *at the pin*,
    # inside the trace inductance, because nothing 20 mm away serves a 5 ns edge
    # at any value. C804's 10 uF sat beside it and is gone; see VREF_RESERVOIR.
    _capacitor(design, "C803", LOGIC_LOCAL, "VREF", "MAGND",
               description="'541 local decoupling and the Kelvin closure -- at "
                           "the package, where OUTS joins OUTF")
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


def reference_load():
    """What hangs on OUTF, against the datasheet's stability range.

    Two capacitors, 10.1 uF, inside the 0.1 to 10 uF the datasheet qualifies:

        C802  10 uF    the required output capacitor, at OUTF
        C803  100 nF   local decoupling at the '541's Vcc pin, and the Kelvin
                       closure
                       -------
                       10.1 uF, which is page 16's own recommendation for a
                       switching load: "a 10uF capacitor in parallel with a
                       0.1uF capacitor"

    **It was 20.1 uF, and C804 was deleted to get here.** The ceiling is a
    stability limit rather than a guideline -- page 4's "Capacitive-Load
    Stability Range", qualified "no sustained oscillations" -- and an unstable
    reference is the '541's Vcc and therefore all six channels' full scale at
    once. 10.1 uF against a 10 uF limit is the datasheet's own arithmetic, the
    100 nF being 1% of a 10 uF part whose tolerance is +/-10% anyway; 20.1 uF is
    a second bulk capacitor and is not.

    **Why C804 and not C802, derived rather than chosen.** C804's justification
    was that it was "the reservoir the steady 684 uA comes out of, so U12's own
    loop never sees the load step when six channels change duty at the 8 kHz
    frame rate". That is not a thing a capacitor of that size can do at that
    frequency. A load step divides between the reservoir and the part's own
    output impedance in inverse proportion to impedance, and at 8 kHz:

        10 uF                        1.99 ohm
        MAX6126 load regulation      0.028 ohm    (28 uV/mA, the datasheet MAX)
                                     ---------
        reservoir's share of the step  1.4%

    So the reference supplied 98.6% of the step it was being shielded from, and
    10 uF only becomes the stiffer of the two above 568 kHz. Nor did the step
    need shielding: 682 uA x 0.028 ohm is 19 uV on VREF, the CV filter is
    -59.9 dB at 8 kHz, so 19 nV reaches Vc and at dg/g = 3.49/V that is -143 dB
    of AM against a -54 dB requirement.

    What a capacitor *can* do there is serve the PWM edges, and that needs 100 nF
    at the pin rather than 10 uF across the board -- nothing 20 mm away serves a
    5 ns edge. C803 does it: 630 pC from six simultaneous edges is 6.3 mV of sag,
    -83.1 dB through the filter, -116 dB of AM, or -132 dB with the phase stagger
    spec section 4.2 asks for.

    **And the Kelvin decision was never the same question**, which is what made
    this look like a trade for a session. "Locate the output capacitor as close
    to OUTF as possible" and closing OUTS at the load are the two halves of force
    and sense: the capacitor stabilises the amplifier at its output, the sense
    line closes at the load so the loop corrects the drop between them --
    97 mohm x 682 uA = 66 uV, the largest error in the block and the only one
    force and sense removes. Both, at different places. The sense pair still
    closes at the '541; it closes at C803 now instead of C804.

    verify.check_reference_load() holds the range against KiCad's exported
    netlist rather than against this function, so a capacitor drawn onto VREF
    fails even when nothing in design.py changed.
    """
    fitted = {"C802": VREF_RESERVOIR_FARADS, "C803": LOGIC_LOCAL_FARADS}
    # Cross-checked against the netlist, so a capacitor added to VREF cannot be
    # left out of the total by being left out of this dict.
    on_vref = {ref for ref, _ in NETS["VREF"] if ref.startswith("C")}
    assert on_vref == set(fitted), (
        f"VREF carries {sorted(on_vref)} and reference_load() knows the value of "
        f"{sorted(fitted)} -- add the pair and re-read the stability range")
    return dict(classify_reference_load(fitted),
                # What the deleted reservoir was for, and what it could actually
                # have contributed to it. Numbers, so the argument stays runnable.
                step_amps=CHANNELS * VREF / CV_R1_OHMS,
                part_ohms=0.028,
                reservoir_share_at_8k=(
                    0.028 / (0.028 + 1 / (2 * math.pi * 8e3 * 10e-6))),
                reservoir_wins_above_hz=1 / (2 * math.pi * 0.028 * 10e-6))


def classify_reference_load(fitted):
    """Bulk and local, and whether that is a configuration the datasheet shows.

    **A naive total is the wrong test and getting it wrong the first time is
    instructive.** Summing everything on the net gives 10.1 uF against a 10 uF
    ceiling and reports a fault -- but 10.1 uF is *page 16's own recommendation*:
    "it is advantageous to use a 10uF capacitor in parallel with a 0.1uF
    capacitor". A check that fails on the datasheet's own worked example is
    measuring the wrong thing.

    What the datasheet actually describes is a topology, and it is expressible
    entirely in the datasheet's own two numbers:

      * **one** output capacitor, between VREF_CLOAD_MIN_F and
        VREF_CLOAD_MAX_F, as close to OUTF as possible;
      * optionally a capacitor *at* the floor value in parallel with it, which is
        what the recommendation adds and what local decoupling at a logic pin is.

    So a capacitor larger than the floor is bulk and there may be exactly one of
    it; a capacitor at or below the floor is a local and may be repeated. No
    threshold is invented -- 0.1 uF is the datasheet's floor and also the value of
    the parallel capacitor it recommends, which is why the one number serves for
    both.

    That distinction is what separates the fault from the fix. Two 10 uF is two
    bulk capacitors, 2x the qualified load, and no reading of the datasheet
    sanctions it. One 10 uF plus a 100 nF is 10.1 uF and is printed in it.
    """
    # `>` is not safe on the boundary and the boundary is where the fitted part
    # sits. kisim.magnitude("100n/50V X7R") returns 1.0000000000000001e-07, which
    # is greater than 1e-7 by one part in 1e16, so C803 classified as *bulk* on
    # the first run and the check reported three bulk capacitors where there is
    # one. A tolerance of 1e-6 is a million times tighter than any capacitor
    # tolerance and a billion times looser than the float noise.
    def is_local(farads):
        return (farads < VREF_CLOAD_MIN_F
                or math.isclose(farads, VREF_CLOAD_MIN_F, rel_tol=1e-6))

    bulk = {ref: farads for ref, farads in fitted.items()
            if not is_local(farads)}
    local = {ref: farads for ref, farads in fitted.items()
             if is_local(farads)}
    total = sum(fitted.values())
    problems = []
    if len(bulk) > 1:
        problems.append(
            f"{sorted(bulk)} are all larger than the {VREF_CLOAD_MIN_F * 1e6:g} uF "
            f"floor, so VREF carries {len(bulk)} bulk capacitors totalling "
            f"{sum(bulk.values()) * 1e6:.1f} uF -- the part is qualified for one, "
            f"of at most {VREF_CLOAD_MAX_F * 1e6:g} uF")
    for ref, farads in sorted(bulk.items()):
        if farads > VREF_CLOAD_MAX_F:
            problems.append(
                f"{ref} is {farads * 1e6:.1f} uF, above the "
                f"{VREF_CLOAD_MAX_F * 1e6:g} uF capacitive-load stability ceiling")
    if total < VREF_CLOAD_MIN_F:
        problems.append(
            f"VREF carries {total * 1e6:.3f} uF and the datasheet requires an "
            f"output capacitor of at least {VREF_CLOAD_MIN_F * 1e6:g} uF")
    return {"fitted": fitted, "bulk": bulk, "local": local,
            "total_farads": total, "ceiling_farads": VREF_CLOAD_MAX_F,
            "floor_farads": VREF_CLOAD_MIN_F, "problems": problems,
            "in_range": not problems}


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

    print("the VCA input, one fixed R_IN and no pad")
    p = vca_input()
    print(f"  R_IN = R_OUT         {p['rin']:>8.0f} ohm  gain "
          f"{p['gain_db']:+.2f} dB, unity by construction")
    print(f"  I_IN at {p['peak']:.2f} V pk   {p['current'] * 1e6:>8.1f} uA   "
          f"{p['headroom_ratio']:.0f}x inside the 900 uA page 4 advises")
    print(f"  inside 7k5-100k?     {'yes' if p['in_range'] else 'NO':>8}      "
          f"and no longer bounded by a top pad step")
    print(f"  10u block corner     {p['block_corner']:>8.2f} Hz")
    print(f"  quieter than the recommended 20k by "
          f"{p['quieter_than_recommended_db']:.1f} dB; 7k5 would be "
          f"{p['quietest_would_gain_db']:.1f} dB quieter again "
          f"-- MEASURED['vca_rin']")
    a = allocation()
    print(f"  {a['packages']} packages, {a['per_package']} channels each: "
          f"{a['die_mates']} die-mates per string against "
          f"{a['alternative_die_mates']} at 4+2, {a['spare']} spare grounded")
    print()

    print("VCA noise, Class AB, and where the datasheet's rise actually lives")
    print(f"  conditions           {VCA_NOISE_CONDITION}")
    v = vca_noise(VCA_RIN_OHMS)
    print(f"  R_IN/OUT {VCA_RIN_OHMS:.0f}      {v['dbu']:>6.1f} dBu  "
          f"{v['rms'] * 1e6:>6.2f} uV rms  {v['density'] * 1e9:>5.1f} nV/rtHz")
    for rin in sorted(VCA_NOISE_DBU):
        row = vca_noise(rin)
        print(f"    datasheet {rin:>6.0f}  {row['dbu']:>6.1f} dBu"
              f"                  {row['density'] * 1e9:>5.1f}")
    fit = vca_cell_fit()
    print(f"  fitted: i_cell {fit['i_cell'] * 1e12:.2f} pA/rtHz at the cell's "
          f"*output*, x R_OUT")
    print(f"          e_fixed {fit['e_fixed'] * 1e9:.1f} nV/rtHz, R-independent "
          f"(the TL072 at NG 2 is "
          f"{fit['amp_at_noise_gain_2'] * 1e9:.0f})")
    print(f"          residual {fit['rms_db']:.2f} dB rms over four points read "
          f"to the nearest dB")
    print(f"          plausibility: full shot noise on "
          f"{fit['shot_equivalent_amps'] * 1e6:.0f} uA")
    print()

    print("the 2-bit coarse pad, priced against the control port that replaces it")
    b = pad_benefit()
    print("  step     R_IN     pad cell    Vc cell (out/in-referred)   pad buys")
    for row in b["rows"]:
        print(f"  {row['db']:>+5.0f} dB {row['rin']:>7.0f}  "
              f"{row['pad_cell'] * 1e9:>6.2f} nV   "
              f"{row['control_cell'][0.0] * 1e9:>6.2f} / "
              f"{row['control_cell'][1.0] * 1e9:>6.2f} nV      "
              f"{row['benefit_db'][0.0]:>+5.2f} .. "
              f"{row['benefit_db'][1.0]:>+5.2f} dB")
    print(f"  THD says the same: A_V = -20 dB is "
          f"{b['thd_attenuated'] * 100:.3f} % at full input against "
          f"{b['thd_unity'] * 100:.3f} % at unity")
    print(f"  and the control port has {b['cv_span_db']:.1f} dB of span for the "
          f"{-b['deepest_step_db']:.0f} dB, for no parts")
    print(f"  the pad would have bought {b['tempco_saved_db']:.1f} dB of tempco "
          f"wander on the deepest step -- see tempco_span(), which declines to "
          f"compensate more")
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
