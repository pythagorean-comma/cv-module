# CLAUDE.md — cv-module

Rules that must survive context compaction. The opening prompt will be forgotten
by hour three of a schematic session; this file will not.

---

## The two repositories

| | |
|---|---|
| **This repo** (`cv-module`) | The per-string CV generation module. New, churning, nothing fabricated |
| **`../summing-mixer`** (or wherever it is mounted) | The existing six-channel summing mixer. **Boards are ordered and fabricated.** |

### The mixer repo is READ-ONLY. Absolutely.

Its own documentation states: *"Nothing in this repo is to be modified."* The
boards exist in physical reality. Nothing you can do here justifies changing it.

- **Never** write, edit, create, delete, stage or commit anything under the mixer
  repo path.
- **Never** run `git` commands from a directory that contains both repos. Keep them
  as siblings, never nested.
- If something there looks wrong, **write it down in `docs/FINDINGS.md`**. Do not
  fix it.

### Read-only means the interface, not the code

The mixer repo is a **fabricated hardware interface that this module references**,
and referencing an interface does not mean importing another project's Python. So
there are two relationships and they must not be confused:

- **the interface** — `design.py`, `source.py`, `fab/mechanical-*.json` — is
  consumed at the pinned commit through `contract/socket.py` and never copied;
- **the KiCad plumbing** — `sexp` `kisch` `symlib` `kicad` `kisim` — is **copied
  into `toolchain/` and is ours to modify.**

See the Toolchain section for what went wrong with the previous arrangement.

### Record the fabricated revision

The boards were fabricated from a specific commit. This module must mate with
**what was actually built**, not with whatever the mixer's `design.py` says later.
Capture the hash in `contract/PINNED.md` and check against that commit, not `HEAD`.

---

## Consume the contract, do not copy it

The mixer repo is the single source of truth for the interface. The enclosure repo
already consumes `fab/mechanical-*.json` rather than duplicating it — this module
is a third consumer and follows the same pattern.

**Import these; do not retype them:**

- `DC_BLOCK_VALUE`, `RIN`, `NEGATIVE_RAIL_DROP`
- `MEASURED["noise_floor"]`
- `CHANNEL_POT_FP = CONN_FP[3]` and the `RV{n}01` pin order
- `fab/mechanical-*.json`

**Call these rather than reimplementing them**, so the effect of hanging this
module off the socket can be shown as a delta against the existing model:

- `summing_stage_noise(wiper=…)` — the wiper source resistance disappears when a
  buffer replaces the pot. Show what that does.
- `attenuator()`, `attenuator_input_impedance()`, `coupling_burden()`
- `output_swing()`, `clipping_peak()`

If a constant cannot be imported cleanly, put a single adapter in
`contract/socket.py` with a comment naming the upstream symbol. **One copy, one
place, one reason.** Never a magic number inline.

---

## Read before writing

Before generating any design code, read the mixer's `design.py` and `verify.py`
and write `docs/STYLE.md` — a short note on the conventions you found: naming,
how constants are declared, how checks are structured, how units and derivations
are expressed. Then follow it. This repo should read like a sibling of that one,
not like a stranger.

Pay particular attention to `check_attenuators()`, which compares the netlist. It
is the existing precedent for the kind of check `verify.py` here should contain.

---

## Design rules

**Two things this pass settled that are worth carrying.** `UNSPECIFIED` is empty
— the bypass relay is an Omron G6S-2 DC5 and its MOSFET a Diodes DMG1012T, each
chosen by a number the design computes rather than by a class. And the clamp
diode **had failed and every instrument agreed it worked**, because all of them
read one assumed constant: `D803` sits on an op-amp's output pin and carries its
36 mA short-circuit current, not the "microamps" `ASSUMPTIONS.md` claimed, and a
BAT54 there is 5.5 dB over the mixer's headroom. `clamp_gain()` computes the
drop from the fitted part's own datasheet now. An assumption that names the
wrong *operating point* is invisible to every check that consumes its result.

