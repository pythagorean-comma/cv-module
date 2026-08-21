# The footprint audit — a land pattern against the part's own drawing

**Not generated.** A decision-and-measurement record, in the shape
`fabrication-class.md` and `routing-tool.md` have: what was checked, against
which document, and what it found.

Started 2026-08-21, before ordering. **Three parts failed and one of them could
not be fitted at all. All three are fixed in `design.py`; the board needs one
sync in KiCad before a package can be written again.**

| | was | is | costs |
|---|---|---|---|
| `BYPASS_RELAY` | `G6S-2 DC5` | **`G6S-2F DC5`** | nothing — same land, same pin map, same ratings |
| `ENV_DIODE`'s MPN | `1N4148WS-7-F` | **`1N4148W-7-F`** | nothing — the value string already said `1N4148W` |
| the five BAT54s | `Diode_SMD:D_SOD-123` | **`Package_TO_SOT_SMD:SOT-23`** | a symbol, a pin map, and a re-route of five nets |

**The board is synced and the loop is closed.** KiCad's Update PCB from
Schematic put the new lands on it; `krt.py` re-routed the affected scope;
`verify.py` passes and `gen_fab.py` has written the package again. What that
took, in order, is worth keeping because none of it was on the list:

| | |
|---|---|
| **the scope was wider than the five diodes** | the moved pads landed under other nets' copper. `MISO`, `IRQ`, `MOSI` and `PWM5` were shorting to them, so the scope was **derived from the DRC report** rather than guessed: `FSAC FSG FSD VMOD MISO IRQ MOSI PWM5` |
| **`--nets` takes patterns, not a comma list** | `--nets "A,B,C"` is one pattern that matches nothing, and `route.py` says so and exits 2 rather than routing nothing quietly |
| **`MDGND` was excluded and had to be, so one pad stayed open** | `D801`'s anode is the only ground pad among the five. Its old stitch went east from a pad that has moved, and KiCad re-netted that via to `FSAC` when the new cathode pad landed on it — so it read 0.00 mm against the `MDGND` pour. One via and one stub, placed at (42.35, 168.0775), 0.76 mm from the pad and clear of the body |
| **the router's gate refused the first run and was right** | `disconnected_pads_before: 10, after: 1` — and the 1 was that stitch. It committed on the second run |

Nothing else in the design moved: no value, no net, no other footprint. The
board is **5116 segments and 992 vias**, one width, one via size, no signal
copper on either plane, 0 DRC and 0 unconnected.

**And the last twelve violations were silkscreen, from a rule reading a proxy.**
`gen_pcb.py` puts a designator on `F.Fab` rather than on silk when the part has
two pads, because 128 of this board's parts are smaller than their own
reference text. A SOT-23 has **three** pads — the middle one is not connected —
so the rule stopped applying, five designators were promoted onto silk, and DRC
found them colliding with neighbours that had not moved a micron. The test
counts the terminals the *design connects* now, which is what "two-terminal
part" means; `Q801`'s SOT-523 has three and keeps its designator on silk, which
is right, because a transistor is oriented by hand.

---

## Why nothing in this repository could have caught these

Every instrument here reads an artefact this project wrote. `verify.py`
compares KiCad's own netlist to `design.py` by name *and pin*, which catches a
wire that missed its endpoint and a polarised part drawn backwards.
`Design.check_order_codes()` decodes a ceramic's part number and compares its
case, dielectric, voltage and capacitance against the value string and the
land. `gen_pcb.check_courtyards()` holds `placement.SIZE` to KiCad's own
courtyard.

**None of them opens a datasheet.** The question "is this KiCad land pattern
the pattern this manufacturer draws for this part number" is answered by a
document outside the repository, and until now nobody had asked it. The
netlist comparison is specifically unable to help: it compares pad number to
pin number, and a pad numbered 1 on the wrong package is still pad 1.

That is this project's oldest shape once more — **a claim about a part,
checked against a model of the part** — and here the model is KiCad's library
and the part is what arrives in a bag.

---

## The method, three questions per part

1. **Does the part number name the package the land pattern is for?** Read off
   the manufacturer's own datasheet or part page, not a distributor's summary.
2. **Does the pin *numbering* the netlist uses match the datasheet's terminal
   arrangement** — and for a part with more than one variant, the *right
   column* of it?
