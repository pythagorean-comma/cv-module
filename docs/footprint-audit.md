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

## What this suggests as an instrument

`Design.check_order_codes()` already decodes one vendor family's part numbers
and compares four fields to the value string and the land. **All three
findings here are the same shape one class out**: a package named in a part
number, against the package named in a footprint.

That is mechanisable for exactly the reason ceramics were — a suffix table per
vendor, reported-and-counted when unparsed, never passed silently. It would
have caught the `WS`, the missing `W`, and the missing `F`. What it still
could not do is tell whether a part *exists*, which the existing check already
says is a distributor's question.

## Not yet audited

The passives — 0805 resistors and capacitors on their own lands, where
`check_order_codes()` already decodes case against footprint — and the
dimensions (rather than the series names) of the Würth choke, the Bourns
inductor, the SCHURTER fuse, the Pico module and the SOIC/TSSOP families.
Those are lower risk: a standard package on its own KiCad land, with the
package named in the part number.
