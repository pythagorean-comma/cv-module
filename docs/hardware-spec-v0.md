# Hardware spec v0 — per-string CV module

**Purpose:** seed document for a schematic/PCB spike. This is not a design
discussion. This is the extracted, buildable specification, with every value
either stated or explicitly marked as *compute*, and every unknown explicitly
marked as *BLOCKED* or *TBD*.

Read [`00-current-state.md`](00-current-state.md) for why any of these choices are
what they are.

---

## ⚠ This is v0, and the design has moved past it in places

**Kept unedited on purpose.** It is the baseline the corrections are measured
against, and rewriting a claim in place would destroy the record of what was
specified versus what was derived. So the numbered sections below say what they
said on day one, and **where a claim has been overturned the answer is somewhere
else.** This table is the index; none of it is restated here, because one copy in
one place is the rule the rest of the repo runs on.

| where | what moved | the current answer |
|---|---|---|
| §2, §4.1, §4.2, §4.5, §1.1, §1.4 | seventeen claims, checked against the SSI2164 datasheet read first-hand. Six move a component value or a part count | [`ssi2164-control-port.md` §7](ssi2164-control-port.md#7-corrections-to-hardware-spec-v0md) |
| §5.2 | *"Six separate returns to six pin-3s"* — **struck.** No mechanism: pairwise crosstalk through a single bond is 122 dB below one string against a −54 dB requirement | `CLAUDE.md`, and `design.FRONT_R` for the arithmetic |
| §5.3, §4.1 | *"zero DC by construction"* — restated. A servo is feedback, not construction, and it overstates by three orders of magnitude | `CLAUDE.md` constraint 4 |
| §5.4 | *"or the 31.8 Hz corner moves"* — corrected. 31.8 Hz is the corner at 5 kΩ, one end of the window the sentence quotes | `CLAUDE.md` constraint 3 |
| §5.5 | *"individually-shielded twisted triads"* — demoted from load-bearing to good practice on 59 dB of margin, and a triad here is a pair inside a shield | `CLAUDE.md` constraint 5 |
| §4.2 | *"MAX6126A25 … (35 nV/√Hz)"* — 35 nV/√Hz is the **2.048 V** part. The 2.5 V part is 45 | `design.VREF`, read first-hand |
| §4.1, §4.5 | *"Coarse pad … Keeps the VCA near unity where its noise costs least"* — **struck, and it is the largest deletion in the repo.** The SSI2164's noise rise belongs to R_OUT, which a pad does not move; against the control port, which reaches the same level for no parts, the pad is 0.03–3.9 dB *worse* at the cell and 0.000 dB at the system. 36 parts, 52 % of the courtyard, two thirds of the BOM | `design.pad_benefit()`, `delta.pad_system_delta()` |
| §4.4 | *"**ADS131M08** ... or **MCP3564**"* — decided, and by neither channel count nor price. The ADS131M08's external reference input stops at **1.3 V**, so its full scale at unity gain is 1.20 V against `socket.clipping_peak()`'s 1.233 — it clips 0.24 dB *below* the level it exists to measure, and its minimum gain is 1. The MCP3564 takes VREF up to AVDD, so the board's own 2.5 V reference works and `floorplan.CROSSING_RULE`'s already-written *"the ADC's own reference is VREF"* becomes true | `design.ENV_ADC` |
| §4.4 | *"only SCLK/MOSI/MISO/CS cross"* — **six, not four.** A data-ready line, and a master clock: the MCP3564 multiplexes one modulator across six channels, so its internal RC oscillator — 3.3 to 6.6 MHz, a factor of two — cannot hold 2 kHz per channel at any OSR. That is the multiplexer's bill and it is paid in conductors | `design.envelope_adc_clock()` |
| §4.4 | *"1–2 kHz sampling is sufficient"* — not a range. At 1 kHz the top string's full-wave ripple fundamental is above Nyquist and folds to −29 dB, −33 dB of it near DC. **2 kHz** | `design.envelope_sample_rate()` |
| §4.4 | *"six precision rectifiers → RC"* with no time constant, recorded here as needing a musical target — **it does not, and it is drawn.** A symmetric one-pole has no release bound: 4.7 ms falls 46× faster than the fastest musical decay. Full-wave, on the bow's account, which is 12 op-amp sections against the 6 reserved | `design.envelope_filter()`, `design.envelope()` |
| §4.5 | *"bypass relay"*, singular — **six changeover contacts, not one.** The module replaces six level pots, so bypass is six independent links back. 3 DPDT, and non-latching by mechanism: de-energised must *be* bypass | `design.BYPASS_RELAYS`, `bypass_state()` |
| §4.5 | *"Any stuck state … collapses the pump and drops to bypass"* — true, and it does **not** cover the one fail-loud path. A reference inverter failing to the rail leaves the MCU healthy and the pump up. One Schottky clamp turns +20 dB into +7.4 dB | `design.clamp_gain()`, and the correction at `fail_states()` |
| §4.5 | *"12 coils (six 2-bit pads)"* driven by *"2× TPIC6B595"* — does not close. Dual-coil latching, as §4.1 asks, is 24 coils and 3× registers. **Moot with the pad struck**, and recorded because a spec that does not close arithmetically is worth knowing about | [`ASSUMPTIONS.md`](ASSUMPTIONS.md) |
| §1.1 | *"\|f_module − 45 kHz\| > 20 kHz, target ≥300 kHz"* — **the rule is stated for the pump's fundamental and the mechanism it defends against is not.** The pump's ripple has harmonics at every n × 45 kHz, and the fitted converter's own 522–638 kHz band contains the 12th, 13th and 14th: the nearest beat is **5 kHz**. No switching frequency clears them all. What makes it safe is the isolation and the second-order size of the product | `design.supply_beat()` |
| §1.1 | *"~60–80 mA with the op-amps"*, and `supply-decision.md`'s own *"~44 mA per rail"* — the board draws **110 mA**, and the converter has to deliver **3.87 W** rather than the 3.10 that summing the rail powers gives, because V5 is made linearly from VA+ | `design.supply_requirement()`, `design.supply_fit()` |
| §4.3 | *"Needs: USB device (MIDI), DIN MIDI in/out, tap footswitch, expression pedal in, **12 GPIO for relay drive**, SPI for the ADC"* — five of six, and the sixth went with the coarse pad. What the drawn block actually needs is **19 GPIO of 30**, because the list omits the part's own periphery: two MIDI lines, the tap, the pedal and USB's VBUS sense | `design.CONTROLLER_MAP`, `controller_asks()` |
| §4.3 | *"Not a module — bare chip plus QSPI flash and a crystal, so the power architecture is ours"* — held, and the power architecture is where the block's one open question ended up: the 3.3 V rail is a switcher because two linear rails cannot carry it out of 35.4 mA of +Vout | [`controller.md`](controller.md) |
| §7 | asks `verify.py` to check "six separate returns", which is §5.2 and struck | `verify.check_shield_returns()` holds the half that has a mechanism |

**§6 has not moved and is still binding.** Nothing in the list above was invented
to replace a claim; each is either read from a datasheet or derived, with the
arithmetic in a function.

---

## 0. Scope of the spike

**In scope:** the CV generation module — controller, CV chain, envelope sensing,
coarse pad relays, fail-safe. One board.

**Out of scope:** the existing summing mixer (already fabricated), the VCA board
if it ends up separate, the enclosure, the UI panel.

**Deliverable of the spike:** a netlist whose connectivity is machine-checked, all
component values derived rather than guessed, a PCB floorplan with a defensible
ground strategy, and a written list of everything that had to be assumed.

---

## 1. BLOCKED — must be resolved before drawing

Three items. Two of them only Tim can answer.

### 1.1 The module's supply — RESOLVED, see `supply-decision.md`

> **DECIDED.** One shared DC inlet → an **isolated DC-DC at ≥300 kHz** → ±12 V for
> a small audio domain plus +5 V / +3V3 for everything else.
>
> Three reasons, the third decisive:
> 1. **The negative rail only needs ~44 mA**, not ~100 mA — CV and envelopes are
     >    unipolar and run single-supply. Enforce that domain split on the schematic.
> 2. **The mixer already runs a 45 kHz charge pump.** A VCA is a multiplier, so two
     >    supply ripples intermodulate into the audio band. Rule:
     >    **|f_module − 45 kHz| > 20 kHz**, target ≥300 kHz. *Do not use an ICL7660S /
     >    TC1044S with the boost pin — that sets exactly 45 kHz.*
> 3. **Sharing a DC inlet non-isolated creates a second ground bond**, breaking the
     >    "exactly one bond" rule. Isolation preserves it by construction.
>
> Still to look up: the mixer's actual rail voltages and DC input range, from
> `design.py` alongside `NEGATIVE_RAIL_DROP` / `output_swing()` / `clipping_peak()`.

<details>
<summary>Original text, kept for the record</summary>

### 1.1 The module's bipolar supply — genuinely undecided

The SSI2164 needs **±4 V to ±18 V** [S]. The parent doc forbids the module drawing
anything from `VREG`, `V+` or `V−` (*"Every mA on V− costs 65 mV of rail"*). So the
module needs its own bipolar rail, roughly **60–80 mA** with the op-amps — and
nothing in any document decides where it comes from.

| Option | Cost |
|---|---|
| Separate mains inlet, linear ±15 V | Quietest. Second inlet, transformer, board area, heat |
| Single DC inlet + low-noise charge pump for the negative rail | One inlet. A switching aggressor, though at low current |
| Single DC inlet + DC-DC | Smallest. The exact thing the enclosure argument exists to avoid |

**This changes board area, connector count, thermal design and the entire
grounding plan. Decide it before drawing anything.**

</details>

### 1.2 The interface contract with the existing boards

Needed from the existing repo, which I have never seen:

- `RV{n}01` / `CHANNEL_POT_FP = CONN_FP[3]` — connector part, pitch, gender, and
  the exact pin order for `PIN{n}` / `SIN{n}` / `AGND`
- `fab/mechanical-*.json` — board outline, mounting holes, keep-outs
- `DC_BLOCK_VALUE` and the actual `RIN` value, so the 10 kΩ load and the 31.8 Hz
  corner can be checked rather than assumed
- `MEASURED["noise_floor"]` — if it has been measured since

### 1.3 CV architecture — pick one, they are different boards

**Recommendation: PWM.** Fewer parts, no chip-select question, and the filter it
needs is mandatory anyway. But it is a decision, not a default.

| | PWM | DAC |
|---|---|---|
| Parts | 6 MCU PWM pins → 74AHC541 → filter | SPI → DAC → filter |
| CS/framing | none | 8 CS pulses (DAC8568) or one (6× AD5683R chain) |
| Simultaneous update | no (≤33 µs skew, acceptable) | LDAC |
| Extra BOM | 74AHC541 ~£0.30 | DAC ~£10 |

---

### 1.4 The VCA element is no longer settled — but does not block the spike

`element-revisit.md` reopens SSI2164 vs THAT2180 vs **THAT4301**. Summary:

- The control-law argument that originally won it for the SSI2164 is **cancelled by
  the divider ratio** the deep dive later added.
- **Crosstalk is the binding constraint on the lead feature**, and the SSI2164 puts
  four channels on one die. The THAT parts are one channel per package.
- **THAT4301** contains a VCA *and* an RMS detector with a matched 6.5 mV/dB law
  *and* three op-amps — collapsing the analogue compressor (feature 12) and the
  buffer/I–V/servo trio into the same package. Six packages total, against ~7 or
  ~11 for the alternatives.

**This does not block drawing.** All three are current-in/current-out Blackmer-class
parts with identical surrounding topology. Draw with the SSI2164, keep the footprint
choice isolated, and note the variants. Phase 1.5 becomes a three-way bench-off.

**But check the mixer's rail voltages first** — the THAT4301 needs ±7 to ±15 V and
is out below that.

---

## 2. Look up before committing values (does not block topology)

**SSI2164 control-port structure.** Our working figures — *"current-summing node,
nominally 10 kΩ, internal 10:1 divider, −33 mV/dB"* — came from a research pass,
not from a first-hand read. Before fixing any resistor value, confirm from the
datasheet: the actual VC input structure, the recommended summing arrangement, the
input impedance, and the standard **+3300 ppm/°C tempco resistor** practice for the
control divider. Twenty minutes, and it sets half the passive values on the board.

---

## 3. Block diagram

```
  ┌─ from existing mixer, ×6 ────────────────────────────────────────────────┐
  │  PIN{n} ──[ 10k to AGND ]──[ buffer ]──┬──[ pad relays ]──[ SSI2164 ]──► │
  │                                         │                      ▲          │
  │                                         │                   VC{n}         │
  │                        envelope tap ────┘                      │          │
  │  ◄── SIN{n} ──[ DC servo ]──[ I–V ]────────────────────────────┘          │
  └──────────────────────────────────────────────────────────────────────────┘
                    │                                              ▲
              6× rectifier                                  6× CV filter
                    │                                              ▲
              external SPI ADC ──────┐              ┌── 74AHC541 (Vcc = VREF)
                                     ▼              ▲
                                ┌─ RP2040 ─┐   6× PWM
                                │  USB MIDI │
                                │  DIN MIDI │
                                │  tap / exp│
                                └───────────┘
                                     │
                        AC-coupled charge pump ──► bypass relay
```

---

## 4. Block specifications

### 4.1 Channel front end (×6)

| Net / part | Value | Note |
|---|---|---|
| Load to AGND | **10 kΩ** | Replicates the pot. Keeps `DC_BLOCK_VALUE`'s 31.8 Hz corner. **Verify against the real `RIN`** |
| Buffer | JFET or low-noise op-amp, unity gain | Decouples the socket contract from the VCA operating point. Also the envelope tap point |
| Envelope tap | **1 MΩ** series | ≤0.1 dB loading; shifts the corner ~1 % [D] |
| Coarse pad | 0 / −6 / −12 / −18 dB, 2-bit | Latching relays. Keeps the VCA near unity where its noise costs least |
| VCA | **SSI2164**, 2 packages — **but see `element-revisit.md`; this is now a bench decision** | R_IN 30 kΩ after the buffer (datasheet noise condition), R_OUT *compute* |
| I–V + servo | op-amp, servo corner ~1 Hz | `SIN{n}` must be **zero DC by construction** |

### 4.2 CV chain (×6) — the part that most affects the sound

Control noise is **multiplied** into audible AM at **dg/g = −3.48 per volt** [D].
This block matters more than the controller.

| | Spec |
|---|---|
| Filter | **2-pole, 200–400 Hz**, inverting multiple-feedback |
| | The MFB stage does three jobs: anti-AM filter, offset injection (second input resistor from VREF), and buffering the source from the 2164's control node. Use one stage, not three |
| Filter resistors | **≤22 kΩ** so their Johnson noise (19 nV/√Hz) stays ~13 dB under the source |
| Op-amp | OPA1644 (quad JFET, 3.3 nV/√Hz) or OPA4192 |
| Scaling | Source at 0–5 V through **~15 kΩ** into the 10 kΩ control node → ×0.4 → 2 V span and **−8 dB on all source-referred noise** [D]. *Compute exactly once §2 is resolved* |
| Reference | **MAX6126A25 with the 0.1 µF NR cap** (35 nV/√Hz) or ADR4525C/D. Shared by CV source, ADC and the '541 |
| Polarity | Positive CV **attenuates**. Unipolar 0→+V only ever attenuates — no negative rail needed for CV, and code-near-zero is both loudest and quietest |

If PWM: **12-bit, 30.5 kHz carrier** at 125 MHz → 128 µV ripple after the filter =
**0.0039 dB**, step 0.015 dB/LSB [D]. Phase-stagger the six slices so the buffer
transients don't hit the reference together. Local 1 µF + 100 nF at the '541.

### 4.3 Controller

**RP2040.** On-chip LDO, production to 2041, 16 PWM outputs, PIO if the CV
architecture changes to SPI later. Not a module — bare chip plus QSPI flash and a
crystal, so the power architecture is ours.

Control frame rate **8 kHz** (not 32 kHz — the CV filter kills the aggressor
argument; 125 µs grid is 0.12 % of a sixteenth note [D]).

Needs: USB device (MIDI), DIN MIDI in/out, tap footswitch, expression pedal in,
12 GPIO for relay drive, SPI for the ADC.

### 4.4 Envelope sensing

Six precision rectifiers → RC → **external SPI ADC placed in the analogue
section**, so only SCLK/MOSI/MISO/CS cross the analogue–digital boundary rather
than six analogue traces crossing into the digital region.

Parts: **ADS131M08** (8 simultaneous channels, one CS per read) or **MCP3564**
(SCAN mode into a FIFO). 1–2 kHz sampling is sufficient. **Detect pre-gain**, off
the buffer — post-gain makes it a feedback loop that latches shut.

### 4.5 Relay drive and fail-safe

**Coarse pad:** 12 coils (six 2-bit pads). **2× TPIC6B595** shift registers — same
"one SPI burst plus a latch pulse" discipline as everything else.

> **Highest-probability field failure in the design.** These are *level* drivers.
> Dual-coil latching relays need a 3–10 ms pulse and must then be de-energised, and
> a shift register will hold a coil energised until it burns. **Drive the register's
> OE from a one-shot (74LVC1G123)** so maximum coil-on time is set by an RC,
> independent of register contents. One 6-pin part.

**Fail-safe, two stages:**

1. MCU emits ~10 kHz on a GPIO → two-diode charge pump → MOSFET → bypass relay.
   **Any** stuck state — high, low, hi-Z, crashed, halted clock — collapses the pump
   and drops to bypass. Covers the failure a watchdog IC cannot see: firmware alive,
   CV engine wedged.
2. If the CV source is a DAC8568: supervisor reset → **CLR pin, clear-code register
   set to full scale** = maximum attenuation = hardware mute in ~1 µs, long before a
   relay can transfer (~5 ms).

> **Power-on hazard:** a DAC's POR to zero scale = 0 V = **unity gain = fail-loud**.
> The bypass relay must be de-energised (bypassed) at power-up and stay so until
> firmware has written CVs and kicked the watchdog. Same applies to PWM outputs
> idling low. **Design the power-up sequence explicitly.**

---

## 5. Constraints that must not be violated

> **Four of these five have moved. See the table at the top.** One was struck for
> having no mechanism, two were restated because they overstate what is
> achievable, and one was demoted to good practice on 59 dB of margin. The
> wording below is v0's.

From the parent doc, and they are load-bearing:

1. **The module draws nothing from `VREG`, `V+` or `V−`.**
2. **Exactly one bond** between module audio ground and board AGND. Six separate
   returns to six pin-3s, **not commoned in the module**.
3. `SIN{n}` carries **zero DC by construction**.
4. `PIN{n}` sees ~5–10 kΩ, or the 31.8 Hz corner moves.
5. Audio as individually-shielded twisted triads, shields grounded at the
   main-board end only.

---

## 6. Do not invent

If a value or part is not in this document and cannot be *derived* from it, stop
and flag it rather than choosing plausibly. Specifically do not invent: the
connector part or pinout (§1.2), the supply topology (§1.1), the SSI2164 control
port structure (§2), `RIN`, or `DC_BLOCK_VALUE`.

---

## 7. Verification expectations

The parent project's culture is that constraints live somewhere a script can see
them. Match it:

- A `verify.py` that checks the netlist against §5 — one AGND bond, no module load
  on `VREG`/`V±`, six separate returns, 10 kΩ presented at each `PIN{n}`
- Every computed value emitted with its derivation, not just its result
- A BOM with a source and a price per line
- An explicit `ASSUMPTIONS.md` listing everything that had to be guessed

---

## 8. Known-unknowns that do NOT block the spike

These affect whether it sounds good, not whether it can be drawn. Note them and
carry on:

- SSI2164 channel-to-channel crosstalk (target ≤−54 dB per pair)
- SSI2164 control-port voltage-noise density (unspecified)
- Whether the 74AHC-powered-from-a-reference topology is sound (no vendor app note)
- Whether a 250 Hz CV filter is fast enough for the gate feel