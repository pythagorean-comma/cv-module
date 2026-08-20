# The controller — the block, the two gates, and the module that replaced it

Resolves `design.DEFERRED`'s last entry. **`DEFERRED` is empty.**

> **The part is a Raspberry Pi Pico now, and everything below the rule is the
> record of the bare RP2040 it replaced.** That block was drawn, placed, routed
> and DRC-clean; it is not deleted here because both gates it closed are the
> reason the module is worth what it costs, and because two of the five things
> drawing it found are still live. The module section is at the bottom of this
> page. What is superseded is marked where it is superseded, and nothing above
> the module section describes what is on the board today.

---

The part was settled a pass ago and the block was not drawn, for two reasons
that had stopped being scope statements and become arithmetic:
`controller_package()` said this router could not reach a 0.40 mm pitch at the
fabrication class then fitted, and `controller_supply()` said the 3.3 V rail
could not be made linearly out of what the converter had left. This is what
closing both of them cost, and what drawing the block then found.

---

## The two gates

| | how it closed |
|---|---|
| **the package** | Not here. The fabrication class moved to 0.09/0.09 mm on 1 oz copper, for this reason and measured against three alternatives — [`fabrication-class.md`](fabrication-class.md). At that class no pad on the QFN needs a fan-out escape at all |
| **the supply** | A **TPS560430XF**: 1.1 MHz, forced PWM, 12 V in, fixed 3.3 V out, SOT-23-6. `design.mcu_supply()` |

### What chose the switcher, and it is not the obvious property

Three things, and the first is the one that would not have been noticed:

**It has to be forced-PWM.** `design.mcu_dcdc_light_load()` computes the
boundary between continuous and discontinuous conduction for the fitted
inductor — 91 mA — against this board's *maximum* 3.3 V draw of 87. So a
pulse-frequency-modulation part would be in discontinuous conduction always,
and its switching frequency would be proportional to load: **246 kHz at this
board's idle**, under the ≥ 300 kHz rule spec §1.1 sets, and in the audio band
outright below 1.6 mA. That is the same objection `supply_beat()` records
against the RCC-topology TMR 6 — *"a frequency that wanders cannot be designed
against at all"* — arriving at a second part from the other end.

**Its frequency is a stated band.** 0.935 to 1.265 MHz, §7.7. `mcu_dcdc_beat()`
needs a band to compute with, and a typical figure is not one.

**Its datasheet states the passives.** Table 1's row for 1.1 MHz at 3.3 V gives
L = 12 µH, C_OUT = 22 µF and the divider as 51 k / 22.1 k. Nothing in the
switcher is this repo's invention, which is what §6 of the spec asks for.
`mcu_dcdc_output()` checks the divider against equation 7 rather than trusting
the table: 3.308 V, and 3.21–3.40 V at every tolerance corner against an
absolute maximum of 3.63.

**The fixed-3.3 V sibling was refused, and the reason is a reading rule.** The
TPS560430X3F is the same die with the divider inside it — two fewer parts — and
the datasheet nowhere says how to connect its FB pin. The electrical table's
*"Fixed 3.3-V output, VFB = 3.96 V"* and the recommended-conditions line *"FB 0
to 4.5 V"* only imply that FB goes to VOUT. An inferred connection on the pin
that sets a rail is not worth two resistors.

### Where its input comes from, and it is one node

