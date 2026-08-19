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

**A spike, and an honest one.** Every number carries its arithmetic, every check
can be shown to fail, and everything guessed is in
[`ASSUMPTIONS.md`](docs/ASSUMPTIONS.md).

**The programmatic approach has passed its useful limit at the geometry, and
this pass acts on that.** Code keeps the logic — the netlist, the algebraic
values, the pin configuration, the constraints, the checks — and the board is
handed to KiCad. `route.py` is deleted; `gen_pcb.py` places, pours and stitches
and lays no signal copper. The rule that follows is the one to read before
anything else here:

> **The netlist is generated and authoritative. The board is hand-laid and
> verified.**

Running `gen_pcb.py` over a hand-routed board destroys the routing, with no undo
and no warning. The sync path for a netlist change is KiCad's own **Update PCB
from Schematic**, against the generated sheet. `verify.py` is unchanged in what
it asks, because every one of its questions was always asked *of* the board by
reading it back.

**And the controller is a Raspberry Pi Pico.** 0.40 mm of pin pitch became
2.54, which is what made the router's whole subject go away — and it took the
supply with it, because a Pico makes its own 3.3 V with a converter this design
does not choose. See [`controller.md`](docs/controller.md).

| | |
|---|---|
| one channel derived | ✅ every value, arithmetic inline |
| the coarse pad | ✅ **struck** — 0.000 dB of system noise for 36 parts |
| netlist | ✅ **289 parts, 184 nets, 823 pin connections** — 25 parts and 17 nets went inside the module |
| schematic | ✅ **0 merges, 0 breaks, 0 stranded pins** |
| the verification loop | ✅ `verify.py` reads **KiCad's** netlist, compared by name |
| ERC | ✅ **0 errors and 0 warnings** — `ERC_ALLOWED` is empty |
| the envelope rectifier | ✅ derived, drawn and checked — τ from the transient, not from a target |
| the fail-safe | ✅ drawn: de-energised **is** bypass, and the pump's own rise time is the power-up interlock |
| section 5 constraints | ✅ checked mechanically, **81** planted faults caught — and the faults themselves are checked too. Five faults went dead when their targets left the board, and the guard named all five before a case ran |
| deltas against the mixer's own model | ✅ four disagreements, three of them with `00-current-state.md` |
| floorplan, BOM, assumptions | ✅ |
| board | ⚠️ **the routed board from `bfa4483`, awaiting a sync.** 55,854 segments and 767 vias, and **263 of the 288 shared parts are at identical coordinates** — the audio channels, CV rows, envelope rows, ADC and fail-safe keep their copper. What needs re-routing is the controller zone: 27 nets, ~94 connections of 639. `check_board_is_the_design()` is the new instrument and it fails until KiCad's Update PCB from Schematic is run |
| ~~the fan-out~~ | **deleted with `route.py`.** Four escapes at U17 closed the board it was written for and nothing on this board exercises it: the finest pitch left is a TSSOP's 0.65 mm. This repo's rule about a declaration nothing is obliged to use, applied to code |
| the design rules | ✅ one copy in `rules.py`, and DRC is finally enforcing them |
| the two `UNSPECIFIED` parts | ✅ **chosen** — Omron G6S-2 DC5 and Diodes DMG1012T. `UNSPECIFIED` is empty and no courtyard is reserved |
| the Schottky clamp | ✅ **read, and it had failed** — the BAT54 missed by 5.5 dB. PMEG2010AEH fits with 1.5 dB |
| the supply | ✅ **chosen, drawn, placed, routed and checked** — Traco TMR 6-2422WI, isolated, ±12 V at 250 mA, **580 kHz PWM**, on this board. The isolation barrier is copper `verify.py` measures |
| the +5 V rail | ✅ NCP1117 — and **the package is the answer**: 0.77 W against the SOT-223's own 160 °C/W is 124 degrees of rise, so it is a DPAK |
| documents to look at | ⚠️ **the three plots are of two different designs and that is worth knowing before you open them.** The [schematic](docs/cv-module-schematic.pdf) is plotted from the generated sheet, so it is the Pico. The [layout](docs/cv-module-layout.pdf) and the [render](docs/cv-module-top.png) are plotted from the *board*, and the board on disk is deliberately `bfa4483`'s routed RP2040 — kept as the routing reference — so they show a QFN-56, its flash, its crystal and a USB connector that are no longer in the netlist. `gen_plots.py --verify` passes because the plots do match the board; `check_board_is_the_design()` fails because the board does not match the design. Both are true and neither says the thing above, which is why it is said here. They converge when step 3 of the open list regenerates the board. ❌ no gerbers, and that is a gate |
| the inlet choke | ✅ **fitted, and it is the second half of `barrier_return()`** — a WE-SL2 744222, 2 × 1 mH at 800 mA. The 580 kHz residual at the audio bond goes from 1.24 mV to **1.14 µV**: 42 dB *under* the mixer's own noise floor, where it was 18.7 dB over |
| the envelope ADC | ✅ **chosen, drawn, placed, routed and checked** — MCP3564. The ADS131M08 lost on full scale: its reference input stops at 1.3 V, so 1.20 V of full scale against a 1.233 V signal |
| the 3.3 V rail | ✅ **real now, and it had been declared for four passes with no net** — `RAILS` said `V3V3` and `supply-decision.md` said there is no such rail. `check_rails_are_drawn()` is the instrument |
| the inlet fuse | ❌ **derived and not fitted.** The converter's datasheet asks for 1.6 A slow blow and the assessment says yes — the inlet is shared with a fabricated board that has none. No part number was verified this session, and a plausible order code is worse than an absent part |

| the controller | ✅ **a Raspberry Pi Pico, and `DEFERRED` is empty.** SC0915, castellated, 2.54 mm. It deleted about 25 parts — the flash, the crystal, USB with its terminations and VBUS divider, twelve capacitors, the BOOT and SWD headers — and one whole class of problem. `pico_backdrive()` refuses the cheap supply topology on documentation rather than on arithmetic; `mcu_supply()` is what the documented one then cost — see [`controller.md`](docs/controller.md) |
| the fabrication class | ✅ **re-opened, re-decided, and put back — 0.09/0.09 on 1 oz, unchanged.** The QFN that forced it has gone and the arithmetic says 0.15/0.15 on 2 oz is now enough. It omits the 55,854 segments already laid on a 0.23 mm grid, which are legal at 0.09 mm wide and illegal at 0.15. **The class is a free choice only for a board routed from nothing** — see [`fabrication-class.md`](docs/fabrication-class.md) |
| the +Vout budget | ✅ **212.9 mA of 250, and it failed first.** Two converters in series made the 67.8 % threshold a threshold on a *product*, the pessimistic corner missed by 4.6 mA, and `verify.check_supply()` said so. Closed by the lever `MEASURED["mcu_dcdc_efficiency"].when_wrong` has named since the QFN pass: U22 makes 5 V now and carries the relay coils |

**`design.DEFERRED` is empty and so is `design.UNSPECIFIED`.** There were six
deferred blocks: the supply, the envelope ADC, the envelope rectifier, the
fail-safe, the relay drive and the controller. Five are drawn and the sixth was
deleted along with the coarse pad it existed to drive. Every part has a
footprint, no courtyard is reserved, and no pin is still a role.

**What follows from that is worth stating rather than discovering.**
`gen_plots.orderable()` reads both of those and returns nothing now, so
**nothing in the design stops a fabrication package being written** — and
`gen_plots.py` still writes none. Gerbers are a decision somebody takes, and it
is on the open list below rather than in the code.

Choosing them also settled a bug that only existed while they were not. The
dict is keyed by a part's *value*, and an unchosen part's value is `None` — so
`BYPASS_RELAY` and `BYPASS_FET` were the same key, and the relay's requirement,
every word of it derived, was overwritten at import for the life of the block.
Nothing noticed: every consumer asks `value not in UNSPECIFIED`, and a
membership test is answered as well by one entry as by two. **A dict keyed by
the thing that is missing collapses exactly when it is carrying the most.**

## Run it

Nothing to install. Stdlib only, following the mixer's own rule that "there is
no `requirements.txt` because there is nothing to install". KiCad 10 is not
optional any more: `verify.py` runs `kicad-cli` twice, once for the netlist and
once for ERC; `gen_pcb.py` needs its bundled Python for `pcbnew`; and
`gen_plots.py` plots the schematic, the layout and the render. That is the point
rather than a dependency to regret.

