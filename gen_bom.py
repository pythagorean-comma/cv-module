"""The bill of materials, with a source and a price on every line.

Grouped by value and footprint, because parts sharing a value share a part
number -- which is how the mixer's ORDER_CODES table and a BOM line are the
same thing seen from two ends.

**Provenance is a column, and it is the most important one here.** This project's
recurring failure is a source named rather than read, and a price is the easiest
place in a document to write a plausible number nobody checked. So every line
carries a `basis`:

    read       a page was fetched in this session and states this figure
    snippet    a search result quoted a distributor's figure; the page itself
               was not opened
    band       a typical distributor band for that class of part at the stated
               quantity. Not read from anything. An estimate, said so.
    none       the part is not chosen, so it has no price by construction

Totals are therefore given as a range, and the range is honest rather than
decorative: the `band` lines are wide because nobody looked.

The distributor convention is the mixer's, inherited rather than invented. Its
`fab/SHOPPING.md` uses **Mouser UK catalogue searches keyed on the manufacturer's
part number** rather than product-page deep links, and says why: "a search
survives a part being re-listed, which a deep link does not". That warning was
worth having -- a guessed Digi-Key product URL tried during this session
resolved to a HIWIN linear rail.

    python3 gen_bom.py

writes `out/cv-module-bom.csv` and `docs/SHOPPING.md`.
"""

import collections
import csv
import pathlib

import design

HERE = pathlib.Path(__file__).resolve().parent

# Two destinations, and the split is by audience rather than by file type.
# `out/` is what a machine reads next: the CSV goes to a quoting tool or an
# assembly house. `docs/` is what a person reads: SHOPPING.md is a page you work
# from with a browser open. Both are generated and neither is source.
OUT = HERE / "out"
DOCS = HERE / "docs"

# Spares policy, inherited verbatim from the mixer's SHOPPING.md: "enough spare
# to lose a few 0805s off a pair of tweezers, and one spare of each active."
SPARE_PASSIVE = 4
SPARE_ACTIVE = 1

# What a price line carries. `low` and `high` are the same number where the
# figure was read, and a band where it was not.
Price = collections.namedtuple(
    "Price", "low high currency qty basis source note")


def read(value, currency, qty, source, note=""):
    return Price(value, value, currency, qty, "read", source, note)


def snippet(low, high, currency, qty, source, note=""):
    return Price(low, high, currency, qty, "snippet", source, note)


def band(low, high, currency, qty, note=""):
    return Price(low, high, currency, qty, "band",
                 "typical distributor band, not read this session", note)


NONE = Price(None, None, "", 0, "none", "part not chosen", "")


