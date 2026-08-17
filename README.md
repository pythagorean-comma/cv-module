# cv-module

Per-string CV generation for a six-string guitar effects box: six analogue VCAs
(SSI2164) set per-string levels, and the audio never enters the digital domain.

The module hangs off the six `RV{n}01` level-control positions of
[`summing-mixer`](../summing-mixer), replacing its per-channel trimmers. That
board is **fabricated**, so this repo consumes its interface at a pinned commit
and never writes to it — see [`contract/PINNED.md`](contract/PINNED.md).

```
6 x Nu capsule -> Nexus-GK -> summing-mixer ---- RV{n}01 socket ---- [this]
                                    ^                                  |
                                    +------------ SIN{n} --------------+
```

## Status

**A spike, and an honest one.** All seven tasks of the brief are complete. Every
number carries its arithmetic, every check can be shown to fail, and everything
guessed is in [`ASSUMPTIONS.md`](docs/ASSUMPTIONS.md).

| | |
|---|---|
| one channel derived | ✅ every value, arithmetic inline |
| the coarse pad | ✅ **struck** — 0.000 dB of system noise for 36 parts |
| netlist | ✅ 225 parts, 144 nets, all pins resolved |
| schematic | ✅ **0 merges, 0 breaks, 0 stranded pins** |
| the verification loop | ✅ `verify.py` reads **KiCad's** netlist, compared by name |
| ERC | ✅ **0 errors and 0 warnings** — `ERC_ALLOWED` is empty |
| the envelope rectifier | ✅ derived, drawn and checked — τ from the transient, not from a target |
| the fail-safe | ✅ drawn: de-energised **is** bypass, and the pump's own rise time is the power-up interlock |
| section 5 constraints | ✅ checked mechanically, 50 planted faults caught |
| deltas against the mixer's own model | ✅ four disagreements, three of them with `00-current-state.md` |
| floorplan, BOM, assumptions | ✅ |
| board | ✅ placed, poured and **86 % routed**, 0 DRC violations. ❌ 67 connections left, named |

Three shared blocks are deferred with reasons in `design.DEFERRED`: controller,
envelope ADC and supply. There were six. The relay drive is not deferred but
deleted, along with the pad it drove; the envelope rectifier and the fail-safe
are drawn. Two parts are `UNSPECIFIED` — the bypass relay and its MOSFET — each
declared by the property that filters it rather than by a guess.

## Run it

Nothing to install. Stdlib only, following the mixer's own rule that "there is
no `requirements.txt` because there is nothing to install". KiCad 10 is not
optional any more: `verify.py` runs `kicad-cli` twice, once for the netlist and
once for ERC, and that is the point rather than a dependency to regret.

```bash
python3 design.py && python3 gen_netlist.py && python3 gen_sch.py \
  && python3 gen_project.py && python3 placement.py && python3 gen_pcb.py \
  && python3 verify.py && python3 test_verify.py \
  && python3 constraints.py && python3 delta.py && python3 floorplan.py \
  && python3 gen_bom.py && python3 gen_assumptions.py
```

`gen_pcb.py` is run with the ordinary interpreter and **re-runs itself under
KiCad's bundled one**, because `pcbnew` is a SWIG extension that exists nowhere
else. It then re-runs `gen_project.py`, because `SaveBoard()` rewrites the
project file with KiCad's defaults and takes every design rule with it — the
mixer's `build.sh` exists for that reason and says several hours were spent
chasing violations that were only that.

`gen_sch.py` and `gen_project.py` moved ahead of `verify.py` in that list, which
is the shape of the change this pass made: `verify.py` now reads the netlist
KiCad exports from the schematic, so the schematic and its project have to exist
first. Everything from `verify.py` onwards needs KiCad on the machine.

`contract/socket.py` finds the mixer at `$SUMMING_MIXER`, then
`../summing-mixer`, then `~/code/summing-mixer`. **Keep the two as siblings,
never nested** — and never run `git` from a directory containing both.

## What this repo takes from the mixer, and what it does not