**Two pipelines now, and the split is the whole of the new workflow.** The
first is safe and is what you run: it regenerates the netlist, the schematic
and every document, and it verifies the board that is on disk without writing
to it.

```bash
python3 design.py && python3 gen_netlist.py && python3 gen_sch.py \
  && python3 gen_project.py && python3 placement.py \
  && python3 verify.py && python3 test_verify.py \
  && python3 constraints.py && python3 delta.py && python3 floorplan.py \
  && python3 gen_bom.py && python3 gen_assumptions.py && python3 rules.py \
  && python3 gen_plots.py
```

**`gen_pcb.py` is not in it.** It places, pours and stitches, and it lays no
signal copper -- so running it over a hand-routed board discards the routing,
with no undo. It is a *starting* step, run once, and after that the board is
edited in KiCad:

```bash
python3 gen_pcb.py                 # refuses if the board carries signal copper
python3 gen_pcb.py --discard-routing   # and this is how you mean it
```

The refusal is `gen_pcb_guard.refuse_to_discard_routing()` and it is enforced
rather than documented, because for one pass it was documented in three files
while this very code block still had `gen_pcb.py` in the middle of it.

**To move a netlist change onto a routed board**, use KiCad's own **Tools ->
Update PCB from Schematic** against `out/cv-module.kicad_sch`, which the first
pipeline regenerates. That is the only sync path.

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
| [`fabrication-class.md`](docs/fabrication-class.md) | 0.09/0.09 on 1 oz — the decision, and the four-row table that took it |
| [`contract/socket.py`](contract/socket.py) | the only place upstream constants are adapted |
| [`toolchain/`](toolchain/PROVENANCE.md) | KiCad plumbing, copied from the mixer. Ours to modify |
| `design.py` | values, derivations, the netlist, and the borrowed-symbol patch |
| `constraints.py` | does each constraint have a mechanism? One did not |
| `delta.py` | this module's effect, via the mixer's own functions |
| `gen_sch.py` / `gen_project.py` | the sheet, the project KiCad needs to read it, and **the project's own symbol and footprint libraries** — `out/cv.kicad_sym` and `out/cv.pretty`, the second holding the one land pattern KiCad does not ship |
| `rules.py` | the fabrication rules, the routing pitch derived from them, and the fab class read first-hand |
| `gen_plots.py` | the schematic, the layout and a render — the outputs you can look at without KiCad |
| `placement.py` | the floorplan as coordinates. It does not import KiCad |
| `gen_pcb.py` | the board, through the deprecated `pcbnew` bindings — **place and pour only** |
| `verify.py` / `test_verify.py` | the constraints against KiCad's own netlist, and proof the checks can fail |
| [`FINDINGS.md`](docs/FINDINGS.md) | things wrong in the mixer repo — noted, never fixed |
| [`ASSUMPTIONS.md`](docs/ASSUMPTIONS.md) | everything guessed, with what it costs if wrong |
| `out/` | for machines: schematic, board, project, netlist, BOM as CSV. All generated |
| `docs/` | for people: [floorplan](docs/floorplan.md), [constraint audit](docs/constraints.md), [design rules](docs/rules.md), [shopping list](docs/SHOPPING.md), and the three plots. All generated |

## The results worth knowing

**The barrier's return current is a divider, and this pass fitted the other
side of it.** `C810` was already at the largest value the low-frequency side of
its own trade allows — 470 nF against a 610 nF ceiling — and it left 1.24 mV of
580 kHz across the audio ground bond, which is ultrasonic, inaudible, and
**18.7 dB above the mixer's own noise floor as a number**. That is enough to
make any measurement of that noise floor wrong. The remaining 19 dB was never
available from a capacitor: the split is `Z_Y` against `Z_loop`, and a
capacitor can only divide the first.

A **Würth WE-SL2 744222** — 2 × 1 mH at 800 mA, 207 mΩ per winding, every
figure read off its own datasheet — multiplies the second instead. 3.6 kΩ at
580 kHz against a 2.8 Ω loop takes the residual to **1.14 µV, 42 dB under the
noise floor**, and 36 dB under it at the choke's own ±50 % tolerance. It costs
161 mV of DC drop at 389 mA, on a converter that has 2.5 V of input headroom
spare.

**Where it goes is as load-bearing as what it is.** `L801` sits immediately at
`J8`, ahead of `D804` and the three primary decoupling capacitors. Put it after
them and those capacitors common the inlet pair in front of it, so the
common-mode current never sees the winding: the same part, the same four wires,
0 dB, and a schematic no reader could tell apart. `verify.check_supply()`
asserts both that and the winding pairing — 1-4 and 2-3, not 1-2 and 4-3, which
is the difference between 3.6 kΩ across the common-mode path and 1 mH in series
with the supply current.

**And fitting it broke the function that measures it, in the direction that
hides the result.** `barrier_return()` returned `through_loop * z_loop` as the
voltage at the bond, which is right — pessimistically right — for as long as
every ohm in the loop *is* bond. With the choke in it, that expression reports
**1.5 mV, worse than the 1.24 mV it reports unfitted**: the current falls by
1300 and the impedance it is multiplied by rises by 1300. It was never a wrong
formula; it was a formula that was correct because two different quantities
happened to be the same number, with nothing recording that they were
different. The only warning was that the answer got worse when the part got
better.

**The envelope ADC is chosen, and one number chose it.** Spec §4.4 named
"ADS131M08 or MCP3564" and left it. Both were read first-hand, and the decision
is not channel count, price, or the simultaneous-versus-multiplexed question
that looks like the interesting one:

| | ADS131M08 | MCP3564 |
|---|---|---|
| external reference input | **1.1 / 1.25 / 1.3 V** | **0.6 V to AVDD** |
| full scale at unity gain | 1.20 V | 2.50 V |
| against `socket.clipping_peak()` = 1.233 V | **−0.24 dB** | +6.14 dB |

The ADS131M08's full scale is **below the level it exists to measure**, its
minimum gain is 1, and its reference cannot be raised to fix it — the top of
the range buys 1.248 V and 0.1 dB. The MCP3564 takes the board's own 2.5 V
reference, which also makes `floorplan.CROSSING_RULE`'s already-written *"the
ADC's own reference is VREF"* true rather than aspirational. That sentence was
written before either datasheet was opened, and exactly one of the two
candidates could honour it.

**What the multiplexer costs is a clock, and that is the honest debit.**
`envelope_adc_clock()` shows the MCP3564's SCAN mode is not pipelined across
channels — the decimation filter resets between them — so six channels at 2 kHz
need `MCLK ≥ 4 × 6 × TCONV × 2000`. Its internal RC oscillator is specified as
**3.3 to 6.6 MHz**, a factor of two, and the design has to hold at the bottom:
even at the coarsest useful setting that is 1432 Hz per channel, and
`envelope_sample_rate()` has already shown what happens below 2 kHz. So MCLK is
external, from the deferred controller, and it is a sixth signal across the
domain boundary where §4.4 promised four.

**The ADC's inputs are divided, not clamped, and the difference is a failure
mode.** `ENV{n}` is a ±12 V node and the part's absolute input rating is
AVDD + 0.1 = 3.4 V. A series resistor limits the ESD current without stopping
it, and the current has to go somewhere: into a 3.3 V rail whose regulator
cannot sink. Six channels clipping together would push more current *into* that
rail than the ADC draws out of it. So each channel gets 22k/4k99, which puts
the largest voltage stage B can produce — 11.65 V — at 2.15 V, inside full
scale rather than merely inside the rating. **No input can reach a voltage that
needs protecting.** It gives up 20.8 dB of converter range above the loudest
level the system has, and `envelope_adc_clock()` buys that back in OSR for no
parts.

**Its reference decoupling is a refusal, and the refused thing is the fault
this repo already deleted once.** DS20006181C asks for 0.1 µF and 10 µF at
REFIN+ and calls them "not mandatory for correct ADC operation". The MAX6126 is
qualified for **one** bulk capacitor and already has it, so a 10 µF there is
the second reservoir `C804` was deleted to remove — arriving from a different
direction, with a datasheet sentence recommending it. `reference_load()`'s own
assertion is what stopped the build: *"a capacitor added to VREF cannot be left
out of the total by being left out of this dict."*