# Per value string. Everything in design.ORDER_CODES needs an entry here or
# check() below complains -- a part number without a price is half a BOM line.
PRICES = {
    # -- actives -----------------------------------------------------------
    design.VCA: read(
        3.80, "GBP", 1, "https://www.thonk.co.uk/shop/ssi2164/",
        "page fetched; states \"£3.80 (Excl. VAT)\". A UK synth-DIY "
        "distributor rather than a catalogue house, which is where this part "
        "actually lives."),

    design.OPAMP: snippet(
        2.40, 4.98, "USD", 1,
        "https://octopart.com/opa1644aid-texas+instruments-18186989",
        "**Out of stock at TI itself** -- ti.com/product/OPA1644 shows "
        "'Out of stock' for both OPA1644AIDR and OPA1644AID and displays no "
        "price at all. Eight of these is the largest line on the board, so "
        "the stock position matters more than the price. See ASSUMPTIONS."),

    design.VREF_PART: snippet(
        8.76, 9.96, "USD", 1,
        "Digi-Key, via search; MAX6126B25+ at $8.76/1 and MAX6126AASA50+ at "
        "$9.96/1",
        "The exact A-grade 2.5 V part (MAX6126AASA25+) was not priced "
        "directly; this brackets it with the B grade at the same voltage and "
        "the A grade at a different one. ADR4525C/D is the second source "
        "spec section 4.2 names and is not priced here at all."),

    # The supply, and it is the largest single line on this BOM by a factor of
    # two -- more than the reference, more than eight OPA1644. Worth seeing as
    # a number rather than as a part: an isolated 6 W converter with a stated
    # switching frequency costs what a whole channel of this module costs, and
    # the alternative that would halve it is the plain TMR 6, whose RCC
    # topology puts its fundamental on the mixer's own pump harmonic. See
    # design.supply_beat().
    design.SUPPLY_PART: read(
        18.16, "GBP", 1, "https://www.tme.eu/gb/details/tmr6-2422wi/"
        "dc-dc-converters/traco-power/tmr-6-2422wi/",
        "page fetched: \u00a318.16 at 1+, \u00a316.89 at 5+, \u00a316.77 at "
        "10+, net of VAT, 87 in stock. The same page states the switching "
        "frequency as 580 kHz and the body as 21.8 x 11.2 x 9.1 mm, which "
        "agrees with the datasheet read for design.SUPPLY_KHZ_TYP. The "
        "datasheet itself is at " + design.SUPPLY_DATASHEET + " -- fetched "
        "and read to the end. tracopower.com's own copy of the same document "
        "refuses an automated fetch, and a link nobody could follow is the "
        "thing STYLE.md rule 10 is about."),

    design.V5_PART: band(
        0.35, 0.90, "GBP", 10,
        "NCP1117DT50G, DPAK. **The DT suffix and not ST**, which is the whole "
        "of v5_regulator(): the SOT-223 part is the same die, the same price "
        "and 160 C/W against 0.77 W."),

    design.INLET_DIODE: band(
        0.20, 0.60, "GBP", 10,
        "B340A-13-F, SMA. The mixer's own reverse-protection part, chosen "
        "there for a forward drop that falls as the diode is run below its "
        "rating -- see design.INLET_DIODE."),

    # The envelope ADC, and it is the second-largest line on this BOM after
    # the converter. Worth seeing beside the part it beat: an ADS131M08 is a
    # 32-pin QFN at about twice this, and it lost on a number that costs
    # nothing to have -- reference input range. See design.ENV_ADC.
    design.ENV_ADC: read(
        5.35, "GBP", 1,
        "https://www.digikey.co.uk/en/products/detail/microchip-technology/"
        "MCP3564-E-ST/11618284",
        "page fetched: \u00a35.35 at 1, \u00a34.46 at 25, \u00a34.05 at 100, "
        "net of VAT, 599 in stock, \"20-TSSOP (0.173\", 4.40mm Width)\". The "
        "tube part; MCP3564T-E/ST is the same die on tape. Datasheet "
        "DS20006181C at " + design.ENV_ADC_DATASHEET + " -- fetched and read. "
        "Microchip's own ww1 URL 301s to a filehandler that refuses an "
        "automated fetch, which is the same obstacle the converter's own "
        "datasheet had, and STYLE.md rule 10 says a link nobody can follow "
        "is not a citation."),

    design.V3V3_PART: read(
        0.38, "GBP", 1,
        "https://www.digikey.co.uk/en/products/detail/microchip-technology/"
        "MCP1700T-3302E-TT/652676",
        "page fetched: \u00a30.38 at 1, \u00a30.322 at 25, \u00a30.298 at "
        "100, net of VAT, 81,458 in stock, SOT-23-3. Its 4 uA of quiescent "
        "current is the whole reason a third linear rail was affordable: an "
        "NCP1117 in the same position is 10 mA maximum, which is a third of "
        "the converter's remaining headroom spent on a regulator's own "
        "biasing. Datasheet DS20001826F at " + design.V3V3_DATASHEET + " -- "
        "fetched; the 336 C/W this design uses is from DS21826B, which "
        "publishes the minimum-pad figure revision F drops."),

    design.INLET_FUSE: read(
        1.80, "USD", 1,
        "https://www.digikey.com/en/products/detail/schurter-inc/"
        "3403-0168-11/957690",
        "page fetched: $1.80 at 1, $1.38 at 10, $1.145 at 50, $1.056 at 100, "
        "$0.807 at 1000, 16,067 in stock. The listing's 1.6 A, 250 VAC, "
        "125 VDC, Slow Blow and 10.10 x 3.00 x 3.00 mm all agree with the "
        "datasheet read for design.INLET_FUSE -- and the 3.00 mm height is "
        "what put it in GAP_MM's passive class rather than the tall one. "
        "**Its \"Breaking Capacity: 200 A AC, 35 A DC\" is the datasheet's "
        "worst row and not this application's**: note 2) on page 5 gives "
        "35 A only at 250 VDC, against 200 A at 63 VAC/DC, and this inlet is "
        "24 V. A distributor's summary field flattens a table, and the row it "
        "keeps is the one that sells the part conservatively."),
    design.INLET_CHOKE: read(
        1.97, "GBP", 1,
        "https://www.digikey.co.uk/en/products/detail/"
        "w%C3%BCrth-elektronik/744222/1638889",
        "page fetched: \u00a31.97 at 1, \u00a31.94 at 10, \u00a31.75 at 50, "
        "\u00a31.69 at 100, \u00a31.37 at 1000 T&R, net of VAT, 12,641 in "
        "stock. The listing's own \"1 mH @ 100 kHz\", 800 mA and 207 mOhm "
        "agree with the datasheet read for design.INLET_CHOKE, and its "
        "\"6 kOhms @ 4 MHz\" is the frequency the datasheet's Zmax row omits "
        "-- which is what puts 580 kHz on the inductive slope rather than "
        "over the peak. The datasheet is at "
        + design.INLET_CHOKE_DATASHEET + " -- fetched and read."),

    design.RAIL_FILTER_R: band(
        0.01, 0.03, "GBP", 100,
        "0805 thick film. Two of them, and they are the rail filter: "
        "rail_filter() is why this is a resistor and not an inductor."),

    "10u/50V X7R": band(
        0.30, 0.80, "GBP", 25,
        "1210 X7R at 50 V, which is 4x derating on the +/-12 V rails and 2.5x "
        "on the 20 V primary. A 25 V part would be cheaper and would have "
        "lost most of its capacitance at the top of the inlet range -- the "
        "same argument the mixer makes at its own VIN_P."),

    design.LOGIC: band(
        0.40, 0.90, "GBP", 10,
        "SN74AHC541DWR, SOIC-20W. An ordinary logic part from any of the four "
        "UK catalogue houses."),

    # The envelope rectifier's two parts, and the point of the first is that it
    # is not the OPA1644: two TL074 against two more of the largest line on
    # this BOM, for twelve sections whose specification is offset and slew
    # rather than noise. See design.ENV_OPAMP.
    design.ENV_OPAMP: band(
        0.25, 0.70, "GBP", 10,
        "TL074CDR, SOIC-14. About a tenth of the OPA1644 and stocked "
        "everywhere; the SSI2164's own datasheet uses its dual in the same "
        "position."),
    design.ENV_DIODE: band(
        0.02, 0.08, "GBP", 100,
        "1N4148WS-7-F or any 1N4148 in SOD-123. Inside an op-amp's feedback "
        "loop, so the forward drop does not reach the answer."),

    # -- passives ----------------------------------------------------------
    # Three classes, and the first is the one that costs something.
    "10k 0.1%": band(0.10, 0.30, "GBP", 100,
                     "Panasonic ERA-6A thin film, 0.1 %, 25 ppm. Thin film is "
                     "the specification and not the tolerance -- see FRONT_R."),
    "12k1 0.1%": band(0.10, 0.30, "GBP", 25, "ERA-6A thin film"),

    "10k 1%": band(0.01, 0.03, "GBP", 100,
                   "0805 thick film. The envelope rectifier's ratios are 1 %, "
                   "not the 0.1 % the audio path uses: a 2 % ratio error is "
                   "0.17 dB on a *reported level*, which is inside what "
                   "envelope_balance() already allows for the E96 half-value."),
    "4k99 1%": band(0.01, 0.03, "GBP", 100, "0805 thick film, E96"),

    "22k 1%": band(0.01, 0.03, "GBP", 100, "0805 thick film"),
    "17k8 1%": band(0.01, 0.03, "GBP", 100, "0805 thick film, E96"),
    "220R 1%": band(0.01, 0.03, "GBP", 100, "0805 thick film"),
    "1M 1%": band(0.01, 0.03, "GBP", 100, "0805 thick film"),
    "100k 1%": band(0.01, 0.03, "GBP", 100, "0805 thick film"),
    "0R": band(0.01, 0.03, "GBP", 100, "0805 jumper"),

    "100p/50V C0G": band(0.02, 0.08, "GBP", 100, "0805 C0G"),
    "1200p/50V C0G": band(0.02, 0.08, "GBP", 100, "0805 C0G"),
    # ~~"100n/50V C0G"~~ -- **removed with the value string, and its own note
    # was the only argument for C0G that existed anywhere.** It read: "0805
    # C0G at 100 nF is a large part for the class and priced accordingly. It
    # is the reference's NR capacitor, which is worth C0G." The first sentence
    # is why it could not be sourced; the second is an assertion with nothing
    # behind it, sitting in a *price* table rather than beside the constant --
    # which is why nobody looking at design.py ever saw a reason and nobody
    # looking here expected one. See design.VREF_NR_CAP for what the datasheet
    # actually says.
    "22n/50V X7R": band(0.02, 0.08, "GBP", 100, "0805 X7R"),
    "56n/50V X7R": band(0.02, 0.08, "GBP", 100, "0805 X7R"),
    "150n/50V X7R": band(0.02, 0.08, "GBP", 100, "0805 X7R"),
    "100n/50V X7R": band(0.01, 0.05, "GBP", 100, "0805 X7R"),
    "470n/50V X7R": band(0.02, 0.08, "GBP", 100, "0805 X7R"),
    "10u/16V X7R": band(0.08, 0.25, "GBP", 25, "1210 X7R"),

    "2n2/50V C0G": band(0.02, 0.08, "GBP", 100, "0805 C0G"),
    "1u/16V X7R": band(0.02, 0.08, "GBP", 100, "0805 X7R"),
    design.PUMP_DIODE: band(
        0.05, 0.15, "GBP", 100,
        "BAT54-7-F, in SOD-123. Five of them do two jobs -- the two-diode "
        "pump and three coil flybacks -- and what the pump wants from it is "
        "*leakage*, 2 uA max at 25 V, because the same diode has to hold a "
        "1 uF node up between 10 kHz cycles. Its forward drop at the pump's "
        "18 uA is off the bottom of its own table; PUMP_DIODE_VF's 0.32 V "
        "sits above the datasheet maximum at ten times that current, "
        "deliberately."),

    design.CLAMP_DIODE: band(
        0.10, 0.30, "GBP", 100,
        "PMEG2010AEH in SOD123F, and it is the one diode on this board "
        "chosen by a number rather than a class. It is a 1 A part carrying "
        "36 mA, which is the whole trick: 259 mV max there against the "
        "BAT54's 545 mV, and design.clamp_vf_ceiling() says the mixer's "
        "headroom will take 320 mV. The BAT54 that used to be fitted here "
        "missed by 5.5 dB. Higher leakage is the price and it is free on a "
        "node inside an op-amp's feedback loop."),

    design.BYPASS_RELAY: band(
        3.00, 5.50, "GBP", 10,
        "Omron G6S-2 DC5, surface-mount G6S-2F body. Single-side stable, "
        "which is Omron's name for non-latching and is the property the "
        "whole fail-safe turns on. The line worth reading twice is the "
        "contact material -- bifurcated crossbar, Ag(Au-Alloy) -- because a "
        "plain silver contact needs a wetting current a guitar string will "
        "never supply, and fails intermittently in a way that looks like a "
        "dry joint."),

    design.BYPASS_FET: band(
        0.06, 0.20, "GBP", 100,
        "Diodes DMG1012T in SOT-523. Chosen for one row of its table: "
        "R_DS(on) 0.7 ohm max at V_GS = 1.8 V, which is the gate voltage "
        "pump_timing() computes and the only voltage this circuit can "
        "produce. Vgs(th) 1.0 V max is the stated filter; being "
        "characterised at 1.8 V is what made this part rather than another "
        "that meets it."),

    # -- the controller block ----------------------------------------------
    #
    # **Every line here is a band and not a read, and that is a statement
    # rather than an omission.** The four actives were chosen from datasheets
    # read first-hand this session; no distributor page was fetched for any of
    # them, so what is quoted is a class figure with the reasoning attached.
    # STYLE.md rule 10's point is that a citation is a thing somebody followed,
    # and `band` is this file's word for "not this session".
    design.CONTROLLER: band(
        3.60, 5.00, "GBP", 1,
        "Raspberry Pi Pico, SC0915. **The one line on this BOM whose price is "
        "published rather than banded**: the Pico datasheet's own Table 6 "
        "says US$4.00 at 1+, which is the only figure in this file that came "
        "from a vendor's ordering table instead of from a class. It is now "
        "the most expensive active on the board after the converter, and it "
        "replaced four lines that came to about GBP 3 between them -- the "
        "RP2040, the flash, the crystal and the USB receptacle -- plus twelve "
        "capacitors, four resistors and two headers. So the parts cost is "
        "roughly a wash and what it bought is elsewhere: 0.40 mm of pin pitch "
        "became 2.54, which re-opened docs/fabrication-class.md, and about 25 "
        "lines of assembly became one."),

    design.MIDI_OPTO: band(
        1.00, 2.20, "GBP", 10,
        "Toshiba TLP2761, SO6L. It is dearer than the 6N138 CA-033 names and "
        "the reason is the whole of design.MIDI_OPTO: 2.7 V of supply and "
        "1.6 mA of threshold current, which is what makes a receiver possible "
        "on a board whose only logic rail is 3.3 V."),

    design.MCU_DCDC: band(
        0.70, 1.60, "GBP", 10,
        "TPS560430XFDBVR, SOT-23-6. **The F suffix is the price of this "
        "line**: the PFM version is the same die and a few pence cheaper, and "
        "design.mcu_dcdc_light_load() shows the PFM sibling would fall to "
        "194 kHz in bypass at idle -- under the >= 300 kHz rule spec section "
        "1.1 sets, on a rail the audio domain shares. The state matters: in "
        "circuit the relay coils hold this rail continuous, and bypass is "
        "where they let go."),

    design.MCU_DCDC_L: band(
        0.30, 0.90, "GBP", 25,
        "Bourns SRN6045TA-150M, 15 uH, 6.0 x 6.0 mm shielded. Table 1 of the "
        "switcher's datasheet asks for 18 uH at 5 V and this series does not "
        "make one; 15 is inside the +/-20 % the table's own column heading "
        "gives and 22 is 0.4 uH outside it. What the part is chosen against "
        "is its Isat of 3.8 A against a 1.4 A peak current limit, which is "
        "section 9.2.2.4's rule and 2.7x of it."),

    # The passives the block adds. Same classes as everything above them.
    "88k7 1%": band(0.01, 0.05, "GBP", 100, "0805 1%"),
    "22k1 1%": band(0.01, 0.05, "GBP", 100, "0805 1%"),
    "1k 1%": band(0.01, 0.05, "GBP", 100, "0805 1%"),
    "390R 1%": band(0.01, 0.05, "GBP", 100, "0805 1%"),
    # CA-033's own tolerances, and the wattage is the reason the 33 ohm is
    # called out: "RA 33 ohm 5% 0.5W". An 0805 is 0.125 W and the loop puts
    # 33 x 5.5 mA squared = 1 mW through it, so the specification's figure is
    # about a *shorted* output rather than about this current.
    "33R 5%": band(0.01, 0.05, "GBP", 100, "0805 5%"),
    "10R 5%": band(0.01, 0.05, "GBP", 100, "0805 5%"),
    "4u7/50V X7R": band(0.08, 0.30, "GBP", 25,
                        "1210 X7R at 50 V, 2.5 mm body. It was a 2u2 and the "
                        "DC bias curve is why -- see design.MCU_DCDC_CIN"),
    "22u/16V X5R": band(0.08, 0.30, "GBP", 25, "1210 X5R"),

    # -- not chosen --------------------------------------------------------
    None: NONE,
}

