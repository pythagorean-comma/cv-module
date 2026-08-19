"""One channel of the per-string CV module, as derived values.

Values only, in this pass. The netlist, the five constraint checks and the
board follow; this file is where every number gets its arithmetic, because a
schematic full of plausible values is worse than an incomplete one -- it looks
finished.

    from the mixer's RV{n}01 socket
      PIN{n} --[ 10k ]--+-- inverting unity front end --+-- |x| --[ 4.7 ms ]--> ENV{n}
       (pin 1)          |          (Rf 10k)             |   (2 amps, 2 diodes)
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
# The fabrication rules, because whether a package can be *routed* is a design
# input and not a layout detail -- see controller_package(). rules.py imports
# nothing but math, which is what makes this safe at the top of the chain.
import rules

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

    "env_opamp_iq": Assumption(
        value=2.5, units=" mA/amplifier, TL074 quiescent, maximum",
        low=1.125, high=2.8,
        question="What is the plain TL074's maximum quiescent current per "
                 "amplifier? SLOS080W is a combined TL071/72/74 document and "
                 "the pages walked in this session carry the TL07x*H* grade "
                 "(937.5 uA typ, 1125 uA max); the plain grade's own row was "
                 "not located. The 1.4 mA typical this repo carries is "
                 "unsourced.",
        sets="8 amplifiers of the 40 on VA+/VA-, so about 8 mA on a rail "
             "supply_load() puts at 110 mA maximum",
        when_wrong="The bipolar rails move by at most 11 mA either way, which "
                   "is inside any sensible margin on a DC-DC that has not been "
                   "chosen. It is declared rather than resolved because a "
                   "supply sized on an invented maximum is exactly what "
                   "section 6 forbids, and because fitting the H grade -- "
                   "which is read -- would settle it by choosing a part."),

    "mcu_rail_ma": Assumption(
        value=52.1, units=" mA on 3.3 V, RP2040 alone, maximum average",
        low=19.2, high=52.1,
        question="What does the RP2040 draw on the 3.3 V side in *this* "
                 "application? Its datasheet's Table 637 measures four use "
                 "cases rather than specifying a maximum, and none of them is "
                 "this one: 'Popcorn' is VGA video at 48 MHz and is the "
                 "heaviest at 52.1 mA (DVDD 16.6 + IOVDD 35.5, worst-case "
                 "device over temperature), 'BOOTSEL idle' the lightest active "
                 "at 19.2 mA. This board runs 125 MHz with almost no IO "
                 "activity -- six PWM at 30.5 kHz, one 10.4 MHz clock -- and "
                 "XIP from flash, which Table 635 prices at 37.6 uA/MHz on "
                 "DVDD and which firmware can retire by running from SRAM. "
                 "The range is the datasheet's own measurements; the value is "
                 "its top.",
        sets="nothing, and that is the point -- controller_supply() shows the "
             "linear V3V3 chain fails at both ends of this range and a "
             "switcher clears both, so no topology decision waits on it",
        when_wrong="Only the size of the switcher, not whether there is one. "
                   "The bound that decides is conservation of energy: a "
                   "converter's input current is at least vout/vin times its "
                   "output, so 3.3/12 x 52.1 = 14.3 mA against 35.4 mA of "
                   "+Vout headroom, and any efficiency above 40 % clears it. "
                   "Measuring this would size a part; it would not change the "
                   "topology. **Both halves of that held and the margin did "
                   "not.** The switcher is fitted and mcu_supply() counts the "
                   "rest of the rail -- the flash's 25 mA, the MIDI loop, the "
                   "opto, the pedal -- so the 14.3 mA floor is 23.6 mA and "
                   "the efficiency that clears it is 67 %, not 40. It still "
                   "fits and it is the tightest margin on this board."),

    # The one number the fitted switcher needs that its datasheet publishes
    # only as a curve.
    "mcu_dcdc_efficiency": Assumption(
        value=0.85, units=" fractional, TPS560430XF at 12 V in, 3.3 V out",
        low=0.75, high=0.92,
        question="What does U22 draw from VA_RAW at this board's real 3.3 V "
                 "load? SLVSE22B gives efficiency as figures rather than as a "
                 "table -- section 7.8's curves at 8, 12, 24 and 36 V in -- "
                 "and a number read off a plotted curve is not a reading. The "
                 "measurement is one ammeter in series with the switcher's "
                 "VIN pin.",
        sets="how much of the converter's remaining 35.4 mA of +Vout the "
             "controller costs, and that is the tightest budget on the board",
        when_wrong="**Only in one direction, and the threshold is computed "
                   "rather than assumed.** mcu_supply() states the efficiency "
                   "at which the +Vout budget stops closing -- about 67 % -- "
                   "and the range's floor is above it deliberately: a "
                   "synchronous buck at a quarter of its rated current does "
                   "not do worse than three quarters, and the FPWM version's "
                   "own penalty at light load is inside that. If the "
                   "measurement came back under 67 % the fix is not this "
                   "part: it is the 92.7 mA of relay coil that V5 makes "
                   "linearly from twelve volts, which is 37 % of +Vout and "
                   "the only load on this board large enough to matter."),

    # **The second efficiency, and it exists because the module carries a
    # converter this design does not choose.** It has the same shape as the
    # one above and it is worse in one specific way: the two multiply.
    # mcu_supply() shows the +Vout budget now closes on their *product*
    # against the same 67.8 % threshold, so a corner that each part clears
    # alone is not a corner the board clears.
    "pico_smps_efficiency": Assumption(
        value=0.91, units=" fractional, RT6150 at 4.7 V in, 3.3 V out, PWM",
        low=0.86, high=0.93,
        question="What does the Pico draw from VSYS at this board's load? "
                 "DS6150A/B-05 gives efficiency only as plotted curves -- the "
                 "'Buck-Boost 3.3V Efficiency, PS/SYNC = H' figure, which is "
                 "the forced-PWM one this design runs in -- and at 100 mA the "
                 "VIN = 3.3 V trace sits near 95 % with the 2.4 V trace about "
                 "three points under it. A number read off a plotted curve is "
                 "not a reading, and this one is read at a different inductor "
                 "from the module's. The measurement is one ammeter in series "
                 "with the Pico's VSYS pin, with GPIO23 high.",
        sets="together with mcu_dcdc_efficiency, whether the +Vout budget "
             "closes at all -- see mcu_supply()",
        when_wrong="**Both directions matter now, which is new.** The range's "
                   "floor is chosen so that the product with the other "
                   "assumption's floor is 0.660, and 0.678 is where the "
                   "budget stops closing -- so the pessimistic corner already "
                   "fails by 1.8 points and mcu_supply() says so rather than "
                   "rounding it away. Two levers, in order of cost: the relay "
                   "coils named above, and moving the module's own load off "
                   "the RT6150 by back-driving its 3V3 pin, which "
                   "pico_backdrive() prices and refuses on documentation "
                   "grounds rather than on arithmetic."),

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

    # The two the supply's isolation barrier turns on, and neither is on any
    # datasheet. Traco states the barrier's capacitance and its switching
    # frequency; what it cannot state is how hard the primary drives that
    # capacitance, because that is inside the potting.
    "dcdc_node_v": Assumption(
        value=40.0, units=" V pk-pk, flyback primary switching node",
        low=24.0, high=72.0,
        question="How large is the swing on the TMR 6WI's primary switching "
                 "node? A flyback's drain sits at Vin plus the reflected "
                 "output, so at a 12-18 V input the range below is 2x to 4x "
                 "the input -- read off what the topology permits, not off "
                 "the datasheet, which does not say.",
        sets="the common-mode current through the 50 pF barrier, and with it "
             "the size of the Y-capacitor",
        when_wrong="Linearly. barrier_return() scales with it, so the top of "
                   "the range is 5 dB worse than the value and the bottom is "
                   "4 dB better -- and the *fraction* returned locally does "
                   "not move at all, because it is set by two impedances. "
                   "What would change is whether the residual at the bond is "
                   "worth another part, and at every point in this range it "
                   "is not."),

    "inlet_loop_uh": Assumption(
        value=0.75, units=" uH, the loop the shared inlet closes",
        low=0.3, high=1.5,
        question="What is the inductance of the loop formed by the audio "
                 "ground bond, the mixer's own AGND/PGND star, and the two "
                 "inlet leads back to the shared barrel jack? It is a "
                 "property of how the box is wired, not of either board.",
        sets="the impedance of the bond the barrier's residual current is "
             "developed across",
        when_wrong="**Re-read after L801 was fitted, and it is a different "
                   "assumption now.** It used to be the *denominator of a "
                   "split* -- barrier_return() divided the barrier current "
                   "between C810 and this loop, so a smaller loop was a "
                   "worse result and the whole declared range mattered. The "
                   "choke puts 3.6 kohm in that denominator, so the split is "
                   "set by the part and not by the box: 0.3 and 1.5 uH give "
                   "the same 99.98 % local return to four figures. What is "
                   "left is a straight scale on the residual, because the "
                   "bond voltage is this impedance times a current that no "
                   "longer depends on it -- a factor of 5 across the range, "
                   "on 1.1 uV that is 42 dB under the mixer's own noise "
                   "floor. Every point in the range is inaudible and so is "
                   "every point outside it. The old clause named a choke as "
                   "the answer if the number went the wrong way; the choke is "
                   "fitted, so the question this assumption asks has stopped "
                   "being load-bearing and is kept because it is still "
                   "unmeasured."),

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

# OPA1644, named in spec section 4.2 for the CV filter.
#
# 32 sections and eight quads, with nothing left over: 6 front ends, 6 I-V,
# 6 servos, 6 CV filters, 6 envelope summing stages, one reference inverter and
# one spare terminated as a follower. The envelope block is what filled the
# last six -- they were reserved for it and the reservation was for one section
# per channel, which is a half-wave rectifier. ENV_FULL_WAVE wants two.
OPAMP = "OPA1644"
OPAMP_EN = 3.3e-9
OPAMP_SECTIONS = 4
OPAMP_NEEDED = 6 * 5 + 1 + 1          # +refinv, +the spare that is terminated
OPAMP_QUADS = -(-OPAMP_NEEDED // OPAMP_SECTIONS)

# The second op-amp, and it is a *second* rather than a replacement.
#
# **The note that used to sit here was half right and the wrong half was
# actionable.** It read: "The servo and rectifier sections do not need a
# 3.3 nV/rtHz JFET part and a cheaper quad would serve; that is a BOM
# optimisation and not a design change, and it is left until the BOM is
# costed." The BOM is costed now, the OPA1644 is both its largest line and out
# of stock at TI, and the obvious move was to put the servos on the cheap part
# too. **It is wrong for the servo**, and the reason is in this repo already:
# the servo's whole specification is its input offset -- servo_residual() says
# so, "a servo does not make DC small, it makes DC somebody else's offset" --
# and MEASURED["servo_vos"] declares a range of 0.05 to 3 mV. A TL074 is 3 mV
# typical and 10 mV maximum, which is the top of that range on a good day.
# Noise was the wrong axis to have judged it on.
#
# What does move is the rectifier's *first* stage, and it moves for a second
# reason as well as price. A1's output slews across two diode drops at every
# zero crossing, up to about a thousand times a second on the top string --
# the hardest edge anywhere in the analogue domain except the '541 -- and the
# rule at SECTIONS is that a switching thing does not share a die with an audio
# front end. So stage A goes on its own packages, and stage B, whose output is
# already filtered by ENV_R x ENV_C, takes the six precision sections that were
# reserved for the block. That also puts the low offset where it is worth
# something: A2's offset is the floor of the whole detector, see
# envelope_balance().
#
# TL074: the same 14-pin quad pinout the OPA1644 borrows its symbol from,
# checked pin by pin in LIBS already, and the part the SSI2164's own datasheet
# uses in the position this one occupies (Figure 1, "1/2 TL072"). 3 mV of
# offset is -52 dB against the mixer's clipping_peak(), which is the detector's
# floor and not the audio path's.
ENV_OPAMP = "TL074"
ENV_OPAMP_EN = 18e-9                  # nV/rtHz at 1 kHz, and it never reaches audio
ENV_OPAMP_VOS = 3.0e-3                # typical; 10 mV maximum
ENV_SECTIONS_NEEDED = CHANNELS
ENV_QUADS = -(-ENV_SECTIONS_NEEDED // OPAMP_SECTIONS)
ENV_PACKAGES_REFS = tuple(f"U{13 + i}" for i in range(ENV_QUADS))

# The audio-path quads, U1 to U8. Declared beside the envelope's own tuple
# because supply_load() counts packages off the netlist and needs to know which
# refs are quads rather than inferring it from a prefix.
OPAMP_PACKAGES_REFS = tuple(f"U{1 + i}" for i in range(OPAMP_QUADS))

# Spec section 1.1's rule, as a number: |f_module - 45 kHz| > 20 kHz because the
# mixer already runs a 45 kHz charge pump and a VCA is a multiplier, so two
# supply ripples intermodulate into the audio band. That gives f > 65 kHz; the
# target the decision settles on is 300 kHz, which puts the beat at 255 kHz and
# is easy to filter. See docs/supply-decision.md section 2.
SUPPLY_MIN_KHZ = 300.0

# MAX6126 supply current, from the datasheet REF_PINS was read out of
# (19-2647 Rev 8): 400 uA typ, 550 uA max, no load. Small against three relay
# coils and counted rather than dropped, because "small" is a judgement and a
# sum is not.
VREF_SUPPLY_MA = (0.4, 0.55)


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
# The envelope detector, which the spec said could not be derived
# ---------------------------------------------------------------------------

# Spec section 4.4 asks for "six precision rectifiers -> RC -> external SPI ADC"
# and gives a sampling rate and no time constant. This repo carried the block in
# DEFERRED with the reason "the smoothing time constant is not derivable -- spec
# section 4.4 gives a sampling rate and no attack/release target", and README
# listed it as waiting on a musical decision.
#
# **That is true of the detector the phrase imagines and false of the one this
# instrument needs.** "Attack and release" are the two halves of an *asymmetric*
# detector -- fast up, slow down -- and asymmetry is a musical preference, which
# is why it wants a target. A *symmetric* one-pole wants no preference at all,
# because both of its bounds are electrical:
#
#     upper   the picked transient. hexsim.karplus_strong's calibration note,
#             which is the only measured envelope profile in the project --
#             "peak in the first 20 ms, 8-12 dB down by 250 ms, then
#             1.8-3.1 dB/s" -- against a real picked electric. A one-pole at
#             5 ms reads 0.16 dB under the true peak at 20 ms; at 20 ms it
#             reads 4 dB under, and the attack is gone rather than late.
#     lower   ripple. Full-wave rectified, the lowest string puts 164.8 Hz on
#             the detector's own output, and shorter tau lets more of it
#             through.
#
# **And the release bound turns out not to exist.** A 5 ms one-pole falls at
# 1.7 dB per millisecond; the fastest thing it has to follow downwards is the
# early decay above, at 25 ms per decibel. It is 43x faster than the music, so
# a symmetric filter already tracks every musical decay exactly and an
# asymmetric release buys nothing that firmware cannot do better.
#
# **What the instrument is decides the rest, and it is not a guitar.** The
# target is a modern arpeggione: six strings, standard guitar tuning, bowed as
# well as picked. Those two techniques want opposite detectors -- picked wants
# a fast attack and a decay-following release; bowed has no transient at all,
# modulates continuously through the note, and wants the smoothing that would
# destroy a pick attack. An RC fixes one compromise across both, permanently.
# A firmware constant at the 1-2 kHz frame does not, and onset shape is exactly
# what distinguishes the two, so it can switch on what it hears.
#
# So: the analogue side takes the one constant that serves both, and the
# musical shaping lives at the sample rate where it costs nothing and can be
# set by ear against hexsim's renders -- which is how corrections 7 and 8 in
# 00-current-state.md were found in the first place. **The block is no longer
# blocked on a decision from Tim.** What is left of it is drawing.
#
# The derivation survives the one thing nobody here has measured. A bowed
# onset's rise time appears nowhere in this project and is not needed: the pick
# binds the fast end and the bow only ever asks for slower.

# 10k x 470n. Both E12, both already ordinary on this board, and the product is
# the derived figure rather than the round one -- see envelope_filter().
ENV_R = "10k 1%"
ENV_R_OHMS = 10_000.0
ENV_C = "470n/50V X7R"
ENV_C_FARADS = 470e-9

# Full-wave, and it is the bow that decides it. Half-wave doubles the ripple
# period and leaves 4.67 dB of it on a sustained low E -- at the string's own
# pitch, which is precisely the flutter a bowed swell would show. It also costs
# a second op-amp section per channel, and the six sections OPAMP_NEEDED
# reserves are one each: **the section count had quietly chosen half-wave and
# nothing had costed it**, which is the coarse pad's shape one block along.
#
# Those twelve sections do not want a 3.3 nV/rtHz JFET part -- the note at
# OPAMP has said so since the first pass, "left until the BOM is costed", and
# the BOM is costed now, with the OPA1644 both the largest line on it and out
# of stock at TI. The part is not chosen here; what is derived is that it is a
# different one.
ENV_FULL_WAVE = True
ENV_SECTIONS_PER_CHANNEL = 2

# hexsim.TUNING_HZ, E2 to E4 in standard tuning. Not imported: hexsim needs
# numpy and scipy at import time, and nothing in this pipeline may -- see
# CLAUDE.md on third-party packages. Cited rather than copied silently.
STRING_HZ = (82.41, 110.00, 146.83, 196.00, 246.94, 329.63)

# hexsim.karplus_strong's calibration note, against a real picked electric.
PICK_PEAK_S = 0.020
PICK_EARLY_DB, PICK_EARLY_S = 10.0, 0.250

# Spec section 4.4: "1-2 kHz sampling is sufficient". **It is not a range, and
# the low end fails.** envelope_sample_rate() is the arithmetic: the top string
# open is 329.63 Hz, its full-wave ripple is 659 Hz, and at 1 kHz that is above
# Nyquist and folds back at -29 dB. 2 kHz clears it. Open question 6 in
# 00-current-state.md asks whether 1-2 kHz is enough for the swell to feel
# responsive; the sample rate turns out to be settled by the rectifier's own
# output spectrum before the musical question is reached.
ENV_SAMPLE_HZ = 2_000.0

# What the firmware averages over, as a *duration* rather than a sample count,
# so the figure does not silently change with the sample rate. 8 ms is chosen
# to be short against the 20 ms the picked transient takes to peak: the digital
# side removes ripple without touching the attack the analogue side was tuned
# to keep.
ENV_FIRMWARE_BOX_S = 8e-3

# The two-op-amp absolute-value circuit, which is the standard one: an
# inverting half-wave stage whose diodes sit inside the loop, then a summing
# stage that adds the input to twice the half-wave output. Five resistors and
# two diodes per channel, and the ratio that does the work is R{n}54 = R/2 --
# everything else is R.
#
#     BUF --R51-- (-)A1 [D51 to -in, D52 to HW] --R52-- HW
#     BUF --R53-- (-)A2 <-- R54 from HW, R55 || C51 in feedback --> ENV
#
# The half value is 4k99 rather than 5k because 5k is not an E96 value. 0.2 %
# off a ratio that only sets the match between the two half-cycles, and a
# symmetric waveform averages the mismatch away; it is reported by
# envelope_balance() rather than assumed to be nothing.
ENV_R_HALF = "4k99 1%"
ENV_R_HALF_OHMS = 4_990.0

# 1N4148W: an ordinary small-signal switching diode in SOD-123, and the
# arithmetic that matters for it is not the forward drop -- both diodes sit
# inside an op-amp's feedback loop, which is the entire point of a *precision*
# rectifier and is why a 0.6 V drop does not appear in the answer. What is left
# outside the loop is reverse leakage into the summing junctions, and 1N4148
# leakage at the millivolts of reverse bias these ever see is picoamps against
# the 123 uA that R{n}51 delivers at the mixer's own clipping_peak().
ENV_DIODE = "1N4148W"

# **Named, not numbered, and this repo has a sibling that paid for the rule.**
# The mixer's DIODE_PINS records D801 fitted backwards for the whole life of
# that design, with the note that "a pin number can be transposed silently;
# 'A' and 'K' cannot". Read off KiCad's own Device:D this session: **pin 1 is
# the cathode** and pin 2 the anode, which is the opposite of what a reader
# guessing from the picture would assume, because at angle 0 the symbol's
# triangle points left and current runs right to left.
DIODE_PINS = {"K": 1, "A": 2}

# Fretted, so the highest fundamental is not an open string. The fret count of
# the instrument is written down nowhere in this project and is not invented
# here -- envelope_sample_rate() shows the answer is flat above the eighth fret
# of the top string, so the unknown does not reach the result. 24 is used to
# sweep past the point where that becomes true.
ENV_TOP_FRET = 24


def envelope_harmonics(f0, terms=20):
    """Ripple components of a rectified sine, relative to its own mean.

    Full-wave is even harmonics of f0 with amplitude (4/pi)/(4k^2-1); half-wave
    adds the fundamental at half the peak. Both are divided by their own mean,
    because what the ADC cares about is ripple as a fraction of the level being
    reported, not as a fraction of the input.
    """
    if ENV_FULL_WAVE:
        mean = 2 / math.pi
        return [(2 * k * f0, (4 / math.pi) / (4 * k * k - 1) / mean)
                for k in range(1, terms + 1)]
    mean = 1 / math.pi
    return [(f0, 0.5 / mean)] + [
        (2 * k * f0, (2 / math.pi) / (4 * k * k - 1) / mean)
        for k in range(1, terms + 1)]


def envelope_filter(tau=None, sample_hz=None):
    """The one-pole after the rectifier: what it costs and what it keeps.

    Four figures per string and none of them is a preference.

    `attack_db` is how far under the true peak the filter sits at the moment
    the picked transient peaks. It is the number that bounds tau from above and
    it is not recoverable afterwards -- a peak the filter missed is gone.

    `ripple_db` is the residue at the detector's output. It bounds tau from
    below and it *is* recoverable, because the ripple sits at a known frequency:
    each channel carries exactly one string, so the firmware knows what to
    average. **That asymmetry is the whole of the choice of tau.** Ripple is
    recoverable and attack is not, so the budget goes to the transient and the
    ripple is left for the sample rate to clean up.

    `alias_db` is the worst component still above Nyquist at the ADC, which is
    the one thing no amount of firmware fixes.

    `firmware_db` is what survives an ENV_FIRMWARE_BOX_S box average -- the
    digital half doing the job the RC is not being asked to do.
    """
    tau = tau or ENV_R_OHMS * ENV_C_FARADS
    sample_hz = sample_hz or ENV_SAMPLE_HZ

    def onepole(f):
        return 1.0 / math.sqrt(1 + (2 * math.pi * f * tau) ** 2)

    def box(f):
        # An N-sample box at the frame rate is a sinc; N is a duration here.
        x = math.pi * f * ENV_FIRMWARE_BOX_S
        return abs(math.sin(x) / x) if x else 1.0

    rows = []
    for f0 in STRING_HZ:
        harmonics = envelope_harmonics(f0)
        ripple = sum(a * onepole(f) for f, a in harmonics)
        alias = max([a * onepole(f) for f, a in harmonics
                     if f > sample_hz / 2] or [0.0])
        rows.append({
            "f0": f0,
            "ripple_db": 20 * math.log10(1 + ripple),
            "alias_db": 20 * math.log10(alias) if alias else -math.inf,
            "firmware_db": 20 * math.log10(
                1 + sum(a * onepole(f) * box(f) for f, a in harmonics)),
        })
    return {
        "tau": tau,
        "corner": 1.0 / (2 * math.pi * tau),
        "attack_db": 20 * math.log10(1 - math.exp(-PICK_PEAK_S / tau)),
        "fall_db_per_ms": 8.685889638 / (tau * 1000),
        "music_ms_per_db": PICK_EARLY_S / PICK_EARLY_DB * 1000,
        "faster_than_music": (8.685889638 / (tau * 1000)
                              / (PICK_EARLY_DB / (PICK_EARLY_S * 1000))),
        "full_wave": ENV_FULL_WAVE,
        "sections": ENV_SECTIONS_PER_CHANNEL * CHANNELS,
        "rows": rows,
    }


def envelope_balance():
    """What the E96 half-value costs, and what the detector's floor is.

    Two small numbers that a "coarse enough" argument would skip, and this
    repo's own habit is that coarse is a claim about what a block is for and
    not permission to leave it uncomputed -- pad_states() used to say so and
    envelope_filter() is the reason it matters here: the whole block exists to
    report level, so an error in the reported level is the one error it cannot
    absorb.

    `imbalance_db` is the mismatch between the two half-cycles from R{n}54
    being 4k99 where the ratio wants 5k. It is a *difference* between halves,
    so a symmetric waveform averages it out and what is left is second-order;
    the figure below is the worst case, on a waveform with only one polarity.

    `floor_db` is the offset of the summing amplifier referred to the mixer's
    own clipping_peak(), which is the quietest thing this detector can report.
    It is the reason the two stages are not on the same part -- see
    ENV_PACKAGES_REFS.
    """
    ideal = ENV_R_OHMS / 2
    imbalance = ENV_R_HALF_OHMS / ideal
    peak = socket.clipping_peak()
    return {
        "ratio_error": imbalance - 1,
        "imbalance_db": abs(20 * math.log10(imbalance)),
        "floor_db": 20 * math.log10(ENV_OPAMP_VOS / peak),
        "floor_volts": ENV_OPAMP_VOS,
        "peak": peak,
        "input_current": peak / ENV_R_OHMS,
    }


def envelope_sample_rate(tau=None):
    """Why 2 kHz and not 1, and what is left aliasing at either.

    Spec section 4.4 offers "1-2 kHz" as though the difference were a taste.
    It is not: the rectifier's output spectrum decides it, and the decision is
    made by the *top* string rather than by anything musical.

    Swept across the fretted range rather than the open strings, because this
    is a fretted instrument and the highest fundamental is not an open E4. Two
    regimes, and the crossover is the whole reason 1 kHz fails:

      * below about the eighth fret of the top string, the ripple fundamental
        2*f0 is under 1 kHz's Nyquist, so what aliases is the *second* ripple
        harmonic and the one-pole has already buried it. 2 kHz is ~20 dB
        better here, and it is the region a player actually lives in;
      * above it, 2*f0 clears Nyquist at either rate and the alias is set by
        the RC rather than by the sample rate, so the two converge and the
        answer improves with pitch.

    `folds_to_dc` is the case that matters most and reads best: an alias only
    becomes unremovable when it folds close to DC, which happens where 2*f0
    approaches the sample rate itself. Everything else lands high in the band
    and the firmware's own average takes it out with the ripple.
    """
    tau = tau or ENV_R_OHMS * ENV_C_FARADS

    def onepole(f):
        return 1.0 / math.sqrt(1 + (2 * math.pi * f * tau) ** 2)

    def worst(f0, sample_hz):
        folded = [(a * onepole(f), abs(sample_hz - f))
                  for f, a in envelope_harmonics(f0) if f > sample_hz / 2]
        return max(folded or [(0.0, 0.0)])

    out = {"tau": tau, "rates": {}}
    fundamentals = [STRING_HZ[-1] * 2 ** (n / 12)
                    for n in range(ENV_TOP_FRET + 1)]
    for sample_hz in (1_000.0, 2_000.0):
        rows = [(f0, *worst(f0, sample_hz)) for f0 in fundamentals]
        peak = max(rows, key=lambda row: row[1])
        near_dc = min(rows, key=lambda row: row[2])
        out["rates"][sample_hz] = {
            "worst_db": 20 * math.log10(peak[1]) if peak[1] else -math.inf,
            "worst_f0": peak[0],
            "worst_fret": round(12 * math.log2(peak[0] / STRING_HZ[-1])),
            "folds_to_dc_db": (20 * math.log10(near_dc[1]) if near_dc[1]
                               else -math.inf),
            "folds_to_dc_hz": near_dc[2],
        }
    return out


# ---------------------------------------------------------------------------
# The envelope ADC, and what the repo already believed about it
# ---------------------------------------------------------------------------
# **Six places said something about this block and they did not agree.** The
# rule the last pass arrived at -- a deferred block is not drawn, so nothing
# forces its descriptions to agree -- said to start here rather than with what
# the part needs:
#
#   1. DEFERRED said "ADS131M08 or MCP3564 ... the six ENV{n} nets exist and
#      are driven ... so that only SPI crosses the domain boundary";
#   2. floorplan.CROSSING_RULE said the four SPI signals "cross in the same
#      direction, because the ADC's own reference is VREF and its ground is
#      MAGND";
#   3. floorplan.ZONES puts it in **zone D2**, whose domain is DIGITAL, "at
#      the D2/A4 edge so only SPI crosses";
#   4. NET_DC's own comment on ENV{n} says "the ADC that reads it is
#      single-supply";
#   5. **RAILS has carried "V3V3": 3.3 since the first pass**, with no net of
#      that name anywhere on the board;
#   6. supply-decision.md's correction index says flatly *"there is no 3V3
#      rail on the board. The reference is on V5 and the MCU is deferred."*
#
# (2) and (3) disagree about which domain the part is in. (5) and (6)
# contradict each other outright. And the "only SPI" of (1) is enumerated by
# (2), after spec section 4.4, as four signals -- where the part needs six.
# Every one of those was consumed by something --
# check_crossings() reads CROSSINGS, check_zones() reads ZONES, NET_DC reads
# RAILS -- and none of them could fail, because **a rail with no net is
# invisible to every check that walks nets, and a zone with no parts is
# invisible to every check that walks parts.** That is zone P's fault again,
# one artefact along: `RAILS` is a declaration nothing is obliged to use.
# check_rails_are_drawn() below is the instrument, and V3V3 is why it exists.
#
# The resolutions: the part is **analogue**, so (2) wins over (3) and ZONES is
# corrected; V3V3 becomes real, so (5) wins over (6) and the supply document's
# index gains a line; and (1) becomes six signals rather than four.

# **MCP3564 against ADS131M08, and the full scale settles it in one line.**
#
# Both are named by spec section 4.4 and neither was chosen. Read first-hand:
# SBAS950B (ADS131M08, revised February 2021) and DS20006181C (MCP3561/2/4,
# 2021).
#
#   | | ADS131M08 | MCP3564 |
#   |---|---|---|
#   | channels | 8, simultaneous | 8 single-ended, multiplexed (SCAN) |
#   | external VREF | **1.1 / 1.25 / 1.3 V** | **0.6 V to AVDD** |
#   | full scale, gain 1 | +/-0.96 x VREF = 1.20 V | +/-VREF = 2.50 V |
#   | clock | CLKIN, or a crystal on XTAL1/2 | MCLKIN, or internal RC |
#   | AVDD current | 6.5 typ / 7.7 max mA | 0.93 typ / 1.3 max mA |
#   | package | 32-pin WQFN or TQFP | 20-lead TSSOP |
#
# **socket.clipping_peak() is 1.233 V** -- the mixer's own largest per-channel
# peak with all six aligned, and therefore the largest level this detector
# exists to report. The ADS131M08's full scale at unity gain is 1.20 V. It
# clips **0.24 dB below the signal it is there to measure**, and its own
# reference input cannot be raised to fix it: the top of the range, 1.3 V,
# buys 1.248 V and 0.1 dB. Its minimum gain is 1, so there is no setting that
# helps; the fix would be six attenuators, which is what the MCP3564 needs
# anyway for a different reason and does not need in order to *reach* the
# level.
#
# The MCP3564 takes the board's own 2.5 V reference and gives 2.5 V of full
# scale, which at unity is **6.1 dB above clipping_peak** -- and it makes
# floorplan.CROSSING_RULE's already-written sentence true rather than
# aspirational. That sentence was written before either part was read, and
# exactly one of the two candidates can honour it.
#
# The secondary differences all point the same way and none of them would have
# decided it: a fifth of the AVDD current, a leaded package a person can
# inspect, and one datasheet paragraph (7.3) that sanctions by name the thing
# this board wants -- "consider the MCP3561/2/4 as an analog component, and
# therefore, connect AVDD to DVDD and AGND to DGND with a star connection",
# with its cost stated ("the decoupling capacitors may be larger").
#
# **What the multiplexer costs is a clock, and that is the honest debit.** The
# ADS131M08 converts all eight channels at once; the MCP3564 converts one at a
# time and envelope_adc_clock() shows its internal RC oscillator cannot make
# the rate. So MCLK crosses the domain boundary as a sixth signal. See
# floorplan.CROSSINGS.
ENV_ADC = "MCP3564"
ENV_ADC_REF = "U17"
ENV_ADC_MPN = "MCP3564-E/ST"
ENV_ADC_DATASHEET = ("https://download.mikroe.com/documents/datasheets/"
                     "MCP3564_datasheet.pdf")
ENV_ADC_REVISION = "DS20006181C, 2021"
# DS20006181C page 3, the 20-lead TSSOP for the quad-channel device.
ENV_ADC_PINS = {"AVDD": 1, "AGND": 2, "REFIN-": 3, "REFIN+": 4,
                "CH0": 5, "CH1": 6, "CH2": 7, "CH3": 8, "CH4": 9, "CH5": 10,
                "CH6": 11, "CH7": 12, "CS": 13, "SCK": 14, "SDI": 15,
                "SDO": 16, "IRQ": 17, "MCLK": 18, "DGND": 19, "DVDD": 20}
ENV_ADC_AVDD_RANGE = (2.7, 3.6)
ENV_ADC_AIDD_MA = (0.93, 1.3)          # BOOST = 1x, the default
ENV_ADC_DIDD_MA = (0.25, 0.37)
ENV_ADC_VREF_RANGE = (0.6, None)       # None means "AVDD" -- the table's own
ENV_ADC_INPUT_MARGIN = 0.1             # AGND - 0.1 V to AVDD + 0.1 V
ENV_ADC_ZIN_OHMS = 260_000.0           # gain 1x, typ, at the table's AMCLK
ENV_ADC_ZIN_AMCLK = 4.9152e6           # "proportional to 1/AMCLK"
ENV_ADC_MCLK_RANGE = (1.0e6, 20.0e6)   # external, DVDD >= 2.7 V
ENV_ADC_MCLK_INTERNAL = (3.3e6, 6.6e6)
# Table 5-6, "Oversampling Ratio and Sinc Filter Relationship": OSR setting ->
# (conversion time in DMCLK periods, no-missing-code resolution in bits). Only
# the settings that could reach 2 kHz on six channels inside the 20 MHz clock
# limit are listed; the rest of the table runs to OSR 98304.
ENV_ADC_OSR = {32: (96, 16), 64: (192, 19), 128: (384, 22), 256: (768, 24)}
# **Which string goes on which channel is free again, and the map is the simple
# one.** It was CH0-CH3, CH5 and CH6, and the reason was real while it lasted: a
# TSSOP's pins are 0.65 mm apart and the router's grid is 0.5 mm, so
# rules.pad_reach() shows two of the ten pin rows hold no grid cell at any
# placement whatsoever -- and no placement fixes that, because a pad wide enough
# to always contain a cell would sit closer to its neighbour than this board's
# own clearance rule allows. What a placement could choose was *which* two rows
# lose, and this dict spent that on the ADC's two grounded channels.
#
# **The fan-out removes the constraint rather than easing it.**
# route.Grid.escape() lays a pad's escape as fixed copper on the pad's own
# centre line, so a pin row with no cell in it is entered anyway -- see
# rules.track_offset_limit(). There is no longer a row that costs anything, so
# there is nothing to spend and the map is CH0 to CH5 in order.
#
# **So the map is free, and it is kept anyway -- which is a different statement
# from the one that was here and the difference is the whole point.** CH0 to CH5
# in order was drawn, routed and measured. It is electrically identical, it is
# what firmware would naively expect, and it puts all six inputs on the west row
# where they face the dividers -- CH6 is pin 11, on the *logic* side, so the old
# map makes ENVA6 get round the package on a board whose whole reason for
# rotation 0 is that the analogue pins face the divider columns.
#
# **It cost a net 30 mm away.** Moving the channels down one pin makes a fifth
# pad need an escape -- pin 9 instead of pin 10 -- and the escape's halo takes
# cells out of the one corridor the six ENVA{n} runs already converge into. The
# router closed all six ENVA nets and dropped **CVN3**, in the CV band, with
# DRC still at zero violations and two unconnected items. That is the honest
# price and it is not one worth paying for a tidier dict: verify.UNROUTED_ITEMS
# at 0 is a stronger property than a firmware convenience.
#
# **The finding is that an escape's copper is not free and it is not spent where
# it is laid.** Four escapes at U17 closed four nets there and shortened the
# whole fan -- 1547 track runs against 1489. A fifth closed nothing extra and
# broke something in another zone. Nothing in this repo would have predicted
# either; the router is the only instrument that knows.
#
# Firmware reads the mapping from here; nothing electrical distinguishes one
# channel from another, and this dict is now a *record of a measurement* rather
# than a constraint.
ENV_ADC_CHANNEL = {1: "CH0", 2: "CH1", 3: "CH2", 4: "CH3", 5: "CH5", 6: "CH6"}
ENV_ADC_GROUNDED = ("CH4", "CH7")
ENV_ADC_PRESCALE = 1
# The chosen point. envelope_adc_clock() is the arithmetic; this is its answer
# written where the netlist can see it.
ENV_ADC_OSR_CHOICE = 64

# The 3.3 V rail, and it exists because the ADC does.
#
# Microchip MCP1700, DS20001826F (2005-2020) with DS21826B alongside for the
# figure the newer revision drops. Read first-hand:
#
#     Input operating voltage   VIN   2.3 to 6.0 V; absolute maximum 6.5
#     Quiescent current         Iq    1.6 uA typ, 4 uA max at IL = 0
#     Maximum output current          250 mA min for VR >= 2.5 V
#     Dropout                         178 mV typ, 350 mV max at 250 mA
#     Line / load regulation          +/-0.75 %/V typ, +/-1.0 % typ
#     Output noise              eN    3 uV/rtHz at 1 kHz, COUT = 1 uF
#     PSRR                            44 dB at 100 Hz, COUT = 1 uF
#     Thermal, SOT-23           thJA  212 C/W (rev F, JESD51-7);
#                                     336 C/W (rev B, minimum trace, 1 layer)
#     Tj max                          150 C
#     SOT-23 pinout                   1 GND, 2 VOUT, 3 VIN
#
# **The 6.0 V input limit is a feature here and not a compromise**: it makes
# V5 the only rail this regulator can hang off, and V5 is the right source
# anyway. The alternative is VA+, and 12 V into 3.3 at even 50 mA is 435 mW in
# a SOT-23 -- v5_regulator()'s arithmetic one package smaller. From V5 the
# same 50 mA is 85 mW. The part cannot be fitted the wrong way round because
# its own rating forbids it.
#
# **336 C/W and not 212**, following v5_regulator()'s stated principle: the
# minimum-pad figure is the honest one to design to, because a number that
# depends on how much copper somebody poured is a number the fabricator can
# change. Revision F publishes only the JESD51-7 four-layer figure; revision B
# publishes both, so the pessimistic one is still a reading.
#
# Its SOT-23 pin map is the NCP1117's -- 1 GND, 2 VOUT, 3 VIN -- which is why
# V5_PINS serves both and there is no second dict.
V3V3_PART = "MCP1700-3.3"
V3V3_MPN = "MCP1700T-3302E/TT"
V3V3_REF = "U18"
V3V3_VOLTS = 3.3
V3V3_VIN_MAX = 6.0
V3V3_IQ_MA = 0.004
V3V3_IOUT_MA = 250.0
V3V3_DROPOUT_V = 0.35                  # maximum, at 250 mA
V3V3_THETA_JA = 336.0                  # rev B, minimum trace, single layer
V3V3_TJ_MAX = 150.0
V3V3_CAP = "1u/16V X7R"                # the datasheet's own CIN and COUT
V3V3_CAP_FARADS = 1e-6
V3V3_DATASHEET = ("https://ww1.microchip.com/downloads/aemDocuments/documents/"
                  "APID/ProductDocuments/DataSheets/"
                  "MCP1700-Data-Sheet-20001826F.pdf")

# The per-channel network between ENV{n} and the ADC pin. Three parts a
# channel and every one of them is derived at envelope_adc_input().
ENV_ADC_R_TOP = "22k 1%"
ENV_ADC_R_TOP_OHMS = 22_000.0
ENV_ADC_R_BOT = "4k99 1%"
ENV_ADC_R_BOT_OHMS = 4_990.0
ENV_ADC_C = "1200p/50V C0G"
ENV_ADC_C_FARADS = 1200e-12
# Local decoupling, and the one number here that is a refusal: see
# envelope_adc_reference().
ENV_ADC_LOCAL = "100n/50V X7R"


def envelope_adc_mclk(osr=None, sample_hz=None, channels=None):
    """The minimum master clock for one OSR setting, in Hz.

    Split out of envelope_adc_clock() because envelope_adc_input() needs it
    too -- the ADC's input impedance is "proportional to 1/AMCLK", so the
    divider's loading depends on the clock, and the clock depends on the
    channel count and the OSR and nothing else. Two functions calling one
    third is the shape that keeps them from calling each other.
    """
    osr = osr or ENV_ADC_OSR_CHOICE
    periods = ENV_ADC_OSR[osr][0]
    return (4 * ENV_ADC_PRESCALE * (channels or CHANNELS) * periods
            * (sample_hz or ENV_SAMPLE_HZ))


def envelope_adc_clock(sample_hz=None, channels=None):
    """What MCLK has to be, and why it cannot come from inside the part.

    The MCP3564 has one modulator and a multiplexer, so six channels cost six
    conversions. DS20006181C's Figure 5-16 is explicit that SCAN Continuous is
    not pipelined across channels -- the decimation filter is reset between
    them -- so each channel costs a full settling conversion:

        DMCLK       = MCLK / (4 x Prescale)          equation 4-2
        TCONV       = Table 5-6, in DMCLK periods    (3 x OSR3 x OSR1)
        rate/channel = DMCLK / (channels x TCONV)

    which rearranges to the minimum master clock for a given rate:

        MCLK_min = 4 x Prescale x channels x TCONV x rate

    **The internal oscillator fails this, and it fails it on its tolerance
    rather than on its value.** DS20006181C gives fMCLK_INT as 3.3 to 6.6 MHz
    -- a factor of two, because it is an RC -- and the design has to hold at
    the *bottom* of it. Even at the coarsest useful setting, OSR = 32, the
    slow end gives 1432 Hz per channel, and envelope_sample_rate() has already
    shown what happens below 2 kHz: the top fretted string's rectified
    fundamental crosses Nyquist and folds towards DC, where no averaging
    removes it. So MCLK is external, from the deferred controller, and that is
    a signal crossing the analogue boundary that the simultaneous-sampling
    alternative would not have needed. It is the multiplexer's bill.

    **Which OSR, and it is decided by the detector's floor rather than by the
    converter.** Every row below reaches 2 kHz inside the part's own 20 MHz
    ceiling except OSR 256, so the choice is free in parts and costs only
    clock frequency. The LSB is quoted referred to ENV{n} -- through
    envelope_adc_input()'s divider, which is where the measurement actually
    happens -- against the 3 mV that envelope_balance() calls the floor of the
    whole detector. OSR 32's LSB is 413 uV, which is under that floor but not
    under the offset of the OPA1644 that stage B actually is; OSR 64 is 52 uV
    and is under both, for one octave of MCLK. That is the setting fitted.
    """
    sample_hz = sample_hz or ENV_SAMPLE_HZ
    channels = channels or CHANNELS
    scale = envelope_adc_input()["ratio"]
    rows = {}
    for osr, (periods, bits) in sorted(ENV_ADC_OSR.items()):
        mclk_min = envelope_adc_mclk(osr, sample_hz, channels)
        lsb = 2 * VREF / 2 ** bits
        rows[osr] = {
            "tconv_periods": periods,
            "bits": bits,
            "mclk_min": mclk_min,
            "fits": mclk_min <= ENV_ADC_MCLK_RANGE[1],
            "lsb_at_pin": lsb,
            "lsb_at_env": lsb / scale,
            "internal_rate_low": (ENV_ADC_MCLK_INTERNAL[0]
                                  / (4 * ENV_ADC_PRESCALE * channels
                                     * periods)),
            "internal_rate_high": (ENV_ADC_MCLK_INTERNAL[1]
                                   / (4 * ENV_ADC_PRESCALE * channels
                                      * periods)),
        }
    chosen = rows[ENV_ADC_OSR_CHOICE]
    return {
        "rows": rows,
        "osr": ENV_ADC_OSR_CHOICE,
        "sample_hz": sample_hz,
        "channels": channels,
        "mclk_min": chosen["mclk_min"],
        "mclk_max": ENV_ADC_MCLK_RANGE[1],
        "internal_range": ENV_ADC_MCLK_INTERNAL,
        # The best the internal oscillator can do at *any* OSR, against the
        # rate the design needs: the coarsest setting is the fastest, so this
        # is OSR 32's slow end and it is 2.9 dB short.
        "internal_best_hz": max(row["internal_rate_low"]
                                for row in rows.values()),
        "internal_short_db": 20 * math.log10(
            sample_hz / max(row["internal_rate_low"]
                            for row in rows.values())),
        "internal_usable": any(row["internal_rate_low"] >= sample_hz
                               for row in rows.values()),
        "dmclk": chosen["mclk_min"] / (4 * ENV_ADC_PRESCALE),
        "detector_floor_v": envelope_balance()["floor_volts"],
    }


def envelope_adc_input(r_top=None, r_bot=None, c_farads=None, mclk=None):
    """The three parts between ENV{n} and CH{n-1}, each with its reason.

    **The problem is that ENV{n} is a +/-12 V node and the ADC is a 3.3 V
    part.** NET_DC declares ENV{n} as (0, MODULE_RAIL) and stage B is an
    OPA1644, so the largest voltage it can present is the rail less
    OPAMP_SWING_HEADROOM -- 11.65 V. The MCP3564's absolute input rating is
    AGND - 0.1 V to AVDD + 0.1 V, which is 3.4 V, and its own text says what
    happens above it: "Any voltage above or below this range will cause
    leakage currents through the ESD diodes at the input pins. This ESD
    current can cause unexpected performance of the device."

    **A series resistor is the obvious answer and it is the wrong one.** It
    limits the ESD current but does not stop it, and the current has to go
    somewhere: into AVDD, on a rail whose regulator cannot sink. Six channels
    clipping together would put more current *into* the 3.3 V rail than the
    ADC draws out of it, and the rail would rise towards the 3.6 V the part is
    rated to. That is a failure whose trigger is a hard-picked string.

    So the input is **divided**, not clamped, and the ratio is set by the one
    number that bounds ENV{n} from above:

        11.65 V x 4990 / (22000 + 4990) = 2.15 V

    which is inside VREF and therefore inside the linear range, not merely
    inside the absolute rating. **No input on this ADC can reach a voltage
    that needs protecting, at any signal the module can produce.**

    What it costs is range at the other end, and the cost is computable:
    socket.clipping_peak() lands at 9.1 % of full scale, so 20.8 dB of the
    converter's span sits above the loudest level the system has. That is why
    envelope_adc_clock() spends an octave of MCLK on OSR 64 rather than 32 --
    the bits given away here are bought back there, for no parts.

    **The loading is a scale error and it is stated rather than trimmed.** The
    ADC's input is a switched capacitor, so it presents ENV_ADC_ZIN_OHMS in
    parallel with the divider's lower leg, and the datasheet gives that figure
    as a typical proportional to 1/AMCLK with no tolerance. It is identical on
    all six channels -- same value, same clock -- so it is a gain error and
    not a matching error, in the same sense MEASURED["logic_law_error"] is,
    and one measured curve calibrates it in firmware.

    **C{n}52 is the anti-alias, and its two bounds are 25 kHz apart.** The
    modulator samples at DMCLK, and the only band-limiting between stage B's
    own 33.9 Hz pole and that sampler is this RC. Above, it must be flat
    across the band envelope_sample_rate() sweeps -- up to the top fretted
    string's rectified fundamental, which at the 24th fret is 2.64 kHz; below,
    it must be as far under DMCLK as that allows. 1200 pF sits at 32.6 kHz,
    which is 0.03 dB of droop at 2.64 kHz and 37 dB of rejection at DMCLK.
    """
    r_top = r_top or ENV_ADC_R_TOP_OHMS
    r_bot = r_bot or ENV_ADC_R_BOT_OHMS
    c_farads = c_farads or ENV_ADC_C_FARADS
    mclk = mclk or envelope_adc_mclk()
    ratio = r_bot / (r_top + r_bot)
    swing = MODULE_RAIL - OPAMP_SWING_HEADROOM
    z_in = ENV_ADC_ZIN_OHMS * ENV_ADC_ZIN_AMCLK / mclk
    loaded_bot = 1.0 / (1.0 / r_bot + 1.0 / z_in)
    loaded = loaded_bot / (r_top + loaded_bot)
    source = 1.0 / (1.0 / r_top + 1.0 / r_bot)
    corner = 1.0 / (2 * math.pi * source * c_farads)
    peak = socket.clipping_peak()
    ripple_hz = 2 * STRING_HZ[-1] * 2 ** (ENV_TOP_FRET / 12.0)
    return {
        "ratio": ratio,
        "loaded_ratio": loaded,
        "load_error": loaded / ratio - 1.0,
        "z_in": z_in,
        "swing": swing,
        "at_swing": swing * ratio,
        "at_clipping_peak": peak * ratio,
        "full_scale": VREF,
        "absolute_max": V3V3_VOLTS + ENV_ADC_INPUT_MARGIN,
        "headroom_db": 20 * math.log10(VREF / (swing * ratio)),
        "clipping_peak_fraction": peak * ratio / VREF,
        "range_given_up_db": 20 * math.log10(VREF / (peak * ratio)),
        "source_ohms": source,
        "corner_hz": corner,
        "ripple_hz": ripple_hz,
        "droop_db": -10 * math.log10(1 + (ripple_hz / corner) ** 2),
    }


def envelope_adc_reference():
    """What REFIN+ may take from the MAX6126, and what it may not.

    Two sentences from two datasheets meet on this net and they do not both
    fit.

    DS20006181C section 3.2: *"For optimal ADC accuracy, appropriate bypass
    capacitors should be placed between REFIN+ and AGND at all times. Using a
    0.1 uF and a 10 uF ceramic capacitor can help ... These bypass capacitors
    are not mandatory for correct ADC operation."*

    The MAX6126's own page 4, via design.classify_reference_load(): **one**
    output capacitor between 0.1 and 10 uF, and any number of 0.1 uF locals
    beside it. VREF already carries its one -- C802 at 10 uF -- so a 10 uF at
    REFIN+ would be a *second bulk capacitor* on a part qualified for one.
    That is the exact fault this repo deleted C804 to fix, arriving from a
    different direction and with a datasheet sentence recommending it.

    **So the 10 uF is refused and the 100 nF is fitted**, and the refusal is
    the cheaper of the two: the MCP3564 calls the capacitor optional and the
    MAX6126 calls its own limit a stability range.

    **The buffer the ADC's Figure 7-1 draws is also refused, and for the
    opposite kind of reason.** That figure puts an op-amp between reference
    and REFIN+ "because the REFIN+ input is not buffered", which is true and
    is about *driving* the switched-capacitor load. What it would cost here is
    a series element between a reference and a load whose current
    DS20006181C never states -- there is no reference input current row
    anywhere in it -- so the DC accuracy would depend on an unknown. Section 6
    of the spec forbids inventing that number, and the honest move is to
    remove the term rather than guess it: connected directly, the load current
    reaches VREF through no resistance at all and shows up only as load
    regulation.

    **Which is bounded even though the current is not**, and that is what
    makes the direct connection safe to assert. The MAX6126's load regulation
    maximum is 28 uV/mA, so the question to ask is not "how big is this
    current" but "how big would it have to be", and that one the datasheets
    answer between them. To move VREF by 100 uV -- 0.004 % of 2.5 V, and five
    times the 19 uV of load regulation reference_load() already attributes to
    the '541 -- it would have to be **3.6 mA**, which is five times the whole
    '541 load and nearly three times the ADC's own maximum AVDD current. A
    switched-capacitor reference input on a part drawing 1.3 mA is not that,
    by any reading of any of it.
    """
    load_reg = 28e-6                    # V/mA, MAX6126 maximum
    target = 100e-6
    return {
        "local_farads": 100e-9,
        "bulk_refused_farads": 10e-6,
        "existing_bulk": reference_load()["total_farads"],
        "ceiling_farads": VREF_CLOAD_MAX_F,
        "load_regulation_v_per_ma": load_reg,
        "current_to_move_100uv_ma": target / load_reg,
        "logic_load_ma": reference_load()["step_amps"] * 1e3,
        "adc_avdd_ma": ENV_ADC_AIDD_MA[1],
    }


# ---------------------------------------------------------------------------
# The controller, and the positive case for it
# ---------------------------------------------------------------------------
# **The part is the RP2040 and what was missing was the argument for it.**
# 00-current-state.md's corrections table records the choice at entry 9 --
# *"Teensy 4.1 / RP2350B for the controller"* overturned because *"both have
# mandatory buck converters"*, found by *"deep dive"* -- and that is a
# **negative**: the other candidates carry a switcher onto a board whose whole
# supply argument is keeping switchers away from a multiplier. Nobody ever
# wrote the positive, which is that this part does the job with room to spare,
# so the choice rested on a comparison instead of on a requirement.
#
# **Claim 9 is marked as not relied upon, and here is why that is the honest
# state rather than a hedge.** Its "mandatory" came from a deep dive in the
# parent project's documents 0-4, which are not in this repo; no RP2350 or
# Teensy datasheet page is cited anywhere here; and entry 10 of the same table
# says the MCU was never the load-bearing choice in the first place. So the
# claim may well be true and nothing in this repo can check it. controller_fit()
# is what the decision rests on instead: every row is a requirement this board
# makes and a number read off the RP2040's own datasheet, and the smallest
# margin in it is 2.1x. That is this repo's own rule about a constraint with
# margin -- do it, do not defend it as load-bearing -- applied to a part.
#
# Raspberry Pi RP2040 datasheet, build-date 2024-11-05, read first-hand. Every
# figure below is quoted from it with the table or section named. The URL below
# is the one Raspberry Pi publish and it was fetched and seen to resolve --
# through two redirects, to pip-assets.raspberrypi.com, which is why the
# canonical form is the one recorded rather than the final one.
CONTROLLER = "RaspberryPi_Pico"
CONTROLLER_REF = "U19"
# Table 6 of the Pico datasheet, "Part Number", read first-hand: SC0915 is the
# Raspberry Pi Pico. SC0917 is the Pico H, which is the same board with the
# headers already fitted and the debug pads brought to a 3-way connector; it is
# not what is drawn here because this footprint is the castellated module.
CONTROLLER_MPN = "SC0915"
CONTROLLER_DATASHEET = ("https://datasheets.raspberrypi.com/rp2040/"
                        "rp2040-datasheet.pdf")
CONTROLLER_REVISION = "RP2040 Datasheet, build-date 2024-11-05"
# **The part is a module now and the silicon inside it has not changed.** Two
# documents, and keeping them apart is the whole of this section:
#
#   * the RP2040 datasheet is still the authority for what the *chip* can do --
#     the PWM slices, the GPIO functions, the clock outputs, the ADC, and every
#     current figure in CONTROLLER_USE_CASES. None of that moved;
#   * the Pico datasheet is the authority for what the *module* brings out, and
#     it takes things away: four GPIO are wired to board functions, one of the
#     four ADC channels is one of them, and the 3.3 V rail is made on the
#     module by a converter this design does not choose.
#
# **What this swap deleted is 25 parts and one whole class of problem.** The
# QFN-56's 0.40 mm pitch is what moved rules.COPPER_OZ to 1 oz and
# rules.TRACK_MM to 0.09; a 2.54 mm module needs none of it. Gone with the
# package: U20 and its decoupling, Y801 with R824 C832 C833, J14 with R820
# R821 R822 R823, twelve supply capacitors, and the BOOT and SWD headers.
# fabrication-class.md is re-opened by that and controller_package() says so.
CONTROLLER_MODULE = "Raspberry Pi Pico"
CONTROLLER_MODULE_DATASHEET = ("https://datasheets.raspberrypi.com/pico/"
                               "pico-datasheet.pdf")
CONTROLLER_MODULE_REVISION = "Raspberry Pi Pico Datasheet, RP-004484"
# Section 2: "a single sided 51x21 mm 1 mm thick PCB with a micro-USB port
# overhanging the top edge and dual castellated/through-hole pins around the
# remaining edges", 40 pins on 2.54 mm.
CONTROLLER_MODULE_MM = (21.0, 51.0)
CONTROLLER_MODULE_PIN_PITCH_MM = 2.54
# Section 2.1, and the numbers are Figure 2's own: "A few RP2040 GPIO pins are
# used for internal board functions". So the part has 30 GPIO and the module
# offers 26, and the four it keeps are not four spare ones -- one of them is an
# ADC channel and one of them is the only power-save control the on-module
# converter has.
CONTROLLER_INTERNAL_GPIO = {
    23: "on-board SMPS power-save (PS) control",
    24: "VBUS sense -- high if VBUS is present",
    25: "user LED",
    29: "ADC3, measuring VSYS/3",
}
CONTROLLER_EXPOSED_GPIO = tuple(
    gpio for gpio in range(30) if gpio not in CONTROLLER_INTERNAL_GPIO)
# Figure 2, and the pin numbering is Figure 4's: 1 to 20 down the left edge,
# 21 to 40 up the right, with the micro-USB at the top. Transcribed rather than
# generated, because a generated pinout is a guess with a loop around it.
CONTROLLER_MODULE_PINS = {
    "GPIO0": 1, "GPIO1": 2, "GPIO2": 4, "GPIO3": 5, "GPIO4": 6, "GPIO5": 7,
    "GPIO6": 9, "GPIO7": 10, "GPIO8": 11, "GPIO9": 12, "GPIO10": 14,
    "GPIO11": 15, "GPIO12": 16, "GPIO13": 17, "GPIO14": 19, "GPIO15": 20,
    "GPIO16": 21, "GPIO17": 22, "GPIO18": 24, "GPIO19": 25, "GPIO20": 26,
    "GPIO21": 27, "GPIO22": 29, "GPIO26_ADC0": 31, "GPIO27_ADC1": 32,
    "GPIO28_ADC2": 34,
    "RUN": 30, "AGND": 33, "ADC_VREF": 35, "3V3": 36, "3V3_EN": 37,
    "VSYS": 39, "VBUS": 40,
}
CONTROLLER_MODULE_GND_PINS = (3, 8, 13, 18, 23, 28, 38)
# Section 2.1: "3V3 is the main 3.3 V supply to RP2040 and its I/O, generated
# by the on-board SMPS. This pin can be used to power external circuitry
# (maximum output current will depend on RP2040 load and VSYS voltage, it is
# recommended to keep the load on this pin less than 300 mA)."
CONTROLLER_3V3_OUT_MAX_MA = 300.0
# Section 2.1 again: "VSYS is the main system input voltage, which can vary in
# the allowed range 1.8 V to 5.5 V".
CONTROLLER_VSYS_RANGE = (1.8, 5.5)

# -- the converter this design did not choose ------------------------------
#
# **The module carries its own switcher, so the supply question moves rather
# than disappearing.** Richtek RT6150B-33GQW, named in the Pico datasheet
# section 4.4, and read first-hand here at DS6150A/B-05 (July 2015) because
# the Pico datasheet does not state its switching frequency at all -- and
# without a frequency, supply_beat() has nothing to price a second switcher
# against. That is what the Richtek read was for, and it settled three things.
PICO_SMPS = "RT6150B-33GQW"
PICO_SMPS_DATASHEET = ("https://www.richtek.com/assets/product_file/"
                       "RT6150A=RT6150B/DS6150AB-05.pdf")
PICO_SMPS_REVISION = "DS6150A/B-05, July 2015"
# Electrical characteristics: "Oscillator Frequency fOSC ... 0.8 / 1 / 1.2 MHz".
# A stated band with a minimum and a maximum, which is exactly the shape
# mcu_dcdc_beat() needs and exactly what MCU_DCDC_KHZ already is. A typical
# figure would not have been usable.
PICO_SMPS_KHZ = (800.0, 1200.0)
PICO_SMPS_KHZ_TYP = 1000.0
# "Power Save Mode (PSM) Enable Control ... PSM operation is user controlled
# and can be enabled by driving the PS pin low. If the PS pin is driven high,
# then fixed frequency switching is enabled." The Pico wires PS to GPIO23 and
# its own datasheet says "When PS is low (the default on Pico) the regulator is
# in Pulse Frequency Modulation mode ... Setting PS high forces the regulator
# into Pulse Width Modulation (PWM) mode ... at the expense of much worse
# efficiency."
#
# **That is mcu_dcdc_light_load()'s objection arriving at a third part, and
# this time the answer is a firmware constant rather than a suffix.** The
# TPS560430 was chosen in its forced-PWM version because a PFM buck's
# frequency falls with load and walks into the audio band; the same is true
# here and the same rule applies, but there is no part to choose -- the module
# is the module. So GPIO23 must be driven high before anything else runs, and
# it is recorded in CONTROLLER_MAP's own note and in controller.md's list of
# things firmware has to hold.
PICO_SMPS_PS_GPIO = 23
# Absolute maximum ratings: "VOUT, VIN, EN, PS, VINA, FB Pin ... -0.3V to 6V",
# stated per pin and *not* relative to VIN. And the two switch-leakage rows,
# 5 uA and 10 uA maximum, which are the only numbers the document gives for
# how much current an idle output stage passes.
PICO_SMPS_VOUT_ABS_MAX = 6.0
PICO_SMPS_SWITCH_LEAKAGE_UA = (5.0, 10.0)
# Section 1.2, "Key features", and section 4.5.1 for the PWM shape.
CONTROLLER_CLOCK_HZ = 133e6            # "clk_sys ... maximum frequency 133MHz"
CONTROLLER_CLOCK_TYPICAL_HZ = 125e6    # the frequency PWM_CARRIER is set from
CONTROLLER_GPIO = 30                   # "30 GPIO pins, 4 of which ... analogue"
CONTROLLER_ADC_CHANNELS = 4
CONTROLLER_PWM_SLICES = 8              # "8 identical slices"
CONTROLLER_PWM_OUTPUTS = 16            # "up to 16 controllable PWM outputs"
CONTROLLER_UARTS = 2
CONTROLLER_SPI = 2
CONTROLLER_SRAM_KB = 264
# Section 1.4.1: "The USB bootloader requires a 12MHz crystal or 12MHz clock
# input", which is what makes the crystal a value rather than a choice.
CONTROLLER_XTAL_HZ = 12e6
# Section 1.4.2: "VREG_VOUT ... nominal voltage 1.1V, 100mA max current", and
# Table 192 gives IMAX 100 mA, ILIMIT 150 mA minimum, VREG_VIN 1.63-3.63 V.
CONTROLLER_VREG_IMAX_MA = 100.0
CONTROLLER_VREG_VIN = (1.63, 3.63)
# Table 625, IO characteristics: "Maximum Total IOVDD current IIOVDD_MAX 50 mA
# -- Sum of all current being sourced by GPIO and QSPI pins". A limit, not a
# draw, and it is quoted because it is the only hard current number the part
# gives for the 3.3 V side.
CONTROLLER_IIOVDD_MAX_MA = 50.0
# Table 637, "Power Consumption", both columns. The rows are use cases rather
# than an electrical maximum, and the document is explicit about what each
# column means: 'Typical Average Current' is "averaged over several seconds
# ... at room temperature and nominal voltage", 'Maximum Average Current' is
# "the maximum ... on a worst-case RP2040 device, across the temperature
# extremes, and maximum voltage".
#
#   use case                 DVDD typ/max   IOVDD typ/max   USB_VDD typ/max
CONTROLLER_USE_CASES = {
    "Popcorn":        ((10.9, 16.6), (24.8, 35.5), (0.0, 0.0)),
    "BOOTSEL active": ((9.4, 14.7), (1.2, 4.3), (1.4, 2.0)),
    "BOOTSEL idle":   ((9.0, 14.3), (1.2, 4.3), (0.2, 0.6)),
}
# **The package that used to be the gate.** RP2040 ships in one package, a 7x7
# QFN-56 at 0.40 mm pitch, and rules.QFN_PIN_PITCH_MM is still that number --
# controller_package() keeps the derivation because it is what moved the
# fabrication class, and moving the class back is a decision that has to be
# taken against it rather than instead of it.
#
# What is fitted is the module: 2.54 mm pitch on 1.6 mm pads, read off
# Module:RaspberryPi_Pico_SMD_HandSolder rather than off the drawing, the way
# placement.SIZE is read off KiCad's own courtyards.
CONTROLLER_PIN_PITCH_MM = CONTROLLER_MODULE_PIN_PITCH_MM
CONTROLLER_PAD_WIDTH_MM = 1.6
CONTROLLER_QFN_PIN_PITCH_MM = rules.QFN_PIN_PITCH_MM
CONTROLLER_QFN_PAD_WIDTH_MM = rules.QFN_PAD_WIDTH_MM
# Where the controller meets this board. Five of the mixer's own 5-way headers,
# declared here so controller_asks() counts what they carry rather than
# repeating it -- a table of what a connector carries is a second copy of the
# connector, and the two would be free to disagree.
CONTROLLER_HEADERS = ("J9", "J10", "J11", "J12", "J13")
# **The MCLK divisor, and it is a choice among seven rather than a solution.**
# envelope_adc_clock() puts the floor at 9.216 MHz and the MCP3564's external
# clock range at 1-20 MHz, so every integer divide of 125 MHz from 7 to 13
# lands inside the window -- 17.86 MHz down to 9.615. 12 is the design point
# because it is the middle of that run and 13 % above the floor; the row in
# controller_fit() is worth reading as "seven divisors clear it" rather than as
# a ratio, because what makes an integer divide the right answer is that the
# ADC's conversions are not on a jittered clock, and that is true of all seven.
CONTROLLER_MCLK_DIVIDE = 12


def controller_asks():
    """What this board asks of a controller, counted rather than listed.

    **The signal count comes off the netlist and not off a table**, because a
    table of what a part carries is a second copy of the part. That principle
    is unchanged and what it counts has moved, which is worth recording rather
    than quietly rewriting.

    It used to walk J9 to J13 -- five 5-way headers that were where a deferred
    off-board controller would have met this design -- and count what they
    carried that was not a ground. Those headers are gone: the controller is on
    this board, in zone D2, so the nets go to its pins. So this walks U19's own
    GPIO pins instead, and **the number went up**, from 14 to 19. Four of the
    five new ones are things the headers never carried because the block that
    needed them was not drawn: two MIDI, the tap, the pedal and USB's VBUS
    sense. GPIO margin falls from 2.14x to 1.58x and is still the tightest
    countable row in controller_fit().

    That is the shape of what drawing a deferred block does to a requirement
    derived while it was deferred: the requirement was not wrong, it was
    counted against an interface that stood in for the thing. The interface
    carried what the *rest of the board* needed from a controller. The part
    also needs pins for its own periphery.

    Everything else here is a figure some other function in this file derived,
    quoted rather than restated:

      * MCLK from envelope_adc_clock(), which is the one genuinely awkward ask;
      * the control frame from spec section 4.3 and the envelope frame from
        envelope_sample_rate();
      * the fail-safe's pump frequency from PUMP_HZ;
      * the PWM count from CHANNELS, and its carrier from PWM_CARRIER -- which
        is already derived *from this part's clock*, and is noted below as
        margin rather than as a reason.
    """
    gpio_pins = {str(pin): gpio for gpio, pin in CONTROLLER_GPIO_PINS.items()}
    signals = sorted(
        net for (ref, pin), net in DESIGN.pin_owner().items()
        if ref == CONTROLLER_REF and pin in gpio_pins)
    return {
        "signals": signals,
        "signal_count": len(set(signals)),
        "gpio_used": sorted(gpio_pins[pin]
                            for (ref, pin) in DESIGN.pin_owner()
                            if ref == CONTROLLER_REF and pin in gpio_pins),
        "pwm": CHANNELS,
        "pwm_slices": len(controller_slices()["used"]),
        "mclk_hz": envelope_adc_clock()["mclk_min"],
        "control_frame_hz": FRAME_RATE,
        "envelope_frame_hz": ENV_SAMPLE_HZ,
        "pump_hz": PUMP_HZ,
        "analogue_in": 1,          # the expression pedal
        "digital_in": 1,           # the tap footswitch
        "uart": 1,                 # DIN MIDI in and out
        "usb": 1,                  # USB MIDI
    }


def controller_fit():
    """Every ask against the RP2040's own number, with the margin.

    **This is the table that was missing.** The decision used to rest on
    00-current-state.md's entry 9, which says only that two other candidates
    have switching regulators; nothing said what this part has to do or whether
    it does it. Here is the second half.

    Two rows are worth reading rather than skimming:

      * **USB MIDI is one of one**, and that is not a thin margin -- the board
        needs one USB device interface and the part has one. A ratio is the
        wrong instrument on a row where the requirement is a yes;
      * **MCLK is the only row with real arithmetic behind it**, and the answer
        is not the ratio either. envelope_adc_clock() puts the floor at
        9.216 MHz because the MCP3564 multiplexes one modulator across six
        channels without pipelining them, and what matters is that 125 MHz
        divides to it by an *integer* -- a fractional divide would put the
        conversions on a jittered clock. Seven divisors do: 7 through 13,
        17.86 MHz down to 9.615. CONTROLLER_MCLK_DIVIDE picks 12.

    Every other row is between 1.0x and four orders of magnitude, which is the
    shape of a part that is comfortably sufficient rather than one chosen
    against the requirement.

    **Every countable row is now a row about the module, and one of them is
    exactly 1.00x.** The chip has not changed and three denominators have:

      * **GPIO is 18 of 26 rather than 19 of 30.** The module wires four of the
        part's thirty to its own board functions -- CONTROLLER_INTERNAL_GPIO --
        and one of the nineteen asks went away with J14, because VBUS sense is
        one of those four. 1.44x, and it is no longer the tightest row;
      * **the ADC is 1 of 3 rather than 1 of 4**, because GPIO29 is ADC3 and
        the module spends it measuring VSYS/3;
      * **MCLK's row is 1 of 1.** The requirement is a *clock output*, not a
        frequency: four pins on the chip can drive CLOCK GPOUT and three of
        them are internal to the module, so GPIO21 is the only pin on this
        board that can carry MCLK at all.

    **"tightest" is still the PWM slices at 1.33x and that is the arithmetic
    rather than a judgement.** Both figures skip the rows where `has == needs`,
    for the reason stated above about USB -- a ratio is the wrong instrument
    where the requirement is a yes -- so a row that is *exactly* met never
    appears as the tightest one however scarce it is. That was a fair
    simplification while the only such row was USB, and the module added a
    second one that is not like it at all: USB is a peripheral the part either
    has or does not, and CLOCK GPOUT is a pool of four with three of them
    spent by somebody else.

    So the return carries `exactly_met` beside `tightest`, and the honest
    reading of the table is two sentences rather than one: **the tightest
    ratio is the PWM slices at 1.33x, and the rows with no spare at all are
    USB and the clock output.** There is no second CLOCK GPOUT to move MCLK to
    if GPIO21 is ever wanted for something else, so a future change that needs
    that pin needs a different clock strategy -- which is exactly the sort of
    thing the QFN's twelve spare pins were hiding.

    **PWM_CARRIER is in the table as margin and not as a reason**, and the
    distinction matters because it is the one place this board's arithmetic
    already depends on this part's clock. 125 MHz / 2^12 = 30.5 kHz, which
    pwm_ripple() puts 83 dB down for 0.0027 dB of gain error. A different clock
    would land somewhere else and also be fine -- the CV filter has 15 to 20 dB
    of rejection to spare -- so the number is a consequence of the choice, not
    an argument for it.
    """
    asks = controller_asks()
    mclk = asks["mclk_hz"]
    divisors = [d for d in range(1, 64)
                if ENV_ADC_MCLK_RANGE[0]
                <= CONTROLLER_CLOCK_TYPICAL_HZ / d <= ENV_ADC_MCLK_RANGE[1]
                and CONTROLLER_CLOCK_TYPICAL_HZ / d >= mclk]
    fitted = CONTROLLER_CLOCK_TYPICAL_HZ / CONTROLLER_MCLK_DIVIDE
    # The chip's four CLOCK GPOUT pins, and how many of them the module lets
    # out. Read off CONTROLLER_GPIO_FUNCTIONS rather than counted by hand, so
    # that the row is a consequence of the two tables rather than a third claim.
    gpout = [gpio for gpio, fns in CONTROLLER_GPIO_FUNCTIONS.items()
             if fns[3] and fns[3].startswith("CLOCK GPOUT")]
    gpout_exposed = [g for g in gpout if g in CONTROLLER_EXPOSED_GPIO]
    rows = [
        # **The denominator is the module's and not the chip's**, which is the
        # whole of what this swap did to this table. CONTROLLER_GPIO is still
        # 30 and is still true about the RP2040; nothing on this board can
        # reach four of them.
        ("signals on GPIO", asks["signal_count"], len(CONTROLLER_EXPOSED_GPIO),
         f"of the part's {CONTROLLER_GPIO}, module exposes", "count"),
        ("MCLK on a CLOCK GPOUT pin", 1, len(gpout_exposed),
         f"of the part's {len(gpout)} -- GPIO21, and there is no second one",
         "count"),
        # **Slices and not outputs, and the change is a correction.** This
        # counted six PWM against the part's sixteen *outputs*, which is the
        # wrong denominator for the thing spec section 4.2 asks for: a slice
        # is one counter with two outputs, so two channels on one slice cannot
        # be staggered against each other. Six of eight rather than six of
        # sixteen, and the assignment in CONTROLLER_MAP spends six different
        # slices for exactly this reason. controller_slices() is the check.
        ("PWM carriers, one slice each", asks["pwm_slices"],
         CONTROLLER_PWM_SLICES,
         f"slices, {CONTROLLER_PWM_OUTPUTS} outputs", "count"),
        ("MCLK for the envelope ADC", mclk, fitted,
         f"125 MHz / {CONTROLLER_MCLK_DIVIDE}, one of "
         f"{len(divisors)} integer divides", "Hz"),
        ("control frame, all channels", asks["control_frame_hz"] * CHANNELS,
         CONTROLLER_CLOCK_TYPICAL_HZ, "clk_sys", "Hz"),
        ("envelope frame, all channels", asks["envelope_frame_hz"] * CHANNELS,
         CONTROLLER_CLOCK_TYPICAL_HZ, "clk_sys", "Hz"),
        ("the fail-safe pump on a GPIO", asks["pump_hz"],
         CONTROLLER_CLOCK_TYPICAL_HZ, "clk_sys", "Hz"),
        ("expression pedal", asks["analogue_in"],
         len([g for g in CONTROLLER_ADC_GPIO if g in CONTROLLER_EXPOSED_GPIO]),
         f"of the part's {CONTROLLER_ADC_CHANNELS} ADC channels -- ADC3 "
         f"measures VSYS on the module", "count"),
        ("DIN MIDI in and out", asks["uart"], CONTROLLER_UARTS,
         "UARTs", "count"),
        ("SPI to the envelope ADC", 1, CONTROLLER_SPI,
         "SPI controllers", "count"),
        ("USB MIDI", asks["usb"], 1, "USB 1.1 device", "count"),
    ]
    scalable = [has / needs for _, needs, has, _, _ in rows if has != needs]
    counted = min(((has / needs, name) for name, needs, has, _, units in rows
                   if units == "count" and has != needs), default=(0.0, ""))
    return {
        "rows": [{"asked": name, "needs": needs, "has": has, "units": units,
                  "note": note, "ratio": has / needs if needs else float("inf")}
                 for name, needs, has, note, units in rows],
        "tightest": min(scalable),
        "tightest_count": counted[0],
        "tightest_count_row": counted[1],
        # The rows `tightest` cannot see, named rather than left to be
        # inferred from a ratio of 1.00 that never gets printed as the answer.
        "exactly_met": [name for name, needs, has, _, units in rows
                        if units == "count" and has == needs],
        "mclk_divisors": divisors,
        "mclk_hz": fitted,
        "mclk_margin": fitted / mclk,
        # Margin, stated as margin. See the docstring.
        "pwm_carrier_hz": PWM_CARRIER,
        "pwm_carrier_from_clock": CONTROLLER_CLOCK_TYPICAL_HZ / 2 ** PWM_BITS,
    }


def controller_package():
    """Two pitches, and the one that is fitted is not a question any more.

    **The module is 2.54 mm on 1.6 mm pads and it clears the top rung of
    rules.fan_out_class() by two orders of the quantity that matters.** There
    is nothing to derive about reaching it: a track starts inside one of those
    pads at every phase of every grid this project has ever considered, and the
    nearest neighbouring pad is 0.94 mm of bare laminate away. This function
    returns both rungs -- the module's and the QFN's -- because the second one
    is what moved rules.COPPER_OZ to 1 oz and rules.TRACK_MM to 0.09, and a
    decision to move it back has to be taken against the derivation rather
    than instead of it. fabrication-class.md is that decision and this is its
    input.

    **What the swap actually retired is one class of problem and not one
    part.** rules.pad_reach(), rules.track_offset_limit(), the counting limit,
    the jog condition and route.Grid.escape() were all written for a 0.40 mm
    pitch; every one of them is still correct and none of them is exercised by
    anything on this board. The fan-out went dormant when the class moved and
    it is *gone* now, with route.py -- which is this repo's rule about a
    declaration nothing is obliged to use, applied to code.

    **And the ladder is what says the module is safe rather than what says it
    is convenient**, which is the distinction the QFN pass paid for. 2.54 mm
    is not "obviously fine"; it is `limit >= grid / 2` with a limit of
    1.145 mm, and the arithmetic is below.

    ----------------------------------------------------------------------
    **The QFN derivation, kept whole.** Can this router reach a 0.40 mm pin
    pitch? No, and it is arithmetic.

    **The gate nobody had looked for, because every package on this board so
    far has been a SOIC or a TSSOP.** rules.fan_out_class() is the ladder and
    the RP2040's QFN-56 falls off the bottom of it on two independent counts,
    neither of which a placement or a rotation touches:

      * **the escape is too wide.** A 0.40 mm pitch on 0.20 mm pads -- and
        0.20 is already the widest a pad may be, because two pads are two nets
        and `pin_pitch - clearance` is 0.20 -- leaves 0.30 mm from a pad's
        centre line to its neighbour's near edge. A track laid there has to fit
        `clearance + track / 2` into 0.30, so the widest legal escape is
        **0.20 mm against this board's 0.25**. It is also under the board's own
        min_track_width rule, which is a rule rather than a preference;
      * **there are not enough cells.** An escape ends on a grid cell and may
        move at most half a pitch across the row to get there, so pins map onto
        grid lines in order -- and 0.40 mm of pitch on a 0.50 mm grid means two
        pins have to share a line. Two nets cannot own one cell. Fourteen pins
        a side over 5.2 mm want fourteen lines and the grid offers eleven.

    **The second one is why a thinner escape is not the answer on its own.**
    0.15 mm of track clears by 25 um and is inside the 2 oz class this board is
    already ordered at, so the fabricator does not care -- but the counting
    limit is about the *grid*, and the grid is `track + clearance + margin`.
    Bringing it under 0.40 mm means bringing the class to the 2 oz minimum,
    0.15/0.15, for all 164 nets and 1500 pads on the board. That is a
    fabrication decision and a re-route of everything, and it is exactly the
    trade rules.class_table() prices -- for a different reason than the one
    that function was written for, which was the corridor between two SOIC
    pins.

    **There is a third condition and its absence made this function wrong.** The
    two above were derived and a "2 oz minimum, 0.15/0.15, clears it" was
    written under them -- because at that class the escape fits and the pins get
    a grid line each. They do. What no one had derived is that the **jog** is
    ordinary track pointing at a neighbour 0.40 mm away, and two tracks need
    `clearance + track` between centres:

        0.40 - grid / 2  >=  clearance + track

    At 0.15/0.15 that is 0.225 against 0.30 and it fails, and unlike the TSSOP
    it cannot be rescued by phase: rules.fan_out_class() computes whether the
    arithmetic *forbids* two adjacent escapes pointing the same way, and at
    0.65 mm on a 0.5 mm grid it does while at 0.40 on 0.35 it does not. So
    adjacent QFN escapes can point into each other, and route.escape_clearances()
    refuses the second one.

    **How the wrong claim survived is the part to keep.** Two conditions were
    enumerated, both were true, and the conclusion was stated as though the
    enumeration were complete -- a rule whose stated *test* was narrower than
    its stated *mechanism*, which is the failure floorplan.CROSSING_RULE
    records one artefact along. Nothing would have caught it either: no board
    has a 0.40 mm part on it, so there was nothing for a check to fail against.
    It was caught by asking the arithmetic for the class rather than reading a
    class off a table.

    **rules.coarsest_class_for() solves it instead of tabulating**, and the
    answer is **0.12/0.12 mm or finer** -- below JLCPCB's 0.15 mm 2 oz floor and
    above its 0.09 mm one. So the only listed class that works is 0.09/0.09,
    which is **1 oz outer copper only**: the copper weight is the price and no
    intermediate class avoids paying it. At 0.09/0.09 the grid is 0.23 mm, the
    offset limit rises to 0.165 mm against a 0.115 mm worst phase, and **no pad
    on the package needs an escape at all** -- the fan-out becomes unnecessary
    rather than sufficient.

    Two things that decision drags with it, and neither is settled here:
    2.8x to 4.7x the grid cells for the whole board, on a router whose work is
    superlinear in that; and the coil nets, which carry 93 mA and would be at
    0.09 mm of 1 oz copper unless they are given a width of their own -- and
    route.py draws one width. rules.grid_cost() is the first; the second wants
    the IPC-2221 curve read rather than assumed.

    The alternative is a spreading fan: outer pins running further out and
    turning further across, in lanes, with a width per escape. That breaks the
    counting limit honestly and it is a different mechanism from the single jog
    route.Grid.escape() lays. Either way it is a pass of its own.
    """
    rung = rules.fan_out_class(CONTROLLER_PIN_PITCH_MM, CONTROLLER_PAD_WIDTH_MM)
    qfn = rules.fan_out_class(CONTROLLER_QFN_PIN_PITCH_MM,
                              CONTROLLER_QFN_PAD_WIDTH_MM)
    return {
        **rung,
        "fitted_pitch_mm": CONTROLLER_PIN_PITCH_MM,
        "pins": len(CONTROLLER_MODULE_PINS) + len(CONTROLLER_MODULE_GND_PINS),
        "pins_per_side": 20,
        # The package this project does not fit, kept as the input to the
        # fabrication-class decision rather than deleted with the part.
        "qfn": {**qfn, "pitch_mm": CONTROLLER_QFN_PIN_PITCH_MM,
                "pins": 56, "pins_per_side": 14},
        # **Every listed class against both pitches.** The QFN column is what
        # the class would have to become for its counting limit to clear, and
        # is why 0.09/0.09 was fitted; the module column is what the class may
        # now become without the controller having an opinion, which is the
        # question fabrication-class.md is re-opened to answer. Read off
        # rules.FAB_CLASSES rather than chosen.
        "classes": [
            {"class": name, "track_mm": track, "clearance_mm": clearance,
             "grid_mm": rules.route_pitch(track=track, clearance=clearance),
             **rules.fan_out_class(CONTROLLER_PIN_PITCH_MM,
                                   CONTROLLER_PAD_WIDTH_MM,
                                   grid=rules.route_pitch(track=track,
                                                          clearance=clearance),
                                   track=track, clearance=clearance),
             "qfn": rules.fan_out_class(
                 CONTROLLER_QFN_PIN_PITCH_MM, CONTROLLER_QFN_PAD_WIDTH_MM,
                 grid=rules.route_pitch(track=track, clearance=clearance),
                 track=track, clearance=clearance)}
            for name, track, clearance, _ in rules.FAB_CLASSES],
    }


def pico_backdrive():
    """May this board drive the module's 3V3 pin and hold its SMPS off?

    **No, and the reason is that the datasheet settles the neighbouring
    question rather than this one.** This function exists to record the read
    rather than the conclusion, because the conclusion is a refusal and a
    refusal with no arithmetic under it is the easiest thing in this repo to
    quietly reverse.

    The topology it would buy is the cheap one: leave MCU_DCDC exactly as
    drawn, take its 3.3 V straight to pin 36, tie 3V3_EN low, and the module's
    own converter never runs. One conversion instead of two, and mcu_supply()
    prices it at **32.1 mA of +Vout against 35.4 available** -- it fits, where
    the topology that is drawn does not fit at its pessimistic corner. So the
    arithmetic argues for it and the documents decide against it.

    **What the Pico datasheet says, in full.** Section 2.1: "3V3 is the main
    3.3 V supply to RP2040 and its I/O, *generated by the on-board SMPS*. This
    pin can be used to power external circuitry". And "3V3_EN connects to the
    on-board SMPS enable pin ... To disable the 3.3 V (which also de-powers the
    RP2040), short this pin low." Section 4.5, "Powering Pico", then enumerates
    every sanctioned way in -- the micro-USB, VSYS from "your preferred power
    source (in the range ~1.8 V to 5.5 V)", and ORing a second source into VSYS
    through a diode or a P-FET. **Pin 36 is an output in all four sentences and
    appears in none of the three topologies.**

    **What the RT6150 datasheet says, and it is closer than it looks.** Three
    things, and they are worth having straight:

      * the feature list carries "VOUT Disconnected from VIN during Shutdown",
        and the Enable section says "In shutdown mode, the converter stops
        switching, internal control circuitry is turned off, and the load is
        disconnected from the input";
      * the two switch-leakage rows bound what an idle output stage passes at
        5 uA and 10 uA maximum, and a *switch leakage* figure is by its nature
        a figure about switches that are off;
      * the absolute maximum table rates VOUT to 6 V **absolutely** -- one line
        for "VOUT, VIN, EN, PS, VINA, FB", not referenced to VIN -- so 3.3 V on
        that pin with the input at zero is inside a stated rating.

    **And here is the gap.** Every one of those is stated with the input
    present: the electrical table's header is "VIN = VOUT = 3.6V", and the one
    sentence that describes what the output may do in shutdown says "the output
    voltage can *drop below* the input voltage". The condition this topology
    needs is the other one -- VIN absent, VOUT held above it by somebody else
    -- and the document neither permits it nor forbids it. It is a reading, and
    a good one, and it is still a reading.

    **Which is the same rule that refused the TPS560430X3F**, one block over:
    the fixed-output sibling would have saved two resistors and its FB
    connection is nowhere stated, only implied by two table entries, and "an
    inferred connection on the pin that sets a rail is not worth two
    resistors". Here the inference is on the pin that *is* the rail, and what
    it would buy is larger -- which makes it more tempting and not more
    documented. The honest form of the trade is stated rather than resolved:
    this refusal costs the board its pessimistic corner, and mcu_supply() says
    by how much.

    **One thing it is not.** It is not a hazard nobody has noticed: if the
    topology were ever taken, 3V3_EN would have to be *driven* low and not left
    to the module's own 100 kOhm pull-up, because that pull-up goes to VSYS and
    VSYS comes up whenever a USB cable is plugged in. A pull-up to a rail that
    is sometimes present is a pull-up that sometimes enables a second regulator
    into a rail this board is already driving.
    """
    return {
        "permitted_by_pico_datasheet": False,
        "permitted_by_rt6150_datasheet": None,
        "documented_shutdown_condition": "VIN present, VOUT free to fall",
        "condition_this_topology_needs": "VIN absent, VOUT held above it",
        "vout_abs_max_v": PICO_SMPS_VOUT_ABS_MAX,
        "switch_leakage_ua": PICO_SMPS_SWITCH_LEAKAGE_UA,
        "sanctioned_inputs": ("VBUS", "VSYS", "VSYS through an ORing diode"),
        "decision": "refused -- feed VSYS",
    }


def pico_smps_beat():
    """A third switcher on the board, and what its frequency is worth.

    **supply_beat()'s subject was two converters and there are three.** The
    mixer's 45 kHz pump, this board's TMR 6 at 522-638 kHz, U22 at
    935-1265 kHz, and now the module's RT6150 at 800-1200 kHz -- and the rule
    spec section 1.1 sets is about the first pair only. What supply_beat()
    already established carries over unchanged and is the reason this row is
    short: the rule is a fundamental-only rule, no frequency clears every
    harmonic of a sawtooth, and what makes the arrangement safe is isolation
    and the second-order size of a difference-frequency product.

    **What is new is that this one is not a part this design chose**, so the
    only lever is the PS pin. In power-save mode -- the module's own default --
    the RT6150 pulse-skips, and a pulse-skipping converter's repetition rate
    falls with load until it is in the audio band. That is not a beat to
    compute, it is a source *at* audio, and it is the same objection
    mcu_dcdc_light_load() raised against a PFM buck. Driving GPIO23 high buys
    the stated band, and the band is what makes the arithmetic below possible
    at all.

    **The overlap is the interesting number.** U22 is 935-1265 kHz and the
    RT6150 is 800-1200 kHz, and those bands *intersect* -- so two units can
    land on the same frequency and the beat between them passes through zero.
    Beyond dividing, that is what supply_beat() already says about the pump's
    harmonics arriving at a third part: a beat frequency is not a thing to
    design a margin into, and the defence is amplitude rather than separation.
    """
    # Both ends of the stated band, through supply_beat() itself rather than a
    # second copy of its harmonic search -- which is the fault that function
    # already records about its own harmonic count.
    ends = [supply_beat(f_khz=f) for f in PICO_SMPS_KHZ]
    worst_vs_pump = min(end["worst_beat_khz"] for end in ends)
    overlap = (max(PICO_SMPS_KHZ[0], MCU_DCDC_KHZ[0]),
               min(PICO_SMPS_KHZ[1], MCU_DCDC_KHZ[1]))
    return {
        "khz": PICO_SMPS_KHZ,
        "typ_khz": PICO_SMPS_KHZ_TYP,
        "clears_the_minimum": PICO_SMPS_KHZ[0] >= SUPPLY_MIN_KHZ,
        "worst_beat_against_pump_khz": worst_vs_pump,
        "pump_worst_beat_khz": supply_beat()["worst_beat_khz"],
        "overlaps_mcu_dcdc": overlap[0] <= overlap[1],
        "overlap_khz": overlap if overlap[0] <= overlap[1] else None,
        "ps_gpio": PICO_SMPS_PS_GPIO,
        "pfm_is_the_hazard": "a pulse-skipping rate falls into the audio band "
                             "with load -- see mcu_dcdc_light_load()",
    }


def controller_supply():
    """What the controller costs the converter, and the topology decides it.

    **The linear chain cannot carry it and the arithmetic is v5_regulator()'s,
    one rail further down.** V3V3 is an MCP1700 off V5, V5 is an NCP1117 off
    VA+, and VA+ is the converter's +Vout -- so a milliamp of 3.3 V is a
    milliamp of *twelve* volts at the converter's pin, dissipated twice on the
    way. supply_fit() leaves **35.4 mA** of the part's 250, and that is the
    whole budget for the controller, its flash, its crystal, its USB PHY and
    its MIDI.

    **The RP2040's own measured range straddles that, and the decision does not
    depend on where in the range it lands** -- which is the useful thing about
    it. Table 637's heaviest use case is 52.1 mA on the 3.3 V side and its
    lightest *active* one is 19.2 mA; the top of that fails outright, and the
    bottom leaves 16.2 mA for a QSPI flash whose read current is tens of
    milliamps, a DIN MIDI current loop and an opto-isolator. Neither end is a
    board that works, so MEASURED["mcu_rail_ma"] records the range without
    anything waiting on it.

    **A switcher from VA+ is the only topology with room, and the honest way to
    say so does not need an efficiency figure.** A converter's input current is
    at best `vout / vin` times its output current -- that is conservation of
    energy and not a datasheet reading -- so the floor is

        3.3 / 12 x 52.1 mA  =  14.3 mA        at 100 % efficiency

    and the real part draws `that / efficiency`. So the question "does a
    switcher fit" has an answer with no invented number in it: it fits at any
    efficiency above

        14.3 / 35.4  =  40 %

    and there is no buck converter that is not. Quoting 85 % here would have
    been a plausible number about a part nobody has chosen, which is the thing
    section 6 of the spec forbids; the bound is stronger anyway, because it
    cannot be wrong.

    **What it costs is a switching aggressor on VA_RAW and MDGND**, sharing
    both with the audio domain -- which is why the requirement below is stated
    as numbers rather than a part, exactly as supply_requirement() stated the
    converter's before a part existed. supply_beat() is what has to price its
    frequency, and note what that function already found: the >= 300 kHz rule is
    a fundamental-only rule, so a second unit's frequency has to be checked
    against the mixer's pump harmonics *and* against this converter's own
    522-638 kHz band. Two switchers on one board beat with each other as well.

    ------------------------------------------------------------------------
    **The module moved this and did not remove it, which is the thing to carry
    from the swap.** The controller is a Raspberry Pi Pico now, and a Pico is
    a 3.3 V load with a converter already bolted to it -- so the question
    stops being "what makes 3.3 V" and becomes "where does this board hand the
    module its power". Section 4.5 of the Pico datasheet allows three answers
    and pico_backdrive() shows that the cheap fourth one is not among them.

    **The topology, and it changes no value in the switcher block.** U22 stays
    exactly as it was drawn -- 12 V in, 3.3 V out, the same divider, the same
    12 uH, the same input node -- and its output goes one node further: through
    D806 to the module's VSYS pin, which is Figure 16 of the Pico datasheet.
    The module's own RT6150 then makes the 3.3 V its RP2040 and its flash run
    on, and brings it back out on pin 36 as VMCU, where this board's opto, tap
    pull-up, pedal divider and MIDI driver hang off it -- 6.8 mA against the
    300 mA that section allows on that pin.

    **Three consequences, and the first is the whole cost of the refusal:**

      * **two converters in series, so the two efficiencies multiply.**
        mcu_supply() has always stated the efficiency at which the budget stops
        closing, and that threshold has not moved -- 67.8 % -- but it is now a
        threshold on a *product*. The pessimistic corner of the two
        assumptions is 0.660 and it fails. This is stated rather than rounded,
        and the levers are named where they always were, in
        MEASURED["mcu_dcdc_efficiency"].when_wrong;
      * **D806 is not optional and it is not there for the drop.** Without it,
        a USB cable pushes VBUS through the module's own D1 onto VSYS and from
        there back into this board's 3.3 V rail -- a host supply back-powering
        a converter output. The Pico datasheet's own sentence is that the
        diodes are what prevent "either supply from back-powering the other".
        What it costs is 0.29 V at 100 mA, so VSYS sits at about 3.0 V, which
        is 1.2 V inside the module's stated 1.8-5.5 V range;
      * **the >= 300 kHz rule now has a third unit under it and no part to
        choose.** pico_smps_beat() is that arithmetic and its answer is a line
        of firmware: GPIO23 high, or the module's converter pulse-skips at a
        rate that falls into the audio band with load.

    ------------------------------------------------------------------------
    **The gate was closed by U22, a TPS560430XF**, and what this function still
    does is state the requirement; MCU_DCDC and mcu_supply() are the answer,
    mcu_dcdc_beat() prices the frequency, and mcu_dcdc_injection() is what the
    aggressor is worth at the control port. Three things drawing the QFN
    version changed in what is written above:

      * **the input goes to VA_RAW and not to VA+**, one node ahead of R804 --
        the same choice v5_regulator()'s input makes and for a sharper reason.
        The switcher's input current is a pulse train, and taking it from
        behind the rail filter would put that pulse train's own IR drop on the
        rail the six channels share. In front of it, the filter that exists for
        the TMR's 75 mVp-p attenuates this one's ripple too, at twice the
        frequency and so about 6 dB harder;
      * **the "any efficiency above 40 %" bound was computed for the MCU
        alone.** The rail also carries the flash, the opto, the MIDI loop and
        the pedal, and mcu_supply() counts them: the floor is 23.6 mA of +Vout
        rather than 14.3, and the efficiency that clears it is about 67 %. The
        bound is still one that cannot be wrong -- it is conservation of energy
        divided by a headroom -- and it is no longer comfortable, which is the
        honest description of a 250 mA converter delivering 246;
      * **the switching frequency is a band and it had to be.** A part whose
        frequency collapses with load -- any PFM buck -- was excluded by
        mcu_dcdc_light_load() before any part was compared, for the reason
        supply_beat() gives about the RCC-topology TMR 6.
    """
    # **include_mcu=False, and getting this wrong is instructive.** With the
    # block drawn, supply_fit()'s headroom already has the switcher's input
    # current subtracted from it, so asking it here computes "the efficiency at
    # which a switcher fits in what is left after the switcher" -- which came
    # out as 432 % and printed itself into the report before anybody read it.
    # The gate was argued from the budget *before* this block, and that is the
    # question this function is still asking.
    fit = supply_fit(include_mcu=False)
    head = fit["positive_headroom_ma"]
    low = sum(rail[1] for rail in CONTROLLER_USE_CASES["BOOTSEL idle"])
    high = sum(rail[1] for rail in CONTROLLER_USE_CASES["Popcorn"])
    ratio = V3V3_VOLTS / SUPPLY_VOUT
    return {
        "headroom_ma": head,
        "mcu_ma": (low, high),
        "linear_cost_ma": (low, high),
        "linear_fits": (low <= head, high <= head),
        "linear_watts": ((SUPPLY_VOUT - V5_VOLTS) * high * 1e-3
                         + (V5_VOLTS - V3V3_VOLTS) * high * 1e-3),
        "switcher_ratio": ratio,
        "switcher_floor_ma": (low * ratio, high * ratio),
        "switcher_min_efficiency": high * ratio / head,
        # The requirement on a part nobody has chosen, in the shape
        # supply_requirement() uses for the converter.
        "requires": {
            "vin_v": SUPPLY_VOUT,
            "vout_v": V3V3_VOLTS,
            "iout_ma": high,
            "min_efficiency": high * ratio / head,
            "min_khz": SUPPLY_MIN_KHZ,
            "beats_the_pump_at_khz": supply_beat()["worst_beat_khz"],
            "and_the_converter_at_khz": SUPPLY_KHZ,
        },
        # The part that meets it, and the rail as drawn rather than as asked
        # for. mcu_supply() counts the whole 3.3 V load; the two lines above
        # are the MCU alone, kept because they are what the gate was argued
        # from.
        "part": MCU_DCDC,
        "fitted": mcu_supply(),
    }


# ---------------------------------------------------------------------------
# The controller's pins, and which net lands on which one
# ---------------------------------------------------------------------------
# **Two tables and they do different jobs.** CONTROLLER_PINS is the package --
# RP2040 datasheet section 5.5.2, tables 615 to 621, transcribed name by name
# so that a wire lands on a number somebody read. CONTROLLER_GPIO_FUNCTIONS is
# the multiplexer -- Table 2, "General Purpose Input/Output (GPIO) Bank 0
# Functions" -- and it exists so that CONTROLLER_MAP's assignment of a net to a
# GPIO can be *checked* rather than believed.
#
# That third table is the design decision and the other two are the datasheet.
# controller_pin_map() joins them and Design.check_controller_functions()
# refuses an assignment the part cannot honour -- which is the failure mode a
# pin assignment has: every pin looks the same on a schematic, and "GPIO14 is
# SPI0 SCK" is exactly as easy to write as the truth.
CONTROLLER_IOVDD_ABS_MAX = 3.63        # Table 622, I/O supply voltage
CONTROLLER_VIH = 2.0                   # Table 625, at IOVDD = 3.3 V
CONTROLLER_VIL = 0.8
CONTROLLER_VOL = 0.5                   # maximum, any drive strength
CONTROLLER_VOH = 2.62                  # minimum, any drive strength
CONTROLLER_VHYS = 0.2                  # Schmitt trigger, at 3.3 V
CONTROLLER_PULL_KOHM = (50.0, 80.0)    # RPU / RPD
CONTROLLER_ADC_RIN = 100_000.0         # Table 627, minimum
CONTROLLER_ADC_ENOB = 8.7
CONTROLLER_ADC_BITS = 12
# Section 4.9.2: "The ADC input is capacitive, and when sampling, it places
# about 1pF across the input", and "Capturing a sample takes 96 clock cycles
# (96 x 1/48MHz) = 2us per sample".
CONTROLLER_ADC_CSAMPLE = 1e-12
CONTROLLER_ADC_CONVERSION_S = 2e-6
# Section 2.9: "IOVDD should be decoupled with a 100nF capacitor close to each
# of the chip's IOVDD pins", the same sentence for DVDD, USB_VDD and ADC_AVDD,
# and "A 1uF capacitor should be connected between VREG_VIN and ground close to
# the chip's VREG_VIN pin". The minimal design's section 2.1.3 adds the output:
# "We must place 1uF capacitors close to both the input (VREG_IN) and the
# output (VREG_OUT)".
#
# **The reference design does not do this and says why.** It shares one
# capacitor between pins 48 and 49 "as there is not a lot of room on that side
# of the device ... we have decreased the complexity and cost, at the expense
# of having less decoupling capacitance". That is a two-layer board with parts
# on one side; this is a four-layer board with a ground plane under the part,
# so the vendor's own rule -- one per pin -- is what is drawn.
CONTROLLER_DECOUPLE = "100n/50V X7R"
CONTROLLER_VREG_C = "1u/16V X7R"
CONTROLLER_VREG_C_FARADS = 1e-6
CONTROLLER_RUN_PULLUP = "10k 1%"
CONTROLLER_BOOT_SERIES = "1k 1%"

# Section 5.5.2.2, tables 615-621. Every entry is a name and a number read off
# the datasheet; the six IOVDD and two DVDD pins are lists because the part has
# more than one of each and each one gets its own capacitor.
# The KiCad symbol names the analogue-capable pins GPIO26_ADC0 and so on, so
# the netlist has to as well. One place, here -- and note that ADC3 is on the
# list because the *chip* has it, while CONTROLLER_INTERNAL_GPIO is what says
# the module does not bring it out. Two facts, two tables, and
# check_controller_pins_exposed() is where they meet.
CONTROLLER_ADC_GPIO = {26: "ADC0", 27: "ADC1", 28: "ADC2", 29: "ADC3"}


def _gpio_symbol(gpio):
    """The symbol's own name for a GPIO -- 'GPIO14', or 'GPIO26_ADC0'."""
    if gpio in CONTROLLER_ADC_GPIO:
        return f"GPIO{gpio}_{CONTROLLER_ADC_GPIO[gpio]}"
    return f"GPIO{gpio}"


# **Derived from CONTROLLER_MODULE_PINS rather than typed a second time.** The
# QFN's version of this was a transcribed table of 30 entries and it had to be,
# because a package pin number is not a function of anything. A module's is:
# the pinout above is the transcription, and this is a lookup into it. A GPIO
# missing from here is a GPIO the module does not expose, which is the property
# controller_pin_map() and check_controller_pins_exposed() both read.
CONTROLLER_GPIO_PINS = {
    gpio: CONTROLLER_MODULE_PINS[_gpio_symbol(gpio)]
    for gpio in range(30) if _gpio_symbol(gpio) in CONTROLLER_MODULE_PINS
}

# Table 2, columns F1 (SPI), F2 (UART), F4 (PWM), F8 (CLOCK) and F9 (USB).
# F3 is I2C and F5-F7 are SIO and the two PIOs, which are on every pin -- Table
# 3, "SIO ... must be selected for the processors to drive a GPIO" -- so a "SIO"
# assignment below is checked against the pin existing rather than against this
# table.
CONTROLLER_GPIO_FUNCTIONS = {
    0:  ("SPI0 RX",  "UART0 TX",  "PWM0 A", None,           "USB OVCUR DET"),
    1:  ("SPI0 CSn", "UART0 RX",  "PWM0 B", None,           "USB VBUS DET"),
    2:  ("SPI0 SCK", "UART0 CTS", "PWM1 A", None,           "USB VBUS EN"),
    3:  ("SPI0 TX",  "UART0 RTS", "PWM1 B", None,           "USB OVCUR DET"),
    4:  ("SPI0 RX",  "UART1 TX",  "PWM2 A", None,           "USB VBUS DET"),
    5:  ("SPI0 CSn", "UART1 RX",  "PWM2 B", None,           "USB VBUS EN"),
    6:  ("SPI0 SCK", "UART1 CTS", "PWM3 A", None,           "USB OVCUR DET"),
    7:  ("SPI0 TX",  "UART1 RTS", "PWM3 B", None,           "USB VBUS DET"),
    8:  ("SPI1 RX",  "UART1 TX",  "PWM4 A", None,           "USB VBUS EN"),
    9:  ("SPI1 CSn", "UART1 RX",  "PWM4 B", None,           "USB OVCUR DET"),
    10: ("SPI1 SCK", "UART1 CTS", "PWM5 A", None,           "USB VBUS DET"),
    11: ("SPI1 TX",  "UART1 RTS", "PWM5 B", None,           "USB VBUS EN"),
    12: ("SPI1 RX",  "UART0 TX",  "PWM6 A", None,           "USB OVCUR DET"),
    13: ("SPI1 CSn", "UART0 RX",  "PWM6 B", None,           "USB VBUS DET"),
    14: ("SPI1 SCK", "UART0 CTS", "PWM7 A", None,           "USB VBUS EN"),
    15: ("SPI1 TX",  "UART0 RTS", "PWM7 B", None,           "USB OVCUR DET"),
    16: ("SPI0 RX",  "UART0 TX",  "PWM0 A", None,           "USB VBUS DET"),
    17: ("SPI0 CSn", "UART0 RX",  "PWM0 B", None,           "USB VBUS EN"),
    18: ("SPI0 SCK", "UART0 CTS", "PWM1 A", None,           "USB OVCUR DET"),
    19: ("SPI0 TX",  "UART0 RTS", "PWM1 B", None,           "USB VBUS DET"),
    20: ("SPI0 RX",  "UART1 TX",  "PWM2 A", "CLOCK GPIN0",  "USB VBUS EN"),
    21: ("SPI0 CSn", "UART1 RX",  "PWM2 B", "CLOCK GPOUT0", "USB OVCUR DET"),
    22: ("SPI0 SCK", "UART1 CTS", "PWM3 A", "CLOCK GPIN1",  "USB VBUS DET"),
    23: ("SPI0 TX",  "UART1 RTS", "PWM3 B", "CLOCK GPOUT1", "USB VBUS EN"),
    24: ("SPI1 RX",  "UART1 TX",  "PWM4 A", "CLOCK GPOUT2", "USB OVCUR DET"),
    25: ("SPI1 CSn", "UART1 RX",  "PWM4 B", "CLOCK GPOUT3", "USB VBUS DET"),
    26: ("SPI1 SCK", "UART1 CTS", "PWM5 A", None,           "USB VBUS EN"),
    27: ("SPI1 TX",  "UART1 RTS", "PWM5 B", None,           "USB OVCUR DET"),
    28: ("SPI1 RX",  "UART0 TX",  "PWM6 A", None,           "USB VBUS DET"),
    29: ("SPI1 CSn", "UART0 RX",  "PWM6 B", None,           "USB VBUS EN"),
}

# **The assignment, and every row of it is answerable.** Net, GPIO, and the
# function that pin has to provide -- checked against the table above.
#
# Three rows are not free and the rest are:
#
#   * **the six PWM are on six different slices**, which is what spec section
#     4.2's "phase-stagger the six slices so the buffer transients don't hit
#     the reference together" requires: a slice is one counter, so two channels
#     on one slice share a phase. Six A channels of slices 0 to 5, and
#     controller_fit() counts the slices rather than the outputs for the same
#     reason;
#   * **MCLK has to be a CLOCK GPOUT, and on this module there is exactly one
#     pin that can be.** envelope_adc_clock() needs an *integer* divide of the
#     system clock, and a bit-banged or PWM-derived clock is neither integer
#     nor jitter-free. Table 3: "CLOCK GPOUTx ... Can drive a number of
#     internal clocks (including PLL outputs) onto GPIOs, with optional integer
#     divide." Four pins on the chip can do it -- GPIO21, 23, 24 and 25 -- and
#     **three of them are the module's own internal functions**, so GPIO21 is
#     not a choice among four any more, it is the only one. That row is 1 of 1
#     in controller_fit() and it is the tightest countable row on the table;
#   * ~~**VBUSD has to be a USB VBUS DET pin**~~ -- **the net is gone.** It
#     existed to sense VBUS on J14, and J14 was this board's USB receptacle.
#     The module has its own, wired to its own GPIO24, so the requirement is
#     met on the module and the divider, the connector and the net all go with
#     it. That is the honest reason the signal count fell rather than rose:
#     **18 of 26 rather than 19 of 30**, and it did not fall because anything
#     was simplified -- it fell because one of the nineteen was a job the
#     module does for itself.
#
# The four SPI signals are one peripheral's four pins, which is a constraint
# the table enforces rather than a preference: SPI0's RX, CSn, SCK and TX are
# fixed relative to each other, so choosing MISO chooses the other three.
#
# **FSDRV is a plain GPIO and that is load-bearing.** The fail-safe's whole
# mechanism is that *any* stuck state collapses the pump -- fail_states() and
# pump_timing() -- and a PWM peripheral output is precisely a source of square
# waves that survives the processor stopping. So FSDRV is toggled in software
# from the control loop, and putting it on a pin whose PWM function is
# available anyway is not the point: the point is that firmware must not use
# it. Recorded here because it is a hardware-shaped constraint on firmware, the
# same kind of record ENV_ADC_CHANNEL is.
CONTROLLER_MAP = {
    "PWM1": (0, "PWM0 A"),
    "PWM2": (2, "PWM1 A"),
    "PWM3": (4, "PWM2 A"),
    "PWM4": (6, "PWM3 A"),
    "PWM5": (8, "PWM4 A"),
    "PWM6": (10, "PWM5 A"),
    "MIDI_TX": (12, "UART0 TX"),
    "MIDI_RX": (13, "UART0 RX"),
    "OE": (14, "SIO"),
    "FSDRV": (15, "SIO"),
    "MISO": (16, "SPI0 RX"),
    "CS": (17, "SPI0 CSn"),
    "SCLK": (18, "SPI0 SCK"),
    "MOSI": (19, "SPI0 TX"),
    "IRQ": (20, "SIO"),
    "MCLK": (21, "CLOCK GPOUT0"),
    "TAP": (22, "SIO"),
    "EXPR": (26, "ADC0"),
}
# **What firmware has to hold, recorded here because nothing else in this repo
# can.** FSDRV's rule is above. This one arrived with the module:
#
#   **GPIO23 must be driven high, and it is not a signal on this board.** It is
#   the RT6150's PS pin, and low -- the module's own default -- is pulse
#   frequency modulation, whose switching frequency falls with load. That is
#   the objection mcu_dcdc_light_load() raised against a PFM buck and the
#   reason MCU_DCDC is the F suffix; here there is no suffix to buy, so the
#   same requirement is a line of firmware. pico_smps_beat() computes what it
#   is worth. It is deliberately *not* in CONTROLLER_MAP, because a map of
#   nets to pins is a map of copper and this pin has none: it is inside the
#   module, and putting it in the table would make check_controller_functions()
#   look for a net that cannot exist.
CONTROLLER_FIRMWARE_PINS = {
    PICO_SMPS_PS_GPIO: "drive high at reset: forces the module's SMPS into "
                       "fixed-frequency PWM -- see pico_smps_beat()",
}


def usb_ground_loop(current_ma=None):
    """What a USB cable does to constraint 5.2, and it is not a violation of it.

    **The hazard this block introduces, priced rather than mentioned.** DIN
    MIDI is opto-isolated because CA-033 requires it, and the reason CA-033
    requires it is a ground loop between two mains-powered boxes. USB has no
    such isolation: plugging this module into a computer ties MDGND to that
    computer's ground, and from there the loop closes through R902, R901, the
    mixer's own AGND and whatever cable carries the mixer's output back.

    **Constraint 5.2 still holds and that is exactly the point.** The rule is
    "exactly one bond between module audio ground and board AGND", and there is
    still one: R901. What a USB cable adds is a path to a *third* ground, and
    the constraint has nothing to say about it -- which is worth writing down,
    because a rule that holds while the thing it defends against happens is a
    rule somebody will quote as protection.

    What the loop injects into the audio is the current times the impedance of
    the segment it shares with the audio return, which is the bond:

        v = I x BOND_R_OHMS                 at 50 Hz, where the bond is
                                            resistance and nothing else

    The current is a property of the *installation* -- two appliances, their
    safety earths, and the difference between them -- and nothing in this repo
    can measure it, so this takes it as a parameter and reports the answer
    against the mixer's own noise floor rather than inventing a value. At a
    milliamp, which is the order a mains ground loop between two earthed boxes
    reaches, it is 40 uV against a 144 uV floor: **11 dB down, at 50 Hz, where
    the ear is not forgiving**. That is not a fault the board can fix and it is
    not nothing.

    Three answers exist and none of them is free, so none is drawn:

      * **a USB isolator** -- an ADuM3160 class part, a second isolated 3.3 V
        supply for its far side, and a barrier this file would then have to
        model. It is the honest fix and it is a block of its own;
      * **unplug it.** USB here is for firmware and configuration; the
        instrument does not need it while it is being played, and MIDI's own
        DIN pair is isolated by construction;
      * **accept it**, which is what every bus-powered USB-MIDI interface in
        the world does.

    Recorded so that the second one is a decision somebody took rather than a
    habit, and so that the first one is costed if the measurement says it is
    needed.
    """
    current = (1.0 if current_ma is None else current_ma) * 1e-3
    volts = current * BOND_R_OHMS
    floor = MEASURED["noise_floor"].value
    return {
        "current_ma": current * 1e3,
        "bond_ohms": BOND_R_OHMS,
        "volts": volts,
        "floor_v": floor,
        "below_floor_db": 20 * math.log10(floor / volts) if volts else math.inf,
        "hz": 50.0,
        # The one bond is still one bond: this is a path to a third ground, not
        # a second path to the mixer's.
        "bonds_to_mixer": 1,
    }


def controller_pin_map():
    """Net -> GPIO -> package pin -> the datasheet function that allows it.

    The join, done once, so that every consumer -- the netlist, the schematic,
    verify.py and the report -- reads the same table rather than repeating the
    assignment. Returns one row per net, in GPIO order.
    """
    rows = []
    for net, (gpio, function) in sorted(CONTROLLER_MAP.items(),
                                        key=lambda kv: kv[1][0]):
        # **KeyError here is the module refusing a pin it does not bring out**,
        # and it is deliberately not caught: the assignment is wrong and the
        # build must stop. check_controller_pins_exposed() is the version that
        # says so in a sentence rather than in a traceback, and it exists
        # because CONTROLLER_MAP carried GPIO25 -- the module's user LED --
        # for the whole life of the QFN, where it was a free pin.
        pin = CONTROLLER_GPIO_PINS[gpio]
        name = f"GPIO{gpio}"
        if gpio in CONTROLLER_ADC_GPIO:
            name = f"GPIO{gpio}/{CONTROLLER_ADC_GPIO[gpio]}"
        rows.append({"net": net, "gpio": gpio, "pin": pin, "name": name,
                     "function": function,
                     "available": CONTROLLER_GPIO_FUNCTIONS[gpio]})
    return rows


def controller_slices():
    """Which PWM slice each channel's carrier comes out of, and whether they
    are distinct.

    Spec section 4.2 asks for the six carriers to be phase-staggered. A slice
    is one counter with two outputs, so two channels sharing a slice share a
    phase and the stagger is unavailable to them -- which makes "six slices"
    the requirement rather than "six outputs". This is what controller_fit()
    counts.
    """
    slices = {}
    for n in range(1, CHANNELS + 1):
        gpio, function = CONTROLLER_MAP[f"PWM{n}"]
        slices[f"PWM{n}"] = (int(function.split()[0][3:]), function.split()[1])
    used = sorted({index for index, _ in slices.values()})
    return {
        "slices": slices,
        "distinct": len(used) == CHANNELS,
        "used": used,
        "available": CONTROLLER_PWM_SLICES,
        "carrier_hz": PWM_CARRIER,
        "stagger_deg": 360.0 / CHANNELS,
    }


# ---------------------------------------------------------------------------
# The controller's own 3.3 V rail -- gate 2, and it is a part decision
# ---------------------------------------------------------------------------
# **controller_supply() derived the requirement and this is the part that meets
# it.** The requirement, unchanged: V3V3 is an MCP1700 off V5 off VA+, so a
# milliamp of 3.3 V is a milliamp of *twelve* at the converter's pin, and
# supply_fit() leaves 35.4 mA of +Vout against an RP2040 whose own measured
# range is 19.2 to 52.1 mA. A switcher from VA_RAW is the only topology with
# room, and conservation of energy puts its input current at 3.3/12 of its
# output whatever the part.
#
# Texas Instruments TPS560430, SLVSE22B (September 2017, revised June 2018),
# read first-hand. Every figure below is from it with the table named.
#
# **Three properties chose this part and the first is the one nobody would
# think of.**
#
#   * **it is the FPWM version, and that is load-bearing rather than tidy.**
#     A buck that drops into pulse-frequency modulation at light load has a
#     switching frequency proportional to load -- it stops being a frequency at
#     all and becomes a rate. mcu_dcdc_light_load() computes where the boundary
#     is for the fitted inductor and this board sits below it whenever the MCU
#     is not busy, so a PFM part would spend most of its life pulse-skipping at
#     a rate that sweeps *through the audio band*, on a rail this module's own
#     amplifiers share. That is the same objection supply_beat() records
#     against the RCC-topology TMR 6 -- "a frequency that wanders cannot be
#     designed against at all" -- arriving at a second part for the same
#     reason. Section 8.4.5: "For FPWM version, TPS560430 is locked in PWM mode
#     at full load range";
#   * **the frequency is a stated band and not a typical.** Section 7.7 gives
#     the 1.1 MHz version as 0.935 to 1.265 MHz, so mcu_dcdc_beat() has
#     something to compute with. The 2.1 MHz version exists and is not fitted:
#     it costs switching loss on the one rail whose input current comes out of
#     35 mA of headroom;
#   * **Table 1 gives L, C_OUT and the divider for 1.1 MHz at 3.3 V.** 12 uH,
#     22 uF, 51 k and 22.1 k. Nothing here is chosen by this repo, which is
#     what section 6 of the spec asks for, and mcu_dcdc_output() checks the
#     divider's arithmetic against equation 7 rather than trusting the table.
#
# **The fixed-output sibling exists and is deliberately not fitted.** The
# TPS560430X3F is the same die with a 3.3 V reference and no divider -- two
# fewer parts on the board -- and its FB pin's connection is nowhere stated in
# the datasheet. The electrical table's "Fixed 3.3-V output, VFB = 3.96 V" and
# the recommended-conditions line "FB 0 to 4.5 V" only *imply* that FB goes
# straight to VOUT. An inferred connection on the pin that sets a rail is not
# worth two resistors, and this repo's rule is that a source is read rather
# than deduced from.
MCU_DCDC = "TPS560430XF"
MCU_DCDC_REF = "U22"
MCU_DCDC_MPN = "TPS560430XFDBVR"
MCU_DCDC_DATASHEET = "https://www.ti.com/lit/ds/symlink/tps560430.pdf"
MCU_DCDC_REVISION = "SLVSE22B, September 2017, revised June 2018"
# Section 6, DBV package, 6-pin SOT-23-6.
MCU_DCDC_PINS = {"CB": 1, "GND": 2, "FB": 3, "EN": 4, "VIN": 5, "SW": 6}
MCU_DCDC_VIN = (4.0, 36.0)             # section 7.3, recommended operating
MCU_DCDC_IOUT_MAX_MA = 600.0
MCU_DCDC_KHZ = (935.0, 1265.0)         # section 7.7, 1.1-MHz version
MCU_DCDC_KHZ_TYP = 1100.0
MCU_DCDC_VREF = 1.0                    # section 7.5, FB reference
MCU_DCDC_VREF_RANGE = (0.985, 1.015)   # over -40 to 125 degC
MCU_DCDC_IQ_MA = 0.120                 # non-switching, maximum
MCU_DCDC_ILIM_A = (0.8, 1.1, 1.4)      # peak inductor current limit
MCU_DCDC_THETA_JA = 173.0              # section 7.4, and see mcu_dcdc_fit()
# **Table 1's 1.1 MHz / 5 V row, and it moved from the 3.3 V one.** What
# moved it is mcu_supply(): a Pico makes its own 3.3 V, so this part stopped
# being the 3.3 V supply and became the switched rail that feeds the module
# *and* the relay coils -- the 93 mA that V5 was making linearly out of twelve
# volts and that MEASURED["mcu_dcdc_efficiency"].when_wrong has named as the
# lever since the QFN pass. It is the same part in the same package at the
# same frequency, and 5 V is the operating point the datasheet's own worked
# example uses: Table 2, "12 V typical", "5 V +/-3%", "600 mA", "1.1 MHz".
MCU_DCDC_L_HENRIES = 15e-6
MCU_DCDC_RFBT_OHMS = 88_700.0
MCU_DCDC_RFBB_OHMS = 22_100.0
MCU_DCDC_L = "15u 20%"
MCU_DCDC_RFBT = "88k7 1%"
MCU_DCDC_RFBB = "22k1 1%"
MCU_DCDC_COUT = "22u/16V X5R"
MCU_DCDC_COUT_FARADS = 22e-6
# **Table 1 asks for 18 uH and the series does not make one**, which is a
# choice this repo has to take rather than read. SRN6045TA goes 15 to 22 with
# nothing between, and the deciding line is in Table 1's own column heading:
# the inductor is specified +/-20 %, so 18 uH means 14.4 to 21.6 uH. 15 is
# inside that band and 22 is 0.4 uH outside it. The direction is also the safe
# one to be wrong in for the current limit and the wrong one for ripple, and
# mcu_dcdc_ripple() computes what that costs: the peak stays a quarter of the
# minimum current limit.
MCU_DCDC_L_TABLE_HENRIES = 18e-6
# Section 9.2.2.6: "The typical recommended value for the high frequency
# decoupling capacitor is 2.2 uF or higher ... Include a capacitor with a value
# of 0.1 uF for high-frequency filtering and place it as close as possible to
# the device pins." Both are fitted; the 2.2 uF is at 50 V because the same
# section asks for "a voltage rating of twice the maximum input voltage" and
# the input is twelve.
MCU_DCDC_CIN = "2u2/50V X7R"
MCU_DCDC_CIN_FARADS = 2.2e-6
MCU_DCDC_CIN_HF = "100n/50V X7R"
# Section 9.2.2.7: "The recommended bootstrap capacitor is 0.1 uF and rated at
# 16 V or higher ... high-quality ceramic type with X7R or X5R grade".
MCU_DCDC_CBOOT = "100n/50V X7R"
# Bourns SRN6045TA-150M, datasheet read first-hand: 15 uH +/-20 %, DCR 71 mohm
# +/-20 %, Irms 2.80 A, Isat 3.80 A, SRF 20 MHz, 6.0 x 6.0 x 4.5 mm shielded.
# Same series and same land as the SRN6045TA-120M this replaced. The
# datasheet's own selection rule is section 9.2.2.4's last line -- "The
# inductor current rating should be a bit higher than current limit" -- and the
# current limit is 1.4 A maximum, so Isat clears it by 2.7x rather than by a
# hair. Bourns defines both ratings and they are quoted with their conditions:
# Irms is "Temperature Rise 40 degC at rated Irms" and Isat is "Inductance
# drops 30 % at Isat".
MCU_DCDC_L_MPN = "SRN6045TA-150M"
MCU_DCDC_L_DCR = 0.071
MCU_DCDC_L_ISAT_A = 3.8
MCU_DCDC_L_IRMS_A = 2.8
MCU_DCDC_L_DATASHEET = ("https://www.bourns.com/docs/Product-Datasheets/"
                        "SRN6045TA.pdf")


def mcu_dcdc_output(rfbt=None, rfbb=None):
    """The divider, checked against the datasheet's own equation rather than
    read off its table.

    Equation 7 is `RFBT = (VOUT - VREF) / VREF x RFBB`, and Table 1's 5 V row
    gives 88.7 k and 22.1 k. Those are not the exact solution -- the exact one
    is 88.4 k, and the datasheet says so itself: "The formula yields to a value
    88.4 kOhm, a standard value of 88.7 kOhm is selected." So what this returns
    is the rail the *fitted* pair produces and the error against 5 V.

    **What the ceiling is has changed with the rail's job and it is worth
    saying which ceiling.** While this made 3.3 V it was the RP2040's IOVDD
    absolute maximum, 3.63 V, and a divider error was a part-destroying error.
    Now the rail feeds two things that are both far more tolerant: the module's
    VSYS, which its own datasheet gives as 1.8 to 5.5 V, and three relay coils
    whose G6S data sheet rates them at 5 V nominal. The binding one is VSYS's
    ceiling -- through D806, so the diode's drop is headroom rather than a cost
    here -- and the coils' own tolerance is checked by bypass_state() rather
    than by this function.

    The reference's own tolerance is wider than the divider's: +/-1.5 % over
    temperature against 1 % resistors, and both are in the total below.
    """
    rfbt = MCU_DCDC_RFBT_OHMS if rfbt is None else rfbt
    rfbb = MCU_DCDC_RFBB_OHMS if rfbb is None else rfbb
    ratio = 1.0 + rfbt / rfbb
    nominal = MCU_DCDC_VREF * ratio
    low = MCU_DCDC_VREF_RANGE[0] * (1.0 + rfbt * 0.99 / (rfbb * 1.01))
    high = MCU_DCDC_VREF_RANGE[1] * (1.0 + rfbt * 1.01 / (rfbb * 0.99))
    return {
        "rfbt": rfbt, "rfbb": rfbb,
        "volts": nominal,
        "exact_rfbt": (RAILS["VMOD"] - MCU_DCDC_VREF) / MCU_DCDC_VREF * rfbb,
        "error": nominal / RAILS["VMOD"] - 1.0,
        "worst": (low, high),
        # The module's own ceiling on VSYS, section 2.1 -- what the rail may
        # not reach, as opposed to what it should be. D806 is between, so the
        # comparison is deliberately made *without* its drop: a diode that is
        # working is not a reason a rail may be higher.
        "vsys_abs_max": CONTROLLER_VSYS_RANGE[1],
        "fits": high < CONTROLLER_VSYS_RANGE[1],
        # The static current the divider itself draws from the rail, which is
        # counted in mcu_supply() rather than ignored.
        "divider_ma": 1e3 * RAILS["VMOD"] / (rfbt + rfbb),
    }


def mcu_dcdc_light_load(l_henries=None, vin=None):
    """Where a PFM part would stop being a fixed frequency, and it is above
    every load this board presents.

    **This is the argument for the F suffix and it is arithmetic.** A buck in
    discontinuous conduction skips pulses, and the load at which that starts is
    the boundary between continuous and discontinuous conduction: half the
    inductor's own ripple current,

        dI = VOUT x (VIN - VOUT) / (VIN x L x fSW)     datasheet equation 8
        I_boundary = dI / 2

    **The rail this part makes has changed and so has the argument, and the
    conclusion is the same for a different reason.** While U22 made 3.3 V for a
    bare RP2040, Table 1's 12 uH gave a boundary of 91 mA against a maximum
    load of 87: a PFM part would have been discontinuous *always*. It now makes
    5 V for the module and the three relay coils, so at 15 uH the boundary is
    **88 mA and the rail carries 160** -- comfortably continuous, and the F
    suffix would look like a part chosen for a condition that has gone.

    **It has not, and the state that keeps it load-bearing is bypass.** The
    coils are 93 mA of that 160 and they are de-energised exactly when the
    fail-safe drops the module out of circuit -- which is not a fault state
    the box spends microseconds in: it is the state it powers up in, and the
    state it stays in whenever anything is wrong. With the coils off the rail
    carries the module alone, **67 mA**, which is under the boundary; with the
    processor idle as well it is **16 mA**, where a PFM part would run at
    **194 kHz -- under the 300 kHz rule**. In bypass at full tilt it would be
    834 kHz and legal.

    So the correction is worth stating rather than being glad the answer did
    not move: this part is no longer chosen because a PFM sibling would
    *always* be discontinuous. It is chosen because the sibling would be
    discontinuous in **bypass** -- the state the box sits in at power-up and
    after a fault, with audio passing through the mixer's own pots and a
    load-modulated switcher sitting on VA_RAW. A narrower argument, and a
    worse state to have got it wrong in.

    So the switching frequency of a PFM part would be

        f = I_load / q,   q = dI / (2 x fSW)

    -- the load divided by the charge one pulse delivers, which is the triangle
    of height dI and base 1/fSW. That is proportional to load, and the two
    numbers it passes through are the ones this project already has rules
    about:

      * **at the board's own idle draw it is under 300 kHz**, which is the
        threshold spec section 1.1 sets and supply-decision.md argues for. A
        part that fails the rule at idle fails it during most of the music;
      * **below a couple of milliamps it is inside the audio band outright.**
        That is not this firmware -- the RP2040's own BOOTSEL idle is 19 mA --
        but it is one `wfi` away, and a sleep mode that makes the box quieter
        electrically and noisier acoustically is exactly the kind of trap a
        hardware choice should take off the table.

    So the frequency of a PFM part here is not a number but a function of what
    the processor happens to be doing, which is the objection supply_beat()
    records against the RCC-topology TMR 6 -- "a frequency that wanders cannot
    be designed against at all" -- arriving at a second part, for the same
    reason, from the other end. The FPWM version is locked in PWM at every
    load: section 8.4.5, "For FPWM version, TPS560430 is locked in PWM mode at
    full load range."

    What the F suffix costs is efficiency at light load, because the inductor
    current is allowed to go negative -- ILS_NEG is -0.5 A typical. That cost
    is inside MEASURED["mcu_dcdc_efficiency"], which is what supply_fit()
    spends.
    """
    l_henries = l_henries or MCU_DCDC_L_HENRIES
    vin = vin or SUPPLY_VOUT
    vout = RAILS["VMOD"]
    f_hz = MCU_DCDC_KHZ_TYP * 1e3
    ripple_a = vout * (vin - vout) / (vin * l_henries * f_hz)
    chain = mcu_chain()
    charge = ripple_a / (2 * f_hz)
    # **Two loads and the second one is the subject.** In circuit the coils
    # are energised and the rail is heavy; in bypass they are not, and what is
    # left is the module. mcu_rail_load()'s idle figure is the module at its
    # own idle, taken through the RT6150 at the same efficiency.
    load_ma = chain["vmod_ma"]
    bypass_ma = chain["vsys_ma"] + chain.get("divider_ma", 0.0)
    bypass_idle_ma = (mcu_rail_load()["idle_ma"] / mcu_rail_load()["load_ma"]
                      * chain["vsys_ma"])

    def pfm_hz(load_ma):
        """What a PFM part's repetition rate would be at this load."""
        return min(load_ma * 1e-3 / charge, f_hz)

    return {
        "ripple_a": ripple_a,
        "boundary_ma": ripple_a / 2 * 1e3,
        "load_ma": load_ma,
        "bypass_ma": bypass_ma,
        "idle_ma": bypass_idle_ma,
        "charge_c": charge,
        "always_discontinuous": load_ma < ripple_a / 2 * 1e3,
        "continuous_in_circuit": load_ma >= ripple_a / 2 * 1e3,
        "continuous_in_bypass": bypass_ma >= ripple_a / 2 * 1e3,
        "pfm_hz_at_load": pfm_hz(load_ma),
        "pfm_hz_at_bypass": pfm_hz(bypass_ma),
        "pfm_hz_at_idle": pfm_hz(bypass_idle_ma),
        # The two loads that matter, solved rather than swept: where a PFM
        # part would cross the spec's own 300 kHz rule and where it would
        # enter the audio band.
        "pfm_under_rule_below_ma": SUPPLY_MIN_KHZ * 1e3 * charge * 1e3,
        "pfm_in_band_below_ma": BANDWIDTH * charge * 1e3,
        "idle_breaks_rule": pfm_hz(bypass_idle_ma) < SUPPLY_MIN_KHZ * 1e3,
        "bypass_breaks_rule": pfm_hz(bypass_ma) < SUPPLY_MIN_KHZ * 1e3,
        "fpwm": True,
    }


def mcu_dcdc_beat(f_khz=None):
    """This board's second switcher, against the first and against the pump.

    supply_beat() already found that the ">= 300 kHz" rule is a fundamental-only
    rule for a mechanism that is not, and nothing here overturns that. What is
    new is that there are now **two** switchers on one board, so there are three
    products to price rather than one:

      * against the mixer's 45 kHz pump and its harmonics -- supply_beat() does
        this for any frequency and the answer for 1.1 MHz is the same shape:
        somewhere in the stated band a harmonic lands on it exactly;
      * against the TMR's own 522-638 kHz band, and its harmonics. The second
        harmonic of the TMR reaches 1276 kHz and this part's band starts at
        935, so those two overlap as well;
      * and the two-unit case, which is not a case here: there is one of each.

    **The conclusion is the same and the reason is different, which is worth
    being exact about.** For the pump, what makes the product harmless is that
    this module shares no rail with the mixer -- the isolation barrier. That
    argument is *not* available for this converter, because VA_RAW is shared
    with the audio domain by construction. What is available instead is
    mcu_dcdc_injection(): the same R804/C811 pole that the TMR's own ripple goes
    through, at twice the frequency, and the product is second order in two
    quantities that are both already tiny.
    """
    f_khz = f_khz or MCU_DCDC_KHZ_TYP
    against_pump = supply_beat(f_khz)
    # Against the converter's own band, at every harmonic of each that can
    # reach the other. The beat is |n x f1 - m x f2| minimised over the band,
    # and the band is what makes it zero: two ranges that overlap contain a
    # coincident pair.
    overlaps = []
    for n in range(1, 4):
        for m in range(1, 4):
            lo = abs(n * MCU_DCDC_KHZ[0] - m * SUPPLY_KHZ[1])
            hi = abs(n * MCU_DCDC_KHZ[1] - m * SUPPLY_KHZ[0])
            if (n * MCU_DCDC_KHZ[0] <= m * SUPPLY_KHZ[1]
                    and m * SUPPLY_KHZ[0] <= n * MCU_DCDC_KHZ[1]):
                overlaps.append((n, m, 0.0))
            else:
                overlaps.append((n, m, min(lo, hi)))
    worst = min(overlaps, key=lambda row: row[2])
    return {
        "f_khz": f_khz,
        "band_khz": MCU_DCDC_KHZ,
        "against_pump": against_pump,
        "against_converter": overlaps,
        "worst_pair": worst[:2],
        "worst_beat_khz": worst[2],
        "rule_holds": abs(f_khz - socket.PUMP_FREQUENCY / 1e3) > 20.0,
        "above_rule": f_khz >= SUPPLY_MIN_KHZ,
    }


def mcu_dcdc_injection(f_khz=None):
    """What the second switcher puts on the rail the audio domain shares.

    **The reason the input side is where this is computed.** The converter's
    output ripple stays on VMCU and MDGND, which is the digital domain and the
    controller's own problem. What reaches the audio is the *input* current: a
    buck draws a pulse train from its supply, and its supply here is VA_RAW,
    which feeds R804 into VA+ and U16 into V5.

    The input ripple current of a buck is the switch current minus its own
    average, so its RMS is the standard

        I_rms = I_out x sqrt(D x (1 - D))        D = VOUT / VIN

    and what it develops is that current across the impedance of VA_RAW at the
    switching frequency, which is C813's 10 uF in parallel with the converter's
    own output impedance. C813 alone is the pessimistic reading and is what is
    used: giving the flyback credit for its impedance at a megahertz would be
    inventing a figure the datasheet does not give.

    Then R804/C811 -- the pole rail_filter() already computes for the TMR's own
    75 mVp-p -- stands between VA_RAW and VA+, at twice the frequency it was
    designed against, so it is worth about 6 dB more.
    """
    f_hz = (f_khz or MCU_DCDC_KHZ[0]) * 1e3
    supply = mcu_supply()
    duty = V3V3_VOLTS / SUPPLY_VOUT
    i_rms = supply["load_ma"] * 1e-3 * math.sqrt(duty * (1 - duty))
    z_bulk = 1.0 / (2 * math.pi * f_hz * PRIMARY_BULK_C_FARADS)
    on_raw = i_rms * z_bulk
    # The same pole as rail_filter(), evaluated here rather than there because
    # the frequency is this part's and not the TMR's.
    corner = 1.0 / (2 * math.pi * RAIL_FILTER_R_OHMS * RAIL_FILTER_C_FARADS)
    attenuation = math.sqrt(1 + (f_hz / corner) ** 2)
    residual = on_raw / attenuation
    return {
        "f_khz": f_hz / 1e3,
        "duty": duty,
        "input_rms_ma": i_rms * 1e3,
        "z_bulk": z_bulk,
        "on_va_raw_v": on_raw,
        "attenuation_db": 20 * math.log10(attenuation),
        "residual_v": residual,
        "am": ripple_am(residual),
        # Against the TMR's own residual on the same node, which is what
        # rail_filter() reports: the two add on the rail and multiply at the
        # control port.
        "converter_residual_v": rail_filter()["residual_vpp"] / 2,
    }


def mcu_rail_load():
    """Every milliamp on VMCU, and where each figure was read.

    Separated from mcu_supply() for one reason and it is a real one: supply_
    load() has to know this rail's current, mcu_supply() has to know what the
    converter has left *before* this rail, and supply_fit() computes the second
    from the first. Three functions in a ring unless the counting is its own
    function, which it now is.
    """
    owner = DESIGN.pin_owner() if "DESIGN" in globals() else {}
    on_rail = sorted({ref for (ref, _), net in owner.items() if net == "VMCU"})
    # **Two of these terms are not netlist parts and that is worth a sentence
    # rather than a shrug.** supply_load()'s whole principle is that a rail's
    # current is counted off the netlist, because a table of what hangs on a
    # rail is a second copy of the rail. A module breaks that: the RP2040 and
    # the flash are behind castellations, so the walk cannot see them and they
    # are the two largest terms. What keeps the principle honest is that they
    # are *named as such* -- U19 is one part on the netlist and two loads here
    # -- rather than folded into a single figure nobody can take apart.
    terms = {
        CONTROLLER_REF: sum(rail[1] for rail in CONTROLLER_USE_CASES["Popcorn"]),
        "U19 flash, on the module": FLASH_ICC_MA["program"][1],
        MIDI_OPTO_REF: MIDI_OPTO_ICC_MA,
        "MIDI out loop": midi_loop()["out_ma"],
        "expression pedal": expression_input()["short_ma"],
        "tap pull-up": tap_debounce()["closed_ma"],
    }
    idle_terms = {
        CONTROLLER_REF: sum(rail[1]
                            for rail in CONTROLLER_USE_CASES["BOOTSEL idle"]),
        "U19 flash, on the module": FLASH_ICC_MA["standby"][1],
        MIDI_OPTO_REF: MIDI_OPTO_ICC_MA,
    }
    typical = {
        CONTROLLER_REF: sum(rail[0] for rail in CONTROLLER_USE_CASES["Popcorn"]),
        "U19 flash, on the module": FLASH_ICC_MA["read_104"][0],
        MIDI_OPTO_REF: MIDI_OPTO_ICC_MA,
    }
    return {
        "parts": on_rail,
        "terms": terms,
        "load_ma": sum(terms.values()),
        "idle_ma": sum(idle_terms.values()),
        "typ_ma": sum(typical.values()),
        "watts": V3V3_VOLTS * sum(terms.values()) * 1e-3,
    }


def mcu_chain(eta_module=None, eta_buck=None):
    """VMCU -> RT6150 -> VSYS -> D806 -> VMOD -> U22 -> +Vout, stage by stage.

    **Its own function so that two callers cannot make a ring.** supply_load()
    needs VMOD's current to declare the rail; mcu_supply() needs the whole
    chain to answer the budget; and mcu_supply() asks supply_fit() what the
    headroom was *before* this block, which asks supply_load(). Putting the
    arithmetic here means the dependency runs one way and there is still one
    copy of it -- the same reason mcu_rail_load() was split out of mcu_supply()
    when there were three functions in a ring the first time.

    Walked from the load outward, a stage at a time, because the alternative --
    one efficiency figure called "the controller supply" -- is exactly what
    would hide the fact that there are now two of them and a diode between.

    The diode's drop is taken at the current it carries rather than at a
    nominal, which needs one pass round the loop: _schottky_vf() is a table
    lookup on the PMEG2010AEH's own curve and the second iteration moves the
    answer by under a millivolt.
    """
    eta_module = (MEASURED["pico_smps_efficiency"].value
                  if eta_module is None else eta_module)
    eta_buck = (MEASURED["mcu_dcdc_efficiency"].value
                if eta_buck is None else eta_buck)
    watts = mcu_rail_load()["watts"]
    divider_ma = mcu_dcdc_output()["divider_ma"]
    vsys_ma = watts / (eta_module * RAILS["VMOD"]) * 1e3
    vf = _schottky_vf(vsys_ma * 1e-3, CLAMP_VF_TABLE)
    for _ in range(2):
        vf = _schottky_vf(vsys_ma * 1e-3, CLAMP_VF_TABLE)
        vsys_ma = watts / (eta_module * (RAILS["VMOD"] - vf)) * 1e3
    # **The coils are on this rail and they are two thirds of it.** Counting
    # only the module's current here would price U22 for the smaller of its
    # two customers and hand supply_fit() a number that is right about a rail
    # nobody has.
    coil_ma = BYPASS_COIL_MA[1] * BYPASS_RELAYS
    vmod_watts = RAILS["VMOD"] * (vsys_ma + coil_ma + divider_ma) * 1e-3
    return {
        "vmcu_watts": watts,
        "vsys_ma": vsys_ma,
        "diode_vf": vf,
        "vsys_volts": RAILS["VMOD"] - vf,
        "vsys_in_range": (CONTROLLER_VSYS_RANGE[0] <= RAILS["VMOD"] - vf
                          <= CONTROLLER_VSYS_RANGE[1]),
        "coil_ma": coil_ma,
        "vmod_ma": vsys_ma + coil_ma + divider_ma,
        "vmod_watts": vmod_watts,
        "input_ma": vmod_watts / (eta_buck * SUPPLY_VOUT) * 1e3
                    + MCU_DCDC_IQ_MA,
    }


def mcu_supply():
    """The 3.3 V load, counted off the netlist, and what it costs the converter.

    **Counted rather than listed, for supply_load()'s own reason**: a table of
    what hangs on a rail is a second copy of the rail. Every term below is a
    datasheet maximum read first-hand:

      * the RP2040 at 52.1 mA -- Table 637's heaviest use case, summed across
        DVDD, IOVDD and USB_VDD, because DVDD is made from IOVDD's own supply
        by an on-chip *linear* regulator and a linear regulator passes its
        output current through;
      * the flash at 25 mA -- W25Q128JV section 9.4, ICC5 page-program maximum,
        which is larger than the 20 mA of ICC3 read at 104 MHz;
      * the opto at 1.0 mA -- TLP2761 ICCH/ICCL maximum;
      * the MIDI out loop, the expression pedal's divider, the tap pull-up and
        the switcher's own feedback divider, each computed by the function that
        owns it.

    **The pedal term is a fault current and it is counted anyway.** A TS plug
    in a TRS socket shorts ring to sleeve, which is VMCU to ground through
    R832 alone -- see expression_input(). It is 3 mA, it is a state a musician
    reaches by plugging in the wrong lead, and a supply budget that excludes
    the states the panel can be put into is a budget about the good case.
    """
    load = mcu_rail_load()
    efficiency = MEASURED["mcu_dcdc_efficiency"]
    module = MEASURED["pico_smps_efficiency"]
    watts = load["watts"]
    worst = mcu_chain(module.low, efficiency.low)
    nominal = mcu_chain(module.value, efficiency.value)
    best = mcu_chain(module.high, efficiency.high)
    # **The headroom *before* the controller**, which is the 35.4 mA
    # controller_supply() argued the gate from. Asking supply_fit() for the
    # figure with this block already in it would be asking a question whose
    # answer contains its own subject; the parameter is what keeps one copy of
    # the arithmetic and two questions.
    head = supply_fit(include_mcu=False)["positive_headroom_ma"]
    return {
        "parts": load["parts"],
        "terms": load["terms"],
        "load_ma": load["load_ma"],
        "idle_ma": load["idle_ma"],
        "watts": watts,
        # **Conservation of energy, and it has not moved.** The floor is the
        # 3.3 V load's power divided by twelve volts, whatever is between --
        # two converters, a diode, or one converter as it was before. That is
        # the property that made this bound worth stating and it survives the
        # topology changing under it.
        "floor_ma": watts / SUPPLY_VOUT * 1e3,
        "min_efficiency": watts / SUPPLY_VOUT * 1e3 / head,
        # ...and it is a threshold on a **product** now, which is the whole of
        # what the module cost. 0.678 against two assumptions whose pessimistic
        # ends multiply to 0.660: the corner fails, by 1.8 points of efficiency
        # and 4.6 mA of +Vout, and it is said here rather than rounded.
        "min_efficiency_product": watts / SUPPLY_VOUT * 1e3 / head,
        "efficiency_product": (module.low * efficiency.low,
                               module.value * efficiency.value,
                               module.high * efficiency.high),
        "fits": (best["input_ma"] <= head, nominal["input_ma"] <= head,
                 worst["input_ma"] <= head),
        "chain": {"worst": worst, "nominal": nominal, "best": best},
        # The stage that used to be the whole story, kept under the same key
        # so every consumer reads the pessimistic corner as it always did.
        "input_ma": worst["input_ma"],
        "input_ma_typical": nominal["input_ma"],
        "vsys_ma": worst["vsys_ma"],
        "vsys_volts": worst["vsys_volts"],
        "diode_vf": worst["diode_vf"],
        # **What the ORing diode costs, priced because it is larger than the
        # margin it leaves.** 0.29 V of 3.3 is 8.8 % of this chain, which is
        # about 2.9 mA of +Vout at the nominal corner -- more than the 2.0 mA
        # the nominal corner has left. The Pico datasheet's own improvement is
        # a P-FET, Figure 17, and it names a part; it is not fitted for two
        # reasons that are stated together because neither is sufficient
        # alone: it does not rescue the pessimistic corner either, being 2.9 mA
        # against a 4.6 mA shortfall, and its orientation is precisely the
        # failure mode DIODE_PINS and CAP_PINS record -- a polarised part
        # fitted backwards, which works, passes DRC, and is wrong.
        "diode_watts": nominal["diode_vf"] * nominal["vsys_ma"] * 1e-3,
        "diode_cost_ma": (nominal["diode_vf"] * nominal["vsys_ma"] * 1e-3)
                         / (efficiency.value * SUPPLY_VOUT) * 1e3,
        "headroom_before_ma": head,
        "iout_limit_ma": MCU_DCDC_IOUT_MAX_MA,
        "iout_margin": MCU_DCDC_IOUT_MAX_MA / load["load_ma"],
        # What is left of +Vout once this block is on it. The number the whole
        # gate was about, answered -- at all three corners, because one of them
        # is now negative.
        "headroom_after_ma": head - worst["input_ma"],
        "headroom_after_typical_ma": head - nominal["input_ma"],
        # U22's own dissipation, which is not what limits it: the loss is the
        # difference between what it takes and what it delivers.
        "watts_lost": worst["vmod_watts"] / efficiency.low
                      - worst["vmod_watts"],
        "rise_c": (worst["vmod_watts"] / efficiency.low
                   - worst["vmod_watts"]) * MCU_DCDC_THETA_JA,
    }


# ---------------------------------------------------------------------------
# What hangs off the controller: flash, crystal, USB, MIDI, pedal, footswitch
# ---------------------------------------------------------------------------
# Everything in this section comes from one of two documents read first-hand:
# the RP2040 datasheet (build-date 2024-11-05) and **Hardware design with
# RP2040** (RP-008279-DS, chapter 2, "Minimal design example"), which is the
# vendor's own reference design and the place every value below with an RP
# section number against it comes from. The MIDI half comes from CA-033, the
# MMA/AMEI "MIDI 1.0 Electrical Specification Update [2014]", also read.
#
# **The rule this section follows, because it is the one section 6 of the spec
# is about:** where the vendor's reference design states a value, that value is
# used and the reasoning is quoted rather than re-derived. Where it states a
# *range* or leaves the choice to the application -- the MIDI receiver's
# resistor, the pedal's series resistor, the VBUS divider -- a function here
# derives it and says against what.

# -- the flash, the crystal and USB: on the module ---------------------------
#
# **Three blocks became one line of the Pico datasheet.** Section 1: "Pico
# provides minimal (yet flexible) external circuitry to support the RP2040
# chip: flash (Winbond W25Q16JV), crystal (Abracon ABM8-272-T3), power
# supplies and decoupling, and USB connector." Every constant this repo
# derived for those three is gone with the parts, and two of them are worth a
# sentence on the way out:
#
#   * **the crystal is the same part.** RP2040 section 1.4.1 makes 12 MHz a
#     requirement and minimal design 2.3.1 names the ABM8-272-T3; the module
#     fits that part. Arriving at the vendor's answer independently and then
#     buying the vendor's module is a pleasant thing to notice and is not
#     evidence of anything -- both readings came from the same document;
#   * **crystal_load() is deleted rather than kept for reference.** It computed
#     C/2 plus 3 pF of board stray against a 10 pF part, which is a fact about
#     a board this design no longer draws. Its one open question is deleted
#     with it: the load error could not be quoted in ppm, because that needs
#     the crystal's *motional* capacitance and the ABM8 datasheet publishes
#     C0 and not C1.
#
# **What stays is what a load current is read from**, because the flash is
# still 25 mA of the 3.3 V rail whoever solders it. The module's part is the
# 16 Mbit W25Q16JV and this project has read the 128 Mbit sibling's datasheet,
# not that one -- so the figures below are kept as an **upper bound with its
# provenance stated** rather than replaced by a number nobody has looked up.
# They are the same die family in the same package with the same programming
# engine, and a page program is one 256-byte page either way.
FLASH = "W25Q128JV"
FLASH_MODULE = "W25Q16JV"
FLASH_DATASHEET = "https://docs.rs-online.com/7d70/0900766b81703faf.pdf"
FLASH_REVISION = "Revision G, 8 April 2019"
FLASH_VCC = (2.7, 3.6)
# Section 9.4, DC electrical characteristics: (typical, maximum) milliamps.
FLASH_ICC_MA = {
    "standby": (0.010, 0.060),
    "read_104": (12.0, 20.0),
    "program": (20.0, 25.0),
}
# Table 626's own figure for the bus rail, kept because NET_DC["VSYS"] needs a
# ceiling: with a USB cable in, VSYS is VBUS minus the module's D1 and this is
# what VBUS may be.
USB_VBUS_VOLTS = (4.75, 5.25)

# -- DIN MIDI --------------------------------------------------------------
#
# CA-033, "MIDI 1.0 Electrical Specification Update [2014]", MMA/AMEI, read
# first-hand. The interface is "31.25 (+/- 1%) Kbaud, asynchronous, with a
# start bit, 8 data bits (D0 to D7), and a stop bit ... a total of 10 bits for
# a period of 320 microseconds per serial byte", and "The MIDI circuit is a 5mA
# current loop; logical 0 is current ON."
#
# The transmitter's two resistors are the specification's own, in its 3.3 V
# column: "RA 33 ohm 5% 0.5W" from the supply and "RC 10 ohm 5% 0.25W" from the
# driver. Nothing is derived there; they are a table entry.
#
# **The receiver's resistor is not a table entry and that is where the work
# is.** CA-033 draws RB as 220 ohm and says of the pull-up RD only that its
# "Value ... depends on opto-isolator and VRX". Two things follow. RD does not
# exist here at all -- the TLP2761 has a totem-pole output, so there is nothing
# to pull up, which is one part and one node fewer than the 6N138 the
# specification names. And RB has to be *computed*, because this receiver may
# be driven by either a 5 V transmitter (220 + 220 ohm) or a 3.3 V one
# (33 + 10), and those two differ by a factor of six in source resistance
# against an opto whose recommended input current spans 2 to 6 mA.
# midi_loop() is that arithmetic and 220 ohm does not survive it.
MIDI_BAUD = 31_250.0
MIDI_BIT_S = 1.0 / 31_250.0
MIDI_LOOP_MA = 5.0
MIDI_RISE_MAX_S = 2e-6                 # "Rise and fall times should be less
                                       # than 2 microseconds"
# The transmitter, CA-033 Figure 1's 3.3 V column.
MIDI_OUT_RA = "33R 5%"
MIDI_OUT_RA_OHMS = 33.0
MIDI_OUT_RC = "10R 5%"
MIDI_OUT_RC_OHMS = 10.0
# The receiver's own series resistor, derived by midi_loop().
MIDI_IN_RB = "390R 1%"
MIDI_IN_RB_OHMS = 390.0
# CA-033 Figure 2's "Reverse voltage protection for opto-isolator", drawn as a
# 1N914. The board already buys the 1N4148W, which is the same junction in a
# SOD-123, so this adds no BOM line.
MIDI_IN_DIODE = ENV_DIODE
# The optional 0.1 uF from the MIDI IN jack's pin 2 and shield to local ground:
# "Pin 2 of the MIDI In connector shall not have any DC path to the receiver's
# ground. However, a connection through a small capacitor (0.1uF typical) to
# ground is optional for improved high-frequency (RF) shielding." Fitted,
# because it is the only thing on this board that grounds a shield the audio
# domain does not own, and a capacitor is what keeps that true at DC.
MIDI_IN_SHIELD_C = "100n/50V X7R"
#
# Toshiba TLP2761, datasheet rev 10.0 (2026-05-11), read first-hand. **The
# specification names PC-900V and 6N138 and both are 5 V parts**; this board's
# logic rail is 3.3 V and the RP2040's inputs are not 5 V tolerant, so the
# receiver has to be a part specified at 3.3 V. CA-033 allows exactly that --
# "Other high-speed opto-isolators may be satisfactory. The receiver must
# require less than 5 mA to turn on. Rise and fall times should be less than 2
# microseconds" -- and every one of those three is a number this part states:
# 2.7 to 5.5 V supply, 1.6 mA threshold input current at 125 degC, 49 ns
# typical propagation delay against a 2 us requirement.
MIDI_OPTO = "TLP2761"
MIDI_OPTO_REF = "U21"
MIDI_OPTO_MPN = "TLP2761(TP,E)"
MIDI_OPTO_DATASHEET = ("https://toshiba.semicon-storage.com/info/docget.jsp"
                       "?did=28819&prodName=TLP2761")
MIDI_OPTO_REVISION = "Rev 10.0, 2026-05-11"
MIDI_OPTO_PINS = {"A": 1, "NC": 2, "K": 3, "GND": 4, "VO": 5, "VCC": 6}
MIDI_OPTO_IF_ON_MA = (2.0, 6.0)        # section 9, recommended operating
MIDI_OPTO_IF_ABS_MAX_MA = 10.0         # section 8, absolute maximum
MIDI_OPTO_IFHL_MA = 1.6                # threshold input current, -40 to 125 C
MIDI_OPTO_VF = (1.35, 1.65)            # at IF = 2 mA, 25 degC
MIDI_OPTO_ICC_MA = 1.0                 # ICCH/ICCL maximum
MIDI_OPTO_TPD_S = 80e-9                # maximum, either direction
MIDI_OPTO_SKEW_S = 25e-9               # pulse width distortion, maximum
MIDI_OPTO_VCC = (2.7, 5.5)
# "A ceramic capacitor (0.1 uF) should be connected between pin 6 and pin 4 to
# stabilize the operation of a high-gain linear amplifier. Otherwise, this
# photocoupler may not switch properly. The bypass capacitor should be placed
# within 1 cm of each pin." Not decoupling in the usual sense -- a condition of
# operation, with a distance attached, which is why placement.py has to know.
MIDI_OPTO_LOCAL = "100n/50V X7R"
MIDI_OPTO_LOCAL_MM = 10.0


def midi_loop(rb=None):
    """The receiver's series resistor, against both kinds of transmitter.

    **The one value in the MIDI block this repo has to choose, and CA-033's own
    220 ohm does not survive the arithmetic.** The loop is a series circuit:
    the transmitter's supply, its two resistors, the cable, this board's RB and
    the opto's LED. The specification gives two transmitters:

        5 V   RA 220 + RC 220 = 440 ohm      the original circuit
        3.3 V RA  33 + RC  10 =  43 ohm      CA-033's update

    and this receiver may be plugged into either, because both are current
    standards and a MIDI cable does not say which is on the other end. So RB
    has to hold the LED current inside the TLP2761's recommended 2 to 6 mA at
    *both* ends, with the LED's own forward voltage at its own extremes:

        I = (VTX - VF - VOL) / (R_TX + RB)

    **CA-033's own 220 ohm does not fail this and 390 is not a rescue** -- a
    claim written here first and corrected by running the arithmetic rather
    than by reading it. At 220 ohm the four corners are 4.32 to 5.51 mA: inside
    the recommended range, and 9 % under its ceiling with the 3.3 V
    transmitter. That is a working receiver with the margin all on one side.

    **390 ohm centres it**: 2.66 to 3.80 mA, which is 1.66x above the threshold
    current at the worst corner and 1.58x under the recommended ceiling at the
    best. The choice is between margin that is 2.7x one way and 1.09x the
    other, and margin that is 1.66x and 1.58x -- and what makes the balanced
    one right here is that neither end of the spread is knowable: the
    transmitter is somebody else's box, and VF is quoted at 2 mA rather than at
    the current the loop actually delivers.

    The driver's own VOL is the RP2040's, Table 625: 0.5 V maximum at any drive
    strength. It is in the arithmetic because at 3.3 V it is a sixth of the
    voltage the loop has to work with.
    """
    rb = MIDI_IN_RB_OHMS if rb is None else rb
    transmitters = {
        "5V (220 + 220)": (5.0, 440.0),
        "3V3 (33 + 10)": (V3V3_VOLTS, MIDI_OUT_RA_OHMS + MIDI_OUT_RC_OHMS),
    }
    corners = {}
    for name, (volts, r_tx) in transmitters.items():
        for vf, label in ((MIDI_OPTO_VF[0], "VF min"),
                          (MIDI_OPTO_VF[1], "VF max")):
            corners[f"{name}, {label}"] = (
                (volts - vf - CONTROLLER_VOL) / (r_tx + rb) * 1e3)
    low, high = min(corners.values()), max(corners.values())
    return {
        "rb": rb,
        "corners": corners,
        "low_ma": low,
        "high_ma": high,
        "recommended": MIDI_OPTO_IF_ON_MA,
        "inside": (low >= MIDI_OPTO_IF_ON_MA[0]
                   and high <= MIDI_OPTO_IF_ON_MA[1]),
        "threshold_margin": low / MIDI_OPTO_IFHL_MA,
        "abs_margin": MIDI_OPTO_IF_ABS_MAX_MA / high,
        # What this board's own transmitter draws from VMCU when it is sending
        # a zero, into the 220 ohm receiver CA-033 draws.
        "out_ma": (V3V3_VOLTS - MIDI_OPTO_VF[0] - CONTROLLER_VOL)
                  / (MIDI_OUT_RA_OHMS + MIDI_OUT_RC_OHMS + 220.0) * 1e3,
        # The timing, which is the other half of "may be satisfactory".
        "bit_s": MIDI_BIT_S,
        "delay_fraction": MIDI_OPTO_TPD_S / MIDI_BIT_S,
        "skew_fraction": MIDI_OPTO_SKEW_S / MIDI_BIT_S,
        "rise_requirement_s": MIDI_RISE_MAX_S,
    }


# -- the tap footswitch and the expression pedal ---------------------------
#
# Both are panel jacks on the far end of a lead somebody stands on, so both get
# the same two things: a defined impedance at the pin and a series resistor
# between the outside world and the die. Neither value is in any datasheet --
# they are this board's -- so both are derived below.
TAP_PULLUP = "10k 1%"
TAP_PULLUP_OHMS = 10_000.0
TAP_SERIES = "1k 1%"
TAP_SERIES_OHMS = 1_000.0
TAP_C = "100n/50V X7R"
TAP_C_FARADS = 100e-9
EXPR_TOP = "1k 1%"
EXPR_TOP_OHMS = 1_000.0
EXPR_SERIES = "1k 1%"
EXPR_SERIES_OHMS = 1_000.0
EXPR_C = "100n/50V X7R"
EXPR_C_FARADS = 100e-9
# What a standard expression pedal is: a potentiometer wired tip = wiper,
# ring = supply, sleeve = ground. **The element value is not standardised** --
# 10 k and 25 k are both common -- and expression_input() shows why that does
# not have to be settled here.
EXPR_POT_OHMS = (10_000.0, 25_000.0)


def tap_debounce():
    """The footswitch's pull-up, its series resistor and where bounce is dealt
    with.

    **Bounce is not dealt with here and that is deliberate**, in the same shape
    as envelope_filter(): the hardware sets an impedance and a rate, and the
    musical constant is a firmware one at the frame rate. FRAME_RATE is 8 kHz,
    so firmware sees this pin 125 us apart and a contact that bounces for
    milliseconds is tens of samples -- a debounce anybody would write in three
    lines. Sizing the RC to swallow a 10 ms bounce instead would need 1 uF at
    the pin and would put a 3.3 mA discharge spike through the switch.

    So the two resistors do the jobs a firmware constant cannot:

      * the 10 k pull-up gives the pin a **defined impedance from reset**. The
        part's own pull-up is 50 to 80 kohm (Table 625) and its reset state on
        a plain GPIO is pull-*down* (Table 615), so without this the node's
        state before firmware runs is a range rather than a level;
      * the 1 k series resistor is what a lead going out of the enclosure gets
        between it and the die. At the absolute maximum on an IO pin -- IOVDD
        + 0.5 -- it holds any injected current to well under a milliamp, and
        with the 100 nF it slows the edge to a time constant the part's own
        Schmitt trigger (VHYS 0.2 V at 3.3 V) is specified to clean up.
    """
    tau_open = TAP_PULLUP_OHMS * TAP_C_FARADS
    tau_closed = TAP_SERIES_OHMS * TAP_C_FARADS
    return {
        "pullup": TAP_PULLUP_OHMS,
        "series": TAP_SERIES_OHMS,
        "c": TAP_C_FARADS,
        "tau_open_s": tau_open,
        "tau_closed_s": tau_closed,
        "frame_s": 1.0 / FRAME_RATE,
        "frames_per_tau": tau_open * FRAME_RATE,
        "closed_ma": V3V3_VOLTS / TAP_PULLUP_OHMS * 1e3,
        "internal_pullup_kohm": CONTROLLER_PULL_KOHM,
        "hysteresis_v": CONTROLLER_VHYS,
    }


def expression_input(series=None, top=None):
    """The pedal's series resistor, and what a mono plug in a stereo socket
    costs.

    **The failure this exists for is mechanical.** An expression pedal is a
    potentiometer on a TRS lead -- ring to the supply, wiper to the tip, sleeve
    to ground -- and a TS plug pushed into a TRS socket shorts the ring to the
    sleeve. That is the supply to ground through whatever is in series with the
    ring, and it happens every time somebody reaches for the wrong lead in the
    dark. R832 is the whole of the protection:

        short current = VMCU / R_top

    at 1 k that is 3.3 mA, which mcu_supply() counts as load rather than as a
    fault, so the supply budget is right in the state the panel can be put
    into.

    What it costs is full scale, and the cost depends on a pot value nobody
    specifies: the top of the range is `Rpot / (Rpot + R_top)` of the rail, so
    91 % with a 10 k pedal and 96 % with a 25 k one. **That is not a problem
    the hardware has to solve.** An expression input is calibrated at its
    extremes by firmware -- heel down and toe down -- because pedals differ in
    taper and travel anyway, so what the hardware must deliver is monotonic and
    bounded, and it does.

    The ADC end needs no buffer and the datasheet says so directly: "The
    effective impedance, even when sampling at 500ksps, is over 100kohm, and
    for DC measurements there should be no need to buffer" (section 4.9.2).
    The series resistor and capacitor at the pin settle in nanoseconds against
    a 2 us conversion.
    """
    series = EXPR_SERIES_OHMS if series is None else series
    top = EXPR_TOP_OHMS if top is None else top
    spans = {pot: pot / (pot + top) for pot in EXPR_POT_OHMS}
    # Source impedance seen by the ADC: the pot's Thevenin resistance is worst
    # at mid-travel, a quarter of its value, plus the series resistor.
    worst_source = max(EXPR_POT_OHMS) / 4 + series
    return {
        "top": top,
        "series": series,
        "short_ma": V3V3_VOLTS / top * 1e3,
        "spans": spans,
        "full_scale_v": {pot: V3V3_VOLTS * span for pot, span in spans.items()},
        "worst_source_ohms": worst_source,
        "adc_rin_ohms": CONTROLLER_ADC_RIN,
        "settling_s": worst_source * CONTROLLER_ADC_CSAMPLE * 10,
        "conversion_s": CONTROLLER_ADC_CONVERSION_S,
        "anti_alias_hz": 1.0 / (2 * math.pi * series * EXPR_C_FARADS),
        "lsb_v": V3V3_VOLTS / 2 ** 12,
        "enob": CONTROLLER_ADC_ENOB,
    }


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

    The last row is the single fail-loud path in the CV chain, and **what this
    docstring used to say about it was wrong**: "the mitigation belongs with
    the shared fail-safe blocks, and the bypass relay's AC-coupled charge pump
    covers it at the audio level in the meantime."

    It does not cover it. The pump collapses when the *MCU* stops, and an
    inverted reference that fails to the positive rail leaves the MCU healthy,
    still emitting its 10 kHz, holding the relay in. The one state the
    fail-safe cannot see is the one state that is loud, and the sentence read
    as though "the fail-safe" were a single thing that covered everything.

    D803 is the answer and it is one diode: clamp_gain() turns +20 dB into
    +7.4 dB, inside the mixer's own 7.84 dB of headroom. See CLAMP_DIODE.
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
# The fail-safe: the bypass relay, the pump that holds it in, and the clamp
# ---------------------------------------------------------------------------

# Spec section 4.5, and it is three claims in one sentence: "MCU emits ~10 kHz
# on a GPIO -> two-diode charge pump -> MOSFET -> bypass relay. **Any** stuck
# state -- high, low, hi-Z, crashed, halted clock -- collapses the pump and
# drops to bypass."
#
# The mechanism is sound and it is the reason this is a pump rather than a
# watchdog: a watchdog IC sees a signal that firmware can emit while wedged,
# and an AC-coupled pump can only be held up by something that keeps changing.
# Three things about it are not in the sentence, and each moves a part count.
#
# **"Bypass" here is six changeover contacts, not one relay.** This module
# replaces the mixer's six RV{n}01 level pots, so removing it from circuit means
# reconnecting each PIN{n} to its own SIN{n} -- six independent audio paths, not
# one. That is 3 DPDT, and it is the third count in section 4.5 that does not
# close (the coil arithmetic was the second; the pad it drove is deleted).
#
# **The relay must be non-latching, which is the opposite of the pad's
# requirement**, and the reason is the whole of the fail-safe: de-energised has
# to *be* bypass, so that losing the rails, the MCU or the pump all land in the
# same safe state. A latching relay holds its last position through a power cut,
# which is precisely the property that makes it wrong here. Nothing in the
# module's own supply can be a precondition for being safe.
#
# **It costs continuous coil current, and that is the bill.** A 5 V signal DPDT
# coil is 25-40 mA; three of them is 75-120 mA held for as long as the module is
# working, against about 55 mA for every amplifier and VCA on the board. See
# coil_budget() -- it is a requirement on the deferred supply, not a detail.
# **Chosen, and the choice is a reading rather than a preference.** Omron G6S-2
# DC5: DPDT, single-side stable -- which is Omron's name for non-latching, and
# the property the whole block turns on -- fully sealed, in the surface-mount
# G6S-2F body. From the ratings table on page 2 of its data sheet, at 5 VDC:
# 28.1 mA of coil, 178 ohm, must-operate 75 % max of rated and must-release
# 10 % min, which is 3.75 V and 0.5 V.
#
# The contact material is the part of the table that decides it for audio and
# it is not the part anybody would think to filter on: **bifurcated crossbar,
# Ag (Au-Alloy)**. Two contact points per pole in parallel and a gold alloy over
# them, which is what makes a relay usable at the microvolts a guitar string
# produces -- a plain silver contact needs a wetting current this signal path
# will never provide, and its failure mode is intermittent and looks like a bad
# solder joint.
BYPASS_RELAY = "G6S-2 DC5"
# **SOT-523 and the spec said SOT-23**, which is worth being explicit about
# because the package was the one part of that requirement nobody had derived.
# UNSPECIFIED filtered on Vgs(th) <= 1.0 V and Id >= 200 mA, both computed, and
# then named a package out of habit. Diodes DMG1012T (DS31783 Rev. 8-2) meets
# the two derived filters -- Vgs(th) 0.5 to 1.0 V, Id 0.63 A at 25 C -- and
# meets them with the row that actually matters here:
#
#     R_DS(on) at V_GS = 1.8 V, I_D = 350 mA:  0.5 ohm typ, 0.7 ohm max
#
# **1.8 V is the number pump_timing() computes**, to two decimal places, and
# this is the only candidate whose data sheet characterises it there rather
# than leaving a curve to be read at the one gate voltage this circuit can
# produce. A part specified only at 4.5 V would have been a guess about the
# region the design lives in. The package followed the electrical filter, which
# is the right way round.
BYPASS_FET = "DMG1012T"
BYPASS_RELAYS = 3
BYPASS_POLES_EACH = 2
BYPASS_COIL_V = 5.0                    # V5 exists in RAILS; the coil must suit
BYPASS_COIL_OHMS = 178.0               # G6S data sheet page 2, at 5 VDC
BYPASS_COIL_MA = (28.1 * 0.9, 28.1 * 1.1)   # read, +-10% per the table's note 1
BYPASS_TRANSFER_MS = 5.0               # section 4.5's own figure

# The pump, and every value here is set by an inequality rather than preferred.
PUMP_HZ = 10_000.0                     # "~10 kHz on a GPIO", section 4.5
PUMP_GPIO_V = 3.3                      # RP2040 output swing
PUMP_DIODE_VF = 0.32                   # BAT54-class Schottky at microamps
PUMP_C = "2n2/50V C0G"
PUMP_C_FARADS = 2.2e-9
PUMP_HOLD_C = "1u/16V X7R"
PUMP_HOLD_C_FARADS = 1e-6
PUMP_BLEED_R = "100k 1%"
PUMP_BLEED_R_OHMS = 100_000.0

# What the gate has to do with 1.8 V, which is all the pump can give it. This is
# a filter on which MOSFET may be fitted, in the same sense RELAY_PINS was a
# filter on which relay: a part with a 2.5 V threshold will not turn on at all,
# and one with a 1.0 V threshold will. It is not a part number.
FET_VGSTH_MAX = 1.0
FET_ID_MIN = 0.2                       # A, to cover three coils with margin


def pump_timing(c_pump=None, c_hold=None, r_bleed=None):
    """When the module comes into circuit, and how long it stays there dead.

    A two-diode pump is a switched capacitor, so it presents the hold node a
    source resistance of 1/(f*C) -- 45 kohm here -- and the bleed resistor that
    discharges the node also divides the pump's output down. Both time
    constants fall out of that pair, and **they are not independent**:

        t_on   the gate reaching the FET's threshold from cold
        t_off  the gate falling back through it after the drive stops

    with t_off / t_on always greater than one, because the same capacitor
    charges through R_eq in parallel with the bleed and discharges through the
    bleed alone. **A pump cannot be made to drop out faster than it picks up**,
    which is the opposite of what a fail-safe would prefer and is worth knowing
    before somebody tries to tune it that way.

    So the values are chosen against two inequalities and the second one is why
    this block exists at all:

      * `t_off` bounds how long a wedged MCU keeps the module in circuit. It
        wants to be short;
      * `t_on` must exceed VREF_TURN_ON_S. **This is the consumer that number
        has been waiting for.** The '541's Vcc is VREF, so for 20 ms after
        power-up the CV chain's full scale is ramping from zero and a control
        voltage of zero is unity gain -- and the relay must not put the module
        into circuit during that. Nothing in firmware is trusted for it: the
        hold capacitor starts at zero volts, so the delay is a property of the
        board.

    `margin_v` is the third inequality and the thinnest: the pump's final
    voltage against the threshold of whatever MOSFET is fitted. There is no
    room to spend here, which is why FET_VGSTH_MAX is declared as a
    requirement.
    """
    c_pump = c_pump or PUMP_C_FARADS
    c_hold = c_hold or PUMP_HOLD_C_FARADS
    r_bleed = r_bleed or PUMP_BLEED_R_OHMS

    r_eq = 1.0 / (PUMP_HZ * c_pump)
    v_final = ((PUMP_GPIO_V - 2 * PUMP_DIODE_VF)
               * r_bleed / (r_bleed + r_eq))
    tau_rise = (r_eq * r_bleed / (r_eq + r_bleed)) * c_hold
    tau_fall = r_bleed * c_hold
    return {
        "r_eq": r_eq,
        "v_final": v_final,
        "margin_v": v_final - FET_VGSTH_MAX,
        "tau_rise": tau_rise,
        "tau_fall": tau_fall,
        "t_on": -tau_rise * math.log(1 - FET_VGSTH_MAX / v_final),
        "t_off": tau_fall * math.log(v_final / FET_VGSTH_MAX),
        "interlock": -tau_rise * math.log(1 - FET_VGSTH_MAX / v_final)
                     > VREF_TURN_ON_S,
        "needs": VREF_TURN_ON_S,
        "transfer_s": BYPASS_TRANSFER_MS * 1e-3,
    }


def coil_budget():
    """What holding the module in circuit costs, continuously.

    The number that makes this block a supply requirement rather than a corner
    of the schematic, and it is the price of the non-latching relay the
    mechanism forces. Compared against everything else on the board, because a
    figure like this only means something next to what it displaces.
    """
    low, high = BYPASS_COIL_MA
    quads = OPAMP_QUADS + ENV_QUADS
    # **1.7 mA was here and no row of the OPA1644's table says 1.7.** Its
    # POWER SUPPLY section gives 1.8 mA typical per amplifier and 2.3 maximum
    # (SBOS484D page 8); the figure used here matched neither. Both constants
    # come from OPAMP_IQ_MA and ENV_OPAMP_IQ_MA now, so this and supply_load()
    # cannot quote different numbers for the same amplifiers -- which they did.
    amplifiers = (OPAMP_QUADS * OPAMP_SECTIONS * OPAMP_IQ_MA[0]
                  + ENV_QUADS * OPAMP_SECTIONS * ENV_OPAMP_IQ_MA[0])
    vcas = VCA_PACKAGES * VCA_SUPPLY_MA
    return {
        "relays": BYPASS_RELAYS,
        "low_ma": low * BYPASS_RELAYS,
        "high_ma": high * BYPASS_RELAYS,
        "amplifiers_ma": amplifiers,
        "vcas_ma": vcas,
        "rest_ma": amplifiers + vcas,
        "quads": quads,
        "ratio": (low + high) / 2 * BYPASS_RELAYS / (amplifiers + vcas),
        "rail": "VMOD",
    }


# What each amplifier costs its rails, typical and maximum. **The pair matters
# and the repo only had one half of it**: coil_budget() computed the board's
# draw from typicals alone, which is the right number for "what does the module
# dissipate" and the wrong one for "what must the supply deliver". A supply is
# sized on maxima, and the two differ here by 41 %.
#
# OPA1644, SBOS484D page 8, POWER SUPPLY: quiescent current per amplifier,
# I_OUT = 0 A -- 1.8 mA typ, 2.3 mA max. Read first-hand. **This corrects the
# 1.7 mA that coil_budget() carried**, which matched no row of that table.
OPAMP_IQ_MA = (1.8, 2.3)

# TL074, and **this is the one figure in the supply arithmetic that is not
# read.** SLOS080W (July 2025) is a combined TL071/72/74 document; the pages
# walked in this session carry the TL07x**H** grade at 937.5 uA typ and
# 1125 uA max per amplifier, and the plain grade's own row was not located. The
# 1.4 mA typical below is the figure the repo already carried, unsourced. The
# maximum is declared as an envelope rather than invented precisely, and it is
# deliberately the pessimistic end: MEASURED["env_opamp_iq"] holds the range.
#
# It is 8 amplifiers of 40, so the whole uncertainty is 8 mA on a rail carrying
# about 110 -- worth declaring, not worth blocking on.
ENV_OPAMP_IQ_MA = (1.4, 2.5)


def supply_load():
    """What each rail must deliver, counted off the netlist rather than a table.

    **Counted, because the alternative drifted.** coil_budget() multiplies
    OPAMP_QUADS and ENV_QUADS by a per-section figure, and those constants are
    derived from how many sections the design *needs* -- not from how many
    packages are on the sheet. The two agree today and nothing holds them
    together. This walks pin_owner(), so a package added to a rail appears here
    whether or not anybody updated a count.

    Returns typical and maximum milliamps per rail. The maximum is the number a
    DC-DC is chosen against; the typical is the number the board dissipates.
    """
    owner = DESIGN.pin_owner()
    on_rail = {}
    for (ref, _), net in owner.items():
        on_rail.setdefault(net, set()).add(ref)

    def quads(rail, refs):
        return sorted(r for r in on_rail.get(rail, ()) if r in refs)

    mcu = mcu_rail_load()
    opamps = quads("VA+", set(OPAMP_PACKAGES_REFS))
    envs = quads("VA+", set(ENV_PACKAGES_REFS))
    vcas = quads("VA+", set(VCA_PACKAGES_REFS))
    coils = sorted(on_rail.get("VMOD", set()) & set(BYPASS_RELAY_REFS))
    # The 3.3 V rail, counted on V5 because that is where it comes from. Its
    # own load is the ADC, and the regulator's quiescent current goes with it
    # -- 4 uA maximum, which is the reason a linear rail was affordable here
    # at all and is the number the NCP1117 would have made 10 mA.
    adc = sorted(on_rail.get("V3V3", set()) & {ENV_ADC_REF})
    v3v3_typ = len(adc) * (ENV_ADC_AIDD_MA[0] + ENV_ADC_DIDD_MA[0])
    v3v3_max = len(adc) * (ENV_ADC_AIDD_MA[1] + ENV_ADC_DIDD_MA[1])
    if adc:
        v3v3_typ += V3V3_IQ_MA
        v3v3_max += V3V3_IQ_MA

    bipolar_typ = (len(opamps) * OPAMP_SECTIONS * OPAMP_IQ_MA[0]
                   + len(envs) * OPAMP_SECTIONS * ENV_OPAMP_IQ_MA[0]
                   + len(vcas) * VCA_SUPPLY_MA)
    bipolar_max = (len(opamps) * OPAMP_SECTIONS * OPAMP_IQ_MA[1]
                   + len(envs) * OPAMP_SECTIONS * ENV_OPAMP_IQ_MA[1]
                   + len(vcas) * VCA_SUPPLY_MA_MAX)
    coil_typ, coil_max = (BYPASS_COIL_MA[0] * len(coils),
                          BYPASS_COIL_MA[1] * len(coils))
    return {
        "VA+": {"typ_ma": bipolar_typ, "max_ma": bipolar_max,
                "volts": RAILS["VA+"], "parts": opamps + envs + vcas,
                "source": None},
        "VA-": {"typ_ma": bipolar_typ, "max_ma": bipolar_max,
                "volts": RAILS["VA-"], "parts": opamps + envs + vcas,
                "source": None},
        # **What is left on the linear rail, and it is two parts.** V5 used
        # to carry three relay coils as well, and that was 93 mA of the
        # converter's +Vout for 465 mW of coil -- see mcu_supply() for what
        # moved them. What stays is what a switched rail would have been the
        # wrong home for: the MAX6126, which is the reference the whole CV
        # chain is measured against, and the MCP1700 that makes the envelope
        # ADC's own analogue 3.3 V out of it. Neither is large and both are
        # quiet, which is the entire argument for keeping a linear regulator
        # whose quiescent current is now four times its load.
        "V5": {"typ_ma": VREF_SUPPLY_MA[0] + v3v3_typ,
               "max_ma": VREF_SUPPLY_MA[1] + v3v3_max,
               "volts": RAILS["V5"],
               "parts": [REF_REF] + ([V3V3_REF] if adc else []),
               "source": None},
        # Declared as a rail of its own even though it is drawn from V5,
        # because check_rails_are_drawn() reads RAILS and RAILS is the list of
        # rails this board *has*. A rail whose current is folded into its
        # parent's line and named nowhere is how V3V3 sat in RAILS for four
        # passes with no net.
        "V3V3": {"typ_ma": v3v3_typ, "max_ma": v3v3_max,
                 "volts": RAILS["V3V3"], "parts": adc, "source": "V5"},
        # **U22's output, and it has exactly two loads: a divider and a
        # module.** Declared as a rail because it has a net and a voltage and
        # check_rails_are_drawn() reads RAILS -- and because calling it "the
        # switcher's output node" rather than a rail is how a 3.3 V net with a
        # converter on each end stops being anybody's subject.
        # **U22's output, and it has two customers with nothing in common.**
        # The module, through D806, and the three relay coils. Declared as a
        # rail because it has a net and a voltage and check_rails_are_drawn()
        # reads RAILS -- and because calling it "the switcher's output node"
        # rather than a rail is how a 5 V net with 160 mA on it stops being
        # anybody's subject.
        "VMOD": {"typ_ma": mcu_chain()["vsys_ma"] + coil_typ,
                 "max_ma": mcu_chain(MEASURED["pico_smps_efficiency"].low,
                                     None)["vsys_ma"] + coil_max,
                 "volts": RAILS["VMOD"],
                 "parts": [MCU_DCDC_REF] + coils,
                 "source": None},
        # **The controller's rail, and its source is a pin on a part now.**
        # It used to be None for the same reason V5's is -- a rail this module
        # dissipates power on, with what it costs the converter asked one
        # function down. That is still true and there is one more stage in
        # between: VMCU is made by the module's own RT6150 out of VSYS, so
        # naming VMOD as its source is what stops supply_fit() from counting
        # 3.3 V of load straight against twelve volts of converter and getting
        # the answer the board had before the module.
        "VMCU": {"typ_ma": mcu["typ_ma"], "max_ma": mcu["load_ma"],
                 "volts": RAILS["VMCU"], "parts": mcu["parts"],
                 "source": "VMOD"},
    }


def supply_requirement():
    """The DC-DC this board needs, as numbers rather than as a topology.

    Spec section 1.1 decided the topology -- one DC inlet, an isolated DC-DC at
    >= 300 kHz -- and left the sizing to a table in supply-decision.md that
    predates the schematic. **That table says "~44 mA per rail" for the bipolar
    domain and the board draws 110 mA maximum**, which is not a small error and
    has a specific cause worth recording rather than patching.

    The document's own argument was that the CV filters and the envelope
    rectifiers should run single-supply off +5 V, precisely so the negative rail
    would stay small -- "the temptation will be to run everything bipolar
    because it's simpler to think about. Resist it." The schematic did not
    resist it: U7, U8, U13 and U14 are all on VA+/VA-, which is 16 amplifiers
    of the 40.

    **And the reason the advice stopped applying is in the same document.** The
    44 mA figure existed to make a *charge pump* viable -- "at 100 mA a charge
    pump would have been out; at 44 mA it is comfortable". The decision that
    document reaches is an isolated DC-DC, which does not care. So running the
    CV and envelope stages bipolar is defensible, and nobody wrote down that the
    constraint it violated had been retired. That is the gap this function
    closes: the number is now derived from what is drawn.
    """
    load = supply_load()
    # **Only the rails nothing else feeds.** V3V3 is made from V5 and its
    # current is already counted in V5's line, so adding 3.3 V x 1.67 mA here
    # would count the same milliamps twice and dissipate them at two voltages
    # at once. That is the same mistake in method supply_fit() records at the
    # other end -- summing rail powers without the topology between them -- so
    # the topology is data now: each rail says what feeds it, and this sums
    # the roots.
    watts = sum(abs(rail["volts"]) * rail["max_ma"] * 1e-3
                for rail in load.values() if rail["source"] is None)
    return {
        "load": load,
        "rails": {name: rail["volts"] for name, rail in load.items()},
        "isolated": True,
        "min_khz": SUPPLY_MIN_KHZ,
        "watts_max": watts,
        "doc_estimate_ma": 44.0,
        "largest_single_load": "three relay coils on V5, 93 mA",
    }


# ---------------------------------------------------------------------------
# The supply, and the first thing it decides is not a part
# ---------------------------------------------------------------------------
# **Two artefacts of this repo disagreed about where the converter goes, and
# nothing checked which.** `floorplan.ZONES` has carried a zone P since the
# first pass -- "supply", DIGITAL domain, "the far corner from A1 and R, with
# its own local return", and a placement rule about |f - 45 kHz| that is a rule
# about *this board's* copper. `design.py` meanwhile described J8 as "from the
# isolated DC-DC (DEFERRED): 1=VA+, 2=VA-, 3=MAGND, 4=V5, 5=MDGND", which is a
# five-way *secondary* inlet and puts the converter on some other board.
#
# Both were written down, both were consumed -- placement.py implements the
# zone list, gen_sch.py draws the header -- and the two claims cannot both be
# true. Nothing in the repo compares a zone's declared contents against the
# parts that exist, because until now every zone except P and D2 had some.
#
# **This paragraph named `floorplan.check_zone_occupancy()` as "the instrument
# that would have said so", and it did not exist.** A named check, in a comment
# about two artefacts disagreeing because nothing compared them -- which is the
# same failure one level further out, and it survived two passes because a
# comment naming a function is not a call to it. It exists now as
# `placement.check_zone_occupancy()`: there rather than in floorplan.py because
# floorplan.py cannot import placement.py -- the dependency runs the other way,
# for the domain table -- and the question is "what is placed where", which is
# placement's own subject. It reads a zone-to-parts table that had to be
# written down for the first time, which is itself the point: until the last
# zone was drawn, "the parts in zone P" was not a thing any file could be
# asked for.
#
# **The converter comes onto this board**, and zone P is the older and the
# derived claim of the two:
#
#   * spec section 0 says "One board." An off-board converter is an undeclared
#     second PCB in a project whose scope statement is one;
#   * the isolation barrier is what makes constraint 5.2 true *by
#     construction* -- supply-decision.md's own decisive argument. Off-board,
#     the barrier is somebody's wiring and the guarantee is discipline again,
#     which is the thing that document rejects the non-isolated option for. On
#     this board the barrier is copper, and copper is what verify.py can read;
#   * there is room. The board is 19,046 mm2 with 1,654 mm2 of placed
#     courtyard, and zone P's corner is empty.
#
# So J8 stops being a five-way secondary inlet and becomes a two-way *primary*
# one: the raw brick, in parallel with the mixer's own J8 at the shared barrel
# jack. Every net it used to carry is generated here now.

# The shared inlet, read off the mixer at the pinned commit rather than
# assumed: SUPPLY_RANGE is "12-18V DC centre-negative, 25mA" and SUPPLY_INTENT
# is "2.1mm barrel, centre negative (Boss standard)". **The positive terminal
# is the sleeve** -- the mixer's own J8 comment records that the instruction
# beside it said "centre pin" for the whole life of that design and was
# backwards, which is worth copying correctly rather than re-deriving.
#
# 18 V is the top of the accepted range and the mixer's own note says an 18 V
# brick "measures about 20 V unloaded", which is the number a part is chosen
# against.
INLET_VOLTS = (12.0, 18.0)
INLET_UNLOADED_MAX = 20.0

# Traco TMR 6-2422WI. Datasheet TMR 6WI Series, 6 Watt, revision 7 November
# 2023, read first-hand -- all four pages. Every figure below is from it.
#
#     Models          TMR 6-2422WI: 9-36 VDC in (24 VDC nom.),
#                     +12 VDC 250 mA / -12 VDC 250 mA, efficiency 87 % typ.
#     Switching       "522 - 638 kHz (PWM) / 580 kHz typ. (PWM)"
#     Topology        "Flyback Converter"
#     Isolation       1'600 VDC test, 1'000 Mohm, "Isolation Capacitance
#                     - Input to Output, 100 kHz, 1 V: 50 pF max."
#     Cross reg.      "5 % max." at 25 % / 100 % asymmetric load
#     Ripple/noise    "12 / -12 Vout models: 75 / 75 mVp-p max." (20 MHz BW)
#     Capacitive load "12 / -12 Vout models: 330 / 330 uF max."
#     Minimum load    "Not required"
#     Start-up        30 ms typ.
#     Transient       250 us typ. at a 25 % load step
#     Input filter    "Internal Capacitor"
#     Input fuse      "24 Vin models: 1'600 mA (slow blow)"
#     Package         SIP8, 21.8 x 9.1 x 11.2 mm, 4.8 g
#
# **Why this part and not the obvious cheaper one.** The plain TMR 6 -- same
# power, same package, same outputs, half the price -- is "100 kHz min." on an
# **RCC** topology, which is self-oscillating: its frequency moves with load
# and input voltage. Two things are wrong with that here and the second is the
# one nobody would think of. 100 kHz clears the |f - 45 kHz| > 20 kHz rule, and
# it is also exactly twice the mixer's pump, so the converter's fundamental
# sits on the pump's second harmonic and beats with it at **DC**. And a
# frequency that wanders cannot be designed against at all: supply_beat()
# below only has an answer because 522-638 kHz is a stated band.
SUPPLY_PART = "TMR6-2422WI"
SUPPLY_MPN = "TMR 6-2422WI"
SUPPLY_VIN = (9.0, 36.0)
SUPPLY_VOUT = 12.0
SUPPLY_IOUT_MA = 250.0
SUPPLY_WATTS = 6.0
SUPPLY_EFFICIENCY = 0.87
SUPPLY_KHZ = (522.0, 638.0)
SUPPLY_KHZ_TYP = 580.0
SUPPLY_RIPPLE_VPP = 75e-3
SUPPLY_CLOAD_MAX_F = 330e-6
SUPPLY_ISO_PF = 50e-12
SUPPLY_CROSS_REG = 0.05
SUPPLY_FUSE_A = 1.6
SUPPLY_DATASHEET = ("https://cdn-reichelt.de/documents/datenblatt/C700/"
                    "TMR6-2411WI_DB.pdf")

# Dual-output pinout, datasheet page 4. **There is no pin 4** -- the package is
# a SIP-8 with the fourth position omitted, which is the creepage gap between
# primary and secondary, and it is the reason the footprint has to be right:
# 5.08 mm between pin 3 and pin 5 where every other gap is 2.54.
SUPPLY_PINS = {"-Vin": 1, "+Vin": 2, "Remote": 3, "NC": 5,
               "+Vout": 6, "Com": 7, "-Vout": 8}
SUPPLY_REF = "U15"
# The one part allowed to sit across the barrier that is not the converter.
# Declared here and again in placement.ISOLATION_BRIDGE, because the netlist
# claim and the copper claim are different claims: floorplan.check_isolation()
# reads this one and verify.check_isolation_gap() reads the other.
ISOLATION_BRIDGE = ("C810",)
# **The second barrier's bridge, and it is the same shape one board along.**
# CA-033 forbids a DC path from the MIDI IN jack's pin 2 or its shield to this
# board's ground and offers a capacitor as the way to have an RF one anyway --
# "a connection through a small capacitor (0.1uF typical) to ground is optional
# for improved high-frequency (RF) shielding". C836 is that capacitor, and it
# is declared here for the reason C810 is: a part that crosses a barrier is
# either the barrier or a fault, and the only way a check can tell is a list.
MIDI_BRIDGE = ("C836",)
# Everything on the isolated primary, by reference. Declared here rather than
# written out in verify.check_supply(), which is where the list used to live
# as a set literal: a part added to the primary and not to that literal is a
# check that quietly stops covering the thing it names. L801 is the part that
# found it.
# F801 is a literal here and INLET_FUSE_REF thirty lines below, because
# this list is declared before the fuse's own block. One of the two has
# to be a string and this is the one nothing computes from.
PRIMARY_PARTS = ("J8", "F801", "L801", "D804", "C807", "C808", "C809")
# **The primary's nets, and this moved here from verify.py because a second
# file needed it.** gen_pcb.py reserves the primary's corner of the board and
# admits only these nets into it; verify.check_isolation_gap() measures the
# same region against the same list. Those were two literals in two files that
# cannot import each other, agreeing because one person typed them twice --
# which is the fault PRIMARY_PARTS' own comment above records, one net class
# along. Fitting F801 is what would have separated them: the reservation would
# have kept VIN_F out of the region its own part sits in.
#
# Four nets and a reference: IGND is the primary's 0 V, and the live conductor
# is cut twice, by the fuse and by the choke, so it is three nets rather than
# one. A net that spans a part is a net that says the part is not there.
PRIMARY_NETS = frozenset({"IGND", "IGND_J", "VIN", "VIN_F", "VIN_J", "VIN_P"})

# ON Semiconductor NCP1117, publication NCP1117/D revision 25, June 2013, read
# first-hand. The 5.0 V fixed part:
#
#     Vin max              20 V
#     Vout                 4.950-5.050 V at 10 mA / 25 C;
#                          4.900-5.100 V over Vin 6.5-12 V, 0-800 mA, over T
#     Dropout at 100 mA    0.95 V typ, 1.10 V max
#     Quiescent current    6.0 mA typ, 10 mA max (5.0 V, Vin = 15 V)
#     Minimum load         "No Minimum Load Requirement for Fixed Voltage
#                          Output Devices"
#     Ripple rejection     57 dB min, 61 dB typ at 120 Hz
#     Output noise         0.003 %Vout, 10 Hz-10 kHz -- 150 uV rms
#     SOT-223 (318H)       R_thJA 160 C/W at minimum pad, R_thJC 15
#     DPAK (369C)          R_thJA  67 C/W at minimum pad, R_thJC 6.0
#     Tj max               150 C
#
# **The package is chosen by v5_regulator()'s arithmetic and not by habit**,
# and it is the one place on this board where the obvious choice is wrong: a
# SOT-223 is what a 100 mA regulator goes in, and 160 C/W against 0.77 W is
# 124 degrees of rise. The DPAK is the same die with a tab.
V5_PART = "NCP1117-5.0"
V5_MPN = "NCP1117DT50G"
V5_VOLTS = 5.0
V5_VIN_MAX = 20.0
V5_DROPOUT_V = 1.10                    # maximum, at Iout = 100 mA
V5_IQ_MA = (6.0, 10.0)
V5_TJ_MAX = 150.0
V5_THETA_JA = {"SOT-223": 160.0, "DPAK": 67.0}
V5_PINS = {"GND": 1, "VO": 2, "VI": 3}
V5_REF = "U16"

# What the board is expected to sit in. Not a measurement and not a guess with
# consequences -- it is the number the junction-temperature arithmetic is
# quoted at, and it is stated here so that changing it changes every answer at
# once. A closed aluminium box on a pedalboard, indoors.
AMBIENT_C = 40.0

# The rail filter. R is a resistor and not an inductor, and that is derived:
# an LC of the same corner has Q = R_load * sqrt(C/L), which for this load is
# about 59 -- a 35 dB peak at 15.9 kHz, inside the audio band, on the rail
# every channel shares. rail_filter() carries both.
RAIL_FILTER_R = "4R7 1%"
RAIL_FILTER_R_OHMS = 4.7
RAIL_FILTER_C = "10u/50V X7R"
RAIL_FILTER_C_FARADS = 10e-6

# The Y-capacitor across the isolation barrier, and it is the one part of this
# block that is load-bearing. barrier_return() is the argument and the value
# comes out of it.
BARRIER_C = "470n/50V X7R"
BARRIER_C_FARADS = 470e-9

# The primary side's own decoupling. 50 V parts on a rail that reaches 20 V,
# because a class-2 ceramic at 80 % of its rating has lost most of its
# capacitance -- the mixer makes the same argument at its own VIN_P and reaches
# 35 V there because its brick is the only thing on that node.
PRIMARY_BULK_C = "10u/50V X7R"
PRIMARY_BULK_C_FARADS = 10e-6
PRIMARY_HF_C = "100n/50V X7R"

# Reverse-polarity protection, and it is the mixer's own part for the mixer's
# own reason: a 3 A / 40 V Schottky run at a fraction of its rating has a
# forward drop far below what a correctly-sized small part would give. The
# mixer draws 25 mA through one and gets about 0.2 V; this draws 371 mA and
# gets about 0.35 V, which is what inlet_budget() spends.
INLET_DIODE = "B340A"
INLET_DIODE_VF = 0.35


# The common-mode choke in the inlet pair, and it is the second half of
# barrier_return() rather than an EMC part.
#
# Wurth Elektronik WE-SL2 **744222**, datasheet revision 008.002 of
# 2023-04-12, read first-hand. Every figure below is its own:
#
#     Number of windings   N       2
#     Inductance           L       100 kHz / 5 mV      1000 uH   +/-50 %
#     Maximum impedance    Zmax                        6000 ohm  typ
#     Rated current        IR      dT = 40 K            800 mA   max
#     DC resistance        RDC     @ 20 C              0.207 ohm max
#     Leakage inductance   LS      1 MHz / 1 mA           90 nH  typ
#     Insulation test      VT      50 Hz / 3 mA / 3 s    500 VAC max
#     Rated voltage        VR                             80 V
#     Body                         9.2 x 6.0 x 5.0 mm, AEC-Q200 Grade 1
#
# **Why a choke and not more capacitor**, which is the whole of the argument
# and is already written at barrier_return(): the barrier's common-mode
# current divides between the Y-capacitor and the loop the shared inlet
# closes, so a bigger C810 *divides* Z_Y and a choke *multiplies* Z_loop.
# C810 is at the value the low-frequency side of that trade allows -- 470 nF
# against a 610 nF ceiling -- so the capacitor has nothing left to give, and
# the remaining 19 dB has to come from the other side of the divider.
#
# **Four filters, and the third is the one that eliminates the obvious part.**
#
#   * **mH class.** At 580 kHz a ferrite bead is a few ohms and a 5 uH choke
#     is 18. Traco name their own TCK-122 as a compatible accessory and it is
#     5 uH: barrier_return(choke_uh=5.0) prices it at 4.3 dB, which is an EMC
#     accessory doing an EMC accessory's job and not this one. 1 mH is
#     3.6 kohm at 580 kHz, against a Z_Y of 0.58 ohm.
#   * **>= 0.5 A.** inlet_budget() gives 382 mA at the bottom of the accepted
#     brick range and 800 mA is the datasheet's own rated current at a 40 K
#     rise.
#   * **DC resistance is in series with the whole module.** Two windings carry
#     the supply current, so the DC loop sees 2 x 0.207 = 0.414 ohm maximum:
#     158 mV at 382 mA, which inlet_budget() now spends and which the
#     converter's 9 V minimum input has thirty times over.
#   * **It has to fit in the primary region**, which has no pour under it.
#     10.09 x 6.59 mm of courtyard, and the row it goes in re-spaces by
#     1.5 mm rather than the board growing -- see placement.SUPPLY.
#
# **580 kHz is on the inductive slope and the datasheet says where the slope
# ends**: Zmax is 6000 ohm and the distributor listing that quotes it gives
# the frequency as 4 MHz, so the self-resonance is nearly a decade above the
# converter's fundamental and |Z| = wL holds there. The binding uncertainty is
# not the frequency, it is the **+/-50 % tolerance**, and barrier_return()
# reports both ends of it.
INLET_CHOKE = "744222"
INLET_CHOKE_REF = "L801"
INLET_CHOKE_UH = 1000.0
INLET_CHOKE_TOLERANCE = 0.5
INLET_CHOKE_ZMAX = 6000.0
INLET_CHOKE_ZMAX_HZ = 4.0e6
INLET_CHOKE_IR_MA = 800.0
INLET_CHOKE_RDC = 0.207                # ohm, one winding, maximum
INLET_CHOKE_LEAKAGE_NH = 90.0
INLET_CHOKE_VR = 80.0
INLET_CHOKE_DATASHEET = ("https://www.we-online.com/components/products/"
                         "datasheet/744222.pdf")
# The datasheet's own Schematic block: winding A is 1-4 and winding B is 2-3,
# with 1 and 2 on one side of the body and 4 and 3 on the other. The inlet
# pair goes in at 1/2 and the converter hangs off 4/3, which is the connection
# that cancels the differential flux and leaves the common-mode inductance.
# Getting this pairing wrong -- 1-2 and 4-3 -- draws identically, passes ERC,
# and puts 1 mH in series with the supply current instead of across it.
INLET_CHOKE_PINS = {"L1_IN": 1, "L2_IN": 2, "L2_OUT": 3, "L1_OUT": 4}

# ---------------------------------------------------------------------------
# The inlet fuse, which was derived for four passes and not fitted
# ---------------------------------------------------------------------------
#
# **It is fitted now and nothing about the requirement changed.** The
# converter's datasheet has said "Recommended Input Fuse, 24 Vin models:
# 1'600 mA (slow blow)" since the part was chosen, and supply()'s own
# assessment -- that a shared inlet with a *fabricated* board carrying no fuse
# of its own wants one -- has stood unopposed for as long. What blocked it was
# neither of those: it was that no order code had been verified and KiCad
# shipped no land pattern for the families that were looked at. Section 6 of
# the spec forbids inventing a value and an order code is a value, so the
# requirement was recorded and the part left off.
#
# **SCHURTER UMT 250, datasheet dated 21/07/2026, read first-hand.** It is a
# ceramic surface-mount fuse, 3 x 10.1 mm, and its own headline is the whole
# specification: "Surface Mount Fuse, 3 x 10.1 mm, Time-Lag T, 250 VAC,
# 125 VDC". The 1.6 A variant, from the Variants table on page 4:
#
#     Rated current        1.6 A
#     Rated voltage        250 VAC, 125 VDC
#     Breaking capacity    note 2) -- IEC 200 A @ 250 VAC, 100 A @ 125 VDC
#     Characteristic       Time-Lag T, IEC 60127-4
#     Voltage drop 1.0 In  300 mV max, 124 mV typ
#     Power dissipation    1000 mW max at 1.25 In
#     Melting I2t 10 In    5.89 A2s typ
#     Order number         3403.0168.11 (bag) / 3403.0168.24 (tape)
#
# and from the Technical Data on page 1: ceramic housing, copper-alloy
# tin-plated terminals, -55 to 125 C, reflow and wave.
#
# **1.6 A and not the 1.5 A this file used to name.** supply()'s note read "a
# 1.5 A slow-blow -- below the datasheet's figure and four times the load --
# is the part", which was a number reached by dividing rather than by opening
# a catalogue: IEC 60127 fuses come in an E-series and 1.5 A is not one of the
# eighteen this family offers. The converter's vendor states 1.6 A for this
# exact model, the series has 1.6 A, and STYLE.md rule 10's own form applies
# -- where the vendor states a value it is used, and where it states a range a
# function here derives one. **A derived value that falls between two catalogue
# steps is a derivation that never met a catalogue.**
INLET_FUSE_REF = "F801"
INLET_FUSE = "1.6A T 250V"
INLET_FUSE_MPN = "3403.0168.11"
INLET_FUSE_A = SUPPLY_FUSE_A
INLET_FUSE_VDC = 125.0
# Voltage drop at rated current, the maximum and the typical. Divided by the
# rating these are a resistance -- 187 and 78 milliohms -- and both are the
# *hot* element: the figure is measured at 1.0 In, where the wire is close to
# melting. At the 24 % of rating this inlet runs at, the element is at ambient
# and its resistance is lower, so using the hot number in the headroom
# arithmetic is pessimistic in the direction headroom wants.
INLET_FUSE_DROP_MAX_V = 0.300
INLET_FUSE_DROP_TYP_V = 0.124
# Pre-arcing time, page 3, for the 0.08-6.3 A rows. The first is the reason
# inlet_fuse() can say what it says about the brick.
INLET_FUSE_PREARC = {1.25: "60 min min", 2.0: "120 s max",
                     10.0: "10 ms min, 100 ms max"}
INLET_FUSE_DATASHEET = "https://www.schurter.com/en/datasheet/typ_umt_250.pdf"


def inlet_fuse():
    """The inlet fuse against the load it passes and the fault it opens for.

    Three questions and the third is the one that decides what this part is
    worth.

        R_fuse   = V_drop(1.0 In) / In          # hot, so pessimistic here
        drop     = R_fuse x I_working
        headroom = V_brick_min - Vf(D804) - I x (2 R_choke + R_fuse) - 9 V

    **It passes the load with the margin a fuse wants.** inlet_budget() gives
    the working current, and 1.6 A against it is the ratio below. A fuse run
    near its rating opens on nothing in particular; run at a quarter of it,
    the derating curve (page 3, 100 % at 23 C, ~95 % at 40 C) is not in play
    at all.

    **Its drop comes out of the converter's input headroom** and is added to
    the choke's two windings there, which is why inlet_budget() takes a fuse
    resistance rather than this function reporting a drop nobody consumes.

    **And what it protects against is bounded by a part this project does not
    choose.** The pre-arcing table says 1.25 x In takes at least an hour and
    2 x In up to two minutes; ten times opens in 10 to 100 ms. So the fuse is
    protection only when the brick can source several amps into a fault. A
    24 V supply that current-limits at 2 A is 1.25 In and this fuse never
    opens -- the brick's own limit is the protection, and the fuse is
    insurance against the case where somebody plugs in a larger one.
    inlet_budget() already records that the brick is a system-level part
    nobody here has ordered; this is the second thing that turns on it.

    **Which is not an argument against fitting it.** The asymmetry is total:
    the part costs 11.4 mm of one row and a few pence, and the case it covers
    -- a converter failing short on an inlet shared with a fabricated board --
    is one where the alternative is whatever the brick does when asked for
    everything it has.
    """
    resistance_max = INLET_FUSE_DROP_MAX_V / INLET_FUSE_A
    resistance_typ = INLET_FUSE_DROP_TYP_V / INLET_FUSE_A
    working_a = inlet_budget()["worst_ma"] / 1e3
    return {
        "rating_a": INLET_FUSE_A,
        "working_a": working_a,
        "headroom_x": INLET_FUSE_A / working_a,
        "resistance_max": resistance_max,
        "resistance_typ": resistance_typ,
        "drop_max_v": resistance_max * working_a,
        "drop_typ_v": resistance_typ * working_a,
        "opens_fast_a": 10.0 * INLET_FUSE_A,
        "opens_slow_a": 2.0 * INLET_FUSE_A,
        "never_opens_a": 1.25 * INLET_FUSE_A,
        "prearc": INLET_FUSE_PREARC,
        "rated_vdc": INLET_FUSE_VDC,
        "inlet_max_v": INLET_UNLOADED_MAX,
    }



def supply_fit(include_mcu=True):
    """The converter's two outputs against what the board actually draws.

    **supply_requirement() states 3.10 W and the converter has to deliver
    3.87 W, and the 25 % is a mistake in method rather than in arithmetic.**
    That function sums each rail's power at its own voltage -- 12 V x 110 mA
    twice, 5 V x 93 mA once -- which is right for "what does the module
    dissipate" and wrong for "what must the converter deliver", because V5 is
    not one of the converter's outputs. It is made linearly from VA+, so every
    milliamp of it leaves the converter at *twelve* volts and arrives at five.

    Summing rail powers is exactly the shortcut that looks complete: three
    rails, three products, one total, nothing obviously missing. What it omits
    is the topology between them, and the omission is invisible until somebody
    draws the topology. It is the same shape as the assumption whose "if it is
    wrong" clause cancelled itself -- an answer that cannot be checked by
    looking harder at the thing that produced it.

    So this walks the other way: from the converter's pins outward.
    """
    load = supply_load()
    v5_ma = load["V5"]["max_ma"] + V5_IQ_MA[1]
    # **The controller's rail arrives here as an input current and not as a
    # load**, which is the whole difference between a switcher and the linear
    # rail beside it. V5's 95 mA leaves the converter as 95 mA; VMCU's 86 mA
    # leaves it as 3.3/12 of that, divided by an efficiency with a range. The
    # pessimistic end of MEASURED["mcu_dcdc_efficiency"] is what is spent,
    # because this is the arithmetic that decides whether a 250 mA part is
    # inside its rating.
    # **It is two efficiencies and a diode now, and this asks mcu_supply()
    # rather than repeating the arithmetic.** The single-line version --
    # load x 3.3 / (efficiency x 12) -- was right while there was one
    # converter, and a second copy of it here would have gone on being right
    # about a topology the board no longer has. mcu_supply() calls
    # supply_fit(include_mcu=False), so there is no ring.
    mcu_ma = 0.0
    if include_mcu:
        mcu_ma = mcu_supply()["input_ma"]
    positive = load["VA+"]["max_ma"] + v5_ma + mcu_ma
    negative = load["VA-"]["max_ma"]
    watts = SUPPLY_VOUT * (positive + negative) * 1e-3
    return {
        "positive_ma": positive,
        "mcu_ma": mcu_ma,
        "negative_ma": negative,
        "limit_ma": SUPPLY_IOUT_MA,
        "positive_headroom_ma": SUPPLY_IOUT_MA - positive,
        "negative_headroom_ma": SUPPLY_IOUT_MA - negative,
        "watts": watts,
        "watts_limit": SUPPLY_WATTS,
        "watts_headroom": SUPPLY_WATTS - watts,
        "rail_power_sum": supply_requirement()["watts_max"],
        # The imbalance the datasheet's cross-regulation figure is quoted
        # against: "5 % max." for 25 % / 100 % asymmetric load. This is milder
        # than that test, which is what makes 5 % an upper bound here rather
        # than a number to be interpolated.
        "asymmetry": (positive / SUPPLY_IOUT_MA, negative / SUPPLY_IOUT_MA),
        "cross_reg_volts": SUPPLY_VOUT * SUPPLY_CROSS_REG,
        "deferred_headroom_ma": SUPPLY_IOUT_MA - positive,
    }


def supply_beat(f_khz=None):
    """What the >= 300 kHz rule is worth, and it is not what it says.

    Spec section 1.1 and supply-decision.md give one rule --
    |f_module - 45 kHz| > 20 kHz, target >= 300 kHz -- with a mechanism that is
    real: a VCA is a multiplier, so two ripple components on its control port
    do not add, they intermodulate, and the difference frequency lands in the
    audio band.

    **The rule is a fundamental-only rule and the mechanism is not.** The
    mixer's pump is a switched-capacitor inverter, so its ripple is a sawtooth
    with harmonics at every n x 45 kHz, and a converter at f beats with the
    n-th of them at |f - n x 45|. Over this part's own stated band, 522 to
    638 kHz, n runs from 12 to 14 and the beat passes through zero: there is
    no switching frequency, at any value, that clears every harmonic. A rule
    that can be satisfied by choosing a number, when the thing it defends
    against cannot be, is a rule that stops measuring the moment it is obeyed.

    So what makes this safe is not the frequency. Two things, and the first is
    the one the same document already bought and did not notice it had:

      * **isolation.** This module shares no rail with the mixer, so the pump's
        ripple reaches it only down the audio path, as signal, through the
        mixer's own rail filter and its op-amps. The one place two supply
        ripples could meet at full size is a shared rail, and there is not
        one. The ground bond carries the *other* direction and
        barrier_return() is where that is priced;
      * **order.** The product at |f1 - f2| is second order in both
        amplitudes. In the SSI2164's control law a rail ripple of amplitude a1
        and a second of a2 give a difference-frequency gain modulation of
        a1 x a2 / 2, so two terms at -56 dB each make one at -117 dB.

    That second line is also the honest answer to "why one converter and not
    two", which is the question this block was expected to turn on. **It does
    not turn on it.** Two independent TMR 6WI would beat somewhere in 0 to
    116 kHz -- unbounded below, so for some pair of units it is in the audio
    band with certainty -- and it would still be 117 dB down. What decides one
    converter is that a second one is a second isolation barrier, a second
    Y-capacitor network and a second 18-pound part, against 0.77 W of heat in
    a regulator. See v5_regulator().
    """
    f_khz = f_khz or SUPPLY_KHZ_TYP
    pump_khz = socket.PUMP_FREQUENCY / 1e3
    # **How far up the harmonics to look is a function of the frequency and it
    # used to be the literal 20.** That was right for the only caller this had
    # -- 580 kHz is the pump's 12.9th -- and wrong the moment mcu_dcdc_beat()
    # asked it about 1.1 MHz, which is the 24th: the search stopped at 900 kHz
    # and reported a 200 kHz beat against the 20th, when the real answer is
    # 20 kHz against the 24th. Nothing was wrong with the arithmetic; the
    # constant was a fact about one caller written where it looked like a fact
    # about sawtooths. The report printed the wrong number once.
    orders_needed = int(f_khz / pump_khz) + 2
    orders = [(abs(f_khz - n * pump_khz), n)
              for n in range(1, orders_needed + 1)]
    beat_khz, order = min(orders)
    # The whole stated band, not the typical: the part is not trimmed and two
    # units are not the same frequency.
    reachable = [n for n in range(1, orders_needed + 1)
                 if SUPPLY_KHZ[0] <= n * pump_khz <= SUPPLY_KHZ[1]]
    return {
        "f_khz": f_khz,
        "pump_khz": pump_khz,
        "rule_khz": SUPPLY_MIN_KHZ,
        "fundamental_beat_khz": abs(f_khz - pump_khz),
        "rule_holds": abs(f_khz - pump_khz) > 20.0,
        "worst_beat_khz": beat_khz,
        "worst_order": order,
        "in_audio_band": beat_khz * 1e3 < BANDWIDTH,
        "harmonics_inside_band": reachable,
        # Two units of one part, each anywhere in its own stated band.
        "two_unit_beat_khz": (0.0, SUPPLY_KHZ[1] - SUPPLY_KHZ[0]),
    }


def ripple_am(volts):
    """Gain modulation the SSI2164 makes of a ripple on its control port.

    Deliberately pessimistic in the one place a figure is missing: it assumes
    the ripple reaches V_C **undiminished**, which is a power-supply rejection
    of 0 dB. The OPA1644's PSRR at half a megahertz was not read this session
    and inventing it is what section 6 forbids, so the arithmetic is done at
    the value that cannot be optimistic. Every real amplifier does better.

    Returns the modulation as a fraction and in dB relative to the signal.
    """
    decibels = abs(volts) / abs(control_constant())
    fraction = 10 ** (decibels / 20.0) - 1.0
    return {"volts": volts, "db_of_gain": decibels, "fraction": fraction,
            "am_db": 20 * math.log10(fraction) if fraction > 0 else -math.inf}


def rail_filter(r_ohms=None, c_farads=None, f_khz=None):
    """What is left of the converter's 75 mVp-p by the time a channel sees it.

    One pole per rail, R then C, and **the R is the derivation**. The obvious
    part is an inductor -- same corner, no drop, no dissipation -- and it is
    wrong here for a reason that is arithmetic rather than taste. An LC loaded
    by a current sink has

        Q = R_load x sqrt(C / L)

    and at equal corners sqrt(L/C) is exactly this resistor's own value, so
    the comparison needs no second set of numbers: 12 V / 110 mA = 109 ohm
    against 4.7 gives Q = 23, which is a 27 dB peak at 3.4 kHz -- inside the
    audio band, on the one rail all six channels share. Damping it costs a
    resistor and a capacitor, which is more parts than starting with the
    resistor. The RC has no resonance to damp, and its cost is 0.52 V of rail
    and 56 mW in an 0805 rated 125.

    The DC drop is spent where it is worth least: the LDO is fed from the
    converter's pin, ahead of this resistor, so the 93 mA of relay coil never
    flows through it. That is worth stating because it is the whole reason the
    resistor can be this big -- with the coils downstream of it the drop would
    be 0.47 V and would step by 0.2 V every time the module went into circuit.
    """
    r_ohms = r_ohms or RAIL_FILTER_R_OHMS
    c_farads = c_farads or RAIL_FILTER_C_FARADS
    # The bottom of the stated band, because that is the least attenuated.
    f_hz = (f_khz or SUPPLY_KHZ[0]) * 1e3
    corner = 1.0 / (2 * math.pi * r_ohms * c_farads)
    attenuation = math.sqrt(1 + (f_hz / corner) ** 2)
    residual = SUPPLY_RIPPLE_VPP / attenuation
    current = supply_load()["VA+"]["max_ma"] * 1e-3
    # The LC of the same corner, which is the comparison: equal corners means
    # sqrt(L/C) = R, so the characteristic impedance the damping is measured
    # against is this resistor's own value and Q falls straight out of the
    # load impedance divided by it.
    inductor_h = r_ohms * r_ohms * c_farads
    inductor_q = (SUPPLY_VOUT / current) / r_ohms
    return {
        "r_ohms": r_ohms,
        "c_farads": c_farads,
        "corner_hz": corner,
        "attenuation_db": 20 * math.log10(attenuation),
        "residual_vpp": residual,
        "am": ripple_am(residual / 2.0),
        "drop_v": r_ohms * current,
        "watts": current * current * r_ohms,
        "rail_v": SUPPLY_VOUT - r_ohms * current,
        # What the same corner would cost as an LC, which is the comparison
        # the docstring makes and the reason there is no inductor here.
        "lc_q": inductor_q,
        "lc_h": inductor_h,
        "lc_peak_db": 20 * math.log10(inductor_q),
        "cload_limit_f": SUPPLY_CLOAD_MAX_F,
        "cload_used_f": 2 * c_farads,
    }


def barrier_return(c_y=None, node_vpp=None, loop_uh=None, choke_uh=None):
    """Where the isolation barrier's own current goes, and it is load-bearing.

    The one part of this block that constraint 5.2 can be lost to, and it is
    not a DC bond. The converter's barrier is 50 pF (datasheet, input to
    output, 100 kHz, 1 V) and the primary's switching node swings across it at
    580 kHz, so a common-mode current flows from primary to secondary and has
    to get back. Two paths, in parallel:

      1. the Y-capacitor, primary ground to MDGND, at the module -- a loop of
         millimetres;
      2. out through the secondary ground, across R902, across R901, along the
         bond wire into the mixer's AGND, through the mixer's own AGND/PGND
         star, back down the shared inlet lead to the barrel jack, through
         **L801** and into the primary. **That path runs through the audio
         ground bond**, which is the one conductor this whole design is
         arranged around.

    Without (1) all of it takes (2), and this computes what that is worth:
    milliamps at 580 kHz across a bond whose impedance at that frequency is
    the loom's inductance, in series with every channel's signal return.

    **The value of C810 is a trade and not a maximum**, which is why it is
    computed rather than picked. A larger Y-capacitor takes more of the
    barrier current locally and also lowers the impedance of the
    low-frequency loop that the isolation exists to open -- so the same part
    that fixes the 580 kHz problem re-creates a hum loop if it is made big
    enough. Both directions are below, and 470 nF is where the residual at
    580 kHz and the injection at 100 Hz are both small: the second is helped
    by the fact that the bond's impedance at 100 Hz is its resistance,
    milliohms, and not the fraction of an ohm it presents at half a megahertz.

    **The choke is the other side of that divider and it is fitted now.** The
    split is Z_Y against Z_loop; a capacitor can only divide the first and
    C810 is already at the largest value the 100 Hz side allows. L801 is
    3.6 kohm at 580 kHz against a 2.8 ohm loop, so it multiplies the second by
    1300 and the residual goes from 1.24 mV to about a microvolt -- from
    18.7 dB *above* the mixer's own noise floor to 42 dB below it. See
    INLET_CHOKE for the part and the four filters that chose it.

    ------------------------------------------------------------------------
    **The correction, and it is the reason fitting the part had to change the
    function rather than just its argument.** This returned

        bond_v = through_loop * z_loop

    with z_loop the whole of MEASURED["inlet_loop_uh"] plus BOND_R_OHMS. That
    is right -- pessimistically right -- while every ohm in the loop *is*
    bond: the loop and the bond are the same conductor, so the current times
    the loop impedance is the voltage across the thing the audio returns
    share, and attributing all of the loom's inductance to the bond overstates
    it in the safe direction.

    **Fitting the choke breaks that identity, and it breaks it in the
    direction that hides the result.** With 3.6 kohm of choke in the loop,
    `through_loop * z_loop` is 1.5 mV -- *larger* than the 1.24 mV it reports
    unfitted -- because the current falls by 1300 and the impedance it is
    multiplied by rises by 1300. The function would have said the choke made
    the design 0.4 dB worse, and every number downstream would have agreed
    with it. The voltage across a choke on the primary side is not a voltage
    in series with any audio return; it is the whole point of the part.

    So the two impedances are separate now: `z_bond` is what the residual is
    developed across, `z_choke` is what keeps the current out of it, and
    `z_loop` is their sum and is only used as the denominator of the divider.
    Nothing about the unfitted answer changes -- at choke_uh = 0 the two are
    equal and this returns exactly what it returned before.

    **What that says about the instrument, which is the part to keep.** The
    old expression was not a wrong formula. It was a formula that was correct
    only because two quantities happened to be the same number, with nothing
    anywhere recording that they were different quantities. A design change
    that separated them was always going to produce a confident wrong answer,
    and the only warning was that the answer got worse when the part got
    better. This repo's habit of printing a delta rather than a value is what
    would have caught it, and did.
    ------------------------------------------------------------------------

    Three figures here are assumptions or tolerances rather than readings, and
    all three are declared: the switching node's amplitude and the loop
    inductance are in MEASURED, and the choke's own +/-50 % is the datasheet's
    own tolerance, reported at both ends as `bond_v_low_l`.
    """
    c_y = c_y if c_y is not None else BARRIER_C_FARADS
    node_vpp = node_vpp or MEASURED["dcdc_node_v"].value
    loop_uh = loop_uh or MEASURED["inlet_loop_uh"].value
    choke_uh = INLET_CHOKE_UH if choke_uh is None else choke_uh
    omega = 2 * math.pi * SUPPLY_KHZ_TYP * 1e3
    # Fundamental of the switching node, treated as a sine of the stated
    # peak-to-peak. A real flyback edge has more high-frequency content and
    # less of it reaches the audio band, so this is the term that matters.
    drive_rms = node_vpp / (2 * math.sqrt(2))
    source_z = 1.0 / (omega * SUPPLY_ISO_PF)
    z_y = 1.0 / (omega * c_y) if c_y else math.inf
    # The two halves of the return path, kept apart. z_bond is the conductor
    # the audio shares; z_choke is in the same loop and in nothing else.
    z_bond = omega * loop_uh * 1e-6 + BOND_R_OHMS
    z_choke = omega * choke_uh * 1e-6
    z_loop = z_bond + z_choke
    total = drive_rms / source_z
    through_loop = total * z_y / (z_y + z_loop)
    # The same arithmetic at the bottom of the choke's tolerance band, which
    # is what the design has to survive: 1000 uH +/-50 % is 500 uH minimum.
    z_low = z_bond + z_choke * (1 - INLET_CHOKE_TOLERANCE)
    through_low = total * z_y / (z_y + z_low)
    # At 100 Hz the same loop is resistive: the bond is 0R plus wire, and the
    # Y-capacitor is what limits the current. The choke does not appear --
    # 1 mH is 0.63 ohm there, against 3.4 kohm of capacitor.
    hum_omega = 2 * math.pi * 100.0
    hum_z = 1.0 / (hum_omega * c_y) if c_y else math.inf
    hum_current = LOOP_EMF_V / hum_z
    # The comparison a 100 Hz tone deserves is the noise in its own critical
    # band, not the whole 20 kHz: a third octave at 100 Hz is 23.1 Hz wide.
    third_octave = 100.0 * (2 ** (1 / 6.0) - 2 ** (-1 / 6.0))
    floor = MEASURED["noise_floor"].value * math.sqrt(third_octave / BANDWIDTH)
    bond_v = through_loop * z_bond
    return {
        "c_y": c_y,
        "node_vpp": node_vpp,
        "loop_uh": loop_uh,
        "choke_uh": choke_uh,
        "barrier_ma": total * 1e3,
        "local_fraction": 1.0 - through_loop / total,
        "through_bond_ma": through_loop * 1e3,
        "bond_v": bond_v,
        # Both references the fitted answer is quoted against. The first is
        # no Y-capacitor and no choke -- every milliamp on the bond; the
        # second is C810 alone, which is where this block stood before L801.
        "bond_v_unfitted": total * z_bond,
        "bond_v_no_choke": (total * z_y / (z_y + z_bond)) * z_bond,
        "bond_v_low_l": through_low * z_bond,
        "improvement_db": 20 * math.log10(total / through_loop),
        # The residual against the mixer's own noise floor, which is the
        # comparison that decides whether another part is worth fitting.
        # Positive is above the floor.
        "floor_db": 20 * math.log10(bond_v / MEASURED["noise_floor"].value),
        "floor_db_low_l": 20 * math.log10(
            through_low * z_bond / MEASURED["noise_floor"].value),
        "hum_current_a": hum_current,
        "hum_v": hum_current * BOND_R_OHMS,
        "hum_floor_v": floor,
        "hum_margin_db": 20 * math.log10(
            floor / (hum_current * BOND_R_OHMS)),
        "noise_floor_v": MEASURED["noise_floor"].value,
        "z_y": z_y,
        "z_bond": z_bond,
        "z_choke": z_choke,
        "z_loop": z_loop,
    }


def v5_regulator():
    """The 5 V rail, and what is left on it is two parts.

    **The coils have gone to VMOD and this function's own subject went with
    them.** It used to carry three relay coils and the reference -- 93.3 mA,
    of which 92.7 was coil -- and the arithmetic below was about a package.
    mcu_supply() moved the coils onto U22's switched 5 V, because a milliamp
    of linear 5 V is a milliamp of the converter's +Vout and the module's own
    conversion had taken the budget past 250. So the rail now carries the
    MAX6126 and the MCP1700: **2.2 mA maximum, against 10 mA of the
    regulator's own quiescent current.**

    **A regulator whose idle current is four times its load is worth a
    sentence rather than a shrug**, and the sentence is that it is not what
    this rail is for. What V5 buys is that the reference the whole CV chain is
    measured against, and the LDO that makes the envelope ADC's analogue
    supply, sit behind a linear regulator rather than behind a 1.1 MHz
    switcher. The 10 mA is the price of that and it is 4 % of +Vout; moving
    these two parts to VMOD would save it and would put the board's voltage
    reference on the same node as three relay coils.

    ------------------------------------------------------------------------
    **What the package arithmetic was, kept because it is the record of a
    number that has moved.** At 93.3 mA the dissipation was

        (12 - 5) x 93.3 mA  +  12 x 10 mA  =  0.77 W

    and 0.77 W is what chose the package: a 100 mA regulator goes in a SOT-223
    without anybody thinking about it, and the NCP1117's own table gives that
    package 160 C/W to ambient at a minimum pad, which is 124 degrees of rise.
    The DPAK is 67 C/W and the same die. Both figures are the datasheet's own
    and both are at a minimum pad, which is the honest one to design to: a
    number that depends on how much copper somebody poured is a number the
    fabricator can change.

    **At 0.14 W both packages now fit** -- 22 degrees of rise in the SOT-223 --
    so the package is a free choice again and the DPAK is kept, because
    changing a footprint to save nothing is how a board acquires a revision
    for no reason. The figure is returned either way and `fits` says both.

    The other reading worth carrying: the 5.0 V line of the electrical table
    is characterised over **Vin = 6.5 to 12 V**, and this runs it at exactly
    12. The absolute maximum is 20 V and note 3 restricts only currents above
    1 A, so it is inside its rating and at the top of its characterisation --
    a distinction worth writing down rather than discovering as a tolerance.
    """
    load = supply_load()["V5"]
    current = load["max_ma"] * 1e-3
    watts = (SUPPLY_VOUT - V5_VOLTS) * current + SUPPLY_VOUT * V5_IQ_MA[1] * 1e-3
    rises = {name: watts * theta for name, theta in V5_THETA_JA.items()}
    return {
        "current_ma": load["max_ma"],
        "coil_ma": load["max_ma"] - VREF_SUPPLY_MA[1],
        "watts": watts,
        "rises": rises,
        "junction": {name: AMBIENT_C + rise for name, rise in rises.items()},
        "tj_max": V5_TJ_MAX,
        "fits": {name: AMBIENT_C + rise < V5_TJ_MAX
                 for name, rise in rises.items()},
        "package": "DPAK",
        "headroom_v": SUPPLY_VOUT - V5_VOLTS - V5_DROPOUT_V,
        "vin_characterised_to": 12.0,
        "vin_max": V5_VIN_MAX,
    }


def inlet_budget():
    """What the shared brick has to supply now, which is not what it did.

    The mixer's own SUPPLY_RANGE reads "12-18V DC centre-negative, **25mA**".
    This module adds the converter's input current, and at the bottom of the
    accepted range that is fifteen times the figure on the board it plugs in
    beside. Recorded rather than acted on: the mixer is fabricated and nothing
    here touches it, but the *brick* is a system-level part and somebody
    ordering one from that string would order the wrong thing.

    **The choke is in this budget twice and only one of them costs anything.**
    Its rated current has to clear the working current, which it does by 2.1x;
    and both of its windings carry that current, so the DC loop gains
    2 x RDC of series resistance. **F801 joins that loop and not this
    sentence's first half**: a fuse's rating is a fault threshold rather than
    a continuous limit, so it is inlet_fuse() that asks whether 1.6 A clears
    382 mA and this function only carries its resistance. That drop comes out of the converter's own
    input headroom, which is 9 V against a 12 V brick -- so the number worth
    printing is not the drop but what is left of the margin after it.
    """
    fit = supply_fit()
    watts_in = fit["watts"] / SUPPLY_EFFICIENCY
    low, high = INLET_VOLTS
    # **Three series resistances now, and they get three names.** Both choke
    # windings carry the current and so does F801, so what the quadratic
    # below needs is the loop -- and the moment the fuse joined it, `choke_r`
    # stopped being the choke's resistance while every key built from it went
    # on being called `choke_*`. That is barrier_return()'s fault verbatim, in
    # the function one block along: an expression that was right only while
    # two different quantities were the same number. The loop is `loop_r` and
    # the two parts keep their own.
    #
    # The fuse's is its *hot* resistance, 187 mohm against the choke's 414,
    # taken at a quarter of rated current where the element is at ambient and
    # the real figure is lower. Pessimistic in the direction headroom wants --
    # see inlet_fuse().
    choke_r = 2 * INLET_CHOKE_RDC
    fuse_r = INLET_FUSE_DROP_MAX_V / INLET_FUSE_A
    loop_r = choke_r + fuse_r
    # Solved rather than iterated: the converter is a constant-power load, so
    # V_in x I = W with V_in = V_brick - Vf - I x R_loop gives a quadratic in
    # I. R x I^2 - (V - Vf) x I + W = 0, and the root that matters is the
    # small one.
    module_ma = {}
    for volts in (low, high):
        head = volts - INLET_DIODE_VF
        disc = head * head - 4 * loop_r * watts_in
        current = (head - math.sqrt(disc)) / (2 * loop_r)
        module_ma[volts] = current * 1e3
    worst = max(module_ma.values())
    return {
        "watts_out": fit["watts"],
        "watts_in": watts_in,
        "module_ma": module_ma,
        "worst_ma": worst,
        "mixer_ma": 25.0,
        "total_ma": worst + 25.0,
        "mixer_range": socket.SUPPLY_RANGE,
        "fuse_a": SUPPLY_FUSE_A,
        "diode_watts": worst * 1e-3 * INLET_DIODE_VF,
        # The choke's own lines, and they are the choke's again.
        "choke_ohms": choke_r,
        "choke_drop_v": worst * 1e-3 * choke_r,
        "choke_watts": (worst * 1e-3) ** 2 * choke_r,
        "choke_rated_ma": INLET_CHOKE_IR_MA,
        "choke_margin": INLET_CHOKE_IR_MA / worst,
        # The fuse's, and what the loop is once both are in it.
        "fuse_ohms": fuse_r,
        "fuse_drop_v": worst * 1e-3 * fuse_r,
        "loop_ohms": loop_r,
        # What the converter's +Vin pin sees at the bottom of the brick range,
        # against its own 9 V minimum.
        "converter_vin_low": (low - INLET_DIODE_VF
                              - module_ma[low] * 1e-3 * loop_r),
        "converter_vin_min": SUPPLY_VIN[0],
    }


def input_filter(lead_nh=None):
    """Why there is no series inductor on the primary, stated as a number.

    A pi filter is what a converter datasheet's application note draws, and
    the reason to want one here is specific rather than compliance: the inlet
    is *shared*, so this converter's input ripple current has a conductor
    straight to the mixer's own inlet, where its LM317's rejection at half a
    megahertz is nothing to speak of.

    What the arithmetic says is that the local ceramics and the lead already
    do it. The ripple current divides between the capacitance at the module's
    own pins and the series inductance of the lead to the jack, and even at
    the shortest lead this design could plausibly be built with, the lead is
    the larger impedance by more than an order of magnitude.

    **And the thing it would arrive at is not audible.** 580 kHz on the
    mixer's rails is 580 kHz: the mixer contains no multiplier, its op-amps
    are linear, and the one part in this system whose gain is a product is on
    *this* board, behind the isolation. That is the same argument
    supply_beat() reaches from the other end, and it is why this is good
    practice rather than load-bearing -- so it is done with the parts the
    converter needs anyway, and no inductor is fitted.
    """
    lead_nh = lead_nh or MEASURED["inlet_loop_uh"].value * 1e3 / 3.0
    omega = 2 * math.pi * SUPPLY_KHZ_TYP * 1e3
    z_local = 1.0 / (omega * 2 * PRIMARY_BULK_C_FARADS)
    z_lead = omega * lead_nh * 1e-9
    share = z_local / (z_local + z_lead)
    return {
        "z_local": z_local,
        "z_lead": z_lead,
        "lead_nh": lead_nh,
        "share": share,
        "rejection_db": -20 * math.log10(share),
        "load_bearing": False,
    }

def bypass_state():
    """What the mixer sees with the module out of circuit, and it is not new.

    The claim worth checking rather than assuming: bypass links PIN{n} to
    SIN{n}, which puts the mixer's own RIN on the same node as this module's
    R{n}01 -- 10k in parallel with 10k. **That is 5 kohm, which is exactly what
    the fabricated pot presents at full rotation**, and attenuator_input_
    impedance(1.0) upstream says so. So the bypass state is not an unusual
    condition the mixer has never seen; it is the wide-open pot, load and all,
    and check_headroom() upstream already covers it.

    It is also the loudest state the instrument has, and that is the point: a
    box that fails should leave the player audible.
    """
    parallel = 1.0 / (1.0 / FRONT_R_OHMS + 1.0 / socket.RIN_OHMS)
    wide_open = socket.attenuator_input_impedance(1.0)
    return {
        "parallel": parallel,
        "pot_wide_open": wide_open,
        "matches": abs(parallel - wide_open) < 1.0,
        "gain_db": 0.0,
        "module_max_db": 0.0,
    }


# The clamp, and it is one part answering the one fail-loud path this design
# has.
#
# **fail_states() said the bypass relay covered this and it does not.** Its note
# read "the mitigation belongs with the shared fail-safe blocks, and the bypass
# relay's AC-coupled charge pump covers it at the audio level in the meantime",
# which sounds right and is not: the pump collapses when the *MCU* stops, and an
# inverted reference that fails to the positive rail leaves the MCU perfectly
# healthy, still emitting 10 kHz, holding the relay in. The one state the pump
# cannot see is the one state that is loud.
#
# What it costs to fix is a diode. VREFN sits at -2.5 V in normal operation, so
# a Schottky with its anode there and its cathode at MAGND is reverse-biased and
# does nothing; if the inverter's output heads for +12 V, it conducts at about
# 0.3 V instead. clamp_gain() computes what that is worth: +20 dB becomes
# +7.4 dB, which is inside the 7.84 dB of margin the mixer's own clipping_peak()
# has over its assumed channel peak. The failure stops clipping the summer.
#
# The margin is 0.4 dB and that is thin enough to state plainly rather than
# round off. What the clamp buys is not comfort, it is the difference between a
# fault that overloads the whole mono mix and one that sits at the edge of the
# design's own envelope.
#
# ---------------------------------------------------------------------------
# **The 0.3 V was never read, and reading it broke the clamp.** This constant
# was `CLAMP_VF = 0.3` with a BAT54 behind it, and ASSUMPTIONS.md's own entry
# said the basis was "a BAT54-class part at the microamps this circuit draws,
# and no datasheet was opened this session". Both halves of that turned out to
# be wrong in different ways, and the second is the one that matters.
#
# **It is not microamps.** D803's anode is U8's output pin -- floorplan.py puts
# it there deliberately, "what it clamps is that amplifier and a long run would
# clamp the trace instead" -- so when the loop breaks, the diode carries
# whatever the amplifier can source. The OPA1644's own figure, read first-hand
# from SBOS484D page 8, is I_SC = 36 mA sourcing. Three orders of magnitude
# above the assumption, and in the direction that costs forward drop.
#
# **And no series resistor rescues it**, which is the part worth keeping
# because it is the reason a part change is the only fix. Put R between U8 and
# VREFN and both the normal 682 uA and the fault current flow through it, so
# their ratio is fixed by the voltage ratio alone:
#
#     I_fault / I_normal = (V_sat - Vf) / VREF = 11.65 / 2.5 = 4.54x
#
# R cancels. The best case is R large enough to sit the amplifier on its own
# negative rail in normal operation -- unusable -- and even that only reaches
# 846 uA. clamp_current() has the arithmetic.
#
# So the requirement is a part: **Vf <= 0.32 V at 36 mA**, which is what
# clamp_gain() shows the mixer's 7.84 dB of headroom will take. The BAT54 is a
# 200 mA diode and its own table says 500 mV max at 30 mA -- 13.4 dB, over by
# 5.5 dB. The clamp did not work, and every instrument in this repo agreed it
# did, because all of them read CLAMP_VF.
CLAMP_DIODE = "PMEG2010AEH"

# **One constant used to name three different jobs**, and splitting it is half
# of this correction. `CLAMP_DIODE = "BAT54"` was fitted at D801/D802 (the
# pump), D8{1,2,3}3 (the coil flybacks) and D803 (the clamp) alike, so a part
# change for one of them was a part change for all three -- and the three want
# opposite things. The pump wants low leakage and does not care about drop; the
# clamp wants low drop at 36 mA and does not care about leakage; the flybacks
# care about neither. The BAT54 stays where its leakage is what is wanted.
PUMP_DIODE = "BAT54"
FLYBACK_DIODE = "BAT54"

# OPA1644, SBOS484D page 8: "Voltage output swing from rail ... (V-)+0.35" at
# RL = 2 kohm. The pessimistic row of the two, deliberately -- the other is
# 0.2 V at RL = 10 kohm, and headroom arithmetic wants the bad number.
OPAMP_SWING_HEADROOM = 0.35

# Nexperia PMEG2010AEH, 20 V 1 A "very low VF" trench Schottky in SOD123F, data
# sheet of 8 October 2024, Table 7, Tamb = 25 C, all **maxima** rather than
# typicals:
#
#     IF          10 mA    100 mA     1 A
#     VF max      220 mV   290 mV     430 mV
#
# A 1 A die run at 36 mA is the whole trick: same conduction, a thirtieth of
# the current density. Leakage is the price -- 50 uA max at VR = 5 V against
# the BAT54's 2 uA -- and it is free *here*, because D803's reverse leakage
# lands on VREFN, which is a driven node inside U8's feedback loop, so the
# amplifier absorbs it and the reference does not move. It would not be free in
# the pump, where the same leakage would discharge the hold capacitor; see
# PUMP_DIODE.
CLAMP_VF_TABLE = ((10e-3, 0.220), (100e-3, 0.290), (1.0, 0.430))

# OPA1644, SBOS484D page 8, OUTPUT section: I_SC source 36 mA. The sink figure
# is -30 mA and is not the one that matters -- the fault drives VREFN positive.
OPAMP_ISC_SOURCE = 36e-3


def _schottky_vf(current, table):
    """Forward drop at a current, log-interpolated between datasheet points.

    Between two tabulated points a Schottky's drop is close to linear in
    log(I), which is what makes interpolation legitimate here rather than a
    curve nobody read. **Points from the datasheet only** -- the function
    refuses to run off the end of the table instead of extrapolating, because
    an extrapolated Schottky drop is exactly the kind of plausible number
    section 6 of the spec exists to forbid.
    """
    if current <= table[0][0]:
        return table[0][1]
    for (i0, v0), (i1, v1) in zip(table, table[1:]):
        if current <= i1:
            return v0 + (v1 - v0) * math.log10(current / i0) / math.log10(i1 / i0)
    raise ValueError(
        f"{current * 1e3:.1f} mA is off the end of a forward-voltage table "
        f"that stops at {table[-1][0] * 1e3:.0f} mA -- read the datasheet "
        f"further rather than extrapolating")


def clamp_current(r_series=0.0):
    """What D803 carries on the fault, and why a resistor cannot reduce it.

    `r_series` is a resistor between U8's output and VREFN, which is the
    obvious fix and does not work. Both the normal reference load and the fault
    current cross it, so their ratio is set by the voltage ratio alone and R
    cancels out of it. The only thing R buys is how far the amplifier has to
    swing in normal operation, and it runs out of swing long before the fault
    current is small enough to matter.
    """
    v_sat = MODULE_RAIL - OPAMP_SWING_HEADROOM
    normal = CHANNELS * VREF / CV_ROFF_OHMS
    if r_series <= 0.0:
        return {"amps": OPAMP_ISC_SOURCE, "normal_amps": normal,
                "limited_by": "the amplifier's own short-circuit current",
                "normal_drop_v": 0.0}
    drop = normal * r_series
    return {
        "amps": min(OPAMP_ISC_SOURCE,
                    (v_sat - _schottky_vf(1e-3, CLAMP_VF_TABLE)) / r_series),
        "normal_amps": normal,
        "limited_by": f"{r_series / 1e3:.1f} k in series",
        "normal_drop_v": drop,
        "fits_swing": drop + VREF <= v_sat,
    }


def clamp_gain(r_series=0.0):
    """What the VREFN clamp turns the fail-loud path into.

    The clamped figure is now computed from the diode's own datasheet at the
    current it actually carries, rather than from a constant. That is the whole
    of this correction: the number used to be an input and is now a result.
    """
    filt = cv_filter()
    fault = clamp_current(r_series)
    vf = _schottky_vf(fault["amps"], CLAMP_VF_TABLE)
    unclamped = -(filt["gain"] / CV_ROFF_OHMS * CV_R1_OHMS) * MODULE_RAIL
    clamped = -(filt["gain"] / CV_ROFF_OHMS * CV_R1_OHMS) * vf
    headroom = 20 * math.log10(
        socket.clipping_peak() / socket.MEASURED["channel_peak"].value)
    return {
        "clamp_amps": fault["amps"],
        "clamp_vf": vf,
        "unclamped_vc": unclamped,
        "unclamped_db": max(min(control_law(unclamped), GAIN_MAX_DB),
                            GAIN_MIN_DB),
        "clamped_vc": clamped,
        "clamped_db": control_law(clamped),
        "headroom_db": headroom,
        "margin_db": headroom - control_law(clamped),
        "fits": control_law(clamped) < headroom,
    }


def clamp_vf_ceiling():
    """The largest forward drop the mixer's headroom will accept. A requirement.

    Stated as a function because it is what filters the part: any Schottky
    whose datasheet maximum at clamp_current() is under this figure will do,
    and one whose is not, will not. It is 0.32 V, which is a BAT54 at 1 mA and
    a PMEG2010AEH at rather more than the 36 mA this circuit asks of it.
    """
    filt = cv_filter()
    per_volt = control_law(-(filt["gain"] / CV_ROFF_OHMS * CV_R1_OHMS) * 1.0)
    headroom = 20 * math.log10(
        socket.clipping_peak() / socket.MEASURED["channel_peak"].value)
    return headroom / per_volt


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

# **RELAY_PINS is back, and the note below said it would be.** It was deleted
# with the coarse pad, with the observation that "the deferred bypass relay will
# face the same question, and it is worth knowing that a pin map can be pinned
# before a part is chosen, by naming the standard rather than the manufacturer".
# That is what this is: IEC 60947 contact numbering again, on a part that is
# still UNSPECIFIED.
#
# The map is the same shape and the *requirement* is the opposite one. The pad
# wanted dual-coil latching; this must be **non-latching**, single coil, because
# de-energised has to be bypass -- see BYPASS_RELAYS. So the coil is A1/A2 and
# there is no B pair, which is the whole difference between the two parts
# expressed in a dict.
# **And now the part is chosen, so the standard is not the map any more.**
# IEC 60947 numbering was the right thing to write while BYPASS_RELAY was None:
# it named a convention instead of guessing a manufacturer's pinout. What it
# was never going to be is the pin numbers on a real relay, and the G6S's are
# its own -- 1, 3, 4, 5, 8, 9, 10, 12, with three positions of the twelve left
# empty. Read off the Terminal Arrangement/Internal Connections diagram on
# page 5 of Omron's own G6S data sheet, top view, single-side stable:
#
#            12 (-)      10    9    8         coil across 1 and 12
#            [coil]       \    o    /         pole A pivots at 9
#             1 (+)        3    4    5        pole B pivots at 4
#
# **The de-energised state is the one drawn**, which is what makes this map
# check out against bypass_state(): the blade hangs from the pivot and rests on
# the *outer left* contact, so 9-10 and 4-3 are closed with no coil current.
# Those are the NC pair and they are the ones that must carry the link back to
# the mixer. If they were the other way round the module would be in circuit
# when it was dead, which is the failure this whole block exists to prevent and
# is not visible in any netlist -- it is visible only in that drawing.
#
# The coil is polarised and the diagram marks it: pin 1 is +, pin 12 is -.
# V5 goes to 1 and the sink to 12, which is also what puts the flyback diode
# the right way round.
RELAY_PINS = {"COIL+": "1", "COIL-": "12",
              "COM_A": "9", "NC_A": "10", "NO_A": "8",
              "COM_B": "4", "NC_B": "3", "NO_B": "5"}

# Which relay and which pole carries each channel. Three DPDT, two channels
# each, and the arithmetic is here rather than at the connect site so that
# gen_sch.py and verify.py cannot disagree with it.
BYPASS_RELAY_REFS = tuple(f"K80{i + 1}" for i in range(BYPASS_RELAYS))


def bypass_contact(n):
    """(ref, com, nc, no) for channel n's changeover."""
    ref = BYPASS_RELAY_REFS[(n - 1) // BYPASS_POLES_EACH]
    pole = "A" if (n - 1) % BYPASS_POLES_EACH == 0 else "B"
    return (ref, RELAY_PINS[f"COM_{pole}"], RELAY_PINS[f"NC_{pole}"],
            RELAY_PINS[f"NO_{pole}"])


# The MOSFET that sinks the coils, read off KiCad's Transistor_FET:Q_NMOS_GSD
# this session: gate 1, source 2, drain 3. Named for the same reason the diodes
# are -- a transposed 2 and 3 puts the coil in the source and the drain on
# ground, which draws as a transistor and works as a diode.
FET_PINS = {"G": 1, "S": 2, "D": 3}
FET_REF = "Q801"

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
    # The same stock symbol under its own name, which is the one case in this
    # table where nothing is being borrowed: the OPA1644 above *is* a renamed
    # TL074 because their pinouts are identical, so the envelope's own TL074 is
    # that symbol not renamed. Two lib_ids, one source, and the project library
    # carries both.
    "cv:TL074": ("cv", "Amplifier_Operational", "TL074", None),
    "Device:D": ("Device", "Device", "D", None),
    # Under the "cv" nickname, not "Device": the symbol lives in KiCad's
    # Transistor_FET library, and a lib_id of Device:Q_NMOS_GSD asks the
    # Device library for it. ERC said so in one line -- "Symbol
    # 'Q_NMOS_GSD' not found in symbol library 'Device'" -- which is the
    # cheapest fault this pass produced and the reason ERC runs on every
    # build rather than at the end.
    "cv:Q_NMOS_GSD": ("cv", "Transistor_FET", "Q_NMOS_GSD", None),
    # Non-latching this time. The generic symbol carries IEC contact numbering
    # and one coil, which is exactly what the fail-safe requires and nothing
    # part-specific -- the same argument that made the pad's symbol safe to
    # draw with, for the opposite part.
    "cv:Relay": ("cv", "Relay", "Relay_DPDT", "Relay"),
    "cv:SSI2164": ("cv", "Audio", "SSI2164", None),
    "cv:74AHC541": ("cv", "74xx", "74AHC541", None),
    "cv:MAX6126": ("cv", "Reference_Voltage", "ADR4525", "MAX6126"),
    # The converter, borrowed from its own four-watt sibling: the TMR 4WI's
    # symbol *is* the TMR 6WI's, because both are the dual-output SIP-8 whose
    # pin map page 4 of the datasheet gives -- 1 -Vin, 2 +Vin, 3 Remote, 5 NC,
    # 6 +Vout, 7 Com, 8 -Vout -- and KiCad has no symbol for the six. Nothing
    # is renumbered; only the name and the properties change, which is the
    # same borrowing OPA1644 makes of TL074 and for the same reason.
    #
    # **The footprint is not borrowed and that is the difference**, because a
    # symbol carries a pin map and a footprint carries a body. See SUPPLY_FP.
    "cv:TMR6-2422WI": ("cv", "Converter_DCDC_Isolated", "TMR4-2422WI",
                       "TMR6-2422WI"),
    # And the regulator from AP1117-50, which is the same 1117 pin map -- 1
    # Adjust/Ground, 2 Output and the tab, 3 Input -- at the same 5.0 V.
    "cv:NCP1117-5.0": ("cv", "Regulator_Linear", "AP1117-50", "NCP1117-5.0"),
    # The 3.3 V regulator, and this one is *not* borrowed: KiCad ships the
    # MCP1700 in its SOT-23 variant under its own name, so the only reason it
    # is under the cv nickname is that gen_project.py writes one library.
    "cv:MCP1700-3.3": ("cv", "Regulator_Linear", "MCP1700x-330xxTT",
                       "MCP1700-3.3"),
    # **The ADC, and it is the largest repinning in this table.** KiCad has no
    # MCP3564. What it has is the ADS131M04 -- the four-channel sibling of the
    # part this design rejected -- and that symbol is a 20-pin TSSOP whose
    # four corners already agree: 1 AVDD, 2 AGND, 19 DGND, 20 DVDD. The
    # sixteen pins between them are renamed to ENV_ADC_PINS.
    #
    # Borrowing the *loser's* symbol is worth a sentence, because it looks
    # like a mistake and is the opposite of one. A symbol carries a pin map
    # and a body, and nothing else; what separated the two candidates was full
    # scale and reference range, which live in neither. The alternative was to
    # draw a 20-pin rectangle from scratch, which is a second place for a pin
    # map to be wrong -- the same argument the relay's renumbering makes.
    "cv:MCP3564": ("cv", "Analog_ADC", "ADS131M04xPW", "MCP3564"),
    "Device:D_Schottky": ("Device", "Device", "D_Schottky", None),
    # The inlet choke. The generic four-terminal symbol and not a
    # part-specific one, and the suffix is load-bearing: _1423 puts 1 and 4 on
    # the top winding and 2 and 3 on the bottom, which is the 744222's own
    # Schematic block. _1234 would draw the same body with the windings paired
    # 1-2 and 3-4 -- the connection that puts the choke in series with the
    # supply current instead of across it, and it draws identically.
    "cv:744222": ("cv", "Filter", "Choke_CommonMode_FerriteCore_1423",
                  "744222"),
    # The controller and its periphery. Four of these are stock symbols under
    # their own names, which is the cheapest kind of entry in this table:
    # nothing is renamed, so nothing can be renamed wrongly.
    # **One symbol replaced four**, which is the same arithmetic as the parts:
    # RP2040, W25Q128JVS, USB_B_Micro and Crystal_GND24 were the chip and the
    # three things around it, and the module is one stock symbol under its own
    # name -- nothing renamed, so nothing renamed wrongly.
    #
    # It is the plain "RaspberryPi_Pico" and not "..._Debug", which is the
    # same symbol with the three underside SWD pads added. Drawing pins this
    # board cannot solder would put three nets on the sheet that no iron can
    # reach; see PICO_FP.
    "MCU_Module:RaspberryPi_Pico": ("MCU_Module", "MCU_Module",
                                    "RaspberryPi_Pico", None),
    "Isolator:TLP2761": ("Isolator", "Isolator", "TLP2761", None),
    "Device:L": ("Device", "Device", "L", None),
    "Device:Fuse": ("Device", "Device", "Fuse", None),
    # The 3.3 V switcher, borrowed from the LMR50410 -- **and the borrowing is
    # a pin map rather than a resemblance.** Both are TI SOT-23-6 buck
    # converters whose pinout is 1 CB, 2 GND, 3 FB, 4 EN, 5 VIN, 6 SW; the
    # TPS560430's section 6 gives exactly that and nothing is renumbered. The
    # same argument as the TMR 6WI's borrowing of its four-watt sibling's
    # symbol, and the same limit: a symbol carries a pin map and a body, so
    # what separated these two parts -- FPWM, and a frequency stated as a band
    # -- lives in neither and is in MCU_DCDC's comment instead.
    "cv:TPS560430XF": ("cv", "Regulator_Switching", "LMR50410",
                       "TPS560430XF"),
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


def _renumber(definition, mapping):
    """Renumber a borrowed symbol's pins, all at once.

    **All at once, and that is the whole of it.** The map from IEC contact
    numbers to the G6S's own has "12" on both sides -- it is the IEC coil's A2
    and it is the relay's NC on pole A -- so renumbering pin by pin renames one
    pin and then matches the renamed one. Collecting every pin first and
    assigning afterwards is what makes the mapping a permutation rather than a
    sequence of substitutions.
    """
    pins = []
    for unit in definition:
        if not (isinstance(unit, list) and str(unit[0]) == "symbol"):
            continue
        for pin in unit:
            if not (isinstance(pin, list) and str(pin[0]) == "pin"):
                continue
            for item in pin:
                if isinstance(item, list) and str(item[0]) == "number":
                    pins.append((str(item[1]), item))
    missing = sorted(set(mapping) - {number for number, _ in pins})
    if missing:
        raise AssertionError(
            f"the symbol has no pins {missing}, which the renumbering map "
            f"names -- the borrowed symbol has changed under this patch")
    for number, item in pins:
        if number in mapping:
            item[1] = type(item[1])(mapping[number])


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
    if lib_id.endswith(":RaspberryPi_Pico"):
        # **The module's ground pins are typed `power_out` and this board
        # needs them to be `power_in`.** MCU_Module:RaspberryPi_Pico gives GND
        # (pin 3, with six stacked on it) and AGND (pin 33) the type a *source*
        # of ground has, which is defensible for a module that brings a plane
        # out on a castellation. On this board MDGND is already driven -- by
        # the converter's Com pin, which is the thing that actually makes the
        # ground -- so ERC saw two power outputs on one net and reported it
        # twice, once per module ground pin.
        #
        # **The alternative was to declare it in verify.ERC_ALLOWED and that
        # is the wrong way round**, for the reason this whole function exists:
        # a declaration says "expected residue" and this is not residue, it is
        # a symbol modelling the part as a supply when this board uses it as a
        # load. Every other patch here corrects a pin map or a name where the
        # stock symbol is wrong about the part; this corrects a pin's
        # *direction* where the stock symbol is right about the module and
        # wrong about the role. Said plainly because the distinction is thin
        # and somebody will want to reverse it.
        #
        # 3V3 stays `power_out` and that is the one to leave alone: the module
        # really does source VMCU, it is the only driver on that net, and it
        # is why the PWR_FLAG that used to be there had to move to VSYS.
        for pin in (CONTROLLER_MODULE_GND_PINS
                    + (CONTROLLER_MODULE_PINS["AGND"],)):
            _repin(definition, pin, "power_in")
    elif lib_id.endswith(":OPA1644"):
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
    elif lib_id.endswith(":MCP3564"):
        _set_property(definition, "Datasheet", ENV_ADC_DATASHEET)
        _set_property(definition, "Description",
                      "8-channel 24-bit delta-sigma ADC, SCAN sequencer, "
                      "20-lead TSSOP")
        # Every pin between the four corners, by number, from page 3 of
        # DS20006181C. The corners are left alone because the borrowed symbol
        # already has them right -- and leaving them alone is what makes this
        # a rename rather than a redraw.
        for name, kind in (("REFIN-", "input"), ("REFIN+", "input"),
                           ("CH0", "input"), ("CH1", "input"),
                           ("CH2", "input"), ("CH3", "input"),
                           ("CH4", "input"), ("CH5", "input"),
                           ("CH6", "input"), ("CH7", "input"),
                           ("CS", "input"), ("SCK", "input"),
                           ("SDI", "input"), ("SDO", "tri_state"),
                           ("IRQ", "open_collector"), ("MCLK", "input")):
            _repin(definition, ENV_ADC_PINS[name], kind, name=name)
    elif lib_id.endswith(":MCP1700-3.3"):
        _set_property(definition, "Datasheet", V3V3_DATASHEET)
        _set_property(definition, "Description",
                      "3.3 V 250 mA LDO, 1.6 uA quiescent, SOT-23")
    elif lib_id.endswith(":USB_B_Micro"):
        # **The connector's GND is not a power source and ERC said so.** KiCad
        # draws a USB receptacle's VBUS and GND as `power_out`, which is right
        # for a board that takes its supply from the bus. This one does not:
        # it has an isolated converter, and what arrives on J14's shell is a
        # *reference* -- the host's ground, tied to MDGND so that the data
        # pair has one. Left as an output it is a second power source on a net
        # the converter's Com already drives, which ERC reported as two power
        # outputs connected, and no flag or exemption makes that statement
        # true. `passive` is what the pin is here.
        #
        # VBUS keeps its type deliberately: it *is* a source, it is the only
        # thing on this board that comes from outside the module's own supply,
        # and usb_vbus_divider() is a divider hanging off a 5 V rail nobody
        # here regulates. Saying so is worth the asymmetry.
        _set_property(definition, "Description",
                      "USB 2.0 micro-B receptacle, device end. Self-powered: "
                      "VBUS is sensed and not consumed")
        _repin(definition, 5, "passive", name="GND")
    elif lib_id.endswith(":Relay"):
        # **The generic symbol is IEC-numbered and the chosen relay is not.**
        # KiCad's Relay_DPDT carries A1/A2 and 11/12/14, 21/22/24, which was
        # exactly right while BYPASS_RELAY was None: it named the standard
        # instead of guessing a manufacturer. The G6S numbers its terminals
        # 1/12 for the coil and 9/10/8, 4/3/5 for the poles, so the symbol has
        # to be renumbered or the sheet and the footprint describe different
        # parts -- and verify.py compares pin by pin precisely so that they
        # cannot.
        #
        # Renumbering rather than substituting a G6S-specific symbol, because
        # there is not one in KiCad's libraries and drawing one would be a
        # second place for the pin map to be wrong. RELAY_PINS stays the single
        # copy; this maps the borrowed symbol onto it.
        _set_property(definition, "Description",
                      "DPDT signal relay, single-side stable, "
                      "bifurcated Au-alloy contacts")
        _renumber(definition, {
            iec: RELAY_PINS[role]
            for role, iec in (("COIL+", "A1"), ("COIL-", "A2"),
                              ("COM_A", "11"), ("NC_A", "12"), ("NO_A", "14"),
                              ("COM_B", "21"), ("NC_B", "22"), ("NO_B", "24"))})
    return definition

R_FP = "Resistor_SMD:R_0805_2012Metric"
C_FP = "Capacitor_SMD:C_0805_2012Metric"
C_FILM_FP = "Capacitor_SMD:C_1210_3225Metric"
SOIC8_FP = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
SOIC14_FP = "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm"
SOP16_FP = "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"
SOIC20_FP = "Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm"
SOD123_FP = "Diode_SMD:D_SOD-123"
# SOD123F, the PMEG2010AEH's package: 4.40 mm of courtyard against
# SOD-123's 4.70, so the low-drop clamp drops into the slot the BAT54
# was placed in and no row moves.
SOD123F_FP = "Diode_SMD:D_SOD-123F"
# The DMG1012T's package and the G6S-2F's. Both arrived with the two parts
# that were UNSPECIFIED; neither was a free choice.
SOT523_FP = "Package_TO_SOT_SMD:SOT-523"
RELAY_FP = "Relay_SMD:Relay_DPDT_Omron_G6S-2F"
SOT23_FP = "Package_TO_SOT_SMD:SOT-23"
# The inlet choke, and **KiCad's own footprint is fine as it stands**, which
# is worth stating because the opposite was expected. These four-terminal
# bodies draw their courtyard as a run of fp_line segments rather than as one
# rectangle -- WE-SL5 uses four, ACM7060 and DR331 twelve each -- and
# placement.SIZE and gen_pcb.check_courtyards() are both written around a
# rectangle. The two facts do not meet: what check_courtyards() reads is
# `GetCourtyard(F_CrtYd).BBox()`, and KiCad builds that polygon from whatever
# closed outline is on the layer, however many segments it took. All four
# candidate footprints return exactly one closed outline and a bounding box
# (WE-SL2 10.090 x 6.590, measured). So neither of the two things this could
# have needed -- a generated footprint like the TMR 6WI's, or a polygon-aware
# courtyard check -- is needed at all.
#
# **The mistake worth recording is the shape of the claim**, not the claim: a
# statement about how a drawing is *drawn* was read as a statement about what
# the API *returns*. The distinction is invisible from the .kicad_mod source,
# which is where the polylines are, and takes one call to settle.
CHOKE_FP = "Inductor_SMD:L_CommonMode_Wuerth_WE-SL2"
# The inlet fuse, and it is a stock footprint under the part's own name --
# the cheapest kind. KiCad's own descr line for it reads "Surface Mount
# Fuse, 3 x 10.1 mm, Time-Lag T, 250 VAC, 125 VDC", which is the datasheet's
# headline word for word, so the two agree without either being asked to.
FUSE_FP = "Fuse:Fuse_Schurter_UMT250"
# The ADC's own body. 20-lead TSSOP, 4.4 x 6.5 mm, which is the leaded option
# of the two the datasheet offers -- the other is a 3 x 3 mm UQFN with a
# thermal pad. Leaded on purpose and it is the same argument the DPAK made at
# v5_regulator(): this is a spike whose board a person has to be able to
# inspect and rework, and a 0.5 mm-pitch QFN under a microscope is a different
# kind of project. The part dissipates 6 mW, so the pad buys nothing here.
TSSOP20_FP = "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm"
# The supply's own three, and the first of them is this repo's first footprint.
#
# **KiCad has no TMR 6WI land pattern and the two it has that look like one are
# not it.** Converter_DCDC_TRACO_TMR4-xxxxWI_THT and ..._TMR8-xxxxWI_THT carry
# exactly the right pad pattern -- 1, 2, 3, then a 5.08 mm gap where pin 4 is
# not, then 5, 6, 7, 8 -- and different bodies: the TMR 4WI's is 9.3 mm deep
# with the pin row 2.575 from its front edge, against this part's 9.1 and 3.5.
# A millimetre in the wrong direction on a silkscreen is the sort of thing the
# word "approximate" used to cover in placement.SIZE, and that comment is there
# because it covered a set of transposed courtyards for three passes.
#
# So it is generated, from the outline drawing on page 4 of the datasheet, by
# gen_project.footprint_library() -- next to the *symbol* library that is
# already generated for exactly the same reason, and under the same nickname.
SUPPLY_FP = "cv:TRACO_TMR-6-xxxxWI_Dual_THT"
# DPAK, and see v5_regulator(): 0.77 W against the SOT-223's own 160 C/W is
# what puts it here.
DPAK_FP = "Package_TO_SOT_SMD:TO-252-2"
# The controller's own packages. The QFN is the only one RP2040 is made in --
# section 5.1, 7x7 mm, 0.40 mm pitch, 3.2 x 3.2 mm exposed pad -- and
# controller_package() is why the board is at 0.09/0.09 mm.
# **The ThermalVias variant, and it is the exposed pad that asks for it.** Pin
# 57 is a 3.2 x 3.2 mm ground pad in the middle of the package, and the way a
# QFN's ground reaches an inner plane is through vias inside that pad -- this
# variant carries four, at +/-1.35 mm, 0.5 mm pads on a 0.2 mm drill. The plain
# variant does not, and gen_pcb.stitch_grounds() cannot help: its rule is to
# put a via *beyond* a pad along the pad's own long axis, which for a pad in
# the middle of a 56-pin package is inside the pin rows on every side. It said
# so and stopped the build, which is the right failure.
# **The module, and the variant is a decision with a mechanism.** KiCad ships
# four Pico lands. The through-hole one is refused and not for cost: 40 holes
# on 2.54 mm in two rows 17.78 mm apart is a picket fence through *both* inner
# layers, and the region between the rows becomes a plane island joined only at
# its ends -- on a board whose ground strategy is two solid pours and one bond.
# The castellated land leaves all four layers continuous under the module, and
# a hand-soldered castellation is soldered from the side, which is what the
# HandSolder variant's extended pads are for.
#
# What it costs is the module's three debug pads, which are on its underside
# and unreachable by an iron. See the reset comment in controller().
PICO_FP = "Module:RaspberryPi_Pico_SMD_HandSolder"
# ~~QFN56_FP~~ -- gone with the bare RP2040, and with it the only part on this
# board that had an opinion about the fabrication class. rules.QFN_PIN_PITCH_MM
# stays, because controller_package() still computes against it and
# fabrication-class.md is re-opened rather than reversed.
# 8-pin SOIC 208-mil, the flash's package code S: D and E are 5.28 mm nominal
# in its own section 10.1, which is this land.
SOIC8_208_FP = "Package_SO:SOIC-8_5.3x5.3mm_P1.27mm"
SOT23_6_FP = "Package_TO_SOT_SMD:SOT-23-6"
SO6L_FP = "Package_SO:SO-6L_10x3.84mm_P1.27mm"
# **The generic 3225 land and not Abracon's own.** KiCad ships
# Crystal_SMD_Abracon_ABM8G-4Pin_3.2x2.5mm, and ABM8G is a different series
# from the ABM8 the vendor recommends. Its pads are identical -- 1.4 x 1.2 mm
# at +/-1.1, +/-0.85 -- so the borrow would work and would also be a claim
# about a drawing this session did not read: the ABM8 datasheet gives its land
# pattern as a figure, which pdftotext does not extract. The generic 3.2 x 2.5
# 4-pad land makes the same geometry a statement about the *package*, which is
# what a footprint is.
CRYSTAL_FP = "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm"
# 6.0 x 6.0 x 4.5 mm shielded, the SRN6045TA's own body.
INDUCTOR_FP = "Inductor_SMD:L_Bourns_SRN6045TA"
USB_MICROB_FP = "Connector_USB:USB_Micro-B_Molex-105017-0001"
SMA_FP = "Diode_SMD:D_SMA"
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
    PUMP_C:           "GRM2165C1H222JA01D",
    PUMP_HOLD_C:      "GRM21BR71C105KA01L",
    PUMP_DIODE:       "BAT54-7-F",
    CLAMP_DIODE:      "PMEG2010AEH,115",
    BYPASS_RELAY:     "G6S-2 DC5",
    BYPASS_FET:       "DMG1012T-7",
    ENV_OPAMP:        "TL074CDR",
    ENV_DIODE:        "1N4148WS-7-F",
    "10k 1%":         "RC0805FR-0710KL",
    "4k99 1%":        "RC0805FR-074K99L",
    # The controller block. The module, the opto, the switcher and the
    # inductor are order codes read off the datasheet or the vendor's own
    # ordering table -- CONTROLLER_MPN is the Pico datasheet's own Table 6 --
    # and the passives follow Yageo's and Murata's published numbering, which
    # is the same rule the rest of this table runs on.
    #
    # Four lines went with the module: the flash, the crystal, the USB
    # receptacle and the 27 ohm pair. Every one of them was a part this repo
    # chose and read a datasheet for, and every one of them is now inside
    # somebody else's order code.
    CONTROLLER:       CONTROLLER_MPN,
    MIDI_OPTO:        MIDI_OPTO_MPN,
    MCU_DCDC:         MCU_DCDC_MPN,
    MCU_DCDC_L:       MCU_DCDC_L_MPN,
    "88k7 1%":        "RC0805FR-0788K7L",
    "22k1 1%":        "RC0805FR-0722K1L",
    "33R 5%":         "RC0805JR-0733RL",
    "10R 5%":         "RC0805JR-0710RL",
    "390R 1%":        "RC0805FR-07390RL",
    "1k 1%":          "RC0805FR-071KL",
    "15p/50V C0G":    "GRM2165C1H150JA01D",
    "1u/16V X7R":     "GRM21BR71C105KA01L",
    "2u2/50V X7R":    "GRM21BR71H225KA73L",
    "22u/16V X5R":    "GRM21BR61C226ME44L",
    "470n/50V X7R":   "GRM21BR71H474KA88L",
    VCA:              "SSI2164S-RT",
    LOGIC:            "SN74AHC541DWR",
    # 8-pin SO, A grade, 2.5 V. The "+" suffix is the lead-free marker in
    # Maxim's scheme and is part of the order code, not decoration.
    VREF_PART:        "MAX6126AASA25+",
    # The supply. Note the space in Traco's own part number -- "TMR 6-2422WI"
    # is how it is printed on the datasheet, the model page and every
    # distributor, and an order code is a string to be copied rather than
    # tidied.
    SUPPLY_PART:      SUPPLY_MPN,
    # DT is the DPAK suffix and ST is the SOT-223 one. The letter is the whole
    # of v5_regulator()'s conclusion, so it is worth seeing here.
    V5_PART:          V5_MPN,
    INLET_DIODE:      "B340A-13-F",
    RAIL_FILTER_R:    "RC0805FR-074R7L",
    # Wurth print their own order code as the bare number, and it is the whole
    # part number: no package suffix, because the series is one package.
    INLET_CHOKE:      "744222",
    # E is the extended temperature grade and ST is the 20-lead TSSOP. The
    # tube part rather than MCP3564T-E/ST, which is the same die on tape.
    ENV_ADC:          ENV_ADC_MPN,
    # T here is *not* a grade: for the SOT-23 and SOT-89 packages the MCP1700
    # is only sold on tape, so the T is part of the code rather than a choice.
    V3V3_PART:        V3V3_MPN,
    "10u/50V X7R":    "GRM32ER71H106KA12L",
    # SCHURTER print the rating and the packaging in one code: 3403.0168 is
    # the 1.6 A UMT 250 and the .11 is a hundred in a bag rather than two
    # thousand on a reel. Off the Variants table on page 4 of the datasheet,
    # which is the whole reason this part is fitted -- see INLET_FUSE.
    INLET_FUSE:       INLET_FUSE_MPN,
}

# Parts and blocks this pass does not place, each with the reason. Declared so
# that "deferred" and "missed" are different states a check can distinguish --
# the same argument design.NO_CONNECT makes upstream about floating pins.
# **Refilled by the fail-safe, which is what this dict is for.** It was emptied
# when the coarse pad went, with the note that "the deferred DC-DC, ADC and
# bypass relay are all named by function and not by part". Two of those are
# here now, and both are declared by the property that filters them rather than
# by a guess at a part number -- which is section 6 obeyed rather than worked
# around.
# **Empty, and it held one entry when it should have held two.** The dict is
# keyed by a part's *value*, and an unchosen part's value is None -- so
# BYPASS_RELAY and BYPASS_FET were the same key and the relay's requirement,
# every word of it derived, was overwritten at import for the life of the
# block. Nothing noticed: every consumer asks `value not in UNSPECIFIED`, and a
# membership test is answered just as well by one entry as by two. The pin map,
# the reserved courtyards and the coil budget all came from elsewhere, so the
# only thing lost was the declaration, which is the only part a person reads.
#
# Choosing both parts settles it rather than fixing it, and the shape of the
# bug is worth keeping written down: **a dict keyed by the thing that is
# missing collapses exactly when it is carrying the most.**
UNSPECIFIED = {}

# Pins deliberately left unconnected, declared beside the circuit rather than
# buried in the checker -- the mixer's NO_CONNECT, same argument.
REF_REF = "U12"
# The GPIO pins nothing is wired to. **Flagged rather than left silent**, for
# the reason no_connects() gives in gen_sch.py: a pin the sheet has not been
# asked about is indistinguishable from a forgotten wire. They are safe open --
# RP2040 Table 615 gives every GPIO's reset state as pull-down, so a spare pin
# is held at a level by the part itself rather than floating -- and they are
# the margin controller_fit()'s GPIO row counts: 18 used of the 26 the module
# brings out.
#
# **This iterates CONTROLLER_GPIO_PINS and that is now load-bearing**, because
# that dict is the *module's* pins rather than the chip's: GPIO23, 24, 25 and
# 29 are not in it, so they are not flagged here. Flagging them would be
# claiming this board has decided to leave a pin open, and it has not -- the
# module wired them to its own SMPS, its VBUS sense, its LED and its VSYS
# divider, and nothing on this sheet can reach them.
CONTROLLER_SPARE_GPIO = tuple(
    gpio for gpio in sorted(CONTROLLER_GPIO_PINS)
    if gpio not in {row[0] for row in CONTROLLER_MAP.values()})

NO_CONNECT = tuple(
    (CONTROLLER_REF, str(CONTROLLER_GPIO_PINS[gpio]))
    for gpio in CONTROLLER_SPARE_GPIO
) + tuple(
    (REF_REF, str(REF_PINS[name])) for name in ("IC1", "IC2")
) + tuple(
    # The '541's two unused *outputs*. Its unused inputs are held at MAGND
    # below, per page 4 note 1, and an output cannot be: tying a driven output
    # to ground is a short through the driver. So the inputs get a potential and
    # the outputs get a flag, which is the only pairing that is right at both
    # ends. Found by ERC, which is the one instrument that looks at pins rather
    # than at nets and is why it is worth running on a partial sheet.
    (LOGIC_REF, str(LOGIC_Y[n])) for n in (7, 8)
) + (
    # The converter's pin 5, which its own pinout table calls NC on both the
    # single and the dual models. Flagged rather than left open, for the same
    # reason the '541's two unused outputs are: an open pin the sheet has not
    # been asked about is indistinguishable from a forgotten wire.
    (SUPPLY_REF, str(SUPPLY_PINS["NC"])),
) + (
    # ~~The micro-B's ID pin.~~ Gone with J14: the module carries the
    # receptacle and the decision about its ID pin.
    #
    # **The module's three pins this board deliberately does not drive**, and
    # each is a different kind of decision:
    #
    #   * **3V3_EN, pin 37, is not driven because the module's converter is
    #     meant to run.** It is pulled to VSYS through 100 kOhm on the module,
    #     so open *is* enabled. pico_backdrive() is where the other topology
    #     is refused, and note what it would need: this pin driven low by
    #     something on this board, not left to a pull-up whose rail comes up
    #     whenever a USB cable is plugged in;
    #   * **VBUS, pin 40, is an output and this board has no use for it.** It
    #     would be the gate drive for the P-FET of Pico datasheet Figure 17,
    #     which mcu_supply() prices and does not fit;
    #   * **ADC_VREF, pin 35, is already connected -- on the module.** Section
    #     2.1: "ADC_VREF is the ADC power supply (and reference) voltage, and
    #     is generated on Pico by filtering the 3.3 V supply." Wiring it to
    #     VMCU here would short out that filter, and the pedal is the one
    #     thing that reads against it. The same sentence offers an external
    #     reference "if better ADC performance is required" -- it is not: the
    #     pedal is calibrated at its extremes, so what matters is monotonic
    #     and bounded, and expression_input() is where that is derived.
    (CONTROLLER_REF, str(CONTROLLER_MODULE_PINS["3V3_EN"])),
    (CONTROLLER_REF, str(CONTROLLER_MODULE_PINS["VBUS"])),
    (CONTROLLER_REF, str(CONTROLLER_MODULE_PINS["ADC_VREF"])),
    # The opto's pin 2, "N.C." in its own pin assignment.
    (MIDI_OPTO_REF, str(MIDI_OPTO_PINS["NC"])),
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
# **Empty, and it is the end of a list that had six entries.** What each one
# was, and what closed it, because the pattern is the useful part:
#
#   * **"supply"** -- "the topology is decided and the part is not", which was
#     true and hid a second question nobody had noticed was open: *where* the
#     converter goes. floorplan.py had a zone P on this board and design.py had
#     J8 taking a secondary from somewhere else, and a block being deferred is
#     what let both survive -- a deferred block is not drawn, so nothing forces
#     its two descriptions to agree. See supply();
#   * **"envelope ADC"** -- "ADS131M08 or MCP3564, undecided in spec section
#     4.4". Settled by neither channel count nor price: the ADS131M08's
#     external reference input tops out at 1.3 V, so its full scale at unity
#     gain is 1.20 V against socket.clipping_peak()'s 1.233. Deferral had
#     hidden four disagreements about a block nobody had drawn -- which domain
#     it is in, whether this board has a 3.3 V rail, how many signals cross,
#     and whether "only SPI" was four things or six;
#   * **"envelope rectifier"** -- "the smoothing time constant is not derivable
#     -- spec section 4.4 gives a sampling rate and no attack/release target",
#     which was true of an asymmetric detector and false of the symmetric one
#     this instrument wants. envelope_filter() bounds tau above by the picked
#     transient and below by ripple, and there is no release bound at all;
#   * **"bypass relay and fail-safe"** -- drawn, with the part left in
#     UNSPECIFIED until a number chose it;
#   * **"relay drive"** -- 2 x TPIC6B595 and a 74LVC1G123 one-shot, section
#     4.5. **Deleted rather than drawn**, with the coarse pad they existed to
#     drive: section 4.5 calls the one-shot's absence "the highest-probability
#     field failure in the design", which was true and is now a failure this
#     board cannot have;
#   * **"controller"** -- and its reason changed kind twice. It read "shared
#     block, and the scope statement puts shared blocks after one channel is
#     complete", which was a scope statement rather than a finding -- true of
#     every shared block and by then the only one it was still true of.
#     Deriving what the block asks for turned it into two computed gates, and
#     both are now closed: controller_package() by the fabrication class moving
#     to 0.09/0.09 on 1 oz, controller_supply() by MCU_DCDC. See controller().
#
# **The general lesson is zone P's and it is worth keeping at the top of an
# empty dict.** A deferred block suspends every instrument at once: nothing is
# drawn, so nothing can be checked for where it lives, what it draws or what it
# contradicts. Three of the six hid a disagreement that only surfaced when
# somebody drew the thing. That is an argument for drawing blocks early and
# badly rather than late and well.
DEFERRED = {}


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
        self.check_rails_are_drawn()
        self.check_pin_numbers()
        self.check_orderable()
        self.check_controller_functions()

    def check_rails_are_drawn(self):
        """Every rail RAILS declares is a net some part is on.

        **The instrument V3V3 needed and nothing had.** RAILS has carried
        "V3V3": 3.3 since the first pass and no net of that name existed
        anywhere, while docs/supply-decision.md's own correction index said
        flatly that this board has no 3.3 V rail. Two artefacts, one saying a
        rail exists and one saying it does not, both consumed -- NET_DC reads
        RAILS, supply_requirement() named its three rails by hand -- and
        nothing could tell them apart, because **a rail with no net is
        invisible to every check that walks nets**, which is all of them.

        That is zone P one artefact along. A deferred block is not drawn, so
        the things it would have made real stay declarations, and a
        declaration nothing is obliged to use cannot be wrong. The general
        form: a table that is read by consumers is not thereby checked by
        them, because a consumer that finds nothing to do is a consumer that
        passes.

        The other direction is deliberately not checked. A net that carries a
        rail and is missing from RAILS is caught by check_net_potentials(),
        which refuses any net with no NET_DC entry, and NET_DC is built from
        RAILS -- so the two halves are already covered by different means.
        """
        undrawn = sorted(name for name in RAILS if name not in self.nets)
        if undrawn:
            raise AssertionError(
                f"RAILS declares {', '.join(undrawn)} and no part is on "
                f"{'them' if len(undrawn) > 1 else 'it'} -- either draw the "
                f"rail or stop declaring it. A rail that exists only in RAILS "
                f"is a claim no check can reach")

    def check_controller_functions(self):
        """Every net on a GPIO asks that pin for a function the part has.

        **The failure this exists for is that every pin looks the same.** A
        schematic that puts SCLK on GPIO14 is exactly as legible as one that
        puts it on GPIO18, and only one of them is a pin SPI0's clock can come
        out of. Nothing downstream can tell: ERC sees two bidirectional pins,
        DRC sees copper, and verify.py's netlist comparison proves the board
        matches design.py -- which is the same relationship DIODE_PINS records
        being wrong about D801 for the whole life of that design.

        So the datasheet's own multiplexer table is transcribed
        (CONTROLLER_GPIO_FUNCTIONS, Table 2) and the assignment
        (CONTROLLER_MAP) is checked against it. Three things it catches:

          * a function on a pin that does not offer it -- the plain mistake;
          * two nets on one GPIO, which the netlist would otherwise merge into
            one net without complaint;
          * an assignment that names a *net* nothing is wired to, which is how
            a rename half-lands.

        "SIO" and the four ADC names are checked differently and deliberately:
        SIO is on every pin (Table 3, "SIO ... must be selected for the
        processors to drive a GPIO"), so what is checked is that the pin
        exists; ADC0-3 are pin identities rather than mux functions, so they
        are checked against CONTROLLER_ADC_GPIO.
        """
        seen = {}
        for net, (gpio, function) in sorted(CONTROLLER_MAP.items()):
            if gpio not in CONTROLLER_GPIO_PINS:
                raise AssertionError(
                    f"{net} is assigned to GPIO{gpio}, which this part does "
                    f"not have -- CONTROLLER_GPIO_PINS is Table 615")
            if gpio in seen:
                raise AssertionError(
                    f"GPIO{gpio} carries both {seen[gpio]} and {net} -- two "
                    f"nets on one pin is one net")
            seen[gpio] = net
            if function == "SIO":
                pass
            elif function in CONTROLLER_ADC_GPIO.values():
                if CONTROLLER_ADC_GPIO.get(gpio) != function:
                    raise AssertionError(
                        f"{net} asks GPIO{gpio} for {function}, and the "
                        f"analogue inputs are {CONTROLLER_ADC_GPIO}")
            elif function not in CONTROLLER_GPIO_FUNCTIONS[gpio]:
                raise AssertionError(
                    f"{net} asks GPIO{gpio} for '{function}', which Table 2 "
                    f"does not give it: "
                    f"{[f for f in CONTROLLER_GPIO_FUNCTIONS[gpio] if f]}")
            pin = str(CONTROLLER_GPIO_PINS[gpio])
            if self.pin_owner().get((CONTROLLER_REF, pin)) != net:
                raise AssertionError(
                    f"CONTROLLER_MAP puts {net} on GPIO{gpio} (pin {pin}) and "
                    f"the netlist has "
                    f"{self.pin_owner().get((CONTROLLER_REF, pin))} there")
        # The six carriers have to be on six different slices, because a slice
        # is one counter and spec section 4.2 asks for the phases to differ.
        if not controller_slices()["distinct"]:
            raise AssertionError(
                f"the six PWM carriers share slices "
                f"{controller_slices()['slices']} -- two channels on one slice "
                f"cannot be phase-staggered against each other")

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

# The envelope detector's summing stage, in the six sections U2/U4/U6 C and D
# that were reserved for "the envelope rectifier" and left empty for two passes.
# **They are the half of the rectifier that belongs on this part**, and the
# split is derived rather than tidy -- see ENV_OPAMP. A2's offset is the
# detector's floor, so it wants the low-offset part; A1 slews across two diode
# drops at every zero crossing, so it wants to be somewhere else.
#
# It does relax the rule at the top of this table, and the relaxation is worth
# naming: U2 carries two front ends, so two channels' envelope summing stages
# now share a die with them. The rule was written about the CV filter's 30.5 kHz
# square wave, and what lands here instead is a stage whose own output is
# already low-passed at 33.9 Hz by ENV_R x ENV_C. Its *input* carries the
# half-wave edges, which is the term to watch if the front end ever measures
# dirtier than it computes.
for _n in range(1, CHANNELS + 1):
    SECTIONS[("env_b", _n)] = (f"U{2 + 2 * ((_n - 1) // 2)}",
                               "CD"[(_n - 1) % 2])

# The envelope detector's half-wave stage, on its own packages. Six sections
# into two quads leaves two over, and they are terminated the same way U8's is.
for _n in range(1, CHANNELS + 1):
    SECTIONS[("env_a", _n)] = (ENV_PACKAGES_REFS[(_n - 1) // OPAMP_SECTIONS],
                               "ABCD"[(_n - 1) % OPAMP_SECTIONS])

# The genuinely spare sections, and they need terminating rather than leaving.
# An unused JFET section with floating inputs is not neutral: it sits against a
# rail, draws more than its share of the supply and couples back through the die
# it shares. Wired as unity followers with their inputs at MAGND, which is the
# standard answer and costs no parts.
#
# There is one on the precision side -- U8 D, the remainder after 31 -- and two
# on the cheap side, because six half-wave stages do not fill two quads.
SECTIONS[("spare", 0)] = ("U8", "D")
for _index, (_ref, _unit) in enumerate(
        [(ENV_PACKAGES_REFS[-1], "ABCD"[u])
         for u in range(ENV_SECTIONS_NEEDED % OPAMP_SECTIONS
                        or OPAMP_SECTIONS, OPAMP_SECTIONS)], start=1):
    SECTIONS[("spare", _index)] = (_ref, _unit)

OPAMP_PACKAGES = sorted(
    {pkg for pkg, _ in SECTIONS.values()} - set(ENV_PACKAGES_REFS),
    key=lambda r: int(r[1:]))
SPARE_SECTIONS = sorted(key for key in SECTIONS if key[0] == "spare")


def package_part(ref):
    """(lib_id, value) for an op-amp package. Two parts on this board now."""
    if ref in ENV_PACKAGES_REFS:
        return "cv:TL074", ENV_OPAMP
    return "cv:OPA1644", OPAMP


# Every net, and what DC it sits at. Single numbers where a net has one,
# (low, high) where it swings -- the mixer's convention, and net_dc() below
# reads either.
#
# The audio nets are 0 V by construction and that is the whole of constraint 3
# stated as data: SIN{n} appears here as 0.0 and check_sin_dc() in verify.py is
# what holds it.
# **Two 3.3 V rails, and they are deliberately not one net.** V3V3 is the
# MCP1700's, on V5, and it exists because the envelope ADC's AVDD is the supply
# pin of a 24-bit converter -- envelope_adc_reference() is what it is protecting.
# VMCU is the TPS560430XF's, on VA_RAW, and it is a switching rail feeding a
# processor. Joining them would put 1.1 MHz on the ADC's own supply to save one
# regulator that costs 4 uA and one line of BOM, which is the trade
# supply-decision.md's whole argument is against.
#
# The two meet nowhere: every signal that crosses between them is logic, and
# both parts' VOL/VOH are specified against their own rails. VCORE is the
# RP2040's own 1.1 V, made inside the part and brought out at VREG_VOUT so that
# its DVDD pins can be fed off-chip -- section 2.9.2, "The connection between
# the output pin of the on-chip regulator (VREG_VOUT) and the DVDD supply pins
# is made off-chip".
# **VCORE is gone and that is check_rails_are_drawn()'s job done twice.** The
# RP2040's 1.1 V core rail was a real net while the part was a bare QFN: made
# on the die and brought back out to the DVDD pins off-chip. Inside a module it
# is made and consumed behind the castellations, so there is no net -- and a
# rail declared here with no net is exactly the four-pass fault that check was
# written for. It fires the moment the part changes and nothing else would.
#
# **VMOD is new and it is one node, not one rail's worth of parts.** It is
# U22's output, and everything that used to hang on it now hangs on VMCU --
# which the *module* makes. So the 3.3 V of this board comes out of a pin on a
# part rather than out of a regulator this design drew, and RAILS says so with
# VMCU's source.
RAILS = {"VA+": MODULE_RAIL, "VA-": -MODULE_RAIL, "V5": 5.0, "V3V3": 3.3,
         "VMOD": 5.0, "VMCU": 3.3}
NET_DC = {
    "MAGND": 0.0, "MDGND": 0.0, socket.AGND: 0.0,
    "VREF": VREF, "VREFN": -VREF,
    "OE": (0.0, 3.3),
    **RAILS,
}
for _n in range(1, CHANNELS + 1):
    NET_DC.update({
        f"PIN{_n}": 0.0, f"SIN{_n}": 0.0, f"IVOUT{_n}": 0.0,
        f"FEN{_n}": 0.0, f"BUF{_n}": 0.0,
        f"CPL{_n}": 0.0, f"IIN{_n}": 0.0, f"RCJ{_n}": 0.0,
        f"IOUT{_n}": 0.0, f"SVN{_n}": 0.0, f"SRV{_n}": (-MODULE_RAIL,
                                                        MODULE_RAIL),
        f"CVX{_n}": (0.0, VREF), f"CVN{_n}": 0.0,
        # The envelope detector. HWN and ENVN are virtual earths; AOUT is an
        # amplifier output and swings both ways; HW is negative-going only,
        # because it is the half-wave stage's output and D{n}52 only conducts
        # one way; and ENV is |x|, so it is positive by construction. That last
        # one is a claim worth declaring rather than assuming, because the ADC
        # that reads it is single-supply.
        f"HWN{_n}": 0.0, f"HW{_n}": (-MODULE_RAIL, 0.0),
        f"AOUT{_n}": (-MODULE_RAIL, MODULE_RAIL),
        f"ENVN{_n}": 0.0, f"ENV{_n}": (0.0, MODULE_RAIL),
        f"VC{_n}": (0.0, VREF), f"LOGO{_n}": (0.0, VREF),
        f"PWM{_n}": (0.0, 3.3),
    })
    # PS{n}A-D and PSEL{n}X/Y were here: the pad's four resistor tails and the
    # two selector nodes between its relays. Six nets a channel, thirty-six in
    # all, gone with it.

# The supply's primary side, and **these five are the only nets on this board
# whose potentials are not referenced to module ground.** They are referenced
# to IGND, which is the inlet's own 0 V and, through the shared barrel jack,
# the mixer's own PGND -- a node this module touches nowhere else and must
# not. That is what the isolation barrier is, stated as data: a net's DC value
# is only meaningful against a reference, and here there are two references.
# verify.check_isolation() is what holds the two apart on the netlist, and
# gen_pcb's own keep-out holds them apart in copper.
#
# The ranges are the accepted brick at its extremes: 12 V at the bottom, and
# 20 V for an 18 V brick measured unloaded, which is the mixer's own note.
NET_DC["IGND"] = 0.0
NET_DC["VIN"] = (0.0, INLET_UNLOADED_MAX)
NET_DC["VIN_P"] = (0.0, INLET_UNLOADED_MAX - INLET_DIODE_VF)
# The jack side of the choke. Two more nets rather than a longer VIN, because
# L801 is a *part* between them and a net that spans a winding is a net that
# says the winding is not there. Same potentials as their partners -- the
# choke's differential drop is 160 mV -- and the names carry the J because
# what distinguishes them is which side of the choke they are on.
NET_DC["VIN_J"] = (0.0, INLET_UNLOADED_MAX)
# Between the fuse and the choke. A third net on one conductor for the
# reason there is a second: F801 is a part, and a net that spans a fuse
# is a net that says the fuse is not there.
NET_DC["VIN_F"] = (0.0, INLET_UNLOADED_MAX)
NET_DC["IGND_J"] = 0.0
# The converter's own output pins, ahead of the rail filter and of the 5 V
# regulator. Named RAW because that is what they are: 75 mVp-p of 580 kHz on
# them is a datasheet maximum, and VA+/VA- are what is left after rail_filter().
NET_DC["VA_RAW"] = MODULE_RAIL
NET_DC["VN_RAW"] = -MODULE_RAIL

# ---- the controller block -------------------------------------------------
#
# The 3.3 V switcher's three private nets. MSW is a square wave between the
# rails it switches, so its declared range is the whole of VA_RAW; MCB sits a
# bootstrap diode above MSW, which is why its top is higher than any other net
# on the secondary side; MFB is a feedback node held at the part's own
# reference by the loop, exactly as RINV is held at MAGND.
NET_DC["MSW"] = (0.0, MODULE_RAIL)
NET_DC["MCB"] = (0.0, MODULE_RAIL + 5.5)
NET_DC["MFB"] = MCU_DCDC_VREF
# **VSYS, and its declared range is the reason D806 is fitted.** It is VMOD
# minus a Schottky when this board is powering the module, and it is VBUS minus
# the module's own D1 when a USB cable is in -- which is *higher*. So the
# ceiling here is not 3.3 V and saying it is 3.3 V would be declaring away the
# one condition the diode exists for. The floor is zero because the module may
# be running on USB with this board unpowered.
NET_DC["VSYS"] = (0.0, USB_VBUS_VOLTS[1])
# The reset link. Pulled to the module's own 3.3 V by ~50 kOhm on the RP2040
# die and shorted to ground by the jumper, so its range is the module's rail
# and not this board's -- which is the same 3.3 V and reaches it by a
# different route, and that is exactly the sort of thing worth writing once.
NET_DC["RUN"] = (0.0, 3.3)
# ~~The crystal, the QSPI bus, USB and the MCU's non-GPIO pins.~~ **Fourteen
# nets, all gone with the module** -- XIN/XOUT/XTAL, six QSPI, four USB, VBUS
# and VBUSD, RUN, BOOT, SWCLK and SWDIO. Every one of them was copper between
# the RP2040 and a part the Pico already carries, and the module's own
# datasheet is the authority for each: section 1, "flash (Winbond W25Q16JV),
# crystal (Abracon ABM8-272-T3), power supplies and decoupling, and USB
# connector". The crystal is the same ABM8-272-T3 this repo derived
# independently from RP2040 section 2.3, which is a pleasant thing to find and
# not evidence of anything.
# The panel: the footswitch's jack node and the pedal's three.
NET_DC["TAPJ"] = (0.0, 3.3)
NET_DC["TAP"] = (0.0, 3.3)
NET_DC["EXPRV"] = (0.0, 3.3)
NET_DC["EXPRW"] = (0.0, 3.3)
NET_DC["EXPR"] = (0.0, 3.3)
# The two UART nets, on this side of the barrier: MIDI_RX is the opto's own
# totem-pole output and MIDI_TX is a GPIO.
NET_DC["MIDI_RX"] = (0.0, 3.3)
NET_DC["MIDI_TX"] = (0.0, 3.3)
# MIDI out: the supply leg and the driven leg of CA-033's own transmitter.
NET_DC["MOUTV"] = (0.0, 3.3)
NET_DC["MOUTD"] = (0.0, 3.3)
# **MIDI in, and these three are the second isolation barrier on this board.**
# Like the converter's primary side, they are referenced to somebody else's
# ground -- the transmitting device's -- and this module touches that node
# nowhere else. CA-033 is explicit that it must stay that way: "Pin 2 of the
# MIDI In connector shall not have any DC path to the receiver's ground", and
# the shield's own capacitor is what keeps the RF connection without making a
# DC one. The potentials below are the loop's, against the sender's ground:
# 5 V is the older transmitter's rail, which is the larger of the two CA-033
# allows.
NET_DC["MINJ"] = (0.0, 5.0)
NET_DC["MINA"] = (0.0, 5.0)
NET_DC["MINK"] = (0.0, 5.0)
NET_DC["MINSH"] = (0.0, 5.0)

# The reference inverter's virtual earth, held at MAGND by feedback.
NET_DC["RINV"] = 0.0
# The fail-safe. FSDRV is the MCU's 10 kHz; FSAC is the pump's own node, which
# is the one net on this board that sits *below* ground -- the clamp diode
# holds it at -Vf on the negative half of every cycle, which is how a two-diode
# pump works and is worth declaring rather than discovering at a polarised
# part. FSG is the gate and FSD is the coils' low side, pulled to MDGND by the
# FET when the pump is up.
NET_DC["FSDRV"] = (0.0, 3.3)
NET_DC["FSAC"] = (-PUMP_DIODE_VF, PUMP_GPIO_V)
NET_DC["FSG"] = (0.0, PUMP_GPIO_V)
NET_DC["FSD"] = (0.0, BYPASS_COIL_V)
# Each spare section's own output, shorted to its own inverting input. 0 V
# because its non-inverting input is at MAGND and it is a follower. One per
# spare, because two sections sharing a net would be two followers with their
# outputs tied together -- which is a fault, not a termination.
for _index, _key in enumerate(sorted(k for k in SECTIONS if k[0] == "spare")):
    NET_DC[f"SPARE{_key[1]}"] = 0.0
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

# The envelope ADC. ENVA{n} is ENV{n} through the divider, so it is positive
# by the same construction and bounded by envelope_adc_input()["at_swing"]
# rather than by a rail -- which is the whole point of the divider and is
# worth declaring as a *number* rather than as MODULE_RAIL, because that is
# the claim the part's absolute input rating rests on.
for _n in range(1, CHANNELS + 1):
    NET_DC[f"ENVA{_n}"] = (0.0, round(
        (MODULE_RAIL - OPAMP_SWING_HEADROOM)
        * ENV_ADC_R_BOT_OHMS / (ENV_ADC_R_TOP_OHMS + ENV_ADC_R_BOT_OHMS), 3))
# The SPI, and MCLK with it. All six are V3V3 logic, and all six cross the
# analogue/digital boundary -- see floorplan.CROSSINGS, where the direction
# claim had to be corrected to a level claim to accommodate SDO and IRQ.
for _name in ("SCLK", "MOSI", "MISO", "CS", "MCLK", "IRQ"):
    NET_DC[_name] = (0.0, RAILS["V3V3"])


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
# What the bond is, electrically, as opposed to what it means. R901 is a 0R
# 0805 -- about 20 mohm of its own -- and the conductor to the mixer's TP6 is a
# wire of the order of 150 mm. At 100 Hz that whole path is its resistance and
# nothing else, which is the fact that makes barrier_return()'s low-frequency
# half come out small; at half a megahertz it is the inductance, and that is
# the half that has to be defended.
BOND_R_OHMS = 0.04

# The electromotive force the inlet loop is assumed to enclose, and it is
# supply-decision.md's own worst case reused rather than re-derived: "a
# 200 x 20 mm loop 50 mm from 1 A of switched current picks up ~160 mV". That
# figure was the argument for *rejecting* a mains transformer inside the
# enclosure, so with the transformer gone there is no 1 A at 50 Hz in the box
# and the real number is far below it. It is used at its rejected-case value
# on purpose: a Y-capacitor sized against the worst loop anybody costed is one
# that cannot be wrong in the direction that hums.
LOOP_EMF_V = 0.160

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

    # The bypass changeover, and it is the first thing in the channel rather
    # than the last because that is where it sits electrically: SIN{n} is the
    # mixer's wiper, and what it is connected to is either this module or a
    # link straight back to PIN{n}. De-energised is the link -- see
    # fail_safe(), and bypass_state() for why that link reproduces the
    # fabricated pot at full rotation exactly, 5 kohm load included.
    relay, com, nc, no = bypass_contact(n)
    design.connect(f"SIN{n}", (relay, com))
    design.connect(f"PIN{n}", (relay, nc))
    design.connect(f"IVOUT{n}", (relay, no))

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

    # I-V, holding IOUT at virtual earth.
    #
    # **Its output was SIN{n} and is now IVOUT{n}**, because the bypass relay
    # sits between the two: SIN{n} is what the mixer's wiper sees, and in
    # bypass that is PIN{n} rather than this amplifier. The servo follows it --
    # sensing downstream of a contact would open the loop the moment the
    # module left circuit, and an integrator with an open loop goes to a rail
    # and stays there, so the module would come back *wrong* rather than
    # coming back. See fail_safe().
    package, unit = SECTIONS[("iv", n)]
    out, inverting, non_inverting = OPAMP_UNITS[unit]
    _resistor(design, f"R{n}21", VCA_ROUT, f"IOUT{n}", f"IVOUT{n}",
              description=f"Channel {n} I-V -- unity, R_OUT = R_IN")
    _capacitor(design, f"C{n}21", IV_CF, f"IOUT{n}", f"IVOUT{n}",
               description=f"Channel {n} I-V compensation")
    design.connect(f"IVOUT{n}", (package, out))
    design.connect(f"IOUT{n}", (package, inverting))
    design.connect("MAGND", (package, non_inverting))

    # The DC servo, sensing IVOUT{n} and injecting into IOUT{n}.
    package, unit = SECTIONS[("servo", n)]
    out, inverting, non_inverting = OPAMP_UNITS[unit]
    _resistor(design, f"R{n}31", SERVO_R, f"IVOUT{n}", f"SVN{n}",
              description=f"Channel {n} servo sense -- upstream of the bypass "
                          f"contact, so the loop stays closed in bypass")
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


def fail_safe(design):
    """The bypass relays, the charge pump that holds them in, and the clamp.

    Spec section 4.5's shape, with three things it does not say and one it says
    that is wrong. All four are derived above: BYPASS_RELAYS on why bypass is
    six changeovers and why the relay cannot latch, pump_timing() on why the
    hold capacitor is what sets the power-up interlock, coil_budget() on what
    holding it in costs, and CLAMP_DIODE on the fail-loud path the pump cannot
    see.

    The state table, which is the whole block in four lines:

        MCU emitting 10 kHz     pump up    FET on    coils energised    module
        MCU stopped, any way    pump down  FET off   coils released     bypass
        module unpowered        -          -         -                  bypass
        power-up, first 25 ms   charging   off       released           bypass

    The last two rows are why this is a relay and not an analogue switch. A
    CMOS switch needs its own supply to be in a defined state, so "the module
    lost its rails" would leave the audio path undefined; a relay's rest
    position is mechanical and survives everything.
    """
    # The pump. C805 couples the drive, D801 clamps the node's negative half to
    # its own forward drop, D802 charges C806 on the positive half, and R803
    # is what discharges it when the drive stops -- so R803 is the fail-safe's
    # actual time constant and is not a pull-down somebody can "tidy".
    _capacitor(design, "C805", PUMP_C, "FSDRV", "FSAC",
               description="Fail-safe pump: the AC coupling that makes a "
                           "stuck level -- high, low or hi-Z -- indistinguish"
                           "able from a dead MCU")
    design.add(Part("D801", PUMP_DIODE, SOD123_FP,
                    description="Fail-safe pump clamp: anode MDGND, cathode "
                                "FSAC"))
    design.connect("MDGND", ("D801", DIODE_PINS["A"]))
    design.connect("FSAC", ("D801", DIODE_PINS["K"]))
    design.add(Part("D802", PUMP_DIODE, SOD123_FP,
                    description="Fail-safe pump rectifier: anode FSAC, cathode "
                                "FSG"))
    design.connect("FSAC", ("D802", DIODE_PINS["A"]))
    design.connect("FSG", ("D802", DIODE_PINS["K"]))
    _capacitor(design, "C806", PUMP_HOLD_C, "FSG", "MDGND",
               description="Fail-safe hold: starts at zero volts, which is "
                           "what makes the power-up interlock a property of "
                           "the board rather than of firmware")
    _resistor(design, "R803", PUMP_BLEED_R, "FSG", "MDGND",
              description="Fail-safe bleed -- sets t_off, see pump_timing()")

    design.add(Part(FET_REF, BYPASS_FET, SOT523_FP,
                    description="Fail-safe sink: gate on the pump, drain on "
                                "the coils, source on MDGND"))
    design.connect("FSG", (FET_REF, FET_PINS["G"]))
    design.connect("FSD", (FET_REF, FET_PINS["D"]))
    design.connect("MDGND", (FET_REF, FET_PINS["S"]))

    # The relays. Coils in parallel on the one sink, each with its own flyback
    # diode -- the coil is the only inductor on this board and the FET is the
    # only thing that switches it off.
    for index, ref in enumerate(BYPASS_RELAY_REFS, start=1):
        design.add(Part(ref, BYPASS_RELAY, RELAY_FP, units=1,
                        description=f"Bypass relay {index} of {BYPASS_RELAYS}: "
                                    f"non-latching DPDT, de-energised is "
                                    f"bypass; contacts carry channel audio"))
        # **VMOD and not V5, and the coil is unchanged.** Same relay, same
        # 5 V, same current -- what moved is which 5 V rail it comes from.
        # V5 is the NCP1117's, made linearly from twelve volts, so 93 mA of
        # coil there is 93 mA of the converter's +Vout; VMOD is U22's, and
        # the same coil costs 42. See mcu_supply() for what forced it and
        # v5_regulator() for what is left on the linear rail.
        design.connect("VMOD", (ref, RELAY_PINS["COIL+"]))
        design.connect("FSD", (ref, RELAY_PINS["COIL-"]))
        diode = f"D{80 + index}3"
        design.add(Part(diode, FLYBACK_DIODE, SOD123_FP,
                        description=f"{ref} coil flyback: anode FSD, cathode "
                                    f"VMOD"))
        design.connect("FSD", (diode, DIODE_PINS["A"]))
        design.connect("VMOD", (diode, DIODE_PINS["K"]))

    # The clamp on the inverted reference, which is the fail-loud path the pump
    # cannot see. Reverse-biased at -2.5 V in normal operation and doing
    # nothing; conducting at +0.3 V if the inverter's output heads for the
    # rail. See clamp_gain(): +20 dB becomes +7.4 dB, which the mixer's own
    # headroom covers and +20 dB does not.
    design.add(Part("D803", CLAMP_DIODE, SOD123F_FP,
                    description="Reference inverter clamp: anode VREFN, "
                                "cathode MAGND. Reverse-biased in normal "
                                "operation"))
    design.connect("VREFN", ("D803", DIODE_PINS["A"]))
    design.connect("MAGND", ("D803", DIODE_PINS["K"]))


def envelope(design, n):
    """One channel's precision full-wave rectifier and its one-pole.

    Spec section 4.4's "six precision rectifiers -> RC", with the topology and
    the time constant derived at envelope_filter() rather than chosen. Hung off
    BUF{n}, which is the front end's output and therefore *pre-gain* -- section
    4.4 is explicit that post-gain detection "makes it a feedback loop that
    latches shut", and the tap is free here because BUF{n} is a driven low
    impedance. Section 4.1's 1 Mohm series tap belongs to the follower topology
    that front_end() replaced, and verify.check_pin_load() now refuses it.

    Stage A is the half-wave inverting stage with both diodes inside its loop.
    Stage B sums BUF{n} with twice A's output and low-passes the result. The
    output is |BUF{n}|, positive, into a deferred ADC.

    **The diodes are the one part on this board where the drawing can be right
    and the circuit backwards**, which is why they are connected by role and
    not by number. D{n}51 conducts when A1's output goes positive -- input
    negative -- and holds the loop closed; D{n}52 passes the other polarity out
    to HW{n}. Swap them and the rectifier still draws, still passes ERC, and
    reports nothing.
    """
    package, unit = SECTIONS[("env_a", n)]
    out, inverting, non_inverting = OPAMP_UNITS[unit]

    _resistor(design, f"R{n}51", ENV_R, f"BUF{n}", f"HWN{n}",
              description=f"Channel {n} half-wave input")
    _resistor(design, f"R{n}52", ENV_R, f"HWN{n}", f"HW{n}",
              description=f"Channel {n} half-wave feedback")
    design.add(Part(f"D{n}51", ENV_DIODE, SOD123_FP,
                    description=f"Channel {n} half-wave clamp -- anode to "
                                f"A1's output, cathode to its summing node"))
    design.connect(f"AOUT{n}", (f"D{n}51", DIODE_PINS["A"]))
    design.connect(f"HWN{n}", (f"D{n}51", DIODE_PINS["K"]))
    design.add(Part(f"D{n}52", ENV_DIODE, SOD123_FP,
                    description=f"Channel {n} half-wave output -- anode to "
                                f"HW{n}, cathode to A1's output"))
    design.connect(f"HW{n}", (f"D{n}52", DIODE_PINS["A"]))
    design.connect(f"AOUT{n}", (f"D{n}52", DIODE_PINS["K"]))
    design.connect(f"AOUT{n}", (package, out))
    design.connect(f"HWN{n}", (package, inverting))
    design.connect("MAGND", (package, non_inverting))

    # The summing stage: BUF{n} at unity, HW{n} at twice, and the feedback pair
    # that makes it the one-pole envelope_filter() derives.
    package, unit = SECTIONS[("env_b", n)]
    out, inverting, non_inverting = OPAMP_UNITS[unit]
    _resistor(design, f"R{n}53", ENV_R, f"BUF{n}", f"ENVN{n}",
              description=f"Channel {n} envelope sum -- the input at unity")
    _resistor(design, f"R{n}54", ENV_R_HALF, f"HW{n}", f"ENVN{n}",
              description=f"Channel {n} envelope sum -- the half-wave at 2x")
    _resistor(design, f"R{n}55", ENV_R, f"ENVN{n}", f"ENV{n}",
              description=f"Channel {n} envelope feedback -- with C{n}51, tau")
    _capacitor(design, f"C{n}51", ENV_C, f"ENVN{n}", f"ENV{n}",
               description=f"Channel {n} envelope one-pole -- "
                           f"{ENV_R_OHMS * ENV_C_FARADS * 1e3:.1f} ms")
    design.connect(f"ENV{n}", (package, out))
    design.connect(f"ENVN{n}", (package, inverting))
    design.connect("MAGND", (package, non_inverting))


def envelope_adc(design):
    """The ADC, its 3.3 V rail, the six input networks and the SPI out.

    Spec section 4.4's "external SPI ADC placed in the analogue section", and
    the reason it is in the analogue section is the count: six analogue traces
    crossing the boundary against six logic ones, with the logic ones each
    tolerating about 1.5 V of ground offset and the analogue ones about
    0.1 mV. That is floorplan.CROSSING_RULE's arithmetic and it is unchanged;
    what changed is that the rule said *four* signals and named them by
    direction. There are six and two of them go the other way. See
    envelope_adc_clock() for why MCLK is one of them.

        ENV{n} --R{n}56--+--R{n}57--+ MAGND        U18: V5 -> V3V3
                         |          |
                         +--C{n}52--+              U17: CH{n-1}
                        ENVA{n}                         REFIN+ = VREF
                                                        AGND = DGND = MAGND

    **AGND and DGND are the same net here, and it is the datasheet's own
    second option rather than a shortcut.** Section 7.3 offers two schemes:
    two supplies and two grounds joined at a star, or "consider the
    MCP3561/2/4 as an analog component, and therefore, connect AVDD to DVDD
    and AGND to DGND with a star connection", whose stated cost is that "the
    decoupling capacitors may be larger, due to the ripple on the digital
    power supply ... now causing glitches on the analog power supply". This
    board already has a star -- R902 -- and putting the ADC's own second star
    beside it would be two joins between two domains, which is precisely the
    thing floorplan.py exists to forbid. So the part is analogue, entirely,
    and the boundary stays where it is.
    """
    # -- the 3.3 V rail ----------------------------------------------------
    #
    # From V5 and not from VA+, and the part's own 6.0 V input rating is what
    # makes that a fact rather than a preference. See V3V3_PART.
    design.add(Part(V3V3_REF, V3V3_PART, SOT23_FP, mpn=V3V3_MPN,
                    description="+3.3 V for the envelope ADC, from V5. "
                                "1.6 uA of quiescent current, which is what "
                                "keeps it off the converter's headroom -- "
                                "see supply_fit()"))
    design.connect("V5", (V3V3_REF, V5_PINS["VI"]))
    design.connect("V3V3", (V3V3_REF, V5_PINS["VO"]))
    design.connect("MAGND", (V3V3_REF, V5_PINS["GND"]))
    # The datasheet's own CIN and COUT, at its own value: every figure in its
    # electrical table is specified at 1 uF of each. **The MCP3564 asks for
    # 10 uF here and it is declined**, for the reason the reference's own
    # bulk capacitor was: a larger output capacitor is a change to a
    # regulator's loop that its datasheet has not qualified, and "stable with
    # 1.0 uF ceramic output capacitor" is the only claim this one makes.
    _capacitor(design, "C815", V3V3_CAP, "V5", "MAGND", footprint=C_FP,
               description="U18 input capacitor, 1 uF -- the datasheet's own "
                           "test condition")
    _capacitor(design, "C816", V3V3_CAP, "V3V3", "MAGND", footprint=C_FP,
               description="U18 output capacitor, 1 uF -- the value its "
                           "stability is stated at")

    # -- the six input networks -------------------------------------------
    for n in range(1, CHANNELS + 1):
        _resistor(design, f"R{n}56", ENV_ADC_R_TOP, f"ENV{n}", f"ENVA{n}",
                  description=f"Channel {n} ADC divider, upper -- see "
                              f"envelope_adc_input(): the ratio is set by the "
                              f"largest voltage stage B can produce, not by "
                              f"the largest it should")
        _resistor(design, f"R{n}57", ENV_ADC_R_BOT, f"ENVA{n}", "MAGND",
                  description=f"Channel {n} ADC divider, lower")
        _capacitor(design, f"C{n}52", ENV_ADC_C, f"ENVA{n}", "MAGND",
                   description=f"Channel {n} ADC anti-alias, "
                               f"{envelope_adc_input()['corner_hz'] / 1e3:.1f}"
                               f" kHz against DMCLK")

    # -- the converter -----------------------------------------------------
    design.add(Part(ENV_ADC_REF, ENV_ADC, TSSOP20_FP, mpn=ENV_ADC_MPN,
                    description="Envelope ADC: 8 single-ended channels, "
                                "SCAN sequencer, 24-bit. Six used at "
                                f"{ENV_SAMPLE_HZ / 1e3:.0f} kHz each -- see "
                                "envelope_sample_rate()"))
    design.connect("V3V3", (ENV_ADC_REF, ENV_ADC_PINS["AVDD"]),
                   (ENV_ADC_REF, ENV_ADC_PINS["DVDD"]))
    design.connect("MAGND", (ENV_ADC_REF, ENV_ADC_PINS["AGND"]),
                   (ENV_ADC_REF, ENV_ADC_PINS["DGND"]),
                   # "For single-ended reference applications, the REFIN- pin
                   # should be directly connected to AGND" -- DS20006181C 3.2,
                   # and note 3 of the electrical table says the same.
                   (ENV_ADC_REF, ENV_ADC_PINS["REFIN-"]))
    design.connect("VREF", (ENV_ADC_REF, ENV_ADC_PINS["REFIN+"]))
    for n in range(1, CHANNELS + 1):
        design.connect(f"ENVA{n}",
                       (ENV_ADC_REF, ENV_ADC_PINS[ENV_ADC_CHANNEL[n]]))
    # **The two spare channels are grounded, not flagged, and which two they
    # are is a routing decision.** They are analogue inputs on a part whose own
    # note asks for AGND on an unconnected pin "for a better susceptibility to
    # electromagnetic fields", and an input left open inside a multiplexer is a
    # floating node the SCAN sequencer can be told to read. A no-connect flag
    # would declare the opposite of what is wanted -- see NO_CONNECT, which is
    # for pins that must stay open. See ENV_ADC_CHANNEL for why they are CH4
    # and CH7: the fan-out has removed the reason, and CH0-CH5 was measured and
    # costs a net in another zone.
    design.connect("MAGND", *[(ENV_ADC_REF, ENV_ADC_PINS[name])
                              for name in ENV_ADC_GROUNDED])
    for name, net in (("SCK", "SCLK"), ("SDI", "MOSI"), ("SDO", "MISO"),
                      ("CS", "CS"), ("MCLK", "MCLK"), ("IRQ", "IRQ")):
        design.connect(net, (ENV_ADC_REF, ENV_ADC_PINS[name]))
    # Local decoupling at the two supply pins and at the reference input.
    # envelope_adc_reference() is why the third of these is 100 nF and not the
    # 10 uF its own datasheet suggests.
    for ref, net, note in (
            ("C817", "V3V3", "U17 AVDD decoupling, at the pin"),
            ("C818", "V3V3", "U17 DVDD decoupling, at the pin"),
            ("C819", "VREF", "U17 REFIN+ decoupling -- 100 nF and not the "
                             "10 uF DS20006181C suggests, because VREF's one "
                             "bulk capacitor is already fitted. See "
                             "envelope_adc_reference()")):
        _capacitor(design, ref, ENV_ADC_LOCAL, net, "MAGND", description=note)

    # **J12 and J13 were here and they are gone with the deferral.** Two more
    # of the mixer's own 5-way headers, carrying the six logic signals out to
    # a controller on some other board, with the two clocks in the middle of
    # their connectors so each had a ground on both sides. The controller is
    # on this board now and controller() wires those six to its pins; what
    # replaces the ground-between-signals rule is floorplan.CROSSINGS and the
    # router.


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

    for ref in OPAMP_PACKAGES + list(ENV_PACKAGES_REFS):
        _, value = package_part(ref)
        design.add(Part(ref, value, SOIC14_FP,
                        units=len(OPAMP_UNITS),
                        description=(
                            "Quad JFET, envelope half-wave stages"
                            if ref in ENV_PACKAGES_REFS
                            else "Quad JFET, front end / I-V / servo / CV / "
                                 "envelope sum")))
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

    # The spare sections, terminated. See SECTIONS[("spare", 0)] for why an
    # unused JFET section is not free. Output to its own inverting input, input
    # at MAGND: a follower sitting at 0 V, with no external part.
    #
    # **Three of them now, and each gets its own net.** One net across all three
    # would tie three followers' outputs together, which is a fault that draws
    # as a tidy single label -- and the netlist comparison would have agreed
    # with it, because design.py would have said the same wrong thing.
    for key in SPARE_SECTIONS:
        package, unit = SECTIONS[key]
        out, inverting, non_inverting = OPAMP_UNITS[unit]
        design.connect(f"SPARE{key[1]}", (package, out), (package, inverting))
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

    # **J9 to J13 were here and they are gone.** Five of the mixer's own 5-way
    # headers, carrying six PWM, OE, FSDRV and the ADC's six logic signals out
    # to a controller on some other board -- with the note that "when those
    # blocks land they replace these headers rather than joining them", which
    # is what has happened. The controller is in zone D2 and controller() wires
    # those fourteen nets to its pins.
    #
    # Worth recording rather than deleting silently, because the headers were
    # carrying an argument as well as fourteen nets: their pinouts put a ground
    # between every pair of signals and the two clocks in the middle of their
    # connectors, which was the right rule for a ribbon and has no meaning on a
    # board. What replaces it is floorplan.CROSSINGS and the router, and
    # neither of those is a pin order.

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


def supply(design):
    """The isolated converter, its inlet, its barrier and the 5 V rail.

    Left to right, and the middle of it is a line rather than a part:

        J8 --- F801 --- D804 --+-- C807 C808 C809 --+-- U15 +-- R804 -- VA+
        the shared             |                    |   |   |
        barrel jack          IGND ------------------+   |   +-- R805 -- VA-
                               |                        |   |
                               +------ C810 ------------+   +-- U16 --- V5
                                    across the barrier

    Everything left of C810 is referenced to IGND, which is the inlet's 0 V
    and therefore the mixer's own PGND through the shared jack. Everything
    right of it is referenced to MDGND. The two meet at one capacitor and at
    50 pF of transformer, and at nothing else -- that is constraint 5.2 held
    by construction rather than by discipline, which is supply-decision.md's
    own decisive argument for isolating in the first place.

    Four things here are derived rather than chosen, each in its own function:
    the converter against the load (supply_fit()), the resistor rather than an
    inductor in the rail filter (rail_filter()), the Y-capacitor (barrier_
    return()), and the regulator's *package* (v5_regulator()).

    **What the rails actually are, as opposed to what RAILS says.** The
    converter is +/-1 % on set accuracy with 5 % of cross regulation on output
    2, and the rail filter drops another 0.24 V, so VA+ and VA- sit inside
    about 11.5 to 12.4 V rather than at 12.000. RAILS keeps 12.0 and every
    consumer of it is conservative at that value in the direction that
    matters: clamp_gain() uses it as the amplifier's saturation voltage, where
    a *larger* rail is the worse fault, and NET_DC uses it to pick voltage
    ratings, where the same is true. It is worth writing down that the two
    disagree and why, because the next number derived from MODULE_RAIL may not
    be conservative at all.
    """
    # -- the primary, and it is one net at a time on purpose ---------------
    #
    # The polarity comment is copied from the mixer's own J8 rather than
    # re-derived, because the mixer's records that the instruction beside it
    # read "centre pin" for the whole life of that design and was backwards.
    # On a Boss-standard centre-negative barrel the *sleeve* is positive.
    design.add(Part("J8", "PWR", socket.CONN_FP[2], mpn=socket.CONN_MPN[2],
                    description=f"Shared DC inlet ({socket.SUPPLY_RANGE}), in "
                                f"parallel with the mixer's own J8 at the "
                                f"barrel jack: 1=sleeve (+), 2=centre pin "
                                f"(0 V). Primary side -- see IGND"))
    design.connect("VIN_J", ("J8", 1))
    design.connect("IGND_J", ("J8", 2))

    # -- the inlet fuse, ahead of everything -------------------------------
    #
    # **In series with the live conductor and ahead of the choke**, so that
    # what it protects includes the choke. A fuse is a two-terminal element in
    # one leg of the pair and shunts nothing across it, which is why it can
    # sit in front of the winding without being the fault the check below
    # exists for: what must not go there is anything that *commons* the two
    # conductors. See inlet_fuse() for the part, the rating and the honest
    # limit on what a fuse is worth here.
    design.add(Part(INLET_FUSE_REF, INLET_FUSE, FUSE_FP, mpn=INLET_FUSE_MPN,
                    description=(
                        "Inlet fuse, 1.6 A time-lag, in the live conductor "
                        "ahead of L801: the converter datasheet's own "
                        "recommended input fuse for 24 Vin models")))
    design.connect("VIN_J", (INLET_FUSE_REF, 1))
    design.connect("VIN_F", (INLET_FUSE_REF, 2))

    # -- the common-mode choke, and it goes first for a reason ------------
    #
    # Everything else on the primary -- D804, the three decoupling
    # capacitors, the converter's own +Vin and -Vin -- sits on the converter
    # side of it. That is what makes the barrier's return current see 1 mH:
    # the current arrives from the mixer through *both* inlet conductors at
    # once, so what it meets has to be common mode to both, and a choke placed
    # after the decoupling would have the capacitors shorting the pair
    # together in front of it. See barrier_return(); the same part in the
    # wrong place is worth 0 dB and looks identical on the sheet.
    design.add(Part(INLET_CHOKE_REF, INLET_CHOKE, CHOKE_FP,
                    mpn=INLET_CHOKE, description=(
                        "Common-mode choke in the inlet pair, 2 x 1 mH, "
                        "800 mA: the second half of barrier_return(). "
                        "Windings are 1-4 and 2-3 -- see INLET_CHOKE_PINS")))
    design.connect("VIN_F", (INLET_CHOKE_REF, INLET_CHOKE_PINS["L1_IN"]))
    design.connect("VIN", (INLET_CHOKE_REF, INLET_CHOKE_PINS["L1_OUT"]))
    design.connect("IGND_J", (INLET_CHOKE_REF, INLET_CHOKE_PINS["L2_IN"]))
    design.connect("IGND", (INLET_CHOKE_REF, INLET_CHOKE_PINS["L2_OUT"]))

    # **The fuse above closes an entry that stood open for four passes**, and
    # what closed it was not the requirement. The old note here read: "It is
    # not fitted because no part number was verified this session. The obvious
    # families do not hold: Littelfuse's 453 Nano2 is ultra-fast rather than
    # Slo-Blo, its 154 series is a 2410 body and not the 1206 this was drawn
    # around, and KiCad ships a land pattern for neither of the parts that
    # would fit." Every clause of that is true and the conclusion drawn from
    # it -- that the part could not be fitted -- was a fact about one
    # manufacturer. SCHURTER's UMT 250 is time-lag by construction, KiCad
    # ships its land pattern under the part's own name, and the 1.6 A variant
    # has an order number on page 4 of a datasheet this repo has now read.
    #
    # **The search was for a footprint that fitted a shape already drawn**, and
    # that is the reusable half: "the 1206 this was drawn around" is the
    # reason a 2410 body was a disqualification rather than a dimension. There
    # was no board to fit it to -- the row it goes in is packed by
    # placement.pack_east() and simply got 11.4 mm longer.

    # Reverse protection. Series rather than shunt, and the mixer's part for
    # the mixer's reason -- see INLET_DIODE. No TVS: the module's own input is
    # rated 36 V continuous and 50 V for a second, against a 20 V worst-case
    # brick, so the only overvoltage a TVS would catch is a 24 V supply
    # plugged in by mistake, which the converter survives and the mixer's
    # LM317 already handles. A clamp that never conducts is a leakage path and
    # a part.
    design.add(Part("D804", INLET_DIODE, SMA_FP,
                    description="Inlet reverse-polarity protection: anode "
                                "VINF, cathode VIN_P"))
    design.connect("VIN", ("D804", DIODE_PINS["A"]))
    design.connect("VIN_P", ("D804", DIODE_PINS["K"]))

    # Two bulk and one HF, all on the protected side and all 50 V -- see
    # PRIMARY_BULK_C. input_filter() is why there is no inductor between them.
    for ref, value, note in (
            ("C807", PRIMARY_BULK_C, "Primary bulk, at the inlet end"),
            ("C808", PRIMARY_BULK_C, "Primary bulk, at the converter's pin"),
            ("C809", PRIMARY_HF_C, "Primary HF, at the converter's pin")):
        _capacitor(design, ref, value, "VIN_P", "IGND", description=note,
                   footprint=C_FILM_FP if value is PRIMARY_BULK_C else C_FP)

    design.add(Part(SUPPLY_REF, SUPPLY_PART, SUPPLY_FP, mpn=SUPPLY_MPN,
                    description="Isolated DC-DC, 9-36 V in, +/-12 V at "
                                "250 mA, 580 kHz PWM flyback, 1600 VDC"))
    design.connect("VIN_P", (SUPPLY_REF, SUPPLY_PINS["+Vin"]))
    design.connect("IGND", (SUPPLY_REF, SUPPLY_PINS["-Vin"]))
    # Remote is an *input* referred to -Vin, and its own table reads "On: 0 to
    # 0.5 VDC or open circuit". Open would work and is not what is drawn: a
    # pin that is on because nobody connected it is a pin that changes meaning
    # the first time somebody adds a pull-up. Tied to -Vin it is on by
    # assertion and draws nothing, because the 0.5 to 3.5 mA the datasheet
    # quotes is the current when it is driven *off*.
    design.connect("IGND", (SUPPLY_REF, SUPPLY_PINS["Remote"]))

    # -- the barrier -------------------------------------------------------
    #
    # The one part in this block that is load-bearing, and the one whose value
    # is a trade rather than a maximum. barrier_return() is the whole of it.
    # It is the envelope detector's own 470 nF, which is worth saying because
    # it is the reason there is no new BOM line: the value barrier_return()
    # arrives at is one the board already buys a reel of.
    _capacitor(design, "C810", BARRIER_C, "IGND", "MDGND",
               description="Y-capacitor across the isolation barrier -- the "
                           "local return for the 50 pF of common-mode "
                           "current, so it does not take the audio bond")

    # -- the secondary -----------------------------------------------------
    design.connect("VA_RAW", (SUPPLY_REF, SUPPLY_PINS["+Vout"]))
    design.connect("MDGND", (SUPPLY_REF, SUPPLY_PINS["Com"]))
    design.connect("VN_RAW", (SUPPLY_REF, SUPPLY_PINS["-Vout"]))

    # One pole per rail. The capacitors return to MDGND and not to MAGND, and
    # that is the floorplan's rule rather than a preference: this is switching
    # return current and it belongs in the pour that the star lets it be in.
    # Sending it to MAGND would run every milliamp of it through R902.
    _resistor(design, "R804", RAIL_FILTER_R, "VA_RAW", "VA+",
              description="VA+ rail filter -- see rail_filter(), a resistor "
                          "and not an inductor because the LC would ring at "
                          "Q ~ 100 inside the audio band")
    _capacitor(design, "C811", RAIL_FILTER_C, "VA+", "MDGND",
               footprint=C_FILM_FP, description="VA+ rail filter")
    _resistor(design, "R805", RAIL_FILTER_R, "VN_RAW", "VA-",
              description="VA- rail filter -- the same pole on the other rail")
    _capacitor(design, "C812", RAIL_FILTER_C, "VA-", "MDGND",
               footprint=C_FILM_FP, description="VA- rail filter")

    # The 5 V rail, and its input is taken from VA_RAW rather than from VA+.
    # That is worth being explicit about because it looks like a shortcut and
    # is the opposite: the relay coils are 93 mA that step every time the
    # module goes into or out of circuit, and taking them from ahead of R804
    # keeps that step out of the rail the six audio channels share. It costs
    # nothing -- the same copper, one node earlier.
    design.add(Part(V5_REF, V5_PART, DPAK_FP, mpn=V5_MPN,
                    description="+5 V for the relay coils and the reference. "
                                "DPAK and not SOT-223: 0.77 W against that "
                                "package's own 160 C/W -- see v5_regulator()"))
    design.connect("VA_RAW", (V5_REF, V5_PINS["VI"]))
    design.connect("V5", (V5_REF, V5_PINS["VO"]))
    design.connect("MDGND", (V5_REF, V5_PINS["GND"]))
    # Both required by the datasheet rather than added for luck: its
    # electrical table is specified at Cin = Cout = 10 uF and Figure 1 draws
    # both.
    _capacitor(design, "C813", PRIMARY_BULK_C, "VA_RAW", "MDGND",
               footprint=C_FILM_FP,
               description="NCP1117 input capacitor, 10 uF -- the datasheet's "
                           "own test condition")
    _capacitor(design, "C814", "10u/16V X7R", "V5", "MDGND",
               footprint=C_FILM_FP,
               description="NCP1117 output capacitor, 10 uF")


def controller(design):
    """The RP2040, its flash, its crystal, USB, DIN MIDI, the panel and the
    3.3 V switcher.

    **The block J9 to J13 were standing in for.** Those five headers were "where
    the deferred blocks meet this one", with design.py's own note that "when
    those blocks land they replace these headers rather than joining them" --
    so they are gone and the fourteen nets they carried land on U19's pins.

    What is drawn here follows the vendor's own reference design wherever that
    document states a value, and the constants above carry the quotation. What
    it does not follow is its decoupling compromise: the minimal design shares
    one capacitor between pins 48 and 49 because it is a two-layer board with
    parts on one side, and says so; this is four layers with a plane under the
    part, so every supply pin gets its own.
    """
    P = CONTROLLER_MODULE_PINS
    design.add(Part(CONTROLLER_REF, CONTROLLER, PICO_FP, mpn=CONTROLLER_MPN,
                    description="Raspberry Pi Pico. Dual Cortex-M0+ at "
                                "125 MHz, and on the module with it: the "
                                "flash, the crystal, the USB receptacle, the "
                                "3.3 V converter and every decoupling "
                                "capacitor -- about 25 parts this board no "
                                "longer draws. See controller_fit()"))

    # -- supplies ----------------------------------------------------------
    #
    # **Three pins, and the direction of two of them is the whole topology.**
    # VSYS is an input and 3V3 is an output; this board hands the module its
    # power at the first and takes its 3.3 V rail back from the second. See
    # controller_supply() for why, and pico_backdrive() for the cheaper
    # arrangement that is refused.
    design.connect("VSYS", (CONTROLLER_REF, P["VSYS"]))
    design.connect("VMCU", (CONTROLLER_REF, P["3V3"]))
    for pin in CONTROLLER_MODULE_GND_PINS:
        design.connect("MDGND", (CONTROLLER_REF, pin))
    # **AGND to MDGND, and the datasheet is the one that allows it.** Section
    # 2.1: "AGND is the ground reference for GPIO26-29 ... If the ADC is not
    # used or ADC performance is not critical, this pin can be connected to
    # digital ground." One channel is used and it reads a foot pedal that
    # firmware calibrates at its extremes, so what is asked of it is monotonic
    # and bounded rather than accurate -- expression_input(). This board's
    # analogue ground is on the other side of R902 and a separating star, and
    # taking a module's analogue return there would be a second bond across
    # the split for a pedal.
    design.connect("MDGND", (CONTROLLER_REF, P["AGND"]))
    # **The ORing diode, and it is not there for the drop.** Pico datasheet
    # Figure 16: "The simplest way to safely add a second power source to Pico
    # is to feed it into VSYS via another Schottky diode ... with the diodes
    # preventing either supply from back-powering the other."
    #
    # What it prevents here is sharper than that sentence and worth writing
    # down, because it is a path through a part rather than into one. With no
    # diode and a USB cable plugged into an *unpowered* board, VBUS reaches
    # VSYS through the module's own D1, and from VSYS it is on U22's output --
    # where the buck's high-side body diode carries it to VA_RAW. A USB host
    # would then be sitting on this board's twelve-volt rail at about four
    # volts, with every op-amp and VCA on it in a state nothing has derived.
    # The diode is what makes "USB plugged in, board off" a state rather than
    # a question.
    design.add(Part("D806", CLAMP_DIODE, SOD123F_FP,
                    description="VMOD to VSYS: the ORing diode of Pico "
                                "datasheet Figure 16. PMEG2010AEH because it "
                                "is already on this board and its curve is "
                                "read -- 0.29 V at 100 mA, CLAMP_VF_TABLE, "
                                "against the BAT54's 0.4 and its 200 mA"))
    design.connect("VMOD", ("D806", DIODE_PINS["A"]))
    design.connect("VSYS", ("D806", DIODE_PINS["K"]))

    # -- reset -------------------------------------------------------------
    #
    # **One 2-way header, and what it buys is the sanctioned way in.** The
    # module's route to BOOTSEL is its own datasheet's: "depower the board,
    # then hold the BOOTSEL button down during board power-up". Depowering
    # *this* board means switching off a bipolar analogue supply and waiting
    # for it, so a reset link turns that into holding the module's own button
    # and shorting two pins. RUN has a ~50 kOhm pull-up on the die -- section
    # 2.1, "an internal (on-chip) pull-up resistor to 3.3 V of about ~50 kOhm"
    # -- so R825 goes with the QFN: an external pull-up on a pin that has one
    # and never leaves the enclosure is a part with no argument.
    #
    # ~~SWD.~~ **Not drawn, and the reason is the assembly rather than the
    # part.** J20 existed because "the other two ways in both depend on
    # something" -- USB BOOTSEL needed a working flash and a working crystal,
    # both of which this board carried. The module carries them, and its
    # bootloader is in ROM, so that argument is gone. What is left is
    # debugging, and the module's three debug pads are on its *underside*:
    # reachable by reflow, not by the iron this board is built with.
    design.connect("RUN", (CONTROLLER_REF, P["RUN"]))
    design.add(Part("J19", "RESET", socket.CONN_FP[2], mpn=socket.CONN_MPN[2],
                    description="Reset link: 1 = RUN, 2 = MDGND. Short to "
                                "reset -- Pico datasheet section 2.1"))
    for pin, net in ((1, "RUN"), (2, "MDGND")):
        design.connect(net, ("J19", pin))

    # -- DIN MIDI ----------------------------------------------------------
    #
    # In: CA-033 Figure 2, with RD deleted because the TLP2761's output is
    # totem pole. Out: Figure 1's 3.3 V column, unchanged.
    design.add(Part(MIDI_OPTO_REF, MIDI_OPTO, SO6L_FP, mpn=MIDI_OPTO_MPN,
                    description="MIDI IN opto-isolator. 2.7-5.5 V supply and "
                                "1.6 mA of threshold current, which is what "
                                "makes a 3.3 V receiver possible at all"))
    design.connect("MINA", (MIDI_OPTO_REF, MIDI_OPTO_PINS["A"]))
    design.connect("MINK", (MIDI_OPTO_REF, MIDI_OPTO_PINS["K"]))
    design.connect("VMCU", (MIDI_OPTO_REF, MIDI_OPTO_PINS["VCC"]))
    design.connect("MDGND", (MIDI_OPTO_REF, MIDI_OPTO_PINS["GND"]))
    design.connect("MIDI_RX", (MIDI_OPTO_REF, MIDI_OPTO_PINS["VO"]))
    _capacitor(design, "C835", MIDI_OPTO_LOCAL, "VMCU", "MDGND",
               description="U21 bypass, 100 nF. Not decoupling: its datasheet "
                           "makes it a condition of operation -- 'otherwise, "
                           "this photocoupler may not switch properly' -- and "
                           "gives it a distance, within 1 cm of each pin")
    _resistor(design, "R827", MIDI_IN_RB, "MINJ", "MINA",
              description="MIDI IN loop resistor -- 390 ohm and not CA-033's "
                          "220, because this receiver may face either a 5 V "
                          "or a 3.3 V transmitter. See midi_loop()")
    design.add(Part("D805", MIDI_IN_DIODE, SOD123_FP,
                    description="Reverse voltage protection for the opto's "
                                "LED -- CA-033 Figure 2's own 1N914, in the "
                                "SOD-123 this board already buys"))
    design.connect("MINA", ("D805", DIODE_PINS["K"]))
    design.connect("MINK", ("D805", DIODE_PINS["A"]))
    design.add(Part("J15", "MIDIIN", socket.CONN_FP[3], mpn=socket.CONN_MPN[3],
                    description="To the panel's MIDI IN socket: 1 = DIN pin "
                                "4, 2 = DIN pin 2 and the shield, 3 = DIN pin "
                                "5. Pins 1 and 3 of the DIN are unused"))
    for pin, net in ((1, "MINJ"), (2, "MINSH"), (3, "MINK")):
        design.connect(net, ("J15", pin))
    # "a connection through a small capacitor (0.1uF typical) to ground is
    # optional for improved high-frequency (RF) shielding" -- and a capacitor
    # is the only thing that can do it, because CA-033 forbids the DC path in
    # the sentence before.
    _capacitor(design, "C836", MIDI_IN_SHIELD_C, "MINSH", "MDGND",
               description="MIDI IN shield and DIN pin 2 to local ground at "
                           "RF only -- CA-033's optional capacitor, and the "
                           "specification forbids any DC path here")
    design.add(Part("J16", "MIDIOUT", socket.CONN_FP[3], mpn=socket.CONN_MPN[3],
                    description="To the panel's MIDI OUT socket: 1 = DIN pin "
                                "4, 2 = DIN pin 2 to ground, 3 = DIN pin 5"))
    for pin, net in ((1, "MOUTV"), (2, "MDGND"), (3, "MOUTD")):
        design.connect(net, ("J16", pin))
    _resistor(design, "R828", MIDI_OUT_RA, "VMCU", "MOUTV",
              description="MIDI OUT RA -- CA-033's 3.3 V column, 33 ohm")
    _resistor(design, "R829", MIDI_OUT_RC, "MIDI_TX", "MOUTD",
              description="MIDI OUT RC -- CA-033's 3.3 V column, 10 ohm")

    # -- the panel: tap and expression -------------------------------------
    design.add(Part("J17", "TAP", socket.CONN_FP[2], mpn=socket.CONN_MPN[2],
                    description="Tap footswitch jack: 1 = tip, 2 = sleeve. "
                                "Momentary to ground; bounce is a firmware "
                                "constant at the 8 kHz frame -- see "
                                "tap_debounce()"))
    design.connect("TAPJ", ("J17", 1))
    design.connect("MDGND", ("J17", 2))
    _resistor(design, "R830", TAP_PULLUP, "VMCU", "TAPJ",
              description="Tap pull-up -- the pin's reset state is pull-DOWN "
                          "(Table 615), so without this the level before "
                          "firmware runs is undefined")
    _resistor(design, "R831", TAP_SERIES, "TAPJ", "TAP",
              description="Tap series resistor: what a lead leaving the "
                          "enclosure gets between it and the die")
    _capacitor(design, "C837", TAP_C, "TAP", "MDGND",
               description="Tap RC, into the pin's own Schmitt trigger "
                           "(VHYS 0.2 V at 3.3 V)")
    design.add(Part("J18", "EXPR", socket.CONN_FP[3], mpn=socket.CONN_MPN[3],
                    description="Expression pedal jack: 1 = tip (wiper), 2 = "
                                "ring (supply), 3 = sleeve. A TS plug shorts "
                                "2 to 3 -- see expression_input()"))
    for pin, net in ((1, "EXPRW"), (2, "EXPRV"), (3, "MDGND")):
        design.connect(net, ("J18", pin))
    _resistor(design, "R832", EXPR_TOP, "VMCU", "EXPRV",
              description="Expression pedal supply resistor -- the only thing "
                          "between VMCU and a mono plug in a stereo socket")
    _resistor(design, "R833", EXPR_SERIES, "EXPRW", "EXPR",
              description="Expression wiper series resistor")
    _capacitor(design, "C838", EXPR_C, "EXPR", "MDGND",
               description="Expression anti-alias and ESD, at the pin")

    # -- what lands on which GPIO ------------------------------------------
    #
    # CONTROLLER_MAP is the assignment and controller_pin_map() is the join;
    # this is the only place either is turned into copper, so the check in
    # Design.check_controller_functions() covers the netlist rather than a
    # table beside it.
    for row in controller_pin_map():
        design.connect(row["net"], (CONTROLLER_REF, row["pin"]))

    # -- the 3.3 V switcher ------------------------------------------------
    #
    # Input from VA_RAW, one node ahead of the rail filter, so that its pulse
    # train is on the same side of R804 as the converter's own ripple. See
    # controller_supply() and mcu_dcdc_injection().
    Q = MCU_DCDC_PINS
    design.add(Part(MCU_DCDC_REF, MCU_DCDC, SOT23_6_FP, mpn=MCU_DCDC_MPN,
                    description="3.3 V for the controller: 1.1 MHz, forced "
                                "PWM at every load, 12 V in. See "
                                "mcu_dcdc_light_load() for why the F suffix "
                                "is load-bearing"))
    design.connect("VA_RAW", (MCU_DCDC_REF, Q["VIN"]), (MCU_DCDC_REF, Q["EN"]))
    design.connect("MDGND", (MCU_DCDC_REF, Q["GND"]))
    design.connect("MSW", (MCU_DCDC_REF, Q["SW"]))
    design.connect("MCB", (MCU_DCDC_REF, Q["CB"]))
    design.connect("MFB", (MCU_DCDC_REF, Q["FB"]))
    _capacitor(design, "C840", MCU_DCDC_CIN, "VA_RAW", "MDGND",
               footprint=C_FILM_FP,
               description="U22 input capacitor, 2.2 uF at 50 V -- section "
                           "9.2.2.6, which asks for twice the maximum input "
                           "voltage of rating")
    _capacitor(design, "C841", MCU_DCDC_CIN_HF, "VA_RAW", "MDGND",
               description="U22 high-frequency input capacitor, 100 nF, at "
                           "the pins -- the same section's second sentence")
    _capacitor(design, "C842", MCU_DCDC_CBOOT, "MCB", "MSW",
               description="U22 bootstrap capacitor, 100 nF -- section 9.2.2.7")
    design.add(Part("L802", MCU_DCDC_L, INDUCTOR_FP, mpn=MCU_DCDC_L_MPN,
                    description="12 uH, Isat 4.0 A against a 1.4 A peak "
                                "current limit -- Table 1's own value for "
                                "1.1 MHz at 3.3 V"))
    design.connect("MSW", ("L802", 1))
    design.connect("VMOD", ("L802", 2))
    _capacitor(design, "C843", MCU_DCDC_COUT, "VMOD", "MDGND",
               footprint=C_FILM_FP,
               description="U22 output capacitor, 22 uF -- Table 1")
    _resistor(design, "R850", MCU_DCDC_RFBT, "VMOD", "MFB",
              description="U22 feedback divider, upper. 51k/22k1 is Table 1's "
                          "pair and mcu_dcdc_output() is the equation-7 check "
                          "on it")
    _resistor(design, "R851", MCU_DCDC_RFBB, "MFB", "MDGND",
              description="U22 feedback divider, lower")


def build():
    design = Design()
    shared(design)
    supply(design)
    fail_safe(design)
    for n in range(1, CHANNELS + 1):
        channel(design, n)
        envelope(design, n)
    # After the six, because it hangs off all of them: ENV{n} has to exist
    # before the divider that reads it.
    envelope_adc(design)
    # Last, because it is the block every other one was waiting for: its own
    # nets are the ones J9-J13 used to carry.
    controller(design)
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
    # **C819 is here because this assertion refused to let it be anywhere
    # else.** The envelope ADC's REFIN+ hangs on VREF, so its local decoupling
    # is a third capacitor on a net qualified for one bulk part -- and the
    # first thing that happened when the block was drawn was this function
    # stopping the build. That is the check working: it was written against a
    # capacitor somebody might add without re-reading the stability range, and
    # the somebody was this pass. See envelope_adc_reference() for why the
    # value is 100 nF and not the 10 uF the ADC's own datasheet suggests --
    # the second bulk capacitor is the fault C804 was deleted to remove, and
    # it would have arrived here with a datasheet sentence recommending it.
    fitted = {"C802": VREF_RESERVOIR_FARADS, "C803": LOGIC_LOCAL_FARADS,
              "C819": 100e-9}
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
          f"{OPAMP_QUADS} x {OPAMP}, all used")
    print(f"  plus                 {ENV_SECTIONS_NEEDED:>8d}     -> "
          f"{ENV_QUADS} x {ENV_OPAMP} for the envelope half-wave stages, "
          f"{len(SPARE_SECTIONS)} spare terminated")
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

    print("envelope detector -- symmetric one-pole, and both bounds are electrical")
    e = envelope_filter()
    print(f"  tau                  {e['tau'] * 1e3:>8.2f} ms  "
          f"({ENV_R} x {ENV_C}), corner {e['corner']:.1f} Hz")
    print(f"  at the pick's peak   {e['attack_db']:>+8.2f} dB  "
          f"(peak arrives at {PICK_PEAK_S * 1e3:.0f} ms -- hexsim's own "
          f"calibration)")
    print(f"  falls at             {e['fall_db_per_ms']:>8.2f} dB/ms  "
          f"against {e['music_ms_per_db']:.0f} ms/dB of early decay -- "
          f"{e['faster_than_music']:.0f}x")
    print(f"  -> there is no release bound, so no attack/release target is "
          f"needed. {e['sections']} sections,")
    print(f"     {'full' if e['full_wave'] else 'half'}-wave: the bow decides "
          f"it, see ENV_FULL_WAVE")
    print(f"  open string  ripple    alias at {ENV_SAMPLE_HZ / 1e3:.0f} kHz"
          f"   after {ENV_FIRMWARE_BOX_S * 1e3:.0f} ms")
    for row in e["rows"]:
        print(f"  {row['f0']:>8.1f} Hz  {row['ripple_db']:>+6.2f} dB  "
              f"{row['alias_db']:>+11.1f} dB  {row['firmware_db']:>+13.2f} dB")
    b = envelope_balance()
    print(f"  detector floor       {b['floor_db']:>+8.1f} dB  "
          f"({b['floor_volts'] * 1e3:.0f} mV of A2 offset against "
          f"{b['peak']:.2f} V pk), and the E96 half-value costs "
          f"{b['imbalance_db']:.3f} dB")
    s = envelope_sample_rate()
    print("  and the sample rate is derived, not the range section 4.4 offers:")
    for rate, row in sorted(s["rates"].items()):
        print(f"    {rate / 1e3:.0f} kHz   worst {row['worst_db']:>+6.1f} dB "
              f"across the fretted range (fret {row['worst_fret']}), "
              f"{row['folds_to_dc_db']:+.1f} dB folding to "
              f"{row['folds_to_dc_hz']:.0f} Hz")
    print()

    print(f"the controller -- {CONTROLLER}, and the case for it is derived now")
    fit = controller_fit()
    for row in fit["rows"]:
        if row["units"] == "count":
            need = f"{row['needs']:.0f}"
            has = f"{row['has']:.0f}"
        else:
            need = f"{row['needs'] / 1e6:.3f} MHz"
            has = f"{row['has'] / 1e6:.3f} MHz"
        print(f"  {row['asked']:<30}{need:>11} -> {has:<11} "
              f"{row['note']}")
    print(f"  -> the tightest row is MCLK at {fit['mclk_margin']:.2f}x, and it "
          f"is not a margin to spend: {len(fit['mclk_divisors'])} integer "
          f"divisors clear the floor and the point is the integer. The "
          f"tightest countable row is {fit['tightest_count']:.2f}x, on "
          f"{fit['tightest_count_row']}")
    print(f"  PWM_CARRIER is margin, not a reason: "
          f"{fit['pwm_carrier_from_clock'] / 1e3:.1f} kHz is 125 MHz / 2^"
          f"{PWM_BITS}, and pwm_ripple() has 83 dB on it either way")
    pack = controller_package()
    print(f"  package                  QFN-56, {pack['pin_pitch_mm']:.2f} mm "
          f"pitch on {pack['pad_width_mm']:.2f} mm pads -- the only one "
          f"{CONTROLLER} is made in")
    print(f"    widest legal escape    {pack['escape_track_mm']:.2f} mm "
          f"against this board's {rules.TRACK_MM} mm track, and "
          f"{pack['pins_per_side']} pins a side want "
          f"{pack['pins_per_side']} grid lines from "
          f"{pack['pin_pitch_mm'] / pack['grid_mm']:.1f} per pin")
    for row in pack["classes"]:
        print(f"    {row['class']:<13} {row['track_mm']:.2f}/"
              f"{row['clearance_mm']:.2f} mm -> {row['grid_mm']:.2f} mm grid, "
              f"escape {row['escape_track_mm']:.2f} mm -- "
              f"{'reachable' if row['reachable'] else 'unreachable'}")
    sup = controller_supply()
    print(f"    supply                 +Vout has "
          f"{sup['headroom_ma']:.1f} mA and the part alone is "
          f"{sup['mcu_ma'][0]:.1f}-{sup['mcu_ma'][1]:.1f} mA on 3.3 V, "
          f"one for one through two linear rails "
          f"({sup['linear_watts'] * 1e3:.0f} mW dissipated)")
    print(f"      a switcher's floor is {sup['switcher_ratio']:.3f} x that = "
          f"{sup['switcher_floor_ma'][1]:.1f} mA, so it clears at any "
          f"efficiency over {sup['switcher_min_efficiency'] * 100:.0f} % -- "
          f"no efficiency figure needed, and none invented")
    print(f"  -> both gates are closed: the package by the fabrication class, "
          f"the supply by U22. DEFERRED is empty")
    print()

    print(f"the controller's own rail -- {MCU_DCDC}, {MCU_DCDC_KHZ[0]:.0f}-"
          f"{MCU_DCDC_KHZ[1]:.0f} kHz forced PWM, from VA_RAW")
    mcu = mcu_supply()
    for name, milliamps in sorted(mcu["terms"].items(),
                                  key=lambda kv: -kv[1]):
        print(f"    {name:<22}{milliamps:>7.2f} mA")
    print(f"    {'total on VMCU':<22}{mcu['load_ma']:>7.2f} mA   "
          f"({mcu['watts'] * 1e3:.0f} mW; idle {mcu['idle_ma']:.1f})")
    print(f"  costs +Vout           {mcu['input_ma']:>7.2f} mA at the "
          f"assumption's pessimistic {MEASURED['mcu_dcdc_efficiency'].low:.2f}"
          f", against {mcu['floor_ma']:.1f} mA at 100 %")
    print(f"  headroom              {mcu['headroom_before_ma']:>7.2f} mA "
          f"before, {mcu['headroom_after_ma']:.2f} after -- the tightest "
          f"margin on this board")
    print(f"  fits at any efficiency over "
          f"{mcu['min_efficiency'] * 100:.0f} %, and the assumed range starts "
          f"at {MEASURED['mcu_dcdc_efficiency'].low * 100:.0f} %")
    light = mcu_dcdc_light_load()
    print(f"  the F suffix           boundary {light['boundary_ma']:.0f} mA: "
          f"continuous in circuit at {light['load_ma']:.0f} mA "
          f"({light['continuous_in_circuit']}), and in bypass at "
          f"{light['bypass_ma']:.0f} mA ({light['continuous_in_bypass']}) -- "
          f"the coils are the difference")
    print(f"    a PFM part would be  {light['pfm_hz_at_bypass'] / 1e3:.0f} kHz "
          f"in bypass and {light['pfm_hz_at_idle'] / 1e3:.0f} kHz in bypass at "
          f"idle, which is under the {SUPPLY_MIN_KHZ:.0f} kHz rule, and in the "
          f"audio band below {light['pfm_in_band_below_ma']:.1f} mA")
    beat = mcu_dcdc_beat()
    inject = mcu_dcdc_injection()
    print(f"  beats                  {beat['worst_beat_khz']:.0f} kHz against "
          f"the TMR at harmonics {beat['worst_pair'][0]}:"
          f"{beat['worst_pair'][1]}, and "
          f"{beat['against_pump']['worst_beat_khz']:.0f} kHz against the "
          f"pump's {beat['against_pump']['worst_order']}th -- second order, "
          f"as supply_beat() says")
    print(f"  injection              {inject['input_rms_ma']:.1f} mA rms of "
          f"input ripple over {inject['z_bulk'] * 1e3:.0f} mohm is "
          f"{inject['on_va_raw_v'] * 1e6:.0f} uV on VA_RAW, "
          f"{inject['residual_v'] * 1e9:.0f} nV on VA+ after R804 "
          f"({inject['am']['am_db']:.0f} dB of AM)")
    out = mcu_dcdc_output()
    print(f"  rail                   {out['volts']:.3f} V from "
          f"{out['rfbt'] / 1e3:.0f}k/{out['rfbb'] / 1e3:.1f}k, "
          f"{out['worst'][0]:.2f}-{out['worst'][1]:.2f} V at every tolerance, "
          f"against the module's {out['vsys_abs_max']:.1f} V VSYS ceiling")
    print()

    print("the controller's pins -- CONTROLLER_MAP against the datasheet's own "
          "Table 2")
    for row in controller_pin_map():
        print(f"  {row['net']:<8} {row['name']:<12} pin {row['pin']:<3} "
              f"{row['function']}")
    print()

    loop = usb_ground_loop()
    print(f"  USB ground   a {loop['current_ma']:.0f} mA installation loop "
          f"puts {loop['volts'] * 1e6:.0f} uV of "
          f"{loop['hz']:.0f} Hz across the bond -- "
          f"{loop['below_floor_db']:.0f} dB under the mixer's noise floor, "
          f"and constraint 5.2 still holds. See usb_ground_loop()")
    print()

    print("what hangs off it")
    chain = mcu_supply()
    back = pico_backdrive()
    print(f"  the module   VSYS {chain['vsys_volts']:.2f} V at "
          f"{chain['vsys_ma']:.0f} mA through D806 ({chain['diode_vf']:.2f} V "
          f"at that current), and 3V3 back out as VMCU")
    print(f"               3V3 back-drive: {back['decision']} -- the "
          f"documented shutdown condition is \"{back['documented_shutdown_condition']}\" "
          f"and this needs \"{back['condition_this_topology_needs']}\"")
    beat = pico_smps_beat()
    print(f"               RT6150 {beat['khz'][0]:.0f}-{beat['khz'][1]:.0f} kHz "
          f"in forced PWM (GPIO{beat['ps_gpio']} high, firmware): clears the "
          f">= {SUPPLY_MIN_KHZ:.0f} kHz rule at the fundamental "
          f"({beat['clears_the_minimum']}), nearest beat against the pump "
          f"{beat['worst_beat_against_pump_khz']:.0f} kHz, and its band "
          f"overlaps U22's ({beat['overlaps_mcu_dcdc']})")
    m = midi_loop()
    print(f"  MIDI in      {m['rb']:.0f} ohm gives {m['low_ma']:.2f}-"
          f"{m['high_ma']:.2f} mA into the opto over both transmitters, "
          f"inside its {m['recommended'][0]:.0f}-{m['recommended'][1]:.0f} mA "
          f"and {m['threshold_margin']:.2f}x over threshold")
    print(f"               the opto costs {m['delay_fraction'] * 100:.2f} % of "
          f"a bit in delay and {m['skew_fraction'] * 100:.2f} % in distortion")
    e = expression_input()
    print(f"  pedal        a mono plug shorts {e['short_ma']:.1f} mA; full "
          f"scale is "
          + " and ".join(f"{v:.2f} V on {int(k / 1000)}k"
                         for k, v in sorted(e['full_scale_v'].items()))
          + ", and firmware calibrates the ends")
    t = tap_debounce()
    print(f"  footswitch   {t['tau_open_s'] * 1e3:.1f} ms of RC against a "
          f"{t['frame_s'] * 1e6:.0f} us frame: bounce is firmware's, the "
          f"impedance is the board's")
    print()

    print(f"the envelope ADC -- {ENV_ADC}, and the full scale chose it")
    adc = envelope_adc_input()
    clk = envelope_adc_clock()
    print(f"  ADS131M08 full scale     1.20 V at unity, against "
          f"clipping_peak {socket.clipping_peak():.3f} V -- "
          f"{20 * math.log10(1.20 / socket.clipping_peak()):+.2f} dB. Its "
          f"reference input stops at 1.3 V")
    print(f"  {ENV_ADC} full scale{VREF:>10.2f} V, "
          f"{20 * math.log10(VREF / socket.clipping_peak()):+.2f} dB, on the "
          f"board's own VREF")
    print(f"  divider              {adc['ratio']:>10.4f}  "
          f"({ENV_ADC_R_TOP} / {ENV_ADC_R_BOT}): "
          f"{adc['swing']:.2f} V of amplifier swing becomes "
          f"{adc['at_swing']:.2f}, inside a {adc['full_scale']:.1f} V full "
          f"scale and a {adc['absolute_max']:.1f} V absolute rating")
    print(f"  -> no input can reach a voltage that needs clamping, so no ESD "
          f"current is ever injected into a 3.3 V rail that cannot sink it")
    print(f"  clipping_peak lands at   {adc['clipping_peak_fraction'] * 100:.1f}"
          f" % of full scale, giving up {adc['range_given_up_db']:.1f} dB")
    print(f"  loading error        {adc['load_error'] * 100:>10.2f} %  "
          f"(Z_IN {adc['z_in'] / 1e3:.0f} kohm at this AMCLK; common to all "
          f"six, so a law error)")
    print(f"  anti-alias           {adc['corner_hz'] / 1e3:>10.1f} kHz  "
          f"({adc['droop_db']:+.3f} dB at the top string's ripple, "
          f"{20 * math.log10(clk['dmclk'] / adc['corner_hz']):.0f} dB at "
          f"DMCLK)")
    print(f"  six channels at {ENV_SAMPLE_HZ / 1e3:.0f} kHz need a master "
          f"clock, and the part's own RC cannot make it:")
    for osr, row in sorted(clk["rows"].items()):
        print(f"    OSR {osr:>4}  {row['bits']:>2} bits  MCLK >= "
              f"{row['mclk_min'] / 1e6:>6.3f} MHz  "
              f"{'' if row['fits'] else '(over the 20 MHz limit)':<24}"
              f"  internal RC gives "
              f"{row['internal_rate_low']:>4.0f}-{row['internal_rate_high']:.0f} Hz"
              f"{'   <- fitted' if osr == clk['osr'] else ''}")
    print(f"  -> internal oscillator is {clk['internal_short_db']:.1f} dB "
          f"short at its best setting, so MCLK is external and crosses the "
          f"boundary. That is the multiplexer's bill")
    ref = envelope_adc_reference()
    print(f"  REFIN+ decoupling    {ref['local_farads'] * 1e9:>10.0f} nF  "
          f"and not the 10 uF its datasheet suggests: VREF already carries "
          f"{ref['existing_bulk'] * 1e6:.1f} uF against a "
          f"{ref['ceiling_farads'] * 1e6:.0f} uF ceiling")
    print(f"  -> the reference input current is unspecified; it would have to "
          f"reach {ref['current_to_move_100uv_ma']:.1f} mA to move VREF by "
          f"100 uV, against {ref['logic_load_ma'] * 1e3:.0f} uA for the whole "
          f"'541")
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
    g = clamp_gain()
    print(f"  the last row is the only loud one, and D803 is the answer: "
          f"{g['unclamped_db']:+.0f} dB -> {g['clamped_db']:+.1f} dB")
    print(f"  against {g['headroom_db']:.2f} dB of headroom at the mixer's "
          f"summer: fits = {g['fits']}")
    print()

    print("the fail-safe -- de-energised is bypass")
    t = pump_timing()
    c = coil_budget()
    b = bypass_state()
    print(f"  pump source impedance {t['r_eq'] / 1e3:>6.1f} k   "
          f"(1 / f.C at {PUMP_HZ / 1e3:.0f} kHz)")
    print(f"  gate reaches          {t['v_final']:>6.2f} V   against a "
          f"{FET_VGSTH_MAX:.1f} V threshold requirement, "
          f"{t['margin_v']:+.2f} V of margin")
    print(f"  comes into circuit at {t['t_on'] * 1e3:>6.1f} ms  "
          f"(VREF needs {t['needs'] * 1e3:.0f} ms: "
          f"{'holds' if t['interlock'] else 'FAILS'})")
    print(f"  drops to bypass in    {t['t_off'] * 1e3:>6.1f} ms  "
          f"+ {t['transfer_s'] * 1e3:.0f} ms of transfer, after any stuck "
          f"MCU state")
    print(f"  bypass presents       {b['parallel']:>6.0f} ohm  "
          f"= the pot at full rotation ({b['pot_wide_open']:.0f}), so the "
          f"mixer has seen it: {b['matches']}")
    print(f"  coils cost            {c['low_ma']:>3.0f}-{c['high_ma']:.0f} mA  "
          f"continuous on {c['rail']}, against {c['rest_ma']:.0f} mA for every "
          f"amplifier and VCA ({c['ratio']:.1f}x)")
    print()

    supply = supply_requirement()
    print("the supply -- what the rails have to deliver")
    for name, rail in supply["load"].items():
        print(f"  {name:<4} {rail['volts']:>+6.1f} V   "
              f"typ {rail['typ_ma']:>5.1f} mA   max {rail['max_ma']:>5.1f} mA   "
              f"({len(rail['parts'])} parts, counted off the netlist)")
    print(f"  isolated, >= {supply['min_khz']:.0f} kHz, "
          f"{supply['watts_max']:.2f} W at maximum")
    print(f"  supply-decision.md estimated {supply['doc_estimate_ma']:.0f} mA "
          f"per bipolar rail and the board draws "
          f"{supply['load']['VA+']['max_ma']:.0f}: see supply_requirement()")
    print()

    fit = supply_fit()
    beat = supply_beat()
    rails = rail_filter()
    barrier = barrier_return()
    regulator = v5_regulator()
    inlet = inlet_budget()
    print(f"the converter -- {SUPPLY_MPN}, isolated, "
          f"{SUPPLY_KHZ[0]:.0f}-{SUPPLY_KHZ[1]:.0f} kHz PWM flyback")
    print(f"  +Vout                {fit['positive_ma']:>7.1f} mA of "
          f"{fit['limit_ma']:.0f}   (board, plus V5 made linearly from it)")
    print(f"  -Vout                {fit['negative_ma']:>7.1f} mA of "
          f"{fit['limit_ma']:.0f}")
    print(f"  delivered            {fit['watts']:>7.2f} W of "
          f"{fit['watts_limit']:.0f}, against "
          f"{fit['rail_power_sum']:.2f} W if the rail powers are summed -- "
          f"see supply_fit()")
    print(f"  the >= {SUPPLY_MIN_KHZ:.0f} kHz rule holds at the fundamental "
          f"({beat['fundamental_beat_khz']:.0f} kHz away) and the nearest "
          f"beat is {beat['worst_beat_khz']:.0f} kHz, against the pump's "
          f"{beat['worst_order']}th")
    print(f"  rail filter          {rails['attenuation_db']:>7.1f} dB at "
          f"{SUPPLY_KHZ[0]:.0f} kHz: {SUPPLY_RIPPLE_VPP * 1e3:.0f} mVpp "
          f"becomes {rails['residual_vpp'] * 1e6:.0f} uVpp, "
          f"{rails['am']['am_db']:.1f} dB of AM at PSRR = 0 dB")
    print(f"  the LC of that corner would ring at Q = {rails['lc_q']:.0f}, "
          f"which is {rails['lc_peak_db']:.0f} dB at "
          f"{rails['corner_hz'] / 1e3:.1f} kHz -- hence a resistor")
    print(f"  barrier              {barrier['barrier_ma'] * 1e3:>7.0f} uA "
          f"through {SUPPLY_ISO_PF * 1e12:.0f} pF, and the bond carries "
          f"{barrier['bond_v'] * 1e6:.2f} uV of it")
    print(f"    {barrier['bond_v_unfitted'] * 1e3:.2f} mV bare, "
          f"{barrier['bond_v_no_choke'] * 1e3:.2f} mV with C810 alone, "
          f"{barrier['bond_v'] * 1e6:.2f} uV with L801 -- "
          f"{barrier['floor_db']:+.0f} dB against the mixer's noise floor, "
          f"{barrier['floor_db_low_l']:+.0f} at the choke's -50 %")
    print(f"    Z_Y {barrier['z_y']:.2f} ohm against Z_bond "
          f"{barrier['z_bond']:.2f} and Z_choke "
          f"{barrier['z_choke'] / 1e3:.2f} kohm: the capacitor divides the "
          f"first, the choke multiplies the second")
    print(f"  the inlet choke      {inlet['choke_drop_v'] * 1e3:>7.0f} mV of "
          f"DC drop at {inlet['worst_ma']:.0f} mA, "
          f"{inlet['choke_margin']:.1f}x inside its rating; the converter "
          f"sees {inlet['converter_vin_low']:.1f} V of its 9 V minimum")
    print(f"  V5 regulator         {regulator['watts']:>7.2f} W: "
          + ", ".join(f"{name} {rise:.0f} C rise"
                      for name, rise in sorted(regulator['rises'].items()))
          + f" against Tj {regulator['tj_max']:.0f} at {AMBIENT_C:.0f} ambient")
    print(f"  the brick            {inlet['total_ma']:>7.0f} mA now, and the "
          f"mixer's own string says \"{inlet['mixer_range']}\"")
    print()

    print("assumptions still open here")
    for name, assumption in sorted(MEASURED.items()):
        print(f"  {name:<16} {assumption!r}")


if __name__ == "__main__":
    _report()
