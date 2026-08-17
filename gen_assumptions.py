"""Generate ASSUMPTIONS.md: everything in this repo that had to be guessed.

Half of it is generated and half is declared here, and the split is deliberate.

The structured half -- design.MEASURED, design.UNSPECIFIED, design.DEFERRED,
socket.ADAPTED, and the price bases in gen_bom -- is pulled from the code, so a
guess cannot be quietly resolved in one place and left standing in the
document. That is the mixer's own arrangement: its `check_assumptions()` exists
to catch somebody tightening a range without revisiting the value it was
written around.

The declared half is the assumptions that are not numbers: a reading of a
sentence, a datasheet not opened, a model that leaves a term out. Those cannot
live in a dict of floats and they are exactly the kind this project keeps
finding out about late, so they are written out in full below with what each
one costs if it is wrong.

    python3 gen_assumptions.py
"""

import collections
import pathlib

import design
import contract.socket as socket
import gen_bom

OUT = pathlib.Path(__file__).resolve().parent

Guess = collections.namedtuple("Guess", "what basis affects if_wrong settle")

# ---------------------------------------------------------------------------
# The assumptions that are not numbers
# ---------------------------------------------------------------------------

READINGS = (
    Guess(
        "The `MAX6126A25` pin map.",
        "Not read. The part is chosen on its noise figure and its voltage, "
        "both of which came from the datasheet's electrical table via a text "
        "mirror rather than from the PDF itself.",
        "U12's four connections are pin *roles* in the netlist -- `<VIN>`, "
        "`<VOUT>`, `<GND>`, `<NR>` -- and design.check_pin_numbers() refuses "
        "to let a number be invented for them.",
        "Nothing silently. The netlist is not loadable by KiCad until they "
        "resolve, which is the intended state.",
        "Open the MAX6126 datasheet and fill in design.UNSPECIFIED's entry."),

    Guess(
        "The MAX6126's noise figures per output voltage.",
        "Read from a text mirror of the datasheet (pdf.datasheet.live), not "
        "from Analog Devices' own PDF, which timed out three times. The "
        "figures are internally coherent -- noise scales almost exactly with "
        "output voltage -- and one of them (35 nV/rtHz at 2.048 V) is "
        "corroborated by an independent search result.",
        "The whole of correction 5: whether the '0-5 V through 15k' scaling "
        "buys 8 dB or nothing. The answer turns on 45 nV/rtHz at 2.5 V "
        "against 95 at 5 V.",
        "If the scaling really is proportional to voltage, nothing changes. "
        "If the 2.5 V part is quieter than 45 nV/rtHz relative to the 5 V "
        "part, the 5 V option becomes worth something again -- and it is "
        "still blocked by the '541's input threshold, so the conclusion is "
        "robust even if the numbers move.",
        "Fetch the ADI PDF when it is reachable and check the two rows."),

    Guess(
        "The OPA1644's input offset voltage.",
        "Not read. `MEASURED['servo_vos']` assumes 0.5 mV with a declared "
        "range of 0.05 to 3 mV, which is wide enough to cover any JFET quad.",
        "The residual DC on SIN{n}, which is constraint 3.",
        "Nothing, across the whole declared range: servo_residual() shows the "
        "worst case still lands at nanoamps through the mixer's master wiper, "
        "against the 0.2-1.0 nA it already accepts.",
        "One line of the OPA1644 datasheet. Worth doing when the BOM is "
        "finalised anyway."),

    Guess(
        "The 74AHC541's output impedance at Vcc = 2.5 V.",
        "The datasheet characterises VOH/VOL at 3.3 V and 4.5 V only. "
        "`MEASURED['logic_law_error']` extrapolates.",
        "The linearity of dB against code -- a duty-dependent bend in the "
        "control law.",
        "Nothing structural. It is common to all six channels, so it is a law "
        "error rather than a matching error, and 0.23 % over a 61 dB span is "
        "0.14 dB. Calibratable in firmware from one measured curve.",
        "Measure V_C against duty on one channel, once."),
)