# Connectors are priced by part number rather than by value, because the value
# is what the silkscreen says. The mixer does the same thing -- its J11/J13/J15
# read "TO JACKS 1/2", "3/4", "5/6" -- and a builder reading CH1..CH6 off six
# identical headers is the point of them. One part, one price, six labels.
# **The 1x03 line went and came back, and both moves were the check working.**
# It was the mixer's own CONN_MPN[3] on J11; J11 grew to five ways when the
# fail-safe needed a pin for its 10 kHz drive with a ground either side, and
# the stale-entry half of check() said so -- a price for a part nobody fits is
# a line that will never be ordered and hides the fact that a connector
# changed. The controller brings five of them back: MIDI in and out, the
# expression pedal, the boot header and SWD are all three-conductor.
#
# **And the 1x05 line has gone the same way, in the same run.** J9 to J13 were
# five of them, standing in for a controller on another board; the controller
# is on this one and nothing here is five ways any more. The entry was left in
# for a moment on the argument that an unused price is what makes an absence
# visible -- and check() refused it in the same breath, which is the better
# answer: the record of a part leaving belongs in a sentence like this one,
# and the table is for parts somebody is going to buy.
PRICES_BY_MPN = {
    "61300311121": band(0.30, 0.75, "GBP", 10,
                        "Wurth WR-PHD 1x03 vertical, gold-plated: "
                        "CONN_MPN[3]. Five on this board, all of them the "
                        "controller's: MIDI in and out, the expression "
                        "pedal, boot/reset and SWD. Three conductors is what "
                        "a TRS jack and a DIN's two used pins both want."),
    "61300211121": band(0.25, 0.60, "GBP", 10,
                        "Wurth WR-PHD 1x02 vertical, gold-plated: CONN_MPN[2]. "
                        "Two ways because the loom is a shielded pair -- the "
                        "shield lands at the mixer end only, so it has no pin "
                        "here. See design.FRONT_R."),
}


