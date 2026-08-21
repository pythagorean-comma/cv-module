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

**And `design.DEFERRED` is empty now.** The controller was the last entry; the
converter, the envelope ADC, the envelope rectifier and the fail-safe went
before it, and the relay drive was deleted rather than drawn. What follows from
that is worth knowing before it is discovered: `gen_plots.orderable()` reads
`DEFERRED` and `UNSPECIFIED`, both are empty, and every part has a footprint —
so **nothing stopped a fabrication package being written any more** -- and one
is written now, by `gen_fab.py`, into `fab/`. `orderable()` is still the gate
and is imported there rather than restated. Gerbers were a decision and the
decision has been taken; what is still open is the *order*, and `fab/ORDER.md`
lists which fields.

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
  `IGND`, `VIN_J`, `VIN_F`, `VIN`, `VIN_P`, listed in `design.PRIMARY_NETS` —
  lives west of `placement.ISOLATION_X`, south of `ISOLATION_Y` and **north of
  `placement.isolation_south()`**, with **no ground pour under it at all**.
  `gen_pcb.build()` pours the southern MDGND as three overlapping rectangles
  for that reason, and `verify.check_isolation_gap()` measures the region
  rather than a clearance. `C810` is the one declared bridge and it is in
  `design.ISOLATION_BRIDGE`.

  **The southern edge is new and its absence is the finding.** The region was
  a quadrant with no bottom, which was true for exactly as long as the supply
  band was the southernmost thing on the board — and it stopped being that
  when the Pico got a strip below it. Two consequences at once: the check
  reported `D806`'s VSYS and VMOD copper, 27 mm south and squarely digital, as
  *inside the primary's region*; and the pour that leaves that region bare
  left **the module strip's western third over no ground plane at all**. The
  check was right about the region, and the region had grown a tail.
* **The `>=300 kHz` rule is a fundamental-only rule.** `design.supply_beat()`
  shows the pump's 12th, 13th and 14th harmonics all fall inside the chosen
  part's own 522–638 kHz band, so the nearest beat is **5 kHz** and no
  switching frequency clears every harmonic. What makes it safe is the
  isolation — this module shares no rail with the mixer — and the fact that the
  product is second order. Do not re-derive the rule and stop there.
* **The inlet fuse is fitted and the blocker was a catalogue.** SCHURTER
  UMT 250, 1.6 A time-lag, `3403.0168.11`, in the live conductor between `J8`
  and the choke -- so `VIN_J` reaches only the inlet and the fuse, and `VIN_F`
  only the fuse and the choke. A fuse is a series element in one leg and
  shunts nothing across the pair, which is why it may sit in front of the
  winding where a capacitor may not. Three things to carry: **1.6 A and not
  the 1.5 A this repo derived**, because 1.5 A is not one of the eighteen an
  IEC 60127 series offers and a value that falls between two catalogue steps
  is a derivation that never met a catalogue; **`inlet_budget()`'s series
  resistance got three names**, because the moment the fuse joined the loop
  `choke_r` stopped being the choke's and every `choke_*` key built from it
  went on being called that -- `barrier_return()`'s fault, one block along;
  and **what a fuse is worth here is bounded by a part nobody has chosen**,
  since 1.25 x In takes an hour to open and a 2 A brick is 1.25 In.
* **The two hole rules are owned, at `rules.hole_rules()`**, and the open
  question about them did not survive being asked of the right page. It read
  *"whether to design to the fabricator's published 0.20 mm rather than
  KiCad's stricter 0.25 mm default"* -- **JLCPCB's number, on a PCBWay
  board**. PCBWay publishes 0.406 mm hole-to-hole and 0.178 mm hole-to-copper,
  so the fabricator is stricter on one and looser on the other and there was
  never one comparison to make. The rule is the stricter of published and
  KiCad's own, pointing both ways, and neither binds: `via_exclusion()` shows
  the *copper* rule setting all three of a via's distances at this class.
* **Summing rail powers understates a linear rail.** `supply_requirement()`
  says 3.11 W and the converter has to deliver 3.89, because V5 is made from
  VA+ and leaves the converter at twelve volts. `supply_fit()` counts from the
  converter's pins outward, and every rail now carries a `source` so a child
  rail is not counted twice.
* **The barrier's return is a divider and both sides are fitted.** `C810`
  divides `Z_Y`; `L801` — a WE-SL2 744222, 2 × 1 mH, immediately at `J8` and
  ahead of every other primary part — multiplies `Z_loop`. Together they take
  the 580 kHz residual at the audio bond from 7.15 mV bare to **1.14 µV**,
  which is 42 dB under the mixer's own noise floor. The choke has to be at the
  inlet: put it after the decoupling and the capacitors common the pair in
  front of it, and the same part is worth 0 dB and draws identically.

---

## The two things drawing these blocks taught, and they are one thing

**A declaration nothing is obliged to use cannot be wrong.** That is zone P's
lesson generalised, and it cost two more findings this pass.

`design.RAILS` had carried `"V3V3": 3.3` since the first pass with **no net of
that name anywhere on the board**, while `docs/supply-decision.md`'s own
correction index said flatly that this board has no 3.3 V rail. Both were
consumed — `NET_DC` is built from `RAILS` — and neither could fail, because a
rail with no net is invisible to every check that walks nets, and that is all
of them. `Design.check_rails_are_drawn()` is the instrument, and it exists
because the envelope ADC made V3V3 real.

`barrier_return()` returned `through_loop * z_loop` as the voltage at the audio
bond. That was not a wrong formula; it was a formula that was right only
because two quantities happened to be the same number, with nothing recording
that they were different quantities. Fitting the choke separated them, and the
unfixed version reported the choke making the design **0.4 dB worse** — the
current fell by 1300 and the impedance it was multiplied by rose by 1300. The
only warning was that the answer got worse when the part got better.

**And a rule whose stated test is narrower than its stated mechanism will be
quoted long after it stops being true.** `floorplan.CROSSING_RULE` said "every
crossing here is an *input* to the analogue domain" and gave the mechanism as
logic threshold against precision output. Those are not the same test: a logic
signal tolerates a ground offset in either direction. The ADC has to return
data, so `MISO` and `IRQ` leave the analogue domain, and they are exactly as
cheap as the six that enter. Nothing would have failed — `check_crossings()`
reads `CROSSINGS`, not the prose — so the wrong sentence would have gone on
being quoted.

**What to do about it, and it is the only general answer this project has
found:** when a deferred block is drawn, the first question is not "what does
it need" but "what does the repo already believe about it, in how many places,
and do those agree". Six places said something about the envelope ADC and four
of them disagreed. That list is at the head of the ADC section in `design.py`.

---

## The board is not regenerated, and that is the rule to read first

**`gen_pcb.py` places and pours. It does not route.** `route.py` -- a maze
router with rip-up and retry, a fan-out escape and a three-way via-exclusion
model -- closed this board at 0 unrouted and 0 DRC. The problem it existed for
went with the RP2040's QFN-56; what it cost is the thing to carry, and it was
never the copper. It was that the **board had to be a function of `design.py`**,
so no question about geometry could be asked of a layout until it had been
answered in Python first.

**`route.py` was deleted for one pass and is restored, and the restoration is
a narrower claim than the deletion was.** It runs **once**, as
`gen_pcb.py --seed-routing`, and what it produces is a starting point somebody
edits in KiCad -- not an output the build reproduces. Running it once does not
put the board back under `design.py`; re-running it on every build would, and
`gen_pcb_guard.refuse_to_discard_routing()` already stops that by accident. The
reason to have it is the person: a board handed over with 486 airwires and a
board handed over with a legal route to adjust are two different jobs, and only
the second one is editing.

**And none of the seed's copper is on the board any more.** KiCadRoutingTools,
through `krt.py`, re-routed every net and `--commit` promoted the result -- so
`route.py` is now how a board is started from nothing, and not how this board
was built. Measured on the tracked board: **5081 segments and 1135 vias**, of
which **290 are ground stitches** -- 151 `gen_pcb.py`'s, beside ground pads,
and 139 `returns.py`'s, beside signal vias -- and 845 are on signal nets; one
track width (0.2 mm), one via size (0.7/0.3), 13073 mm of track, and no signal
copper on `In1.Cu` or `In2.Cu`.

Two things about it that are worth not re-deriving. **The board is inside its
competence rather than at the edge of it**: it closed the QFN board at
0.09/0.09 on a 0.23 mm grid, and the fitted class is 0.20/0.20 on 0.45 mm with
the MCP3564's 0.65 mm TSSOP as the finest pitch left. And **nothing in the file
changed to come back** -- it imports nothing from this repo and takes its rules
as an argument, which is why deleting and restoring it cost one `git show`.

**The workflow consequence, and nobody may be allowed to discover it by
accident:**

> **The netlist is generated and authoritative. The board is not regenerated
> -- it is edited, and verified by reading it back.**

**That rule said "hand-laid and verified" for two passes and no millimetre of
this board was ever laid by hand.** Only the second half was ever load-bearing:
every question `verify.py` asks is asked *of* the board, by reading it back,
and not one of them cares who drew the copper. "Hand-laid" was the means at the
moment the sentence was written, promoted into the wording of the rule, and
then quoted after the means changed. `floorplan.CROSSING_RULE` is the same
shape one artefact along, and the general form is that **a rule written in
terms of how it is currently satisfied outlives the thing that satisfied it.**
That is why the restatement names the mechanism instead: the board is not a function of `design.py`, so
a question about geometry is asked of the artefact instead of being answered in
Python first.

* running `gen_pcb.py` writes a fresh board with the footprints placed, the
  planes poured, the ground pads stitched and **no signal copper at all** -- so
  running it over a hand-routed board destroys the routing, with no undo and no
  warning, because `pcbnew` has no notion of "the parts moved, keep the tracks";
* the way to move a netlist change onto a routed board is KiCad's own **Update
  PCB from Schematic**, against the generated `out/cv-module.kicad_sch`;
* `verify.py` is unchanged in what it asks -- DRC, the netlist against KiCad's
  own export, the ground split, the isolation region, both barriers -- because
  every one of those questions is asked *of the board*, by reading it back.
  None of them ever needed the board to have been written by us;
* **`verify.UNROUTED_ITEMS` is a progress marker and the check around it is a
  ratchet.** It is **0**: every net is closed, DRC reports nothing, and
  `check_board_is_the_design()` passes. Zero laid by a router is not the same
  claim as zero at the end of a person's pass -- neither router knows which
  nets are audio or where a return current wants to go, so moving copper is
  expected and moving copper can open a connection. The rule is unchanged:
  **down as copper is laid, up only with the nets named there.** Zero is the
  gate on gerbers, and `gen_plots.orderable()` reads it;
