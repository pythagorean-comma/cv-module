"""The floorplan: zones, the two ground domains, and what crosses between them.

A floorplan for this module is not mostly about where parts fit. It is about
which current each part's return belongs to, because one of them is three times
the other and it switches:

    audio          ~35 uA per channel at the summing node
    CV switching  ~114 uA per channel through the '541 at 30.5 kHz

**There was a third and it was two orders larger.** Twelve relay coils at
~40 mA for 3-10 ms, which were the reason this file's largest zone straddled
the boundary. design.pad_benefit() struck the pad that needed them, and that
takes 36 parts, 1566 mm2 of courtyard and the only milliamps on the board out
of the plan at once. What is left is two microamp currents and a boundary with
nothing inductive across it. pad_area() is where the millimetres are.

So this file is a placement *contract* rather than a drawing: zones, the
adjacency each one requires and why, the ground star, and an explicit list of
every net allowed to cross the analogue/digital boundary. The list is checked
against the netlist, which is the only part of a floorplan a script can hold --
and it is the part that would otherwise be discovered by a hum.

`python3 floorplan.py` prints it and writes `docs/floorplan.md`.

**The outline is not here, and cannot be.** See BLOCKED at the bottom: the
module does not fit the mixer's enclosure, and `comma-enclosure` is not
available in this session. What is derived instead is a minimum area from the
part inventory, which is a lower bound on any answer.
"""

import math
import pathlib

import design
import contract.socket as socket

DOCS = pathlib.Path(__file__).resolve().parent / "docs"


# ---------------------------------------------------------------------------
# The two domains, and the star
# ---------------------------------------------------------------------------

ANALOGUE, DIGITAL = "MAGND", "MDGND"
# The third domain, and it is not a third ground in the sense the other two
# are. MAGND and MDGND meet at R902; IGND meets neither, ever, and that is the
# whole of what isolation buys. A part on this domain returns to the inlet's
# own 0 V, which through the shared barrel jack is the mixer's PGND -- so the
# module touches that node here and nowhere else, and the one bond of
# constraint 5.2 stays one.
ISOLATED = "IGND"
# U15 and C810 are the two parts with pins on both sides of the barrier, and
# they are not STRADDLE: a straddler bridges two grounds that are already
# joined at a star, and these bridge two that are not joined at all. The
# distinction earns its own word because check_isolation() below has to treat
# them differently -- a straddler is excluded from a crossing test, and these
# are the *only* things allowed to cross this one.
BARRIER = "BARRIER"
# **The fourth domain, and this board has it because MIDI is a current loop.**
# The far side of U21's LED belongs to whatever is transmitting: CA-033 puts a
# 5 mA loop between two devices and requires that the receiver break it --
# "the transmitter circuitry and receiver circuitry are internally separated
# by an opto-isolator", and "Pin 2 of the MIDI In connector shall not have any
# DC path to the receiver's ground". So J15, its loop resistor and the
# protection diode return to a ground this module never touches, exactly as
# the inlet's primary does.
#
# It is a second isolation barrier and this file used to say "the" barrier in
# three places. U21 is its U15 and C836 is its C810 -- the declared bridge,
# there for the same reason and with the same shape of argument: without it
# the shield has no RF path at all, and with a DC path instead of a capacitor
# the isolation would be gone.
MIDI_LOOP = "MIDIGND"

# The two barriers, each with the parts allowed to cross it. Read by
# check_isolation(), which is one test run twice.
BARRIERS = (
    (ISOLATED, design.ISOLATION_BRIDGE, "the isolated primary"),
    (MIDI_LOOP, design.MIDI_BRIDGE, "the MIDI transmitter's own ground"),
)

GROUND_STRATEGY = """
Three stars, and only the first is a rule this module inherits.

**R901: MAGND to the mixer's AGND. Exactly one, and it is constraint 2.**
A dedicated conductor from the module's audio ground to the mixer's own
designated AGND pad, TP6 -- whose comment upstream calls it "the *only* correct
one, given the ground rule". The six shields land at the same node and at no
other, which is the whole of what makes the bond count one: a shield is
terminated at the main-board end and cut back here, so nothing in the loom
carries a second path between the two grounds.

**Two sentences here were stale and are corrected.** They said "RET{n} reaches
MAGND only through R{n}03 + R{n}04, which is 20 kohm and carries nanoamps, and
verify.py asserts that impedance". There is no RET{n} and there are no R{n}03 or
R{n}04 -- they were the difference amplifier's sense pair, struck with
constraint 2's second sentence (see design.FRONT_R), and verify.py has never
asserted an impedance. A description of a topology that no longer exists reads
exactly like one that does.

**R902: MAGND to MDGND, inside the module.** The module's own analogue/digital
join, and not a bond to anything of the mixer's. Everything that switches for
its own reasons -- the controller, the fail-safe pump, the DC-DC's secondary --
returns here and nowhere else. The relay drivers were on that list and are not
any more.

**The star point of MAGND is the SSI2164 ground pins, and that is derived.**
This is the part of the strategy that is not obvious and not optional.

The control port is *ground-referenced*: V_C is measured against the chip's own
pin 8. So the CV filter's output reference, the '541's ground and the VCA's
ground pin all have to be the same node, or the difference between them appears
in series with the control voltage and is multiplied into AM at 3.488 per volt.
One millivolt of it is AM 51 dB below the signal, against the reference's own
91.7 dB -- so a ground-domain mistake here is worth forty decibels and looks
like nothing in a netlist, because both nets are called ground.

That fixes where the star is. The audio return current and the CV switching
return current both have to arrive at the VCA's ground pin, so they meet there
and nowhere earlier -- two branches, not one pour crossing the CV block on its
way to the front ends. R903 is that branch point, and pin 8 of U9 and U10 is
where it physically is.

**Two grounds is enough; three would be a mistake.** A separate CVGND that met
MAGND at a resistor was drawn and rejected: it would put the CV filter's
reference on a different node from the VCA's ground pin, which is precisely the
fault above with the offset moved somewhere harder to see.
"""