3. **For the one hand-drawn footprint, do the coordinates match the drawing?**
   Computed from the generated `.kicad_mod`, not read off a screen.

---

## Results

| part | fitted land | verdict |
|---|---|---|
| **TMR 6-2422WI** | `cv:TRACO_TMR-6-xxxxWI_Dual_THT` (ours) | ✅ **passes on every measurement** — see below |
| **G6S-2 DC5** | `Relay_SMD:Relay_DPDT_Omron_G6S-2F` | ❌ **the part number is the through-hole model** |
| **BAT54-7-F** ×5 | `Diode_SMD:D_SOD-123` | ❌ **SOT-23 part on a two-pad land** |
| **1N4148WS-7-F** ×13 | `Diode_SMD:D_SOD-123` | ❌ **SOD-323 part on a SOD-123 land** |
| **TLP2761(TP,E)** | `Package_SO:SO-6L_10x3.84mm_P1.27mm` | ✅ package designation is SO6L |
| **PMEG2010AEH,115** | `Diode_SMD:D_SOD-123F` | ✅ SOD-123F, and `SOD123F_FP`'s comment already reasons about the difference |
| **3403.0168.11** | `Fuse:Fuse_Schurter_UMT250` | ✅ name and series match; dimensions not yet checked |
| **SRN6045TA-150M**, **744222**, **SC0915** | vendor-named KiCad footprints | ✅ series matches; dimensions not yet checked |

---

## The one we drew ourselves passes, and it is worth saying how completely

`gen_project.TMR6WI` generates `out/cv.pretty/TRACO_TMR-6-xxxxWI_Dual_THT.kicad_mod`
from the outline drawing on page 4 of the TMR 6WI datasheet, Rev. November 7
2023. Checked against that page:

| | datasheet | generated | |
|---|---|---|---|
| body length | 21.8 (0.86) | 19.8 − (−2) = **21.8** | ✅ |
| body width | 9.1 (0.36) | 5.6 − (−3.5) = **9.1** | ✅ |
| pin 1 inset | 2.0 (0.08) | pad 1 at x = 0, left edge at −2.0 | ✅ |
| pin string | 2.0 / 2 × 2.54 / 5.08 / 3 × 2.54 | 0, 2.54, 5.08, **10.16**, 12.7, 15.24, 17.78 | ✅ |
| leftover at the far end | 21.8 − 19.78 = 2.02 | 19.8 − 17.78 = **2.02** | ✅ |
| pin row from the near long edge | 3.5 (0.14) | pads at y = 0, edges at −3.5 and +5.6 | ✅ |
| pin 4 | **omitted** | absent | ✅ |
| pin cross-section | 0.50 × 0.25 | 1.0 mm drill, 1.6 mm pad | ✅ 0.30 mm annulus, 0.44 mm of slack on the 0.559 mm diagonal |

**The error this could most plausibly have made is not made.** The pin row is
3.5 mm from one long edge and 5.6 mm from the other; a generator that centred
the body on the pads would have been 1.05 mm out on each side, and the
courtyard is what `placement.check_courtyard_gap()` walks. It is not centred.

**And the pinout is the right column of two.** The datasheet's Pinout table has
separate Single Output and Dual Output columns, and they differ at exactly the
two pins that matter: single is `7 −Vout, 8 NC`, dual is `7 Common, 8 −Vout`.
`design.SUPPLY_PINS` is the dual column, which is the ±12 V part this design
fits. Read off the board:

| pad | datasheet, dual | net on the board |
|---|---|---|
| 1 | −Vin (GND) | `IGND` |
| 2 | +Vin (Vcc) | `VIN_P` |
| 3 | Remote | `IGND` |
| 5 | NC | *(none)* |
| 6 | +Vout | `VA_RAW` |
| 7 | Common | `MDGND` |
| 8 | −Vout | `VN_RAW` |

**Pin 3 to `IGND` is the ON state and not an accident.** Page 3, Remote
Control: *"Voltage Controlled Remote (passive = on) — On: 0 to 0.5 VDC or open
circuit; Off: 3 to 12 VDC; Refers to 'Remote' and '-Vin' Pin."* Tying it to
−Vin asserts the defined ON state rather than relying on the open-circuit one.