1. **Do not invent values.** If something is not in `docs/hardware-spec-v0.md` and
   cannot be *derived* from it, stop and ask. A schematic full of plausible values
   is worse than an incomplete one, because it looks finished. §6 of the spec lists
   the specific things not to invent.
2. **Every computed value carries its derivation**, not just its result.
3. **One channel completely, then replicate.** The failure mode of a six-channel
   spike is six copies of a wrong front end.
4. **Flag anything in the spec you think is wrong.** Twelve claims in the source
   documents have already been overturned, two of them by a datasheet contradicting
   a research summary. The spec is fallible; say so when you find it.

---

## Load-bearing constraints — and which of them actually are

Five were listed here, attributed to the mixer's design documentation, under the
heading *"check these mechanically, not by eye"*. **They have now been tested
for a mechanism and they are not equivalent.** One had none at all.

`constraints.py` computes, for each, the mechanism, the threshold the arithmetic
supports, and the margin. `docs/constraints.md` is its output. Run it before
treating any line below as settled.

The distinction that matters: a constraint with thin margin is load-bearing and
`verify.py` must hold it. A constraint with 60 dB of margin is good practice and
should not be defended as though the design depended on it. The attribution was
also only half true — 2a and 4 do come from the mixer's own documents and
functions, 1 and 3 are derivable from its constants, and 5 appears nowhere in it.

### Load-bearing — `verify.py` must test these

**Numbered as the spec numbers them.** This section used to run 1–4 in its own
order, which made it the only artefact in the repo disagreeing with
`hardware-spec-v0.md` §5 — and since `verify.py` prints the spec's numbers and
every `constraint N` reference in `design.py` uses them, "constraint 3" meant the
PIN load here and the SIN DC everywhere else. Grouping by load-bearing versus
practice is the point of this section; renumbering was not.

**§5.2 — Exactly one bond** between module audio ground and board AGND. The mixer's
own `_GROUND_RULE` applied across the connector: a second bond makes a loop
enclosing the mixer's AGND pour and the whole length of the loom. Binary —
either there is one bridge or there is not. `R901`.

**§5.1 — No *supply* current from `VREG`, `V+` or `V−`.** Every mA off V− costs
65 mV of rail (55 Ω pump + 10 Ω filter), and less rail is less headroom.
**Reworded, because "nothing" is unachievable:** the mixer's summer sources
this module's 212 µA of signal current from its own rails, exactly as it did
for the potentiometer. What is checkable is that no mixer rail net appears in
this module's netlist, and it is free to honour because the module's supply is
isolated. The arithmetic allows 21.8 mA before `check_headroom()` upstream
fails, so the real margin is ~100×.

**§5.4 — `PIN{n}` presents 5–10 kΩ**, keeping the DC-block corner inside the
15.9–31.8 Hz the fabricated design already sweeps. **Corrected:** the old
wording said *"or the 31.8 Hz corner moves"*, and 31.8 Hz is the corner at
5 kΩ — one end of the window, so the sentence held at exactly one point in
its own range. 10 kΩ gives 15.9 Hz and is what this module presents.
Mechanism is `coupling_burden()`, the mixer's own function. Note the trade the
old wording hid: the top of the window gives back **5.72 dB of subsonic
rejection**, which is the same figure `DESIGN.md` quotes for choosing 1 µF
over 2.2 µF in the first place.

**§5.3 — `SIN{n}` puts no more DC through the master pot's wiper than the
mixer already does.** **Restated:** *"zero DC by construction"* overstates by three
orders of magnitude and is unachievable — a servo is feedback, not
construction, and the series capacitor that would be construction puts a
second high-pass within a decade of the mixer's own 15.9 Hz. The servo gives
0.5 mV, which through `C703` and `R706` is 3.0 nA at the wiper, against the
0.2–1.0 nA the mixer accepts from `U1B`'s own offset. **The absolute threshold
at which a wiper goes audibly noisy is not sourced anywhere in this project**
— the claim is a comparison against the design we plug into, not a limit met.