# Which ground domain each part's return belongs to, by reference pattern. Any
# part not matched is an error rather than a default, because "which ground"
# is the question this file exists to answer and a default answers it silently.
DOMAINS = (
    (r"^J[1-6]$", ANALOGUE, "loom to the mixer: audio in, audio out"),
    (r"^J7$", ANALOGUE, "the ground bond pad and the shield terminations"),
    # **J8 has been all three things this table can say, and each move was a
    # correction.** It was DIGITAL because it is a header and the other three
    # headers are; it became STRADDLE when somebody noticed it carried both
    # rails and both grounds, which had put its MAGND pin's barrel 18 mm
    # inside the digital pour with no analogue plane under it on any layer.
    # It is ISOLATED now, because the converter came onto the board and J8 is
    # the raw inlet: two pins, neither of them referenced to anything this
    # module calls ground. See design.supply().
    (r"^J8$", ISOLATED, "the shared DC inlet, primary side"),
    (r"^L801$", ISOLATED, "the common-mode choke in the inlet pair -- the "
                         "second half of design.barrier_return()"),
    (r"^D804$", ISOLATED, "inlet reverse protection"),
    (r"^C80[789]$", ISOLATED, "primary decoupling, at the converter's pins"),
    (r"^U15$", BARRIER, "the isolated converter: pins 1-3 primary, 6-8 "
                        "secondary, 5.08 mm of package between them"),
    (r"^C810$", BARRIER, "the Y-capacitor -- the *only* other thing across "
                         "the barrier, and it is there so the barrier's own "
                         "common-mode current does not use the audio bond"),
    (r"^U16$", DIGITAL, "the 5 V regulator"),
    (r"^R80[45]$", DIGITAL, "rail filters -- their capacitors return to "
                            "MDGND, not MAGND, because this is switching "
                            "return current"),
    (r"^C81[1234]$", DIGITAL, "rail filter and regulator capacitors"),
    # J9-J13 were five rows here, the headers out to a deferred controller.
    # The controller is on the board and its parts are below.
    (r"^R[1-6]0[12]$", ANALOGUE, "front-end inverting stage"),
    (r"^R[1-6]1[15]$", ANALOGUE, "R_IN and the VCA input RC"),
    (r"^R[1-6]5[1-5]$", ANALOGUE, "envelope rectifier, both stages"),
    (r"^R[1-6]5[67]$", ANALOGUE, "the ADC input divider -- see "
                                 "design.envelope_adc_input()"),
    (r"^C[1-6]52$", ANALOGUE, "the ADC input anti-alias"),
    (r"^U17$", ANALOGUE, "the envelope ADC: AGND and DGND both on MAGND, "
                         "which is DS20006181C section 7.3's second scheme"),
    (r"^U18$", ANALOGUE, "the 3.3 V regulator for the ADC, off V5"),
    (r"^C81[5-9]$", ANALOGUE, "the ADC's rail and reference decoupling"),
    # -- the controller, zone D2 ------------------------------------------
    (r"^U19$", DIGITAL, "the RP2040 -- its exposed pad is the MDGND star for "
                        "this zone"),
    (r"^U20$", DIGITAL, "the QSPI flash, at the package"),
    (r"^U22$", DIGITAL, "the 3.3 V switcher: its input is VA_RAW and its "
                        "return is MDGND, which is where a pulse train "
                        "belongs"),
    (r"^Y801$", DIGITAL, "the 12 MHz crystal, case pins to MDGND"),
    (r"^L802$", DIGITAL, "the switcher's inductor"),
    # C836 is out of this range for R827's reason: it is the MIDI barrier's
    # own bridge and belongs to BARRIER, below.
    (r"^C82\d$|^C83[0-57-9]$", DIGITAL, "controller decoupling, the "
                                         "crystal's load capacitors and the "
                                         "panel's RC"),
    (r"^C84[0-3]$", DIGITAL, "the switcher's input, bootstrap and output"),
    # R827 is deliberately not in this range: it is the MIDI loop's own
    # resistor and it returns to the sending device's ground, not to MDGND.
    # Written as two ranges rather than one because a domain table whose
    # patterns are tidier than the board is a domain table that will be wrong.
    (r"^R82[0-6]$|^R82[89]$", DIGITAL, "USB termination, the VBUS divider, "
                                       "the crystal drive resistor, RUN, "
                                       "BOOTSEL and the MIDI OUT pair"),
    (r"^R83[0-3]$", DIGITAL, "the tap and expression networks"),
    (r"^R85[01]$", DIGITAL, "the switcher's feedback divider"),
    (r"^J14$", DIGITAL, "USB, board-mounted -- see design.USB_CONN_REF"),
    (r"^J16$|^J17$|^J18$|^J19$|^J20$", DIGITAL, "MIDI out, the panel jacks, "
                                                "the boot header and SWD"),
    # -- and the second barrier -------------------------------------------
    (r"^U21$", BARRIER, "the MIDI opto: pins 1 and 3 belong to the sending "
                        "device, 4 to 6 to this board. 5000 Vrms and 0.4 pF "
                        "between them"),
    (r"^C836$", BARRIER, "the MIDI IN shield capacitor -- the declared bridge "
                         "across that barrier, and CA-033 requires it to be a "
                         "capacitor rather than a wire"),
    (r"^J15$", MIDI_LOOP, "the MIDI IN jack: DIN pins 4 and 5 are the "
                          "transmitter's current loop"),
    (r"^R827$", MIDI_LOOP, "the loop's series resistor -- see "
                           "design.midi_loop()"),
    (r"^D805$", MIDI_LOOP, "reverse protection across the opto's LED"),
    (r"^D[1-6]5[12]$", ANALOGUE, "envelope rectifier diodes -- inside A1's "
                                 "loop"),
    (r"^C[1-6]51$", ANALOGUE, "envelope one-pole, 4.7 ms"),
    (r"^K80[1-3]$", "STRADDLE", "bypass relays: contacts audio, coil digital"),
    (r"^Q801$", DIGITAL, "the fail-safe's sink"),
    (r"^D80[12]$", DIGITAL, "the fail-safe's charge pump"),
    (r"^D803$", ANALOGUE, "the inverted reference's clamp"),
    (r"^D8[123]3$", DIGITAL, "coil flyback diodes"),
    (r"^C80[56]$", DIGITAL, "the fail-safe's pump and hold capacitors"),
    (r"^R803$", DIGITAL, "the fail-safe's bleed -- its time constant"),
    (r"^R[1-6]2[12]$", ANALOGUE, "I-V"),
    (r"^R[1-6]3[12]$", ANALOGUE, "DC servo"),
    (r"^R[1-6]4[1-4]$", ANALOGUE, "CV filter -- referenced to the VCA's GND"),
    (r"^C[1-6]0[12]$", ANALOGUE, "VCA input block and stability RC"),
    (r"^C[1-6]21$", ANALOGUE, "I-V compensation"),
    (r"^C[1-6]31$", ANALOGUE, "servo integrator"),
    (r"^C[1-6]4[12]$", ANALOGUE, "CV filter poles"),
    (r"^U[1-8]$", ANALOGUE, "quad op-amps"),
    (r"^U1[34]$", ANALOGUE, "the envelope half-wave stages -- their outputs "
                            "slew across two diode drops at every zero "
                            "crossing, which is why they are not on U1-U8"),
    (r"^U9$|^U10$", ANALOGUE, "the VCAs -- and the MAGND star point is pin 8"),
    (r"^U11$", "STRADDLE", "the '541: Vcc = VREF, GND = MAGND, inputs from "
                           "the digital side"),
    (r"^U12$", ANALOGUE, "the reference"),
    (r"^R80[12]$", ANALOGUE, "reference inverter"),
    (r"^R81[1-6]$", DIGITAL, "PWM pull-downs, at the controller connector"),
    (r"^C80[1-4]$", ANALOGUE, "reference and '541 decoupling"),
    (r"^C7\d\d$", ANALOGUE, "op-amp and VCA rail decoupling"),
    (r"^R90[123]$", "STRADDLE", "the ground stars themselves"),
)