Four other numbers on the same pages corroborate values already in `design.py`:
capacitive load 330 µF per rail, switching frequency 522–638 kHz (580 typ),
isolation capacitance 50 pF max, cross regulation 5 % max. And the recommended
input fuse — *"24 Vin models: 1'600 mA (slow blow)"* — is quoted at
`design.py:5408`, so `SUPPLY_FUSE_A = 1.6` is the vendor's own figure and not
a derivation that happened to land on it.

---

## Finding 1 — `G6S-2 DC5` is the through-hole relay

**Omron's G6S datasheet, page 5, Dimensions.** The single-side stable models
are listed in three rows and the third is a different mounting:

* **G6S-2F / G6S-2F-Y** — gull-wing terminals, *"Mounting Dimensions (Top
  View)"*, terminal arrangement drawn **top view**;
* **G6S-2G / G6S-2G-Y** — surface-mount, a different terminal bend;
* **G6S-2 / G6S-2-Y** — ***"PCB Mounting Holes (Bottom View) — Eight, 1-dia.
  holes"***, straight pins, terminal arrangement drawn **bottom view**.

`design.BYPASS_RELAY` is `"G6S-2 DC5"`; `design.RELAY_FP` is
`Relay_SMD:Relay_DPDT_Omron_G6S-2F`. So the part number names the model that
needs **eight 1 mm drilled holes** and the land pattern is the surface-mount
model's. Three relays, 24 terminals, and the fabrication package contains no
holes for any of them.

**The design's own comment is where the confusion lives:** *"fully sealed, in
the surface-mount G6S-2F body"* treats `-2F` as a body style shared by the
`-2`. The datasheet treats them as different models with different mountings.

**Everything else about the choice is right, including the pin map.**
`design.py:6558` cites *"page 5 of Omron's own G6S data sheet, top view,
single-side stable"* — and top view is the **G6S-2F** row. The terminal
numbers, the ratings table (28.1 mA, 178 Ω at 5 VDC), and the bifurcated
crossbar Ag (Au-alloy) contact material are all the family's.

**Fixed: `G6S-2F DC5`.** Two characters in `design.BYPASS_RELAY`. It changes no
copper, no pin number and no derived figure; every reading in `coil_budget()`
and `bypass_state()` stands.

---

## Finding 2 — `BAT54-7-F` is a SOT-23 part on a two-pad land

**Diodes Incorporated DS11005 Rev. 21-2, page 1, Mechanical Data: "Case:
SOT-23."** The document is titled *BAT54 /A /C /S* and all four are SOT-23,
three-terminal. `design.py` fits five of them — `D801`, `D802`, `D813`,
`D823`, `D833` — on `Diode_SMD:D_SOD-123`, which is a **two-pad** land at
2.6 mm centres.

This is the one that cannot be assembled: a three-lead part on 0.95 mm lead
pitch does not go on two pads 2.6 mm apart in any orientation.

**It is also the fix with a real choice in it**, because the part was picked
for a number. `CLAMP_DIODE`'s note is that the pump wants low *leakage* and
does not care about forward drop, and the BAT54's 2.0 µA max at 25 V is that
number:

* **change the land to SOT-23** — keeps the part and every figure derived from
  it, and costs placement space (SOT-23 is larger than SOD-123) plus a
  re-route of five nets, which `krt.py --nets` does in seconds;
* **change the part to a Schottky that exists in SOD-123** — keeps the board,
  and puts the leakage figure back on the bench, because leakage is what the
  part is there for.

**Fixed by the first**, which is the smaller claim: `SOT23_FP` at all five
sites, `SOT23_DIODE_PINS = {"A": 1, "K": 3}` from Nexperia's Table 2, and a
`cv:BAT54` symbol — `Device:D` with its two pins renumbered onto the package by
`patch_symbol()`, because a symbol carries a pin map and a footprint carries a
body. Pin 2 is not connected, which is what the package says it is.

---

## Finding 3 — `1N4148WS-7-F` is SOD-323, and the value string already said so

Diodes Incorporated's own part page and datasheet title the `1N4148WS` as
**SOD-323** (DS30097, *1N4148WS / BAV16WS*); the SOD-123 member of the family
is the **`1N4148W`** (DS30086, *BAV16W / 1N4148W*). Thirteen parts —
`D151`–`D652` and `D805` — carry MPN `1N4148WS-7-F` on `Diode_SMD:D_SOD-123`.

