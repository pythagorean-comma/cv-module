# cv-module

Per-string CV generation for a six-string guitar effects box: six analogue VCAs
(SSI2164) set per-string levels, and the audio never enters the digital domain.

The module hangs off the six `RV{n}01` level-control positions of
[`summing-mixer`](../summing-mixer), replacing its per-channel trimmers. That
board is **fabricated**, so this repo consumes its interface at a pinned commit
and never writes to it — see [`contract/PINNED.md`](contract/PINNED.md).

```
6 x Nu capsule -> Nexus-GK -> summing-mixer ---- RV{n}01 socket ---- [this]
                                    ^                                  |
                                    +------------ SIN{n} --------------+
```

## Status

Green end to end. `verify.py` passes, `test_verify.py` catches all 112 planted
faults, DRC is at zero, no net is unrouted, and the fabrication package is
written.

| | |
|---|---|
| netlist | 290 parts, 185 nets, 825 pin connections |
| schematic | 0 merges, 0 breaks, 0 stranded pins; ERC clean, `ERC_ALLOWED` empty |
| board | 106.9 × 233.5 mm, 4 layers. 5114 segments, 1142 vias, one track width (0.2 mm), one via size (0.7/0.3), no signal copper on either reference plane |
| routing | every millimetre by KiCadRoutingTools via `krt.py` |
| section 5 constraints | checked mechanically; see `docs/constraints.md` |
| fixings | six, derived from `placement.mounting_deflection()`, each in a plane void |
| silkscreen | title block, connector legend generated from the netlist, 274 designators |
| fabrication package | `fab/` — 9 gerbers, drill, job file, CPL, `ORDER.md` |
| deferred blocks | none. `design.DEFERRED` and `design.UNSPECIFIED` are both empty |

Documents to look at: the [schematic](docs/cv-module-schematic.pdf), the
[layout](docs/cv-module-layout.pdf) one page per copper layer, and a
[render](docs/cv-module-top.png).

**Caveats worth knowing before ordering.** One capacitor is genuinely short on DC
bias — `C840` gives 1.65 µF at 12 V against TI's "2.2 µF or higher" and wants a
higher-voltage part in the same 1210 land. Three Murata lines have no bias curve
here and are reported unchecked. And no check in this repo opens a datasheet: the
netlist comparison is pad number against pin number, so a wrong package passes
everything — see [`footprint-audit.md`](docs/footprint-audit.md), which caught
three.

## Run it

Nothing to install. Stdlib only, following the mixer's own rule that "there is
no `requirements.txt` because there is nothing to install". KiCad 10 is not
optional: `verify.py` runs `kicad-cli` twice, `gen_pcb.py` needs its bundled
Python for `pcbnew`, and `gen_plots.py` plots the schematic, layout and render.

```bash
./build.sh
```

Regenerates the netlist, schematic, project, BOM, generated docs, plots and the
fabrication package, then verifies the board on disk. It never writes the board.
It checks for KiCad first and stops if it is missing; it does not check for
KiCadRoutingTools, because `krt.py` is not one of its stages.

### The three things that do write the board

None of these is in `build.sh`:

```bash
python3 gen_pcb.py --discard-routing   # place, pour and stitch, from nothing
python3 krt.py                         # route it; --commit keeps the result
python3 returns.py                     # add ground stitches; --commit writes
```

`gen_pcb.py` destroys all signal copper. It writes a fresh board with the
footprints placed and the planes poured and nothing else — use it to start again
from nothing, never to make a change. It refuses without `--discard-routing`.

`krt.py` writes a candidate, `out/cv-module-krt.kicad_pcb`; only `--commit`
touches the tracked board. Scope decides what it destroys: `--nets "ENVA*"`
re-lays those six and leaves the rest alone, a bare `python3 krt.py` re-lays
every net.

`returns.py` only adds ground stitches, so it cannot destroy anything. Re-run it
after any re-route. `mounts.py` and `silk.py` are the same shape.