# Every net allowed to carry signal between the two domains, with what bounds
# the damage. Anything else that crosses is a fault, and check_crossings()
# below is what finds it.
#
# The declaration is the mixer's DIODE_DIRECTION move: a property that
# connectivity cannot express, written down so it can be asserted.
CROSSINGS = {
    "PWM1": "logic input to the '541, threshold-limited",
    "PWM2": "logic input to the '541, threshold-limited",
    "PWM3": "logic input to the '541, threshold-limited",
    "PWM4": "logic input to the '541, threshold-limited",
    "PWM5": "logic input to the '541, threshold-limited",
    "PWM6": "logic input to the '541, threshold-limited",
    "OE": "output enable, static in normal operation",
    # The envelope ADC's six, and they are six rather than the four this file
    # used to promise. See CROSSING_RULE.
    "SCLK": "SPI clock into the ADC, V3V3 logic",
    "MOSI": "SPI data into the ADC, V3V3 logic",
    "MISO": "SPI data *out* of the analogue domain, V3V3 logic",
    "CS": "chip select into the ADC, static between transfers",
    "MCLK": "the ADC's master clock, into the analogue domain -- "
            "design.envelope_adc_clock() is why it cannot come from inside "
            "the part",
    "IRQ": "data-ready *out* of the analogue domain, V3V3 logic",
    "VA+": "audio rail, from the converter through R804",
    "VA-": "audio rail, from the converter through R805",
    "V5": "reference supply, from the converter through U16",
    ANALOGUE: "the star itself, at R902",
    DIGITAL: "the star itself, at R902",
}

CROSSING_RULE = """
Thirteen signals and three rails cross, and every one of the thirteen is
**logic** -- which is not the same claim this section used to make.

A logic input tolerates about 1.5 V of ground offset before its threshold is in
doubt -- 3.3 V of drive against the '541's 1.75 V VIH at Vcc = 2.5 V. A
precision output tolerates about 0.1 mV before its error is audible. That is
the mechanism and it is unchanged.

**What was wrong was the criterion stated over it.** This read "every crossing
here is an *input* to the analogue domain", which was true of the seven that
existed and is not the property the mechanism is about. A logic signal
tolerates a ground offset in either direction; what makes a crossing cheap is
its *level*, not its heading. The two were the same thing only while the
crossings happened to be one-way, and the paragraph immediately below already
promised the block that would break it: the envelope ADC has to return data,
so MISO and IRQ leave the analogue domain. They are as cheap as the six that
enter, and the '541 is still the part that converts one kind to the other:
digital in on one row, precision analogue out on the other, which is the
package TI built and said so.

The failure is small and worth naming because it is this repo's usual one at
one remove: a rule whose *stated test* was narrower than its *stated
mechanism*, so satisfying the mechanism could look like violating the rule.
The check reads CROSSINGS and not this prose, so nothing would have failed --
the wrong sentence would simply have gone on being quoted.

What deliberately does not cross:

  * **the six '541 outputs.** LOGO{n} is a 30.5 kHz square wave at 2.5 V and it
    is entirely inside the analogue domain, from the '541's Y pins to R{n}41. It
    is the loudest aggressor on the board and the shortest run on it.
  * **the six ENV{n}.** Spec section 4.4 puts the envelope ADC in the analogue
    section so that SPI crosses instead of six analogue traces, and that is
    what happened: ENV{n} stops at R{n}56 and never leaves the domain. The
    ADC's own reference is VREF and its ground is MAGND, exactly as this
    section said it would be before the part was chosen -- and only one of the
    two candidates could honour it, because the ADS131M08's reference input
    stops at 1.3 V. See design.ENV_ADC.
  * **audio.** Nothing audio-carrying crosses at all. That is what makes the
    boundary a line rather than a suggestion.

**The SPI is six signals and this section promised four.** "Only
SCLK/MOSI/MISO/CS" is spec section 4.4's own list and it is short by two: the
part needs a data-ready line, and -- because it multiplexes one modulator
across six channels rather than converting them at once -- a master clock its
internal RC oscillator cannot make to tolerance. design.envelope_adc_clock()
is that arithmetic. Both additions are logic, so both are cheap by the rule
above; what they cost is two more conductors in the loom and one of them is a
9.2 MHz clock, which is the reason MCLK sits between two grounds on J13.

**The relay coils were the exception that proved the shape, and they are gone.**
Twelve coils, each about 40 mA for 3 to 10 ms, driven from the digital domain
into parts whose contacts sat in the audio path: K{n}0x straddled exactly as
the '541 does, coil return on MDGND and contacts carrying audio. Spec section
4.5 calls the failure they bring -- a shift register holding a coil energised
until it burns -- "the highest-probability field failure in the design", and
bounds it with a one-shot.

With the pad struck, the only part that straddled was the '541 -- and **the
bypass relays have put three back**, which is worth being precise about because
they are not the pad's relays returning under another name.

The pad's coils were pulsed by a shift register that could hold one energised
until it burned, which is why section 4.5 wanted a one-shot around them. The
bypass coils are *continuously* energised by a MOSFET whose gate is a charge
pump, so there is no stuck-on failure to design against: the failure mode is
the coil dropping out, which is the safe state. What they cost instead is
current -- 75 to 120 mA on V5, held for as long as the module works, against
about 78 mA for every amplifier and VCA on the board. See design.coil_budget();
it is a requirement on the deferred supply and it belongs in this file because
the return path for it crosses at R902 like everything else digital.
"""


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------
# West to east, in signal order, on six 7.5 mm strips that line up with the
# mixer's own RV{n}01 column.

