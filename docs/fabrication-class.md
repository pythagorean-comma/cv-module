# The fabrication class — decided against PCBWay, at 0.20 / 0.20 on 1 oz

**Fitted: 0.20 / 0.20 mm track and clearance, 1 oz outer copper, 0.7 / 0.3 mm
vias.** `rules.FABRICATOR = "PCBWay"`, and it clears **both** fabricators:

| | track | space | annular ring |
|---|---|---|---|
| PCBWay, 1 oz | 0.127 → **+57 %** | 0.152 → **+32 %** | 0.15 → **+33 %** |
| JLCPCB, 1 oz | 0.09 → +122 % | 0.09 → +122 % | 0.05 → +300 % |

PCBWay is the binding floor in every row and at every copper weight, so
designing to it leaves JLCPCB open as a second source for nothing.

## What actually picked it, and it is not the margin column

Two SOIC pins leave **0.67 mm** of bare laminate between them
(`escape_corridor()`), and a track through that gap needs `track + 2 ×
clearance`:

| class | w + 2c | through a SOIC? | PCBWay 1 oz margin |
|---|---|---|---|
| **0.20 / 0.20** | 0.600 | **yes**, 0.07 mm spare | +57 % / +32 % |
| 0.25 / 0.25 | 0.750 | **no** | +97 % / +64 % |

The coarser class has *more* margin over the process and **cannot pass between
two pins of a SOIC** — on a board carrying a SOIC-20W, two SOIC-16, several
SOIC-14 and a SOIC-8. So the two figures point opposite ways and the corridor
is the one that decides, because margin over a published minimum is
insurance and the corridor is a routing capability you either have or do not.

**It is a 1 oz class and only a 1 oz class.** At 2 oz PCBWay's spacing floor is
0.203 mm, so 0.20 is 1.5 % *under* it — near enough to read as fine, and not.
This project wrote down "0.20/0.20 on 1 oz or 2 oz" once and it was wrong.

## Why not 2 oz

**Nothing on this board has ever wanted it.** `rules.track_current()` puts the
largest current here — 92.7 mA of relay coil — at **0.088 °C of rise** on
0.20 mm of 1 oz, against 0.028 °C at 2 oz. Both are noise. The weight was
carried for five passes as a free option, in this file's own words *"chosen to
be legal at either weight ... keeping the option costs nothing"*, and was never
bought against a requirement; it was then spent by the QFN, which has gone.

**And at 2 oz it would now cost something real.** The floor is 0.178 / 0.203,
so a track through the SOIC corridor needs 0.584 mm of the 0.67 available and
leaves **0.086 mm of total slack** to spend on margin. At 2 oz you choose
between holding margin over the process and routing between two pins of a
SOIC. At 1 oz you get both.

## The annular ring, which nothing was checking

A 0.6 mm via on a 0.3 mm drill is a **0.150 mm** annular ring against PCBWay's
published *"Min Width of Annular Ring: 0.15mm(6mil)"* — exactly on the floor,
on 767 vias, and passing every check in `rules.py` because each of them asked
about the diameter or the drill and none computed the quantity that is a
function of both. **0.7 / 0.3 mm**, a 0.200 mm ring, a third over.
`check_fab_class()` computes it now.

---