**To move a netlist change onto the routed board**, use KiCad's **Tools → Update
PCB from Schematic** against `out/cv-module.kicad_sch`, which `build.sh`
regenerates. That is the only sync path.

### Toolchain notes

`krt.py` is the one thing here that is not stdlib-only, and it is a subprocess
for that reason — the tool needs numpy, scipy and shapely. Give it an interpreter
of its own, `~/code/KiCadRoutingTools/krt-venv` or `$KRT_PYTHON`; it refuses with
instructions if it cannot find one. See
[`routing-tool.md`](docs/routing-tool.md#installing-the-tools-dependencies).

`gen_pcb.py` re-runs itself under KiCad's bundled interpreter, because `pcbnew`
is a SWIG extension that exists nowhere else, then re-runs `gen_project.py` —
`SaveBoard()` rewrites the project file with KiCad's defaults and takes every
design rule with it.

`contract/socket.py` finds the mixer at `$SUMMING_MIXER`, then
`../summing-mixer`, then `~/code/summing-mixer`. **Keep the two as siblings,
never nested** — and never run `git` from a directory containing both.

## What this repo takes from the mixer, and what it does not

The mixer is a fabricated hardware interface this module references. Referencing
an interface does not mean importing another project's Python:

| | |
|---|---|
| **the interface** — `design.py`, `source.py`, `fab/mechanical-*.json` | read at the pinned commit through `contract/socket.py`, with `git show`. Never copied |
| **the KiCad plumbing** — `sexp` `kisch` `symlib` `kicad` `kisim` | copied into [`toolchain/`](toolchain/PROVENANCE.md). Ours, and modifiable |

The mixer's root is never on `sys.path`. `delta.py` expresses this module's
effect as a delta against the mixer's *own* model, which only works while that
model is the mixer's and not a fork of it.

## What is where

`CLAUDE.md` carries the working rules and the full repo layout. In short:
`design.py` holds the values, derivations and netlist; `verify.py` checks them
against KiCad's own export and `test_verify.py` proves those checks can fail;
`constraints.py` and `delta.py` ask whether the constraints have mechanisms and
what this module costs the existing design; `placement.py`, `krt.py`,
`returns.py`, `mounts.py` and `silk.py` are the board. `docs/` is what a person
reads; `out/` is what another tool reads; `fab/` is what a fabricator is given.

## Open

1. **`MEASURED["noise_floor"]`** — a meter on the mixer's mono output, and the
   only one of the three measurements that can be taken before this board
   exists. It is the most load-bearing unknown here: across its declared range
   the module costs **0.01 dB or 0.79 dB quiescent, 0.08 dB or 3.13 dB while the
   lead feature runs**. It also gates a component value — below 81 µV, `R_IN`
   should move from 12k1 to 7.5 kΩ. [`bench.md`](docs/bench.md).

2. **`MEASURED["mcu_dcdc_efficiency"]` and `["pico_smps_efficiency"]`** — two
   ammeters after fabrication. Confirmations rather than gates: floors of 53 %
   and 45 % against declared ranges starting at 75 and 86. Note that the board
   has no provision for the first — `VA_RAW` has no series element at U22's VIN,
   so that measurement needs a lifted pin or a fitted 0 Ω link. The second is
   free: `D806` is already in series with `VSYS`.

3. **The order form.** `fab/ORDER.md` lists what is not derivable from anything
   here: surface finish, mask and silkscreen colour, electrical test,
   panelisation, IPC class, quantity.

4. **Fiducials and test pads** — not fitted. Three fiducials are derived and
   costed; the test-point case is that no analogue rail and not `MAGND` itself
   has any probe point on the board.

5. **The south-east corner** is 57 mm from its nearest fixing and carries the
   USB socket. Grow the board, move the module, or accept it — all three are
   decisions, so `placement.mounting_reach()` reports the distance rather than
   taking one.

6. **Review the copper.** 844 router vias against an earlier seed's 595 is 33 %
   more perforations of both reference planes for 9.8 % less track. No check
   grades that trade. The recommendation is about scope: re-route a region, not
   the board.