**The 3.3 V rail existed in `RAILS` for four passes with no net.**
`design.RAILS` said `"V3V3": 3.3`; `supply-decision.md`'s correction index said
*"there is no 3V3 rail on the board"*. Both were consumed — `NET_DC` is built
from `RAILS` — and neither could fail, because **a rail with no net is
invisible to every check that walks nets**, which is all of them. That is zone
P one artefact along: a declaration nothing is obliged to use cannot be wrong.
`Design.check_rails_are_drawn()` is the instrument, and the rail is real now —
an MCP1700 off V5, chosen because its 6.0 V input limit makes V5 the only rail
it can hang off and its 4 µA of quiescent current is what an NCP1117 would have
spent 10 mA on.

**Six places in this repo said something about the ADC and four of them
disagreed**, which is the thing the last pass said to look for first. Which
domain it is in (`CROSSING_RULE` said analogue, `ZONES` put it in the digital
zone D2); whether the board has a 3.3 V rail; how many signals cross; and
whether "only SPI" was four things or six. None of it was catchable, for the
same reason each time: the block was not drawn, and deferral suspends every
instrument at once.

**A 0.65 mm pin pitch does not fit a 0.5 mm routing grid, and closing it took
four wrong readings of one symptom and then twenty lines of copper.** This is the
longest thread the project has had and every step of it looked like the last one.

The symptom was unrouted nets at the envelope ADC. It read first as congestion,
then as too little room, then as the wrong rotation — three placements, and the
count went 4, 3, 2. Two real findings came out of those:

| | |
|---|---|
| **`rules.escape_corridor()`** at 0.65 mm pitch on 0.40 mm pads gives a window of **−0.40 mm** at the fitted class and −0.02 at the finest. Not a fine-grid problem, a *negative* one: no legal track centre exists between two of its pins, so every pin escapes outward |
| **`rules.pad_reach()`**, one line further out: a pad holds a grid cell at every phase only if it is **wider than the grid pitch**, and it can be at most `pin_pitch − clearance` wide. So a package is reachable at every placement only above `grid + clearance` = **0.70 mm**. A SOIC clears it by 0.57; a TSSOP misses by 0.05, and no placement fixes that |

**And then DRC found what none of it had.** Eight clearance violations at 0.15 mm
against a 0.2 mm rule, every one a track beside a TSSOP pin. The router had been
*drawing* the connections it could not legally make — through cells exempted from
clearance because they are a pad's own copper. `block_pad_copper` says "a segment
inside a pad's own copper cannot be too close to anything, because the pad
already is not", which is true of the **pad** and not of the **0.25 mm track**
the router then lays through that cell. At 1.27 mm pitch the overhang reaches
nobody, which is why no board before this one showed it. `route.access()` had a
second one of the same shape, in the one function whose docstring forbids it.

**The fourth wrong reading was the check written to predict the third**, and it
is the one worth carrying. `check_fine_pitch_access()` — since removed — asked
whether a grid cell falls inside the pad's *bounding box*. Three boxes, three
answers:

| box | a cell within | who used it |
|---|---|---|
| the pad, 0.400 mm | 0.200 mm of the centre line | the check |
| inset by half a track | 0.075 mm | `route.access()` |
| clearance to the next pin | **0.125 mm** | DRC |

So the check passed on four pads the router then refused, and
`verify.UNROUTED_ITEMS` was 8 while the instrument written to explain it reported
nothing. It was not wrong about the box it measured. It measured the pad, and
what gets drawn is a track — this repo's oldest failure, inside the function
written to catch this repo's oldest failure.
`rules.track_offset_limit()` is the arithmetic now.

**What closed it is the fan-out**, laying each unreachable pin's escape as fixed
copper on the pad's own centre line before `route_all()` runs — the way
`stitch_grounds()` already lays 133 vias, and the way a person drawing this by
hand would do it without thinking about it. Along the pad's own axis first,
because inside the pin row that is the safest track on the board; across to the
grid only past the pad's clearance halo, where there is nothing to be near.

Three things about it are the design and not the implementation:

| | |
|---|---|
| **which pads get one is `route.access()`'s own answer** | The first attempt computed the criterion a second time in `gen_pcb.py`, and the second opinion was wrong: it measured from the pad's *centre line*, which is the only candidate a TSSOP pin has and one of a hundred an NCP1117's DPAK tab has, so it declared the 5 V regulator unreachable and refused its escape. `gen_pcb.escape_plan()` now answers only **which way is out** |
| **an escape is a track, so its halo is one half-track wider than a pad's** | `block_pad_ring()` grows a pad's copper *rectangle* by `clearance + track/2`; `block_escape_ring()` is handed a centre *line*, so the reach is `track + clearance`. The pad's number would leave every neighbour half a track too close — the same fault, from the other side |
| **its clearance is measured, not asked of the grid** | `escape_clearances()` is geometric, against the real pad boxes. The grid would be wrong both ways at once: it would refuse the escape, because the cells beside a fine-pitch pin are blocked to routing and rightly so, and it would pass copper the grid does not own |

**One notion of where a pad is.** `pad_boxes()` keys on the bounding-box centre
and `escape_plan()` first keyed on `GetPosition()`. They agree to within a
nanometre and not to within a float comparison: ENVA1 and MISO matched, ENVA2 and
MOSI missed by one, and the router reported "no escape axis" for a pad 1.475 by
0.400 mm.

**`UNROUTED_ITEMS` is 0 and DRC is still 0.** Four escapes, all at U17, and 1547
track runs and 561 vias against 1489 and 516 with the four nets unmade — so the
escapes did not only close their own pads, they freed enough room for the rest of
the fan to take shorter paths.

**`ENV_ADC_CHANNEL` is a record of a measurement now rather than a constraint,
and the measurement is the interesting part.** It existed to spend the choice of
*which* two pin rows lose on the ADC's grounded channels, so with the constraint
gone the map is free — and CH0–CH5 in order is what firmware would expect, and
it removes a crossing nobody had priced, because CH6 is pin 11 on the *logic*
side and ENVA6 has to get round the package to reach it. It was drawn and routed,
and **it cost a net 30 mm away**: moving the channels down one pin makes a fifth
pad need an escape, whose halo takes cells out of the one corridor the six
`ENVA{n}` runs already converge into, and the router closed all six ENVA nets and
dropped **CVN3** in the CV band — DRC still at zero, two unconnected items. The
old map is kept, because 0 unrouted items is a stronger property than a tidier
dict.

**The general finding is that an escape's copper is not free and it is not spent
where it is laid.** Four escapes closed four nets *and shortened the whole fan*.
The fifth closed nothing extra and broke something in another zone. Nothing in
this repo would have predicted either; the router is the only instrument that
knows, which is the argument for running it rather than reasoning about it.

**The ladder it leaves behind is the reusable part.** `rules.fan_out_class()`
collects three questions into the one a package is chosen against:

| | |
|---|---|
| `limit >= grid/2` | a track starts inside the pad at every phase. **SOIC, 1.27 mm** |
| `2(edge − clearance) >= track`, `pin_pitch >= grid`, **and the jog clears** | it cannot, but an escape on the pad's own centre line reaches it. **TSSOP, 0.65 mm** |
| any of those failing | nothing this router draws gets there. **QFN-56, 0.40 mm** |

The **counting** condition is one nobody would think of: an escape ends on a grid
cell and may move at most half a pitch to get there, so pins map onto grid lines
in order — and two pins closer together than one grid pitch have to share a line,
which two nets cannot. Fourteen pins a side over 5.2 mm want fourteen lines and a
0.5 mm grid offers eleven.

**The jog condition was missing, and its absence made this section wrong for one
pass.** It said the RP2040 "clears at the 2 oz minimum, 0.15/0.15". Two conditions
were enumerated, both were true at that class, and the conclusion was written as
though the enumeration were complete — a rule whose stated *test* was narrower
than its stated *mechanism*, which is exactly what `floorplan.CROSSING_RULE`
records one artefact along. The third condition is that the jog is ordinary track
pointing at a neighbour `pin_pitch` away, so it needs
`pin_pitch − grid/2 >= clearance + track`. Nothing would have caught it: no board
here has a 0.40 mm part on it, so there was nothing for a check to fail against.
It was caught by asking the arithmetic for a class instead of reading a class off
a table.

**The fitted class fails that condition for the TSSOP and the four escapes on
this board are legal anyway — and that is arithmetic, not luck.** Adjacent pins'
offsets differ by `pin_pitch mod grid` = 0.15 mm, and both pins escape only when
both offsets exceed 0.125 mm, which is impossible with the *same* sign because
0.125 + 0.15 exceeds the 0.25 an offset can reach. So two adjacent escapes here
always point **away** from each other. At 0.40 mm on a 0.35 mm grid they need
not, so QFN escapes can point into each other and `escape_clearances()` refuses
the second.