ZONES = (
    ("A0", "loom entry", ANALOGUE,
     "Six triads and the bond, on the west edge at the mixer's own 7.5 mm "
     "pitch so the six runs are parallel and equal-length with nothing "
     "crossing. The bond pad J7 sits at the centre of the column, where the "
     "six shields can land together.",
     "Aligned with RV101-RV601: x = 37.0, y = 6.0 to 43.5 on the mixer."),

    ("A1", "front ends", ANALOGUE,
     "Six difference amplifiers, U1-U2. The highest-impedance and quietest "
     "nodes on the board: R{n}01 into a virtual earth is the socket contract, "
     "and FEN{n} is a summing junction that verify.py refuses to let anything "
     "else touch.",
     "Immediately east of A0 -- every millimetre here is on an unshielded "
     "high-impedance node."),

    ("A2", "coupling and R_IN", ANALOGUE,
     "Six 10 uF control-feedthrough blocks, six R_IN and the six stability "
     "RCs. **This was the pad zone** -- twelve latching relays and twenty-four "
     "resistors, the largest zone on the board by area and the only one with "
     "milliamps in it -- and it is now the smallest analogue zone and entirely "
     "microamps. See design.pad_benefit().",
     "Between A1 and A3, with C{n}02's return to the A3 star rather than to "
     "its own local ground: the 220R/1200pF is the cell's stability network "
     "and its ground is the cell's."),

    ("A3", "VCAs", ANALOGUE,
     "U9 and U10, three channels each. **The MAGND star point is pin 8 of "
     "these two packages** -- see GROUND_STRATEGY. Their 100 nF decoupling "
     "sits at the package, per datasheet page 3.",
     "Centre of the board, each package centred on its own group of three "
     "strips so the six VC{n} and IOUT{n} runs are short and symmetric. The "
     "two packages must be adjacent and at the same temperature, or the "
     "-3300 ppm/degC drift stops being common-mode -- see tempco_span()."),

    ("A4", "I-V and servo", ANALOGUE,
     "U3-U6. Outputs are SIN{n} and go straight back to A0, on an inner layer "
     "under the pour rather than back across A1.",
     "East of A3, with the SIN{n} return routed south of A1 rather than "
     "through it."),

    ("A5", "envelope detectors", ANALOGUE,
     "Twelve amplifier sections, twelve diodes, thirty resistors and six "
     "capacitors. **Split across two part types on purpose**: the half-wave "
     "stages are on U13-U14, whose outputs slew across two diode drops at "
     "every zero crossing, and the summing stages are on the six sections "
     "U2/U4/U6 C and D -- which sit in A1, A4 and A4 respectively, because a "
     "quad package is one placement and those packages' other sections are "
     "front ends, I-V and servos. See design.ENV_OPAMP.",
     "East of A4, with U13-U14 as far from A1 as the board allows. The "
     "consequence of the split is a long run from HW{n} back to whichever "
     "package holds that channel's summing stage, and it is tolerable for a "
     "computable reason: ENVN{n} is a virtual earth whose feedback capacitor "
     "is 470 nF, so a few picofarads of stray on it is 1e-5 of the pole. The "
     "same run on the CV filter's own summing node would not be."),

    ("A6", "the envelope ADC and its rail", ANALOGUE,
     "U17, the six input dividers and their anti-alias capacitors, U18's "
     "3.3 V rail and the ADC's own decoupling. **Analogue, entirely** -- AGND "
     "and DGND are both MAGND, which is the second of the two schemes "
     "DS20006181C section 7.3 offers and the only one compatible with this "
     "board having exactly one analogue/digital star. What leaves the domain "
     "is six logic signals, and they leave at J12/J13 rather than here.",
     "South of A5 in the shared band, north of the split so that every pad on "
     "U17 stitches into its own pour, and east of the rail decoupling. The "
     "dividers sit between the CV band's ENV{n} column and the package, so "
     "the long run is ENV{n} -- which is a driven op-amp output -- and the "
     "short one is ENVA{n}, which is a 4 kohm source into a switched "
     "capacitor."),

    ("F", "the fail-safe", "STRADDLE",
     "Three bypass relays, the charge pump, the sink and the flyback diodes, "
     "plus D803 on the inverted reference. **The relays straddle** -- coils "
     "on MDGND, contacts carrying six channels of audio -- and they are the "
     "only parts on this board that switch anything in the audio path.",
     "Between A0 and D2: the contacts have to reach the loom, and the coils "
     "have to reach the digital domain, so the block sits on the boundary "
     "with its contact side facing west. D803 is the exception and belongs "
     "in R, at the reference inverter's own output pin, because what it "
     "clamps is that amplifier and a long run would clamp the trace instead."),

    ("C1", "CV filters", ANALOGUE,
     "U7-U8 and the six MFB stages. Referenced to the VCA ground pins, which "
     "is why this zone's ground branch meets MAGND at A3 and not on its own.",
     "South of A3, so VC{n} is short and the LOGO{n} runs from D1 are "
     "shorter still."),

    ("R", "reference", ANALOGUE,
     "U12, its NR capacitor, the reservoir, and the inverter section in U8. "
     "Its noise is common to all six channels, which 00-current-state.md "
     "identifies as the most perceptible kind.",
     "Between C1 and D1, adjacent to the '541 it has to supply. See "
     "REFERENCE_PLACEMENT -- this is the one placement the brief asks about "
     "by name."),

    ("D1", "logic buffer", "STRADDLE",
     "U11 alone. The boundary runs through this package: inputs on the north "
     "row from the digital side, outputs on the south row into C1, GND on "
     "MAGND.",
     "On the boundary line, rotated so its A-side faces D2 and its Y-side "
     "faces C1. Note A_n is pin n+1 and Y_n is pin 19-n, so the channel order "
     "reverses across the package -- A1 and Y1 are diagonally opposite."),

    ("D2", "the controller", DIGITAL,
     "U19 and everything it needs: the QSPI flash at the package, the 12 MHz "
     "crystal, USB, DIN MIDI in and out, the panel's two jacks, the boot and "
     "debug headers, twelve decoupling capacitors and U22's 3.3 V switcher. "
     "**Two things in here are not MDGND parts.** U21 and C836 are the MIDI "
     "barrier and J15/R827/D805 sit on the far side of it, on the sending "
     "device's ground -- the same relationship zone P has with the inlet. "
     "And U22's input is VA_RAW, which arrives from P rather than from "
     "anything in this zone.\n\n"
     "**This entry used to place the envelope ADC here**, 'analogue and at "
     "the D2/A4 edge', which put an analogue part inside a zone whose "
     "declared domain is MDGND -- a contradiction check_zones() could not "
     "see, because it only walks per-channel columns. The ADC has its own "
     "zone A6 now and it is north of the split. The 2 x TPIC6B595 and the "
     "74LVC1G123 this entry also named went with the coarse pad.",
     "South-east, one edge, with the star R902 at its corner nearest A3. "
     "Inside it, three placements are load-bearing rather than tidy: the "
     "flash against U19's QSPI row ('short connections to maintain the "
     "signal integrity'), the crystal and its two load capacitors against "
     "XIN/XOUT with the tracks kept short ('the parasitic capacitance of the "
     "PCB traces are a factor'), and U21's own bypass within 10 mm of its "
     "pins, which its datasheet states as a distance."),

    # **This zone was declared for four passes with nothing in it, and the
    # empty declaration was the only place in the repo that said the converter
    # is on this board.** design.py said the opposite -- J8 as a five-way
    # secondary inlet -- and nothing compared the two. See design.supply().
    ("P", "supply", "BARRIER",
     "The isolated converter U15 and the two rails made from it. **The only "
     "zone with two boundaries through it**: the ground split separates two "
     "returns that meet at R902, and the isolation barrier separates two that "
     "meet nowhere. West of ISOLATION_X is the primary -- the inlet, its "
     "protection and its decoupling, on IGND, with no ground pour under any "
     "of it; east is MDGND like the rest of the southern half. C810 is the "
     "one declared bridge and it is there so the barrier's own common-mode "
     "current does not use the audio bond. See design.barrier_return().",
     "The far corner from A1 and R, which is the south: a band below "
     "everything else, so the one switching part on this module is as far "
     "from the front ends as the outline allows. |f - 45 kHz| > 20 kHz "
     "against the mixer's charge pump -- and see design.supply_beat(), "
     "because that rule is stated for the fundamental and the mechanism is "
     "not."),
)

