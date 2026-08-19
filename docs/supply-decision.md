# The module's supply — decision

Resolves `hardware-spec-v0.md` §1.1, the last genuine blocker before the schematic
spike.

---

## ⚠ The decision held. Four of the numbers under it did not

**The topology this document reaches is the topology that is drawn** — one shared
DC inlet, an isolated DC-DC, ±12 V for a small audio domain and a single-supply
rail for the rest. Nothing below is retracted. What follows is the index of what
moved once the block was actually drawn, because a document that is right about
the conclusion and wrong about the arithmetic is the harder kind to catch.

| where | what moved | the current answer |
|---|---|---|
| §1's table | *"~44 mA per rail"* for the bipolar domain, against **110 mA** drawn. The advice that would have kept it at 44 — run the CV filters and rectifiers single-supply — was written to make a *charge pump* viable, and this document's own conclusion retires the charge pump. Nobody wrote down that the constraint had been retired | `design.supply_requirement()` |
| §1's table, again | **3.10 W became 3.87 W**, and it is a mistake in method rather than in arithmetic. Summing each rail's power at its own voltage is right for what the module dissipates and wrong for what the converter delivers: V5 is made linearly from VA+, so every milliamp of it leaves the converter at twelve volts | `design.supply_fit()` |
| §2's rule | *"\|f_module − 45 kHz\| > 20 kHz, target ≥300 kHz"* — **a fundamental-only rule for a mechanism that is not.** The pump's ripple has harmonics at every n × 45 kHz, and over the chosen part's own 522–638 kHz band the 12th, 13th and 14th all fall inside it: the closest beat is **5 kHz**. No switching frequency clears every harmonic. What makes it safe is isolation and second-order smallness, not the number | `design.supply_beat()` |
| §3's cost line | *"barrier capacitance (typically 10–50 pF)"* — the part is **50 pF max**, the top of that range, and the Y-capacitor it hand-waves at is the load-bearing part of the whole block. Fitted, it returns 83 % of the common-mode current locally and leaves 1.2 mV of 580 kHz across the audio bond | `design.barrier_return()` |
| the diagram | ~~*"+3V3 MCU, ADC, reference"* — there is no 3V3 rail on the board~~ — **and that correction was itself half wrong, in the direction that mattered.** `design.RAILS` had carried `"V3V3": 3.3` since the first pass with no net of that name anywhere, so the repo held both answers at once and neither could fail: a rail with no net is invisible to every check that walks nets. The rail is real now — an MCP1700 off V5, for the envelope ADC — and `design.check_rails_are_drawn()` is the instrument that would have said so. The reference is still on V5 and the MCU is still deferred | `design.RAILS`, `design.supply_load()`, `Design.check_rails_are_drawn()` |
| §3's cost line, again | *"the Y-capacitor"* alone was never going to finish the job and `barrier_return()` said so. **The common-mode choke is fitted**: a WE-SL2 744222, 2 × 1 mH at 800 mA, immediately at J8 and ahead of every other primary part. 3.6 kΩ at 580 kHz against a 2.8 Ω loop takes the residual at the audio bond from **1.24 mV to 1.14 µV** — from 18.7 dB above the mixer's own noise floor to 42 below it, and 36 below at the choke's own −50 % tolerance | `design.barrier_return()`, `design.INLET_CHOKE` |
| §1's last line | *"op-amps at 1.8 mA/ch, OPA1644 class"* — right, and the figure this repo carried for its own arithmetic was 1.7, which matches no row of SBOS484D | `design.OPAMP_IQ_MA` |

**And one thing this document did not ask, which turned out to be the open
question:** *where* the converter goes. It says "an isolated DC-DC" without
saying which board it is on, and the repo then held both answers at once —
`floorplan.ZONES` had a zone P on this board while `design.py` described J8 as a
five-way secondary inlet fed from somewhere else. It is on this board. See
`design.supply()`.

---

**Recommendation: one shared DC inlet, an isolated DC-DC for the module, and split
the module into a small bipolar audio domain and a larger single-supply digital/CV
domain.**

Three findings drive it, and the third is decisive.

---

## 1. The negative rail is half the size you'd assume

A naive op-amp count gives ~100 mA per rail, which would have ruled out anything
quiet and simple. But **most of the module doesn't need a negative rail at all.**

Positive CV attenuates, so the CV chain is unipolar. Envelope detector outputs are
unipolar. Both can run single-supply.

| Domain | Contents | Current |
|---|---|---|
| **Bipolar** (audio path only) | 6 front-end buffers, 6 I–V converters, 6 DC servos, 2× SSI2164 | ~~**~44 mA per rail** [D]~~ **110 mA — see the index above** |
| **Single +5 V** | 6 CV filter MFB stages, 12 rectifier op-amps | ~32 mA |
| **+3V3 / +5 V** | MCU, ADC, reference, 74AHC541 | ~60 mA |