### Good practice — do it, do not defend it as load-bearing

**§5.5 — Audio as twisted pairs inside individual shields**, shields grounded
at the main-board end only. Real mechanism, **59 dB of margin**: both loom nodes
are low impedance, because `PIN{n}` is `R{n}01` in parallel with the mixer's
own `C{n}01` and the capsule behind it — **8 Ω at 20 kHz, not 10 kΩ**.
Computing it as 10 kΩ gives −51 dB and *fails* the −54 dB isolation
requirement; the correct figure is −113 dB. **If you re-derive this, get the
impedance right** — that one substitution is 62 dB and the difference between
"mandatory" and "cheap insurance".

Same correction kills a hazard nothing had noticed: the loom carries a
channel's input and output in one twisted pair and the module is
non-inverting end to end, so intra-pair coupling is *positive feedback* around
the channel. 103 dB down, for the same reason.

### Struck — do not reinstate

~~**§5.2, second sentence** — six separate returns to six pin-3s, not commoned
in the module.~~ **No
mechanism.** Per-channel returns exist to prevent shared-impedance crosstalk.
With a single bond carrying all six channels that is 122 dB below one string on
a 100 mm bond and 103 dB on a deliberately bad one, against a −54 dB
requirement — 49 dB of margin, unreachable from physics.

Satisfying it literally cost a four-resistor difference-amplifier front end,
worth 0.008 dB of system noise. The front end is a two-resistor inverting stage
now, and `design.FRONT_R` carries the arithmetic.

**Why it survived is the part to keep.** The clause was generated in an earlier
session answering a question about power, then written into this list — and being
in a list headed *"load-bearing, check these mechanically"* is what made it
unquestionable. Every instrument downstream agreed with it: the netlist satisfied
it, `verify.py` asserted it, `test_verify.py` proved the assertion could fail.
All of that was true and none of it asked whether the requirement had a
mechanism.

That is this repo's sibling failure with the polarity reversed. `../summing-mixer`
records a **source cited and never read** (`PUMP_RULES`). This was a **constraint
cited and never derived**. From the inside, a well-checked wrong constraint and a
well-checked right one look identical.

### Also struck, and for the same kind of reason — the 2-bit coarse pad

**Spec §4.1 asks for 0/−6/−12/−18 dB on latching relays. Do not draw it.**
`design.pad_benefit()` prices it and `delta.pad_system_delta()` states the answer
as a system penalty: **0.000 dB, at every noise floor in the declared range.**

The mechanism, because it is the part that must survive compaction: the
SSI2164's noise table sweeps **R_IN and R_OUT together** at A_V = 0 dB, and the
rise across it belongs to **R_OUT**. A pad raises R_IN. The alternative is not
"no attenuation" — it is the control port, which reaches the same level for no
parts, and against which the pad is 0.03–3.9 dB *worse* at the cell. The
datasheet's own THD at A_V = −20 dB is lower than at unity, so there is no
distortion argument either. It cost 36 parts, 52 % of the placed courtyard, two
thirds of the BOM, 24 coil drives and a coil supply rail.

**The instrument that failed here is one level further out than the last one.**
Constraint 2 was a claim in a list headed *check these mechanically*. This was an
`Assumption` in `ASSUMPTIONS.md` — the repo's own mechanism for recording what it
does not know — whose *"if it is wrong"* clause cancelled its own consequence:
"the pad steps are noisier than modelled, but they are used when the source is
hot, so the signal is larger by the same amount … it does not change a component
value." Every clause false, and the effect was that nobody computed it for five
documents. **An assumption whose consequence is written as self-cancelling is an
assumption nobody will ever compute.** Nothing in this repo instruments the
reasoning inside a declaration, and nothing can.

---

## The supply, and where the converter went