REFERENCE_PLACEMENT = """
The brief asks where the reference sits relative to the six buffer transients,
and the answer changed once the arithmetic was done.

The worry is real in shape: the '541's Vcc *is* the reference, so every output
edge draws its charge from U12, and six edges arriving together would modulate
the one node whose noise is common to all six channels.

The size of it is small. Each output drives R{n}41's 22 kohm, so the steady
current is 2.5 V / 22 k = 114 uA per channel and 684 uA for six. The switching
component is the package's own 12 pF of C_pd plus the trace, at 30.5 kHz:
6 x 42 pF x 2.5 V x 30.5 kHz = about 19 uA. Against the MAX6126's 10 mA of
output current that is a factor of fourteen on the steady term and five hundred
on the transient.

So the placement rules are ordinary rather than delicate, and they are all
local:

  * **C803, 100 nF, at the '541's own Vcc pin.** This is what supplies the
    edges; the reference supplies the average. It is also where the Kelvin sense
    pair closes, because Vcc is the point where the voltage accuracy is needed.
  * **C802, 10 uF, at OUTF.** The output capacitor the datasheet requires,
    "as close to OUTF as possible" -- a loop-stability part, so what matters is
    its inductance to the pin.
  * **C801, the 0.1 uF NR capacitor, at U12.** Not decoupling: it is what takes
    the part from 75 to 45 nV/rtHz, and it is on a high-impedance internal node
    so it goes at the pin and nowhere else. It also costs 20 ms of turn-on
    settling, which is the fail-safe's business rather than the floorplan's --
    see design.VREF_TURN_ON_S.

~~**C804, 10 uF, between the reference and the '541.** The reservoir the steady
684 uA comes out of, so U12's own loop never sees the load step when six channels
change duty at the 8 kHz frame rate.~~ **Struck, and the part is deleted.** Two
things wrong with it, and the second is why it is worth striking rather than
quietly shrinking.

It broke a limit. With C802 also fitted, VREF carried 20.1 uF against the
MAX6126's 0.1-10 uF capacitive-load stability range -- a range qualified "no
sustained oscillations", on the node that is every channel's full scale.

And **the mechanism in that clause runs the other way.** A load step divides
between the reservoir and the part's own output impedance in inverse proportion
to impedance. At 8 kHz a 10 uF is 1.99 ohm and the MAX6126's load regulation is
0.028 ohm, so the reservoir supplied 1.4% of the step and *the loop supplied the
rest*: it cannot be shielded from a load step by a capacitor eighty times its own
impedance, and 10 uF only becomes the stiffer element above 568 kHz. Nor did the
step need shielding -- 682 uA x 0.028 ohm is 19 uV, which the CV filter puts
59.9 dB down, so -143 dB of AM against a -54 dB requirement.

The same shape as the struck constraint in CLAUDE.md: a clause with a plausible
mechanism, satisfied by a fitted part, never checked for whether the mechanism
was reachable. `design.reference_load()` carries the arithmetic and
`verify.check_reference_load()` now holds the range against KiCad's own netlist.
  * **U12 between C1 and D1**, so the reference reaches the '541 and the six
    CV filters' offset resistors without either run crossing the audio zones.
  * **Phase-stagger the six PWM slices in firmware**, per spec section 4.2. It
    divides the transient by six for free and it is the one mitigation here
    that costs nothing at all.

What the arithmetic does *not* excuse is the return path. The 684 uA switches
at 30.5 kHz and returns through the '541's GND pin into MAGND -- which is
twenty times the audio current in the same ground. That is why the CV zone's
ground branch meets MAGND at the VCA ground pins rather than running across
the board to the front ends, and it is the whole reason GROUND_STRATEGY has a
third star in it.
"""


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def domain_of(ref):
    """Which ground domain a part's return belongs to."""
    import re
    for pattern, domain, _ in DOMAINS:
        if re.match(pattern, ref):
            return domain
    return None