MODELS = (
    Guess(
        "The SSI2164's output noise is flat across the band.",
        "The datasheet publishes four points in dBu over 20 Hz to 20 kHz "
        "unweighted, and no spectrum at all. vca_noise() converts a total to "
        "a density by assuming it is flat.",
        "Every noise figure this repo quotes for the VCA, and therefore the "
        "whole of delta.py's system arithmetic.",
        "If the part has significant 1/f, the density at low frequency is "
        "higher than modelled and the figures are optimistic where the "
        "instrument's fundamentals are.",
        "A spectrum analyser on one channel at Phase 1. This is worth adding "
        "to the phase-1 bench list, which currently only has feedthrough, "
        "noise and law drift on it."),

    Guess(
        "The datasheet's noise figures apply at pad steps other than 0 dB.",
        "The table's stated condition is R_IN = R_OUT, which is true only at "
        "the 0 dB step. The other three raise R_IN and leave R_OUT alone, and "
        "vca_noise() is called with the base value throughout.",
        "The noise figures at -6, -12 and -18 dB, which are not computed "
        "anywhere.",
        "The pad steps are noisier than modelled -- but they are used when "
        "the source is hot, so the signal is larger by the same amount. This "
        "is what any pad costs and it is not specific to this arrangement.",
        "Measure, or accept. It does not change a component value."),

    Guess(
        "The SSI2164 noise table already includes an I-V amplifier.",
        "The specification conditions say 'using Figure 1 circuit without "
        "diode', and Figure 1 contains a 1/2 TL072 and both resistors. So "
        "channel_noise() adds no separate I-V term.",
        "Whether delta.py double-counts the largest contributor.",
        "If the figure is somehow the cell alone, this repo *under*-counts by "
        "an op-amp and a resistor -- about 15 nV/rtHz, which would raise the "
        "gating penalty by roughly 0.1 dB.",
        "It is a reading of the conditions line and it is a confident one. "
        "Left as an assumption because it is load-bearing, not because it is "
        "doubtful."),

    Guess(
        "X7R is acceptable for the CV filter's 56 nF and 22 nF.",
        "Assumed, not computed. At 2 V on a 50 V part the bias derating is a "
        "few per cent and f0 goes as 1/sqrt(C1 C2), so the corner moves a "
        "per cent or two.",
        "The CV filter's corner and Q, and therefore the anti-AM figure.",
        "Nothing audible: a 2 % shift on a 255 Hz corner. The reason it is "
        "recorded is that this design names C0G explicitly everywhere it "
        "matters, and these two are the only signal-adjacent parts that are "
        "not C0G -- because C0G at 56 nF is a much larger package.",
        "Compute the bias curve for the specific part, or fit film and take "
        "the area."),

    Guess(
        "Courtyard areas and a packing factor of 2.5.",
        "The areas are from the footprint names; the relay is a 14 x 9 mm "
        "envelope for a part that is not chosen; the packing factor is a "
        "judgement.",
        "floorplan.area(), and the finding that the module is 1466 mm2 larger "
        "than the mixer's whole outline.",
        "The area conclusion survives a wide error, because the shortfall is "
        "24 %. It stops being interesting now the enclosure is bespoke.",
        "Nothing to settle. Superseded by the enclosure decision."),
)

FIRMWARE = (
    Guess(
        "Firmware emits the complement of the level.",
        "Required by 'code 0 = loudest' with the datasheet's Figure 10 "
        "topology: V_C is the *difference* between V_REF and the '541's "
        "output, so the loud end is 100 % duty.",
        "Nothing in hardware -- the board is identical either way. Only which "
        "direction a firmware variable counts.",
        "The control law runs backwards. Obvious in a second at the bench.",
        "One line, and it is written down here because it is the kind of "
        "thing that gets lost between a schematic and a firmware repo."),

    Guess(
        "The six PWM slices can be phase-staggered.",
        "Spec section 4.2 asks for it and the RP2040's PWM slices have "
        "independent counters, so it should be available. Not verified "
        "against the datasheet or the SDK.",
        "The reference's transient load: staggering divides the peak by six.",
        "Little. The arithmetic in REFERENCE_PLACEMENT shows the transient is "
        "19 uA against the MAX6126's 10 mA, so the stagger is a free "
        "improvement rather than a requirement.",
        "Check the RP2040 datasheet when the controller block is drawn."),

    Guess(
        "A 3-10 ms coil pulse is what the latching relays need.",
        "From spec section 4.5, which states it without a part. Used in "
        "floorplan.py's current argument and nowhere else.",
        "The one-shot's RC, which is not designed yet.",
        "Nothing here. It is the relay's specification and arrives with the "
        "relay.",
        "Choose the relay."),
)