The mixer is a **fabricated hardware interface this module references**.
Referencing an interface does not mean importing another project's Python, so
there are two relationships and they are kept apart:

| | |
|---|---|
| **the interface** — `design.py`, `source.py`, `fab/mechanical-*.json` | read at the pinned commit through `contract/socket.py`, with `git show`. Never copied |
| **the KiCad plumbing** — `sexp` `kisch` `symlib` `kicad` `kisim` | **copied into [`toolchain/`](toolchain/PROVENANCE.md). Ours, and modifiable** |

The left column has to agree with a board that exists. The right column carries
no value, net or dimension — `kisim.py` argues its own side in its docstring:
*"it is copied between repositories unchanged, like kicad.py, sexp.py and
symlib.py."* Copying the left column would be the real mistake: `delta.py`
expresses this module's effect as a delta against *the mixer's own* model, and a
forked `source.py` would quietly turn that into a comparison with a copy of
itself.

**The previous arrangement said the opposite and did not do what it claimed.**
`socket.py` appended the mixer's root to `sys.path`, so `import sexp` resolved off
*disk* — whatever the working tree said — while only `design.py` came from the
commit. The guard was a clean-tree assertion over a hand-kept list of files, and
the list had to grow each time a generator imported one more; it named `kisim` and
`source` while `sexp`, `kisch`, `symlib` and `kicad` were asserted nothing at all.
A sheet written by a modified `kisch` would still have been compared to
`design.py`, by a comparison running through the same modified `kisch`.

Now the mixer's root is never on `sys.path`, and the invariant is checked from the
other end: `check_no_mixer_imports()` walks `sys.modules` and refuses anything
loaded from a file under the mixer, identifying the three pinned modules by a
provenance marker rather than by name — a list can only name the collisions
somebody already thought of. `test_verify.py` plants all four ways it must fail.

## What is where

| | |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | the rules, including which "load-bearing constraints" actually are |
| [`STYLE.md`](docs/STYLE.md) | the mixer's conventions, read off its source and followed |
| [`ssi2164-control-port.md`](docs/ssi2164-control-port.md) | the datasheet read first-hand. **Six spec corrections** |
| [`contract/socket.py`](contract/socket.py) | the only place upstream constants are adapted |
| [`toolchain/`](toolchain/PROVENANCE.md) | KiCad plumbing, copied from the mixer. Ours to modify |
| `design.py` | values, derivations, the netlist, and the borrowed-symbol patch |
| `constraints.py` | does each constraint have a mechanism? One did not |
| `delta.py` | this module's effect, via the mixer's own functions |
| `gen_sch.py` / `gen_project.py` | the sheet, and the project KiCad needs to read it |
| `placement.py` / `route.py` | the floorplan as coordinates, and a maze router. Neither imports KiCad |
| `gen_pcb.py` | the board, through the deprecated `pcbnew` bindings |
| `verify.py` / `test_verify.py` | the constraints against KiCad's own netlist, and proof the checks can fail |
| [`FINDINGS.md`](docs/FINDINGS.md) | things wrong in the mixer repo — noted, never fixed |
| [`ASSUMPTIONS.md`](docs/ASSUMPTIONS.md) | everything guessed, with what it costs if wrong |
| `out/` | for machines: schematic, board, project, netlist, BOM as CSV. All generated |
| `docs/` | for people: [floorplan](docs/floorplan.md), [constraint audit](docs/constraints.md), [shopping list](docs/SHOPPING.md). All generated |

## The results worth knowing

**The 2-bit coarse pad is gone, and it is the largest thing this repo has
deleted.** 36 parts, 52 % of the placed courtyard, about two thirds of the BOM,
24 coil drives and a coil supply rail `design.RAILS` never had — for a benefit
nobody had ever computed. Spec §4.1 gives it one job, *"keeps the VCA near unity
where its noise costs least"*, and the SSI2164's noise does not work that way:
its table sweeps **R_IN and R_OUT together** at A_V = 0 dB, and
`design.vca_cell_fit()` splits those four points into a current at the cell's
output (3.8 pA/√Hz, multiplied by R_OUT) and a fixed voltage there (34.7 nV/√Hz,
the size of the ½ TL072 the measurement circuit contains). **A pad raises R_IN
and leaves R_OUT alone**, so it moves the cell by 0.2 dB, downwards.