def check_domains():
    """Every part is assigned to a domain, explicitly.

    An unassigned part is not given a default, because "which ground does this
    return to" is the question this file exists to answer and defaulting
    answers it silently -- which is how a decoupling capacitor ends up grounded
    to whatever was closest. The mixer's check_ground_star() catches that
    upstream by naming its POWER_SECTION; this is the same move with two
    domains instead of one.
    """
    return [f"{ref} has no domain in DOMAINS -- say which ground it returns to"
            for ref in sorted(design.PARTS) if domain_of(ref) is None]


def check_isolation():
    """No net touches both sides of the isolation barrier.

    The netlist half of constraint 5.2's strongest form. A ground *star* is a
    topology -- one bridge, and check_crossings() above is happy for declared
    signals to pass it because the two grounds are joined anyway. A barrier is
    not: nothing crosses, and the two parts that do are the converter, whose
    package is the barrier, and C810, which is there on purpose.

    So this is deliberately not a CROSSINGS-style allow-list of nets. It is an
    allow-list of *parts*, because a net that reaches from IGND to MDGND is a
    fault whatever it is called, and the only way it can legitimately exist is
    through a component built to hold the two apart.

    **There are two barriers now and this function said "the" barrier.** The
    controller brought DIN MIDI, which is an opto-isolated current loop -- so
    U21 is a second U15 and C836 is a second C810, with the same rule and a
    different reason for it: the converter's barrier exists because a second
    ground bond would break constraint 5.2, and MIDI's exists because CA-033
    requires the receiver to break the loop. BARRIERS is the table; the check
    is the same test run twice, which is what it should have been when there
    was one.

    **The geometric half is deliberately not extended to the second barrier.**
    verify.check_isolation_gap() measures a region of the board because the
    converter's primary is a 20 V node switching at half a megahertz across
    50 pF, and what it is protecting is the audio ground bond.  U21's isolation
    is 5000 Vrms and 0.4 pF *inside its own package*, and what the board has to
    do is simply not join the two nets -- which is a netlist property and is
    what this function tests. Saying so here rather than leaving the asymmetry
    to be noticed.

    The geometric half is verify.check_isolation_gap(), which measures copper.
    Both are needed and neither implies the other: this one passes on a board
    where the two pours touch, and that one passes on a netlist where somebody
    has tied IGND to MDGND with a wire, because then they are one net and no
    gap is violated.
    """
    problems = []
    for isolated, bridge, what in BARRIERS:
        for name, entries in sorted(design.NETS.items()):
            refs = sorted({ref for ref, _ in entries})
            domains = {domain_of(ref) for ref in refs}
            if isolated not in domains:
                continue
            others = domains - {isolated, BARRIER}
            if others:
                problems.append(
                    f"{name} reaches {what} and {sorted(others)} through "
                    f"{sorted(refs)} -- the barrier is not a boundary signals "
                    f"cross, and only {sorted(bridge)} and the isolating part "
                    f"itself may touch both sides")
    return problems


def check_crossings():
    """No net crosses the boundary unless CROSSINGS says it may.

    The floorplan property that a netlist *can* hold, and the one worth
    holding: a net touching parts in both domains is a conductor between them,
    and every one of those is either a declared crossing or a path this module
    was designed not to have.

    Straddling parts are excluded from the test rather than assigned a side,
    because that is what they are: the '541 has pins in both domains by design
    -- inputs from the digital row, outputs and ground on the analogue one --
    and pretending otherwise would either flag it forever or hide a real
    crossing behind it. It is the only one left; the twelve relays were the
    others.
    """
    problems = []
    for name, entries in sorted(design.NETS.items()):
        domains = {domain_of(ref) for ref, _ in entries}
        domains.discard("STRADDLE")
        # BARRIER for the same reason and one boundary out: U15 has primary
        # pins and secondary pins by construction, and C810 is the declared
        # bridge. Excluding them here is what leaves check_isolation() below
        # as the only thing that says which nets may cross *that* line, and
        # the two tests must not stand in for one another -- an isolation
        # barrier is a stronger claim than a ground star and deserves its own
        # instrument rather than a share of this one.
        domains.discard(BARRIER)
        if len(domains) > 1 and name not in CROSSINGS:
            refs = sorted({ref for ref, _ in entries})
            problems.append(
                f"{name} spans {sorted(domains)} and is not in CROSSINGS "
                f"-- carried by {refs}")
    stale = sorted(set(CROSSINGS) - set(design.NETS))
    if stale:
        problems.append(
            f"CROSSINGS names {stale}, which are not nets -- a declaration "
            f"that describes nothing is a check that cannot fail")
    return problems


# ---------------------------------------------------------------------------
# Area, which is a lower bound and not an outline
# ---------------------------------------------------------------------------

