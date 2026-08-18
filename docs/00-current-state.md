# Per-string level control — current state

> ## ⚠ Two corrections to this page's own standing
>
> **1. "Where a document contradicts this page, this page wins" no longer holds.**
> Three of the arithmetic's disagreements are with this page now, not two.
> It was true when written, and this page kept its own promise honestly — it is
> the document that established the habit of recording what each correction
> overturned. But `hardware-spec-v0.md` is the authoritative spec for this repo,
> and where either conflicts with a *computed* result, **the arithmetic wins.**
> `delta.py` prints its disagreements last and loudly for exactly this reason.
>
> **2. Three of the four results `delta.py` disagrees with are on this page**,
> and two of them are not details:
>
> | this page says | the arithmetic says |
> |---|---|
> | Hardware table: dominant noise mechanism is **multiplicative**, corrected from additive | **Additive wins, and the correction should be reverted.** The VCA cells sit 84.3 dB under one string; the CV chain's AM sits 91.7 dB under the same signal. The original claim was right and was overturned for a mechanism 8 dB quieter |
> | Three things that most affect the sound, item 2: summing-resistor scaling is a **free 8 dB** | A wash. It assumed source noise independent of the source's full-scale voltage; the MAX6126's noise rises with its output — 45 nV/√Hz at 2.5 V against 95 at 5 V, both read first-hand — so scaling up and dividing back down cancels |
> | Hardware table: gain staging is a **coarse switched passive pad (latching relays) + VCA near unity**, marked *Unchanged* | **Struck.** The SSI2164's noise table sweeps R_IN and R_OUT together and the rise belongs to R_OUT, which a pad does not move; the datasheet's own THD is *lower* at A_V = −20 dB than at unity. Against the control port the pad buys 0.000 dB of system noise at every floor in `noise_floor`'s range, and it cost 36 parts, 52 % of the courtyard and two thirds of the BOM. `design.pad_benefit()` |
>
> **The third one is the reason "Unchanged" is a status worth distrusting.** It
> is the only row in the Hardware table that carried that word through five
> documents, and it meant nobody had revisited it — not that anybody had checked
> it. Every other row on this page won an argument; that one never had one.
>
> `delta.DISAGREEMENTS` is the authority for all three, with the numbers
> recomputed on every run rather than quoted here. The remaining disagreement is
> against `CLAUDE.md`, not this page.
>
> **The reading order below is history.** Documents 0–4 belong to the parent
> project and are not in this repo; nothing here depends on them. What survives
> of that discussion, and is here, is
> [`element-revisit.md`](element-revisit.md) and
> [`supply-decision.md`](supply-decision.md).

**Read this for context, not for current truth.** Five documents accumulated, each
correcting the last, so several confident-sounding passages in the earlier files
are wrong — and, as above, three on this page are too. The value of this page is
that it says *why* the choices are what they are.

Last revised: after the DAC8568 SYNC correction.

---

## Reading order

| # | Document | Status |
|---|---|---|
| 0 | `dynamic-string-levels.md` | **Parent doc, unmodified.** Forks Layer 1 into motorised faders (A) vs electronic attenuator (B) |
| 1 | `option-b-programmable-attenuator.md` | Element choice. **Element analysis stands; control-architecture numbers superseded** |
| 2 | `option-b-controller-and-pattern-engine.md` | Pattern engine + controller. **Engine stands; hardware half superseded** |
| 3 | `option-b-sequenced-gating.md` | The lead feature. **Current** |
| 4 | `phase-0.75-vcv-rack-patch.md` | Live patch for the real-time test. **Current** |
| 5 | `option-b-controller-deep-dive.md` | Controller/CV architecture, done rigorously. **Current — supersedes 1 and 2 on hardware** |

Code: `hexsim/hexsim.py` (offline simulator), `hexsim/hexengine.c` (portable
engine core), `hexsim/demos/` and `hexsim/demos-arp/` (rendered audio).

---

## The state of every live decision

### Musical

