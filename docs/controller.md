# The controller — the block, and the two gates that had to close first

Resolves `design.DEFERRED`'s last entry. **`DEFERRED` is empty.**

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
663 µV on VA_RAW and **2.4 µV on VA+**, which is 102 dB below the signal as AM.
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