def price_for(value, mpn):
    """Value first, then part number. A connector's value is its label."""
    if value in PRICES:
        return PRICES[value]
    return PRICES_BY_MPN.get(mpn)

# **RELAY_ENVELOPE was here and there is no unpriced line left.** It was a
# representative signal DPDT latching relay at GBP 2.50-5.00 -- an envelope so
# the board could be budgeted while the part stayed unchosen -- and twelve of
# them were the largest single cost on the board. Deleting the coarse pad takes
# the BOM from GBP 47-96 to GBP 16-30, which is two thirds of it, and takes the
# only line that had a price without a part number with it.
#
# The mechanism stays: `lines()` still prices a value of None through
# `price_for()`, which returns None, and `check()` still refuses a line that has
# neither a part number nor a declaration in design.UNSPECIFIED. The next
# unchosen part -- the DC-DC, the ADC, the bypass relay -- lands on the same
# path.

# USD to GBP, for the total only, and stated rather than folded in silently.
# Two lines are quoted in dollars because that is the currency the figures were
# found in; converting them would hide that.
USD_GBP = None          # deliberately not set: see totals()


def lines():
    """BOM lines, grouped by value and footprint, in reference order."""
    groups = collections.defaultdict(list)
    for ref, part in design.PARTS.items():
        if not part.in_bom:
            continue
        groups[(part.value, part.footprint, part.mpn)].append(ref)

    def sort_key(ref):
        head = "".join(c for c in ref if c.isalpha())
        tail = "".join(c for c in ref if c.isdigit())
        return head, int(tail or 0)

    out = []
    for (value, footprint, mpn), refs in groups.items():
        refs.sort(key=sort_key)
        active = footprint is None or "SO" in (footprint or "")
        price = price_for(value, mpn)
        out.append({
            "refs": refs,
            "value": value,
            "footprint": footprint,
            "mpn": mpn,
            "fitted": len(refs),
            "order": len(refs) + (SPARE_ACTIVE if active else SPARE_PASSIVE),
            "price": price,
            "unspecified": value in design.UNSPECIFIED,
        })
    return sorted(out, key=lambda row: sort_key(row["refs"][0]))


