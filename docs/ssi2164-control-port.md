# The SSI2164 control port, read first-hand

Spec §2 asks for this, and says why: the working figures — *"current-summing
node, nominally 10 kΩ, internal 10:1 divider, −33 mV/dB"* — came from a research
pass rather than a datasheet, and half the passive values on the board depend on
them.

**Source:** SSI2164 datasheet, **Rev 3.4, February 2023**, Sound Semiconductor,
<https://www.soundsemiconductor.com/downloads/ssi2164datasheet.pdf> — fetched,
resolves, and read to the end. Page references are to that revision. Two of its
application notes are signed: the 0–5 V control circuits on page 9 by Phillip
Gallo, and the temperature-compensated exponential converter on pages 10–11 by
Dave Rossum.

Score: **the spec is right about the divider and the constant, wrong about the
port being a current-summing node, wrong about which noise condition the
datasheet recommends, and more right than I first credited about tempco
resistors.**

---

## 1. Topology — a voltage input, not a current-summing node

Pin description, page 3:

> **3, 6, 11, 14 — V_C x — Ground-referenced control port with a −33mV-per-dB
> constant.**

Figure 4's simplified schematic shows what is behind that pin, and it is not a
virtual earth. It is a plain resistive divider to ground feeding the gain core's
bases:

```
   V_C o----[ 9k ]----+----> bases of Q3 / Q4  (gain core)
                      |
                    [ 1k ]
                      |
                     GND
```

Two consequences, and they are the whole reason this section exists.

**There is nothing to sum currents into.** A current-summing node is held at a
fixed potential by feedback and accepts as many input resistors as you like,
each contributing independently. This pin is a resistor to ground. Anything you
put in series with it forms a divider *with* it.

**The 10 kΩ is a real, tolerance-bearing load.** Page 2's specification table:

| Parameter | Min | Typ | Max | Units |
|---|---|---|---|---|
| Control port input impedance | **9** | **10** | **11** | kΩ |

±10 %, and it is an on-die resistor pair, so it carries the usual process
spread. Within one package the four channels track — page 2 gives
channel-to-channel gain matching of 0.07 dB at 0 dB and 0.24 dB at −40 dB — but
between two packages there is nothing holding them together.

The datasheet says both of these outright. Page 4:

> The control input has a nominal impedance of 10kΩ, with an internal 10:1
> resistor divider. Because of this, any resistance in series with V_C will
> attenuate the control signal somewhat. If precise control of gain and
> attenuation is required, buffering the control voltage is suggested.

and page 11, Note 2, which is the same point stated as a requirement:

> V_CTL should be accurate to 1% or better; use of a band-gap reference is
> recommended, and if resistively divided, **the source impedance kept low to
> eliminate any effect of the wide tolerance on the 10kΩ control port input
> impedance of the SSI2164.**

### What that costs the arrangement in spec §4.2

§4.2 proposes *"Source at 0–5 V through **~15 kΩ** into the 10 kΩ control node →
×0.4"*. Run the tolerance through it:

```
scale = Z / (15k + Z)

Z =  9k  ->  0.3750    -0.56 dB against nominal
Z = 10k  ->  0.4000
Z = 11k  ->  0.4231    +0.49 dB against nominal
```

±6 % on **dB per code**, package to package. That is not a level error a trim
absorbs — it is a slope error, so it grows with depth. At 40 dB of gate it is
±2.4 dB, on the one feature whose character is six strings behaving alike.

**So the scaling goes in the filter stage's own resistor ratio and the stage's
output drives V_C directly.** Same attenuation of source-referred noise, but the
ratio is two resistors chosen here instead of one resistor against an on-die
value nobody controls. §4.2 already asks for this when it lists the MFB stage's
third job as *"buffering the source from the 2164's control node"* — the spec
contains both topologies and they are mutually exclusive.

---

## 2. The constant, and the law

Page 2 and page 4:

| | |
|---|---|
| Gain constant | **−33 mV/dB** (after 60 s of operation) |
| Full range | **+20 dB to −100 dB** for V_C = **−660 mV to +3.3 V** |
| Gain accuracy | +0.30 dB at 0 dB, −0.20 at +20 dB, +0.20 at −20 dB |
| Maximum attenuation | −100 dB |
| Control feedthrough | −60 dB typical, 0 dB → −40 dB |

Polarity, page 6: *"a positive V_C attenuates the input and a negative V_C
amplifies the input. The VCA has unity gain for a control voltage of 0.0V."*

Which is exactly what this design wants — unipolar positive CV, attenuate-only,
and page 4 says so for our case specifically:

> If only attenuation is desired, the control port can be driven directly from a
> low impedance voltage-output DAC.

### The law is derived, not just quoted

Rossum's note gives the gain as equation (3), page 10:

```
G = I_OUT / I_IN = exp( -q A V_CTL / kT )        A = 0.1, the internal 9k:1k
```

so in decibels

```
dB(V_C) = (20 / ln 10) x (-q A / kT) x V_C
        = -20 x 11603 x 0.1 / (T x 2.3026)   dB/V      [q/k = 11603 K/V]
```

which at the datasheet's own nominal die temperature of 325 K (Note 1, page 11)
gives **−31.0 dB/V = −32.2 mV/dB**, against the specified −33. Agreement to 2.4 %,
and the residual is the difference between a theoretical junction and a part
measured warm. **The spec's −33 mV/dB is confirmed, and now it is also
understood** — it is not a design choice anybody made, it is q/kT and a 10:1
divider.

The multiplicative-noise figure follows from the same line and needs no
separate trust:

```
d(ln G)/dV_C = -q A / kT = -ln(10)/0.66 = -3.488 per volt
```

**§4.2's dg/g = −3.48 per volt is correct.** Referred to the source rather than
to the port, it scales by whatever gain sits between them — so the filter
stage's ratio is directly a noise figure, which is why §4.2 ranks it first of
three.

---

## 3. The recommended summing arrangement — and it is our circuit, published

This is the part the research pass missed and it matters most. Page 9 carries
**Figure 10, "0–5 V Exponential Control Circuit"**, which is a summing
arrangement for exactly our voltage range, with values:

```
  V_C-EXPO 1 o--[ 100k ]--+
                          |     +--[ 100p ]--+
  V_C-EXPO 2 o--[ 100k ]--+     |            |
                          +-----+--|-\        |
     -12 V o--[ 270k* ]---+        |  >-------+--[ 68k ]--o  to V_C
                       +--------|+/
                      GND

  * 240k is the computed value; 240k + 50k trimmer where gain must be exact
```

Gallo's text:

> Figure 10 depicts a simple method whereby an op amp sums, inverts, and
> attenuates the control signal into a negative-going 3.4V signal range
> compatible with the SSI2164. […] Ensuring 0 dB for maximum control voltage is
> achieved by summing a correction voltage which positively offsets the control
> output to ensure a 0V output for +5V input. […] **any number of control
> sources can be summed into the op amps input regardless of configuration
> type.**

The arithmetic closes:

```
gain        68k / 100k                = 0.68     ->  5 V x 0.68 = 3.40 V
offset      68k x 12 V / 240k         = 3.40 V
so          V_in = 5 V  ->  V_C = 0.00 V   unity gain
            V_in = 0 V  ->  V_C = +3.40 V  about -103 dB
```

Three things follow, and the second is the important one.

**(a) The summing happens in an op-amp, not at the port.** "Any number of
control sources can be summed" — into the *inverting node of the external
amplifier*. That is the "recommended summing arrangement" §2 asked about, and it
is not the port. This is the same conclusion §1 reached from the tolerance
argument, arrived at independently by the manufacturer.