| | Current position |
|---|---|
| **The instrument** | A modern interpretation of the **arpeggione**: six strings, standard guitar tuning, **bowed as well as picked**. Recorded here because it was not written down anywhere for the first several passes and it decides things — it is what settles the envelope detector's topology, and it is new evidence in the element bench-off. See `design.envelope_filter()` and [`element-revisit.md`](element-revisit.md) |
| **Lead feature** | **Sequenced per-string gating.** Reads as a sequence of *timbres at constant level*, not a chopped rhythm — the arpeggio pattern opens exactly one string per step, so summed gain is constant (measured 1.0500 min and max) |
| Drone bed | Depth is really a "how much chord stays present" knob. Useful range **15–35 dB**; below ~14 dB the pattern vanishes into the chord |
| Polymeter | Six rows on their own loop lengths {5,7,4,3,8,6} → 840 steps, 105 s at 8 steps/s vs 2 s for a fixed 16-step row. One modulo per string |
| Rhythm → timbre boundary | Where step period approaches pitch period: ~41 steps/s for low E. Features 4 and 9 are the same feature at different rates |
| Tremolo phase spread | Weaker than first claimed. The 60°/120° null needs the strings **level with each other**, not steady in time — 9.85 dB residual with a realistic source, and *no null at all* on an ebow-like source |
| Sustain | The texture needs it. A plucked chord is 16 dB down within a few bars |
| Prior art | Moog Guitar did per-string sustain and muting; Vo-96 per-string harmonics; hex distortion exists. **Sequenced per-string amplitude as the primary effect** looks genuinely uncommon |

### The two arithmetic laws that govern gating

Both were wrong in the earlier docs, which used +14 dB for each:

- **Intentional attenuation** — five shut strings are *uncorrelated*, so they power-sum: **+10·log₁₀(5) = +7 dB**
- **Channel crosstalk** — five *copies of one source*, so they voltage-sum: **+20·log₁₀(5) = +14 dB**

For 40 dB of musical gate depth: per-channel depth **≥47 dB**, per-pair isolation
**≤−54 dB**. Crosstalk remains the binding constraint and the thing to measure.

### Hardware

| | Current position | Was |
|---|---|---|
| **Element** | **SSI2164** quad VCA, −33 mV/dB. Unchanged | — |
| **Controller** | **RP2040** (on-chip LDO, production to 2041) or STM32G474. Top three within 4 points — the choice barely matters | Teensy 4.1 / RP2350B — *both fail the switching-regulator gate* |
| **CV generation** | **PWM + 74AHC541 from a precision reference** → 6× AD5683R daisy-chained → DAC8568 with 8 CS pulses | DAC8568 in a single-SYNC burst — *not possible, `t4` min SYNC HIGH = 80 ns* |
| **Control frame rate** | **8 kHz** | 32 kHz — the aggressor argument dies once the CV filter exists |
| **CV filter** | **2-pole, 200–400 Hz, per channel. Mandatory.** Worth 15–20 dB of AM noise and doubles as the de-click | 2 kHz single-pole, treated as cosmetic |
| **Resolution** | **Non-issue.** 10-bit = 0.074 dB/LSB on a dB-linear port | 12 vs 16 bit analysed at length |
| **Dominant noise mechanism** | **Multiplicative** — control noise × 3.48/V, breathing with the signal | Additive, from the VCA |
| **Envelope ADC** | **MCP3564**, external, in the analogue section, at 2 kHz. ~~derived, not chosen~~ — **chosen now**, and by the one number that could not be worked around: the ADS131M08's external reference input stops at 1.3 V, so its full scale is 1.20 V against a 1.233 V signal. `design.ENV_ADC` | On-chip; drove the wrong "must be RP2350B" conclusion |
| **Envelope detector** | Six precision **full-wave** rectifiers into a symmetric 4.7 ms one-pole, drawn. The musical attack/release is a firmware constant at the frame rate, because bowed and picked want opposite shaping | Not decided; recorded as needing a musical target it turned out not to need |
| **Reference** | 35–41 nV/√Hz (MAX6126 + NR cap, or ADR4525C/D), shared by DAC and ADC. Reference noise is **correlated across strings**, so it is the most perceptible kind | Not considered |
| **Feature 12, compression** | **Analogue sidechain.** dB-out RMS detector (6.1 mV/dB) into the dB-in port ⇒ ratio is one resistor ratio | Software, in the sensing layer |
| **Fail-safe** | **AC-coupled charge pump** driving the bypass relay (any stuck state drops it) + DAC CLR-to-full-scale = hardware mute in ~1 µs | Watchdog + latching relay |
| **Gain staging** | ~~Coarse switched passive pad (latching relays) + VCA near unity~~ **Struck** — one fixed R_IN = R_OUT, all attenuation in V_C. See the correction block at the top | Was: *Unchanged* through five documents |
| **Buy vs build** | **Build bespoke.** Nothing off-the-shelf survives the no-switcher rule | Not examined |

### The three things that most affect how it sounds

None is the controller, and none is DAC resolution:

1. **A 2-pole 200–400 Hz low-pass on every CV**, as an inverting MFB stage that also
   injects the offset and buffers the DAC from the 2164's 10 kΩ divider. ~15–20 dB.
2. **Summing-resistor scaling** — DAC at 0–5 V through ~15 kΩ into the 10 kΩ node
   rather than 0–2 V direct. **Free 8 dB for one resistor value.**
3. **A 35–41 nV/√Hz reference**, because its noise is common to all six strings.

---

## Staging

| Phase | What | Cost |
|---|---|---|
| **0.5** | Record hex stems, run `hexsim.py --stems`. Musical go/no-go | £0 |
| **0.75** | Same rig live, in VCV Rack. *Would I actually play this?* | £0 |
| 1 | One SSI2164 channel. **Feedthrough test first**, then noise, then law drift | ~£15 |
| 1.5 | Second channel on the same die. **Measure crosstalk** — caps the whole gating feature set | ~£5 |
| 2 | Six channels + controller + sensing layer + editor | |
| 3–6 | Fader decision, loom, enclosure, failure modes | |

---

## Open questions, ranked

1. **SSI2164 channel-to-channel crosstalk.** Not on the datasheet; binding on
   features 4, 5, 6 and 11. Target ≤−54 dB per pair.
2. **SSI2164 control-port voltage-noise density.** Not specified. Every AM-noise
   figure assumes the external source dominates.
3. **Does the 60° spread null survive per-string level normalisation?** If feature
   12 is running, the strings *are* level, so the null may return.
4. **Whether the 74AHC-powered-from-a-reference topology is sound.** No vendor app
   note exists; the reasoning is sound but unpublished.
5. **Whether a 250 Hz CV filter is fast enough** for the gate feel you want.
6. ~~Whether 1–2 kHz envelope sampling is enough for the swell to feel
   responsive.~~ **Half-answered, and the half that moved was not the musical
   one.** It is not a range: at 1 kHz the top string's own rectified
   fundamental (659 Hz) is above Nyquist and folds back at −29 dB, −33 dB of it
   landing near DC where no averaging removes it. **2 kHz**, and then the
   unremovable residue is −53 dB. `design.envelope_sample_rate()`. Whether it
   *feels* responsive is still open and is now a firmware constant rather than
   a hardware one.

---

## Corrections log

Every claim overturned so far, so the pattern is visible.

| # | Claim | Verdict | Found by |
|---|---|---|---|
| 1 | THAT2180 at 55 nV/√Hz | 89 nV/√Hz from the datasheet | self-check |
| 2 | Phase 1 answers the musical question | It answers the *engineering* question; Phase 2 answers the musical one | self-check |
| 3 | Option B deletes the supply problem | It still needs a bipolar analogue supply | self-check |
| 4 | Control frame rate is audibly binding | 2 kHz to 32 kHz indistinguishable | measurement |
| 5 | Edge slew is the feedthrough mitigation | Buys ~6 dB. Constant-sum patterns buy 25.6 dB | measurement |
| 6 | Five shut strings sum at +14 dB | +7 dB (power sum). +14 dB is crosstalk only | measurement |
| 7 | Spread-60° null gives 4.2 dB | 9.85 dB with a realistic source | **user's ear** |
| 8 | The synthesised source decayed like a guitar | No pick transient at all; it swelled into the note | **user's ear** |
| 9 | Teensy 4.1 / RP2350B for the controller | Both have mandatory buck converters | deep dive |
| 10 | The MCU is the load-bearing choice | The DAC is; and then neither, really | deep dive |
| 11 | DAC8568 can stream frames under one SYNC | It cannot — `t4` min SYNC HIGH = 80 ns | **user reading the datasheet** |
| 12 | PWM loses on cost and accuracy | Leading option once the CV filter is mandatory anyway | consequence of 11 |
| 13 | A coarse relay pad keeps the VCA near unity "where its noise costs least" | **No mechanism.** The 2164's noise rise is R_OUT's; a pad moves R_IN. 0.000 dB of system noise for 36 parts | reading the datasheet's conditions line |

Three of the thirteen came from Tim rather than from me, and two of those three
(7, 8) came from listening rather than from analysis. Worth noting as a working
pattern: **the renders are the most reliable error detector in this project.**

Number 13 is the second of its kind — after `CLAUDE.md`'s struck constraint 2 —
and the two together are the pattern worth naming: **the claims that survive
longest are the ones nobody ever argued about.** Both were carried forward as
settled through every document in the project, and both fell to twenty lines of
arithmetic the first time anybody wrote them down.