> ## The reading that got this wrong, kept
>
> ### ⚠ Everything below this line was decided against JLCPCB
>
> **Every number on this page was read from JLCPCB's capabilities page, and
> the board goes to PCBWay.** The reading was careful, first-hand and quoted;
> what was never asked is whether it was the right page. That is a different
> failure from citing a source without reading it — the repo's own STYLE.md
> rule 10 — and it costs the same, because a check that enforces the right
> number against the wrong process passes for the whole life of the mistake.
> `rules.FABRICATOR` and `rules.FAB_LIMITS` carry both tables now and
> `check_fab_class()` fails.
>
> **PCBWay's published outer-layer minimums**, capabilities page read
> 2026-08-19, converted from mil:
>
> | copper | normal | medium |
> |---|---|---|
> | 35 µm = 1 oz | **0.127 / 0.152 mm** | 0.127 / 0.127 mm |
> | 70 µm = 2 oz | **0.178 / 0.203 mm** | 0.152 / 0.178 mm |
>
> with a headline "Standard PCB" row giving *"0.1mm/4mil"* for both, and no
> copper weight attached to it. **Those two disagree and this page does not
> resolve it** — 0.1 mm is finer than the 1 oz row allows, so one is a
> marketing summary and the other is process engineering, and the document
> does not say which. The by-weight table is what `rules.py` enforces, because
> it is the one that distinguishes what the decision turns on.
>
> **Three things follow, and the first is the expensive one:**
>
> 1. **The fitted 0.09 / 0.09 is not manufacturable at PCBWay at any copper
>    weight** — 29 % under the 1 oz track minimum and 41 % under the spacing.
>    The only 3.5 mil entry on the page is at 18 µm, half an ounce, and is
>    qualified *"or parts 3.5/3.5mil"*. So the 55,854 segments on the board
>    are at a class the target fabricator does not offer, and **the routing has
>    to be redone whatever else is decided.**
> 2. **That removes the argument that put 0.09 / 0.09 back.** The reversal
>    below was justified entirely by preserving the existing copper. The
>    copper cannot be preserved, so the class is a free choice again and the
>    derivation in *The reversal* — 0.205 mm or finer for the finest pitch on
>    the board — is the live one. Against PCBWay's table that is met
>    comfortably by 1 oz normal and by 2 oz normal.
> 3. **It also reopens the controller.** The RP2040's QFN-56 was ruled out
>    because `route.py` could not reach 0.40 mm; `route.py` is deleted, and a
>    person can hand-route it. Against PCBWay's own numbers, a track leaving a
>    QFN pad on its own centre line has 0.211 mm of room against the 0.203 mm
>    that 2 oz normal requires — **4 % of margin** — and 0.237 mm against the
>    0.152 mm that 1 oz normal requires, which is comfortable. So the QFN is
>    buildable at 1 oz and is at the edge of the process at 2 oz, where the
>    Pico's 2.54 mm is not near any edge at either. **That is a decision about
>    how much process margin to hold, and it is not one this file can take.**
>
> Everything below is kept because the arithmetic in it is still correct and
> because it is the record of two mistakes worth not repeating.

---

# The fabrication class — decision, a reversal, and the reversal reversed

**Fitted: 0.09 / 0.09 mm track and clearance, on 1 oz outer copper — unchanged.**
`rules.COPPER_OZ`, `rules.TRACK_MM`, `rules.CLEARANCE_MM`.

> **This section was written as a decision to move to 0.15 / 0.15 on 2 oz, and
> that was wrong.** The derivation below it is correct and it is a fact about
> the *parts*: with the QFN gone, the finest pitch left needs 0.205 mm or
> finer and the 2 oz minimum class clears it. **What it omits is the copper.**
> This board carries 55,854 track segments laid at 0.09 / 0.09 on a 0.23 mm
> routing grid, and they are the starting point for the hand routing rather
> than something to throw away. Two adjacent tracks on that grid are 0.23 mm
> apart: 0.09 mm wide leaves a 0.14 mm gap against a 0.09 mm clearance and is
> legal; 0.15 mm wide leaves 0.08 mm against 0.15 and is not. So the coarser
> class does not merely fail to help — **it condemns every one of those
> segments, and widening them is not available either.**
>
> The shape of the mistake is this repo's oldest, arriving somewhere new: **a
> derivation that asks what the parts need and never asks what the board
> already has.** It is the same omission as `RAIL_FILTER_ESR` and as the
> A/mm² reading below — not a wrong number, a number computed without the term
> that dominates.
>
> **The arithmetic is kept because it is not wasted.** It is the answer for a
> board routed from nothing, so if the existing routing is ever ripped up,
> 0.15 / 0.15 on 2 oz is ready to use. The class is a free choice only when
> there is no copper; while there is, it is a property of the copper.