## The controller: drawn, and it was the last deferred block

**`design.DEFERRED` is empty.** Its last entry read *"shared block, and the
scope statement puts shared blocks after one channel is complete"*, which was a
scope statement rather than a finding; deriving what the block asks for turned
it into two computed gates, and this pass closed both and drew it.
[`docs/controller.md`](docs/controller.md) is the record.

**The case for the RP2040 is derived now, and it never was.**
`00-current-state.md`'s claim 9 is the only case this project ever had for the
part — *"Teensy 4.1 / RP2350B … both have mandatory buck converters"* — and it is
a **negative**: it says what the other candidates carry, not what this one does.
`controller_fit()` is the other half, every row a requirement this board makes
against a number read first-hand from the RP2040 datasheet:

| asked of the controller | RP2040 | |
|---|---|---|
| 19 signals on GPIO, counted off the netlist | 30 GPIO | 1.58× |
| 6 PWM carriers, one slice each | 8 slices, 16 outputs | **1.33×** |
| MCLK ≥ 9.216 MHz, `envelope_adc_clock()` | 10.417 MHz = 125/12, **one of seven integer divides** | 1.13× |
| 8 kHz control frame, 2 kHz envelope frame, all channels | 125 MHz `clk_sys` | 2600× / 10400× |
| ~10 kHz on a GPIO for the fail-safe pump | 125 MHz `clk_sys` | 12500× |
| USB MIDI, DIN MIDI, tap switch, expression pedal | USB 1.1 device, 2 UARTs, GPIO, 4 ADC channels | |

**Two of those rows moved when the block was drawn, and neither moved because
anything was wrong.** The first counted signals across J9–J13 — five headers
standing in for an off-board controller — and got 14: those headers carried what
*the rest of the board* needed from a controller, and the part also needs pins
for its own periphery, so it is 19 now. The second counted six carriers against
sixteen *outputs*, which is the wrong denominator for what §4.2 asks: a PWM
slice is one counter with two outputs, so two channels on one slice cannot be
phase-staggered against each other. Six of eight slices, and it is the tightest
countable row on the table.

The tightest row overall is MCLK and it is not a margin to spend: what makes an integer
divide the right answer is that the ADC's conversions are not on a jittered
clock, and that is true of all seven divisors. `PWM_CARRIER` is in the table as
**margin rather than as a reason** — 125 MHz / 2¹² = 30.5 kHz is already derived
from this part's clock, and `pwm_ripple()` puts it 83 dB down for 0.0027 dB of
gain error, so a different clock would also be fine.

**Claim 9 is marked as not relied upon rather than left standing.** Its
"mandatory" came from a deep dive in the parent project's documents 0–4, which
are not in this repo; no RP2350 or Teensy datasheet page is cited anywhere here;
and claim 10 in the same table says the MCU was never the load-bearing choice
anyway. It may well be true and nothing here can check it — which is this repo's
own rule about a constraint with margin, applied to a part.

**Gate 1 — the package.** RP2040 ships only in a 7×7 QFN-56 at 0.40 mm pitch, and
`rules.fan_out_class()` puts that off the bottom of the ladder on **all three**
counts: widest legal escape 0.20 mm against this board's 0.25 mm track, fourteen
pins a side for eleven grid lines, and the jog coming 0.150 mm to a neighbour
against 0.45.

`rules.coarsest_class_for()` solves for the class rather than reading one off a
table: **0.12/0.12 mm or finer**, which is below JLCPCB's 0.15 mm 2 oz floor and
above its 0.09 mm one. So the only listed class that works is **0.09/0.09 — 1 oz
outer copper only. The copper weight is the price and no intermediate class
avoids it.** At that class no pad on the package needs an escape at all: the
fan-out becomes unnecessary rather than sufficient. What it costs is **not** build time, which is
the surprise: `gen_pcb.py` takes **89.0 s at the fitted class and 69.0 s at
0.09/0.09**, 22 % faster on 4.7× the cells, because runtime is dominated by
contention rather than grid size and a finer grid has far less of it. Cell count
was a proxy that omitted the dominant term, exactly as A/mm² was.
`controller_package()`.

**What it did cost was 56 DRC violations, because "no fan-out needed" is not "no
work needed".** They were two router faults and both are fixed, and both were the
same missing distinction: **`route.py` had one ring of four cells where three
distances were needed.** That ring blocked a via's orthogonal neighbours and not
its diagonals, with a derivation attached that is entirely correct *at a 0.5 mm
grid on 0.25/0.20 copper* and was written as though it were a fact about the
geometry. `rules.via_exclusion()` asks it properly — a via is near three kinds of
thing, and each distance is the stricter of a **copper** rule that shrinks with
the fabrication class and a **hole** rule that does not, because a hole clearance
is drill positioning rather than etching. Somewhere on the way down the hole rule
overtakes the copper one: it wins by 0.01 mm at 0.09/0.09 and loses by 0.10 at the
fitted class, which is exactly why 49 of the violations were hole clearances and 7
were copper.

The hole figures are the fabricator's, read first-hand — *"Via Hole-to-Hole
Spacing: 0.2mm"*, *"Pad Hole-to-Hole Spacing: 0.45mm"*, *"Via hole to Track:
0.2mm"* — and `rules.py` **did not own that rule at all**: KiCad's own 0.25 mm
default had been enforcing it, the same way `min_track_width` once sat at zero.
What DRC enforces is deliberately unchanged, because KiCad's default is *stricter*
than the published figure and declaring 0.20 would have made 49 violations vanish
with no copper moving — indistinguishable from relaxing a check to pass.

**Correcting it answers the class question by measurement**, `gen_pcb.py` end to
end:

| class | via rules | time | unrouted | DRC violations |
|---|---|---|---|---|
| 0.25/0.20, 2 oz | ring of four | 89 s | 0 | 0 |
| 0.09/0.09, 1 oz | ring of four | 69 s | 0 | 56 |
| 0.25/0.20, 2 oz | **corrected** | **454 s** | **10 (V5)** | 0 |
| 0.09/0.09, 1 oz | **corrected** | **89 s** | **0** | **0** |

**The board that used to close was closing on geometry the router had no rule
for**, and DRC agreed because the two illegal cases were never *attempted* at that
grid — a via inside the annulus 0.325 to 0.5 mm from a foreign pad, and two vias
on diagonal cells 0.707 mm apart against a 0.8 mm requirement. Latent, not absent.
So `UNROUTED_ITEMS` going 0 → 10 is the router becoming honest, and the rule about
that number permits exactly this: down as copper is laid, up only with the nets
named. V5 is the name.

**And it reverses the recommendation of an hour earlier.** Keeping 2 oz and
building a spreading fan was the argued answer; measured, the spreading fan is not
needed at all — the finer class removes the problem it was for — and only
0.09/0.09 produces a complete DRC-clean board. Still a fabrication decision, so
not taken here: `rules.COPPER_OZ`, `TRACK_MM` and `CLEARANCE_MM` are the one-line
change.

**And the coil nets were flagged as the other cost, wrongly.**
`rules.track_current()`: 92.7 mA on 0.09 mm of 1 oz copper is **0.33 °C of rise**
— 4.0 °C even if the borrowed IPC-2221 constant is three times out, which is why
the conclusion is quoted despite the source being third-party calculators rather
than the paywalled standard. The figure that made it look close was **29 A/mm²,
and current density was the wrong instrument**: it divides by the cross-section,
which carries the current, and omits the surface area, which does the cooling.
That is why IPC-2221's exponent on area is 0.725 and not 1, and it is the same
shape as the mixer's `RAIL_FILTER_ESR` — a number that was not wrong so much as
computed without the term that dominates. The class decision now has no unread
number in it.

**Gate 2 — the supply, and it is closed by a part.** `supply_fit()` leaves
35.4 mA of +Vout, and V3V3 is an MCP1700 off V5 off VA+ — so a milliamp of 3.3 V
is a milliamp of *twelve* at the converter's pin. The RP2040's own measured
range (Table 637: 19.2 mA idle in BOOTSEL, 52.1 mA running the VGA demo)
straddles that, and **neither end is a board that works**: the top fails
outright and the bottom leaves 16.2 mA for a QSPI flash, a DIN MIDI current loop
and an opto-isolator.

