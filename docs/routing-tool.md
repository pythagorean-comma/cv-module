# KiCadRoutingTools — what it is worth here, and what it must be told

**Not generated.** This is a decision record, in the shape
`fabrication-class.md` and `controller.md` have: what was measured, what it
decided, and what survived being wrong.

[KiCadRoutingTools](https://github.com/drandyhaas/KiCadRoutingTools) is a
Rust-accelerated A\* autorouter for KiCad, with a plugin GUI, a CLI, and nine
Claude Code skills of its own. It was evaluated at **v0.21.2** against this
board, on copies, with the tracked board never written to.

---

## The verdict, first

**It is a better copper engine than `route.py` and it is not a judge of this
board.** Both halves are load-bearing.

It closed all 185 nets from scratch, from a stripped board, in **five minutes** —
twice, on two different layer configurations, with zero failed nets. Its own
checkers independently corroborated `verify.py`: `check_connected.py` and
`check_drc.py` both pass on the committed board, which is the first second
opinion this repository has ever had, every existing instrument being something
that reads `design.py`.

And pointed at this board with its defaults it laid **4106 mm of signal track
through both ground planes**, with its own DRC clean, its own connectivity
clean, and its own improvement gate reporting `accept`.

That last sentence is the whole document. **Every instrument agreed while the
thing this board's noise argument rests on was cut to pieces** — which is this
repository's oldest failure, arriving from outside it for the first time: a
check that passes and covers less than its name.

---

## What it gets right without being asked

Worth stating, because the list is long enough that the four corrections below
would otherwise read as a verdict on the tool rather than on its defaults.

| | |
|---|---|
| **it parses this board exactly** | 185 nets, 290 components, 8 zones — the repo's own figures |
| **it honours the Pico's keep-outs** | all 12 rule areas, `tracks_allowed: False`, `vias_allowed: False`. That is the exact fault `route.py` had: five `items_not_allowed` VMCU tracks, found by DRC |
| **it reads the fab rules off `cv-module.kicad_pro`** | clearance 0.2, board edge 0.3, **hole-to-hole 0.4064** — `rules.hole_rules()`'s own PCBWay figure, consumed without being told |
| **it honours net classes** | including the Power class `route.py` never could draw |
| **it is scoped and non-destructive** | a six-net reroute changed exactly those six nets' copper and nothing else, measured per-net. Committed tracks are never ripped without an explicit flag |
| **it has an improvement gate** | it compares connectivity across all 185 nets before and after, and **reverts the whole run** if any net went open. Measured — see the two-pass section |
| **it does not need `pcbnew`** | `route.py` parses the board with its own s-expression reader, so it runs under an ordinary interpreter. Nothing about it touches KiCad's bundled Python |

It also knows about multiple ground domains: `add_gnd_vias.py` refuses to count
another domain's ground as a return path for a signal. On a board with MAGND
and MDGND that is not a small thing.

---

## The four corrections, each measured

### 1. It routes on the ground planes

`In1.Cu` and `In2.Cu` are **entirely** MAGND and MDGND pour. `route.py` used
only F.Cu and B.Cu, which is the ground strategy — two solid references, split
into analogue and digital, with the primary's corner left bare — and **that
strategy is nowhere written as a rule a tool could read.** It was a consequence
of `route.py` being handed two layers.

The tool defaults to every copper layer and says so in one line of a
two-hundred-line log. What follows is 4.1 metres of slot in the reference plane
directly under the audio it returns. DRC does not object: the zone filler flows
around each track with clearance, so the plane is legal and perforated.

`krt.py`'s `routing_layers()` derives the list from the board's own zones rather
than naming F.Cu and B.Cu, because a layer becomes a plane by being poured on
and the pour lives in `gen_pcb.py`.

### 2. Its fabrication floor is JLCPCB's, not ours

`fab_tiers.py` gives a 4-layer board a `standard` floor of **0.0889 mm track
and 0.10 mm clearance**, and escalates to an `advanced` rung below that. This
board is 0.20/0.20 at PCBWay.

The tool treats the project's net class as a *nominal* and the tier as a floor
it may escalate down to when a net will not otherwise close. It did:
constrained to two layers it rescued `PIN6` — **an audio input from the mixer
socket** — as 34 segments of 0.0889 mm copper, less than half the class the
board is ordered at.

`--fab-overrides`, written from `rules.py`, pins the floor to one rung and
disables the escalation. Measured: `min_clearance_used` goes 0.175 → **0.2**,
every via comes back 0.7/0.3, and no sub-class copper is drawn.

**This is the single most load-bearing argument and it is the one nobody would
think to pass**, because the project file already says 0.20 and the tool
already read it.

### 3. It rewrites the project file

On its way out it rewrites the sibling `.kicad_pro` to match the floors it
used. Unpinned, on this board:

```
min_clearance      0.2   -> 0.175
min_hole_clearance 0.25  -> 0.2
min_track_width    0.2   -> 0.1998
min_via_diameter   0.7   -> 0.25
rule_severities: annular_width, solder_mask_bridge, malformed_courtyard,
                 npth_inside_courtyard, pth_inside_courtyard,
                 lib_footprint_issues, lib_footprint_mismatch  ->  ignore
```

`verify.py` runs `kicad-cli pcb drc` against that file. **So the tool can make
this repository's own verification pass by moving its goalposts.**

Note which number it chose for copper-to-hole: **0.20 mm** — the exact figure
`rules.hole_rules()` refused, on the grounds that declaring it "would have made
49 violations vanish with no copper moving — indistinguishable from relaxing a
check to pass". It arrived anyway, from a tool that had never read that
sentence.

To the tool's credit it announces this under a `FAB FLOOR RELAXED` heading and
records the original values under `kicad_routing_tools.fab_floor_origin`, so
the relaxation is auditable and reversible. In an automated chain it scrolls
past.

**The defence already exists and is not new work.** `gen_project.py` writes the
project from `rules.py`, and `gen_pcb.py` re-runs it after `SaveBoard()` for
this identical reason — `SaveBoard()` flattening the project is the same
failure with a different cause. `krt.py --commit` re-runs it too.

### 4. Two violations it cannot be configured out of

`MCLK` and `CS` come to rest 0.013 and 0.027 mm inside U19's mounting holes,
against this board's 0.25 mm copper-to-hole rule. The override format has keys
for track, clearance, via diameter, via drill, hole-to-hole and board edge —
**none for copper-to-hole**, where the tool works to 0.20 internally.

A person moves them in KiCad in under a minute. `verify.py` is what reports
them. It is recorded here rather than worked around because a gap that is known
is cheaper than one that is rediscovered.

---

## The primary's region needs a keep-out, and that needs three passes

**Measured:** with no keep-out, a full reroute puts **24 pieces of copper**
inside the primary's isolation region — `MIDI_TX` among them.
`verify.check_isolation_gap()` catches every one, which is the check working;
but the router will do it on every run, because nothing in the board says that
corner is special. It is a *place*, and the tool has no notion of place.

The mechanism is there: closed `gr_poly`/`gr_rect` on `User.2` plus
`--keepout`, honoured across single-ended, multipoint and diff-pair routing.
`krt.py` injects one rectangle derived from `placement.ISOLATION_X`,
`ISOLATION_Y` and `isolation_south()` — **the same three numbers
`check_isolation_gap()` measures against, imported rather than re-read**,
because the one thing worse than no keep-out is one that disagrees with the
check by half a millimetre — and strips it from the routed board afterwards,
keyed on a uuid it wrote rather than on the layer.

**And the keep-out is absolute across every net in the run**, which is where
the second pass comes from. A single pass with the region blocked fails the six
primary nets that *live* inside it — and then the improvement gate does exactly
what it should:

```
IMPROVEMENT GATE: this run broke 6 previously-connected net(s) and connected 0 -- REJECTED
  REVERTED ... to the input board (the pre-rip board is the better artifact)
```

So a naive single pass produces **no copper at all**, correctly. The primary
nets are excluded from pass one by pattern and routed alone in pass two, where
they close 6/6 with zero vias, being local to the inlet.

That the gate caught this is the strongest single argument for the tool. It is
also the argument for `verify.UNROUTED_ITEMS` being zero rather than small: the
gate's whole mechanism is a before/after comparison against a board that was
already closed.

### And a keep-out's cost is not paid where it is drawn

**This is the finding of the pass and it cost a run to get.** With the primary
nets excluded by pattern rather than left to fail, pass one *still* lost a net —
`BUF2` — and the gate rejected the run again.

`BUF2`'s five parts (`C201`, `R202`, `R251`, `R253`, `U1`) sit between
y = 17 mm and y = 81 mm. The keep-out is at y = 194–209 mm. **They are 113 mm
apart and BUF2 never wanted that corner.** Blocking the supply's corner
displaced copper that congested the CV band a board-length away.

That is `ENV_ADC_CHANNEL`'s finding arriving a second time, with a keep-out in
place of an escape:

> **an escape's copper is not free and it is not spent where it is laid.**

Nothing in this repository predicts it and nothing could — the router is the
only instrument that knows, which is the same argument for running it rather
than reasoning about it that the fan-out pass already made.

**`--max-ripup` is not the lever, and the way that was established is the
second finding.** A run at 12 returned exactly the run at the tool's default —
176/177, `BUF2` open, rejected — after twenty-five minutes. The tool had
already said it would, in the message printed by the *first* rejection:

> *"This run did not fail to execute — it ran and was REJECTED, so re-running
> it with MORE rip authority cannot help: change the approach (thinner track /
> finer grid / different layers), or accept the open nets and report them."*

**A source cited and never read** — `PUMP_RULES` upstream, `check_rules()`
here, and now a rejection message quoted into a log and not followed. It
arrived inside the pass whose whole subject is instruments that agree with each
other while nobody checks what they measured.

Of the three approaches it names, two are shut on this board: the spare layers
are reference planes and the track width is the fabrication class. What is left
is its third — **accept the open nets and report them**, which is
`verify.UNROUTED_ITEMS`'s own rule, *down as copper is laid, up only with the
nets named there*.

---

## The rescue pass, and where the gate belongs

Accepting an open net means a pass has to be *allowed* to leave one, and the
tool's improvement gate exists precisely to stop that. Both are right, and the
way out is that **they are answering different questions.**

The gate asks *is this pass no worse than its input*. What actually matters is
*is this plan no worse than its input* — and a plan whose first pass
deliberately defers what the keep-out blocked will fail the first question
while passing the second. So the gate comes off the deferring pass
(`KICAD_IMPROVEMENT_GATE=0`) and the refusal moves up to `krt.plan_gate()`,
which runs the tool's own `check_connected.py` over the finished candidate.
Not reimplemented here: a third opinion about what "connected" means is exactly
what this repo keeps finding, and that checker is the one the router itself was
graded against.

The plan is three passes:

| | scope | keep-out | gate |
|---|---|---|---|
| **1. secondary** | everything but the primary nets | **on** | **off** — it may defer |
| **2. rescue** | whatever pass 1 reported in `failed_single` | off | on |
| **3. primary** | the six isolated nets | off | on |

**The rescue is derived, not listed.** Nothing here predicts that `BUF2` is the
net that breaks — the router is the only instrument that knows — so the rescue
reads the answer off the run rather than carrying a name.

**And it drops the keep-out on a theory that has to be tested.** A net the
keep-out broke is not in general a net that wants the region; `BUF2` is 113 mm
from it. That is a claim about each rescued net, so
`verify.check_isolation_gap()` is where it gets checked — the instrument that
already owns the question, against the same three coordinates the keep-out was
built from. If a rescued net did use the region, the check names it and
`--commit` refuses.

### Measured

```
-- pass 1: secondary --   routed 176, failed 1, min clearance 0.2 mm, gate off
                          deferred: BUF2
-- pass 2: rescue (1) --  routed 1, failed 0, min clearance 0.2 mm, gate accept
-- pass 3: primary --     routed 6, failed 0, min clearance 0.2 mm, gate accept

  planes intact: no signal copper on ['In1.Cu', 'In2.Cu']
  every net connected (the tool's own check_connected.py)
  primary's region clear
```

**About 5 min 50 s, whole board, from the committed board** — 5:53 and 5:48
over two runs. The candidate carries
**exactly one track width (0.2 mm) and exactly one via size (0.7/0.3)**, which
is `check_rules()`-clean, and **zero copper on either reference plane**.

**And the two runs are the same board.** Segment count, via count and total
track length are identical to the millimetre — 5122, 991, 13031 mm — and every
one of the 23,244 differing lines between the two files is a `uuid`. So the
router's *geometry* is a function of its inputs, and its *file* is not, which
is `PDF_EPOCH`'s finding one artefact along: a byte diff on a routed board
says nothing, and the way to ask whether anything changed is to compare
extracted geometry. Worth knowing before somebody reads a 23,000-line diff as
a design change.

One DRC violation remains at this board's real class: the `RUN` track 0.013 mm
inside U19's mounting hole — correction 4 above, the copper-to-hole rule the
override format has no key for. It is a minute's work in KiCad.

---

## What adoption actually cost, and neither thing was on the list

The board was routed, every check this file describes passed, and `verify.py`
had still never been run against it. When it was, it reported **703 DRC
violations.**

### The blocker was a stale pour

`route.py` copies the input board's `filled_polygon` data through untouched, so
a routed board carries pours filled around the **previous** via positions.
Every new via sits in solid plane copper with no antipad: 503 clearance and 204
hole-clearance violations, every one a via against MDGND on `In1.Cu` or
`In2.Cu` at **0.0000 mm**.

**Nothing built for this could see it, and the reasons are each worth keeping:**

| instrument | why it passed |
|---|---|
| `check_connected.py` | a via shorted to a plane is *more* connected, not less |
| the improvement gate | same reason — it compares connectivity |
| **`krt.check_planes_intact()`** | **it reads segments, and these are vias** |

The third is the one to carry. It is named for the plane, it was written
precisely to catch copper that perforates the plane, and it examines one of the
two things that do. A check that passes and covers less than its name, inside
the function written to catch checks that pass and cover less than their name —
the third time this project has recorded that exact shape, after
`check_fine_pitch_access()` measuring the pad while the router drew a track,
and `verify._board_copper()` never returning a pad.

`krt.refill_zones()` is the fix: `kicad-cli pcb drc --refill-zones
--save-board`, KiCad's own filler rather than a model of it, run before
anything grades the candidate. **703 → 1.**

### And the keep-out was scoped to the wrong thing

Re-routing the single net `RUN` put **ten pieces of copper inside the primary's
isolation region.** `krt.plan()` applied the keep-out only to whole-board runs,
on the reasoning that *a run that does not touch the supply has nothing to keep
out of the supply's corner* — which confuses where a net's **pads** are with
where its **copper** may go. `RUN`'s pads are nowhere near the barrier.

That is `BUF2`'s finding with the sign reversed. A keep-out's effect is not
confined to the nets near it, and neither is its absence. The keep-out is a
property of the **region**; only nets that belong inside it may ignore it, and
that is a property of the net rather than of the run.

`verify.check_isolation_gap()` named all ten and `--commit` refused. The check
earned its place the same day the bug was written.

### What it looks like now

```
python3 verify.py       -> exit 0, every check ok
python3 test_verify.py  -> all 92 faults caught
```

on a board whose every millimetre of signal copper was laid by
KiCadRoutingTools.

## The measurement

Full board, stripped and rerouted from scratch, on copies. `seed` is the
committed board as `route.py` left it.

| | seed | tool defaults | two layers | **krt.py, 3 passes** |
|---|---|---|---|---|
| nets closed | 185/185 | 183/183 | 183/183 | **185/185** |
| segments | 2925 | 5016 | 5490 | 5122 |
| vias | **746** | 797 | 1026 | 991 |
| total track | 14449 mm | 12112 mm | 13030 mm | **13031 mm** |
| **copper on the planes** | **0** | **4106 mm** | 0 | **0** |
| track widths | {0.2} | 9 values | 9 values | **{0.2}** |
| via sizes | {0.7/0.3} | 4 | 2 | **{0.7/0.3}** |
| DRC at this board's class | 0 | 0 | 2 | **1** |
| isolation region | clean | violated | violated | **clean** |
| wall time | 89 s | 3 min | 5.5 min | **5 min 53 s** |

**Read the via row before the length row.** Fully constrained, the tool gives
**9.8 % less track for 33 % more vias** — 13031 mm against 14449, and 991
against 746. Every extra via is a hole through both reference planes, which is
the same coupling the length saving was supposed to buy back. That trade is not
obviously good on this board, and it is why the recommendation below is not
"replace the seed".

---

## What it does not know, and cannot be told

The tool's judgement is aimed at a different problem class. Its skills do
datasheet-driven analysis of high-speed digital, DDR length matching,
differential pairs and impedance control. **This board has none of those.** It
has six audio channels, a 580 kHz isolated converter, two isolation barriers
and a noise floor argument measured in microvolts.

Nothing in it models:

- which nets are audio and which are not;
- where a return current wants to go;
- that `C810` is a declared bridge and the only thing that may cross a barrier;
- that the ground split at `SPLIT_Y` separates two returns meeting at one bond;
- that the seed's 14449 mm of track was laid on two layers *on purpose*.

Every one of those lives in this repository, in Python, and every one is
expressible to the tool as a layer list, a keep-out rectangle or a net scope.
That is the whole of `krt.py`.

---

## The decision it forced: `POWER_TRACK_MM`, and it is closed

**The tool drew 0.5 mm on the Power class and `route.py` never could.** Eight
nets are in that class — VA+, VA-, V5, VREF, VREFN, MAGND, MDGND, AGND — and
the tool honours the project without being asked, tapering between widths at
each transition. `verify.check_rules()` asserts the board carries **exactly
one** track width, so every such run failed verification.

Its docstring gave the reason:

> *route.py draws every net at TRACK_MM, rails included, because a 0.5 mm track
> needs a 0.7 mm grid and that grid does not route this board. POWER_TRACK_MM is
> what a rail is widened to by hand.*

True of `route.py`, and **a fact about the only existing caller written where it
reads as a fact about the board** — `supply_beat()`'s harmonic count and
`floorplan.CROSSING_RULE` one artefact along each. Nobody had ever widened a
rail by hand, so `POWER_TRACK_MM` was a declared constant with no copper behind
it and the only instrument that mentioned it asserted its *absence*.

**So the arriving router forced a derivation nobody had done.**
`design.power_track_verdict()` is it. Every mechanism a wider rail could
address:

| mechanism | at 0.20 mm | verdict |
|---|---|---|
| heating, `rules.track_current()` | 0.58 °C at VA+'s 213 mA | closed |
| static drop, measured per rail | 42 mV worst case, on V5 | closed |
| **shared-impedance crosstalk** | **−148.8 dB** vs a −54 dB requirement | **94.8 dB of margin** |

The crosstalk path is the only one that could have justified it: channel A's
signal current in a rail resistance channel B also sits on, divided by the
amplifier's power-supply rejection. The numbers are the board's own — the
shared path is **Dijkstra over the real copper graph**, weighting each segment
by its own width (VA+ 40 mΩ, VA- 364, V5 453, VMOD 282; VA- is the worst audio
rail, 148 mm of track) — and the amplifier is the OPA1644, `SBOS484D`.

**And the result does not depend on the datasheet.** PSRR in that document is a
DC row (`V_OS` vs power supply, 0.14 µV/V typ, **2 µV/V max** = −114 dB) plus
Figure 4, a curve; `bench.md`'s own rule is that a number read off a plotted
curve is not a reading. So `power_track_verdict()` also reports the bound with
**PSRR set to zero** — every microvolt on the rail arriving undiminished at the
input, which no amplifier is that bad at — and that is still **−88.8 dB, 34.8 dB
inside the requirement.** The amplifier would need a PSRR of **−34.8 dB**, a
gain of 55 rather than a rejection, for 0.20 mm to fail.

Same shape as the +Vout budget's *"fits at any efficiency above 68 %"*: a bound
that cannot be wrong beats an estimate that is probably right.

**Widening to 0.5 mm buys 7.96 dB on a figure with 94.8 dB of margin.** So
`rules.POWER_TRACK_MM` is deleted, both net classes declare `TRACK_MM`, and
`verify.check_rules()`'s one-width assertion is now a check on something rather
than an excuse for a constant.

**The Power class survives the constant**, and that is the part the arithmetic
did not decide. Its other field is `pcb_color` — the rails and both grounds in
red in the editor — and on a hand-laid board that is worth keeping. `krt.py`
needs no `--net-classes` mode any more either: with one width declared, the
router draws one width.

## How to run it

```bash
python3 krt.py --nets "ENVA*"          # re-route a region; writes a candidate
python3 krt.py --nets "ENVA*" --commit # ...and promote it, then gen_project.py
python3 krt.py                         # whole board, three passes, keep-out on
python3 krt.py --preview --nets "CV*"  # report what would change, write nothing
```

Nothing is written to `out/cv-module.kicad_pcb` without `--commit`. Without it
the routed board lands at `out/cv-module-krt.kicad_pcb` and the run reports what
it would have changed.

**`verify.py` is unchanged and remains the authority.** `krt.py` checks one
thing `verify.py` cannot — `check_planes_intact()`, no signal copper on a
poured layer — and that check exists because until now nothing could put it
there. Everything else is deferred: run the pipeline.

### Installing the tool's dependencies

It needs numpy, scipy and shapely, which this repository does not have and must
not acquire — the mixer's rule that "there is no `requirements.txt` because
there is nothing to install" is what lets the verification loop run anywhere
KiCad runs. **The tool is a subprocess precisely so that stays true.** Give it
an interpreter of its own:

```bash
python3 -m venv ~/code/KiCadRoutingTools/krt-venv
~/code/KiCadRoutingTools/krt-venv/bin/pip install numpy scipy shapely
```

`krt.py` finds `krt-venv` or `.venv` beside the tool, or `$KRT_PYTHON`. The
Rust core ships as an abi3 `.so` and imports on any modern Python; KiCad's own
bundled 3.9 is **not** a candidate — it carries `pcbnew` and none of the three,
and `route.py` never imports `pcbnew` anyway.

---

## Recommendation

**Use it for scoped re-routing, not to replace the seed.** The board is already
at 0 unrouted and 0 DRC; what a full reroute buys is 11 % less track for 32 %
more plane perforations, which is a trade this board should not obviously take.
What it buys on a *region* — a band that is congested, a net that took an ugly
path, a change synced in from the schematic — is a legal route in seconds
instead of an evening, inside constraints the design already owns, with a gate
that refuses to hand back anything worse than what it was given.

The rule from `CLAUDE.md` is unchanged and now has a second tool under it:

> **The netlist is generated and authoritative. The board is hand-laid and
> verified.**

A router that is told where the planes are, what the fab class is, and which
corner is the primary's is a hand tool with a fast edge. One that is not told
is 4.1 metres of slot in a reference plane, with every light green.
