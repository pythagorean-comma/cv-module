# The element choice, revisited

> **Where this landed.** Recommendation 2 was followed: the schematic is drawn with
> the **SSI2164**, two packages, 3 + 3 across them so every string has two
> die-mates rather than four having three and two having one — `design.allocation()`
> carries that arithmetic, which is not in this document because it did not exist
> yet. The footprint choice is isolated as this document asked.
>
> **Recommendation 3 is resolved and it clears.** The rails are ±12 V
> (`design.MODULE_RAIL`, decided in [`supply-decision.md`](supply-decision.md)),
> so the THAT4301's ±7 to ±15 V requirement is not the gate this document worried
> it might be — and the SSI2164 accepts ±4 to ±18 V, read first-hand. The
> bench-off is unblocked rather than narrowed.
>
> **Recommendation 4 is still open**: the THAT4301's price and availability were
> never looked up. So is the bench-off itself, and so is the guess at the bottom of
> this page. Nothing since has tested it.
>
> The datasheet read that followed this document is
> [`ssi2164-control-port.md`](ssi2164-control-port.md), and it settled §1 of this
> page independently: the control-law argument really was cancelled, and the
> reason is a voltage input behind a 9k∥1k divider rather than the current-summing
> node every earlier document assumed.

Short answer: **no, we are not certain — and the SSI2164 recommendation is weaker
now than when it was made, because the lead feature changed afterwards.**

The original case (`option-b-programmable-attenuator.md`) rested on four arguments.
Two have since been eroded, one was never weighted, and a third part has appeared
that was not in the comparison at all.

---

## 1. My headline argument was largely wrong

The original recommendation led with the control law: −33 mV/dB against 6.1 mV/dB
is 5.41×, *"14.7 dB of extra immunity in the control domain"*, and I weighted it
first.

**That advantage is mostly cancelled by the divider ratio** [D]:

| | mV/dB | CV span for 66 dB of range |
|---|---|---|
| SSI2164 | 33.0 | **2.178 V** |
| THAT2180 | 6.1 | **0.403 V** |
| THAT4301 | 6.5 | 0.429 V |

A 2180 needs **5.41× less CV span**, so you divide the source down 5.41× harder —
and that attenuates source-referred noise by exactly the same factor. The law
advantage and the divider ratio cancel.

What actually survives is only what is added **after** the divider: the CV filter
op-amp's own output noise, pickup on the short run to the VC pin, offset drift and
thermal EMF. With a low-impedance MFB output, that is small.

I made this argument before the CV chain had a divider in it. Once the deep dive
added the summing-resistor scaling, it stopped being true.

---

## 2. The argument I never weighted, which now matters most

**Crosstalk is the binding constraint on the lead feature.** Sequenced gating
became the headline *after* the element was chosen, and gate depth is capped at
per-pair isolation + 14 dB:

| Musical gate depth | Per-pair isolation needed |
|---|---|
| 30 dB | ≤ −44 dB |
| 40 dB | ≤ −54 dB |
| 45 dB | ≤ −59 dB |

| | Channels per die | Crosstalk exposure |
|---|---|---|
| **SSI2164** | **4** | **On-die. Not on the datasheet. Unmeasured** |
| THAT2180 | 1 | Board-level only |
| THAT4301 | 1 | Board-level only |

Board-level isolation at audio frequencies is a layout problem you control. On-die
isolation is whatever the die gives you, and no amount of good layout fixes it.

**A quad VCA is structurally the wrong shape for a design whose headline feature is
per-string gating.** That is an uncomfortable sentence to write about a part I
recommended, but it follows directly.

### The honest counter-argument

Same-die channels **match better**, and matching is what sets the residual for the
constant-sum feedthrough cancellation — ±30 % gives 25.6 dB of rejection, ±10 %
gives 9.6 dB more. Six separate packages will match worse than four channels off
one die.

So it is a genuine trade: **on-die buys matching (a bonus), separate packages buy
isolation (a ceiling).** Ceilings beat bonuses — a bonus you lose is 10 dB of
feedthrough rejection you can trim back at build; a ceiling you hit means the
gating features never sound absolute.

---

## 3. Noise and distortion, on a common basis

| | Noise | vs 2180 | THD |
|---|---|---|---|
| THAT2180 | **89.1 nV/√Hz** (−98 dBV @ 0 dB, R_OUT 20 k) | — | **0.005 %** (A grade) |
| THAT4301 | 112.1 nV/√Hz (−96 dBV @ 0 dB, 20 k load) | +2.0 dB | **0.003 %** |
| SSI2164 | 122.7 nV/√Hz (−93 dBu, R 30 k) | **+2.8 dB** | **0.050 %** (class AB) |

Two things I under-weighted:

- **2.8 dB of noise**, in a design where we have been fighting for 8 dB from a
  single resistor value.
- **10× the distortion.** The SSI2164 can reach 0.025 % in class A, but that costs
  **12 dB of noise** (−93 → −81 dBu) [S] — a bad trade here. The THAT parts get
  0.003–0.005 % with no such penalty. The parent doc's whole character is a box
  that is "0.55 dB from theoretical"; 0.05 % is out of keeping with it.