**The two halves of the same row disagree and one of them is right:** the
value string is `"1N4148W"` and the footprint is that part's land. Only the
MPN carries the extra `S`.

A SOD-323 body on a SOD-123 land is not the hard failure the BAT54 is — the
part is smaller than the pads and would probably reflow — but it is a part
number that names something other than what the board is drawn for, on the
envelope rectifier's own diodes.

**Fixed: `1N4148W-7-F`.** One character, and it makes the MPN agree with the
value string that was right all along.

---

## Two things the fixes found, and neither was about a footprint

**`symlib.flatten()` promised a copy and returned a shallow one.** Its
docstring in both repositories says *"a self-contained copy of a symbol"*, and
every list it builds shares the unit bodies inside `_library_cache` — which is
where the pins live. So renumbering a pin on a flattened symbol renumbers it in
the cache, and the next flatten of that source returns the mutated one. It had
no symptom for as long as each borrowed symbol had exactly one borrower, which
was true until `Device:D` was borrowed twice — as itself and as `cv:BAT54`. Six
envelope diodes then failed on a missing pin 2, which is the *loud* version;
the quiet version is `_repin()` or `_set_property()` changing a symbol somebody
else is still drawing with. `flatten()` deep-copies now, and
`toolchain/PROVENANCE.md` records it as ours.

**`check_board_is_the_design()` compared refs and not lands.** Its own docstring
called itself one of "the only things standing between a stale board and a
fabrication package" — and five parts could move from a two-pad land to a
three-pad one with every check in `verify.py` staying green, because the refs
had not changed, the netlist comes from the generated sheet, and DRC agrees
with the board's own stale embedded netlist. **A ref is not a part**: a part is
a ref, a value and a land, and the land is the half that decides whether the
thing in the bag can be soldered to the thing on the board. It compares lands
now, `test_verify.py` plants one, and `gen_fab.refusals()` reads it — so the
sentence in that docstring is executable at the one place where it has to be.

And the harness caught its own: three planted mutations named pins `1` and `2`
on parts that now have `1` and `3`, so they planted nothing. `dead_mutations()`
named all three before a case ran, which is the third time that guard has
earned its place. They ask `design.diode_pins()` now — the same function the
check asks — so a package change moves both ends of the test together.

## Sourcing, checked the same way and on the same day

Three part numbers came back from a distributor as obsolete or unstocked. Each
was checked against the manufacturer rather than taken on trust, and all three
substitutions hold:

| was | is | what the manufacturer says |
|---|---|---|
| `GRM216R71H223KA01D` | **`CEU4J2X7R1H223K125AE`** | Murata's part carries an **obsolete** life-cycle code and RS no longer stocks it. TDK's product page gives the replacement as 22 nF, 50 V, X7R, 2.0 × 1.25 × 1.25 mm — 0805, on the land already fitted |
| `NCP1117DT50G` | **`NCP1117DT50RKG`** | onsemi's own ordering information: the DT50G is 75 per rail and **obsolete**; the DT50RKG is 2500 on tape and reel and **active**. Same die, same DPAK-3, same fixed 5.0 V at 1 A |
| `OPA1644AIDR` | **`OPA1644AID`** | **not obsolescence — stock.** TI lists both as ACTIVE; `D` is the SOIC-14 and `R` is the 2500-piece reel. Distributors have the tube and quote no date for the reel, and nine pieces is a tube's business either way |

**The repository's own check agrees, which is the point of having it.**
`decode_capacitor_code()` reads `CEU4J2X7R1H223K125AE` as 0805 / X7R / 50 V /
22 nF and compares all four to the value string and the land —
independently of anything read on a web page. It had to be taught the `CEU`
prefix first: it is TDK's commercial series and numbers its cases exactly as
CGA, CNA and CNC do, so it joined that pattern rather than getting one of its
own. **An unparsed code is reported and counted, never passed**, so a
re-sourcing pass cannot quietly introduce a part number nothing decodes.

### The fourth was not obsolete, and the check is the same either way