# Courtyard area per footprint, mm^2, from the footprint names this design
# actually uses.
COURTYARD = {
    "R_0805": 3.0, "C_0805": 3.0, "C_1210": 10.0, "D_SOD-123": 4.0,
    "SOIC-14": 58.0, "SOIC-16": 66.0, "SOIC-20W": 145.0,
    "PinHeader_1x03": 21.0, "PinHeader_1x05": 34.0,
    "TestPoint": 6.0,
    # **These eight were missing and the miss was silent for four passes.**
    # _report() prints "parts with no courtyard estimate" and the list has
    # never been empty -- the relays, the VCAs' SOIC-20W under another name,
    # the SOT-523, the SOIC-8 -- so a new absence looked exactly like the
    # standing ones. area() simply skipped them, which means the minimum-area
    # figure this file has quoted since the first pass has always been an
    # underestimate of an unstated size. It is not load-bearing -- placement.py
    # computes the real outline and _report() prints both -- but a number that
    # omits a term is worse than a number that says it cannot be computed.
    "D_SOD-123F": 4.0, "SOT-523": 5.0, "SOT-23": 13.0, "SOIC-8": 40.0,
    "Relay_DPDT_Omron_G6S-2F": 164.0, "PinHeader_1x02": 22.0,
    "D_SMA": 25.0, "TO-252-2": 78.0,
    "TRACO_TMR-6-xxxxWI": 214.0,
    "L_CommonMode_Wuerth_WE-SL2": 66.0,
    "TSSOP-20": 55.0,
    # The controller block. The QFN's number is its 7 x 7 body plus a
    # courtyard; the rest are their own bodies.
    "QFN-56-1EP_7x7mm": 64.0, "SO-6L": 44.0, "SOIC-8_5.3x5.3mm": 34.0,
    "SOT-23-6": 13.0, "Crystal_SMD_3225": 10.0, "L_Bourns_SRN6045TA": 42.0,
    "USB_Micro-B": 60.0,
}

# **What the pad was, kept as arithmetic because the saving is the result.** A
# signal-level dual-coil latching DPDT is typically 14 x 9 mm and there were
# twelve, plus twenty-four 0805 resistors of which six come back as the fixed
# R_IN. This is not a footprint any part in design.PARTS has any more; it is
# what pad_area() prices the deletion against.
RELAY_ENVELOPE = 14.0 * 9.0
PAD_RELAYS = 12
PAD_RESISTORS = 24
PAD_RESISTORS_KEPT = 6

# Routing, keep-out, pours and the zone gaps. 2.5 is ordinary for a four-layer
# mixed-signal board with two ground domains; it was written down while there
# was also a relay field on it, and it is left alone rather than trimmed
# towards the answer now that there is not. It is a judgement either way.
#
# **And it is now measurable, which is better than arguable: placement.py's
# real board is 18242 mm2 against this estimate's 4135.** A factor of 4.4, and
# the estimate is not what is wrong -- 2.5 is a fair packing factor for a dense
# hand layout, and placement.py is not one. It is a *systematic* placement: one
# part per grid slot on a 4 mm column pitch and a 7.62 mm row, which trades area
# for being derivable and checkable. A designer laying this out by eye would
# beat it and would not be able to prove anything about the result.
#
# Both numbers are kept, because they answer different questions. area() says
# how much copper the parts need. placement.area() says how big the board this
# repo can *generate* is. The gap between them is the price of generating it,
# and it is worth knowing before an enclosure is made around either.
PACKING = 2.5


def pad_area():
    """What the coarse pad occupied, against what the board is without it.

    The area half of design.pad_benefit(). Board area was never the argument
    for deleting the pad -- the arithmetic at the cell was, and Tim's decision
    that the enclosure is bespoke had already taken area out of the verdict --
    but it is the largest single number attached to it, and BLOCKED below has
    quoted "52 % of the placed courtyard" as an open question for two passes.
    """
    relays = RELAY_ENVELOPE * PAD_RELAYS
    resistors = COURTYARD["R_0805"] * (PAD_RESISTORS - PAD_RESISTORS_KEPT)
    now = area()["placed"]
    return {
        "relays": relays, "resistors": resistors,
        "removed": relays + resistors,
        "was": now + relays + resistors,
        "now": now,
        "share_of_was": (relays + resistors) / (now + relays + resistors),
        "relay_share_of_was": relays / (now + relays + resistors),
        "with_packing_was": (now + relays + resistors) * PACKING,
        "with_packing_now": now * PACKING,
    }


def area():
    """A minimum board area from the part inventory. A bound, not a size."""
    total, unknown, envelope, tally = 0.0, [], [], {}
    for ref, part in design.PARTS.items():
        if part.footprint is None:
            if part.value in design.UNSPECIFIED:
                envelope.append(ref)
                continue
            unknown.append(ref)
            continue
        for token, mm2 in COURTYARD.items():
            if token in part.footprint:
                total += mm2
                tally[token] = tally.get(token, 0) + 1
                break
        else:
            unknown.append(ref)
    return {"placed": total, "tally": tally, "unknown": sorted(unknown),
            "envelope_unknown": sorted(envelope),
            "with_packing": total * PACKING}


def enclosure_check():
    """Whether this module fits anywhere near the mixer, by area alone.

    A crude test and a decisive one. The mixer's own outline comes from its
    mechanical contract, and the 1590J floor is the figure DESIGN.md quotes for
    the pedal it sits in. Neither is a guess by this repo.
    """
    board = socket.mechanical()["outline"]
    mixer_area = board["width"] * board["height"]
    floor = (129.5, 78.5)                 # 1590J, per the mixer's DESIGN.md
    beside = floor[0] * (floor[1] - board["height"])
    needed = area()["with_packing"]
    return {
        "needed": needed,
        "mixer_outline": (board["width"], board["height"]),
        "mixer_area": mixer_area,
        "mezzanine_short": needed - mixer_area,
        "mezzanine_slack": mixer_area - needed,
        "beside_area": beside,
        "beside_short": needed - beside,
        "beside_slack": beside - needed,
        "fits_mezzanine": needed <= mixer_area,
        "fits_beside": needed <= beside,
    }


