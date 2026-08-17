# Claude Code seed prompt — CV module schematic/PCB spike

Copy the block below as the first message of the session, after seeding the repo
with `hardware-spec-v0.md` and `00-current-state.md`.

---

## Before you paste it: the toolchain reality check

**KiCad has no official Python API for schematics.** This matters more than
anything else in the prompt.

- SWIG `pcbnew` bindings are **deprecated as of KiCad 9.0**, removal planned for
  11.0 [S].
- The **IPC API** (via the `kicad-python` library) is the modern path, but it drives
  a *running* KiCad instance and its coverage is PCB-focused.
- Programmatic *schematic* creation exists only as an experimental fork; KiCad's
  lead dev has said the write API is "not yet mature enough and likely to change".

So do not ask for a `.kicad_sch` to be generated from scratch — the session will
either fail or produce something brittle. Three workable paths:

| Path | Good for |
|---|---|
| **SKiDL** — describe the circuit in Python, emit a netlist, import to `pcbnew` | **Best for this spike.** Connectivity is machine-checked and the board is real, without needing schematic drawing |
| `kiutils` / `kicad-skip` — parse and rewrite `.kicad_sch` s-expressions | Editing an existing schematic. Unofficial, brittle across versions |
| Draw the schematic by hand, Python for PCB + BOM + DRC | The pragmatic default if you want a human-readable schematic |

**The highest-value thing Claude Code can do here is not draw the schematic.** It
is: derive every component value with the arithmetic shown, emit a netlist that is
checkable, write the verification script, and produce the floorplan and ground
strategy. Schematic drawing is the cheapest part and the part the tooling is worst
at.

---

## Repo setup — standalone, with the mixer mounted read-only

Standalone is right, for a reason better than tidiness: the mixer's own
documentation says *"Nothing in this repo is to be modified"*, and a separate repo
makes that **structurally true instead of a promise you have to keep remembering.**
The boards are fabricated; the CV module is a spike that will churn. Different
lifecycles, different verify suites.

```
~/projects/
  summing-mixer/     <- existing, fabricated, READ-ONLY
  cv-module/         <- new, the session runs here
```

**Siblings, never nested.** A stray `git add -A` from a parent directory
containing both is the failure mode you are designing against.

Then in the session: `/add-dir ../summing-mixer`

**Put the read-only rule in `CLAUDE.md`, not just the opening prompt.** A schematic
session runs long; the opening prompt will be out of context by the time the
session gets confident enough to "helpfully" fix something upstream. `CLAUDE.md`
gets re-read. A drafted one is in this folder.

### Pin the fabricated revision

The boards were built from a specific commit. This module must mate with **what was
actually fabricated**, not with whatever `design.py` says six months from now.
Record the hash in `contract/PINNED.md` and check against that commit rather than
`HEAD`.

### Consume the contract, do not copy it

The enclosure repo already consumes `fab/mechanical-*.json` rather than
duplicating it. This module is a third consumer and should follow the same
pattern — import `DC_BLOCK_VALUE`, `RIN`, `CHANNEL_POT_FP`, the `RV{n}01` pin
order and the mechanical JSON, with one adapter file as the single place any of it
is touched.

Better still: **call the mixer's own model functions and show the delta.**
`summing_stage_noise(wiper=…)` exists — and replacing the pot with a buffer removes
the wiper's source resistance from that model. Showing that as a computed
before/after is far more convincing than asserting it, and it is exactly how to
test whether the noise conclusions survive.

---

## The prompt

