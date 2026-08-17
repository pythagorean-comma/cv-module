# FINDINGS.md — things wrong in the summing-mixer repo

**Noted here, never fixed there.** That repo's boards are fabricated and its own
documentation says nothing in it is to be modified. Nothing in this file has
been acted on upstream; nothing in this file should be.

Everything below is read at `contract/PINNED.md`'s commit, `4bc7ddb`, which is
the revision the boards were made from.

---

## F1 — `README.md` says nothing has been fabricated

`README.md`, "Status":

> **Nothing has been fabricated.**

The boards exist. Confirmed by Tim; the sentence is stale rather than
disputed, and is recorded because it is the sentence a reader hits first.

**Cost so far:** one round trip. It is also the reason `contract/PINNED.md`
opens by naming the commit and its provenance rather than treating "HEAD" as
self-evident — a repo that disagrees with itself about whether its hardware is
real is a repo whose HEAD cannot be assumed to be its fab revision.

**Do nothing.**

---

## F2 — the fabricated `fab/ORDER.md` specifies a reverse-log master pot

`fab/ORDER.md` at `4bc7ddb`, line 303, off-board parts table:

> | `RV1` | Bourns **91A1A-B24-T13L**, 5 kΩ log, conductive plastic | master LEVEL […] |

and `design.py` at the same commit carries the matching `MASTER_POT_MPN =
"Bourns 91A1A-B24-T13L"`.

That part number is wrong, and the mixer repo's own **uncommitted working tree**
is what establishes it. The correction sitting unstaged in `design.py` decodes
Bourns' ordering scheme:

> That combined field is the trap. (B) and (E) are linear conductive plastic,
> (D) and (G) are **CW** audio conductive plastic, and (S) and (T) are **CCW**
> audio conductive plastic. This read T13L: the right element, the right value,
> and the law running backwards down the rotation — a reverse-log volume
> control, which is a worse version of the fault the audio taper exists to fix.

So the document a builder orders from, at the revision the boards were made
from, asks for a master volume control that gets louder as it is turned down.

**What is worth more than the correction is that it is only half made.** The fix
exists in the working tree and not in any commit, which means:

- anything ordered from the fabricated revision got the wrong part;
- `contract/socket.py` here is *permanently* pinned to the wrong one, and
  demonstrably so — loading `mixer_design.MASTER_POT_MPN` returns `T13L` while
  the file on disk says `D13L`. That is the pinning mechanism working correctly
  and it is also a standing reminder that a fix which is not committed does not
  exist as far as any consumer is concerned.

**Consequence for this module: none electrically.** `RV1` is `in_bom=False`, a
panel part on flying leads off `J9`, at the far end of stage 2 — five nets away
from anything this module touches. It is recorded because the mixer's own
`MASTER_POT_MPN` comment says this line "carried the wrong part for the life of
the design and nothing here could see it", and that is still true of every
committed revision.

**Do nothing here. Worth Tim checking which part actually arrived.**

---

## F3 — the mechanical contract cannot express what plugs into a connector

`fab/mechanical-summing-mixer.json` is the interface the enclosure is designed
against, and `README.md` is explicit that `comma-enclosure` "reads the two
`fab/mechanical-*.json` contracts and nothing else from here". It publishes:

```json
"stack": { "above": 13.0, "below": 1.0, "total": 15.6, "tallest_part": "C703" }
```

and a `connectors` list giving each one's reference, value, position and
description — but **no height for anything that mates with them**.

`design.PART_HEIGHTS` knows this and says so in a comment:

> And a header's 8.65 mm says nothing about what plugs *into* it: a crimp
> housing adds 9–15 mm on top, which is more than the rest of the stack
> combined.

That number is in a comment. It is not in the contract, and the contract is all
the enclosure sees.

**This module is the third consumer and hits it immediately.** Converting
`RV101`–`RV601` from trimmers to vertical 3-pin headers keeps the *board*
envelope at 15.60 mm — `assembled_height()` returns the same figure either way,
because `C703` at 13.00 mm dominates both. But an ordinary crimp housing on
those six headers stands:

```
8.65 mm header  +  9 to 15 mm housing  =  17.65 to 23.65 mm above the board
```

against a published `stack.above` of **13.00 mm**. Between 4.65 and 10.65 mm
over, on a contract that reports itself satisfied.

**Not a fault, exactly** — nobody wrote a wrong number, and the comment predicts
the failure precisely. It is the shape the mixer repo keeps naming about itself:
*a check that is believed to cover more than it does*. `assembled_height()`
answers "how thick is this populated board", the contract publishes that answer
under `stack`, and a reader reasonably takes it to mean "how much room does this
board need" — which it does not, at any position carrying a connector.

**Do nothing upstream.** The consequence for this module is a design constraint
and it is recorded in `ASSUMPTIONS.md`: the loom to the six sockets is
**soldered directly into the holes, or right-angle**, and not a vertical header
with a crimp housing. It also means the enclosure's lid clearance cannot be
checked from anything I have — see the open item at the end.

---

# Not faults — guarantees that move to this module

Nothing in this section is wrong upstream. These are places where a property
the mixer currently gets *for free from a component* becomes a promise this
module has to keep instead, and where nothing on either side can check it.

## `SIN{n}` at 0 V DC stops being structural

`design.NET_DC` declares every `SIN{n}` at `0.0`, and `check_capacitor_polarity()`
and `check_voltage_ratings()` both lean on it. With a trimmer or a pot in the
socket that is guaranteed by the part: the wiper sits on a track whose far end
is `AGND`, so the net is DC-coupled to ground through at most 2.5 kΩ and cannot
be anywhere else.

Replace the pot with a **driven output** and the guarantee evaporates. `SIN{n}`
becomes whatever this module's I–V and servo leave there, and it faces `R{n}01`
into a virtual earth — so a millivolt of residual offset is a real current into
`SUM`, multiplied by six and landing on the master pot's wiper, which is the
exact fault the mixer's `DC_BLOCK = "cap"` decision exists to prevent.

This is constraint 3 restated with its mechanism. It is why "`SIN{n}` carries
zero DC **by construction**" is a stronger claim than a servo delivers, and
`verify.py` here has to test the construction rather than the intent.

## The wiper resistance leaves `summing_stage_noise()` for good

`summing_stage_noise()`'s docstring is careful that `n` means channels *built*,
not channels in use, because "every branch now returns to the attenuator's
track instead — 2500 Ω at worst, 0 at the ends of the travel — whether anything
is plugged in or not."

With a buffer in the socket every branch returns to a driven low impedance, so
`wiper` is 0 permanently and not merely at the ends of a travel nobody is
touching. The mixer's model already takes `wiper=0` as its default, so the
headline figure does not move — but the *reason* it does not move changes, and
the direction is the opposite of the obvious one: raising branch resistance
**lowers** output noise in that model, so removing the pot makes the summing
stage very slightly worse rather than better. Computed as a delta in
`design.py` here rather than asserted either way.

## The six level positions were built as build B

`fab/ORDER.md` at the pinned commit: *"**13. This is build B.** […] Fit six
Bourns 3299W-1-103LF 25-turn trimmers at `RV101`–`RV601`."* Confirmed by
`fab/summing-mixer-bom.csv`.

So the sockets this module needs are currently occupied by trimmers. Removing
them is sanctioned upstream and is not a modification in any structural sense —
`fab/ORDER.md` says so directly:

> And the choice is **not frozen at fabrication** — swapping a trimmer for a
> header later is rework with an iron, not a respin.

Tim has confirmed the trimmers are coming off. What arrives in their place is a
fourth build the mixer repo does not name, and this repo should: **build B, six
level positions vacated, this module in the holes.**

---

# Open, and not answerable from what is mounted here

- **`comma-enclosure` is not available.** F3's height problem can be *stated*
  from the mixer's contract but not *closed*, because how much room exists above
  `stack.above` is the enclosure's number and this session has no access to that
  repo. If a mezzanine or a loom clearance has to be sized, that repo is needed.