**A switcher from VA_RAW is the only topology with room, and the bound needs no
efficiency figure.** Conservation of energy puts a converter's input current at
least `vout/vin` times its output, so the floor is arithmetic rather than a
datasheet reading. What the drawn block then changed is the *numerator*: the
rail carries the flash's 25 mA, the MIDI loop's 5.5, the pedal's 3.3 and the
opto's 1 as well, so it is **87.3 mA of 3.3 V**, a floor of 24.0 mA at the
converter, and it fits at any efficiency above **68 %** rather than 40. At the
pessimistic end of `MEASURED["mcu_dcdc_efficiency"]` it costs 32.1 mA and leaves
**3.3 mA**, which is the tightest margin on this board and is said plainly
rather than rounded.

**The part is a TPS560430XF and three things chose it**, in order of how easily
each would have been missed:

* **it is the forced-PWM version.** `mcu_dcdc_light_load()` computes the
  continuous/discontinuous boundary for Table 1's own 12 µH — **91 mA against a
  maximum load of 87** — so a PFM part would never be in continuous conduction
  and its switching frequency would be proportional to load: 246 kHz at this
  board's idle, *under* the ≥ 300 kHz rule §1.1 sets, and inside the audio band
  below 1.6 mA. That is `supply_beat()`'s objection to the RCC-topology TMR 6,
  arriving at a second part from the other end;
* **its frequency is a stated band**, 0.935–1.265 MHz, which is what
  `mcu_dcdc_beat()` needs to compute with;
* **its datasheet states the passives** — L, C_OUT and the divider — so nothing
  in the block is this repo's invention. The fixed-3.3 V sibling would have
  saved two resistors and its FB connection is nowhere stated in the document,
  only implied by two table entries; an inferred connection on the pin that sets
  a rail is not worth two resistors.

**Its input is VA_RAW and not VA+**, one node ahead of the rail filter, and that
is the one thing here that would work and be wrong: behind `R804` the switcher's
own pulse train develops across the filter resistor and onto the rail six audio
channels share. In front of it, the same pole attenuates it 6 dB harder than it
does the converter's own ripple — 39 mA rms of input ripple becomes **2.4 µV on
VA+**, 102 dB down as AM. `verify.check_mcu_supply()` holds the wire.

**`SUPPLY_IOUT_MA` is a datasheet reading and was not touched.**

## What drawing the controller found

Five things, and three are corrections to figures derived while the block was
deferred — which is the shape worth carrying: **a requirement derived against an
interface that stands in for a block is a requirement about the stand-in.**

**The GPIO count and the PWM denominator**, both above.

**`supply_beat()`'s harmonic search was a fact about its only caller.** It
looked at the pump's first twenty harmonics, which covers 580 kHz — the 12.9th —
and truncated silently when `mcu_dcdc_beat()` asked about 1.1 MHz, the 24th,
reporting a 200 kHz beat where the answer is 20. The count comes from the
frequency now.

**This board has a second isolation barrier.** DIN MIDI is an opto-isolated
current loop: `U21` is a second `U15`, `C836` is a second `C810`, and CA-033
requires that bridge to be a capacitor — *"Pin 2 of the MIDI In connector shall
not have any DC path to the receiver's ground"*. `floorplan.py` said *"the"*
barrier in three places; `BARRIERS` is a table now and `check_isolation()` is one
test run twice. The geometric half is deliberately not extended to it, and the
docstring says why.

**A connector at the edge is not a connector nearest the edge.**
`placement.outline()` puts `MARGIN` of clear board around whatever is outermost,
so a USB receptacle placed as far east as anything else is 5 mm inside the board
and no plug can reach it — placed, routed, DRC-clean and unusable, and nothing
in this repo could have said so. `EDGE_PARTS` and `check_edge_parts()` are the
instrument; `outline()` leaves the margin off on the side an edge part faces,
without which the check is circular.

**Two more, in files that have nothing to do with the controller — and both
were found by writing a new check rather than by running an old one.**

`verify._board_copper()` had never returned a single pad. Its guard read
`len(net) < 3` with a comment describing a format the boards do not use: KiCad
writes `(net "MDGND")` on a pad here, not `(net 12 "MDGND")`. So
`check_isolation_gap()` — whose whole subject is where parts are — had been
measuring tracks and vias only, and reporting nothing wrong, which was true. It
sees 915 pads now.

And `pad_boxes()` decided a pad's layers from its **drill**: through-hole meant
every layer, anything else meant front. KiCad's `_ThermalVias` QFN puts the
3.2 mm exposed pad on F.Cu *and* B.Cu, so the back-side copper was invisible to
the router, which laid IRQ across it — **64 DRC violations from one
assumption**. The pad is asked what layers it is on now.

**And one value this repo had to choose, plus the wrong reason it nearly had.**
The MIDI receiver's series resistor has to hold the LED current inside the
TLP2761's 2–6 mA against *both* transmitters CA-033 allows — a 5 V one is 440 Ω
of source, a 3.3 V one is 43. The first version of this section said the
specification's own 220 Ω fails, at 6.6 mA. It does not: that used 0.2 V for the
driver's V_OL where the RP2040's table says 0.5, and the real spread is
**4.32–5.51 mA**, inside the range with 9 % of headroom. **390 Ω** is fitted
because it centres the spread at 2.66–3.80 mA, not because 220 breaks — and
`check_midi()` computes the current rather than comparing the value, so it holds
against drift either way.

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

**The board is placed, poured, routed and DRC-clean, and the floorplan is
now held to it.** 266 footprints and no reserved courtyards, 101.4 × 203.2 mm,
four layers, ground split at y = 157.4; 133 ground pads stitched to the planes,
1489 track runs and 516 vias; **0 DRC violations, and 8 unconnected items at
the envelope ADC** — `verify.UNROUTED_ITEMS` declares them and names the four
nets. See the fine-pitch section below: that number went *up* this pass and the
board got better.

`placement.py` is floorplan.py's zones turned into coordinates — twelve
rows in two bands, quad packages spanning the channels their sections serve,
computed from `design.SECTIONS` rather than typed — and `check_zones()` asserts
that a column's parts are in the ground domain its zone declares, so the two
files cannot drift apart. `gen_pcb.py` places every footprint through KiCad's
own `pcbnew`, draws the derived outline and pours the two grounds either side of
the split. It reserved a courtyard for each unchosen part until there were none
left to reserve.

**DRC went 262 → 0.** The first placement put quad packages across rows they do
not serve, and the fault underneath was a loop counter: `design.SECTIONS` keys
spare sections `(role, index)`, so U14's two terminated followers read as
channels 1 and 2 and dragged the package into the wrong band. The last six were
one text field — the VCAs' designators, which KiCad puts *west* of a
90°-rotated body, where the stability capacitor is.

**The board is 4.6× the floorplan's own area estimate**, and the estimate is not
what is wrong: 19020 mm² against 4135. A packing factor of 2.5 is fair for a
dense hand layout and `placement.py` is not one — it is one part per grid slot,
which trades area for being derivable and checkable. Both numbers are kept
because they answer different questions, and the gap between them is the price
of generating a board rather than drawing one.

**`placement.SIZE` had every multi-pin package transposed, and the word
"approximate" was carrying it.** The table declared itself estimates with DRC as
the authority, which is fair about a body dimension rounded down a millimetre
and is not fair about SOIC-14 at (9.2, 6.6) when KiCad's courtyard is 7.40 wide
and 9.16 tall. It survived because every consumer was transposed too: parts
modelled sideways collide with each other exactly as they would upright, and the
rows are generous enough that nothing crossed a threshold. The evidence was on
screen the whole time and nobody read it as evidence — `placement.py` printed one
board outline and `gen_pcb.py` printed another, 8 mm apart, on two lines of the
same build log. It surfaced the moment a part had to be fitted into a gap. The
table is read off KiCad's own courtyards now, and `gen_pcb.check_courtyards()`
is what holds it there: that file is the only place the model and the real
footprint exist at once, which is exactly why they were free to disagree.

**476 connections became 67, then 0, and the violation count never left zero.**
That last clause is the property worth protecting: a router that trades shorts
for finished connections is worse than one that gives up and says so. `route.py`
is Lee's algorithm with A* ordering — a uniform grid, two signal layers, a via
wherever the path changes layer — and it either finds a path or reports the net
by name.

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

**The last 67 connections were three different problems wearing one number**,
and that is the result of this pass. They were left as a choice between a finer
grid on thinner track and rip-up and retry. Neither of those, on its own, was
the answer.

