# STYLE.md — the conventions this repo inherits

Written after reading `../summing-mixer/design.py` (2,900 lines) and its
`verify.py`, before generating anything here. This repo should read like a
sibling of that one. What follows is what I found, stated as rules to follow,
with the upstream example that establishes each.

---

## 1. The design file is the circuit, and prose is generated from it

`design.py` is the single source of truth. The schematic is drawn from it, the
board is placed from it, and `verify.py` reads KiCad's own netlist back and
compares it net by net. `DESIGN.md`'s tables are transcribed from a run, not
worked out in prose — `README.md` says so explicitly.

**Follow:** `design.py` here holds every value and every derivation. Markdown
quotes numbers that `design.py` printed. Never the other way round.

---

## 2. A constant is declared as a pair, and the comment carries the argument

The house form is a value string for the BOM and a number for the arithmetic:

```python
RIN = "10k 0.1%"
RIN_OHMS = 10_000.0
```

The value string is what gets ordered from — which is why
`check_voltage_ratings()` refuses a capacitor whose value states no voltage
rating, and `check_dielectrics()` refuses a ceramic over 1 uF that names no
dielectric. The float is what the model uses.

Above each pair sits a comment that is **the reasoning, not the value**. These
run to twenty and thirty lines and they earn it. `RIN`'s explains that 10k is
kept because halving it would improve the board by 3 dB and the system by
0.003 dB; `CF`'s explains why it is 100 pF and not 33; `DC_BLOCK_VALUE`'s
carries a simulated table and the conditions under which to fit 2u2 instead.

**Follow:** one value, one place, and the comment says *why that number and not
the neighbouring one*. A constant with no argument beside it is a magic number
with extra steps.

---

## 3. Corrections are recorded in place, including how the mistake survived

This is the most distinctive thing about the repo and the easiest to lose.
When a value or a claim turns out to be wrong, `design.py` does not quietly fix
it. It writes down what was believed, what is true, and — the part that
matters — *what was structurally blind to the difference*:

- `DIODE_PINS` records that `D801` was fitted backwards for the whole life of
  the design, and that `verify.py` could never have caught it because
  `verify.py` proves the board matches `design.py` and `design.py` was what was
  wrong.
- `CAP_PINS` records the same fault one part class later at `C808`, and lists
  every instrument that was blind to it: value-string comparison, ERC, DRC, and
  a SPICE model in which `C` is symmetric anyway.
- `RAIL_FILTER_ESR` records that the rejection figure printed on every build
  was 23 dB optimistic because the model omitted ESR, *"not a wrong number but
  a calculation that omits the term which dominates, asked at a frequency the
  model does not reach."*
- `C_FILM_FP` records a footprint corrected in the right direction and one size
  short, twice.

**Follow:** when this repo overturns something — and it already has, twice, in
the SSI2164 datasheet read — the note says what was believed, what is true, and
what would have had to exist to catch it. `FINDINGS.md` is for faults in the
mixer repo; corrections to *this* repo's own spec live beside the constant.

---

## 4. Derivations are runnable functions, not prose

Every number that could be recomputed, is:

```python
def clipping_peak(rf=RF_OHMS, rin=RIN_OHMS, n=CHANNELS):
    """Largest per-channel peak that still fits, with all n channels aligned."""
    return output_swing() / (n * rf / rin)
```

Docstrings carry the method in a small ASCII block (`summing_stage_noise()`
writes out the noise-gain algebra), cite the standard treatment (TI SLVA043,
Douglas Self, Henry Ott), and say where the result was corroborated
independently — `summing_stage_noise()` notes ngspice returns 34.06 nV/rtHz
against its own 34.06.

Parameters have defaults so the function states the design, and are passable so
the same function answers "what if". `rail_filter_rejection(esr=...)` exists
precisely so a candidate part can be asked about.

**Follow:** if a number appears in a document, a function here produced it.

---

## 5. Open questions are objects with a range and a consequence

Unmeasured values are not comments. They are `Assumption` instances in a
`MEASURED` dict, each carrying `value`, `units`, `low`, `high`, `question`,
`sets`, and `when_wrong`:

```python
"noise_floor": Assumption(
    value=144e-6, units="V rms", low=50e-6, high=400e-6,
    question="What is the residual noise at the mono output ...",
    sets="whether any further noise work on this box is worth doing",
    when_wrong="Near the predicted figure means ..."),
```

The class docstring is explicit that **the range matters more than the value**:
the value is a guess, the range is a claim about what the design survives.
`check_assumptions()` enforces only that each value sits inside its own
declared range — a deliberately weak check whose purpose is to catch somebody
*tightening* a range without revisiting the guess it was written around.

**Follow:** every guess this repo makes is an `Assumption`, not a number.
`ASSUMPTIONS.md` is generated from that dict.

---

## 6. Checks are `check_*()` methods that raise with the offending refs named

`Design.check()` calls fourteen of them in order. Each is one invariant. The
docstring says what real mistake it catches and — repeatedly — what *else*
would have missed it:

> *"Neither would be caught by anything else: ERC, the netlist comparison and
> DRC all pass on a board wired this way, and it works, and it hums."*
> — `check_ground_star()`

Failures raise `AssertionError` naming the parts and pointing at the constant
that explains the rule:

```python
raise AssertionError(
    f"{ref} is wired {wiring}, expected {expected} -- pin 2 is "
    f"the wiper and pin 3 is the grounded end")
```

`check_attenuators()` is the precedent named in `CLAUDE.md` and it is worth
copying exactly. It does two things: asserts each `RV{n}01`'s pin-to-net map
against a literal `expected` dict, then asserts the *membership* of the two
nets either side — `PIN{n}` carries exactly `{C{n}01, R{n}02, RV{n}01}` and
`SIN{n}` exactly `{RV{n}01, R{n}01}`. The second half is what catches "anything
extra landing between the DC block and Rin", which would move the corner
`DC_BLOCK_VALUE` computes. Its docstring enumerates three quiet failure modes
before any code appears.

`check_summing_node()` is the same shape at the other end: an exact expected
set, then a separate assertion that no part has *both* pins on the node.

**Follow:** `verify.py` here holds one `check_*()` per constraint in §5, each
naming the failure it exists for and what would otherwise pass.

---

## 7. Rules about physical connectivity get their own checks, twice

The invariants that no electrical tool can express are checked at both levels:

| Netlist | Geometry |
|---|---|
| `design.check_ground_star()` — one part bridges AGND/PGND | `verify.check_ground_star_on_the_board()` — the two pours' bounding boxes do not overlap, because two zones on one layer fill straight through each other and **DRC does not complain** |
| `design.check_boards()` — a net spanning both PCBs must pass through an interconnect pair | — |

`check_boards()`'s docstring names the shape of the silent mistake: *"what
ships is two PCBs with a net that has no conductor between them. ERC cannot see
it."*

**Follow:** the five §5 constraints are this kind of rule. Each wants a netlist
check and, where it is a claim about copper or wire, a geometric one too.

---

## 8. Naming

- **Refs by block, in hundreds.** Channel `n` owns `C{n}01`, `R{n}01`,
  `R{n}02`, `RV{n}01`; stage 2 is the 700s; the supply is the 800s; `R901` is
  the ground star alone. A reference says which block it belongs to.
- **Nets in caps, per channel by suffix.** `IN{n}` -> `PIN{n}` -> `SIN{n}` ->
  `SUM`. `AGND`/`PGND`, `V+`/`V-`, `VREG`, `VNEG`.
- **Footprints and part numbers are named constants**, never literals:
  `CONN_FP` is a dict by pin count, `CHANNEL_POT_FP = CONN_FP[3]`, `ORDER_CODES`
  maps value string to MPN. `check_orderable()` refuses a BOM line without one,
  because *"an assembly house substitutes on value."*
- **Private helpers lead with `_`**: `_resistor()`, `_capacitor()`,
  `_test_point()` add the part and connect both pins in one call.
- **Builder functions are the block**: `inputs()`, `channel(n)`, `summer()`,
  `level_and_output()`, `opamp()`, `supply()`, `interconnect()`.

---

## 9. Units and numbers

- SI base units in floats, named in the identifier: `_OHMS`, `_FARADS`,
  `_VOLTS`. Never a bare number whose unit is in a comment.
- Underscored thousands: `10_000.0`, `45_000.0`.
- `nV/rtHz` in ASCII throughout; `uF`, `kohm`, `mohm`. No unicode in code.
- Frequencies and corners are computed, never typed: `1.0 / (2 * math.pi * R * C)`.
- Deliberate pessimism is stated as such — `OUTPUT_SWING_MARGIN = 1.2` carries
  *"1.2 V is the pessimistic figure, used deliberately -- headroom arithmetic
  wants the bad number."*

---

## 10. Sources are read, not cited

`PUMP_RULES` exists because the ICL7660S datasheet *"was cited above for the
whole life of the design and never walked"* — and item 7 turned out to describe
the circuit by name and ask for a part that was not fitted. All seven items are
now written out with a verdict each.

The rule that follows is stated at `ORDER_CODES`: a URL in the datasheet column
is one that has been **fetched and seen to resolve**; everything else is `~`
rather than a plausible-looking link nobody followed.

**Follow:** this repo's SSI2164 work starts from the datasheet PDF, quotes its
own numbers, and records where they contradict the spec. Same rule on links.

---

## 11. Prose voice

Long comments, plain English, no exclamation. Claims are hedged exactly as far
as the evidence supports and no further — *"That is a race won, not a fault
avoided"*, *"It is not impossible, it is unsanctioned"*, *"The claim is true as
stated and it is not the argument for the design."* Where a sentence was wrong
it is marked wrong in bold rather than deleted. Tables carry the losing option
so the comparison can be re-checked.

The failure this repo names about itself, and the one to keep watching for
here: **a check that is believed to cover more than it does**, and **a source
named rather than read** — because from outside, those look identical to the
real thing.