def totals(rows):
    """Extended cost, per currency, as a range.

    Kept per currency rather than converted. Two lines were priced in dollars
    because that is the currency they were found in, and folding them into a
    sterling total at a rate nobody looked up would turn two honest figures
    into one invented one.
    """
    out = collections.defaultdict(lambda: [0.0, 0.0])
    unpriced = []
    for row in rows:
        price = row["price"]
        if price is None or price.low is None:
            unpriced.append(row)
            continue
        out[price.currency][0] += price.low * row["fitted"]
        out[price.currency][1] += price.high * row["fitted"]
    return dict(out), unpriced


def check(rows):
    """Every line has a part number and a price, or says why it has neither."""
    problems = []
    for row in rows:
        if not row["mpn"] and not row["unspecified"] and row["value"] is not None:
            problems.append(f"{row['refs'][0]}: no MPN and not in UNSPECIFIED")
        if row["price"] is None:
            problems.append(
                f"{row['refs'][0]} ({row['value']!r}): no entry in PRICES -- "
                f"a part number without a price is half a BOM line")
    stale = sorted(set(PRICES) - {r["value"] for r in rows} - {None})
    stale += sorted(set(PRICES_BY_MPN) - {r["mpn"] for r in rows})
    if stale:
        problems.append(f"PRICES has entries for nothing on the board: {stale}")
    return problems