**This page is kept whole and it is read from the bottom.** Everything between
here and *The reversal* is the argument for 0.09 / 0.09 on 1 oz, which was
fitted, built and DRC-clean, and which was correct for the board it was decided
on. What changed is not a number in it: the RP2040's 0.40 mm QFN-56 became a
2.54 mm Raspberry Pi Pico, and the QFN was the whole of why the class was fine.
Rewriting the argument in place would have destroyed the only record of what a
0.40 mm pitch costs — which is the thing worth knowing if a part like it is ever
wanted again.

---

## The reversal, and it is not simply "put it back"

**Nothing on this board has an opinion about pin pitch any more, so this went
back to being a free choice — and a free choice still has to be taken by
arithmetic.** `rules.coarsest_class_for()` answers it against the *finest pitch
left on the board*, which is the MCP3564's TSSOP-20 at 0.65 mm:

| | needs | |
|---|---|---|
| RP2040 QFN-56, 0.40 mm | **0.12 / 0.12 mm or finer** | below the 2 oz floor, so 1 oz was the price |
| MCP3564 TSSOP-20, 0.65 mm | **0.205 / 0.205 mm or finer** | above the 2 oz floor of 0.15, so either weight works |

So the 2 oz minimum class clears the board by 27 % and the class that was
fitted *before* the QFN — 0.25 / 0.20 — does not. **The reversal is not to the
old value.** That is worth stating plainly, because "put it back" is what
everybody would have written down.

**Between 0.09 and 0.15 the arithmetic is silent and three other things are
not:**

* **it is not bought for current.** `rules.track_current()` puts the largest
  current on this board — 92.7 mA of relay coil — at 0.33 °C of rise on 0.09 mm
  of 1 oz and 0.045 °C on 0.15 mm of 2 oz. Both are nothing. Current capacity
  was never the reason and this section says so rather than letting 2 oz look
  like a current decision;
* **0.09 / 0.09 is the published floor with no margin at all**, which its own
  decision above records as the honest cost. 0.15 / 0.15 is the floor for 2 oz
  and 67 % above the finest class available, so process variation has somewhere
  to go;
* **the board is hand-routed now**, and that is this session's argument rather
  than a rediscovered one. A person laying 0.09 mm track on 0.09 mm clearance is
  working at the fabricator's limit with no room for a judgement call, and
  judgement is the whole of what `gen_pcb.py` giving up the router buys.

## What is no longer measurable, and it is the row this decision used to rest on

The four-row table below is `gen_pcb.py` end to end, and **two of its four
columns have stopped existing.** There is no router, so there is no "time" and
no "unrouted"; what is left is DRC, and DRC on a board with no signal copper on
it is a weak instrument.

That matters most for the third row — 0.25 / 0.20 with corrected via rules, 454
seconds, **10 unrouted (V5)**. It is the row that says a coarse class costs
connections, and it was a measurement of *this router* at a uniform 0.5 mm grid.
A person routing by hand is not on a grid and is not bound by it. So the row is
kept as history and **it is not evidence about the class fitted now**, in either
direction: it does not condemn 0.15 / 0.15, which was never measured, and it
does not excuse it.

**What replaces the measurement is that the fabricator's own floor is a
published number and `rules.check_fab_class()` runs against it on every build.**
That is a weaker guarantee than a routed board and it is the one that is
available, and saying which is which is the point of this section.

---

## What asked the question

Nothing on this board needed a fine class for five passes. `rules.py` said so in
as many words — *"the rules below are chosen to be legal at either weight ...
keeping the option costs nothing"* — and that was true, with the caveat attached
to it: *"it stops costing nothing the moment anything asks for 0.09 mm."*

The controller asked. RP2040 ships in one package, a 7 × 7 QFN-56 at 0.40 mm
pitch on 0.20 mm pads, and `rules.fan_out_class()` puts that off the bottom of
its three-rung ladder at the class that was fitted:

| condition | at 0.25 / 0.20 | why |
|---|---|---|
| a track fits on the pad's centre line | ✗ 0.20 mm allowed against a 0.25 mm track | the neighbour's copper is 0.30 mm from the centre line |
| each pin gets its own grid line | ✗ 0.40 mm pitch on a 0.50 mm grid | an escape moves at most half a pitch, so pins map onto lines in order |
| the turn to the grid clears the neighbour | ✗ 0.225 mm against 0.300 needed | the turn is ordinary track pointing at a pin 0.40 mm away |