`PMEG2010AEH,115` was reported obsolete as well. **It is not.** Nexperia's own
product page gives its status as **Production**, and RS UK lists tens of
thousands in stock for next-day delivery; what is true is that DigiKey has it
out of stock and on backorder. That is a distributor's position read as a
lifecycle status, which is now the second time in one afternoon — the
`OPA1644AIDR` was the first. **The manufacturer's page is the one that says
whether a part exists; a distributor's page says whether that distributor has
one.**

The proposed substitute, onsemi's `NRVB120VLSFT1G`, was measured anyway, so
that the work is not repeated the day stock does dry up:

| | fitted `PMEG2010AEH` | proposed `NRVB120VLSF` |
|---|---|---|
| package | SOD-123F, on `Diode_SMD:D_SOD-123F` | **SOD-123FL, CASE 498** — recommended land 1.25 × 1.22 mm pads on a 4.20 mm outer span, against this board's 1.1 × 1.1 on 3.90 mm. KiCad ships no SOD-123FL footprint |
| V_F at the clamp's 36 mA | 259 mV, interpolated | **≤ 275 mV** — its table starts at 100 mA, and `_schottky_vf()` refuses to extrapolate below a table's first point, so the 100 mA maximum stands as a bound that cannot be wrong: a Schottky's drop only falls as the current does |
| `clamp_gain()` | +6.35 dB, **1.49 dB** inside the mixer's headroom | +6.74 dB, **1.10 dB** inside it — still fits |
| D806 on VSYS | V_F 0.2795, VSYS 4.720 V | V_F 0.275, VSYS 4.725 V — no consequence |
| reverse leakage | 50 µA max at V_R = 5 V | **0.60 mA at 25 °C and 15 mA at 85 °C**, at the rated 20 V |

**The leakage is the one number that gets worse, and it is the one nothing
here computes.** The tolerance for it is a prose argument — D803's leakage
lands on VREFN, a driven node inside U8's feedback loop, so the amplifier
absorbs it — and that argument was written against 50 µA. The two figures are
not directly comparable (5 V against 20 V), and at D803's actual 2.5 V of
reverse bias the onsemi part will draw far less; but the datasheet offers only
a curve there, and `bench.md`'s rule is that a number read off a plotted curve
is not a reading.

**Production is not the same as buyable, and the second look said so.** RS's
stock carries a **minimum order of 40** for a board that fits two, and several
distributors quote no stock before 2027. So the substitution question is real
after all, and three candidates were put through the same filter the fitted
part passed — `clamp_vf_ceiling()` at **320 mV**, against each datasheet's own
**maxima**, because that is the rule `CLAMP_VF_TABLE` is written to.

| candidate | land | V_F bound at 36 mA | `clamp_gain()` margin | reverse leakage |
|---|---|---|---|---|
| `PMEG2010AEH` *(fitted)* | SOD-123F | 259 mV, interpolated from a **10 mA** maximum | **+1.49 dB** | 50 µA **max** at 5 V |
| **Toshiba `CRS06`** | **SOD-123F — Toshiba's own recommended land is 1.2 × 1.2 mm pads on 2.8 mm centres, and this board's is 1.1 × 1.1 at ±1.4** | **360 mV** — its only maximum is at **1 A** | **−0.98 dB, over** | 60 µA **typ** at 5 V; 1.0 mA max at 20 V |
| onsemi `NRVB120VLSF` | SOD-123FL — 1.25 × 1.22 pads on a 4.20 mm span, and KiCad ships no such land | 275 mV, its lowest maximum being at 100 mA | **+1.10 dB** | 0.60 mA max at 25 °C, 15 mA at 85 °C, at 20 V |
| Diotec `SKL12` | ~SOD-123FL | **550 mV** — its only forward-voltage figure at all is at 1 A | **−5.64 dB** | 200 µA max at 20 V |

**The CRS06 is the near miss and it is worth being precise about why.** Its land
is this board's, unchanged; its leakage is the best of the three; and its
*typical* forward drop — 0.20 V at 100 mA — is better than the fitted part's
maximum. It fails on one thing only: **Toshiba publishes no maximum below 1 A**,
so the strongest bound its datasheet supports at 36 mA is the 360 mV it
guarantees at a current 28 times higher. On typicals it clears the ceiling by
2.94 dB; on maxima it exceeds it by 0.98 dB. This project does not resolve that
gap by choosing the friendlier column — that is `CLAMP_VF = 0.3` again, which
is the assumption that put a BAT54 here and cost 5.5 dB.