| | |
|---|---|
| **three of the 23 nets were not congestion** | a pad's own copper cells were being marked "blocked" by the neighbouring pin's clearance ring, because two SOIC pins are closer together than one ring is wide. `IOUT1`, `IOUT4` and `VREF` had no reachable cell inside their own pads — and from outside, an unreachable pad and a full board look identical. `route.block_pad_copper()` |
| **the finer grid was priced and refused** | the corridor between two SOIC pins is 0.67 mm wide and the fitted rules need 0.65 of it, leaving a 0.02 mm window against a 0.45 mm pitch floor. It opens at 0.09/0.09 mm, which is **JLCPCB's 1 oz multilayer class and not its 2 oz one** — so "a finer grid" is really "give up 2 oz copper", on a board whose largest current is 120 mA of relay coil. [`rules.md`](docs/rules.md) |
| **rip-up and retry finished it** | at the pitch already fitted, on the first pass, in 20 s. `route.route_all()` |

**The pitch was never the reason, and the sentence that said it was had never
been evaluated.** `gen_pcb.py` declared 0.5 mm as "the tightest pitch these
rules allow and therefore the one that routes". Two tracks on adjacent cells
are `pitch − track` apart, so the tightest pitch these rules allow is
`0.25 + 0.20 = 0.45`. It is not a derivation with a slip in it; it is a
derivation that was never performed, written in the voice of one that had.
`rules.route_pitch()` performs it, and keeps 0.5 mm deliberately — 0.45 puts
two adjacent tracks at exactly the clearance, which passes DRC only because DRC
compares with `<`, and only while the board origin happens to land on KiCad's
0.1 µm lattice.

**Rip-up had been ruled out on an objection that dissolves in one line.**
Displacing individual nets sounds like it needs a ledger of what every cell was
before every claim — and a wrong ledger is a grid that disagrees with the
copper, which is a short. But nothing needs remembering: a released cell goes
back to what *blocking* said, and blocking is a constant. `Grid.freeze()` takes
that snapshot once and `Grid.release()` is three lines. The difficulty was
entirely in having asked "what was here before" instead of "what is here when
nothing is routed".

The cheaper-looking alternative was tried first and is worth keeping on the
record, because it is a good-looking wrong answer: rip up the *whole* board and
re-route it with the failed nets promoted. Every pass is legal, nothing can
short, no bookkeeping at all — and it goes 19, 7, 3, then random-walks. It
remembers **who** lost and nothing about **where**, and after a few passes
almost every net has lost once, so the order it produces is close to arbitrary.
Twenty passes never closed the board that rip-up closes in one.

**Rip-up also invalidated the one tuned constant in the router, and made it
worth a quarter of the board's holes.** `VIA_COST` was set to 2 by measuring
unrouted nets: 9 left 78 unmade, 6 left 69, 4 left 69, 2 left 67 — so cheap
vias "route better on this board". Every one of those values now reaches zero,
so the parameter no longer buys completeness, and what it buys instead is the
count: **452 vias at 2, 345 at 12**, flat after that. The old conclusion was
not wrong about the geometry, it was wrong about what the geometry implied. A
route that cannot get through has to go round, and a via is how it goes round —
so while each net had one attempt, cheap vias were worth having. Once a route
that cannot get through can move somebody else instead, it does not need the
via at all.

**And the sixty-eighth connection was not a routing problem at all.** With the
router finished, DRC still reported one unconnected item, which the count of 67
had been hiding for as long as the board had existed: `J8` pin 3 is MAGND, and
`J8` sat 18 mm inside the *digital* pour. `stitch_grounds()` skips through-hole
pads on the correct reasoning that a barrel already crosses every layer — but it
reaches the plane that is *under it*, so that barrel crossed four layers and met
the wrong ground on two and nothing on the other two. **A through-hole pad is
already stitched only if it is in its own pour.**

The fix is placement, not copper: `J8` carries VA+, VA−, MAGND, V5 and MDGND —
both rails and both grounds — so it is a straddler by `floorplan.py`'s own
definition, and it was filed as `DIGITAL` because it is a header and the other
three headers are. It sits on the line now, in the south-east corner
`floorplan.py` already named for the supply, with the analogue pins north of the
split and MDGND south. Stitching it across instead would have put the whole
board's analogue return on 19 mm of `F.Cu` running the length of the digital
zone, which is the thing `CROSSING_RULE` exists to forbid.

**Nothing this repo produced could be looked at without installing KiCad.**
Every output was either a file another tool reads — the sheet, the board, the
netlist, the BOM — or markdown. There was no *drawing*, so every review of this
design was a review by whoever had the toolchain. The mixer has plotted all
three of these since it had a board; `gen_plots.py` is that step, and the three
`kicad-cli` invocations carry its reasons across rather than rediscovering them
— three settings on the layout plot look cosmetic and are not, and without
`--bg-color` in particular the two plane layers render invisible in half of all
PDF readers.

The most useful page turns out to be In1.Cu, where the ground split plots as a
white band with the three relay courtyards straddling it — the design's central
claim, visible rather than asserted.

They live in `docs/` rather than a `fab/`, and that is derived rather than
copied from the sibling. The mixer's equivalents sit in `fab/` because they
travel with gerbers to a fabricator. Nothing here can travel anywhere yet, so
these are documents for reviewing an unfinished design, and CLAUDE.md's rule is
that the split is by audience. **There are deliberately no gerbers**, and
`gen_plots.orderable()` states why by reading `design.UNSPECIFIED` and
`design.DEFERRED` rather than by carrying a paragraph somebody has to remember
to delete: three parts have no footprint because nobody has chosen them, and
three blocks are not drawn. A gerber set would be a complete-looking package for
a board that must not be ordered.

The two PDFs are byte-normalised, which is the mixer's `--quality basic`
argument arriving one file type later. Two runs over an unchanged board differed
in exactly three bytes — the minute and second inside `/CreationDate` — so a
tracked 600 kB binary would be rewritten by every build whether or not the design
moved. `gen_plots.PDF_EPOCH` makes each file a function of the board, which is
the property that makes a tracked binary worth tracking.

**`test_verify.py` now checks its own faults, because three of them had
stopped being faults.** The harness proves every `verify.py` check *can* fail.
Nothing proved the mutation still had a target — and when the bypass relay was
chosen, three cases that named IEC contact numbers (`"11"`, `"14"`, `"A2"`) on a
part that numbers its terminals 1/12 and 9/10/8, 4/3/5 went quietly dead.
`set.discard` on a member that is not there is a no-op, so they planted nothing,
found nothing, and reported "caught" until a part changed for an unrelated
reason and someone happened to look.

The naive guard — "did the mutation change anything?" — passes all forty cases
and would have passed those three too, because they also `add` a pin and adding
one does change the set. **The discriminator is the discard**: you cannot remove
what is not there, so a discard that removes nothing is a mutation that has lost
its target. `dead_mutations()` runs before the cases do, and it was validated by
replanting the pre-G6S mutation and watching it fire.

**The supply's requirement is derived rather than estimated, and the estimate
was 2.5× out.** `supply_load()` walks the netlist — not a table of counts that
can drift from what is drawn — and sizes each rail on datasheet **maxima**,
which is the number a supply is chosen against, rather than the typicals
`coil_budget()` used. The board needs **±12 V at 110 mA and +5 V at 93 mA,
3.10 W**, against `supply-decision.md`'s "~44 mA per rail".

The cause is worth recording rather than patching. That document argued the CV
filters and envelope rectifiers should run single-supply off +5 V *precisely* to
keep the negative rail small — "the temptation will be to run everything bipolar
because it's simpler to think about. Resist it." The schematic did not: U7, U8,
U13 and U14 are all bipolar, 16 amplifiers of 40. **And the reason the advice
stopped applying is in the same document** — the 44 mA figure existed to make a
*charge pump* viable, and the topology it settles on is an isolated DC-DC, which
does not care. Running them bipolar is defensible; nobody had written down that
the constraint it violated had been retired.

Two smaller corrections fell out: `coil_budget()` costed the OPA1644 at 1.7 mA
per amplifier, which matches no row of its table (1.8 typ, 2.3 max), and the
TL074's maximum is the one figure in the supply arithmetic still unread — 8
amplifiers of 40, declared as `MEASURED["env_opamp_iq"]` rather than invented.

