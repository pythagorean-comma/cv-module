# The return-via stitching — where a signal changes reference plane

**Not generated.** A decision-and-measurement record, in the shape
`fabrication-class.md`, `routing-tool.md` and `footprint-audit.md` have: what
was measured, against which mechanism, and what was decided.

Done 2026-08-21, after the copper review and before ordering.

| | before | after |
|---|---|---|
| audio vias | 217 | 219 — SIN2 was re-routed in between |
| ground vias | 151 | **290** |
| worst separation to a ground via | 22.76 mm | **4.90 mm** |
| median separation | 7.39 mm | **1.50 mm** |
| within 2 mm | 6 of 217 | **190 of 219** |
| total plane-transfer loop area | 1990.6 mm² | **367.8 mm²** |

`constraints.return_loops()` is the measurement, `returns.py` is what moved it,
and `constraints.AUDIO_RETURN_AREA_MM2` is the ratchet — down as copper is
laid, up only with the vias named in the failure message, which is
`AUDIO_OFF_MAGND_MM`'s rule one artefact along.

---

## What the question is

`In1.Cu` and `In2.Cu` carry the same two nets in the same places: MAGND north
of y = 156.44, MDGND south of y = 158.44. So **every via on this board changes
reference plane as well as signal layer**, and the return current has to
transfer from one plane to the other. The only conductor that does that is a
ground via, and the loop the current makes on the way is
`rules.plane_separation()` — 1.03 mm of core — times the distance to the
nearest one.

`gen_pcb.stitch_grounds()` is why the number was what it was, and it is not a
fault in that function. It places a via **beside every ground pad**, because
what a ground pad needs is a hole to the plane underneath it. Nothing in this
repository had ever tried to put a stitch near a *signal* via, so nothing ever
measured how far the nearest one was.

## Two answers, and only one of them is derivable

**As a return impedance it does not matter, and the arithmetic says so
plainly.** The worst loop before any of this was 22.76 mm of In1/In2 pair.
That is tens of nanohenries; at 20 kHz it is sub-milliohm, and the signal
currents on this board are microamps. Tens of nanovolts against the mixer's
144 µV floor. Nothing in the audio band is decided here, and no amount of
copper changes that.

**As a pickup loop it is not derived.** This board carries two switchers of its
own — the converter at 580 kHz and U22 at 1.1 MHz — and an emf is the loop area
times dB/dt. The field is the missing term. `constraints.board_coupling()`
solves trace against trace because both conductors are known and both are on
this board; an aggressor *field* needs the geometry of a current loop inside a
potted brick that no datasheet draws. **`ASSUMPTIONS.md` exists to stop a
number being invented for exactly this**, and the honest end of the derivation
is the sensitivity rather than an answer:

> at 580 kHz, 1990.6 mm² of loop reaches the mixer's own 144 µV floor at
> **19.9 nT** of ambient field. 367.8 mm² needs **107.4 nT** — 5.4× more.

That is arithmetic on numbers this project already owns and it claims nothing
about what the field is. `constraints.return_sensitivity()`.

## So the decision was to spend the copper rather than the derivation

Three things make that cheap, and the second was measured rather than assumed.

**Stitching is not routing.** Every via `returns.py` places goes into open
ground copper. No track already laid is disturbed, nothing has to be re-routed,
and the file cannot destroy anything — it only adds, and only what
`Space.blocker()` has cleared.

**A ground stitch is not a perforation of the reference plane, and a signal via
is.** Measured on the tracked board: a signal via sits in a **0.55 mm-radius
void in both planes** — the filler's own clearance — and a ground via sits in
solid copper with no void at all. So the 845 signal vias take **803 mm² of each
plane, 3.2 % of it**, and the 290 ground vias take none. The trade
[`routing-tool.md`](routing-tool.md) flags — *"844 router vias against the
seed's 595, every extra one a hole through both reference planes"* — is a true
statement about signal vias and **does not apply to these**. What 139 more
stitches cost is 139 more drill hits, and nothing else.

**And the count is not a budget knob.** The reach was priced before it was
chosen, by running the whole placement at six of them:

| reach | new vias | audio vias with no legal spot | median | within 2 mm |
|---|---|---|---|---|
| 1.5 mm | 130 | 71 | 1.17 mm | 158 |
| 2.0 mm | 126 | 29 | 1.50 mm | 182 |
| 2.5 mm | 124 | 12 | 1.50 mm | 158 |
| 3.0 mm | 113 | 6 | 1.70 mm | 137 |
| 4.0 mm | 88 | 0 | 2.08 mm | 105 |
| 5.0 mm | 71 | 0 | 2.30 mm | 87 |