**The DC-DC is on this board.** It was an open question that nobody had noticed
was open: `floorplan.ZONES` has carried a zone P — "supply", far corner, its own
local return — since the first pass, while `design.py` described J8 as a five-way
*secondary* inlet fed from a converter somewhere else. Both are prose, both were
consumed, and they cannot both be true.

**Nothing would have caught it and that is the part to carry.** A check that
every zone holds parts unless its block is deferred would have passed: zone P was
empty and "supply" *was* in `design.DEFERRED`, so the two agreed perfectly while
disagreeing about the only thing that mattered. This repo instruments values,
nets and geometry; a decision that exists only as two sentences in two files is
outside all three.

The general form, and it is the third variant of the failure this project keeps
finding: **a deferred block cannot be checked for where it lives, because nothing
is drawn.** Deferral suspends every instrument at once. That is an argument for
drawing blocks early and badly rather than late and well.

Three things about the block that must survive compaction:

* **The isolation barrier is a place, not a net name.** The primary side —
  `IGND`, `VIN`, `VIN_P` — lives west of `placement.ISOLATION_X` and south of
  `ISOLATION_Y`, with **no ground pour under it at all**. `gen_pcb.build()`
  pours the southern MDGND as an overlapping *L* for that reason, and
  `verify.check_isolation_gap()` measures the region rather than a clearance.
  `C810` is the one declared bridge and it is in `design.ISOLATION_BRIDGE`.
* **The `>=300 kHz` rule is a fundamental-only rule.** `design.supply_beat()`
  shows the pump's 12th, 13th and 14th harmonics all fall inside the chosen
  part's own 522–638 kHz band, so the nearest beat is **5 kHz** and no
  switching frequency clears every harmonic. What makes it safe is the
  isolation — this module shares no rail with the mixer — and the fact that the
  product is second order. Do not re-derive the rule and stop there.
* **Summing rail powers understates a linear rail.** `supply_requirement()`
  says 3.10 W and the converter has to deliver 3.87, because V5 is made from
  VA+ and leaves the converter at twelve volts. `supply_fit()` counts from the
  converter's pins outward.

---

## Toolchain

**Follow `../summing-mixer`. Do not use SKiDL.**

The facts about KiCad's Python surface are unchanged and still worth knowing:
there is no official API for schematics, the SWIG `pcbnew` bindings are
deprecated as of KiCad 9 with removal planned for 11, and the IPC API via
`kicad-python` is PCB-focused. What was wrong was the conclusion drawn from
them. The sibling repo does not work around those limits, it goes through them,
and its boards exist.

Two different mechanisms there, and they should not be conflated:

| | how | in the mixer |
|---|---|---|
| netlist and schematic | **s-expressions written directly.** No API involved — `sexp.py` is a tokeniser, a parser and a pretty printer, about a hundred lines | `sexp.py`, `kisch.py`, `gen_sch.py` |
| board | **the deprecated SWIG `pcbnew` bindings**, run under KiCad's own bundled interpreter | `gen_pcb.py`, invoked by `build.sh` upstream; here `gen_pcb.py` relaunches itself |

So:

- **Do synthesise a `.kicad_sch`.** The previous instruction said not to. The
  sibling repo synthesises one from geometry, reads it back through
  `kicad-cli`, and compares it to `design.py` net by net — which is the whole
  reason its `verify.py` catches a wire that missed its endpoint. That loop is
  not available any other way.