**And the requirement was still 25 % light, for a reason that is a mistake in
method rather than in arithmetic.** 3.10 W is the sum of each rail's power at
its own voltage, which is the right number for what the module dissipates and
the wrong one for what a converter delivers: V5 is made linearly from VA+, so
every milliamp of it leaves the converter at twelve volts and arrives at five.
`supply_fit()` counts from the converter's pins outward instead and gets
**3.87 W** — 213 mA on +Vout against 110 on −Vout. Summing rail powers is
exactly the shortcut that looks complete: three rails, three products, one
total, nothing visibly missing. What it omits is the topology between them, and
the omission is invisible until somebody draws the topology.

## The supply, and the question nobody knew was open

**The converter is on this board, and where it went was undecided in two places
at once.** `floorplan.ZONES` has carried a zone P — *"supply … the far corner
from A1 and R, with its own local return"* — since the first pass, while
`design.py` described J8 as a five-way **secondary** inlet fed from a converter
somewhere else. Both are prose, both were consumed, and they cannot both be
true.

**Nothing would have caught it.** A check that every zone holds parts unless its
block is deferred would have passed: zone P was empty and `"supply"` *was* in
`design.DEFERRED`, so the two agreed perfectly while disagreeing about the only
thing that mattered. This repo instruments values, nets and geometry, and a
decision that exists only as two sentences in two files is outside all three.
The general form is the third variant of the failure this project keeps finding:
**a deferred block cannot be checked for where it lives, because nothing is
drawn.** Deferral suspends every instrument at once.

The part is a **Traco TMR 6-2422WI** — 9–36 V in, ±12 V at 250 mA, 6 W, SIP-8,
1600 VDC, 50 pF of barrier and **580 kHz fixed-frequency PWM**, every figure read
first-hand from the TMR 6WI datasheet of 7 November 2023. The obvious cheaper
part, the plain TMR 6, is the same power in the same package for half the money
and is disqualified by one line of its own datasheet: *"100 kHz min."* on an
**RCC** topology, which is self-oscillating — its frequency moves with load, and
100 kHz sits exactly on the second harmonic of the mixer's 45 kHz pump.

Three results are worth carrying out of it.

**The ≥300 kHz rule is a fundamental-only rule.** `supply_beat()` computes what
`supply-decision.md` states: the pump's ripple has harmonics at every n × 45 kHz,
and the fitted part's own 522–638 kHz band contains the 12th, 13th and 14th — so
the nearest beat is **5 kHz** and no switching frequency, at any value, clears
them all. The rule is kept, because 50 kHz would still be the worst possible
choice, and it is not what makes this safe. What does is the **isolation** the
same document already bought: this module shares no rail with the mixer, so the
two ripples never meet at full size on one node. And the product is second order
— two terms 56 dB down make one 117 dB down.

**The barrier's own current is the load-bearing part, not the ripple.** 50 pF
across a switching node is 2.6 mA at 580 kHz, and without a local return it
takes the audio ground bond: 7.1 mV in series with every channel's return.
`barrier_return()` sizes C810 against a stated criterion — the largest capacitor
whose worst-case 100 Hz injection stays 6 dB under the mixer's own noise floor
in a third-octave band — which is 610 nF, so the value is the 470 nF the board
already buys. It returns 83 % locally and leaves 1.2 mV. **It does not finish
the job and the function says so:** the remaining 19 dB is a common-mode choke
in the inlet pair, which multiplies the loop impedance instead of dividing the
capacitor's, and it is a pass of its own rather than a guess in this one.

**The 5 V regulator's package is the answer.** 0.77 W — (12 − 5) × 93 mA plus
the part's own 10 mA quiescent — against the NCP1117 SOT-223's published
160 °C/W is 124 degrees of rise. The DPAK is the same die at 67 °C/W and 52
degrees. A 100 mA regulator goes in a SOT-223 without anybody thinking about it,
which is the whole reason the arithmetic is worth doing.

The isolation barrier is **a place on the board**, not a set of net names: the
primary lives west of `placement.ISOLATION_X` and south of `ISOLATION_Y` with no
ground pour under it at all, `gen_pcb` pours the southern MDGND as an
overlapping L to leave that corner empty, and `verify.check_isolation_gap()`
measures the region against the saved board. C810 is the one declared bridge.

**DRC had never once run against this project's own design rules.** The
mixer's hard-won lesson is that `SaveBoard()` rewrites the project file with
KiCad's defaults, so its `build.sh` re-runs its project generator afterwards to
put the rules back. This repo copied the re-run and not the rules:
`gen_project.py` wrote `"rules": {}` straight over the block `gen_pcb.py` had
just set through `pcbnew`. The right shape, applied in the wrong direction —
the re-run was the thing destroying them.

What that cost is smaller than it sounds and worth stating exactly rather than
dramatising: DRC takes *clearance* from the net class, and the net class has
always said 0.2 mm, so the copper already reported as DRC-clean genuinely is.
What went unchecked is every rule that is not a clearance — `min_track_width`,
`min_via_diameter` and `min_copper_edge_clearance`, all at KiCad's default of
zero.

**And the check that was supposed to prevent this was cited by name and did not
exist.** `gen_pcb.py`'s docstring said "`check_rules()` in verify.py is what
stops the discipline from decaying into a comment." There was no `check_rules()`
in `verify.py`. Nothing this repo has found is so exactly its own failure mode:
a check named and never written, holding together two files that could not
import each other, in a sentence whose subject is the danger of a discipline
decaying into a comment. It exists now, it reads the project and the board back
off disk, and the first fault planted against it in `test_verify.py` is the bug
it was written to find.

The two files could not have agreed by construction, either. `gen_pcb.py` said
"gen_project.py imports them so the two cannot disagree" — and importing
`gen_pcb.py` relaunches it under KiCad's interpreter before any constant is
reachable, so `gen_project.py` wrote its own literals instead. They matched
because one person typed them twice. [`rules.py`](rules.py) is the one copy.

**The clamp diode did not clamp, and reading one datasheet is what found it.**
`CLAMP_VF = 0.3` was the assumption with the least slack in the repo, and
`ASSUMPTIONS.md` said its basis was "a BAT54-class part at the microamps this
circuit draws". Both halves were wrong, and the second one broke the design.
`D803`'s anode is U8's *output pin* — `floorplan.py` puts it there deliberately
— so when the loop breaks it carries whatever the amplifier can source. The
OPA1644's own figure is **I_SC = 36 mA** (SBOS484D p8), three orders of
magnitude above the assumption and in the direction that costs forward drop. The
BAT54's own table gives **500 mV max at 30 mA**, which is +13.4 dB: over the
mixer's headroom by 5.5 dB, on the fault the clamp exists to prevent.

**And no series resistor rescues it**, which is why the fix had to be a part.
Both the normal 682 µA reference load and the fault current cross the same
resistor, so their ratio is fixed by the voltage ratio alone —
`I_fault / I_normal = 11.65 / 2.5 = 4.54×`, with R cancelling. Even sitting the
amplifier on its own negative rail only reaches 846 µA. `design.clamp_current()`.

A **PMEG2010AEH** — a 1 A trench Schottky run at 36 mA, so a thirtieth of its
rated current density — is 259 mV max there: **+6.3 dB with 1.5 dB of margin**,
and it drops into the same slot because SOD-123F is *narrower* than SOD-123.
Higher leakage is the price and it is free on a node inside an op-amp's feedback
loop. `clamp_gain()` computes the drop from the fitted part's datasheet at the
current `clamp_current()` derives, so the number is a result now instead of an
input, and `verify.check_fail_safe()` fails if the part is substituted.

**One constant was naming three different jobs.** `CLAMP_DIODE` was fitted at
the pump, the coil flybacks and the clamp alike, and the three want opposite
things: the pump wants low *leakage* and does not care about drop, the clamp
wants low drop at 36 mA and does not care about leakage. The BAT54 stays where
its leakage is the point.

**The fail-safe cannot see the one failure that is loud, and one diode can.**
`design.fail_states()` claimed the bypass relay's charge pump covered the
inverted reference failing to the positive rail. It does not: the pump collapses
when the *MCU* stops, and that failure leaves the MCU healthy, still emitting its
10 kHz, holding the relay in. The one state the fail-safe cannot see is the one
state that is +20 dB. D803 — a Schottky from `VREFN` to `MAGND`, reverse-biased
at −2.5 V and doing nothing in normal operation — turns it into **+7.4 dB, inside
the mixer's own 7.84 dB of headroom**. `design.clamp_gain()`.