The comparison that decides it is the pad against the *control port*, which
reaches the same output level for no parts and has 61.3 dB of span against a
47 dB requirement. At the cell the pad is 0.03–3.9 dB worse; at the system, via
`delta.pad_system_delta()`, it is worth **0.000 dB at every noise floor in the
declared 50–400 µV range** and at both ends of the one thing the datasheet does
not say about the cell. The datasheet's own THD rows agree: A_V = −20 dB at full
input is 0.045 % against unity's 0.050 %, so attenuating in the control port is
not the distorting way either.

**How it survived is worth as much as the result.** It was not an unchecked
constraint this time — it was an `Assumption` in `ASSUMPTIONS.md` whose "if it is
wrong" clause cancelled its own consequence: *"the pad steps are noisier than
modelled — but they are used when the source is hot, so the signal is larger by
the same amount … it does not change a component value."* Every clause of that
is false, and an assumption written that way is one nobody will ever compute.
This repository instruments checks, netlists and drawings; nothing looks at the
reasoning inside a declaration.

**The envelope rectifier needed no musical target, and finding that out is the
result.** It sat in `DEFERRED` for two passes with the reason *"the smoothing
time constant is not derivable — spec §4.4 gives a sampling rate and no
attack/release target"*. That is true of an **asymmetric** detector, which is
what "attack and release" describes, and false of a symmetric one:
`design.envelope_filter()` shows a 4.7 ms one-pole falls at 1.85 dB/ms against
25 ms/dB for the fastest musical decay — **46× faster than the music, so there
is no release bound at all**. What is left is bounded on one side only, by the
picked transient (0.12 dB under the peak at 20 ms, from `hexsim`'s own
calibration), and on the other by low-E ripple.

The instrument decides the rest. It is a bowed-and-picked arpeggione, and those
two techniques want opposite shaping — which is the argument for putting the
musical constant in firmware at the 2 kHz frame, where it can differ per
technique, rather than in copper where it cannot. Full-wave on the bow's
account: half-wave leaves **4.67 dB of ripple on a sustained low E**, at the
string's own pitch, which is exactly the flutter a bowed swell would expose.

Two things fell out that nobody was asking. **The reserved op-amp count had
quietly chosen half-wave** — six sections, one per channel, where full-wave
needs two; the second stage now fills those six and the half-wave stages go on
two TL074, away from the audio front ends because their outputs slew across two
diode drops at every zero crossing. And **§4.4's "1–2 kHz sampling" is not a
range**: at 1 kHz the top string's rectified fundamental (659 Hz) is above
Nyquist and folds to −29 dB, −33 dB of it near DC where no averaging removes it.
2 kHz, and the unremovable residue is −53 dB. `design.envelope_sample_rate()`.

**The board is placed, poured and DRC-clean, and the floorplan is now held to
it.** `placement.py` is floorplan.py's zones turned into coordinates — twelve
rows in two bands, quad packages spanning the channels their sections serve,
computed from `design.SECTIONS` rather than typed — and `check_zones()` asserts
that a column's parts are in the ground domain its zone declares, so the two
files cannot drift apart. `gen_pcb.py` places all 222 footprints through KiCad's
own `pcbnew`, reserves a courtyard for each of the three unchosen relays, draws
the derived outline and pours the two grounds either side of the split.

**DRC went 262 → 0.** The first placement put quad packages across rows they do
not serve, and the fault underneath was a loop counter: `design.SECTIONS` keys
spare sections `(role, index)`, so U14's two terminated followers read as
channels 1 and 2 and dragged the package into the wrong band. The last six were
one text field — the VCAs' designators, which KiCad puts *west* of a
90°-rotated body, where the stability capacitor is.

**The board is 4.4× the floorplan's own area estimate**, and the estimate is not
what is wrong: 18242 mm² against 4135. A packing factor of 2.5 is fair for a
dense hand layout and `placement.py` is not one — it is one part per grid slot,
which trades area for being derivable and checkable. Both numbers are kept
because they answer different questions, and the gap between them is the price
of generating a board rather than drawing one.