The via count barely moves across a factor of three, because it is set by how
many audio vias are in distinct places and not by how far a stitch may reach.
What the reach actually buys is **legality room** — 71 refusals at 1.5 mm, none
at 4. So the reach is not a budget and the two columns want different values,
which is why `returns.py` runs two passes: `TIGHT_MM` first, because the loop
*is* the distance and a spot 1 mm away is worth five times one 5 mm away, and
`WIDE_MM` afterwards for the audio vias in packed copper that the first pass
could not reach. 139 vias, no refusals, worst 4.90 mm.

## SIN2, which the copper review measured and did not act on

The same review left a second finding: `SIN2` spent **33.5 mm** south of the
MAGND pour to reach a relay pad about 5 mm past it — a detour rather than a
necessity, since it ran east along y ≈ 160 for 36 mm when the analogue half was
available for all of it. `krt.py --nets "SIN2"` re-laid it at **7.6 mm**, and
`constraints.AUDIO_OFF_MAGND_MM` came down from 144.1 to **118.1**.

It cost two more stitches: the new vias are in new places, so the loop area went
to 377.1 mm² and a second run of `returns.py` took it back to 367.8. That is
worth stating as a property rather than an annoyance — **`returns.py` is
incremental**, it adds only what the board is now short of, so it is the right
thing to run after any re-route.

## Four things this found, and none of them was about a return path

Each is the same shape and it is this repository's oldest one: **a property
inferred from something next to it, where the artefact could have been asked.**

**A regex that found 151 of 994 vias.** The first reader was modelled on
`constraints._raw_segments()`, which is exact for segments — and KiCad writes a
`(tenting ...)` field on a via that came from KiCadRoutingTools and none on a
via that came from `gen_pcb.py`. So the pattern matched precisely the vias this
repository wrote and none of the ones it did not. **The giveaway was that the
audio count came back zero**, which is the failure mode this repo collects: a
probe that reports nothing found. `constraints._vias()` goes through the parser.

**76 of the 151 existing stitches were rejected by their own pour.** KiCad
flattens a polygon-with-holes into a single ring by cutting a zero-width channel
out to each hole, so a distance-to-boundary query answers 0.038 mm for a via
sitting in the middle of solid copper. A slit is exactly a pair of coincident
opposed edges, so `Pour.__init__` removes them exactly rather than by a
tolerance — 1214 of them on the MAGND fill.

**Every rotated footprint's pads were mirrored through their own centre.** The
board's y axis points down, so a `+90` footprint turns its pads the other way
round from the textbook matrix; and the pad's own `at` angle is **absolute**,
not added to the footprint's. Both wrong at once put `K803`'s PIN6 pad where its
SIN5 pad is and transposed every 0805's box, 0.7 mm for 0.5125 — small enough to
look right and *exactly the size of the clearances being checked*. **KiCad's DRC
found it**, by naming a pad this file thought was 2.5 mm away; it was confirmed
against a track endpoint, which is an absolute coordinate and needs no
convention at all. `returns.read()` now validates itself: `check_pad_geometry()` reports
**819 pads with same-net copper landing inside them and six without**, and the
six are through-hole pads a plane connects rather than a track.

**And 135 vias were written inside a footprint.** `commit()` inserted them
before the first `"\t(zone\n"` in the file — which is a substring of
`"\t\t(zone\n"`, so the first match is one of the Pico's own keep-out zones,
60,000 lines above the first top-level one. The board still parsed and KiCad
would still have opened it. **The only thing that said so is that `returns.py`
measures the board back after writing it** and got the number it started with;
that comparison is now a check that raises.

## What is still open

**Whether 4.90 mm is close enough is not answered here and cannot be**, for the
reason the sensitivity section gives: the aggressor field is not derived. What
is answered is that the copper cost nothing but drill hits and that the figure
is now instrumented, so it cannot drift back in silence.

**The 29 audio vias still outside 2 mm** are in packed copper. Each is named in
`constraints.return_loops()["rows"]`, worst first, and the cheapest way to move
any of them is `krt.py --nets` on that net followed by another `returns.py` run
— not a hand edit.