def write_csv(rows):
    # **lineterminator is "\n" so that the file this writes is the file git
    # stores.** csv.writer defaults to CRLF, and this repository is committed
    # with core.autocrlf=input, so the blob is LF -- which made a freshly
    # generated BOM show as modified in `git status` after every run, with an
    # empty `git diff` underneath it. Nothing was wrong with the content and
    # that is the point: a tracked artefact that is dirty on every run is one
    # whose status says nothing, which is PDF_EPOCH's argument arriving at the
    # one generated file nobody had applied it to.
    path = OUT / "cv-module-bom.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["Reference", "Value", "Footprint", "MPN", "Fitted",
                         "Order", "Unit low", "Unit high", "Currency",
                         "Qty break", "Basis", "Source"])
        for row in rows:
            price = row["price"]
            writer.writerow([
                ",".join(row["refs"]), row["value"] or "NOT CHOSEN",
                row["footprint"] or "", row["mpn"],
                row["fitted"], row["order"],
                "" if price.low is None else f"{price.low:.2f}",
                "" if price.high is None else f"{price.high:.2f}",
                price.currency, price.qty or "", price.basis, price.source,
            ])
    return path


def write_shopping(rows):
    path = DOCS / "SHOPPING.md"
    lines_out = [
        "# cv-module: what to buy, and from where",
        "",
        "Generated by `gen_bom.py`. Quantities are for **one board**.",
        "",
        "The convention is the mixer's, inherited rather than invented: "
        "**Mouser UK catalogue searches keyed on the manufacturer's part "
        "number**, not product-page deep links, because \"a search survives a "
        "part being re-listed, which a deep link does not\". **These links "
        "have not been opened.** A guessed Digi-Key product URL tried while "
        "writing this file resolved to a HIWIN linear rail, which is the "
        "failure that warning describes.",
        "",
        "The `order` column carries spares on the mixer's rule: "
        f"{SPARE_PASSIVE} spare of each passive, {SPARE_ACTIVE} of each active.",
        "",
        "## The basis column, and why the totals are a range",
        "",
        "| basis | meaning |",
        "|---|---|",
        "| `read` | a page was fetched in this session and states this figure |",
        "| `snippet` | a search result quoted a distributor's figure; the page itself was not opened |",
        "| `band` | a typical band for the class at the stated quantity. **Not read from anything.** |",
        "| `none` | the part is not chosen, so it has no price by construction |",
        "",
        "Only one line on this board is `read`. That is worth stating plainly "
        "rather than letting a tidy table imply otherwise.",
        "",
        "## Lines",
        "",
        "| Ref | Value | MPN | Fitted | Order | Unit | Basis | Mouser UK |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        price = row["price"]
        refs = row["refs"]
        span = (f"{refs[0]}–{refs[-1]}" if len(refs) > 2
                else ", ".join(refs))
        if price.low is None:
            unit = "—"
        elif price.low == price.high:
            unit = f"{price.currency} {price.low:.2f}"
        else:
            unit = f"{price.currency} {price.low:.2f}–{price.high:.2f}"
        mpn = row["mpn"] or "**not chosen**"
        link = (f"[search](https://www.mouser.co.uk/c/?q={row['mpn']})"
                if row["mpn"] else "—")
        lines_out.append(
            f"| {span} | {row['value'] or 'NOT CHOSEN'} | `{mpn}` | "
            f"{row['fitted']} | {row['order']} | {unit} | {price.basis} | "
            f"{link} |")

    sums, unpriced = totals(rows)
    lines_out += ["", "## Totals, per currency, fitted quantities", ""]
    for currency, (low, high) in sorted(sums.items()):
        lines_out.append(f"- **{currency} {low:.2f} – {high:.2f}**")
    lines_out += [
        "",
        "Kept per currency rather than converted: two lines were priced in "
        "dollars because that is the currency the figures were found in, and "
        "folding them into a sterling total at a rate nobody looked up would "
        "turn two honest figures into one invented one.",
        "",
        "## Notes per line",
        "",
    ]
    for row in rows:
        if row["price"].note:
            refs = row["refs"]
            span = (f"{refs[0]}–{refs[-1]}" if len(refs) > 2
                    else ", ".join(refs))
            lines_out.append(f"**{span}** — {row['price'].note}")
            lines_out.append("")

    lines_out += ["## Not on this BOM", ""]
    lines_out.append("The deferred blocks, each with its reason. None of them "
                     "is costed here, so the totals above are a floor for the "
                     "module and not its price.")
    lines_out.append("")
    for block, reason in sorted(design.DEFERRED.items()):
        lines_out.append(f"- **{block}** — {reason}")
    path.write_text("\n".join(lines_out) + "\n")
    return path


def main():
    OUT.mkdir(exist_ok=True)
    DOCS.mkdir(exist_ok=True)
    rows = lines()
    problems = check(rows)
    print(f"bom: {len(rows)} order lines, "
          f"{sum(r['fitted'] for r in rows)} placements")
    for problem in problems:
        print(f"  {problem}")

    sums, unpriced = totals(rows)
    bases = collections.Counter(
        r["price"].basis if r["price"] else "MISSING" for r in rows)
    print(f"  provenance: " + ", ".join(f"{k} {v}" for k, v in sorted(bases.items())))
    for currency, (low, high) in sorted(sums.items()):
        print(f"  total {currency} {low:.2f} - {high:.2f}")
    if unpriced:
        print(f"  unpriced: {[r['refs'][0] for r in unpriced]}")

    # Both paths named relative to the repo, not by .name, because this file now
    # writes into two directories and "wrote SHOPPING.md" no longer says where.
    for path in (write_csv(rows), write_shopping(rows)):
        print(f"  wrote {path.relative_to(HERE)}")
    if problems:
        raise SystemExit(f"{len(problems)} problems")


if __name__ == "__main__":
    main()