**476 connections became 67, and the violation count never left zero.** That
last clause is the property worth protecting: a router that trades shorts for
finished connections is worse than one that gives up and says so. `route.py` is
Lee's algorithm with A* ordering — a uniform grid, two signal layers, a via
wherever the path changes layer — and it either finds a path or reports the net
by name. `gen_pcb.py` prints all 23 of them on every run.

Three rules make the result DRC-clean by construction rather than by luck, and
each of them is a violation that happened first:

| | |
|---|---|
| **a pad is on the layers it is on** | blocking every pad on F.Cu alone sent back-side tracks through the connectors' through-holes, started routes on B.Cu with no via under them, and let two nets own one back-side cell — 191 dangling tracks and 199 shorts, from one line |
| **a pad's box comes from `GetBoundingBox()`** | `GetSize()` reports the pad in the *footprint's* frame, so a SOIC turned 90° hands back 1.95 × 0.6 for a pad that is 0.6 × 1.95 on the board. The router blocked the wrong rectangle and drew tracks exactly along the rows of pad edges it thought were 0.675 mm away |
| **a via needs its four orthogonal neighbours, not its eight** | at one pitch, via and track copper are 0.075 mm apart — a third of the clearance. At a diagonal they are 0.28 mm apart, which clears. Requiring all eight was the safe version and it cost 27 nets: no via could ever be placed at a package pin, so every route had to escape through the same corridor |

**The two grounds are not routed and must not be.** They are poured on both
inner layers, so what a ground pad needs is a hole to the plane under it — 104
pads, 104 vias, no copper on the signal layers. The stitching has three rules of
its own, and the third is the ground split made physical: a via has to land in
*its own* pour, so a part that straddles the line — the '541 and the three
bypass relays, by design — gets a longer stub back across it. `R902` is rotated
270° rather than 90° for the same reason, and that was the last DRC violation on
the board: at 90° the star's MAGND pin sits over the digital plane and its MDGND
pin over the analogue one, so both stitches crossed the line and each other.

**What is left is where a grid router runs out of room, and it is not
scattered**: the summing junctions and the two rails. A SOIC pin has a
neighbour 1.27 mm away on each side, so on a 0.5 mm grid there is no cell
between them. Finishing them is a finer grid with thinner track — a
fab-capability decision — or rip-up and retry, which this router does not do and
says so.

**The fail-safe cannot see the one failure that is loud, and one diode can.**
`design.fail_states()` claimed the bypass relay's charge pump covered the
inverted reference failing to the positive rail. It does not: the pump collapses
when the *MCU* stops, and that failure leaves the MCU healthy, still emitting its
10 kHz, holding the relay in. The one state the fail-safe cannot see is the one
state that is +20 dB. D803 — a Schottky from `VREFN` to `MAGND`, reverse-biased
at −2.5 V and doing nothing in normal operation — turns it into **+7.4 dB, inside
the mixer's own 7.84 dB of headroom**. `design.clamp_gain()`.

**And "bypass" here is six changeover contacts, not one relay.** This module
replaces six level pots, so taking it out of circuit means six independent links
back. Three DPDT, non-latching — which is the *opposite* of the coarse pad's
requirement and for the reason that is the whole block: de-energised has to *be*
bypass, so losing the rails, the MCU or the pump all land in the same safe
state. `design.bypass_state()` shows that state is not a new one for the mixer:
PIN{n} linked to SIN{n} puts `R{n}01` in parallel with the mixer's own RIN,
which is **5 kΩ — exactly the fabricated pot at full rotation**.

It costs **75–120 mA continuously on V5**, against 78 mA for every amplifier and
VCA on the board. That is the price of the non-latching relay the mechanism
forces, and it is a requirement on the deferred supply rather than a detail.
`design.coil_budget()`.

