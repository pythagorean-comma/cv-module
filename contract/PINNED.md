# PINNED.md — the revision this module mates with

The summing mixer's boards exist in physical reality. This module must fit
**what was actually built**, not whatever `design.py` says later. So the
interface is read from one commit, named here, and `contract/socket.py` refuses
to import anything else.

---

## The commit

```
4bc7ddbae461667370aa7728d3eded31774be4ab
```

    short    4bc7ddb
    date     2026-08-14 21:57:09 +0100
    author   pythagorean-comma
    subject  A shopping list, and the difference between a substitution and an alias

Confirmed by Tim as the fabricated revision. It was `HEAD` of
`../summing-mixer` when this file was written.

`socket.py` parses the hash out of this file rather than carrying its own copy,
so this document is load-bearing and not a note. Editing the hash here changes
what the module is checked against; there is nowhere else to change it.

---

## The mixer's working tree is dirty, and that is why this file is not "HEAD"

At the time of writing, `git status` in the mixer repo reports four modified
files that are **not** in the pinned commit:

```
 M DESIGN.md
 M design.py
 M fab/ORDER.md
 M fab/SHOPPING.md
```

Reading `design.py` off the disk would therefore have read a file that no board
was made from. It happens to be harmless today — the uncommitted diff is
confined to `MASTER_POT_MPN` and `MASTER_POT_DATASHEET`, correcting a Bourns
ordering code from `T13L` (reverse-log) to `D13L` (CW audio) and repointing the
datasheet from the Long Life family to `90sers.pdf`. `RV1` is a panel part on
flying leads, `in_bom=False`, on the far side of the circuit from anything this
module touches. Not one constant consumed here moves.

That it is harmless is luck. `socket.py` reads `git show 4bc7ddb:design.py`
rather than the file on disk, so the next edit cannot drift in silently, and
asserts that every module `design.py` imports is itself unmodified at the pin —
because a clean `design.py` loaded against a dirty `kisim` would be the same
fault one level down.

---

## What is read from it

Imported, never retyped:

| Symbol | What it is |
|---|---|
| `RIN` / `RIN_OHMS` | 10 kΩ, the channel input resistor into the summing node |
| `DC_BLOCK_VALUE` / `DC_BLOCK_FARADS` | 1 µF film, whose corner moves with what we hang on `PIN{n}` |
| `NEGATIVE_RAIL_DROP` | 0.47 V, the pump's sag under the op-amp's draw |
| `MEASURED["noise_floor"]` | 144 µV rms assumed, 50–400 µV declared range |
| `CHANNEL_POT_FP` = `CONN_FP[3]` | `PinHeader_1x03_P2.54mm_Vertical` — the socket footprint |
| `CHANNEL_POT_OHMS` | 10 kΩ, the pot this module replaces |
| `CHANNELS` | 6 |
| `fab/mechanical-summing-mixer.json` | outline, mounting, tall parts, connectors |

Called, never reimplemented:

`summing_stage_noise()`, `attenuator()`, `attenuator_input_impedance()`,
`coupling_burden()`, `output_swing()`, `clipping_peak()`, `thermal()`,
`noise_budget()`, `system_budget()`.

The `RV{n}01` pin order is **derived from the pinned netlist**, not transcribed
from `check_attenuators()`. See `socket.py:channel_socket()`.

---

## Re-pinning

When the mixer is revised and new boards are made, change the hash above and
run `verify.py`. Everything that moved will fail by name. That is the entire
point of the arrangement: this repo should break loudly when its assumptions
about somebody else's fabricated hardware stop being true.