*(Note: none of these conditions are like-for-like on resistor values. Directional,
not decisive.)*

---

## 4. The part that was not in the comparison: THAT4301

The **THAT4301 "Analog Engine"** contains, in one package [S]:

- a Blackmer VCA at **6.5 mV/dB**
- an **RMS-level detector whose output scale factor is also 6.5 mV/dB**
- **three general-purpose op-amps**

Look at what that collapses. The bipolar domain in the current spec is *six
buffers, six I–V converters, six servos and two VCA packages*. One 4301 per string
provides the VCA **and** the three op-amps that do exactly those three jobs:

| | Packages for six channels |
|---|---|
| SSI2164 + discrete op-amps | 2 VCA + ~5 quad op-amp = **~7** |
| THAT2180 + discrete op-amps | 6 VCA + ~5 quad op-amp = **~11** |
| **THAT4301** | **6** |

And the detector is the decisive part. The deep dive concluded that **feature 12
(per-string compression) should be analogue**, because a dB-out detector feeding a
dB-in control port makes the compression ratio a single resistor ratio. The 4301's
detector law is **deliberately matched to its own VCA law** — 6.5 mV/dB into
6.5 mV/dB. It is the exact architecture we arrived at independently, sold as one
part.

Feature 12 is load-bearing three separate ways by now (sustain, thermal drift, and
the spread-null needing level-matched strings). A part that provides it for free is
worth a lot.

**Caveat: the 4301 needs ±7 to ±15 V** [S], narrower than the SSI2164's ±4 to ±18.
If the mixer's rails turn out lower than ±7, the 4301 is out — another reason the
mixer's actual rail voltages are the first thing to check.

---

## 5. Cost, which is not decisive

| | Six channels |
|---|---|
| SSI2164 | 2 × £3.80 = **£7.60** (Thonk, in stock) |
| THAT2180 | 6 × £7.87 = **£47.22** (Farnell UK, 435 in stock) |
| THAT4301 | not checked — **look this up** |

£40 on a one-off build you intend to keep. The 4301 additionally deletes perhaps
£15–25 of op-amps, narrowing it further. This is not the axis to decide on.

---

## The recommendation

**Do not switch on this analysis. Make it a bench decision, and change what Phase
1.5 measures.**

The DAC8568 episode is the relevant precedent: a confident paper conclusion, built
on a plausible reading, overturned by one number in a datasheet. The number that
decides this one is **SSI2164 channel-to-channel crosstalk**, and it is not
published.

- If it comes in at **≤ −60 dB per pair**, the 2164 is fine, its density and price
  advantages hold, and nothing changes.
- If it is nearer **−45 dB**, musical gate depth is capped around −31 dB, the lead
  feature is compromised, and the part is wrong for this design.

### New evidence, added later: the instrument is bowed

The target is a modern **arpeggione** — six strings, standard guitar tuning,
**bowed as well as picked**. That was not known when this document was written
and it strengthens the 4301 case a third time, for a reason the sections above
do not contain.

A bowed note has no transient and the player modulates level continuously
through it, so the sensing layer stops being an onset detector and becomes the
thing that reports the performance. §4.4's answer to that is six precision
rectifiers into an RC and an ADC, which `design.envelope_filter()` now derives —
and it is an *average* detector with ripple at the string's own pitch, needing
12 op-amp sections and a firmware average to clean up after it. The THAT4301
carries an **RMS detector with a dB-linear 6.5 mV/dB output** in the same
package as the VCA. Log-domain, so the ripple problem largely goes away; the
sensing layer lands in the same units as the control law; and it is not 12
sections of a second op-amp type.

Not acted on, for the reason the whole document gives: this is a bench decision
and the number that settles it is still unpublished crosstalk. Recorded so the
bench-off measures the right things.

### Changes to the plan

1. **Phase 1.5 becomes a three-way bench-off**, not a single-part crosstalk check:
   one channel each of SSI2164, THAT2180 and THAT4301. Measure crosstalk, noise,
   control feedthrough, and channel matching on all three. Budget ~£70 rather than
   £5. That is cheap against committing a PCB to the wrong element. **Add the
   4301's RMS detector to what is measured**, on a bowed note as well as a
   picked one — see the bowing note above.
2. **The spike is not blocked.** All three are current-in/current-out Blackmer-class
   parts with the same surrounding topology — local I–V, CV divider, servo. The
   schematic is architecturally identical; only the footprint and two resistor
   values change. **Draw it with the SSI2164 and note the variants**, exactly as the
   original doc intended when it said the element choice should live behind one
   resistor.
3. **Check the mixer's rail voltages early.** If they are below ±7 V the 4301 is
   out before the bench-off starts.
4. **Look up the THAT4301 price and availability**, the one input missing here.

### If I had to guess the outcome

The 4301 wins, on the strength of collapsing feature 12 into the same package and
removing on-die crosstalk in one move. But that is a guess, it contradicts a
recommendation I made confidently three documents ago, and the last two times a
guess of mine met a datasheet the datasheet won. **Measure it.**