```
Read CLAUDE.md, then hardware-spec-v0.md, then 00-current-state.md, before doing
anything. The spec is authoritative; 00-current-state.md is context for why. Where
they conflict, hardware-spec-v0.md wins.

The summing-mixer repo is mounted read-only. It is fabricated hardware and its own
docs say nothing in it is to be modified — treat that as absolute. Read it, import
from it, never write to it.

CONTEXT
This is a CV generation module for a guitar effects box. Six analogue VCAs
(SSI2164) set per-string levels; the audio never enters the digital domain. The
module sits inside an enclosure with an analogue summing node budgeted at
35 nV/sqrt(Hz), and section 5 of the spec lists constraints that are load-bearing
rather than stylistic.

TOOLCHAIN
KiCad has no official Python API for schematics, and the SWIG pcbnew bindings are
deprecated as of KiCad 9. Do not attempt to synthesise a .kicad_sch. Use SKiDL to
describe the circuit and emit a netlist; use the IPC API (kicad-python) or pcbnew
for board work. If you think a different approach is better, say so and why before
writing any code.

SCOPE OF THIS SPIKE
Design ONE channel of the analogue chain completely and correctly first — front
end, coarse pad, VCA, I-V, servo, CV filter, envelope tap. Get every value derived
and checked. Only then replicate to six and add the shared blocks (controller,
reference, ADC, relay drive, fail-safe, supply). Do not start by drawing six of
anything.

TASKS, IN ORDER
0. Read the mixer repo's design.py and verify.py and write STYLE.md here — a short
   note on the conventions you found: naming, how constants are declared, how checks
   are structured, how units and derivations are expressed. Then follow it. Look
   specifically at RV{n}01 / CHANNEL_POT_FP = CONN_FP[3] (around design.py:1195),
   check_attenuators(), fab/mechanical-*.json, and the constants DC_BLOCK_VALUE,
   RIN, NEGATIVE_RAIL_DROP and MEASURED["noise_floor"]. This repo should read like a
   sibling of that one, not like a stranger.
1. Read the SSI2164 datasheet yourself and write up the control-port structure —
   input topology, impedance, the recommended summing arrangement, and the tempco
   compensation practice. Section 2 of the spec explains why: our working figures
   came from a research pass, not a first-hand read, and half the passive values
   depend on them. Correct the spec if it is wrong.
2. List every item in section 1 (BLOCKED) and tell me what you need from me. Do not
   proceed past the point where a blocker actually blocks you — work around it and
   flag it.
3. Derive all component values for one channel. Show the arithmetic inline. The CV
   filter, the summing-resistor scaling, and the reference are ranked in the spec as
   the three things that most affect the sound; treat their values as the most
   important output of this session.
4. Emit the netlist. Write verify.py checking the netlist against section 5 —
   exactly one AGND bond, no module load on VREG/V+/V-, six separate returns to six
   pin-3s, 10 kOhm presented at each PIN{n}. Import the mixer's constants rather
   than retyping them; put every adaptation in contract/socket.py.
4b. Call the mixer's own model functions and show the delta this module makes.
   summing_stage_noise(wiper=...) is the important one: replacing the pot with a
   buffer removes the wiper source resistance from that model, and the VCA adds its
   own noise. Compute the before/after rather than asserting it. Do the same for
   attenuator_input_impedance() and coupling_burden(). If the numbers disagree with
   00-current-state.md, the numbers win and you should say so loudly.
5. Floorplan: analogue/digital boundary, ground strategy, where the SPI crossing
   happens, where the reference sits relative to the six buffer transients.
6. BOM with a source and price per line.
7. ASSUMPTIONS.md listing everything you had to guess.

RULES
- If a value or part is not in the spec and cannot be derived from it, STOP and ask.
  Do not choose something plausible. Section 6 lists the specific things not to
  invent.
- Every computed value gets its derivation, not just its result.
- Flag anything in the spec you think is wrong. Several claims in the source
  documents have already been overturned — including two by the datasheet
  contradicting a research summary — so treat the spec as fallible.
- Section 4.5 contains the highest-probability field failure in the design (latching
  relay coils held on by a level driver) and a power-on fail-loud hazard. Both need
  explicit hardware answers, not firmware promises.

FIRST OUTPUT
Before writing any code: your reading of the SSI2164 control port, your list of what
you need from me, and your proposed approach. Then stop and wait.
```

---

## Why the prompt is shaped like that

- **"One channel completely, then replicate"** — the failure mode of a six-channel
  spike is six copies of a wrong front end.
- **"Read the datasheet yourself"** as task 1 — the one substantive unknown that
  gates half the passive values, and the thing most likely to be wrong in the spec.
- **"Do not invent, stop and ask"** — a schematic full of plausible-looking values
  is worse than an incomplete one, because it looks finished.
- **"Flag anything you think is wrong"** with the reason given — the docs have a
  demonstrated error rate, and saying so licenses pushback.
- **"Stop and wait" after the first output** — cheapest possible checkpoint before
  the session commits to an approach.