**The dominant noise mechanism is additive, not multiplicative.**
`00-current-state.md` records overturning this. Referred to one string: the VCA
cells sit 84.3 dB down and the CV chain's AM sits 91.7 dB down. The original
claim was right and was overturned for a mechanism 8 dB quieter. `delta.py`.

**The "free 8 dB" from summing-resistor scaling is a wash.** It assumed source
noise independent of the source's full-scale voltage; the MAX6126's noise rises
with its output — 45 nV/√Hz at 2.5 V against 95 at 5 V, both **now confirmed
first-hand** against Maxim's own PDF where they had been read from a text mirror.
Scaling up and dividing back down cancels. `ssi2164-control-port.md`.

**A fitted 10 µF was defending against something a capacitor cannot defend
against.** C804 existed to keep the reference's loop from seeing an 8 kHz load
step. At 8 kHz a 10 µF is 1.99 Ω and the MAX6126's own output impedance is
0.028 Ω, so it supplied **1.4%** of that step and the loop supplied the rest — it
only becomes the stiffer element above 568 kHz. Two 10 µF reservoirs also put
VREF at 20.1 µF against a 10 µF stability ceiling. Deleted; VREF now carries the
datasheet's own 10 µF ∥ 0.1 µF, and `verify.check_reference_load()` holds it.
`design.reference_load()`.

**One of the five load-bearing constraints had no mechanism.** "Six separate
returns to six pin-3s" was generated in an earlier session, promoted into a list
headed *check these mechanically*, and then satisfied, asserted and
negative-tested by every instrument downstream — without anyone asking whether
the requirement was reachable from physics. It is not: pairwise crosstalk
through a single bond is 122 dB below one string against a −54 dB requirement.
Struck, with the arithmetic, at `design.FRONT_R`. `constraints.py`.

## The verification loop, and why it is the point

`gen_sch.py` draws all 225 parts. Its own checker builds nets from the geometry
the way eeschema does and compares them to `design.py`; then `verify.py` throws
that away and asks **KiCad** the same question, over
`kicad-cli sch export netlist`. Both agree, net by net and pin by pin.

That second step is what changed here, and it is not tidiness. Before it,
`verify.py` compared `design.py` to a netlist written *from* `design.py` — a
comparison that could not fail for a transcription error, because there was no
transcription. Every check passed and the docstring claimed more than the code
did, which is this repository's own named failure mode.

It found things immediately. Both ground stars were drawn with their pins
swapped: electrically identical for a 0R link, and the comparison is pin-exact
because that is what catches a *polarised* part backwards — the fault the mixer
records twice, at `DIODE_PINS` and `CAP_PINS`, and could not catch.

**The 45 breaks were four causes, and 18 of the 45 were not geometry at all.**
Accounted for exactly — a previous pass, on a sheet that still had the pad on it:

| | |
|---|---|
| 18 | `FEN{n}`, `RCJ{n}`, `CVX{n}` — formed correctly and carrying **no name** |
| 14 | `SVN{n}`, `CVN{n}`, `RINV`, and `MAGND` as their consequence — the +IN column |
| 12 | `SRV{n}` and `IOUT{n}` — `R{n}32` shorted end to end |
| 1 | `MDGND` — the invented coil nets |

The 18 are the reason `gen_sch.py` now labels interior nodes, and they were the
cheapest 18: a summing junction that never leaves its block still needs a name,
because that is what makes KiCad's export comparable to `design.py` by name
instead of by node-set.

The 14 are one geometry fault in three places. An op-amp unit here draws +IN
5.08 mm *above* −IN in the same column, so any route that goes along at the
source part's y to the amplifier's x and then *down* into −IN passes through +IN
— and eeschema reads a pin sitting mid-wire as connected. The summing junction
acquires MAGND and the stage becomes a follower with its feedback grounded. The
front end was the one block that had it the other way round, which is why
`FEN{n}` was the only summing junction that formed; `_to_inverting()` makes that
order the rule, and the order is the whole of the fix. The reference inverter had
it twice over, because it also kept the hand-rolled feedback route that
`_feedback()` exists to replace, running down the amplifier's own column straight
through +IN.