`rules.coarsest_class_for()` solves rather than tabulates: **0.12 / 0.12 mm or
finer.** That is below JLCPCB's 0.15 mm floor for 2 oz outer copper and above its
0.09 mm one, so there is no intermediate class and the copper weight is part of
the answer.

## What decided it, and it was not an argument

Four combinations, `gen_pcb.py` end to end on the same machine and board:

| class | via rules | time | unrouted | DRC violations |
|---|---|---|---|---|
| 0.25 / 0.20, 2 oz | ring of four | 89 s | 0 | 0 |
| 0.09 / 0.09, 1 oz | ring of four | 69 s | 0 | 56 |
| 0.25 / 0.20, 2 oz | **corrected** | **454 s** | **10 (V5)** | 0 |
| 0.09 / 0.09, 1 oz | **corrected** | **89 s** | **0** | **0** |

Only the last row is a complete, DRC-clean board.

The middle two rows are the interesting ones. **The board that used to close was
closing on geometry the router had no rule for.** `route.py` carried a via's
clearance as a ring of four cells, with a derivation that is entirely correct at a
0.50 mm grid on 0.25 / 0.20 copper and was written as though it were a fact about
the geometry. `rules.via_exclusion()` asks it properly — three distances, because
a via is near three kinds of thing, each the stricter of a **copper** rule that
shrinks with the class and a **hole** rule that does not. Correcting it cost the
coarse class the 5 V rail and five times the routing time, and cost the fine class
nothing.

DRC had agreed with the old board because its two illegal cases — a via inside the
annulus 0.325 to 0.500 mm from a foreign pad, and two vias on diagonal cells
0.707 mm apart against a 0.800 mm requirement — were never *attempted* at that
grid. Latent, not absent.

## What it costs

**Current capacity, and the answer is a third of a degree.** `rules.track_current()`
puts `design.coil_budget()`'s 92.7 mA — the largest current anywhere on this
board, and the only one that is not microamps — at **0.33 °C of rise** on 0.09 mm
of 1 oz copper. That figure is 4.0 °C even if the borrowed IPC-2221 constant is
three times out, which is why it is quoted at all: the standard is paywalled and
what was read is a set of independent third-party calculators agreeing on the fit.
The conclusion survives the source being wrong by a lot, which is the same shape
as `design.controller_supply()`'s efficiency bound.

**The figure that made this look like a trade was 29 A/mm², and it was the wrong
instrument.** Current density divides by the cross-section, which carries the
current, and omits the surface area, which does the cooling — which is why
IPC-2221's exponent on area is 0.725 and not 1. It is the same failure as the
mixer's `RAIL_FILTER_ESR`: not a wrong number, a number computed without the term
that dominates.

**Margin, and this is the honest debit.** 0.25 / 0.20 was 1.7× and 1.33× the
published floor; 0.09 / 0.09 *is* the floor. What is left protecting the board is
`PITCH_MARGIN_MM` on top of the routing pitch, and DRC running against these
numbers on every build with `verify.check_rules()` holding all three files to
them.

**Not build time, which was predicted the wrong way round.** 4.7× the grid cells
runs 22 % *faster*, because the router's cost is dominated by contention — routes
that fail, probe, rip up and retry — and a finer grid has far less of it.
`rules.grid_cost()` records the measurement and the wrong prediction it replaced.

## What it buys

* **The RP2040 becomes routable**, with no fan-out escape needed anywhere — the
  pads are directly reachable at a 0.23 mm grid. `design.controller_package()`.
* **The fan-out goes dormant.** `route.Grid.escape()` was written to close four
  nets at U17's TSSOP at the old class, and at this one the TSSOP needs no escape
  either. It is not wasted — it is the mechanism the QFN would have needed at any
  class between the two, and it is what closed the board it was written for — but
  nothing on the board exercises it today. Said here rather than left to be
  discovered.
* **The 5 V rail closes**, which the coarse class could not do once the via rules
  were right.

## What reversing it would cost, and it is not the part

