# CLAUDE.md — cv-module

Rules for working in this repo. **Rules only** — findings and history belong in
the relevant module docstring and the commit message, not here. This file is
loaded into every session, so anything in it that doesn't change what you do is
costing context for nothing.

---

## The two repositories

| | |
|---|---|
| **This repo** (`cv-module`) | The per-string CV generation module. Nothing fabricated yet |
| **`../summing-mixer`** | The six-channel summing mixer. **Boards are ordered and fabricated** |

### The mixer repo is READ-ONLY

Its own documentation says "Nothing in this repo is to be modified", and the
boards physically exist.

- Never write, edit, create, delete, stage or commit anything under the mixer path.
- Never run `git` from a directory containing both repos. Siblings, never nested.
- If something there looks wrong, write it in `docs/FINDINGS.md`. Do not fix it.

### Read-only applies to the interface, not the plumbing

| copied into `toolchain/`, ours to modify | referenced at the pin via `contract/socket.py` |
|---|---|
| `sexp` `kisch` `symlib` `kicad` `kisim` | `design.py`, `source.py`, `fab/mechanical-*.json` |

The left column carries no hardware content. The right column is the interface,
and copying it would make `delta.py` compare the mixer's model against a fork of
itself.

The mixer's root is never on `sys.path`. Every byte read from it comes through
`socket.show()`, which is `git show <pin>:<path>`. `socket.check_pin()` and
`socket.check_no_mixer_imports()` enforce this; `test_verify.py` plants the
failures.

The pinned commit is in `contract/PINNED.md`. The module must mate with what was
built, not with whatever the mixer's `design.py` says now — check against the
pin, not `HEAD`.

---

## Consume the contract, do not copy it

**Import, don't retype:** `DC_BLOCK_VALUE`, `RIN`, `NEGATIVE_RAIL_DROP`,
`MEASURED["noise_floor"]`, `CHANNEL_POT_FP = CONN_FP[3]` and the `RV{n}01` pin
order, `fab/mechanical-*.json`.

**Call, don't reimplement:** `summing_stage_noise(wiper=…)`, `attenuator()`,
`attenuator_input_impedance()`, `coupling_burden()`, `output_swing()`,
`clipping_peak()`. `delta.py` expresses this module's effect as a delta against
the mixer's own model, which only works if the model is the mixer's.

If a constant won't import cleanly, put one adapter in `contract/socket.py` with
a comment naming the upstream symbol. Never a magic number inline.

---

## Design rules

1. **Do not invent values.** If it isn't in `docs/hardware-spec-v0.md` and can't
   be *derived* from it, stop and ask. §6 lists the things not to invent. A
   schematic full of plausible values is worse than an incomplete one because it
   looks finished.
2. **Every computed value carries its derivation**, not just its result.
3. **One channel completely, then replicate.**
4. **Flag anything in the spec you think is wrong.** Twelve claims in the source
   documents have been overturned so far.
5. **A borrowed constant is flagged as borrowed**, in the style
   `rules.track_current()` uses for IPC-2221. If a decision survives the constant
   being three times out, say so; if it doesn't, the constant needs a source.
6. **State the sensitivity rather than inventing the input.** Where a figure
   depends on something nobody here can know — an ambient field, a stage
   acceleration — report the level at which it would matter and refuse to guess
   the level it is at. `return_sensitivity()` and `mounting_deflection()` are the
   pattern.

---

## The section 5 constraints

`constraints.py` computes a mechanism, a threshold and a margin for each;
`docs/constraints.md` is its output. Run it before treating any of these as
settled. **Thin margin means load-bearing and `verify.py` must hold it. Sixty dB
of margin means good practice — do it, don't defend it.**

Numbered as `hardware-spec-v0.md` §5 numbers them, which is also how `verify.py`
prints them and how every `constraint N` reference in `design.py` reads.

**Load-bearing — `verify.py` tests these:**

- **§5.2 — exactly one bond** between module audio ground and board AGND. `R901`.
  Binary: either there is one bridge or there is not.
- **§5.1 — no mixer rail net in this module's netlist.** The module's supply is
  isolated, so this is free to honour. Margin ~100×.
- **§5.4 — `PIN{n}` presents 5–10 kΩ**, keeping the DC-block corner inside the
  15.9–31.8 Hz the fabricated design sweeps. This module presents 10 kΩ = 15.9 Hz.
  Mechanism is the mixer's own `coupling_burden()`.
- **§5.3 — `SIN{n}` puts no more DC through the master pot's wiper than the mixer
  already does.** The servo gives 0.5 mV → 3.0 nA at the wiper, against the
  0.2–1.0 nA the mixer accepts from `U1B`'s own offset. This is a comparison
  against the design we plug into, not an absolute limit — no threshold for
  "audibly noisy wiper" is sourced anywhere in this project.