* **the stitching is not routing and stays.** A plane connection is a hole to
  the copper already underneath, and it is the one piece of geometry a person
  would otherwise reproduce 151 times by hand. **It needs two distances and
  not one**: two vias on different nets keep the copper rule, and two on the
  *same* net keep only the hole rule, because there is no clearance between
  them and there are still two drills. Using the copper figure for both is
  0.2 mm of margin invented on a rule that does not exist, and the bypass
  field is packed tightly enough that inventing it costs a stitch.

## There is a second router now, and its defaults would wreck this board

**`krt.py` drives [KiCadRoutingTools](https://github.com/drandyhaas/KiCadRoutingTools)
and `docs/routing-tool.md` is the record.** It does not change the rule above:
the netlist is still generated and authoritative, the board is still verified
by reading it back, and `krt.py` writes a *candidate* that `--commit`
promotes. What has to survive compaction is why the adapter exists at all.

**Pointed at this board with its own defaults it laid 4106 mm of signal track
through both ground planes -- and its DRC, its connectivity check and its own
improvement gate all reported success.** `In1.Cu` and `In2.Cu` are entirely
MAGND and MDGND; the zone filler flows around a track with clearance, so a
perforated reference plane is legal copper. **Every instrument agreed while
the thing the noise argument rests on was cut to pieces**, which is this
repo's oldest failure arriving from outside it. Nothing here would have said
so either: `verify.py` reads widths, vias, nets and regions, and until this
tool existed nothing could put a track on a plane layer, so nothing asked.
`krt.check_planes_intact()` is the instrument and it is new.

Four things it must be told, each measured, all four generated rather than
typed:

* **the layers** -- every poured layer excluded, derived from the board's own
  zones, because a layer becomes a plane by being poured on;
* **the fabrication floor** -- its default 4-layer floor is **0.0889 mm track
  and 0.10 mm clearance**, JLCPCB's tiers out of `fab_tiers.py`, and it will
  escalate down to them to rescue a net: `PIN6` came back as 34 segments of
  0.0889 mm copper on an audio input. `--fab-overrides` from `rules.py` pins
  it;
* **the primary's region** -- a `User.2` keep-out from the same three
  coordinates `check_isolation_gap()` measures, or it puts 24 pieces of copper
  in there;
* **`gen_project.py` afterwards** -- it rewrites the sibling `.kicad_pro` to
  the floors it used, including `min_hole_clearance` to **0.20**, the exact
  number `rules.hole_rules()` refused. `verify.py` runs DRC against that file,
  so the tool can make this repo's verification pass by moving its goalposts.
  Same failure as `SaveBoard()` flattening the project, same fix.

**And the gate belongs to the plan, not the pass.** A whole board is three
passes -- secondary with the keep-out, a rescue, then the primary nets -- and
the first one must be *allowed* to defer what it could not reach, so its
improvement gate is off and `krt.plan_gate()` refuses at the end instead.
Two facts behind that: `--max-ripup` is **not** the lever (a run at 12 returned
the run at the default, and the tool's own rejection message had said it
would -- a source cited and never read, again); and **a keep-out's cost is not
paid where it is drawn** -- blocking the supply corner broke `BUF2`, whose
parts are **113 mm away**. That is `ENV_ADC_CHANNEL`'s finding a second time,
so the rescue reads the failed net off the run rather than carrying a name.

Measured: 185/185 nets, one track width, one via size, no plane copper, the
primary's region clear, in **5 min 50 s** -- and 9.8 % less track than the seed
for **33 % more vias**.

**And the board was replaced anyway, which is worth stating plainly rather
than leaving the two sentences to be reconciled.** The full three-pass reroute
is what `--commit` promoted and what is on disk: `verify.py` exits 0 and
`test_verify.py` catches all 104 faults on copper the tool laid. What the via
row argues is not "revert it" but that **a whole-board reroute is not a free
improvement**: 844 router vias against the seed's 595 is 33 % more holes
through both reference planes, bought with 9.8 % less track. Whether that trade
is right on this board is a person's call and no check here can make it --
`constraints.parallel_runs()` is the only instrument that has since said
anything about the copper as laid, and it says the worst channel-to-channel
adjacency is **-114.4 dB against -54 dB**. So the recommendation for *future*
runs is unchanged and is about scope: re-route a region, not the board.

## Every via changes reference plane, and nothing had ever measured that

**`In1.Cu` and `In2.Cu` carry the same two nets in the same places** -- MAGND
north of 156.44, MDGND south of 158.44 -- so a track that changes layer changes
*reference plane*, and its return current has to transfer between them. The
only conductor that does that is a ground via. `constraints.return_loops()` is
the measurement: the loop is `rules.plane_separation()`, 1.03 mm of core, times
the distance to the nearest ground via. `returns.py` is what moves it and
`docs/return-vias.md` is the record.

**Why the figure was what it was, and it is not a fault in the function that
made it.** `gen_pcb.stitch_grounds()` places a via beside every ground *pad*,
because that is what a ground pad needs. Nothing here had ever tried to put a
stitch near a *signal* via, so nothing had ever asked how far the nearest one
was: **22.76 mm at worst, 7.39 median, 6 of 217 within 2 mm.** After
`returns.py`: **4.90, 1.50, 190 of 219**, and the total loop area from
**1990.6 mm2 to 367.8**.

Four things about it have to survive compaction.

* **Only half the question is derivable and the honest end is the
  sensitivity.** As a return *impedance* the number does not matter and the
  arithmetic says so: 22.76 mm of In1/In2 pair is tens of nH, sub-milliohm at
  20 kHz, tens of nV against a 144 uV floor. As a *pickup loop* for this
  board's own 580 kHz converter and 1.1 MHz switcher it is not derived,
  because the aggressor is a current loop inside a potted brick that no
  datasheet draws -- `board_coupling()` solves trace against trace because
  both conductors are known. So `return_sensitivity()` states the field at
  which the loops reach the mixer's own floor -- **19.9 nT before, 107.4 nT
  after** -- and claims nothing about what the field is. **Do not invent one.**
* **A ground stitch is not a perforation of the reference plane and a signal
  via is**, measured rather than argued: a signal via sits in a 0.55 mm void
  in *both* planes and a ground via sits in solid copper with none. 845 signal
  vias take 3.2 % of each plane; 290 ground vias take nothing. So the trade
  `docs/routing-tool.md` flags -- *"every extra via is a hole through both
  reference planes"* -- **is about signal vias only**, and 139 more stitches
  cost 139 drill hits and nothing else. That, plus the fact that stitching
  disturbs no copper already laid, is the whole reason the decision was to
  spend the copper rather than the derivation.
* **The reach is not a budget knob and it was priced before it was chosen.**
  Across 1.5 to 5.0 mm the via count moves 130 to 71 while refusals move 71 to
  0: the count is set by how many audio vias are in *distinct places*, and
  what the reach buys is legality room. So `returns.py` runs two passes --
  `TIGHT_MM` first because the loop *is* the distance, `WIDE_MM` after for the
  ones in packed copper -- rather than one at a compromise.
* **It only adds, so it is the thing to re-run after any re-route.**
  `krt.py --nets "SIN2"` re-laid that net's 33.5 mm detour at 7.6 and moved
  `AUDIO_OFF_MAGND_MM` from 144.1 to 118.1; it also put SIN2's vias somewhere
  new, and a second `returns.py` run cost two stitches. Like `krt.py` it is in
  neither pipeline and writes nothing without `--commit`; unlike `gen_pcb.py`
  it cannot destroy anything.

**Both ratchets are in `test_verify.py` now and neither had ever been shown to
fail.** `AUDIO_OFF_MAGND_MM` = 118.2 and `AUDIO_RETURN_AREA_MM2` = 367.8, and
they are planted in opposite ways on purpose: the return one in the
**artefact**, a copy of the board with its stitching stripped, and the plane
one in the **declaration**, by moving the ground split -- which is the move
`check_isolation_gap()`'s two cases make, and for the same reason.

**Both plants carry a dead-mutation guard, and the guard has to raise
something the caller does not catch.** The provocations at the end of
`test_verify.py` are run inside `except (SystemExit, AssertionError)`, so a
guard that announces "this mutation planted nothing" by raising `SystemExit`
is reported as *caught* -- the dead mutation, one level up, which is
`dead_mutations()`' own subject. It raises `RuntimeError`.

### The four faults drawing it found, and the last one is the rule

Each is a property inferred from something next to it where the artefact could
have been asked, which is this repo's oldest shape.

* **A regex found 151 of 994 vias.** Modelled on `constraints._raw_segments()`,
  which is exact for segments -- and KiCad writes `(tenting ...)` on a via from
  KiCadRoutingTools and nothing on a via from `gen_pcb.py`, so the pattern
  matched precisely the vias this repository wrote. The giveaway was that the
  audio count came back **zero**. `_vias()` goes through the parser.
* **76 of the 151 existing stitches were refused by their own pour.** KiCad
  flattens a polygon-with-holes into one ring with zero-width slits, so
  distance-to-boundary answers 0.038 mm in the middle of solid copper. A slit
  is a pair of coincident opposed edges and is removed exactly.
* **Every rotated footprint's pads were mirrored and their boxes transposed.**
  The board's y axis points down, so a footprint's angle turns its pads the
  *other* way; and a pad's own `at` angle is **absolute**, not added to the
  footprint's. Both wrong at once is 0.7 mm for 0.5125 on an 0805 -- the size
  of the clearances being checked. KiCad's DRC found it; a **track endpoint**
  confirmed it, being an absolute coordinate with no convention in it.
  `returns.check_pad_geometry()` is the instrument.
* **And 135 vias were written inside a footprint.** The insertion marker was
  `"\t(zone\n"`, which is a substring of `"\t\t(zone\n"`, so the first match
  in the file is one of the Pico's own keep-out zones 60,000 lines early. The
  board still parsed and KiCad would still have opened it. **The only thing
  that said so is that the file measures the board back after writing it and
  got the number it started with** -- and that comparison is a check that
  raises now. A writer that does not read its own artefact back cannot tell
  "wrote it" from "wrote it somewhere".

## Every geometric instrument was pointed at the audio nets

**And the class none of them covered is the one carrying the fastest edges.**
`constraints.parallel_runs()` compares audio against audio and audio against
the CV filter's passive node. `audio_off_its_own_plane()` and
`return_loops()` both filter to `AUDIO_FAMILIES`. `floorplan.check_crossings()`
reads the **netlist**, so it knows *which* thirteen signals cross the domain
boundary and nothing at all about where or how. So two things were true of the
board as laid and no number in this repository moved for either:

* **MCLK runs 0.428 mm from `SIN6` for 30.2 mm.** A continuously running
  10.4 MHz clock, beside the module's own output to the mixer's wiper, on
  `F.Cu`;
* **the ADC's bundle crosses the ground split 75.6 mm from `R902`**, which is
  the only conductor joining the two planes. `In1.Cu` and `In2.Cu` are split at
  the same y, so a crossing signal has no return path underneath it at all: the
  current runs along one pour's edge to the star, crosses, and runs back. The
  loop is about twice the figure.

`constraints.digital_audio_runs()` and `constraints.crossing_returns()` are the
instruments and both are **ratchets** — `DIGITAL_AUDIO_MM` = 244.2 and
`CROSSING_RETURN_MM` = 75.6, in the shape `AUDIO_OFF_MAGND_MM` is. Section 5e
of `docs/constraints.md` is the output.

Four things about them that must survive compaction.

* **The aggressor list is read, not written.** `crossing_signals()` takes
  `floorplan.CROSSINGS` and drops the rails and the two grounds, so a
  fourteenth crossing arrives in `constraints.py` by being declared in
  `floorplan.py`. That is `CROSSING_RULE`'s own correction applied to its
  consumer: the rule went stale because a second artefact restated it.
* **`PWM1`–`PWM6` are absent from the crossing list and that is the right
  answer, not a gap.** `U11` straddles the split by design — digital in on one
  row, precision analogue out on the other — so those six never cross in
  copper. It is the arrangement `shared()` argues for at length and is worth
  40 dB. The ADC's bundle did not get it.
* **`domain_bridges()` is derived from the netlist rather than named.**
  `verify.check_module_star()` names `R902`, and a named part cannot tell you
  that a second one would have helped. Read from `design.NETS`, a stitching
  capacitor across the split shows up by being drawn.
* **What lowers each figure is different, and neither is a re-route of the
  board.** `DIGITAL_AUDIO_MM` comes down with `krt.py --nets "MCLK"` — one net,
  seconds, every other net's copper untouched, and `returns.py` after it.
  `CROSSING_RETURN_MM` comes down with two or three 10 nF bridging MAGND to
  MDGND *on the split*, at x ≈ 65 and x ≈ 80. **That adds no DC path, so
  `R902` stays the module's only DC star and constraint §5.2 — which is about
  `R901` and the *mixer* — is untouched either way.** What it does need first
  is for `verify.check_module_star()` to learn the difference between a DC
  bridge and an AC one, because today it holds "exactly one MAGND/MDGND part"
  and would refuse the fix.

**And the coupling figure is comfortable, which is not the finding.** Priced
the way `board_coupling()` prices the others — `trace_mutual_capacitance()`
into `pin_impedance()` — the worst pair lands near −104 dB against a −54 dB
requirement. The finding is that **nothing computed it**, so replacing the seed
router changed the number and no instrument could say by how much. That is the
trace-coupling finding one section up, arriving one *net class* along instead
of one router along.

## The board's six fixings, and "underivable" was a claim about a dependency

**Read this before wondering why `gen_fab.py` exits 1.**

The only four unplated holes in the fabrication package belong to the
Raspberry Pi Pico's own footprint. A 106.9 × 233.1 mm board carrying a
21.8 × 9.1 × 11.2 mm converter brick, three relays and a soldered-down module
had **no fixings at all**. `verify.MOUNTING_HOLES` is the board's own count,
declared in the shape `UNROUTED_ITEMS` is; `verify.check_mounting_holes()`
holds it against the board, and `gen_plots.orderable()` gates on the
*shortfall* against what the design asks for. It read 0 for the life of the
design and reads **6** now.

**Nothing here could have said so.** `gen_fab.check_holes()` counts the drill
file against the board's own vias and pads and agrees exactly -- *a perfect
package of a board with nothing to bolt down*. `placement.check_placed()`
holds the parts the netlist declares, and a mounting hole is not in a netlist.
And the repo carries an argument *about* mounting holes: `MOUNTING_IS_ISOLATED`,
quoting the mixer's own *"four plated holes would be four more bridges between
AGND and PGND"*. **The reasoning arrived from upstream at the pinned commit and
the holes did not** -- an inherited argument with nothing to apply it to.

### The correction, and it is the reusable half

This section first said the pattern was **not derivable here**, because where
fixings go is a property of an enclosure this repository does not have, and
§6 forbids guessing. Every clause true, and the conclusion wrong, because it
assumed a dependency direction: *enclosure decides board*.

**It runs the other way.** The mixer targeted a 1590J because that was a
standard size and its own 122.8 × 50.4 mm board fits one. This board fits no
standard enclosure, which is exactly why the enclosure became bespoke -- and a
bespoke enclosure is drawn **after** the board, to whatever pattern the board
declares. So the fixings are an *input* to the enclosure, and §6 stops
forbidding and starts requiring: a value that can be derived should be.

**The general form, and it is a new shape for this collection.** Every previous
instance was a claim whose *test* had gone stale — a rule written in terms of
how it was currently satisfied, a constant that was a fact about its only
caller. This one is a claim of *impossibility* resting on an unstated
dependency direction. "X cannot be derived here" is never a fact about X on its
own; it is a fact about what X is assumed to depend on, and that assumption is
the thing to check first. Nothing can instrument it — a missing derivation
leaves no artefact, which is `DEFERRED`'s lesson at one more remove.

### What the derivation says, and two things came out of it

`placement.mounting_deflection()` models the board as a uniformly loaded beam
along its **long** axis -- the one that bends -- with the thickness taken from
`rules.FAB_FINISHED_MM` so it moves if the stackup does. It reports sag per g
and the acceleration that reaches a millimetre, and **claims nothing about what
acceleration a pedal on a stage floor sees**: that is `return_sensitivity()`'s
discipline reused.

| fixings | span | sag per g | 1 mm of sag at |
|---|---|---|---|
| 2 | 233.1 mm | 0.166 mm | 6.0 g |
| **4** | **233.1 mm** | **0.166 mm** | **6.0 g** |
| **6** | 116.5 mm | 0.010 mm | **96.5 g** |
| 8 | 77.7 mm | 0.002 mm | 488.6 g |

* **Four fixings are worth nothing over two.** Four means one at each corner,
  and the corners on the long axis are still the full 233 mm apart. The
  obvious pattern is the one that buys nothing.
* **Six, and the choice is robust rather than close.** 4 → 6 is **16×** for
  two holes because it halves a span entering to the fourth power; 6 → 8 is
  5.1× for two more. `FR4_MODULUS_PA` and `FR4_DENSITY_KG_M3` are borrowed and
  flagged as borrowed, in the style `rules.track_current()` uses for IPC-2221
  — and the L⁴ dependence means three times out in either moves the
  acceleration by three and does not reorder the table at all. That is this
  repo's own test for whether a borrowed number may be used.

`placement.mounting_holes()` then **walks** each fixing along its own edge from
the nominal corner or mid-edge until the keep-out clears every courtyard, so a
position is a result rather than a literal — `pack_east()` and `clear_south()`
one artefact along. `check_mounting_gap()` walks all 290 parts against it, the
way `check_courtyard_gap()` does, so a walk that gave up says which pair beat
it.

**Two of the six had to slide, and the second is a finding.**

* `H901` slid **16.5 mm** east: the north-west corner is taken by `J1`, the
  first of the six loom connectors, whose column runs down the west edge.
* `H906` slid **53.0 mm** west, and there is no south-east fixing at all.
  `U19` is `EDGE_PARTS`' one entry — at the east edge so its USB socket is
  reachable — **and it is the southernmost thing on the board as well**, which
  is the same two-sided fact that grew the primary's isolation region a tail.
  So `placement.mounting_reach()` puts the **SE corner 57.1 mm from its nearest
  fixing, and that corner carries the USB socket**: a plug pushed into it is a
  force at the free end of a cantilever. Grow the board, move the module, or
  accept it — all three are decisions, so the function reports the distance
  rather than taking one.

### They are fitted, and `mounts.py` is how

`verify.MOUNTING_HOLES` is **6**, the board carries them, and `gen_fab.py`
writes a package again — 1186 drill hits, of which **six are the 3.2 mm
unplated tool**.

**`mounts.py` is `returns.py`'s sibling and it needs `pcbnew` where
`returns.py` needed only text.** A stitch is a via in copper that already
exists. A fixing is a *hole through both reference planes*: `In1.Cu` is MAGND
and `In2.Cu` is MDGND, so an M3 screw through an unvoided hole bridges the two
domains at every fixing — **six ground stars instead of one**, which is
constraint §5.2 defeated by a bag of hardware. So each hole gets a rule area on
all four copper layers and the pours are refilled around it, and a zone fill is
not something a text edit can do. Measured on the board: every fixing sits in a
void with **1.85 to 3.28 mm** between the hole edge and the nearest plane
copper.

It adds and replaces and disturbs nothing — `6256 tracks and vias, unchanged`
is asserted rather than hoped for, and the fixings are measured back off the
saved board before it reports success, which is `returns.py`'s own rule after
135 vias once landed inside a footprint.

**The router had to be told first, and that is the finding.** Nothing ever
reserved the margin, so the router used it: `PIN5` ran **183 mm** through two of
the six keep-outs and was the only net that did. `krt.keepout_rects()` has seven
entries now instead of one — the primary's region and the six fixings, all
derived from `placement` rather than typed — and `krt.py --nets "PIN5"` re-laid
it in one pass, gate accept, planes intact. `returns.py` afterwards cost four
stitches and moved `AUDIO_RETURN_AREA_MM2` from 367.8 to **370.7**, which is the
ratchet's sanctioned case: *up only with the vias named*, and the named net is
the one that moved.

**Three things bit on the way and all three are recorded in the file.**

* **`MOUNTING_KEEPOUT_MM` is KiCad's courtyard, not an M3 washer's.** The
  derivation wanted 6.5 mm; `MountingHole_3.2mm_M3` draws its `F.CrtYd` circle
  at `(end 3.45 0)` — **6.9 mm** — and DRC grades against the courtyard, so the
  land pattern's number binds and ours does not. Two overlaps on positions this
  repo had just certified as clear. That is `check_courtyards()`'s finding
  arriving at a part this project *placed* rather than one it routed.
* **And then 46 µm of it was the stroke width.** `H906` cleared `U19` by
  0.046 mm on the corrected arithmetic and DRC still called them overlapping,
  because a courtyard outline is a *stroked* polygon and both strokes count.
  `mounting_reach_mm()` adds `COURTYARD_TOLERANCE_MM`, which is the same 0.06
  `check_courtyards()` already uses.
* **`check_ground_split_on_the_board()` had never seen a zone with no net.**
  A rule area has none, so `str(net[1])` raised `TypeError` the first time a
  board-level keep-out existed. It did not fail quietly, which is the lucky
  version; it is skipped explicitly now, because that check's subject is where
  *poured copper* is.

**Two `pcbnew` facts that cost an hour and are not written down anywhere
else.** `ZONE.SetOutline()` takes ownership through SWIG, so an outline built
as a local is freed when the function returns and the filler **segfaults**
several hundred lines later — build into `zone.Outline()` instead. And after
`board.Remove()`, SWIG's type registry stops resolving *for the rest of the
process*: `GetArea()` returns raw `SwigPyObject`s and even module-level
`pcbnew.FootprintLoad` comes back as an object with no `FootprintLoad` on it.
Reloading the board does not clear it. So `mounts.py --commit` runs its child
twice — remove and save in one interpreter, add and fill in the next.

**And a fixing is not one of the design's parts.**
`check_board_is_the_design()` reported six parts "on the board and not in
design.py" until it learned that: a mounting hole has no pins, no net, no BOM
line and no symbol, and a netlist has nothing to say about one. It is excluded
by the same all-NPTH test `check_mounting_holes()` uses, so the two agree by
construction rather than by both being maintained.

**What is still open is the south-east corner**, and it is a decision rather
than a defect: `mounting_reach()` puts it **57 mm** from `H906`, and it carries
the USB socket. Grow the board, move the module, or accept it.

## The board said nothing, and a layer that is not blank is not a layer that says anything

**It had no board-level silkscreen at all.** Four `Edge.Cuts` lines, **zero**
`gr_text` of any kind, and 29 of 296 footprint references on `F.Silkscreen` --
which did not include `J1`-`J6`, `J8`, `J17` or `J19`. Every connector on the
west edge was anonymous, so the only way to know which pin of `J1` went back to
the mixer was to read `design.py`. No title, no attribution, no revision.

**Why nothing here noticed, and it is a new corner of the same shape.** A
silkscreen is not in a netlist, so `check_geometry()` cannot miss it. DRC sees
it only when it collides with something, and there was nothing to collide with.
And `gen_fab.package_layers()` **exports each candidate layer and drops the ones
that draw nothing** — which is the one instrument that nearly caught it, and did
not, because 29 footprint references were enough to keep `F.SilkS` non-empty. A
layer that is not blank is not a layer that says anything, and `package_layers()`
can only ask the first question.

### The text is generated from the netlist

`design.SILK_NAME` gives each connector the name a person uses for it — `CH1`,
`DC IN`, `EXP PEDAL` — and `design.SILK_ROLE` says what a *net* means where it
lands on a connector pin. `silk_legend()` then walks that connector's pins **in
order out of the netlist** and pairs them up, so the legend's pin order is the
netlist's pin order by construction and the two cannot drift. `SILK_ROLE` is
keyed on the per-channel *family* where six nets say the same thing, for
`AUDIO_FAMILIES`' reason: `PIN3` is not a different kind of thing from `PIN1`.

That is `gen_plots.orderable()` reading `DEFERRED` rather than restating it,
applied to prose. **A silkscreen is prose printed on copper-clad, and prose
that restates a fact is prose that will one day contradict it.**

`design.check_silk()` is the data half — every connector in the netlist has a
name, and every one of its pins has words — and it raises rather than printing
a blank line, because *a legend with a gap in it is worse than no legend: the
reader trusts the ones either side of it.*

`verify.check_silkscreen()` is the artefact half, and it is the one that could
not be asked before: it reads the board and holds it to the names the design
declares. Both are planted in `test_verify.py`, which is at **110**.

### `silk.py`, and the positions are results

Same idiom as `mounts.py` and `returns.py`: reads the board, adds only,
`--commit` writes, measures back, and asserts the track count unchanged. It
**owns every board-level text on `F.SilkS`**, which is what makes it
idempotent — a commit clears them and redraws.

Each label is tried in a preference order and the first placement that clears
every courtyard, every fixing keep-out **and every label already placed** is the
one taken. A placer that checked only the parts would let two legends overlap
and report success. The west margin is tried first and **rotated**, because a
90° label is bounded by the row pitch in the direction that is tight and by
open margin in the direction that is not — which is what lets a name sit in
4 mm of width.

Three coordinates in the whole file are seeds rather than results — the title
band and the legend block — and both are checked by the same `fits()` rather
than trusted. The title band is 91 × 11.25 mm of clear board across the middle
of the design; the legend sits in 35.5 × 30 mm in the south-west.

**It caught its own overflow on the first run**: `EXP PEDAL 1 tip/wiper 2
ring/supply 3 0V` came out 41.2 mm wide in a 35.5 mm block and the placer
refused it, which is why the roles are written tight.

**Measured after committing: 25 texts, closest approach to any pad 1.00 mm,
DRC 0.**

### The capacitors were deliberate, and the reason had expired

**250 of 296 references sat on `F.Fab`** because `gen_pcb.py` demotes any part
the design connects two terminals to, with the reason written beside it: *"a
0805's designator is wider than the part: KiCad's DRC reported thirteen
silkscreen collisions on the first clean placement and every one was a
designator."* Every word of that was true — **of a designator placed at the
footprint's own fixed offset**, which is where KiCad puts it and takes no view
on what is there.

Measured against a *probe* instead, **all 250 fit**. `silk.py` places 245 at
1.0 mm and 25 more shrunk to `rules.SILK_TEXT_MIN_MM`; six sit in copper too
tight to take one at any legal size and are left on `F.Fab` and named —
`R556`, `R656`, `R457`, `R814`, `C724`, `C221`. `verify.SILK_UNLABELLED` is the
ratchet, in `UNROUTED_ITEMS`' shape: down as room is found, up only with the
parts named. **274 designators are on the silkscreen and DRC reports 0.**

That is *"hand-laid and verified"* and `floorplan.CROSSING_RULE` a fourth time:
**a rule written in terms of how it was being satisfied, outliving the
method.** What silk is for is the board somebody is holding with an iron, and
on a hand-built prototype an unlabelled 0805 is the thing that costs the hour.

### U9 and U10's designators were printed under the chips

**The two SSI2164s — the parts this board exists to drive — had their
references inside their own footprints**, invisible the moment the packages go
on. `placement.REFERENCE_MOVES` put them there: KiCad places a SOIC's reference
above the body, a 90° rotation turns that to the west onto a neighbour, and the
fix was an 8 mm nudge east that landed the text in the middle of a package
10.4 mm long.

The comment beside that dict is exactly right and exactly one part short — *"a
silkscreen offset is a number about two parts' positions, and it goes stale
when either of them moves."* **Two** parts: the label's owner and the neighbour
it was moved off. It never asked about the third thing in the picture, which is
the part the label is *naming*. DRC does not object, because silk on your own
package body collides with nothing.

`verify.silk_reference_faults()` is the instrument and it holds both halves —
no designator inside the part it names, and the unlabelled count against its
declaration.

### What the placer had to learn, in the order DRC taught it

Each step is the previous answer being not quite the thing that gets drawn,
which is this repository's oldest shape arriving on a new layer.

* **28 overlaps.** The placer knew about courtyards and about labels it had
  placed itself — two of the three things on `F.SilkS`. The third is the silk
  footprints bring with them: part outlines, polarity marks, pin-1 dots, and
  the references already there. `claim_existing_silk()` starts from all of it.
* **8 overlaps.** `text_extent()` multiplies a character count by an average
  advance, and a stroke font's advance is per glyph: `R827` is not `C704` wide.
  `Placer.place_item()` *tries* a candidate — moves the item, asks KiCad for
  its bounding box, and tests **that**. The estimate is gone from the answer
  rather than tightened.
* **Every other legend line refused.** The line step was derived from the text
  size alone, so at 0.8 mm consecutive lines sat 1.36 mm apart with 1.7 mm
  boxes and each one was refused by the line above it — which the placer had
  just taken.
* **4 text-height violations.** `rules.py` did not own the silkscreen
  minimum, so DRC was enforcing KiCad's 0.8 mm default on a number nobody here
  had chosen — the hole rules a third time. `rules.SILK_TEXT_MIN_MM` and
  `SILK_TEXT_THICKNESS_MM` own it now, `gen_project.py` writes both, and DRC
  does exactly what it did before.
* **And the check itself invented a fault.** The first version of
  `silk_reference_faults()` reported `U19`'s designator as printed inside the
  Pico when it sits 0.6 mm clear, because the local-to-board rotation had the
  wrong sign. **`returns._rotate()` had already written that down** — the
  board's y axis points down, so a footprint's angle turns its children the
  other way. A check that invents a fault is worse than no check, because
  somebody moves a part to satisfy it.

### Two things about it that are decisions rather than omissions

* **`REV A` is a declaration and not a discovery.** Nothing in this repository
  records a fabricated revision of *this* board, because there has never been
  one — `contract/PINNED.md` pins the mixer's. A board that goes to a
  fabricator without a revision on it is a board nobody can refer to
  afterwards, and the first one is A.
* **The connectors' references stay on `F.Fab`** while every other part's
  moved to silk. For a connector the designator is the wrong word: `J1`
  identifies a BOM line and a CPL row, both of which are files, while `CH1` is
  what somebody holding a loom needs, and there is room in 4 mm of west margin
  for one of them.

## The fabrication package exists, and what it will not decide is the point

**`gen_fab.py` writes `fab/`, and the gate it reads is the one that was
already there.** `gen_plots.orderable()` is imported rather than restated, and
KiCad's own DRC is run *at the moment of writing* rather than read off whatever
report happened to be on disk -- the sibling's rule, whose `build.sh` deletes
the zip when DRC is not clean rather than leaving the last good one beside a
broken board.

Four things about it that must survive compaction:

* **The layer set is a measurement, not a list.** `package_layers()` exports
  the candidate set, reads each file back, and drops any that draws nothing.
  On this board that is `B.Paste` and `B.SilkS`, because all 290 parts are on
  the top. The sibling writes its layer list down and asserts separately that
  its back silk is empty -- two artefacts that have to agree, and its own
  record is that they did not: an empty `B.SilkS` shipped in two zips for the
  life of the design. A derivation cannot go stale that way, and if somebody
  puts a legend on the back tomorrow the layer comes back by itself.
* **`F.Fab` is never in the package and that is the one mistake nothing
  downstream would catch.** It carries a second closed board outline, so CAM
  picking it up instead of `Edge.Cuts` returns the wrong board shape. `NEVER`
  is the denial list, each entry with its reason.
* **`check_holes()` is the check that is not a byte comparison**, and it is
  the one that could catch a wrong export *option*. The drill file's hits are
  counted against the board's own vias, plated and unplated pads -- 1135 + 34
  + 4 = 1173, measured both ways -- and its unplated hits against the board's
  unplated pads, because a mounting hole plated by mistake is a short to
  whatever pours around it. `--verify` proves the package is of *this* board;
  only this proves it is *right about* it. `test_verify.py` plants both, plus
  a stale package, and catches all three.
* **The package is tracked loose and the zip is ignored**, which inverts the
  sibling deliberately. There the zip is tracked because `zip` updates an
  archive in place -- a layer that stops being generated never leaves it.
  Here the directory is rebuilt and the archive rewritten by `zipfile`, so
  that failure is unavailable; what is left is that gerbers are text that
  diffs and a zip's bytes carry the zlib that built it. Two exports of one
  board are byte-identical once `FAB_EPOCH` has replaced four timestamps --
  `PDF_EPOCH`'s argument, one artefact along, measured the same way.

**And it found a third thickness, which is closed now.** `(general
(thickness 1.6))` on the board was KiCad's default; `rules.FAB_FINISHED_MM` is
1.61, what PCBWay publishes for this construction; `rules.FAB_STACKUP` sums to
1.541, the same construction without solder mask. The job file hands a CAM
operator that field as `BoardThickness`, and nothing owned it until
`gen_fab.py` read it -- the stackup pass fixed the layer table and left the
summary field behind. **`rules.apply_thickness()` writes 1.61 and
`verify.check_stackup()` holds it.**

Three things about that to carry. **1.541 is deliberately not the answer** --
it is the declared layers without solder mask and this repository has no mask
thickness, so making the two agree would mean inventing one. **The check is
not ceremony**: KiCad's Board Setup recomputes that field from the stackup, so
opening the dialogue puts 1.541 back. And **the reason it was left alone for a
pass was a rule about who may edit the board** -- *"the board is not this
file's to edit"* -- which was true while `gen_pcb.py` was the only writer and
stopped being true when `returns.py` started adding copper by text. That is
`floorplan.CROSSING_RULE` and "hand-laid and verified" a third time: **a rule
written in terms of how it is currently satisfied outlives the thing that
satisfied it.**

**What it refuses to do is finish the order.** Surface finish, mask and silk
colour, electrical test, panelisation, IPC class, quantity: none is derivable
from anything here, so `ORDER.md` lists them as open. A package that looks
complete with a guess in it is the failure `ASSUMPTIONS.md` exists to prevent,
arriving at the one artefact that leaves the repository.

## The placement is packed, not nudged, and the two functions are the rule

**`placement.check_courtyard_gap()` is at zero.** It was 41 two passes ago and
23 at the start of this one, and the attempts in between went 41 → 23 → 19 →
12-with-three-overlaps before reverting. Every step was a number going down and
no step could say *why* a part was where it ended up. What replaced them:

* **`pack_east(chain, start_x)`** lays a row west to east, each part one
  `required_gap()` from the last. It does not choose the order -- that is the
  design, and the inlet is at the west edge because it is an inlet.
* **`clear_south(north, south, dx)`** gives each of the seven bands south of
  the relays a y that is the band above it plus the clearance of **one named
  pair**. That pair is a claim and not an assertion: `check_courtyard_gap()`
  walks all 290 parts, so a band derived from the wrong neighbour fails and
  says which pair it should have been. It earned that the same day -- fitting
  `F801` moved `C810` out from under an 0805 and under a 1210, and the check
  said "C810 and C840 are 0.00 mm apart".

**The board may grow and that is what makes this cheap.** The whole pass cost
3.6 mm of length and 1.7 mm of width, on a board already 3.8x the enclosure it
does not fit. Millimetres in y are the cheapest thing this design has and
assembly comfort is what they buy. **The cost written down at `SUPPLY_Y` --
"moving them costs 11 nets and 114 connections of re-routing" -- is dated, and
it has now been dated twice in opposite directions.** It was true of the routed
board on disk when it was written; it became expensive again the moment the
copper was something a person would have to re-lay; and it is cheap again now,
because `krt.py --nets` re-routes a named scope inside the design's own
constraints in seconds and leaves every other net's copper alone. **A cost that
depends on the state of an artefact somewhere else has to be re-read, not
quoted** -- and this one also depends on which tools exist, which is a second
way for a number in prose to go stale without anything touching it.

**And the one that will happen again: a fix that asks what the two parts in the
violation need and never asks what the rest of the row already has.** `R901`
and `C701` were 0.07 mm apart; the fix moved the 24-capacitor bypass field
0.6 mm east, with the reason written down as *"the field is 24 parts with
nothing east of them for 1.5 mm"*. There is something east of them -- the ADC's
input column -- and every one of those capacitors needs a ground stitch beside
its pad. The last one missed `R656` by **0.03 mm** and the build stopped. The
star moved instead. What is different from the previous instances is that the
wrong reason was written as a checkable claim, and a generator checked it three
edits later.

**And two invariants moved in worth without moving in content.** `PDF_EPOCH`
exists so a tracked plot is a function of the board -- and the board itself
used to be the churning artefact, 102,909 lines rewritten on every run because
KiCad mints fresh UUIDs. It is not regenerated any more, so a diff on it is a
real signal for the first time, and the deterministic-UUID pass is no longer
needed for that. `gen_plots.check_plots()` is worth *more* for the same reason
-- the plots are now the only generated artefact downstream of the board, so it
is the only thing that can say the two agree -- and it is still not a stage in
the run order, because on a hand-routed board "the board has legitimately
changed" is what every hour of work does.

**What is kept from the router pass is everything below**, and it is kept
because the arithmetic in it is still true and because six findings came out of
it. None of it describes what the build does today.

## The router reached a pad only if a track could *legally* land inside it

**Three boxes, three answers, and the check that existed to predict this
measured the wrong one.** A pad has a bounding box; `route.block_pad_copper()`
insets that by half a track so a track drawn on a cell stays inside the pad's
own copper; and DRC asks a third question, whether the track's edge clears the
*next pin*. For a TSSOP-20 pad, 0.40 mm across on a 0.65 mm pitch, those are:

| box | a cell within | what used it |
|---|---|---|
| the pad | 0.200 mm of the centre line | `check_fine_pitch_access()`, since removed |
| inset by half a track | 0.075 mm | `route.access()` |
| clearance to the next pin | **0.125 mm** | DRC, and `rules.track_offset_limit()` |

So the check passed on four pads the router then refused, and
`verify.UNROUTED_ITEMS` was **8 while the instrument written to explain it
reported nothing**. It was not wrong about the box it measured. It measured the
pad, and what gets drawn is a track — this repo's oldest failure, inside the
function written to catch this repo's oldest failure.

`rules.pad_reach()` is still the arithmetic for *whether a cell lands in the
pad*: a pad holds one at every phase only above `grid + clearance` of pitch,
0.70 mm here, and a TSSOP's 0.65 misses by 0.05. What that costs is now zero,
because the escape does not need a cell in the pad.

### The fan-out, and it is what closed the number

**`route.Grid.escape()` lays each unreachable pin's escape as fixed copper on
the pad's own centre line, before `route_all()` runs.** Four things about it
must survive compaction:

* **Along the pad's own axis first, across to the grid second.** Inside the pin
  row the escape is the safest track on the board, because it is exactly where
  the pad already is — offset zero, 0.325 mm to the neighbour. It turns for the
  grid only past `rules.escape_reach()`, which is the pad's own clearance halo
  plus half a track, so the snapped grid line cannot land on the halo's own
  boundary.
* **Which pads get one is `route.access()`'s own answer, not a prediction.** The
  first attempt computed the criterion a second time in `gen_pcb.py` and the
  second opinion was wrong: it measured from the pad's *centre line*, which is
  the only candidate a TSSOP pin has and one of a hundred an NCP1117's DPAK tab
  has, so it declared the 5 V regulator unreachable and refused its escape.
  `gen_pcb.escape_plan()` now answers only the question that file is the only
  one able to answer — **which way is out** — and the router decides need.
* **The escape is a track and its halo is one half-track wider than a pad's.**
  `block_pad_ring()` is handed a pad's copper *rectangle* and grows it by
  `clearance + track/2`. `block_escape_ring()` is handed a centre *line*, so the
  reach is `track + clearance`. Using the pad's number would leave every
  neighbouring cell half a track too close — the same claim-about-a-pad,
  applied-to-a-track fault, arriving from the other side.
* **Its clearance is measured, not asked of the grid.** `escape_clearances()` is
  geometric, against the real pad boxes. Asking the grid would be wrong in both
  directions at once: it would refuse the escape, because the cells beside a
  fine-pitch pin are blocked to routing and rightly so, and it would pass copper
  the grid does not own.

**One notion of where a pad is.** `pad_boxes()` keys on the bounding box centre
and `escape_plan()` first keyed on `GetPosition()`. They agree to within a
nanometre and not to within a float comparison: ENVA1 and MISO matched, ENVA2
and MOSI missed, and the router reported "no escape axis" for a pad 1.475 by
0.400 mm.

**The result: `UNROUTED_ITEMS` is 0, DRC is 0, four escapes at U17.** 1547 track
runs and 561 vias against 1489 and 516 — the escapes did not only close their
own pads, they freed enough room for the rest of the fan to take shorter paths.

**`design.ENV_ADC_CHANNEL` is a record of a measurement now, not a constraint.**
It existed to spend the choice of *which* two pin rows lose on the ADC's grounded
channels. With the constraint gone, CH0–CH5 in order was drawn and routed — and
**it cost a net 30 mm away.** Moving the channels down one pin makes a fifth pad
need an escape, the escape's halo takes cells out of the one corridor the six
`ENVA{n}` runs already converge into, and the router dropped **CVN3** in the CV
band with DRC still at zero. The map is kept, and the finding is the general one:
**an escape's copper is not free and it is not spent where it is laid.** Four
escapes closed four nets and *shortened* the whole fan; the fifth closed nothing
and broke something in another zone. The router is the only instrument that
knows.

### The two claims that had to be fixed first, and they were about a pad

Both were found by **DRC**, on the first board this project built with a 0.65 mm
pitch on it, and both had been true for as long as every package was a SOIC.
Neither was catchable from inside the router: `check_no_shorts()` looks for
shorts and both are clearances, and in both cases the offending copper is the
piece the grid does not own.

* **`block_pad_copper`** exempts a pad's own cells from clearance — *"a segment
  inside a pad's own copper cannot be too close to anything, because the pad
  already is not."* True of the pad. What the router draws there is a **0.25 mm
  track**, and a TSSOP pad is 0.40 mm across, so a cell more than **0.075 mm**
  off its centre line puts copper past the pad's edge and at the neighbour. The
  box is inset by half a track.
* **`route.access()`**'s docstring said a pad with no free interior cell "cannot
  be reached on this grid, and `route_all()` reports the net". Its last line
  returned the nearest cell *outside* the pad — the only case that line ever ran
  in. The fallback stays, because Q801 needs it, and `_stub_is_clear()` tests
  that stub the way every other piece of track is tested.

**Fixing them made the number go up and the board better**, which is the rule
about that number: 8 unmade and named beats 6 drawn 0.15 mm from a neighbouring
pin. The fan-out then took it to 0.

### The ladder, and the rung the RP2040 falls off

`rules.fan_out_class()` collects the three questions into the one a package is
chosen against, and the answer has three rungs:

| | |
|---|---|
| `limit >= grid/2` | a track starts inside the pad at every phase — half a grid pitch is the furthest the nearest line can be. **SOIC, 1.27 mm** |
| `2(edge − clearance) >= track`, `pin_pitch >= grid`, **and the jog clears** | it cannot, but an escape on the pad's own centre line reaches it. **TSSOP, 0.65 mm** |
| any of those failing | nothing this router draws gets there. **QFN-56, 0.40 mm** |

with `edge = pin_pitch − pad_width/2` and `limit` from `track_offset_limit()`.

**The middle rung has three conditions and the third was missing** — which made
a wrong claim about the RP2040 that stood for one pass: *"it clears at the 2 oz
minimum, 0.15/0.15"*. Two conditions were enumerated, both were true, and the
conclusion was stated as though the enumeration were complete. The third is that
the **jog** is ordinary track pointing at a neighbour `pin_pitch` away, so
`pin_pitch − grid/2 >= clearance + track`. Nothing would have caught it: no board
here has a 0.40 mm part on it, so there was nothing for a check to fail against.

**The fitted class fails the jog condition for the TSSOP and the four escapes are
legal anyway, and that is arithmetic rather than luck.** Adjacent pins' offsets
differ by `pin_pitch mod grid` = 0.15 mm, and both pins escape only when both
offsets exceed 0.125 — impossible with the *same* sign, because 0.125 + 0.15
exceeds the 0.25 an offset can reach. So two adjacent escapes here always point
**away** from each other. `fan_out_class()["same_direction"]` is that arithmetic,
and where it is true the jog condition has to be met outright. At 0.40 mm on a
0.35 mm grid it is true, so QFN escapes can point into each other and
`escape_clearances()` refuses the second.

**The second condition of the middle rung is the counting one and it is the one
nobody would think of.** An escape ends on a grid cell and may move at most half
a pitch across the row to get there, so pins map onto grid lines *in order* — and
two pins closer together than one grid pitch have to share a line, which two
nets cannot. Fourteen pins a side over 5.2 mm want fourteen lines and a 0.5 mm
grid offers eleven. A *spreading* fan breaks that limit honestly and is a
different mechanism from the single jog.

**Q801 is still why the check is two conditions and not one.** A SOT-523's pads
hold no grid cell in y either and that part has routed correctly on every build
this board has had, because its nearest neighbour across that axis is 1.0 mm
away: its limit is 0.475 mm and no phase can reach it. A check that fires on a
working board is the fastest way to get a check switched off, and a fan-out that
fires on one is 1.6 mm of pointless copper on every SOT-23.

---

## The controller is a Raspberry Pi Pico, and it took the supply with it

**`design.CONTROLLER` is a module now** -- SC0915, castellated, on
`Module:RaspberryPi_Pico_SMD_HandSolder`. `docs/controller.md` is the record;
what has to survive compaction is this.

**It deletes about 25 parts and one whole class of problem.** U20, Y801 with
R824/C832/C833, J14 with R820-R823, twelve supply capacitors and the BOOT and
SWD headers. 314 parts became 289 and 201 nets became 184. 0.40 mm of pin pitch
became 2.54, which is why `route.py` stopped being load-bearing -- it is
restored and runs once as a seed, and the QFN is the reason it no longer
has to close a board nobody could close by hand.

**`docs/fabrication-class.md` was re-opened, re-decided at 0.15/0.15 on 2 oz,
and put back to 0.09/0.09 on 1 oz -- and the round trip is the finding.** The
derivation is right about the parts: `coarsest_class_for()` against the finest
pitch left, the MCP3564's TSSOP at 0.65 mm, needs 0.205 or finer, which the
2 oz minimum clears and the old 0.25/0.20 misses. **It omits the copper.**
55,854 segments are already laid at 0.09/0.09 on a 0.23 mm grid, and two
adjacent tracks there are 0.23 mm apart -- legal at 0.09 mm wide, illegal at
0.15, and not widenable. **The class is a free choice only for a board routed
from nothing; while there is copper on it, the class is a property of the
copper.** Same omission as `RAIL_FILTER_ESR`: not a wrong number, a number
computed without the term that dominates.

**Back-driving the module's 3V3 pin is refused and it is not refused on
arithmetic.** `pico_backdrive()` is the record. The cheap topology -- U22
unchanged, straight to pin 36, `3V3_EN` held low -- costs 32.1 mA of +Vout
where the drawn one costs 90, so the numbers argue for it. The RT6150's
datasheet states the disconnect (*"the load is disconnected from the input"*),
states its direction (*"the output voltage can **drop below** the input voltage
during shutdown"*) and bounds the leakage at 10 uA -- and **every one of those
is stated with the input present**, while this topology needs the input absent
and the output held above it. The Pico datasheet's own §4.5 lists three ways to
power the module and pin 36 is in none of them. Same reading rule that refused
the TPS560430X3F's inferred FB connection, on the pin that *is* the rail.

**So the module is fed on VSYS, and that put two converters in series.** The
threshold did not move -- `mcu_supply()` still says 67.8 % -- but it became a
threshold on a **product** of two efficiencies, whose pessimistic ends multiply
to 0.660. **The corner failed by 4.6 mA and `verify.check_supply()` said so**:
254.6 mA asked of a 250 mA output.

**What closed it is the lever the repo had already named.**
`MEASURED["mcu_dcdc_efficiency"].when_wrong` has said since the QFN pass that
the thing to change is the 92.7 mA of relay coil V5 makes *linearly* from
twelve volts. U22 moved from 3.3 V to 5 V -- Table 1's own 1.1 MHz/5 V row, and
§9.2's worked example is that exact operating point -- and carries the coils as
well as the module. +Vout is **212.9 mA of 250**. What is left on the linear V5
is the MAX6126 and the ADC's LDO: 2.2 mA of load behind 10 mA of quiescent
current, kept deliberately, because the reference the whole CV chain is
measured against does not go behind a 1.1 MHz switcher to save 4 % of +Vout.

**Three things about the block that must survive compaction:**

* **`D806` is not there for its drop.** With no ORing diode and a USB cable in
  an *unpowered* board, VBUS reaches VSYS through the module's own D1 and from
  there it is on U22's output, where the buck's high-side body diode carries it
  to VA_RAW -- a USB host on this board's twelve-volt rail, four parts deep,
  every one of them doing what it is supposed to;
* **GPIO23 high is a firmware constant with a hardware reason.** It is the
  RT6150's power-save pin and the module's default is PFM, whose rate falls
  with load. No suffix to buy this time. `pico_smps_beat()`: 800-1200 kHz
  forced, which overlaps U22's own 935-1265 MHz band so those two beat through
  zero -- and `supply_beat()` has already shown that is not a thing to design a
  margin into;
* **the F suffix is still load-bearing and the argument changed underneath it.**
  At 5 V into 15 uH the boundary is 88 mA and the rail carries 160, so "a PFM
  part would be discontinuous *always*" has gone. What replaces it is
  **bypass**: the coils are 93 mA of that 160 and they drop out exactly when
  the fail-safe takes the module out of circuit, which is the state the box
  powers up in. With the processor idle too the rail is 16 mA, where a PFM part
  would run at **194 kHz, under the rule**.

**And one row of `controller_fit()` is exactly 1.00x.** MCLK needs a
`CLOCK GPOUT` pin; four exist on the chip and **three are internal to the
module**, so GPIO21 is the only pin on this board that can carry it. Met, by a
pin the datasheet names, and what it costs is the option. `exactly_met` is
returned beside `tightest` because the "tightest" figure skips rows where
`has == needs` -- fair while USB was the only such row, and not now.

## The controller: drawn as a bare RP2040, and `DEFERRED` is empty

**Both gates closed and the block is on the board.** The package gate closed by
moving the fabrication class — `docs/fabrication-class.md`, and the RP2040 is
what asked the question. The supply gate closed by choosing a part.
`docs/controller.md` is the record; what follows is what has to survive
compaction.

**The part that closed gate 2 is a TPS560430XF and the F is the whole of it.**
1.1 MHz, forced PWM, 12 V in, 3.3 V out, SOT-23-6. `mcu_dcdc_light_load()`
computes the continuous/discontinuous boundary for Table 1's own 12 µH — **91 mA
against this board's maximum 87 mA draw** — so a PFM part would never be in
continuous conduction and its frequency would be proportional to load: 246 kHz
at this board's idle, *under* the ≥ 300 kHz rule, and in the audio band below
1.6 mA. That is `supply_beat()`'s objection to the RCC-topology TMR 6 arriving
at a second part from the other end, and it is the reason a few pence of
difference between two suffixes is load-bearing.

**Its input is VA_RAW and not VA+, one node ahead of `R804`.** A buck draws a
pulse train from its supply; behind the rail filter that train's own IR drop is
on the rail six audio channels share, and in front of it the same pole that
attenuates the converter's 75 mV<sub>pp</sub> attenuates this too, 6 dB harder
at twice the frequency. 39 mA rms of input ripple becomes **3.86 µV on VA+**, 97 dB down as AM — it was 2.4 µV and 102 dB at the capacitors' *nominal* value, and `effective_farads()` is why it moved. `verify.check_mcu_supply()` holds the wire, because VIN on
VA+ works, routes, passes DRC and hums.

**The +Vout budget is the tightest number on this board and it is honest.**
87.3 mA of 3.3 V load counted off the netlist — the RP2040's 52.1, the flash's
25, the MIDI loop, the pedal, the opto — costs **32.1 mA of the 35.4 mA that
was left**, at the pessimistic end of `MEASURED["mcu_dcdc_efficiency"]`. It
fits at any efficiency above **68 %**, which is a bound that cannot be wrong
(conservation of energy over a headroom) and is no longer comfortable. The old
figure in this file was *"clears at any efficiency above 40 %"* and that was
computed for the MCU alone; the rail carries four more things.

**Do not raise `SUPPLY_IOUT_MA`.** It is a datasheet reading. If the efficiency
measurement ever disagrees, the thing to change is the 92.7 mA of relay coil
that V5 makes linearly from twelve volts — 37 % of +Vout, and the only load on
this board large enough to matter.

### What drawing it found, and three of the five are corrections

**A requirement derived while a block is deferred is counted against the
interface that stands in for it.** `controller_asks()` walked J9–J13 and got 14
signals; those headers carried what *the rest of the board* needed from a
controller, and the part also needs pins for its own periphery. **19 of 30**,
and the GPIO margin falls from 2.14× to 1.58×. Nothing was wrong with the
count; it was a count of a different thing.

**The PWM row had the wrong denominator.** Six carriers against *sixteen
outputs* — and spec §4.2 asks for the six to be phase-staggered, which a PWM
slice cannot do to two channels at once because a slice is one counter. Six of
**eight slices**, 1.33×, and it is the tightest countable row in
`controller_fit()` now. `CONTROLLER_MAP` spends six separate slices and
`controller_slices()` checks it.

**`supply_beat()`'s harmonic search was a fact about one caller.** It stopped at
the pump's 20th, which covers 580 kHz — the 12.9th — and truncated the moment
`mcu_dcdc_beat()` asked about 1.1 MHz, the 24th: it reported 200 kHz where the
answer is 20. The count comes from the frequency now. The general form is this
repo's usual one: a constant that is a fact about the *only existing caller*,
written where it looks like a fact about the arithmetic.

**This board has a second isolation barrier.** DIN MIDI is an opto-isolated
current loop, so `U21` is a second `U15` and `C836` is a second `C810` — CA-033
requires the bridge to be a capacitor: *"Pin 2 of the MIDI In connector shall
not have any DC path to the receiver's ground"*. `floorplan.py` said *"the"*
barrier in three places; `BARRIERS` is a table now and `check_isolation()` is
one test run twice. Its geometric half is deliberately **not** extended —
`check_isolation_gap()` measures a region because the converter's primary is a
20 V node switching across 50 pF next to the audio bond, and MIDI's barrier is
0.4 pF inside a package.

**A connector at the edge is not a connector nearest the edge.**
`placement.outline()` adds `MARGIN` of clear board around whatever is outermost,
so a USB receptacle placed as far east as anything else is 5 mm inside the board
and no plug reaches it — placed, routed, DRC-clean and unusable, with nothing in
the repo able to say so. `EDGE_PARTS` and `check_edge_parts()` are the
instrument, and `outline()` leaves the margin off on the side an edge part
faces. Without that second half the check is circular: the connector pushes the
outline out by five millimetres and then fails to reach it, for ever.

### Two the QFN found in files that had nothing to do with the controller

**`verify._board_copper()` had never returned a single pad.** Its guard read
`len(net) < 3`, with a comment saying KiCad writes `(net 12 "MDGND")` on a pad
and `(net "MDGND")` on a segment — and every board this repo has built, every
committed one included, writes the two-element form on *both*. So the guard was
true for every pad, and `check_isolation_gap()` — whose entire subject is where
parts are — had been measuring tracks and vias and nothing that was placed. It
reported nothing wrong, which was true. **Nothing would have found it**: it was
found by writing a second geometric check that needed pads and getting an empty
list back. The reader takes the net name as the last element now, either form,
and the isolation check sees 915 pads where it saw none.

**A QFN's exposed pad is copper on the back as well.** `pad_boxes()` decided a
pad's layers from its *drill* — through-hole means every layer, anything else
means front — and KiCad's `_ThermalVias` variant puts the 3.2 mm thermal pad on
F.Cu **and** B.Cu. Declared front-only it was invisible to the router, which
laid IRQ straight across it on the back: **64 DRC violations from one
assumption**. The pad knows what layers it is on and is asked now, which is
also true of parts nobody has fitted yet.

**Both are the same shape and it is this repo's oldest one:** a property
inferred from a neighbouring fact — a drill, a file format — where the artefact
could have been asked directly.

**And a third, one level further out: `design.supply()`'s comment named
`floorplan.check_zone_occupancy()` as "the instrument that would have said so"
and no such function existed.** In a paragraph about two artefacts disagreeing
because nothing compared them. A comment naming a check is not a call to one,
so nothing could fail; it survived two passes and was found by grepping for the
name while drawing the last zone. It exists now as
`placement.check_zone_occupancy()` — there and not in `floorplan.py` because the
dependency runs the other way — and writing it required a zone-to-parts table
that had never been written down, which is the same finding again: until the
last zone was drawn, *"the parts in zone P"* was not a question any file could
be asked.

### Three things about the block that are firmware's and are recorded here

Because nothing else in this repo can hold them, and they are hardware-shaped:

* **FSDRV is toggled in software, never by the PWM peripheral.** The fail-safe's
  mechanism is that *any* stuck state collapses the charge pump, and a hardware
  PWM output is exactly a square-wave source that outlives a wedged processor.
  It is on a plain GPIO and `CONTROLLER_MAP` says why.
* **The six PWM slices want a phase stagger**, §4.2 — which is what buying six
  separate slices is for.
* **The expression pedal is calibrated at its extremes**, because pedals differ
  in element value and taper. The hardware delivers monotonic and bounded.

### The values, and the rule they follow

Everything in the block comes from a document read first-hand: the RP2040
datasheet, **Hardware design with RP2040** (the vendor's own reference design),
the W25Q128JV's, the TLP2761's, the TPS560430's, Bourns' SRN6045TA, and CA-033
— the MMA/AMEI *MIDI 1.0 Electrical Specification Update*. **Where the vendor
states a value it is used and quoted; where it states a range or leaves the
choice to the application, a function here derives it.** 12 MHz is a
requirement (§1.4.1, the USB bootloader), 15 pF is the reference design's own
arithmetic, 27 Ω is Table 620's word *required*, and the QSPI_SS pull-up is
**not fitted** because §2.2 marks it DNF for this exact flash.

**The one value this repo had to choose is the MIDI receiver's series
resistor, and the first claim about it was wrong.** A MIDI cable does not say
what is on the other end — a 5 V transmitter is 440 Ω of source and a 3.3 V one
is 43 — so the resistor has to hold the LED current inside the TLP2761's 2–6 mA
at both. This file said CA-033's own 220 Ω delivers 6.6 mA and fails; that came
from using 0.2 V for the driver's V_OL where the datasheet says 0.5, and the
real spread at 220 Ω is **4.32–5.51 mA, which passes**. **390 Ω** is fitted
because it centres the spread — 2.66–3.80 mA, 1.66× and 1.58× — rather than
because 220 fails. `midi_loop()` is the arithmetic and `check_midi()` computes
the current rather than comparing the value, which is what makes the check hold
against drift in either direction.

## A part number is a claim about four things, and nothing was reading it

**`Design.check_order_codes()` decodes a ceramic capacitor's MPN** -- case,
dielectric, voltage, capacitance -- and compares all four to the value string
and to the land. It exists because a re-sourcing pass produced three wrong
codes in one afternoon and uncovered a fourth that had stood for four passes:

* `10u/16V X7R` carried an **0805** code on a **1210** land, in **X5R** against
  a value string saying X7R. Eight parts, wrong twice over;
* two substitutes were offered a decimal exponent out -- `562` for `563` is a
  factor of ten, `561` is a factor of a hundred. **The third digit of an EIA
  code is an exponent**, so a one-character slip is always an order of
  magnitude and nothing about the number looks wrong.

**Two limits are written into the check rather than left to be discovered.**
It parses only the vendor schemes it has been taught -- Murata GRM/GCM, TDK C
and CGA, Yageo CC -- and an unparsed code is *reported and counted*, never
passed. And it cannot tell whether a part **exists**: the fourth wrong code
this pass produced was invented by pattern from a real one, decodes correctly
in every field, and TDK does not make it. That is a distributor's question and
the check says so.

**The general form, and it is the one this repo keeps arriving at from new
directions: a fact encoded in a string that nothing reads.** `ORDER_CODES`
had a rule about *links* -- "a URL that has been fetched and seen to resolve"
-- and none about the part number the link points at. `check_orderable()`
asked whether a value *has* a code and never whether the code is that part.

**And its sibling is still open: a choice with no argument recorded.**
`VREF_NR_CAP` was C0G for four passes with no reason written anywhere, which
cost a specialty part at ten times the price of the identical X7R thirty-five
BOM rows above it -- on the one line that then could not be sourced. The
datasheet names no dielectric at that pin and offers 100 uF as an alternative,
which cannot be C0G. `C_FILM_FP` is the same shape and is still bare. This
repo has instruments for a value nothing uses and none for a value used
everywhere with no reason beside it.

## No instrument here opens a datasheet, and three parts were wrong

**`docs/footprint-audit.md` is the record and it must be read before anything
is ordered.** Checked against the manufacturers' own documents, before a first
order:

* **`BAT54-7-F` is SOT-23** (Diodes DS11005, *"Case: SOT-23"*) and sits on
  `Diode_SMD:D_SOD-123`, a two-pad land. Five parts, and no orientation fits a
  three-lead package on two pads at 2.6 mm. **This one cannot be assembled.**
* **`G6S-2 DC5` is Omron's through-hole model.** Its datasheet page 5 lists
  `G6S-2F` and `G6S-2G` with *"Mounting Dimensions"* and `G6S-2` with *"PCB
  Mounting Holes -- Eight, 1-dia. holes"*. The board fits the **-2F** land, so
  three relays want 24 drilled holes the fabrication package does not have.
  The design's own comment -- *"fully sealed, in the surface-mount G6S-2F
  body"* -- is where the two models became one. **Every other reading is
  right, including the pin map**, which was taken from the top-view diagram
  and top view *is* the -2F row. `G6S-2F DC5` is the whole fix.
* **`1N4148WS-7-F` is SOD-323**; the SOD-123 part is `1N4148W-7-F`, which is
  what the value string beside it has said all along.

**The general form, and it is why no green light was wrong.** `verify.py`
compares KiCad's netlist to `design.py` by name *and pin* -- and a pad
numbered 1 on the wrong package is still pad 1. `check_order_codes()` decodes
a ceramic's part number against its land and stops at ceramics.
`check_courtyards()` holds `placement.SIZE` to KiCad's courtyard, which is
KiCad's opinion of a part this project never checked. **Every instrument here
reads an artefact this project wrote**, and a footprint is a claim about
something that arrives in a bag.

**The one footprint this repo drew itself passes on every measurement** --
`gen_project.TMR6WI` against page 4 of the TMR 6WI datasheet: 21.8 x 9.1 body,
the 2.0 / 2 x 2.54 / 5.08 / 3 x 2.54 pin string, pin 4 absent, the row 3.5 mm
from the near long edge and 5.6 from the far one, and the **dual-output**
pinout column rather than the single-output one they differ from at pins 7 and
8. Which is the joke of the pass: the hand-drawn one is right and three
library choices are not.

**What would mechanise it** is `check_order_codes()` one class out -- a
package suffix table per vendor, reported when unparsed, never passed. It
would have caught all three. What it still cannot do is say whether a part
exists.

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
    00-current-state.md  context: why the choices are what they are. Three of
                         its claims lose to delta.py, marked at the top; two
                         rows are stale in their own right and marked in place
                         -- the envelope ADC's, and the controller's, whose
                         claim 9 is now marked "not relied upon"
    STYLE.md             the mixer's conventions, written after reading it
    ssi2164-control-port.md  the datasheet read first-hand — spec corrections
    element-revisit.md   SSI2164 vs THAT2180 vs THAT4301, and where it landed
    supply-decision.md   isolated DC-DC at >=300 kHz, and why. Carries its own
                         index of six numbers that moved once it was drawn
    fabrication-class.md 0.09/0.09 on 1 oz, and the four-row measurement that
                         decided it rather than an argument
    controller.md        the last deferred block: the two gates, the part that
                         closed the second, and the five things drawing it found
    routing-tool.md      KiCadRoutingTools: what it is worth here and the
                         four things it must be told. Its defaults route on
                         the ground planes
    return-vias.md       where a signal changes reference plane, what the
                         loop is worth, and why the copper was cheaper than
                         the derivation
    bench.md             what is left to measure, in order, and what each
                         reading decides. Three, and only noise_floor can be
                         taken before the board is fabricated
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
  placement.py           the floorplan as coordinates. No KiCad import.
                         pack_east() lays a row, clear_south() stacks the
                         bands, and check_courtyard_gap() is at zero
  route.py               the maze router. RESTORED, and it runs once: it is
                         gen_pcb.py --seed-routing and nothing else calls it
  krt.py                 drives KiCadRoutingTools from rules.py, placement.py
                         and design.py. Generates every argument; never writes
                         the board without --commit. docs/routing-tool.md
  silk.py                the silkscreen: the title block, the connector
                         legend and a name beside every connector, all
                         generated from design.SILK_NAME/SILK_ROLE and the
                         netlist. Owns every board-level F.SilkS text;
                         positions are probed, --commit writes
  mounts.py              the board's six fixings. Derives nothing itself --
                         placement.mounting_holes() does -- and puts them on
                         the board through pcbnew, with a rule area each so
                         the pours are voided where a screw passes through
                         both planes. Idempotent; --commit writes
  returns.py             the return-via stitching. Reads the board, finds the
                         audio vias with no ground via near them, and adds one
                         where the rules allow. Adds only -- it disturbs no
                         copper, so re-run it after any re-route. --commit
                         writes. docs/return-vias.md
  verify.py              the constraints, checked against KiCad's own netlist
  test_verify.py         plants faults to prove verify.py's checks can fail

  gen_pcb.py             -> out/cv-module.kicad_pcb, through pcbnew. Relaunches
                         itself under KiCad's Python, then re-runs gen_project.
                         PLACE AND POUR by default: re-running it discards
                         hand-routed copper, and gen_pcb_guard refuses unless
                         --discard-routing. --seed-routing adds one pass of
                         route.py, which is how the handover board was made.
                         Sync a netlist change with KiCad's own Update PCB
                         from Schematic instead
  gen_netlist.py         -> out/cv-module.net
  gen_sch.py             -> out/cv-module.kicad_sch
  gen_project.py         -> out/cv-module.kicad_pro, the lib tables,
                         out/cv.kicad_sym and out/cv.pretty -- the project's
                         own symbols *and* its one own footprint
  gen_bom.py             -> out/cv-module-bom.csv, docs/SHOPPING.md
  gen_plots.py           -> docs/cv-module-{schematic,layout}.pdf, -top.png
  gen_fab.py             -> fab/ -- the gerbers, the drill, the job file, the
                         placement list and ORDER.md. Reads gen_plots.orderable()
                         and KiCad's own DRC as its gate, derives the layer set
                         by exporting and reading back, and normalises every
                         timestamp so the package is a function of the board.
                         --verify says the tracked package is that board's
  gen_assumptions.py     -> docs/ASSUMPTIONS.md
  constraints.py         -> docs/constraints.md
  floorplan.py           -> docs/floorplan.md
  rules.py               -> docs/rules.md

  fab/                   what a fabricator is given. Generated, tracked as
                         loose text; fab/*.zip is the upload and is ignored

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
  && python3 gen_plots.py && python3 gen_fab.py
```

**`gen_pcb.py` is not in it.** It places, pours and stitches, and it lays no
signal copper -- so running it over a hand-routed board discards the routing,
with no undo. It is a *starting* step, run once, and after that the board is
edited in KiCad:

```bash
python3 gen_pcb.py                 # refuses if the board carries signal copper
python3 gen_pcb.py --discard-routing   # and this is how you mean it
python3 gen_pcb.py --discard-routing --seed-routing   # ...with one router pass
```

The third form is how the handover board was made: place, pour, stitch, and
then **one** run of `route.py` so that what somebody opens is a legal route to
adjust rather than a ratsnest. It is a starting point and not an output --
nothing downstream reads it, and the guard refuses the next run whether the
copper came from the router or from a person.

`returns.py` is a fourth way copper gets laid and it is not in either pipeline
either. It adds ground stitches and nothing else, so unlike the other three it
cannot destroy anything; `--commit` is still what writes.

`krt.py` is a third way copper gets laid and it is not in either pipeline
either: it routes a scope with KiCadRoutingTools and writes
`out/cv-module-krt.kicad_pcb`. **Only `--commit` touches the tracked board**,
and that is the whole of its safety -- it does not go through
`gen_pcb_guard.refuse_to_discard_routing()` because it never writes the board
by accident.

**What it discards depends on the scope and the difference is the hazard.**
`--nets "ENVA*"` rips and re-lays those six and leaves every other net's copper
untouched, measured per-net. A bare `python3 krt.py` is `--nets "*"` with
`--force-reroute`: it rips and re-lays **every net on the board**, so committing
one over hand-routed copper destroys the hand-routing exactly as
`gen_pcb.py --discard-routing` would. The candidate file is what stands between
those two, not a guard. See the section above.

The refusal is `gen_pcb_guard.refuse_to_discard_routing()` and it is enforced
rather than documented, because for one pass it was documented in three files
while this very code block still had `gen_pcb.py` in the middle of it.

**To move a netlist change onto a routed board**, use KiCad's own **Tools ->
Update PCB from Schematic** against `out/cv-module.kicad_sch`, which the first
pipeline regenerates. That is the only sync path.

**And the run takes about a minute now, of which `gen_pcb.py` is eleven
seconds.** It was half an hour: 89 s at 164 nets, and the controller took it to
201 nets and 314 parts on a router whose cost is contention rather than cell
count. Deleting the router deleted the whole of that. The measurement is kept
in `rules.grid_cost()` because it is the record of a wrong prediction --
"4.7x the cells will be slower" was 22 % faster -- and because nothing else in
this repo has measured a superlinear cost curve. What is *not* worth keeping is
the advice that followed it: there is no longer a build long enough to be
mistaken for a hang.

**`rules.py` is last in that list and first in the dependency order**, which is
worth not being confused by: `gen_pcb.py` and `gen_project.py` both import it,
so its constants are already in force by the time anything runs. Its own line
only writes `docs/rules.md`.

**And the property `PDF_EPOCH` exists to give the plots, the *board* does not
have.** `out/cv-module.kicad_pcb` is not a function of the design: KiCad mints a
fresh UUID for every footprint, pad and segment on each build and the
serialisation order follows them, so a rebuild of an unchanged design rewrites
**102,909 lines of a 6.5 MB tracked file** — measured, with the geometry
bit-for-bit identical either side (same 266 refs, 960 footprint positions, 26,347
segments, 694 vias). That is exactly the condition `PDF_EPOCH`'s own comment
calls out: *a tracked binary that churns on every run is one whose history says
nothing*. It propagates, too — the layout PDF's content stream follows the
board's item order, so the plot churns for the same reason one level up, and
normalising the timestamp does not touch it.

**The fix is deterministic UUIDs** — derived from the designator and pad number
rather than taken from KiCad's generator, plus emission in a sorted order — and
it is a pass of its own. Until then, a board diff is not evidence of a design
change, and the way to ask is to compare extracted geometry rather than bytes.

**One misread worth recording, because it is how this hid.** A `git diff --quiet`
on the board returned clean and was read as evidence the generator is
deterministic. It was not evidence of anything: the file had just been committed
from that same run, so it matched for that reason. A tautology read as a
measurement.

**`python3 gen_plots.py --verify` is a mode and deliberately not a stage.**
`PDF_EPOCH` makes each tracked plot a function of the board, and that half holds
— two plots of one board are byte-identical, measured. The other half is whether
the plots on disk are a function of *this* board, and nothing covered it: a commit
taken after `gen_pcb.py` writes the board and before `gen_plots.py` replots it
captures a board and a plot from two different runs. **Commit `789c4ba` is exactly
that**, by 534 bytes. `check_plots()` replots the tracked board into a temporary
directory and compares bytes; it was validated by running it against `789c4ba`,
where it fails on the layout PDF and passes on the other two. It is not in the
run order on purpose: after `gen_plots.py` it would compare files just written
against themselves and pass for free, and before it, on a board that has
legitimately changed, it would fail for the expected reason and be switched off
inside a week. Its place is a clean checkout, or before a commit.

**`gen_plots.py` produces the only outputs a person can look at without
installing KiCad** — the schematic, one plotted page per copper layer, and a
render of the board. It must run after `gen_pcb.py`, and it rewrites each PDF's
`/CreationDate` to the epoch so that two builds of one board give byte-identical
files: these are tracked binaries, and a tracked binary that churns on every run
is one whose history says nothing. **It writes no gerbers, and that is now a
division of labour rather than a refusal:** `gen_fab.py` writes them, and
imports `gen_plots.orderable()` -- which still reads `design.UNSPECIFIED` and
`design.DEFERRED` -- as one of its two gates. The other is KiCad's own DRC, run
when the package is written rather than read off an old report.

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

**And the class decision killed two more planted faults, which is the same
lesson a third time.** *"A net class clearance drifts off rules.py"* and *"the
board carries a track of an undeclared width"* mutated by `str.replace` on the
literals `'"clearance": 0.2'` and `'(width 0.25)'` — values `rules.py` owns.
The moment the class moved to 0.09/0.09 neither matched anything: the replace
wrote the file back unchanged, `check_rules()` correctly found no problem, and
both reported MISSED. **A mutation whose target is a value another file owns
goes dead when that file changes**, and the fix is the same shape twice: read
the value from where it lives, and make the harness refuse a mutation that
changes nothing. `dead_mutations()` guards `set.discard`; the file-rewriting
cases now guard `str.replace` the same way, and the guard was validated by
restoring the stale literal and watching it report DEAD.

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