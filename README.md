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
| section 5 constraints | ✅ checked mechanically, 56 planted faults caught — **and the faults themselves are now checked** |
| deltas against the mixer's own model | ✅ four disagreements, three of them with `00-current-state.md` |
| floorplan, BOM, assumptions | ✅ |
| board | ✅ placed, poured and **fully routed** — 0 unconnected, 0 DRC violations |
| the design rules | ✅ one copy in `rules.py`, and DRC is finally enforcing them |
| the two `UNSPECIFIED` parts | ✅ **chosen** — Omron G6S-2 DC5 and Diodes DMG1012T. `UNSPECIFIED` is empty and no courtyard is reserved |
| the Schottky clamp | ✅ **read, and it had failed** — the BAT54 missed by 5.5 dB. PMEG2010AEH fits with 1.5 dB |
| the supply's requirement | ✅ derived from the netlist: **±12 V at 110 mA, +5 V at 93 mA, 3.10 W**. ❌ the DC-DC itself is not chosen |
| documents to look at | ✅ [schematic](docs/cv-module-schematic.pdf), [layout](docs/cv-module-layout.pdf), [render](docs/cv-module-top.png). ❌ no gerbers, and that is a gate |

Three shared blocks are deferred with reasons in `design.DEFERRED`: controller,
envelope ADC and supply. There were six. The relay drive is not deferred but
deleted, along with the pad it drove; the envelope rectifier and the fail-safe
are drawn. **`design.UNSPECIFIED` is empty**: the bypass relay and its MOSFET
are chosen, all 225 parts have a footprint, and no courtyard is reserved.

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

```bash
python3 design.py && python3 gen_netlist.py && python3 gen_sch.py \
  && python3 gen_project.py && python3 placement.py && python3 gen_pcb.py \
  && python3 verify.py && python3 test_verify.py \
  && python3 constraints.py && python3 delta.py && python3 floorplan.py \
  && python3 gen_bom.py && python3 gen_assumptions.py && python3 rules.py \
  && python3 gen_plots.py
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
| `rules.py` | the fabrication rules, the routing pitch derived from them, and the fab class read first-hand |
| `gen_plots.py` | the schematic, the layout and a render — the outputs you can look at without KiCad |
| `placement.py` / `route.py` | the floorplan as coordinates, and a maze router with rip-up and retry. Neither imports KiCad |
| `gen_pcb.py` | the board, through the deprecated `pcbnew` bindings |
| `verify.py` / `test_verify.py` | the constraints against KiCad's own netlist, and proof the checks can fail |
| [`FINDINGS.md`](docs/FINDINGS.md) | things wrong in the mixer repo — noted, never fixed |
| [`ASSUMPTIONS.md`](docs/ASSUMPTIONS.md) | everything guessed, with what it costs if wrong |
| `out/` | for machines: schematic, board, project, netlist, BOM as CSV. All generated |
| `docs/` | for people: [floorplan](docs/floorplan.md), [constraint audit](docs/constraints.md), [design rules](docs/rules.md), [shopping list](docs/SHOPPING.md), and the three plots. All generated |

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

**The board is placed, poured, fully routed and DRC-clean, and the floorplan is
now held to it.** 222 footprints and 3 reserved courtyards, 101.4 × 187.8 mm,
four layers, ground split at y = 157.4; 104 ground pads stitched to the planes,
1140 track runs and 345 vias; 0 unconnected items and 0 DRC violations.

`placement.py` is floorplan.py's zones turned into coordinates — twelve
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

Two of the four items this pass was set are closed and two are not, and the two
that are not are open for different reasons.

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

2. **The DC-DC itself.** Its requirement is now a set of numbers rather than a
   topology — isolated, ≥300 kHz, ±12 V at 110 mA, +5 V at 93 mA, 3.10 W — so
   what is left is choosing a part against them and drawing the inlet, the
   module and its filtering. That is the next increment, and it is the smallest
   of the three deferred blocks.

3. **The other two deferred blocks**, and they are deferred rather than open:
   the controller (RP2040, QSPI flash, crystal, USB, MIDI) and the envelope ADC
   (ADS131M08 or MCP3564, sample rate settled at 2 kHz). Each is a block of its
   own, not a value to fill in, and drawing one badly is worse than leaving it
   declared — spec §6's rule applied to a schematic.

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

6. **The copper weight is still a declaration rather than a decision.**
   `rules.COPPER_OZ` says 2 oz and the fitted rules are legal at either, so it
   costs nothing to hold the option — right up until something wants
   0.09/0.09 mm, which is 1 oz only. Nothing does: the largest current on the
   board is `design.coil_budget()`'s 93 mA of relay coil. Worth deciding when
   the supply lands, because that is the block that would change the answer.
   [`rules.md`](docs/rules.md).