`U22`'s VIN is on **VA_RAW**, ahead of `R804` — the same node `U16` takes, and
for a sharper reason. A buck draws a pulse train from its input; behind the rail
filter, that train's own IR drop lands on the rail the six audio channels share.
In front of it, the pole that exists for the converter's 75 mV<sub>pp</sub>
attenuates this one too, at twice the frequency and about 6 dB harder.
`mcu_dcdc_injection()` prices it: 39 mA rms of input ripple over C813's 17 mΩ is
841 µV on VA_RAW and **3.86 µV on VA+**, which is 97 dB below the signal as AM. *(Was 663 µV and 2.4 µV, computed at the capacitors' nominal capacitance; `design.effective_farads()` now runs the arithmetic at what they are worth at their own DC bias.)*
`verify.check_mcu_supply()` is what holds the wire, because VIN on VA+ works,
routes, passes DRC and hums.

### And the budget it closes is the tightest number on the board

| | |
|---|---|
| +Vout before this block | 35.4 mA of 250 |
| the 3.3 V load, counted off the netlist | **87.3 mA** — RP2040 52.1, flash 25, MIDI loop 5.5, pedal 3.3, opto 1.0, tap 0.33, divider 0.05 |
| its floor at the converter, by conservation of energy | 24.0 mA |
| what it costs at the assumed pessimistic 75 % | **32.1 mA**, leaving 3.3 |
| the efficiency at which it stops fitting | **68 %** |

`controller_supply()`'s earlier bound was *"any efficiency above 40 %"* and that
was computed for the MCU alone. The rail also carries the flash, the opto, the
MIDI loop and the pedal — so the floor is 23.6 mA rather than 14.3, and the
threshold is 68 %. **The bound is still one that cannot be wrong** — it is
conservation of energy divided by a headroom — and it is no longer comfortable.
`MEASURED["mcu_dcdc_efficiency"]` is the one number here that is a guess, its
range starts above the threshold, and its `when_wrong` names what to change if
the measurement disagrees: the 92.7 mA of relay coil that V5 makes linearly from
twelve volts, which is 37 % of +Vout.

---

## What drawing it found

**Five things, and three of them are corrections to numbers that were derived
while the block was deferred.**

### The GPIO count went up, and the requirement was not wrong

`controller_asks()` counted signals across J9–J13 — five headers standing in for
an off-board controller — and got 14. Those headers carried what *the rest of
the board* needed from a controller. The part also needs pins for its own
periphery: two MIDI, the tap, the pedal, and USB's VBUS sense. **19 of 30**, and
GPIO margin falls from 2.14× to 1.58×.

### The PWM row had the wrong denominator

It counted six carriers against the part's **sixteen outputs**. Spec §4.2 asks
for the six to be phase-staggered, and a PWM slice is one counter with two
outputs — so two channels on one slice cannot be staggered against each other.
Six of **eight slices**, which is 1.33× and the tightest countable row in
`controller_fit()`. `CONTROLLER_MAP` spends six different slices for exactly
this reason and `controller_slices()` is the check.

### `supply_beat()`'s harmonic search was a fact about one caller

It looked at the pump's first twenty harmonics, which is right for 580 kHz — the
12.9th — and wrong the moment `mcu_dcdc_beat()` asked it about 1.1 MHz, the
24th. It reported a 200 kHz beat where the answer is 20 kHz. The count comes
from the frequency now.

### The board has a second isolation barrier

DIN MIDI is an opto-isolated current loop, so `U21` is a second `U15` and `C836`
is a second `C810` — the declared bridge, and CA-033 requires it to be a
capacitor: *"Pin 2 of the MIDI In connector shall not have any DC path to the
receiver's ground"*. `floorplan.py` said *"the"* barrier in three places;
`BARRIERS` is a table now and `check_isolation()` is one test run twice. The
geometric half is deliberately **not** extended to it, and `check_isolation()`'s
docstring says why: the converter's barrier is a 20 V node switching across
50 pF beside the audio ground bond, and MIDI's is 0.4 pF inside a package.

### A connector at the edge is not a connector nearest the edge

`placement.outline()` puts `MARGIN` of clear board around whatever is outermost,
so a USB receptacle placed as far east as anything else is still 5 mm inside the
board — and a micro-B plug cannot reach it. Nothing in this repo could have said
so: the part is placed, routed, DRC-clean and unreachable. `EDGE_PARTS` and
`check_edge_parts()` are the instrument, and `outline()` now leaves the margin
off on the side an edge part faces — without which the check is circular, the
connector pushing the outline out by 5 mm and then failing to reach it for ever.

---

## The values, and where each came from

Everything below is quoted from a document read first-hand this session: the
RP2040 datasheet (build-date 2024-11-05), **Hardware design with RP2040**
(RP-008279-DS), the W25Q128JV datasheet (revision G), the TLP2761's (rev 10.0),
the TPS560430's (SLVSE22B), Bourns' SRN6045TA, and CA-033, the MMA/AMEI *MIDI
1.0 Electrical Specification Update*.

| | value | where |
|---|---|---|
| crystal | ABM8-272-T3, 12 MHz, CL 10 pF | §1.4.1 makes 12 MHz a *requirement* — "The USB bootloader requires a 12MHz crystal"; the part is named in minimal design §2.3.1 |
| its load capacitors | 15 pF each side | §2.3's own arithmetic: C/2 + 3 pF of board stray = 10.5 pF against a 10 pF part. `crystal_load()` |
| its drive resistor | 1 kΩ in series with XOUT | §2.3, and the same paragraph ties the value to IOVDD being 3.3 V |
| USB series termination | 27 Ω each line | Table 620, "required for USB operation" |
| decoupling | 100 nF at every supply pin, 1 µF at VREG_VIN and VREG_VOUT | §2.9. The reference design shares one between pins 48 and 49 and explains it by a two-layer board; this is four layers |
| QSPI_SS pull-up | **not fitted** | §2.2: R2 is "marked as DNF ... with this particular flash device, the external pull-up is unnecessary", and this is that flash |
| MIDI OUT | 33 Ω and 10 Ω | CA-033 Figure 1's 3.3 V column |
| MIDI IN | **390 Ω**, and it is *not* CA-033's 220 | see below |
| the opto | TLP2761 | CA-033 names PC-900V and 6N138, both 5 V parts; it also allows "other high-speed opto-isolators", and this one meets all three of its stated conditions at 3.3 V |

### The one value this repo had to choose

CA-033 draws the receiver's series resistor as 220 Ω and its pull-up as *"Value
of RD depends on opto-isolator and VRX"*. Two things follow. **RD does not exist
here at all** — the TLP2761's output is totem-pole, so there is nothing to pull
up, which is one part and one node fewer than the 6N138 the specification names.
And **RB has to be computed**, because a MIDI cable does not say what is on the
other end: this receiver may face a 5 V transmitter (220 + 220 Ω) or a 3.3 V one
(33 + 10 Ω), and those differ by a factor of ten in source resistance against an
opto whose recommended input current spans 2 to 6 mA.

**CA-033's own 220 Ω does not fail this, and the first version of this page said
it did.** That claim came from an arithmetic slip — 0.2 V for the driver's V_OL
where the RP2040's own table says 0.5 — and running the function rather than
reading it gives 4.32 to 5.51 mA at 220 Ω: inside the recommended range, with
9 % of headroom at the top and the 3.3 V transmitter sitting there.

**390 Ω centres it**: 2.66 to 3.80 mA across all four corners, 1.66× above the
threshold current at the worst and 1.58× under the ceiling at the best. The
choice is between margin that is 2.7× one way and 1.09× the other, and margin
that is balanced — and what makes the balanced one right is that neither end of
the spread is knowable here: the transmitter is somebody else's box, and V_F is
quoted at 2 mA rather than at the current the loop delivers.
`design.midi_loop()` is the arithmetic, `verify.check_midi()` computes the
current rather than comparing the value, and the planted fault is a resistor
halved by somebody worrying the LED is under-driven.

---

## What is still a firmware constraint rather than a hardware one

Three, recorded where a hardware document can see them because nothing else in
this repo will:

* **FSDRV must be toggled in software**, not by a PWM peripheral. The
  fail-safe's whole mechanism is that *any* stuck state collapses the charge
  pump; a hardware PWM output is precisely a square-wave source that survives
  the processor stopping. `CONTROLLER_MAP` puts it on a plain GPIO and says so.
* **The six PWM slices want a phase stagger**, §4.2, which is what buying six
  separate slices is for.
* **The expression pedal is calibrated at its extremes.** Pedals differ in
  element value and taper; the hardware delivers monotonic and bounded, and
  `expression_input()` shows the full-scale range that leaves — 91 % of the rail
  with a 10 kΩ pedal, 96 % with a 25 kΩ one.

---

## The hazard this block introduces, and it is not a constraint violation

**A USB cable ties this module's ground to a computer's.** DIN MIDI is
opto-isolated because CA-033 requires it, and the reason CA-033 requires it is a
ground loop between two mains-powered boxes. USB has no such isolation: the loop
closes through `R902`, `R901`, the mixer's AGND and whatever carries the mixer's
output back to the same computer.

**Constraint §5.2 still holds, and that is exactly why this is written down.**
The rule is *exactly one bond between module audio ground and board AGND*, and
there is still one — `R901`. What a USB cable adds is a path to a **third**
ground, which the constraint has nothing to say about. A rule that holds while
the thing it defends against is happening is a rule somebody will quote as
protection.

`design.usb_ground_loop()` prices it rather than mentioning it: the injected
voltage is the loop current times the bond's own 40 mΩ, so **a 1 mA installation
loop is 40 µV of 50 Hz — 11 dB under the mixer's own noise floor**, at a
frequency the ear is not forgiving about. The current is a property of the
installation and nothing here can measure it, so the function takes it as a
parameter and reports against the noise floor rather than inventing a value.

Three answers, none free, so none drawn: a USB isolator (an ADuM3160-class part
and a second isolated supply — the honest fix, and a block of its own);
unplugging it, since USB here is for firmware and configuration and DIN MIDI is
isolated by construction; or accepting it, which is what every bus-powered
USB-MIDI interface does. Recorded so the second is a decision rather than a
habit, and so the first is costed if a measurement ever says it is needed.


---

# The module

**A Raspberry Pi Pico, SC0915, on `Module:RaspberryPi_Pico_SMD_HandSolder`.**
`design.CONTROLLER`, and every value below comes from the Pico datasheet
(RP-004484) or from Richtek's DS6150A/B-05, both read first-hand this session.

## What it deletes, and what it costs

| | |
|---|---|
| **about 25 parts** | U20 and its decoupling, Y801 with R824/C832/C833, J14 with R820–R823, twelve supply capacitors, and the BOOT and SWD headers. 314 parts became 289; 201 nets became 184 |
| **the fine-pitch problem, entirely** | 0.40 mm of pin pitch became 2.54. `route.py` — a maze router with rip-up and retry, a fan-out escape and a three-way via-exclusion model — is deleted, and [`fabrication-class.md`](fabrication-class.md) is re-opened and re-decided at 0.15/0.15 on 2 oz |
| **1243 mm² of board** | against the QFN's 68. The module is 23.08 × 53.85 mm of courtyard in a band 46 mm tall, so it lies on its side and everything else in zone D2 moved west of it; the supply row moved 26 mm south and the board grew from 203 mm to 229 |
| **the 3.3 V rail** | it is made on the module by a converter this design does not choose, and that is the whole of the section below |

**Two things it does not delete, and the second is the surprise.** The RP2040
datasheet is still the authority for everything the *chip* does —
`CONTROLLER_GPIO_FUNCTIONS` is unchanged, and so is every current figure in
`CONTROLLER_USE_CASES`. And the crystal is the same part: RP2040 §1.4.1 makes
12 MHz a requirement, minimal design §2.3.1 names the ABM8-272-T3, and Pico §1
says the module fits one. Arriving at the vendor's answer independently and
then buying the vendor's module is pleasant and is not evidence of anything —
both readings came from the same document.

## The supply, and the cheap topology is refused

**`design.pico_backdrive()` is the record and the answer is no.** The cheap
arrangement is to leave U22 exactly as drawn, take its 3.3 V straight to the
module's pin 36, and hold `3V3_EN` low so the module's own converter never
runs. One conversion instead of two. **It costs 32.1 mA of +Vout where the
drawn topology costs 40 at its pessimistic corner** — so the arithmetic argues
for it and the documents decide against it.

**What the two datasheets say, and the gap between them is one condition.**

| | |
|---|---|
| Pico §2.1 | *"3V3 is the main 3.3 V supply to RP2040 and its I/O, **generated by the on-board SMPS**"*, and 3V3_EN only as *"To disable the 3.3 V (which also de-powers the RP2040), short this pin low"* |
| Pico §4.5 | enumerates every sanctioned way in — the micro-USB, VSYS *"in the range ~1.8 V to 5.5 V"*, and ORing a second source into VSYS. **Pin 36 appears in none of them** |
| RT6150, Enable | *"In shutdown mode, the converter stops switching, internal control circuitry is turned off, and the load is disconnected from the input. This also means that the output voltage can **drop below** the input voltage during shutdown."* |
| RT6150, tables | switch leakage 5 µA and 10 µA maximum, and VOUT rated −0.3 to 6 V **absolutely**, not relative to VIN |

The RT6150 comes close: it states the disconnect, it states its direction, and
it bounds what an idle output stage passes. **Every one of those is stated with
the input present** — the electrical table's header is `VIN = VOUT = 3.6V`, and
the one sentence about what the output may do in shutdown says it may drop
*below* the input. The condition this topology needs is the other one: input
absent, output held above it by somebody else. Neither document permits it and
neither forbids it.

**So it is refused, by the reading rule that refused the TPS560430X3F one block
over**: an inferred connection on the pin that sets a rail is not worth two
resistors. Here the inference is on the pin that *is* the rail, and what it
would buy is larger — which makes it more tempting, not more documented.

## The topology that is drawn, and it changes no value in the switcher

```
VA_RAW ─ U22 (TPS560430XF) ─ VMOD 5 V ─┬─ D806 ─ VSYS ─ [module: RT6150] ─ VMCU 3.3 V
                                       └─ three relay coils
```

* **VSYS, which §4.5 sanctions in one sentence.** The module's own RT6150 makes
  VMCU and brings it back out on pin 36, where this board's opto, tap pull-up,
  pedal divider and MIDI driver hang off it — 6.8 mA against the 300 mA that
  section allows on that pin;
* **`D806` is not there for its drop and the reason is sharper than the
  datasheet's.** Pico Figure 16 fits an ORing diode so that neither supply
  back-powers the other. What it prevents *here* is a path through a part: with
  no diode and a USB cable plugged into an **unpowered** board, VBUS reaches
  VSYS through the module's own D1, and from there it is on U22's output —
  where the buck's high-side body diode carries it to VA_RAW. A USB host on
  this board's twelve-volt rail, four parts deep, every one of them doing what
  it is supposed to;
* **GPIO23 must be driven high, in firmware, and it is not a signal on this
  board.** It is the RT6150's PS pin; low is the module's default and is pulse
  frequency modulation, whose rate falls with load. That is
  `mcu_dcdc_light_load()`'s objection to a PFM buck arriving at a third part
  with no suffix to buy. `design.pico_smps_beat()` is the arithmetic:
  800–1200 kHz forced, which clears the ≥ 300 kHz rule at the fundamental and
  **overlaps U22's own 935–1265 kHz band**, so those two beat through zero —
  which `supply_beat()` has already shown is not a thing to design a margin
  into.

## What the module cost the budget, and it forced a second change

**The threshold did not move and it became a threshold on a product.**
`mcu_supply()` has always stated the efficiency at which +Vout stops closing —
**67.8 %** — and with two converters in series it is 67.8 % of
`η(TPS) × η(RT6150)`. The two assumptions' pessimistic ends multiply to 0.660.
**The corner failed, by 4.6 mA of the 35.4 that were left**, and
`verify.check_supply()` said so: 254.6 mA asked of a 250 mA output.

**What closed it is the lever `MEASURED["mcu_dcdc_efficiency"].when_wrong` has
named since the QFN pass**: the 92.7 mA of relay coil that V5 was making
*linearly* from twelve volts. U22 moved from 3.3 V to 5 V — Table 1's own
1.1 MHz/5 V row, and §9.2's worked example is literally 12 V in, 5 V out,
600 mA, 1.1 MHz — and it now carries the coils as well as the module.

| | before | after |
|---|---|---|
| V5, linear from VA+ | 95 mA of +Vout | **2.2 mA of load** (the MAX6126 and the ADC's LDO) and 10 mA of the NCP1117's own quiescent |
| the controller chain | 32.1 mA | **90.2 mA**, and it carries the coils |
| **+Vout total** | **254.6 mA of 250 — over** | **212.9 mA of 250** |

**Three things that fell out, and the first is a correction:**

* **the F suffix is still load-bearing and for a different reason.** At 5 V into
  15 µH the continuous/discontinuous boundary is 88 mA and the rail carries
  160 — comfortably continuous, so the old argument ("a PFM part would be
  discontinuous *always*") has gone. What replaces it is **bypass**: the coils
  are 93 mA of that 160 and they are de-energised exactly when the fail-safe
  drops the module out of circuit, which is the state the box powers up in.
  With the coils off and the processor idle the rail is 16 mA, where a PFM part
  would run at **194 kHz — under the rule**. A narrower argument, and a worse
  state to have got it wrong in;
* **Table 1 asks for 18 µH and the SRN6045TA series does not make one.** 15 and
  22 either side. The deciding line is Table 1's own column heading: the
  inductor is ±20 %, so 18 µH means 14.4 to 21.6 — 15 is inside that band and
  22 is 0.4 µH outside it. `SRN6045TA-150M`;
* **a regulator whose quiescent current is four times its load**, which is what
  the NCP1117 is now. It is kept, and the reason is what V5 is *for*: the
  MAX6126 that the whole CV chain is measured against, and the LDO that makes
  the envelope ADC's analogue 3.3 V, sit behind a linear regulator rather than
  behind a 1.1 MHz switcher. 10 mA is 4 % of +Vout and that is the price of it.

## The pins, and one row is exactly met

`controller_fit()`'s denominators are the module's now, and the chip's numbers
are unchanged behind them:

| asked | has | |
|---|---|---|
| 18 signals on GPIO | 26 exposed of the part's 30 | 1.44× |
| **MCLK on a CLOCK GPOUT pin** | **1 of the part's 4** | **1.00×** |
| 6 PWM carriers, one slice each | 8 slices | 1.33× |
| expression pedal | 1 ADC of 3 exposed, of the part's 4 | 3.00× |

**The GPIO row fell and it did not fall because anything was simplified.** Four
of the part's thirty are wired to the module's own board functions —
`CONTROLLER_INTERNAL_GPIO` — and one of the nineteen asks went away with J14,
because VBUS sense is one of those four. So it is 18 of 26.

**The MCLK row is the one to read.** Four pins on the chip can drive
`CLOCK GPOUT` — GPIO21, 23, 24 and 25 — and three of them are internal to the
module. GPIO21 is the only pin on this board that can carry MCLK at all. It is
met, by a pin the datasheet names, and what it costs is the *option*: a future
change that wants GPIO21 wants a different clock strategy. `controller_fit()`
returns `exactly_met` beside `tightest` for that reason — the "tightest" figure
skips rows where `has == needs`, which was a fair simplification while USB was
the only such row and is not one now.

## What drawing it found

**`check_rails_are_drawn()` fired on VCORE, which is the second time that
instrument has earned its keep.** The RP2040's 1.1 V core rail was a real net
while the part was a bare QFN — made on the die, brought back out to the DVDD
pins. Inside a module it is made and consumed behind the castellations, so
there is no net, and a rail declared in `RAILS` with no net is exactly the
four-pass fault that check was written for after V3V3.

**The module's symbol types its ground pins as `power_out`**, which is
defensible for a module that brings a plane out on a castellation and put two
power outputs on MDGND against the converter's Com. It is corrected in
`design.patch_symbol()` rather than declared in `verify.ERC_ALLOWED`, and the
distinction is thin enough to be worth writing down: a declaration says
"expected residue", and this is a symbol modelling the part as a supply where
this board uses it as a load. `ERC_ALLOWED` is still empty.

**DRC found the rotation.** At 90° the module's north edge — the one its USB
overhangs — faces west, so what ended up flush with the board's east edge was
the *other* end: three underside debug pads, 0.29 mm from `Edge.Cuts` against a
0.30 mm rule. `check_edge_parts()` could not have caught it, because it asks
whether the courtyard reaches the outline and both rotations do. 270°.

**And SWD is gone, for a reason that is about the assembly rather than the
part.** J20 existed because "the other two ways in both depend on something" —
USB BOOTSEL needed a working flash and a working crystal, both of which this
board carried. The module carries them and its bootloader is in ROM, so that
argument has gone. What is left is debugging, and the module's three debug pads
are on its **underside**: reachable by reflow, not by the iron this board is
built with. The reset link stays, as a 2-way header, because the sanctioned way
into BOOTSEL is *"depower the board, then hold the BOOTSEL button down during
board power-up"* — and depowering this board means switching off a bipolar
analogue supply and waiting for it.
