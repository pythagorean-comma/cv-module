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

**A spike, and an honest one.** All seven tasks of the brief are complete. Every
number carries its arithmetic, every check can be shown to fail, and everything
guessed is in [`ASSUMPTIONS.md`](ASSUMPTIONS.md).

| | |
|---|---|
| one channel derived | ✅ every value, arithmetic inline |
| netlist | ✅ 189 parts, 137 nets, all pins resolved |
| section 5 constraints | ✅ checked mechanically, 14 planted faults caught |
| deltas against the mixer's own model | ✅ three results contradict `00-current-state.md` |
| floorplan, BOM, assumptions | ✅ |
| schematic | ⚠️ **draws, 0 merges, 45 breaks** — see below |
| board | ❌ not started |

Six shared blocks are deferred with reasons in `design.DEFERRED`: controller,
envelope ADC, envelope rectifier, relay drive, fail-safe and supply. The scope
statement put shared blocks after one channel was complete. It is.

## Run it

Nothing to install. Stdlib only, following the mixer's own rule that "there is
no `requirements.txt` because there is nothing to install". KiCad 10 is needed
only to re-parse the schematic.

```bash
python3 design.py && python3 gen_netlist.py && python3 verify.py \
  && python3 test_verify.py && python3 constraints.py && python3 delta.py \
  && python3 floorplan.py && python3 gen_bom.py && python3 gen_assumptions.py \
  && python3 gen_sch.py
```

`contract/socket.py` finds the mixer at `$SUMMING_MIXER`, then
`../summing-mixer`, then `~/code/summing-mixer`. **Keep the two as siblings,
never nested** — and never run `git` from a directory containing both.

## What is where

| | |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | the rules, including which "load-bearing constraints" actually are |
| [`STYLE.md`](STYLE.md) | the mixer's conventions, read off its source and followed |
| [`ssi2164-control-port.md`](ssi2164-control-port.md) | the datasheet read first-hand. **Six spec corrections** |
| [`contract/socket.py`](contract/socket.py) | the only place upstream constants are adapted |
| `design.py` | values, derivations and the netlist |
| `constraints.py` | does each constraint have a mechanism? One did not |
| `delta.py` | this module's effect, via the mixer's own functions |
| `verify.py` / `test_verify.py` | the constraints, and proof the checks can fail |
| [`FINDINGS.md`](FINDINGS.md) | things wrong in the mixer repo — noted, never fixed |
| [`ASSUMPTIONS.md`](ASSUMPTIONS.md) | everything guessed, with what it costs if wrong |
| `out/` | netlist, schematic, BOM, shopping list, floorplan, constraint audit |

## The three results worth knowing

**The dominant noise mechanism is additive, not multiplicative.**
`00-current-state.md` records overturning this. Referred to one string: the VCA
cells sit 84.3 dB down and the CV chain's AM sits 91.7 dB down. The original
claim was right and was overturned for a mechanism 8 dB quieter. `delta.py`.

**The "free 8 dB" from summing-resistor scaling is a wash.** It assumed source
noise independent of the source's full-scale voltage; the MAX6126's noise is
proportional to its output — 45 nV/√Hz at 2.5 V against 95 at 5 V. Scaling up
and dividing back down cancels. `ssi2164-control-port.md`.

**One of the five load-bearing constraints had no mechanism.** "Six separate
returns to six pin-3s" was generated in an earlier session, promoted into a list
headed *check these mechanically*, and then satisfied, asserted and
negative-tested by every instrument downstream — without anyone asking whether
the requirement was reachable from physics. It is not: pairwise crosstalk
through a single bond is 122 dB below one string against a −54 dB requirement.
Struck, with the arithmetic, at `design.FRONT_R`. `constraints.py`.

## Where the schematic stopped

`gen_sch.py` draws all 189 parts and KiCad 10 loads it. Its checker builds nets
from the geometry the way eeschema does and compares them to `design.py`.

**Merges are fatal and there are none.** A merge is two nets touching: the sheet
looks right, ERC passes, and the circuit is different. The first run merged 34
nets into one — an op-amp's +IN and −IN sit 5.08 mm apart in the same column, so
a 5.08 mm ground drop landed its wire *end* on −IN. Seven faults of that class
were found and fixed; the worst was discovering that **KiCad's `Device:R` is
vertical at `angle=0`**, which had put every feedback resistor back in its
amplifier's column.

**45 breaks remain** — nets `design.py` declares that the geometry does not
form, concentrated in the CV filter, servo and pad blocks. A break is a missing
wire, which the checker, ERC and a reader all notice, so it is reported and not
fatal. Fixing them is another pass of: read the coordinate the checker prints,
correct the geometry, re-run.

Closing that loop is what makes `verify.py` mean something. Today it compares
`design.py` to a netlist written from `design.py`, so it cannot catch a
transcription error. Once the schematic matches, point its reader at
`kicad-cli sch export netlist` and the comparison becomes real.

## Open, in the order worth taking

1. **The 45 schematic breaks**, above.
2. **The pad relay.** Not chosen; 52 % of the board area and about a third of
   its cost. Its *pins* are pinned to IEC 60947 contact numbering, which is a
   constraint on which relay may be fitted.
3. **`MEASURED["noise_floor"]`** — the mixer's own unmeasured figure, and this
   module's most load-bearing unknown. It decides whether the module costs
   0.11 dB or 0.85 dB quiescent, and 0.56 dB or 3.17 dB while the lead feature
   is running. `DESIGN.md` upstream calls it "the measurement worth taking".
4. **The envelope rectifier time constant** — not derivable from the spec.
5. **The shared blocks**, all six.