- **Import the KiCad plumbing from `toolchain/`, never from the mixer.**
  **This reverses the previous instruction, which was to import the mixer's
  `sexp.py` read-only at the pinned commit through `contract/socket.py`.** That
  was followed literally and it did not do what it says. `socket.py` appended
  the mixer's root to `sys.path`, so `import sexp` resolved off *disk*, at
  whatever the working tree happened to say — the pin covered `design.py`, read
  with `git show`, and nothing else. The guard was a clean-tree assertion over a
  hand-kept list of files, and the list had to grow every time a generator here
  imported one more: it named `kisim` and `source`, while `sexp`, `kisch`,
  `symlib` and `kicad` came off disk with nothing asserted about them at all. A
  sheet written by a modified `kisch` would still have been compared to
  `design.py` — by a comparison running through the same modified `kisch`.

  `sexp.py`, `kisch.py`, `symlib.py`, `kicad.py` and `kisim.py` are copies in
  `toolchain/` now, and they are this repo's: modify them as needed and record it
  in `toolchain/PROVENANCE.md`. There is deliberately **no check that they still
  match upstream**, because such a check would put the dependency back.

  **The line, and it is the one to hold:**

  | copied into `toolchain/` | referenced at the pin, via `contract/socket.py` |
  |---|---|
  | `sexp` `kisch` `symlib` `kicad` `kisim` | `design.py`, `source.py`, `fab/mechanical-*.json` |

  The left column carries no hardware content — no value, no net, no dimension,
  nothing that has to agree with a board that exists. `kisim.py` argues its own
  side in its docstring: *"it is copied between repositories unchanged, like
  kicad.py, sexp.py and symlib.py."* The right column is the interface, and
  copying it is the mistake the whole arrangement exists to prevent: `delta.py`
  expresses this module's effect as a delta against *the mixer's own* model, and
  a forked `source.py` would silently make that a comparison with a copy of
  itself.

  So **the mixer's root is never on `sys.path`**, and every byte read from it
  comes through `socket.show()`, which is `git show <pin>:<path>`.
  `socket.check_pin()` refuses the path entry and
  `socket.check_no_mixer_imports()` walks `sys.modules` and refuses any module
  loaded from a file under the mixer — by a provenance marker rather than by a
  list of names, because a list can only ever name the collisions somebody
  already thought of. `test_verify.py` plants all four failures.

  Note the one subtlety: the pinned `design.py` imports `source` and `kisim`
  itself, and those resolve to *pinned* module objects, not to `toolchain/`'s
  copies. The fabricated design must compute what it always computed, whatever
  we do to our copy.
- **Use the deprecated `pcbnew` bindings for board work**, as `gen_pcb.py`
  does. Deprecated is a schedule, not a defect; when removal lands, that is a
  problem for both repos at once and they should solve it together.
  **This is done now**, and two things about it are worth carrying: the board
  generator has to run under KiCad's own interpreter (`gen_pcb.py` relaunches
  itself, rather than adding a `build.sh`), and `SaveBoard()` rewrites the
  project file with KiCad's defaults, so `gen_project.py` must run *after* it
  or every design rule is silently gone. The placement itself lives in
  `placement.py`, which imports no KiCad at all — a placement that can only be
  read inside the thing that needs `pcbnew` is a placement nobody can check.
- **No third-party packages.** The mixer's README makes a point of it — *"there
  is no virtual environment and no `requirements.txt`, because there is nothing
  to install"* — and it is what lets the verification loop run anywhere KiCad
  runs. SKiDL would have bought a netlist writer that `gen_netlist.py` is sixty
  lines without, at the cost of that property.
- **If you believe a better approach exists, say so before writing code.**

The most valuable output of this repo is still not a drawn schematic. It is:
derived values with arithmetic shown, a netlist machine-checked against the
constraints above, `verify.py` with `test_verify.py` proving its checks can
fail, `constraints.py` proving the constraints have mechanisms, the floorplan
and ground strategy, and an honest `docs/ASSUMPTIONS.md`.

---

## Layout of this repo

**Everything in `out/` is generated. `docs/` is mixed and the listing below says
which is which.** Everything else is source.

