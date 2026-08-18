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
    # **STRADDLE, and it was DIGITAL.** J8 carries VA+, VA-, MAGND, V5 and
    # MDGND: both rails and both grounds, which is the definition this file
    # applies to the '541, the relays and the stars. It was filed as digital
    # because it is a header and the other three headers are, and the
    # consequence was physical -- placement.py put it 18 mm inside the digital
    # pour, so its MAGND pin's barrel crossed four layers and met the analogue
    # plane on none of them. See the note at placement.SHARED["J8"].
    (r"^J8$", "STRADDLE", "supply inlet from the DC-DC secondary: both rails "
                          "and both grounds"),
    (r"^J9$|^J10$|^J11$", DIGITAL, "PWM and OE from the controller"),
    (r"^R[1-6]0[12]$", ANALOGUE, "front-end inverting stage"),
    (r"^R[1-6]1[15]$", ANALOGUE, "R_IN and the VCA input RC"),
    (r"^R[1-6]5[1-5]$", ANALOGUE, "envelope rectifier, both stages"),
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
    "VA+": "audio rail from the DC-DC secondary",
    "VA-": "audio rail from the DC-DC secondary",
    "V5": "reference supply from the DC-DC secondary",
    ANALOGUE: "the star itself, at R902",
    DIGITAL: "the star itself, at R902",
}

CROSSING_RULE = """
Seven signals and three rails cross, and the seven are all in the direction
that is cheap.

A logic input tolerates about 1.5 V of ground offset before its threshold is in
doubt -- 3.3 V of drive against the '541's 1.75 V VIH at Vcc = 2.5 V. A
precision output tolerates about 0.1 mV before its error is audible. So every
crossing here is an *input* to the analogue domain, and the '541 is the part
that converts one to the other: digital in on one row, precision analogue out
on the other, which is the package TI built and said so.

What deliberately does not cross:

  * **the six '541 outputs.** LOGO{n} is a 30.5 kHz square wave at 2.5 V and it
    is entirely inside the analogue domain, from the '541's Y pins to R{n}41. It
    is the loudest aggressor on the board and the shortest run on it.
  * **SPI.** Spec section 4.4 puts the envelope ADC in the analogue section so
    that only SCLK/MOSI/MISO/CS cross, instead of six analogue traces. When the
    ADC lands, those four join this table -- and they cross in the same
    direction, because the ADC's own reference is VREF and its ground is MAGND.
  * **audio.** Nothing audio-carrying crosses at all. That is what makes the
    boundary a line rather than a suggestion.

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

    ("D2", "controller and drive", DIGITAL,
     "DEFERRED: RP2040, QSPI flash, crystal, USB, DIN MIDI, 2 x TPIC6B595, "
     "the 74LVC1G123 one-shot, the fail-safe charge pump. Plus the envelope "
     "ADC, which is analogue and sits at the D2/A4 edge so only SPI crosses.",
     "South-east, one edge, with the star R902 at its corner nearest A3."),

    ("P", "supply", DIGITAL,
     "DEFERRED: isolated DC-DC at >=300 kHz. The isolation is what preserves "
     "constraint 2 by construction -- a non-isolated shared inlet would be a "
     "second ground bond.",
     "The far corner from A1 and R, with its own local return. |f - 45 kHz| > "
     "20 kHz against the mixer's charge pump: a VCA is a multiplier, so two "
     "supply ripples intermodulate into the audio band."),
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
**Not blocked, and the arithmetic has now moved twice in opposite directions.**

| | available | needed | verdict |
|---|---|---|---|
| beside the mixer in its 1590J | {beside_area:.0f} mm² | {needed:.0f} mm² | **{beside_slack:.0f} mm² spare** |
| as a mezzanine on the mixer's own outline | {mixer_area:.0f} mm² | {needed:.0f} mm² | **{mezzanine_slack:.0f} mm² spare** |

Both rows read the other way two passes ago — 7225 mm² needed against 6189 for
the mixer's whole 122.8 × 50.4 outline, so the module was about a quarter
*larger* than the board it hangs off, and the mezzanine placement was recorded
here as arithmetically dead rather than merely a height question.

**Striking the coarse pad is what turned it round**, and it was not the reason
for striking it: `design.pad_benefit()` argues from the cell's noise, and Tim's
decision that the enclosure is bespoke had already taken area out of the verdict
before that. The area is a consequence, and it is a large one — the pad was
about 55 % of the placed courtyard of the board it was on.

**Drawing the envelope rectifier has since spent a fifth of that back**, which
is the honest way to read the two rows: 48 parts for the sensing layer, against
36 removed for the pad. The mezzanine survives it and the space beside the mixer
in its 1590J does not, which is the first time those two rows have disagreed.

The mezzanine is directly over the `RV{n}01` column, six near-zero-length pairs,
a trivial bond to TP6. It has never been the easy option for another reason, and
that reason is unchanged and mechanical.
Recorded in FINDINGS.md: the mixer's published `stack.above` is 13.00 mm and its
mechanical contract has no field for what plugs into a connector, so a vertical
header with a crimp housing exceeds the envelope the mixer's own enclosure was
designed to. Solder the loom directly into the six `RV{n}01` hole trios, or use
right-angle. See FINDINGS.md F3.

**And the deferred blocks are not in this number.** The controller, the ADC, the
fail-safe and the DC-DC are all still to place, so the honest reading of the two
rows above is that the module has stopped being obviously too big rather than
that it has been shown to fit.
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
    problems = check_domains() + check_crossings()
    print("floorplan checks")
    print(f"  every part has a ground domain          "
          f"{'ok' if not check_domains() else 'FAIL'}")
    print(f"  no undeclared boundary crossing         "
          f"{'ok' if not check_crossings() else 'FAIL'}")
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