READINGS_OF_THE_SPEC = (
    Guess(
        "Constraint 2's \"six separate returns to six pin-3s\" has been "
        "**struck**, not interpreted.",
        "It was generated in an earlier session answering a question about "
        "power, not derived from a measurement or a datasheet, and was then "
        "written into CLAUDE.md under \"load-bearing constraints\" -- which is "
        "what made it unquestionable. Per-channel returns exist to prevent "
        "shared-impedance crosstalk; computed for this module with a single "
        "bond carrying all six channels, pairwise crosstalk is 122 dB below "
        "one string on a 100 mm bond and 103 dB on a deliberately bad one, "
        "against a -54 dB requirement.",
        "The front-end topology. It was a four-resistor difference amplifier "
        "to satisfy the clause literally; it is now a two-resistor inverting "
        "stage, and the loom is a shielded pair rather than a triad.",
        "Nothing measurable either way -- the two topologies differ by "
        "0.008 dB of system noise, because the VCA's 62 nV/rtHz swamps the "
        "front end. What was at stake was twelve resistors and a matched-set "
        "requirement, spent to satisfy a sentence with no mechanism behind it.",
        "**Settled.** The half of the constraint that has a mechanism -- "
        "exactly one bond, which is the mixer's own _GROUND_RULE applied "
        "across the connector -- is kept and checked. The half that does not "
        "is gone, and design.FRONT_R carries the arithmetic. Constraint 5's "
        "\"triad\" becomes \"twisted pair inside an individual shield\"."),

    Guess(
        "The ground bond lands on the mixer's TP6.",
        "TP6 is the mixer's own AGND test pad and its comment calls it 'the "
        "*only* correct one, given the ground rule'. Nothing in the mixer "
        "designates a bond point, because nothing was expected to bond to it.",
        "Where one wire is soldered, and the loom's geometry.",
        "Any AGND point works electrically. TP6 is chosen because it is the "
        "one the mixer itself designates.",
        "Its coordinates are not in fab/mechanical-summing-mixer.json -- test "
        "pads are not tall parts -- so they have to be read off the board or "
        "the .kicad_pcb before the loom is made."),

    Guess(
        "The six triad shields land at the bond point too.",
        "Constraint 5 says shields are grounded at the main-board end only "
        "and does not say where. Grounding them at the bond keeps every "
        "shield at the same potential as the module's own reference.",
        "The loom's construction.",
        "Grounding them at six separate pin-3s would work too, and would put "
        "six shield currents into six different points of the mixer's AGND "
        "pour. The single point is the more conservative choice.",
        "A loom decision, not a board one."),

    Guess(
        "3 + 3 across the two SSI2164 packages, not 4 + 2.",
        "Crosstalk is a within-die property and is the binding constraint on "
        "the lead feature. 3 + 3 gives every string two die-mates; 4 + 2 "
        "gives four strings three and two strings one.",
        "Which channel is which cell, and the floorplan.",
        "Nothing measurable until Phase 1.5 measures crosstalk. If it comes "
        "back far better than -54 dB the arrangement stops mattering.",
        "Phase 1.5, which is already on the staging list for exactly this."),

    Guess(
        "Op-amp sections are grouped by block, not by channel.",
        "Four sections per channel would put one quad per channel, which is "
        "tidy and puts a 30.5 kHz CV filter on the same die as an audio front "
        "end. Grouping by block keeps them apart at the cost of eight "
        "packages with one spare section.",
        "design.SECTIONS, and the floorplan's zone layout.",
        "Provisional. This is the one table in design.py the floorplan may "
        "move, and moving it changes no values.",
        "Settled when the board is laid out."),
)