The 12 are `R{n}32` placed in its amplifier's output column, where the descent
from the output reached the far pin *through* the near one — the servo injection
resistor shorted end to end on all six channels, so the integrator drove the node
it exists to correct, through nothing.

Three more things the pass turned up, each recorded where it happened:

- **The relay coils were invented in the drawing.** 24 global labels on 24
  one-pin nets, and every coil return wired to MDGND — which is backwards for
  the open-drain sink spec §4.5 specifies, since a sink drives the *low* side.
  `design.DEFERRED_PINS` declared those 48 pins and `check_open_pins()` refuses
  to let a no-connect flag be read as final. `check_pins_accounted()` in
  `gen_sch.py` is the check that was missing: nothing walked from the pins that
  exist to what became of them, only from `design.NETS` outwards.
  **`DEFERRED_PINS` is empty now** — all 48 were those coils — and the check is
  unchanged and still holds its declaration in both directions.
- **§4.5's coil arithmetic does not work.** "12 coils … 2 × TPIC6B595" needs
  single-coil relays, which latch by polarity reversal, which a sink cannot do.
  Dual-coil, as §4.1 asks, is 24 coils and 3 × TPIC6B595 exactly. **Moot with
  the pad struck**, and kept in `ASSUMPTIONS.md` because a spec that does not
  close arithmetically is worth knowing about — it was one of two constraints
  recorded against a part that turned out not to belong on the board.
- **ERC ran at 583 violations and could not be read.** 539 were one per symbol
  saying the library configuration was missing; `gen_project.py` writes the
  project and they go. Underneath were 12 real errors: two power flags on nets
  already driven by outputs, the SSI2164's current outputs typed as voltage
  outputs, and the '541's two unused outputs unflagged. Now 0 errors and 6
  warnings, each declared with its reason and its exact count in
  `verify.ERC_ALLOWED`.

## Open, in the order worth taking

~~**The pad relay.** Not chosen; 52 % of the board area and about a third of its
cost.~~ **Closed, by deleting the pad rather than by choosing a relay.** It was
item 1 for two passes, and both of the constraints recorded against it — IEC
60947 contact numbering, and §4.5's coil arithmetic that does not close — turned
out to be constraints on a part that should not be fitted. See the pad result
above.

1. **`MEASURED["noise_floor"]`** — the mixer's own unmeasured figure, and this
   module's most load-bearing unknown. It decides whether the module costs
   0.11 dB or 0.85 dB quiescent, and 0.56 dB or 3.17 dB while the lead feature
   is running. `DESIGN.md` upstream calls it "the measurement worth taking".
2. **The envelope ADC.** The rectifier that feeds it is drawn; the part is
   still ADS131M08 or MCP3564, and its **sample rate is no longer a range** —
   2 kHz, because at 1 kHz the top string's own rectified fundamental is above
   Nyquist. It sits in the analogue section so only SPI crosses the boundary.
3. **The fail-safe's power-up sequence now has a number to wait for.** The NR
   capacitor costs 20 ms of reference turn-on, and the '541's Vcc *is* VREF, so
   for 20 ms every channel's full scale is ramping from zero — and zero CV is
   unity gain. §4.5's named fail-loud hazard, arriving by the reference. 20 ms is
   4× the ~5 ms a relay needs, so it is a sequencing requirement rather than a
   hazard. `design.VREF_TURN_ON_S`, waiting for the deferred fail-safe.
4. **The shared blocks**, all five.
5. **R_IN is a free choice again, and it was not.** 12k1 was forced by the pad's
   top step having to stay inside the part's 100 kΩ; without it the datasheet's
   whole 7.5–100 kΩ is available and the trade is the one page 4 describes —
   *"lower values will produce the best noise performance at some cost in
   distortion"* — with a number on neither side. 7.5 kΩ is 2.1 dB quieter than
   what is fitted. `MEASURED["vca_rin"]`.
6. **The board.** `gen_pcb.py` through the deprecated `pcbnew` bindings, as the
   mixer does — and it starts from a floorplan that has just halved:
   3310 mm² against 7225, which puts the mezzanine placement back on the table
   for the first time. `floorplan.BLOCKED`.