**Two things this section used to say that were wrong**, both worth keeping
because they are the same mistake in different places. It said "the four
`gen_*.py` are the only things that write to `out/`" — `constraints.py` and
`floorplan.py` have always emitted a document as well, so the `gen_` prefix looked
like an invariant and never was. And it said "everything in `out/` and `docs/` is
generated", which was true for the ten minutes before the root's prose moved into
`docs/`. **The arrow list is the authority**: if a file is on the right of an
arrow, something generates it and an edit to it is lost on the next run.

**The root holds two files.** It held eleven markdown files, of which two were
spent prompts whose toolchain advice this file has since reversed. Prose that
records a decision moved to `docs/`; prose that recorded an instruction was
deleted. Keeping a decision log is the point; keeping paths not travelled is
cruft.

```
cv-module/
  README.md              what this is, where it stands, what is open
  CLAUDE.md              this file

  docs/                  every document a person reads
    hardware-spec-v0.md  authoritative spec — read first. Carries an index of
                         its own overturned claims; it is v0 and unedited
    00-current-state.md  context: why the choices are what they are. Two of its
                         claims lose to delta.py, marked at the top
    STYLE.md             the mixer's conventions, written after reading it
    ssi2164-control-port.md  the datasheet read first-hand — spec corrections
    element-revisit.md   SSI2164 vs THAT2180 vs THAT4301, and where it landed
    supply-decision.md   isolated DC-DC at >=300 kHz, and why. Carries its own
                         index of six numbers that moved once it was drawn
    FINDINGS.md          anything wrong in the mixer repo — noted, never fixed
    ASSUMPTIONS.md       everything guessed                      [generated]
    constraints.md       does each constraint have a mechanism?  [generated]
    floorplan.md         zones, domains, boundary crossings      [generated]
    rules.md             the fab class, and what it decides      [generated]
    SHOPPING.md          what to buy and from where              [generated]
    cv-module-schematic.pdf   the sheet, for reading              [generated]
    cv-module-layout.pdf      one page per copper layer           [generated]
    cv-module-top.png         the board, at a glance              [generated]

  contract/
    PINNED.md            the fabricated commit hash — socket.py parses it
    socket.py            the only place upstream constants are adapted

  toolchain/             KiCad plumbing, copied from the mixer. Ours to modify
    PROVENANCE.md        which commit each came from, and what was changed
    sexp.py kisch.py symlib.py kicad.py kisim.py

  design.py              values, derivations, the netlist and the symbol patch
  constraints.py         does each constraint have a mechanism? one did not
  delta.py               this module's effect, via the mixer's own functions
  floorplan.py           zones, ground domains, boundary crossings
  rules.py               the fabrication rules, and the arithmetic behind them
  placement.py           the floorplan as coordinates. No KiCad import
  route.py               a maze router with rip-up and retry. No KiCad
  verify.py              the constraints, checked against KiCad's own netlist
  test_verify.py         plants faults to prove verify.py's checks can fail

  gen_pcb.py             -> out/cv-module.kicad_pcb, through pcbnew. Relaunches
                         itself under KiCad's Python, then re-runs gen_project
  gen_netlist.py         -> out/cv-module.net
  gen_sch.py             -> out/cv-module.kicad_sch
  gen_project.py         -> out/cv-module.kicad_pro, the lib tables,
                         out/cv.kicad_sym and out/cv.pretty -- the project's
                         own symbols *and* its one own footprint
  gen_bom.py             -> out/cv-module-bom.csv, docs/SHOPPING.md
  gen_plots.py           -> docs/cv-module-{schematic,layout}.pdf, -top.png
  gen_assumptions.py     -> docs/ASSUMPTIONS.md
  constraints.py         -> docs/constraints.md
  floorplan.py           -> docs/floorplan.md
  rules.py               -> docs/rules.md

  out/                   for machines: the sheet, the board, the project, the
                         netlist, the BOM as CSV, and from-kicad.net /
                         from-kicad-erc.json / from-kicad-drc.json, which
                         verify.py regenerates on every run
```

**The split between `out/` and `docs/` is by audience, not by file type.** `out/`
is what another tool reads next — KiCad opens the sheet, a quoting tool or an
assembly house reads the CSV. `docs/` is what a person reads at a screen.