SUPPLY = (
    Guess(
        "The module's audio rails are +/-12 V.",
        "Spec section 1.1 decides the topology -- isolated DC-DC at >=300 "
        "kHz, +/-12 V for a small audio domain -- and the DC-DC part is not "
        "chosen.",
        "die_rise(), which is 118 C/W x 24 V x 6 mA = 17 C, and therefore the "
        "tempco span. Also the CV filter op-amp's ability to output exactly "
        "0 V, which needs a negative rail.",
        "A lower rail lowers the die temperature and narrows the tempco span, "
        "which is the direction that helps. A single supply would break the "
        "0 V requirement outright.",
        "Choose the DC-DC. Note the SSI2164 spans +/-4 to +/-18 V, so the "
        "rail is not tightly constrained by the VCA."),

    Guess(
        "The offset reference is stable enough.",
        "Rossum's Note 3 wants the negative reference 'temperature stable to "
        "100 ppm/degC'. This design inverts the +2.5 V reference through one "
        "op-amp section and two 0.1 % resistors, and the resulting drift has "
        "not been computed.",
        "The zero point of the control law -- what V_C is at the loud end, "
        "and therefore whether unity gain is really unity.",
        "A common-mode gain error, not a matching error, because all six "
        "channels share the one inverted reference. Probably invisible; "
        "unverified.",
        "Compute the inverter's drift from the resistors' tempco and the "
        "op-amp's, against the 100 ppm/degC Note 3 asks for."),
)


def _from_measured():
    rows = []
    for name, a in sorted(design.MEASURED.items()):
        rows.append((name, f"{a.value}{a.units}", f"{a.low} .. {a.high}",
                     a.question, a.sets, a.when_wrong))
    return rows