*(op-amps at 1.8 mA/ch, OPA1644 class; SSI2164 at ±6 mA typ, class AB [S])*

**Sizing the negative rail for 44 mA rather than 100 mA is what makes a quiet
solution easy.** At 100 mA a charge pump would have been out; at 44 mA it is
comfortable — a 10 Ω-class part droops 0.44 V, against 2.44 V for the 55 Ω pump
the mixer already uses [D].

Design consequence: **draw the domain boundary explicitly on the schematic.** The
temptation will be to run everything bipolar because it's simpler to think about.
Resist it — the split is what keeps the negative rail small.

---

## 2. There is already a 45 kHz charge pump in the box, and it sets a hard rule

The parent doc gives V−'s source impedance as *"55 Ω pump + 10 Ω filter"* and warns
that 20–25 kHz motor PWM *"beats with the 45 kHz pump"*. So the mixer generates its
negative rail with a switched-capacitor inverter running at ~45 kHz.

This matters more than a purist "no switchers" rule, because **a VCA is a
multiplier.** Two ripple components reaching the control port do not merely add —
they intermodulate, and the difference frequency lands in the audio band:

| Module supply frequency | Beat with 45 kHz | |
|---|---|---|
| 45 kHz | 0 Hz | **fatal** |
| 50 kHz | 5 kHz | **fatal — worst possible** |
| 65 kHz | 20 kHz | marginal |
| ≥300 kHz | ≥255 kHz | fine, and easy to filter |

**Rule: |f_module − 45 kHz| > 20 kHz, so f_module > 65 kHz; target ≥300 kHz.**

> **Corrected, and the correction is in the mechanism rather than in the
> number.** The rule is stated for the pump's fundamental and the multiplier
> does not care which harmonic it mixes with. `design.supply_beat()` computes
> it: at 580 kHz the nearest beat is 5 kHz, against the pump's 13th. The rule
> is kept — a converter at 50 kHz would still be the worst possible choice —
> but it is not what makes this safe, and the fitted part at 580 kHz satisfies
> it while landing 5 kHz from a harmonic anyway.

> **Specific trap:** the obvious cheap inverters — ICL7660S, TC1044S, MAX1044 — have
> a "boost" pin that sets the frequency to **45 kHz**. Choosing the obvious part and
> the obvious option lands you exactly on the mixer's pump frequency. If a charge
> pump is used at all, clock it externally from the MCU at a chosen frequency, or
> pick a part running ≥300 kHz.

---

## 3. Sharing a DC inlet creates a second ground bond — this decides it

The parent doc's rule is absolute: *"Exactly one bond between module audio ground
and board AGND. Six separate returns to six pin-3s, not commoned in the module."*

Six audio returns via the pin-3s is **one** bond. If the module also shares a DC
inlet non-isolated, the power ground is a **second** bond — and the two together
enclose a loop whose area is set by how the looms happen to run.

The parent doc takes this seriously with its own arithmetic: a 200 × 20 mm loop
(40 cm²) 50 mm from 1 A of switched current picks up **~160 mV** against a
35 nV/√Hz node. That figure is why the whole one-enclosure argument exists.

**An isolated DC-DC keeps the module's ground referenced only through the audio
connection, so the one-bond rule survives intact.**

The cost is honest: an isolated converter's barrier capacitance (typically
10–50 pF) passes common-mode switching current. But that is a small, bounded,
locatable problem you can attack with a Y-capacitor and placement — as opposed to
a ground loop, whose area depends on how the wiring was dressed on the day.

---

## The decision

```
   DC inlet (one, shared)
        │
        ├──────────────► mixer, unchanged (its own regulator, its own 45 kHz pump)
        │
        └──► isolated DC-DC (≥300 kHz) ──┬──► ±12 V   audio domain, ~44 mA/rail
                                          ├──► +5 V    CV + sensing
                                          └──► +3V3    MCU, ADC, reference
                     ▲
              isolation barrier: the module's ground touches the mixer
              ONLY through the six pin-3 audio returns
```

- **One inlet.** It stays a one-cable product; no mains transformer inside a box
  with a 35 nV/√Hz node (a 50 Hz magnetic field is a far worse neighbour than a
  300 kHz switcher).
- **Isolated**, so the one-bond rule holds by construction rather than by
  discipline.
- **≥300 kHz**, so it cannot beat with the mixer's pump.
- **LDOs after the DC-DC** on the ±12 V rails — an LT3042-class part on the
  positive rail feeding the reference and the CV chain is cheap insurance, since
  supply noise there becomes gain modulation.
- **Domain split enforced on the schematic**, so the negative rail stays at ~44 mA.

### Rejected