**(b) An inverting stage with a negative-referred offset is what makes positive
V_C possible from a positive-only source.** Last session I flagged §4.2 as not
closing — inverting, one stage, unipolar positive source, and positive-attenuates
cannot all hold at once. Figure 10 is the resolution: the offset current comes
from a **negative** source, so the inverted sum lands positive. The spec's
*"offset injection (second input resistor from VREF)"* has the mechanism right
and the sign of the source wrong.

**(c) The polarity convention is the opposite of ours, and that is one line of
firmware.** Figure 10 is a modular-synth convention: 5 V in = loudest. You have
chosen code 0 = loudest. Emit the complement from the PWM and the same topology
delivers it:

```
firmware writes level D in [0,1], drives duty (1 - D)
'541 output            = (1 - D) x V_REF
inverting stage        = k x ( V_REF - (1 - D) x V_REF ) = k x V_REF x D

D = 0  ->  V_C = 0        unity gain, loudest
D = 1  ->  V_C = k V_REF  full attenuation
```

### And that deletes the power-on fail-loud hazard

§4.5 warns:

> **Power-on hazard:** a DAC's POR to zero scale = 0 V = **unity gain =
> fail-loud.** […] Same applies to PWM outputs idling low.

**That is true of a direct drive and false of this topology, and the difference
is a hardware property rather than a firmware promise.** With Figure 10's
arrangement, 0 V at the '541 output is the *full-attenuation* end:

| State at the '541 | V_C | Result |
|---|---|---|
| PWM idling low, duty 0 | +k·V_REF | **silent** |
| MCU hi-Z, inputs pulled down | +k·V_REF | **silent** |
| '541 in output hi-Z (OE high) | +k·V_REF | **silent** |
| Reference dead, V_REF = 0 | +k·V_REF (offset survives) | **silent** |

Every one of those is silent because the offset current is the only thing
reaching the summing node, and it comes from the negative source rather than
from anything the MCU or the reference controls. The hazard §4.5 asks for an
explicit hardware answer to is answered **by choosing the datasheet's own
topology**, at the cost of six pull-down resistors on the '541 inputs so that a
hi-Z MCU is a defined logic low rather than a floating CMOS gate.

The bypass relay and the AC-coupled charge pump in §4.5 stay — they cover the
audio path, not the CV — but the CV chain is now independently fail-silent,
which it was not going to be.

**One item this opens, for the value derivation:** Figure 10 draws the offset
from the −12 V rail, and Rossum's Note 3 on page 11 says not to:

> The negative voltage reference should be temperature stable to 100ppm/°C;
> while the negative power supply is used as illustration, most designs will use
> a more stable reference.

An unregulated rail's noise and drift inject straight into V_C through
R_OFFSET, multiplied by −3.488/V into AM. So the offset wants a stable negative
source, and there is no negative reference in this design yet. Three candidates
— invert the +2.5 V reference through one more amplifier, bias the filter
stage's non-inverting input from the positive reference instead (where the two
reference paths have opposite sign and partially cancel), or a dedicated
negative reference — and choosing between them is value-derivation work, not
this document's.

---

## 4. Tempco — and here I owe a correction

Last session I said the +3300 ppm/°C tempco resistor was industry practice but
*"not this datasheet's advice"*. **That was wrong, and page 10 names it
explicitly.** Rossum, on the history of the exponential generator:

> Pearlman did not deal with the q/kT term. This has been most commonly handled
> by using a resistor with a known temperature coefficient of **3300ppm/°C** as
> a gain setting element in forming V_IN. The primary disadvantage of this
> approach has become the diminishing availability of such "tempco" resistors.

So §2's *"standard +3300 ppm/°C tempco resistor practice for the control
divider"* is confirmed as standard practice, with the exact figure, and the
objection to it is **availability**, not correctness. My earlier reading was
based on Figure 2 alone and stopped four pages short.

What remains true from last session is the sign in the specification table —
page 2 gives **Gain Constant Temp. Coefficient −3300 ppm/°C** — and it is not a
contradiction. The constant is −33 mV/dB and its *magnitude* rises with absolute
temperature, so the signed value becomes more negative at 3300 ppm/°C. Page 4:

> The 33mV/dB control voltage law is essentially set by transistor physics, and
> has the property of being proportional to absolute temperature, or
> approximately 0.33%/°C. This is low enough to be unimportant in most
> applications, but can be reduced with external temperature-dependent networks.

### Three published approaches, and the arithmetic that declines all three

| | Where | Cost | Accuracy |
|---|---|---|---|
| +3300 ppm/°C resistor in the divider | page 10, named as the historical norm | 1 part/channel, poorly stocked | good |
| NTC network | **Figure 2**, page 4 — 10 kΩ @ 25 °C NTC (Vishay NTCLE100E3103JB0) ∥ 1.8 kΩ, into 3.9 kΩ to ground; also converts −50 mV/dB to −33 | 3 parts/channel, on the node that multiplies | moderate |
| A VCA channel as the q/kT element | **Figure 11**, pages 10–11 (Sowa 1999, refined by Hoshuyama and Johnson) | one gain cell + an op-amp | ±0.12 % over 10 octaves |

Now the span. Page 11, Note 1, gives the thermal model:

> The SOP16 package typical junction to ambient thermal resistance is 118°C/W,
> predicting a die temperature 17°C above ambient.

On this module's ±12 V rails at the Class AB typical 6 mA, dissipation is
24 V × 6 mA = 144 mW — the datasheet's own example figure — so the rise is
118 × 0.144 = **17 °C**. `contract/socket.py`'s inherited `AMBIENT_C` is
0–50 °C (from the mixer's own `DIELECTRICS` comment, *"a pedal never leaves
0–50 C"*), giving a die range of 290–340 K against a 25 °C-ambient reference
die temperature of 315 K.

For a gate set to −40 dB at room temperature, V_C = 40 × 0.033 = 1.32 V fixed:

```
K(T) = 33 mV/dB x T / 315 K

ambient  0 C  ->  die 290 K  ->  K = 30.4 mV/dB  ->  1.32 / 0.0304 = -43.4 dB
ambient 25 C  ->  die 315 K  ->  K = 33.0        ->                  -40.0 dB
ambient 50 C  ->  die 340 K  ->  K = 35.6        ->                  -37.1 dB
```

**6.3 dB of wander on a −40 dB gate.** And the reason to accept it:

**It is common-mode.** One die temperature, one law, six channels. The lead
feature is differential — `00-current-state.md` measures summed gain constant at
1.0500 min and max because the arpeggio opens exactly one string per step — so a
shift that moves all six identically does not disturb the thing the feature
depends on. What it moves is absolute depth, which is a knob the player is
already setting by ear, and the drone bed's floor at ~14 dB is the only place it
could bite.

Against that, compensating means putting three more components per channel on
the one node in the design where added noise is *multiplied* into the audio.
Declined, in agreement with the datasheet's own "low enough to be unimportant".

**Two conditions on that decision, both for the floorplan:**

1. The two packages must sit at the **same** temperature, or the error stops
   being common-mode and becomes a six-way matching error. Both SSI2164s
   together, away from the regulators and the DC-DC.
2. Figure 11's note that *"the two VCA channels employed should reside within
   the same component to benefit from thermal and electrical parameter
   matching"* applies to compensation schemes we are not using, but the
   underlying fact — matching is a within-die property — decides how the six
   channels are allocated across two quads. See §6.

---

## 5. Everything else the read turned up that changes a value

### R_IN / R_OUT — the spec has the noise condition backwards

§4.1 says *"R_IN 30 kΩ after the buffer (datasheet noise condition)"*. Page 2's
table, Class AB, 20 Hz–20 kHz unweighted, and note the parameter is
**R_IN/OUT** — both resistors together, at unity:

| R_IN/OUT | Class AB | Class A | ≈ density (Class AB) |
|---|---|---|---|
| 30 kΩ | −93 dBu | −81 dBu | 123 nV/√Hz |
| 20 kΩ | −96 | −84 | 87 |
| 15 kΩ | −98 | −87 | 69 |
| 7.5 kΩ | −101 | −92.5 | 49 |

and page 4:

> A 20kΩ value for R_IN is recommended for most applications, but can range from
> 7.5kΩ to 100kΩ — **lower values will produce the best noise performance at
> some cost in distortion.**

30 kΩ is the **worst** row and is a recommendation for nothing. Headroom is not
what bounds the choice either: page 4 puts maximum input current handling at
~1 mA peak and advises designing for 900 µA, and at the mixer's
`clipping_peak()` of 1.233 V pk into 7.5 kΩ the current is 164 µA — a factor of
5.5 inside the advice. **R_IN is a noise-versus-distortion choice across
7.5–20 kΩ, and it becomes an `Assumption` in `design.py` rather than a number,
because how much it matters depends entirely on `MEASURED["noise_floor"]`.**

### The conditions line above that table, read later and worth 36 parts

The read above took the four rows and stopped. The line above the whole
specification table is the one that decides the coarse pad, and it was quoted
in this document only as far as "R_IN/OUT". Verbatim, page 2:

> V_S = ±15V, V_IN = 0.775V_RMS, f = 1kHz, **A_V = 0dB**, Class AB, T_A = 25°C;
> **using Figure 1 circuit without diode**

Three things follow, and the second is the one the pad rested on:

- the parameter is **R_IN/OUT**, both resistors moved together, so the table is
  neither an R_IN sweep nor an R_OUT sweep and cannot say on its own which of
  the two the rise belongs to;
- **A_V = 0 dB** — every row is at unity, so it says nothing about noise
  against control voltage either;
- **Figure 1** is the cell plus a ½ TL072 and both resistors, so these figures
  already contain an I-V amplifier at 18 nV/√Hz.

`design.vca_cell_fit()` separates the four points into a current at the cell's
output (3.8 pA/√Hz) and a fixed voltage there (34.7 nV/√Hz), fitting all four
to 0.14 dB rms with the two Johnson terms computed rather than fitted. **The
rise belongs to R_OUT**, and the fixed term is the size of the TL072 at a noise
gain of 2 — which is a corroboration and not a proof, since an output-stage
noise inside the cell would sit in the same place and four points cannot
separate them.

That is what struck the coarse pad. A pad raises R_IN and leaves R_OUT alone,
so it moves the cell's noise by 0.2 dB in the direction of *less*; the 62 →
123 nV/√Hz it was implicitly costed against is R_OUT's and the pad never
touches it. See `design.pad_benefit()`.

**One inconsistency inside the datasheet, recorded rather than reconciled.**
Page 8's ULTRA-LOW NOISE VCA paragraph claims paralleling four channels with
R_IN/OUT divided by four improves output noise by exactly 6 dB, "−97dBu for a
single channel to −103dBu". Every term in the fit scales by 6 dB under that
transformation except the fixed one, which is the op-amp and does not move — so
a full 6 dB needs the fixed term to be negligible and the table's own curvature
needs it to be 34.7 nV/√Hz. They cannot both be exact, by about 2–3 dB. The
table is a specification and the paragraph is prose with round numbers.

### THD is specified against A_V, and it does not punish attenuation

Same conditions line, so V_IN is 0.775 V rms throughout and only A_V changes.
Class AB, 80 kHz bandwidth:

| condition | THD |
|---|---|
| A_V = 0 dB | 0.05 % |
| A_V = 0 dB, V_IN = −17 dBu | 0.025 % |
| A_V = +20 dB | 0.20 % |
| **A_V = −20 dB** | **0.045 %** |

The −20 dB row is measured with the full input still arriving at R_IN and the
cell attenuating in the control port — exactly the case a pad exists to avoid —
and it is *better* than unity. What moves distortion is **input level**, not
gain setting, which is why the second row is half the first. A pad does move
that, and it is worth 0.05 % becoming ~0.03 % on a channel that is 18 dB down
in the mix.

### MODE — the spec never mentions it, and it decides 12 dB

Page 3: *"Leave open for Class AB operation."* Page 5: *"Class AB will yield the
best noise performance which is achieved with Pin 1 left open."* Page 6, on
Class A: *"the high quiescent current level has a severe impact on noise floor
and control feedthrough rejection."* Page 11, Note 1: *"class AB mode
(recommended)"*.

Control feedthrough is the binding constraint on the gating feature, and Class
AB wins on both it and noise. **Pin 1 open, no R_M fitted, Class AB.** Derived,
not chosen — and it also makes the supply arithmetic below the low figure.

### Supply — an order of magnitude smaller than §1.1 assumed

Page 2: Class AB, V_C = GND, **±6 mA typical, ±8 mA maximum per package**. Range
±4 V to ±18 V. Two packages is ±16 mA worst case against the 60–80 mA §1.1's
original text sized a supply around. It also clears the THAT4301's ±7 V floor
from §1.4, so that bench-off is not gated on rails.

### The input RC is not optional, and there is a second capacitor that matters

Page 3, Figure 1 and its text:

> Resistor R_IN converts the input voltage to a current, and a **220Ω resistor
> in series with a 1200pF capacitor connected to ground ensures stable
> operation.** The SSI2164 is quite tolerant of RC network selection, but
> 220Ω/1200pF has been proven to work well over a wide range of R_IN values.

And page 4, one sentence that is directly load-bearing for the lead feature:

> An optional series-connected **10µF capacitor** is recommended for improved
> **control feedthrough.**

Control feedthrough is DC offset at I_IN being multiplied by the changing gain —
which arrives as a **click on every gate transition**, at ~8 steps/s, in a
feature whose entire premise is that the gating reads as timbre rather than as
rhythm. So the series capacitor at the VCA input is not a nicety, and neither is
the servo on the I–V side. Both are about the same fault seen from the two ends
of the cell, and §4.1 lists only one of them.

### Unused channels

Six channels across two quads leaves two spare. Page 5:

> If any channels of the SSI2164 are unused, inputs and outputs should be
> grounded. Control pins can be left open or grounded. Rather than put a channel
> to waste, however, the designer might consider ways to put it to use for
> additional functionality, or parallel with another channel for reduced output
> noise.

Paralleling buys 3 dB — pages 7–8, Figure 7, with R_IN/OUT and R_C divided by
the number of channels and C_C multiplied by it. **Declined, and the reason is
the feature:** paralleling two spares would make two strings 3 dB quieter than
the other four, which is a matching error introduced deliberately. Ground them.

---

## 6. Package allocation is a crosstalk decision, and 3 + 3 beats 4 + 2

Not in the spec, and it follows from what the read establishes. Crosstalk is
the binding constraint on the lead feature — `00-current-state.md` puts the
requirement at ≤−54 dB per pair — and channel separation is a within-die
property (page 2: −110 dB typical, though the datasheet does not specify
channel-to-channel *crosstalk* under signal, which is open question 1).

Two quads, six channels. **4 + 2** gives four strings three die-mates each and
two strings one. **3 + 3** gives every string two die-mates, and leaves one
spare channel per package. Since the failure mode is a chord where five shut
strings each leak a copy of one open string — the +14 dB voltage-sum law — the
arrangement to prefer is the one that minimises the *worst* string's exposure,
not the average.

Recorded here rather than decided: it interacts with the floorplan, and with
whether a spare channel is wanted for feature 12's compressor sidechain.

---

## 7. Corrections to `hardware-spec-v0.md`

| § | Claim | Verdict | Changes |
|---|---|---|---|
| §2, §4.2 | control port is a current-summing node | **Wrong.** Voltage input, 9k∥1k to ground | the whole scaling arrangement |
| §2 | nominally 10 kΩ | **Right**, and it is 9/10/11 kΩ min/typ/max | tolerance budget |
| §2 | internal 10:1 divider | **Right.** 9 kΩ series, 1 kΩ shunt | — |
| §2 | −33 mV/dB | **Right**, and derivable from q/kT | — |
| §2 | +3300 ppm/°C tempco resistor practice | **Right as practice**, named on page 10; declined here on the arithmetic in §4 | six parts saved |
| §2 | (sign) | table gives **−3300 ppm/°C**; consistent, magnitude rises with T | — |
| §4.1 | R_IN 30 kΩ, "datasheet noise condition" | **Wrong.** Worst of four; 20 kΩ recommended, 7.5–100 kΩ range | R_IN, R_OUT |
| §4.1, §4.5 | coarse pad, 0/−6/−12/−18 dB on latching relays, "keeps the VCA near unity where its noise costs least" | **Wrong, and it is the largest thing in this table.** The noise rise belongs to R_OUT, which a pad does not move, and THD at A_V = −20 dB is *lower* than at unity. The control port reaches the same level for no parts | 36 parts, 52 % of the courtyard, two thirds of the BOM, 24 coil drives and a coil supply rail |
| §4.1 | MODE pin | **Absent.** Class AB, pin 1 open, worth 12 dB and better feedthrough | one part not fitted |
| §4.1 | input RC | **Absent.** 220 Ω + 1200 pF is required for stability | 2 parts/channel |
| §4.1 | series 10 µF at the VCA input | **Absent.** Recommended for control feedthrough — the lead feature's own failure mode | 1 part/channel |
| §4.2 | 0–5 V through 15 kΩ, "free 8 dB" | **Wrong twice.** ±6 % slope error from the port tolerance, and the 8 dB is a wash once reference noise scales with V_OUT | scaling moves into the filter ratio |
| §4.2 | offset injection "from VREF" | **Sign wrong.** Figure 10's offset is from a *negative* source | offset topology |
| §4.2 | inverting MFB + unipolar + positive-attenuates | **Now closes**, via Figure 10, with the source complemented in firmware | — |
| §4.5 | PWM idling low = fail-loud | **False for this topology.** Idle low is full attenuation — fail-silent by construction | 6 pull-downs; hazard deleted |
| §1.1 | module needs 60–80 mA | **Over by ~5×** for the VCAs: ±6 mA typ per package | supply sizing |
| §1.4 | THAT4301 needs ±7 V, "check rails first" | **Clears.** ±4 to ±18 V on the 2164; rails are not the gate | bench-off unblocked |

Seven of these move a component value or a part count, and the seventh moves 36
of them. Two — the fail-silent inversion and the missing 10 µF — bear directly
on the lead feature rather than on the noise budget.

---

## 8. Still open after the read

The datasheet does not answer these, and §8 of the spec already lists the first
two:

1. **Channel-to-channel crosstalk under signal.** Page 2 gives channel
   separation −110 dB typical, which is not the same measurement. Binding on
   features 4, 5, 6 and 11 at ≤−54 dB per pair. Phase 1.5.
2. **Control-port voltage-noise density.** Unspecified. Every AM figure in this
   project assumes the external source dominates, and nothing in Rev 3.4 says
   whether it does.
3. **How much of the cell's noise sits ahead of the gain core.** Nothing in
   Rev 3.4 distinguishes input-referred from output-referred, and there is no
   noise-against-gain figure anywhere in it. It decides how much quieter a shut
   channel is than an open one, which is most of the gating penalty in
   `delta.system_delta()`. `design.cell_noise()` takes it as a parameter and
   both ends are computed; the pad decision was deliberately made to survive
   either. In `ASSUMPTIONS.md`.
4. **Gain accuracy at deep attenuation.** The table stops at −40 dB for
   feedthrough and matching, and the feature wants ≥47 dB of usable depth per
   channel. −100 dB is specified as a maximum, not characterised on the way
   down.