def _report():
    L = []

    def out(text=""):
        L.append(text)

    out("# ASSUMPTIONS.md")
    out()
    out("Everything in this repo that had to be guessed, and what each guess "
        "costs if it is wrong.")
    out()
    out("Generated by `gen_assumptions.py`. The numeric entries are pulled "
        "from the code — `design.MEASURED`, `design.UNSPECIFIED`, "
        "`design.DEFERRED`, `contract.socket.ADAPTED` and `gen_bom.PRICES` — "
        "so a guess cannot be resolved in one place and left standing here. "
        "The rest are declared in that file, because a reading of a sentence "
        "does not fit in a dict of floats.")
    out()
    out("The discipline is the mixer's. Its `Assumption` class says it "
        "plainly: **the range matters more than the value.** The value is a "
        "guess; the range is a claim about what the design survives, and "
        "`check_assumptions()` fails the build if a value ever falls outside "
        "the range it was written around.")
    out()

    out("## The short version")
    out()
    out("Two of these would change the board, and the rest would change a "
        "number:")
    out()
    out("1. **`MEASURED['noise_floor']`** — the mixer's own unmeasured "
        "figure, which decides whether this module costs 0.11 dB or 0.85 dB "
        "with everything open, and 0.56 dB or 3.17 dB while the lead feature "
        "is running.")
    out("2. **The pad relay** — not chosen, 49 % of the board area and about "
        "a third of its cost.")
    out("3. **The MAX6126's noise figures**, read from a text mirror rather "
        "than Analog Devices' own PDF. They are what overturn the \"free "
        "8 dB\".")
    out()
    out("One entry that *was* on this list is now settled rather than open: "
        "constraint 2's \"six separate returns\" has been struck, with the "
        "arithmetic, in [Readings of the spec](#readings-of-the-spec).")
    out()

    out("## Numbers with declared ranges")
    out()
    out("From `design.MEASURED`, which is the mixer's `Assumption` class "
        "reused rather than reimplemented.")
    out()
    for name, value, rng, question, sets, when_wrong in _from_measured():
        out(f"### `{name}` = {value}")
        out()
        out(f"**Range:** {rng}")
        out()
        out(f"**Question:** {question}")
        out()
        out(f"**Sets:** {sets}")
        out()
        out(f"**When wrong:** {when_wrong}")
        out()

    out("## Inherited from the mixer")
    out()
    out("Facts this repo takes from `../summing-mixer` at "
        f"`{socket.PIN[:7]}`. Their truth is upstream's problem; what is "
        "assumed here is only that they still apply.")
    out()
    out("| | value | upstream | quoted |")
    out("|---|---|---|---|")
    for name, (value, upstream, quote) in socket.ADAPTED.items():
        out(f"| `{name}` | `{value}` | `{upstream}` | \"{quote}\" |")
    out()
    out("`AMBIENT_C` is the one that does work here: 0–50 °C is what decides "
        "that the SSI2164's −3300 ppm/°C drift is not worth compensating, and "
        "it comes from a comment in the mixer about ceramic dielectrics — "
        "*\"a pedal never leaves 0-50 C\"* — rather than from anything about "
        "this module.")
    out()

    out("## Parts not chosen")
    out()
    for value, reason in sorted(design.UNSPECIFIED.items(),
                                key=lambda kv: str(kv[0])):
        out(f"- **{value}** — {reason}")
    out()

    out("## Blocks deferred")
    out()
    out("Not assumptions so much as absences, listed because a section 5 "
        "check against a partial board proves less than it appears to.")
    out()
    for block, reason in sorted(design.DEFERRED.items()):
        out(f"- **{block}** — {reason}")
    out()

    for title, guesses in (("Readings not taken", READINGS),
                           ("Modelling assumptions", MODELS),
                           ("Firmware assumptions", FIRMWARE),
                           ("Readings of the spec", READINGS_OF_THE_SPEC),
                           ("Supply", SUPPLY)):
        out(f"## {title}")
        out()
        for guess in guesses:
            out(f"### {guess.what}")
            out()
            out(f"**Basis:** {guess.basis}")
            out()
            out(f"**Affects:** {guess.affects}")
            out()
            out(f"**If wrong:** {guess.if_wrong}")
            out()
            out(f"**To settle:** {guess.settle}")
            out()

    rows = gen_bom.lines()
    bases = collections.Counter(
        r["price"].basis if r["price"] else "MISSING" for r in rows)
    out("## Prices")
    out()
    out(f"Of {len(rows)} BOM lines, **{bases.get('read', 0)} carries a price "
        f"read from a page fetched in this session**. "
        f"{bases.get('snippet', 0)} come from search results quoting a "
        f"distributor without the page being opened, and "
        f"{bases.get('band', 0)} are typical bands for the class — estimates, "
        f"labelled as such in the `basis` column of "
        f"`out/cv-module-bom.csv`.")
    out()
    out("The totals in `out/SHOPPING.md` are therefore a range, and the range "
        "is honest rather than decorative. They are also a floor: none of the "
        "deferred blocks is costed.")
    out()

    out("## What is not assumed")
    out()
    out("For contrast, because a document of guesses can make a design look "
        "less settled than it is. These were derived or read, and each has "
        "its arithmetic in the repo:")
    out()
    out("- The **control law** — −33 mV/dB, the 9k:1k divider, the 9/10/11 kΩ "
        "tolerance and dg/g = −3.488 per volt, all from the datasheet, with "
        "the constant re-derived from q/kT to 2.4 %.")
    out("- **Class AB** — pin 1 open, from three separate statements in the "
        "datasheet, worth 12 dB and better control feedthrough.")
    out("- **V_REF ≤ 4.71 V** — from the '541's VIH against a 3.3 V GPIO. "
        "This is what rules out the 5 V reference and it is arithmetic, not "
        "preference.")
    out("- **R_OFF = R1** — the exact-cancellation condition, not a value.")
    out("- **The CV chain is fail-silent** — every fault drives the '541 "
        "output toward 0 V, which is full attenuation, because the offset "
        "current comes from neither the MCU nor the reference that feeds it.")
    out("- **The MAGND star is at the SSI2164 ground pins** — because the "
        "control port is ground-referenced, so 1 mV in the wrong place is AM "
        "51 dB below the signal.")
    out("- **The five section 5 constraints** — checked mechanically by "
        "`verify.py`, and `test_verify.py` plants fourteen faults to prove "
        "the checks can fail.")
    out("- **Every pin map in the netlist except the MAX6126's** — SSI2164, "
        "OPA1644 and SN74AHC541 were each read off their own "
        "pin-configuration tables in this session.")
    return "\n".join(L)


def main():
    path = OUT / "ASSUMPTIONS.md"
    path.write_text(_report() + "\n")
    counts = {
        "MEASURED": len(design.MEASURED),
        "not chosen": len(design.UNSPECIFIED),
        "deferred": len(design.DEFERRED),
        "inherited": len(socket.ADAPTED),
        "declared": len(READINGS) + len(MODELS) + len(FIRMWARE)
                    + len(READINGS_OF_THE_SPEC) + len(SUPPLY),
    }
    print("assumptions: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    print(f"  total {sum(counts.values())} entries")
    print(f"  wrote {path.name}")


if __name__ == "__main__":
    main()