BLOCKED = """
**Blocked on nothing, and the arithmetic has moved three times now -- the last
of them because the *measurement* was wrong rather than the board.**

Both rows below are negative, and reading that as "the supply made the module
too big" would be wrong by a factor of twenty-seven. The supply band is 95 mm2
of the estimate. What moved the other 2,545 is that `COURTYARD` had been missing
eight of the footprints this design uses since the first pass -- the relays, the
VCAs' SOIC-20W, the SOT-523, the SOIC-8 and four more -- and `area()` skipped
what it could not price. `_report()` has printed "parts with no courtyard
estimate" on every run of this file and the list has never been empty, so a new
absence looked exactly like the standing ones. **A number that omits a term is
worse than a number that says it cannot be computed**, and this one was quoted
in a table headed "available / needed / verdict".

So the honest history is: the module was never inside the mezzanine's 6,189 mm2.
Striking the coarse pad took it from about 8,000 to about 4,100 by this
estimate's own arithmetic and the estimate was low by 2,500 throughout.

That changes nothing about the build, and it is worth being explicit about why.
Tim's decision that the enclosure is bespoke took area out of the verdict two
passes ago; `placement.py`'s real outline is 20,600 mm2, three times this
estimate, because it is a systematic grid rather than a hand layout; and the
mezzanine has never been the easy option for a mechanical reason that no area
figure touches.

Recorded in FINDINGS.md: the mixer's published `stack.above` is 13.00 mm and its
mechanical contract has no field for what plugs into a connector, so a vertical
header with a crimp housing exceeds the envelope the mixer's own enclosure was
designed to. Solder the loom directly into the six `RV{n}01` hole trios, or use
right-angle. See FINDINGS.md F3.

**And two deferred blocks are still not in this number** -- the controller and
the envelope ADC. The supply is, and the fail-safe is; both were on this list
and both are drawn.
"""


def _report():
    lines = []

    def out(text=""):
        lines.append(text)

    out(f"# Floorplan")
    out()
    out(f"Zones, ground domains and boundary crossings for the per-string CV "
        f"module, against summing-mixer @ `{socket.PIN[:7]}`.")
    out()
    out(f"Generated by `floorplan.py`. {len(design.PARTS)} parts, "
        f"{len(design.NETS)} nets.")
    out()

    out("## Ground strategy")
    out(GROUND_STRATEGY.strip())
    out()

    out("## Zones, west to east in signal order")
    out()
    out("| | zone | ground | contents |")
    out("|---|---|---|---|")
    for tag, name, domain, contents, _ in ZONES:
        out(f"| `{tag}` | {name} | {domain} | {contents} |")
    out()
    out("### Placement requirement per zone")
    out()
    for tag, name, _, _, requirement in ZONES:
        out(f"- **`{tag}` {name}** — {requirement}")
    out()

    out("## The boundary")
    out(CROSSING_RULE.strip())
    out()
    out("| net | why it may cross |")
    out("|---|---|")
    for net, why in sorted(CROSSINGS.items()):
        out(f"| `{net}` | {why} |")
    out()

    out("## Where the reference sits")
    out(REFERENCE_PLACEMENT.strip())
    out()

    a = area()
    out("## Area, as a lower bound")
    out()
    out("| footprint | count | mm² each |")
    out("|---|---|---|")
    for token, count in sorted(a["tally"].items(), key=lambda kv: -kv[1]):
        out(f"| {token} | {count} | {COURTYARD[token]:.0f} |")
    out()
    pad = pad_area()
    out(f"Placed courtyard area **{a['placed']:.0f} mm²**. At a packing factor "
        f"of {PACKING} that is a minimum of **{a['with_packing']:.0f} mm²** — "
        f"about {math.sqrt(a['with_packing']):.0f} mm square — before any of "
        f"the deferred blocks.")
    out()
    out(f"**With the coarse pad still fitted this board would be "
        f"{pad['with_packing_was']:.0f} mm².** It occupied "
        f"{pad['removed']:.0f} mm² of placed courtyard — "
        f"{pad['relays']:.0f} of relay envelope and {pad['resistors']:.0f} of "
        f"resistors that are not coming back — which was "
        f"**{pad['share_of_was'] * 100:.0f}%** of the board, the relays alone "
        f"being {pad['relay_share_of_was'] * 100:.0f}%. `design.pad_benefit()` "
        f"is why it went, and the argument there is noise rather than area; "
        f"this is what the noise argument was worth in millimetres.")
    out()

    out("## Blocked")
    text = BLOCKED.strip()
    for key, value in enclosure_check().items():
        text = text.replace("{" + key + ":.0f}",
                            f"{value:.0f}" if isinstance(value, float) else str(value))
    out(text)
    return "\n".join(lines)


def main():
    problems = check_domains() + check_crossings() + check_isolation()
    print("floorplan checks")
    print(f"  every part has a ground domain          "
          f"{'ok' if not check_domains() else 'FAIL'}")
    print(f"  no undeclared boundary crossing         "
          f"{'ok' if not check_crossings() else 'FAIL'}")
    print(f"  nothing crosses the barrier             "
          f"{'ok' if not check_isolation() else 'FAIL'}")
    for problem in problems:
        print(f"      {problem}")
    print()

    a = area()
    if a["unknown"]:
        print(f"  parts with no courtyard estimate: {a['unknown']}")
    counts = {}
    for ref in design.PARTS:
        counts[domain_of(ref)] = counts.get(domain_of(ref), 0) + 1
    print(f"  parts by domain: " + ", ".join(
        f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: str(kv[0]))))
    pad = pad_area()
    print(f"  minimum area {a['with_packing']:.0f} mm2 "
          f"({math.sqrt(a['with_packing']):.0f} mm square), "
          f"{pad['with_packing_was']:.0f} if the pad were still fitted")
    e = enclosure_check()
    import placement
    print(f"  placement.py's real outline: {placement.area():.0f} mm2, "
          f"{placement.area() / a['with_packing']:.1f}x this estimate")
    print(f"  fits on the mixer's own outline: "
          f"{'yes' if e['fits_mezzanine'] else 'no'}, beside it in the 1590J: "
          f"{'yes' if e['fits_beside'] else 'no'}")
    print()

    DOCS.mkdir(exist_ok=True)
    path = DOCS / "floorplan.md"
    path.write_text(_report() + "\n")
    print(f"  wrote {path.relative_to(path.parent.parent)}")
    if problems:
        raise SystemExit(f"{len(problems)} problems")


if __name__ == "__main__":
    main()