Worth stating exactly, because it is easy to overstate. At any coarser class the
RP2040's QFN-56 is unreachable **by this router** — and that qualifier carries the
whole meaning. `rules.route_pitch()` ties the routing grid to the fabrication
class, `grid = track + clearance + margin`, and its derivation holds only because
`route.py` permits tracks on adjacent cells:

> two tracks on adjacent cells are `pitch − track` apart, and that has to clear
> `clearance`

That is a property of this router, not of copper. A router with a grid finer than
`track + clearance`, enforcing spacing as a rule rather than through the pitch,
decouples the two — which is how commercial routers do it, and why 0.40 mm QFNs
go onto 2 oz boards routinely.

So reversing this decision costs router work in one of three forms, and the part
is the price only if all three are refused:

| | |
|---|---|
| **decouple the grid from the class** in `route_pitch()` | the general fix; it would retire the fan-out question at every class |
| **build the spreading fan** | at 0.15/0.15 only *one* of `fan_out_class()`'s three conditions fails — the jog, by 0.075 mm — and this is exactly its mechanism. At 0.25/0.20 all three fail and it is a bigger job |
| **hand-route the escape region** | against this repo's generate-don't-draw principle, and legitimate |

Nothing about the board as it stands is contingent on this: it is complete, clean
and routing in 89 s at the class that is fitted. This section exists because the
first prose written about the decision said reversing it "costs the RP2040",
which reads "this router cannot" as "cannot be done" — the same substitution the
four overturned predictions above were made of.

## ~~What is not decided here~~ — decided, and the question did not survive being asked properly

**It is decided.** DRC now enforces `rules.hole_rules()`, written into the
project as `min_hole_to_hole` and `min_hole_clearance` and held by
`verify.check_rules()` like every other rule. What the question turned out to
be is the interesting part, and the original text is below.

**The open item asked which of two numbers to take — and one of them was
JLCPCB's, on a board that goes to PCBWay.** Same fault as this whole page's
top block, one table along, and it survived the fabricator moving because a
hole rule looks like a fact about drills rather than a fact about a supplier.

PCBWay's own capabilities page, read 2026-08-19, normal-process column,
converted from mil:

| | published | KiCad's default | in force |
|---|---|---|---|
| component hole to hole | **0.406 mm** (16 mil) | 0.25 mm | **0.406**, the fabricator's |
| via to via, ⌀ ≤ 0.45 | 0.279 mm (11 mil) | 0.25 mm | — |
| hole to copper, 4 layers | 0.178 mm (7 mil) | **0.25 mm** | **0.25**, KiCad's |

**So the fabricator is stricter on one and looser on the other, and there was
never a single comparison to make.** The rule stays "the stricter of the
published figure and KiCad's own", which is only worth having now that it
points both ways. The board's 0.7 mm vias are above PCBWay's own `⌀ ≤ 0.45`
qualifier, so they are read as component holes — the reading that cannot be
wrong in the direction that matters, and 0.127 mm on a rule that does not bind.

**Neither number binds at this class**, which is what makes adopting them free.
`rules.via_exclusion()` gives a via 0.650 / 0.900 / 0.550 mm to a track, another
via and a pad's copper, and the *copper* rule sets all three. The trap the
original text names is avoided by construction rather than by refusing to
choose: **nothing here makes a violation disappear**, because the number that
moved moved the wrong way for that — 0.406 is 62 % stricter than what DRC has
been running.

> ### The original, kept
>
> **What DRC enforces for hole clearance is deliberately unchanged.** JLCPCB
> publishes *"Via Hole-to-Hole Spacing: 0.2mm"* and *"Via hole to Track:
> 0.2mm"*; KiCad's own default is 0.25 mm and is what has been in force,
> unowned, the same way `min_track_width` once sat at zero. The published
> figures are recorded in `rules.py` and the router is held to the stricter of
> the two. Declaring 0.20 would have made 49 violations disappear with no
> copper moving, which is indistinguishable from relaxing a check to make it
> pass — so designing to the fabricator's real limit is left as a separate
> decision, to be taken deliberately or not at all.
>
> Every clause of that is right except the page the numbers came from.
