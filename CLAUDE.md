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

## The router reaches a pad only if a track can *legally* land inside it

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

## The controller: the part is settled and the block is still not drawn

**`design.DEFERRED` is not empty and its one entry changed kind.** It read
*"shared block, and the scope statement puts shared blocks after one channel is
complete"* — a scope statement, true of every shared block and by then the only
one it was still true of. Deriving what the block asks for turned it into two
computed gates, and **both are decisions above a drawing.**

**What is closed.** `design.controller_fit()` is the positive case that never
existed: ten requirements this board makes, counted off the netlist where they
are countable, against ten numbers read first-hand from the RP2040 datasheet.
Fourteen signals across J9–J13 against 30 GPIO; 6 PWM against 16 on 8 slices;
MCLK ≥ 9.216 MHz met by **seven** integer divides of 125 MHz. Tightest countable
margin 2×. `00-current-state.md`'s claim 9 — *"both have mandatory buck
converters"* — is marked **not relied upon**: it is a negative, its "mandatory"
came from documents 0–4 which are not in this repo, no RP2350 datasheet page is
cited anywhere here, and claim 10 says the MCU was never load-bearing anyway.

**Gate 1 — the package, `controller_package()`.** RP2040 ships only in a 7×7
QFN-56 at 0.40 mm pitch, and it fails **all three** conditions of the middle rung:
the widest escape that clears the next pin is 0.20 mm against this board's 0.25;
0.40 mm of pitch on a 0.50 mm grid gives fourteen pins a side eleven lines to land
on; and the jog comes 0.150 mm to a neighbour against 0.45.

**`rules.coarsest_class_for()` solves for the class rather than reading one off a
table, and the answer is 0.12/0.12 mm or finer** — below JLCPCB's 0.15 mm 2 oz
floor and above its 0.09 mm one. So the only listed class that works is
**0.09/0.09, which is 1 oz outer copper only: the copper weight is the price and
no intermediate class avoids it.** At that class no pad on the package needs an
escape at all — the fan-out becomes unnecessary rather than sufficient — and the
grid goes to 0.23 mm, 4.7× the cells. It drags two unsettled things with it: a
router whose work is superlinear in cell count, and the coil nets at 93 mA on
0.09 mm of 1 oz copper unless they get a width of their own, which `route.py`
cannot currently give them.

**Gate 2 — the supply, `controller_supply()`.** `supply_fit()` leaves **35.4 mA**
of +Vout. V3V3 is an MCP1700 off V5 off VA+, so a milliamp of 3.3 V is a
milliamp of *twelve* at the converter's pin. The RP2040's own measured range is
19.2–52.1 mA (Table 637) and **neither end works**: the top fails outright, the
bottom leaves 16.2 mA for a QSPI flash, a MIDI current loop and an opto. **A
switcher from VA+ is the only topology with room, and saying so needs no
efficiency figure** — conservation of energy puts its input current at least
`3.3/12 × 52.1 = 14.3 mA`, so it clears at any efficiency above **40 %**.
Quoting 85 % would have been a plausible number about a part nobody has chosen.
`supply_beat()` is what has to price its frequency, and note what that function
already found: the ≥300 kHz rule is fundamental-only, so a second unit has to be
checked against the pump's harmonics *and* against this converter's own
522–638 kHz band.

**Do not raise `SUPPLY_IOUT_MA`.** It is a datasheet reading.

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