**The two unchosen parts are chosen, and each was filtered by a number.** The
relay is an **Omron G6S-2 DC5** — "single-side stable", which is Omron's name
for non-latching and the property the whole block turns on. Its ratings table
gives 28.1 mA on 178 Ω at 5 V, which turns `coil_budget()` from a 75–120 mA
guess into **76–93 mA read**. The line worth reading twice is the contact
material: *bifurcated crossbar, Ag (Au-Alloy)*. A plain silver contact needs a
wetting current a guitar string will never supply, and fails intermittently in a
way that looks like a dry joint.

The MOSFET is a **Diodes DMG1012T**, chosen for one row of its table:
`R_DS(on) = 0.7 Ω max at V_GS = 1.8 V`. That is the gate voltage
`pump_timing()` computes and the only voltage this circuit can produce — every
other candidate is characterised at 4.5 V and would have left the region the
design actually lives in to a curve nobody read. It is SOT-523 and the spec said
SOT-23; the package was the one part of that requirement nobody had derived, so
it followed the electrical filter rather than the other way round.

**Choosing the relay retired the IEC placeholder.** `RELAY_PINS` carried IEC
60947 contact numbering, which was right while the part was `None` — it named a
standard instead of guessing a manufacturer. The G6S numbers its terminals
1/12 for the coil and 9/10/8, 4/3/5 for the poles, read off the Terminal
Arrangement diagram on page 5. **The de-energised state is the one drawn**, and
that is what checks the map against `bypass_state()`: the blade rests on 9–10
and 4–3 with no coil current, so those are the contacts that must carry the link
back to the mixer. Wired the other way the module would be *in circuit when it
was dead* — invisible in any netlist, visible only in that drawing.

Three planted faults in `test_verify.py` carried those IEC numbers as literals,
and choosing the part silently disarmed all three: `discard` on a pin the
netlist no longer has is a no-op, so the cases went on passing and stopped
meaning anything. They go through `RELAY_PINS` now.

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

**The list below is the previous pass's and its first two items are closed.**
What is genuinely open now, in order:

1. **Sync the board and route the controller zone.** The board on disk is the
   routed one from `bfa4483` — 55,854 segments, 767 vias — and **263 of the 288
   shared parts are at identical coordinates**, so the audio channels, CV rows,
   envelope rows, ADC and fail-safe keep their copper. What is needed, in
   KiCad: extend `Edge.Cuts` and the southern MDGND zone 26 mm south to open
   the strip the module sits in; **Tools → Update PCB from Schematic** against
   `out/cv-module.kicad_sch`, which deletes the 26 RP2040-periphery footprints
   and adds U19 and D806; place those two; and route **27 nets, about 94
   connections of 639**. `check_board_is_the_design()` fails until the sync is
   run, and `verify.UNROUTED_ITEMS` is the ratchet after it.
2. **The inlet fuse** — 1.6 A slow blow, derived, with no verified order code
   and no footprint. A plausible order code is a value, and §6 of the spec
   forbids inventing one.
3. **`MEASURED["noise_floor"]`** — a meter on the mixer's mono output. Still
   this module's most load-bearing unknown; see item 1 of the old list below.
4. **`MEASURED["mcu_dcdc_efficiency"]` and `MEASURED["pico_smps_efficiency"]`**
   — **two ammeters now, and they multiply.** One in series with U22's VIN and
   one in series with the Pico's VSYS pin with GPIO23 high. The budget closes
   at 212.9 mA of 250 and it failed at 254.6 before U22 took the relay coils,
   so this is the pair that decides whether that headroom is real.
5. **`MEASURED["env_opamp_iq"]`**, settled by fitting a TL07xH grade;
   **`MEASURED["vca_rin"]`**; and **`["dcdc_node_v"]` and `["inlet_loop_uh"]`**,
   both 40 dB from mattering — retire them or measure them.
6. **Whether to design to the fabricator's published 0.20 mm hole clearance**
   rather than KiCad's 0.25 mm default. Unchanged, and see
   `fabrication-class.md`'s last section for why it is deliberately separate.
7. **Gerbers**, which `gen_plots.orderable()` now gates on the routing rather
   than on nothing.

---

### The previous pass's list, kept

~~**The fan-out.**~~ **Closed.** `UNROUTED_ITEMS` is 0 and DRC is 0. See the
fine-pitch section above.

**The controller.** ⚠️ **Not closed, and it is the one thing this pass was set
that is not drawn.** The part is settled and derived; two computed gates stop the
drawing and both are decisions above it — `controller_package()` wants the board
at the 2 oz *minimum* class, 0.15/0.15 mm, and `controller_supply()` wants a
switcher for V3V3 or a larger converter. Item 2 below.

~~**The pad relay.**~~ **Closed** by deleting the pad rather than by choosing a
relay — see the pad result above.

~~**The Schottky forward drop.**~~ **Closed, and it was not a confirmation.**
Reading the curve found the clamp did not work; the fix is a part and the number
is computed from its datasheet now. See above.

~~**The two `UNSPECIFIED` parts.**~~ **Closed.** G6S-2 DC5 and DMG1012T, each
filtered by a number rather than a class.

1. **`MEASURED["noise_floor"]` — and this one cannot be closed at a desk.**
   It is a measurement on hardware that exists: the residual noise at the
   mixer's mono output, no input, level controls at the setting the module will
   replace. Everything downstream of it is already instrumented — `delta.py`
   computes that the module costs **0.11 dB or 0.85 dB quiescent, and 0.51 dB
   or 2.95 dB while the lead feature runs**, across the declared 50–400 µV
   range. Nothing more can be derived; what is missing is a meter on a bench.
   `DESIGN.md` upstream calls it "the measurement worth taking" and it is still
   this module's most load-bearing unknown.

2. **The controller's two gates, and they are one decision each.**
   `controller_package()`: 0.40 mm of pin pitch needs 0.12/0.12 mm or finer,
   so **0.09/0.09 and 1 oz outer copper** — the copper weight, a 0.23 mm grid
   at 4.7× the cells, and a per-net width for the coils that `route.py` does
   not have. The alternative is a **spreading fan** at 0.15/0.15, which keeps
   2 oz and is router work instead. `controller_supply()`: a
   switcher for V3V3, whose requirement is stated as numbers (12 V in, 3.3 V out,
   52 mA, >40 % efficient, and a frequency `supply_beat()` has to clear against
   both the mixer's pump harmonics and this converter's own 522–638 kHz band) —
   or a converter with more than 250 mA on +Vout, which is a part decision about
   a part already chosen and drawn. Neither is a drawing pass.

3. ~~**The DC-DC itself.**~~ ~~**The envelope ADC.**~~ **Both closed** —
   TMR 6-2422WI with its inlet choke, and MCP3564 with a real 3.3 V rail.

4. **`MEASURED["vca_rin"]` — R_IN is a free choice again, and it was not.**
   12k1 was forced by the pad's top step having to stay inside the part's
   100 kΩ; without it the datasheet's whole 7.5–100 kΩ is available and the
   trade is the one page 4 describes — *"lower values will produce the best
   noise performance at some cost in distortion"* — with a number on neither
   side. 7.5 kΩ is 2.1 dB quieter than what is fitted.

5. **The fail-safe's power-up sequence has a number to wait for.** The NR
   capacitor costs 20 ms of reference turn-on and the '541's Vcc *is* VREF, so
   for 20 ms every channel's full scale ramps from zero — and zero CV is unity
   gain. 20 ms is 4× the ~5 ms a relay needs, so it is a sequencing requirement
   rather than a hazard. `design.VREF_TURN_ON_S`.

6. ~~**The copper weight has stopped being a free declaration.**~~
   **Still true, and the objection to going finer is gone.** See
   `rules.track_current()` above: 0.33 °C at 0.09 mm of 1 oz. What is left of
   this item is the fabrication decision itself, which is task 1 of the next
   pass. Original text:

   **The copper weight has stopped being a free declaration.**
   `rules.COPPER_OZ` says 2 oz and the fitted 0.25/0.20 is legal at either, so
   holding the option has cost nothing. The controller ends that:
   `coarsest_class_for()` puts a 0.40 mm pin pitch at 0.12/0.12 or finer, and
   the only listed class that reaches it is **0.09/0.09, 1 oz only**. So the
   copper weight is now a decision with a part behind it, and what wants
   checking before it is taken is the one current on the board that is not
   microamps: `design.coil_budget()`'s 93 mA of relay coil on 0.09 mm of 1 oz
   copper is 29 A/mm² — **and that turned out to be the wrong instrument, not a
   number to read a curve for.** `rules.track_current()` puts the rise at
   0.33 °C. [`rules.md`](docs/rules.md).