**`docs/` mixes source and generated, so the four marked `[generated]` above are
the ones never to hand-edit.** An edit to one is lost on the next run, silently,
which is the worst way to lose one. That mixing is the price of one folder for
prose, and it is why the listing marks them rather than leaving it to be inferred
from a filename.

Run order, and each step reads the one before:

```bash
python3 design.py && python3 gen_netlist.py && python3 gen_sch.py \
  && python3 gen_project.py && python3 placement.py && python3 gen_pcb.py \
  && python3 verify.py && python3 test_verify.py \
  && python3 constraints.py && python3 delta.py && python3 floorplan.py \
  && python3 gen_bom.py && python3 gen_assumptions.py && python3 rules.py \
  && python3 gen_plots.py
```

**`rules.py` is last in that list and first in the dependency order**, which is
worth not being confused by: `gen_pcb.py` and `gen_project.py` both import it,
so its constants are already in force by the time anything runs. Its own line
only writes `docs/rules.md`.

**`gen_plots.py` produces the only outputs a person can look at without
installing KiCad** — the schematic, one plotted page per copper layer, and a
render of the board. It must run after `gen_pcb.py`, and it rewrites each PDF's
`/CreationDate` to the epoch so that two builds of one board give byte-identical
files: these are tracked binaries, and a tracked binary that churns on every run
is one whose history says nothing. **It deliberately writes no gerbers.**
`gen_plots.orderable()` holds the reason and reads it off `design.UNSPECIFIED`
and `design.DEFERRED`, so choosing the last part is what changes the answer.

**`gen_pcb.py` comes before `verify.py` for the same reason the schematic
generators do**: verify.py runs `kicad-cli pcb drc` over the board and reads the
report back, so the board has to exist. It also re-runs `gen_project.py` itself,
because `SaveBoard()` rewrites the project with KiCad's defaults and takes every
design rule with it — the mixer's `build.sh` exists for exactly that.

**The two schematic generators come before `verify.py` and that ordering is the
loop.** `verify.py` runs `kicad-cli sch export netlist` over the sheet and
compares what KiCad found in the geometry to `design.py`, by name and pin. It
used to read `out/cv-module.net`, written by `gen_netlist.py` from the same
`design.py` its checks import — a comparison that could not fail for a
transcription error because there was no transcription. It also runs
`kicad-cli sch erc`, and `verify.ERC_ALLOWED` declares the residue with a reason
and an exact count, so a new violation of a declared class still fails.

**`test_verify.py` checks its own faults now, and it had to.** Three planted
mutations named the bypass relay's contacts as IEC numbers, which was right
while the part was `None` and dead the moment a G6S was fitted — `set.discard`
on a member that is not there is a no-op, so they planted nothing and went on
reporting "caught". `dead_mutations()` runs before the cases and refuses a
discard that removes nothing. The naive version of that test — "did the
mutation change anything?" — passes all forty and would have passed those three,
because they also `add` a pin. **The discriminator is the discard.**

**`test_verify.py` is not optional and is the reason `verify.py` means
anything.** A green check proves nothing on its own — the failure this project
keeps finding is a check that passes and covers less than its name. That file
mutates the netlist into each fault the constraints exist to prevent and fails
if any check does not notice. 31 faults now, and three of the new ones are
*drawing* faults — a wire that missed its endpoint, two nets touching, an
interior node that lost its label — which were not reachable at all while both
sides of the comparison came out of `design.py`.

Its own fixtures leaked, and that is worth keeping written down: three cases
mutate `design` itself and none of them undid it. Nothing showed, because each
check reads a different part of the module and the cases happened not to overlap.
Adding one case that compares against `design.NETS` broke it on the first run.
`_design_restored()` is the fix. A harness whose fixtures leak is the same
failure one level up: it passes, and it stops meaning what its name says.