**And the arithmetic that makes the whole question smaller.** The minimum buy
is 40 pieces of a part this repository prices at **GBP 0.10–0.30**: **GBP
4–12** for 37 spare diodes, which is less than the single spare converter
deleted the same afternoon and less than a day of anybody's time. Where a
minimum order is 40 of something cheap, the cheapest fix is to buy 40.

**Decided: the PMEG stays and the 40 get bought** — the reason being the price
of the alternative rather than the price of the part. The order list still says
3, because it counts what the board needs plus the spares rule and leaves reels
and minimums to the basket where their numbers are visible; the 40 is a fact
about a distributor, and it is written on the BOM line so that the next stock
scare does not re-run this search.

If a second source is ever needed, `NRVB120VLSF` is the one that qualifies on
stated maxima and costs a hand-drawn SOD-123FL land. The `CRS06` becomes
available the moment somebody measures its forward drop at 36 mA and records it
as a `MEASURED` value with a range — which is a five-minute bench job once one
is in hand, and exactly what that mechanism is for.

### And the quantities were wrong, by more than the board costs

Asking why a board that fits one converter was ordering five found a bug rather
than a policy. `gen_bom.py` chose the spares count with `"SO" in footprint` —
meaning to catch SOIC, SOT and SOD — so **every part whose land pattern does
not contain those two letters was classified as a chip passive** and bought
four spares:

| | |
|---|---|
| TMR 6-2422WI | 1 fitted, **5 ordered**, GBP 18.16 each — **GBP 72.64 of spare converter** |
| SC0915 (Pico) | 1 fitted, 5 ordered |
| G6S-2F DC5 | 3 fitted, 7 ordered |
| both inductors, the inlet fuse, an SMA diode, twelve pin headers | all 1 fitted, 5 ordered |

Spares were **GBP 138–190 against a fitted parts cost of GBP 60.67–96.94** —
more than the board — and nothing printed that number, because `totals()`
reported the fitted cost while the CSV carried the order quantity. Two figures
about one basket with nothing comparing them, which is this repository's oldest
complaint about itself arriving at the money.

The class is decided by the land now — `design.R_FP`, `design.C_FP`,
`design.C_FILM_FP`, the three chip lands `design.py` owns — and `NO_SPARE`
holds the parts where even one spare is not bought, each with its reason.
`spare_alerts()` reports every other line whose spares cost more than
`SPARE_ALERT_GBP`, on every run, so that list cannot go stale in silence.
Spares are **GBP 25.32–47.22** now.

## The pin maps, worst first — six checked, six correct

**This is the audit that matters most and the one nothing here can perform.**
`verify.py` compares `design.py`'s netlist to KiCad's own export by name *and*
pin — but both descend from the same pin map, so a wrong map passes every
check in the repository. KiCad's library stops being an independent opinion
exactly where a symbol was borrowed from a *different part* and its pins
renamed, which is twelve of the symbols on this board.

Checked against the manufacturer's own pin table, 2026-08-21:

| part | symbol borrowed from | verdict |
|---|---|---|
| **MCP3564** | `Analog_ADC:ADS131M04xPW` — a different manufacturer's ADC, sixteen pins renamed | ✅ **20/20**. DS20006181C page 3, diagram C: AVDD 1, AGND 2, REFIN− 3, REFIN+ 4, CH0–CH7 on 5–12, CS 13, SCK 14, SDI 15, SDO 16, IRQ/MDAT 17, MCLKIN 18, DGND 19, DVDD 20 |
| **MAX6126** | `Reference_Voltage:ADR4525` | ✅ **8/8**, 19-2647 page 16. And pins 5 and 8 are *"Internally Connected. **Do not connect anything to these pins**"* — this design leaves both open. The Kelvin wiring matches the datasheet's own instruction: OUTF shorted to OUTS at the load, GNDS brought to the load's ground point |
| **TPS560430XF** | `Regulator_Switching:LMR50410` | ✅ **6/6**, SLVSE22B §6: CB 1, GND 2, FB 3, EN 4, VIN 5, SW 6. §5's Device Comparison Table independently confirms the suffix: `XF` is the 1.1 MHz, FPWM, adjustable part, which is the whole argument for it |
| **NCP1117-5.0** | `Regulator_Linear:AP1117-50` | ✅ **3/3 including the tab.** onsemi: *"1. Adjust/Ground, 2. Output, 3. Input. Heatsink tab is connected to Pin 2."* KiCad's `TO-252-2` numbers the 6.4 × 5.8 mm tab as pad 2, and the design puts V5 there — a tab on the wrong net is a short through the heatsink copper |
| **MCP1700-3.3** | `Regulator_Linear:MCP1700x-330xxTT` | ✅ **3/3**, DS20001826F page 1: 3-Pin SOT-23 is 1 GND, 2 VOUT, 3 VIN. **Package-specific**: the same page numbers SOT-89 and TO-92 differently, so `V5_PINS` serving both regulators is correct only because the fitted suffix is `TT` |
| **Raspberry Pi Pico** | stock symbol, retyped not renumbered | ✅ **40/40** against Figure 2 of the Pico datasheet. All eight grounds on MDGND; VSYS 39, 3V3(OUT) 36, RUN 30; VBUS 40 and 3V3_EN 37 left open, the second correctly, since it has an internal pull-up to VSYS |

**Three things in the Pico's map had to be right and are.** `MISO`, `CS`,
`SCLK` and `MOSI` land on GP16/17/18/19, which is one complete **SPI0** group
rather than a mixture of SPI0 and SPI1 pins that would look identical on a
netlist. `MIDI_TX` and `MIDI_RX` are GP12/GP13, both **UART0**. And the six
PWM carriers are on GP0, GP2, GP4, GP6, GP8, GP10 — **six distinct slices**,
which is exactly what `controller_slices()` requires and what §4.2's phase
stagger is impossible without.

**Nothing was found wrong.** That is worth stating plainly rather than
buried: six maps, ninety-two pins, and every one of them is what its
manufacturer's table says. The three verified earlier the same day — the
TMR 6WI's dual-output column, the G6S's top-view arrangement and the BAT54's
SOT-23 numbering — bring it to nine symbols and one hundred and fifteen pins.

**What is left in this category, and why it is lower risk.** `cv:744222`'s
winding pairing (1-4 and 2-3, the difference between a common-mode choke and
1 mH in series with the supply) is already asserted by
`verify.check_supply()` against the WE-SL2 datasheet's own Schematic block.
`cv:OPA1644` borrows the TL074's symbol, and a quad op-amp's numbering is the
same in both datasheets — `design.LIBS` records it as checked pin by pin
against SBOS484D. `cv:SSI2164` is KiCad's own symbol with output *types*
repinned rather than numbers, so its numbering is still KiCad's and it agrees
with `VCA_PINS`.

## The vendor-specific lands — four checked, four exact

The second audit: the lands whose KiCad footprint is named for a *series*
rather than a part, where "the series matches" is all that had been checked.
Each measured against the manufacturer's own recommended land pattern.

| part | manufacturer's recommended land | KiCad's footprint | |
|---|---|---|---|
| **Würth WE-SL2 744222** | 9.5 mm overall, pads **2.0 × 1.2**, rows **2.54** apart | pads 2.0 × 1.2 at x = ±3.75 → 9.5 overall, rows 2.54 | ✅ **exact, numbering included** |
| **SCHURTER UMT 250** | pads **2 × 3.75**, **6.5** between inner edges → ±4.25 centres | pads 2.0 × 3.75 at ±4.25 | ✅ **exact** |
| **Bourns SRN6045TA** | **6.5** overall, **5.1** tall, **1.8** gap → 2.35 wide at ±2.075 | pads 2.35 × 5.1 at ±2.075 | ✅ **exact** |
| **Raspberry Pi Pico** | Figure 5: **22.58** outer, **16.18** inner, **49.86** tall, 2.54 pitch | columns at ±9.69 with 3.2 × 1.6 pads → 22.58 / 16.18 / 49.86 | ✅ **exact** |