| | Why |
|---|---|
| Separate mains inlet, linear ±15 | A mains transformer's 50 Hz magnetic field is a worse aggressor in a small enclosure than any switcher, and two inlets is poor product design |
| Non-isolated shared rail | Second ground bond. Defensible if the loop is deliberately controlled, but it trades a structural guarantee for a discipline you have to maintain |
| Charge pump from the shared rail | Would work at 44 mA, but doesn't solve the ground bond, and the obvious parts land on 45 kHz |
| Drawing from `VREG` / `V+` / `V−` | Forbidden. Every mA on V− costs 65 mV through the 55 Ω pump and moves `NEGATIVE_RAIL_DROP`, `output_swing()`, `clipping_peak()` |

---

## The inlet fuse — fitted, and what closed it was a catalogue

**SCHURTER UMT 250, 1.6 A time-lag, order number 3403.0168.11**, in the live
conductor between `J8` and the choke. `design.inlet_fuse()` is the arithmetic
and `design.INLET_FUSE` carries the datasheet reading.

**Nothing about the requirement changed.** The converter's own line has read
*"Recommended Input Fuse, 24 Vin models: 1'600 mA (slow blow)"* since the part
was chosen, and `design.supply()`'s assessment — that an inlet shared with a
*fabricated* board carrying no fuse of its own wants one — has stood unopposed
for four passes. What blocked it was that no order code had been verified and
KiCad shipped no land pattern for the families that had been looked at. That
was a fact about one manufacturer's catalogue, written as though it were a
fact about the part class:

> Littelfuse's 453 Nano2 is ultra-fast rather than Slo-Blo, its 154 series is a
> 2410 body and not the 1206 this was drawn around, and KiCad ships a land
> pattern for neither of the parts that would fit.

Every clause true. **"The 1206 this was drawn around" is the giveaway** — the
search was for a footprint that fitted a shape already drawn, and there was no
board to fit it to. The row it goes in is packed by `placement.pack_east()` and
simply got longer.

**Three numbers came out of fitting it, and two were corrections:**

| | |
|---|---|
| **1.6 A, not the 1.5 A this repo had derived** | 1.5 A was reached by dividing rather than by opening a catalogue: IEC 60127 runs on an E-series and 1.5 A is not one of the eighteen this family offers. The vendor states 1.6 A for this exact converter and the series has it. **A derived value that falls between two catalogue steps is a derivation that never met a catalogue** |
| **the loop resistance gained a name** | `inlet_budget()` called its series resistance `choke_r` and built five `choke_*` keys from it. Adding the fuse made that expression right and its name wrong — `barrier_return()`'s own fault, in the function one block along. Three names now: `choke_ohms`, `fuse_ohms`, `loop_ohms` |
| **what a fuse is worth here is bounded by a part nobody has chosen** | The pre-arcing table says 1.25 × In takes at least an hour and 2 × In up to two minutes; ten times opens in 10–100 ms. A 24 V brick that current-limits at 2 A is 1.25 In and this fuse never opens. `inlet_budget()` already records that the brick is a system-level part nobody here has ordered; this is the second thing that turns on it — and it is not an argument against fitting, because the case it covers is the one where the brick gives everything it has |

It costs **73 mV** of the converter's input headroom at the pessimistic (hot)
resistance, on a loop that already spends 161 mV in the choke, leaving 2.4 V of
the 9 V minimum. `verify.check_supply()` holds the wiring: `VIN_J` reaches only
the inlet and the fuse, `VIN_F` only the fuse and the choke, and a fuse in the
return leg or bridged across its own pads is a planted fault in
`test_verify.py`.

---

## ~~Look this up before finalising~~ — looked up, and the inference held

**Done.** `contract/socket.py` reads all of it from the mixer at the pinned
commit, so these are the fabricated board's own numbers rather than inferences:

| | |
|---|---|
| `SUPPLY_RAIL` | 8.6 V |
| `VREG_VOLTS` | 9.06 V |
| `NEGATIVE_RAIL_DROP` | 0.47 V — the charge-pump sag this document inferred from *"55 Ω pump"*, and the inference was right |
| `PUMP_FREQUENCY` | 45 kHz — which is what the ≥300 kHz rule below exists to stay clear of |
| `output_swing()` | 7.40 V |
| `clipping_peak()` | 1.23 V per channel with all six aligned |

**Nothing in the decision moved.** The module's own rails are ±12 V for the audio
domain plus 5 V (`design.RAILS` also declares a 3V3 that nothing on the board
uses; the controller is deferred), from an isolated DC-DC — and that the
mixer runs on ±8.6 V rather than ±12 V does not couple, which is the point of
isolating: the two domains meet at one ground bond and at the signal, nowhere
else. `design.DEFERRED` still lists the supply, because **the topology is decided
and the part is not.**

One consequence worth carrying forward: `clipping_peak()` is the mixer's headroom,
not this module's, and it is what `delta.py` measures this module's residual DC
against.