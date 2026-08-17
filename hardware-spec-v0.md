# Hardware spec v0 — per-string CV module

**Purpose:** seed document for a schematic/PCB spike. This is not a design
discussion — the discussion is in the other five files. This is the extracted,
buildable specification, with every value either stated or explicitly marked as
*compute*, and every unknown explicitly marked as *BLOCKED* or *TBD*.

Read `00-current-state.md` for why any of these choices are what they are.

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