**Three of the four datasheets confirmed figures this repo already carried**,
which is worth as much as the geometry: the WE-SL2's Schematic block gives the
winding pairing `verify.check_supply()` asserts (1-4 and 2-3, each winding
straight across the body); SCHURTER's Variants table gives `3403.0168.11` as
the 1.6 A part with a 300 mV drop at 1.0 In, and its Pre-Arcing table is
`INLET_FUSE_PREARC` verbatim; Bourns' `-150M` row gives 15 µH ±20 %, DCR
71 mΩ, Irms 2.80 A, Isat 3.80 A.

### The Pico's stencil is the detail that could most easily have been missing

Raspberry Pi's Figure 6 is a **paste stencil drawn separately from the
footprint**, and the text says why: *"Through trials with customers, we have
determined that the paste stencil must be bigger than the footprint...  We
recommend paste zones 163% larger than the footprint."* The zones are
**3.80 × 2.20 mm** against 3.2 × 1.6 mm pads — 1.633×, exactly the figure
quoted.

A footprint that ignored that would place, route, pass DRC and reflow badly,
and nothing in this repository would have known: paste is not copper, so no
check here reads it. **KiCad's footprint implements it** — 53 paste-only pads
at 3.8 × 2.2 — and those apertures are present in `fab/cv-module-F_Paste.gtp`,
checked in the exported gerber rather than assumed from the library.

### And one word was overstated

Bourns call the SRN6045TA **semi-shielded**; `design.py` called it shielded.
Nothing computes with it, and the distinction is not nothing on this board: a
semi-shielded part is a ferrite core with a magnetic epoxy coating rather than
a closed magnetic path, so it leaks more flux — and it is a 1.1 MHz switcher's
inductor on a board whose noise argument is in microvolts. Corrected where it
was written.

## The instrument, built: `check_package_codes()`

`Design.check_order_codes()` decodes a ceramic's case, dielectric, voltage and
capacitance and stops at ceramics. **All three findings here were the same
shape one class out** — a package named in a part number, against the package
named in a footprint — so that is what the new check decodes.

`PACKAGE_CODES` is a table of (pattern, package, exact?) rules, each read
first-hand and each **anchored on its vendor's own part numbers**. That anchor
is the rule rather than tidiness: written as a bare suffix, `D$` reads Murata's
`GRM2165C1H122JA01D` as a TI SOIC, and the check then reports a capacitor for
being on an 0805 land. A suffix rule with no vendor in it is not a scheme, it
is a coincidence detector, and it was one for about a minute.

Taught so far: Diodes Incorporated's `1N4148W`/`WS` and the `BAT54` family; TI's
`D`, `DW` and `DBV`; Microchip's `/ST` and `/TT`; onsemi's `DT`; Omron's
`G6S-2F` against the bare `G6S-2`; Yageo's literal `RC0805`; and Panasonic's
ERA numeral. **166 placements checked, 25 unparsed**, and the unparsed list is
printed on every run with a count, because a coverage gap nobody sees is one
that grows.

**All three faults are planted in `test_verify.py` and all three are caught** —
`1N4148WS-7-F` on a SOD-123 land, a SOT-23 part on a two-pad land, and Omron's
through-hole relay on the surface-mount model's footprint. The harness is at
101.

**What it still cannot do is unchanged**: whether a code names a part that
*exists* is a distributor's question, exactly as the ceramic check already
says. And the 25 it cannot parse are not failures of the table — they are
vendors whose part numbers carry no package field at all: Nexperia's `,115` is
a packing code, Toshiba's `(TE85L,Q,M)` a taping code, and Würth, Bourns,
SCHURTER, Traco and Raspberry Pi simply number parts without saying what shape
they are.

### One rule was nearly taught by a search result

Panasonic's ERA numeral covers 26 parts on this board, and the first attempt to
add it leaned on a web search, which answered that *"ERA-6A ... case size
1206"*. Panasonic's own part-number table says **6A is 0805** — AOA0000C307 for
the A type, RDM0000C331 for the V and K — which is what this board fits. A
check taught by a search result is a check taught by nobody, and it would have
reported 26 correct parts as wrong.

## Not yet audited

The passives — 0805 resistors and capacitors on their own lands, where
`check_order_codes()` already decodes case against footprint — and the
dimensions (rather than the series names) of the Würth choke, the Bourns
inductor, the SCHURTER fuse, the Pico module and the SOIC/TSSOP families.
Those are lower risk: a standard package on its own KiCad land, with the
package named in the part number.