**Good practice, not load-bearing:**

- **§5.5 — audio as twisted pairs inside individual shields**, shields grounded
  at the main-board end only. 59 dB of margin. If you re-derive it, note that
  `PIN{n}` is 8 Ω at 20 kHz, not 10 kΩ — using 10 kΩ gives −51 dB and wrongly
  fails the −54 dB requirement.

**Struck — do not reinstate:**

- **§5.2's second sentence**, six separate returns to six pin-3s. No mechanism;
  49 dB of margin over the requirement. The front end is a two-resistor inverting
  stage because of this; `design.FRONT_R` carries the arithmetic.
- **§4.1's 2-bit coarse pad**, 0/−6/−12/−18 dB on latching relays. Worth
  **0.000 dB** of system noise at every noise floor in the declared range —
  `design.pad_benefit()` and `delta.pad_system_delta()`. The control port reaches
  the same level for no parts.

---

## The board is not regenerated

> **The netlist is generated and authoritative. The board is not regenerated —
> it is edited, and verified by reading it back.**

`build.sh` never writes the board. Three files do, none of them in the pipeline:

- **`gen_pcb.py --discard-routing`** — places, pours and stitches, and destroys
  all signal copper. How you start from nothing; never how you make a change.
  `gen_pcb_guard.refuse_to_discard_routing()` refuses without the flag.
- **`krt.py`** — routes with KiCadRoutingTools. Writes a candidate; only
  `--commit` touches the tracked board. Scope decides what it destroys: `--nets
  "ENVA*"` re-lays those six, a bare `krt.py` re-lays every net.
- **`returns.py`** — adds ground stitches only, so it cannot destroy anything.
  **Re-run it after any re-route.** `mounts.py` and `silk.py` are the same shape.

**To move a netlist change onto the routed board**, use KiCad's **Tools → Update
PCB from Schematic** against `out/cv-module.kicad_sch`. That is the only sync path.

`verify.py` asks every one of its questions *of the board*, by reading it back,
so none of them cares who drew the copper.

### `krt.py`'s defaults would wreck this board

Pointed at it unconfigured, KiCadRoutingTools laid 4106 mm of signal track
through both ground planes — legal copper, and its own DRC, connectivity check
and improvement gate all reported success. `krt.py` generates the four things it
must be told from the files that own each number: the poured layers, the
fabrication floor, the keep-out rectangles, and a `gen_project.py` run afterwards
(the tool otherwise rewrites the project to looser floors and moves this repo's
own DRC goalposts). `krt.check_planes_intact()` is the instrument.

`docs/routing-tool.md` is the record. Recommendation for future runs: **re-route
a region, not the board.**

---

## Ratchets

Declared numbers that go **down** freely and **up only with the nets or parts
named**. They are in `verify.py` and `constraints.py` and planted in
`test_verify.py`:

`UNROUTED_ITEMS`, `MOUNTING_HOLES`, `SILK_UNLABELLED`, `AUDIO_OFF_MAGND_MM`,
`AUDIO_RETURN_AREA_MM2`, `DIGITAL_AUDIO_MM`, `CROSSING_RETURN_MM`.

---

## Layout and geometry rules

- **The isolation barrier is a place, not a net name.** The primary side —
  `design.PRIMARY_NETS` — lives west of `placement.ISOLATION_X`, between
  `ISOLATION_Y` and `placement.isolation_south()`, with no ground pour under it.
  `C810` is the one declared bridge, in `design.ISOLATION_BRIDGE`.
  `verify.check_isolation_gap()` measures the region, not a clearance.
- **There is a second barrier**, MIDI's opto-isolation. `floorplan.BARRIERS` is a
  table and `check_isolation()` runs once per entry.
- **`In1.Cu` and `In2.Cu` carry MAGND north of the split and MDGND south of it**,
  so every via changes reference plane. `returns.py` is what keeps the transfer
  loop small.
- **When a clearance will be judged by DRC, take it from the land pattern, not
  from the hardware.** `MOUNTING_KEEPOUT_MM` is KiCad's 6.9 mm courtyard, not an
  M3 washer's 6.5.
- **Positions are results, not literals.** `pack_east()`, `clear_south()`,
  `mounting_holes()` and `silk.py`'s placer all walk until clear, so a position
  can say why it is where it is. `check_courtyard_gap()` is at zero.

---

## Toolchain

**Follow `../summing-mixer`. No SKiDL. No third-party packages** — stdlib only,
which is what lets the verification loop run anywhere KiCad runs.

| | how |
|---|---|
| netlist and schematic | s-expressions written directly; `toolchain/sexp.py` is a tokeniser, parser and pretty printer |
| board | the deprecated SWIG `pcbnew` bindings, under KiCad's own interpreter |

