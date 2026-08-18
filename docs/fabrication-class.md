# The fabrication class — decision

Resolves the last free choice in `rules.py`, and it stopped being free when the
controller was derived.

**Decided: 0.09 / 0.09 mm track and clearance, on 1 oz outer copper.**
`rules.COPPER_OZ`, `rules.TRACK_MM`, `rules.CLEARANCE_MM`.

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

## What is not decided here

**What DRC enforces for hole clearance is deliberately unchanged.** JLCPCB
publishes *"Via Hole-to-Hole Spacing: 0.2mm"* and *"Via hole to Track: 0.2mm"*;
KiCad's own default is 0.25 mm and is what has been in force, unowned, the same
way `min_track_width` once sat at zero. The published figures are recorded in
`rules.py` and the router is held to the stricter of the two. Declaring 0.20 would
have made 49 violations disappear with no copper moving, which is
indistinguishable from relaxing a check to make it pass — so designing to the
fabricator's real limit is left as a separate decision, to be taken deliberately
or not at all.