**Do synthesise a `.kicad_sch`.** `verify.py` reads it back through `kicad-cli`
and compares KiCad's netlist to `design.py` net by net. That loop is what catches
a wire that missed its endpoint, and it is not available any other way.

`gen_pcb.py` relaunches itself under KiCad's bundled Python, then re-runs
`gen_project.py` — `SaveBoard()` rewrites the project with KiCad's defaults and
takes every design rule with it.

**`krt.py` is the one thing here that is not stdlib-only**, which is why it is a
subprocess. It needs its own interpreter: `~/code/KiCadRoutingTools/krt-venv` or
`$KRT_PYTHON`.

`toolchain/PROVENANCE.md` records what was copied and what was changed. There is
deliberately no check that `toolchain/` still matches upstream — such a check
would put the dependency back.

**If you believe a better approach exists, say so before writing code.**

---

## What this repo is for

The most valuable output is not a drawn schematic. It is: derived values with
their arithmetic, a netlist machine-checked against the constraints,
`verify.py` with `test_verify.py` proving its checks can fail, `constraints.py`
proving the constraints have mechanisms, the floorplan and ground strategy, and
an honest `docs/ASSUMPTIONS.md`.

**`test_verify.py` is not optional.** A green check proves nothing on its own —
the failure this project keeps finding is a check that passes and covers less
than its name. That file mutates the netlist and the board into each fault the
constraints exist to prevent and fails if any check does not notice. It also
guards its own mutations: a plant that changes nothing reports DEAD rather than
"caught".

---

## Layout of this repo

Everything in `out/` is generated. `docs/` is mixed — the four marked
`[generated]` are never to be hand-edited. Everything else is source. **If a file
is on the right of an arrow below, something generates it and an edit is lost.**

```
cv-module/
  README.md   CLAUDE.md   build.sh

  docs/
    hardware-spec-v0.md   authoritative spec — read first
    00-current-state.md   why the choices are what they are
    STYLE.md              the mixer's conventions
    ssi2164-control-port.md, element-revisit.md, supply-decision.md,
    fabrication-class.md, controller.md, routing-tool.md, return-vias.md,
    footprint-audit.md    topic records
    bench.md              what is left to measure, and what each reading decides
    FINDINGS.md           anything wrong in the mixer repo — noted, never fixed
    ASSUMPTIONS.md        everything guessed                     [generated]
    constraints.md        does each constraint have a mechanism? [generated]
    floorplan.md          zones, domains, boundary crossings     [generated]
    rules.md              the fab class, and what it decides     [generated]
    SHOPPING.md           what to buy and from where             [generated]
    cv-module-*.pdf/.png  the sheet, the layers, the render      [generated]

  contract/     PINNED.md, socket.py — the only place upstream is adapted
  toolchain/    KiCad plumbing copied from the mixer. Ours. PROVENANCE.md

  design.py         values, derivations, the netlist, the symbol patch
  constraints.py    -> docs/constraints.md
  delta.py          this module's effect, via the mixer's own functions
  floorplan.py      -> docs/floorplan.md
  rules.py          -> docs/rules.md. First in dependency order, last in the run
  placement.py      the floorplan as coordinates. No KiCad import
  krt.py            drives KiCadRoutingTools. --commit writes
  returns.py        return-via stitching. Adds only. --commit writes
  mounts.py         the six fixings, with a rule area each. --commit writes
  silk.py           the silkscreen, generated from the netlist. --commit writes
  verify.py         the constraints, checked against KiCad's own netlist
  test_verify.py    plants faults to prove verify.py's checks can fail

  gen_pcb.py        -> out/cv-module.kicad_pcb. DESTROYS SIGNAL COPPER
  gen_netlist.py    -> out/cv-module.net
  gen_sch.py        -> out/cv-module.kicad_sch
  gen_project.py    -> out/cv-module.kicad_pro, lib tables, cv.kicad_sym, cv.pretty
  gen_bom.py        -> out/cv-module-bom.csv, docs/SHOPPING.md
  gen_plots.py      -> docs/cv-module-{schematic,layout}.pdf, -top.png
  gen_fab.py        -> fab/ — gerbers, drill, job file, CPL, ORDER.md
  gen_assumptions.py -> docs/ASSUMPTIONS.md

  fab/   what a fabricator is given. Tracked as loose text; *.zip is ignored
  out/   for machines: sheet, board, project, netlist, BOM, and the
         from-kicad-* files verify.py regenerates on every run
```

Run it with `./build.sh`. That is the only copy of the run order.

Two ordering facts worth not rediscovering: the schematic generators come before
`verify.py` because it reads the sheet back through `kicad-cli`; and
`gen_plots.py --verify` is a mode rather than a stage, because after
`gen_plots.py` it would compare files against themselves and before it, on a
board that legitimately changed, it would fail for the expected reason and get
switched off.
