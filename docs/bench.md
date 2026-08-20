# The bench list — what is left to measure, and what each reading decides

Generated prose is marked `[generated]` in the repo layout; **this one is
not** — it is a procedure a person follows, with the numbers it quotes taken
from the functions named beside them.

**Three measurements, and only the first can be taken today.** `noise_floor`
is a meter on hardware that already exists. The other two need this board
fabricated and populated, so they belong after the layout, not beside it.

---

## 1. `MEASURED["noise_floor"]` — the one that matters, on hardware that exists

**What:** the residual noise at the summing mixer's mono output, with the
strings damped and LEVEL at maximum, **unweighted over 20 kHz**.

**Why it is first:** everything this module claims about itself is a *delta*
against this number, and `delta.py` computes that delta rather than asserting
it. The whole declared range is live:

| measured floor | the module costs, quiescent | …while the lead feature runs |
|---|---|---|
| 50 µV | **0.79 dB** | **3.13 dB** |
| 144 µV (assumed) | 0.10 dB | 0.55 dB |
| 400 µV | 0.01 dB | 0.08 dB |

`delta.system_delta()`. A factor of eight in the measurement is a factor of
forty in the answer, and the assumed value sits in the middle of it doing no
work at all.

**How:**

1. Six channels, no input — strings damped, not unplugged, so the capsules'
   own source impedance is still on the input.
2. Every per-channel level control at the position the module will replace.
   That is the `RV{n}01` wiper setting, and it matters: `summing_stage_noise()`
   is a function of wiper position, and replacing the pot with a buffer is
   what removes the wiper's source resistance from the summer.
3. LEVEL at maximum.
4. Measure at the mono output, **unweighted, 20 Hz – 20 kHz**. Not A-weighted:
   `BANDWIDTH` is 20 kHz unweighted throughout this project and upstream, and
   an A-weighted figure compared against it is 2–3 dB of silent error.
5. Note the mains frequency and whether the reading moves when the enclosure
   is closed. A hum term and a noise term are different problems and the meter
   reports their sum.

**What to do with it:** set `MEASURED["noise_floor"].value` and re-run the
pipeline. Three things move on their own: `delta.py`'s whole table,
`barrier_return()`'s margin, and `check_settled()`'s two retirements — which
is deliberate, because a much lower floor is exactly what would make the
barrier residual load-bearing again.

**And one decision is waiting on it with a number attached.** If the floor
measures **below 81 µV**, `R_IN` should move from 12k1 to 7.5 kΩ: that is
where the change first reaches half a decibel at the system output while
gating. Above 81 µV it is worth less than that and is not worth an
unquantified distortion cost. `delta.rin_sensitivity()`, solved for the floor.

---

## 2. `MEASURED["mcu_dcdc_efficiency"]` — one ammeter, after the board exists

**What:** what **U22** draws from `VA_RAW` while delivering `VMOD`.

**Why the datasheet cannot answer it:** SLVSE22B gives efficiency as plotted
curves — section 7.8, at 8, 12, 24 and 36 V in — and a number read off a
plotted curve is not a reading.

**How:** break `VA_RAW` at U22's VIN pin and put an ammeter in series.
Measure with the module running and the relays **energised**, which is the
loaded state: `VMOD` carries 163.7 mA of which **92.7 mA is relay coil**.
Efficiency is `(5 V × I_VMOD) / (12 V × I_VIN)`.

**What it decides — less than it used to, and that is the point.**
`mcu_supply().u22_floor` is **53 %**, with the module at its own pessimistic
end, against a declared range starting at 75. The worst corner fits with
37 mA of +Vout to spare. This is a confirmation, not a gate.

---

## 3. `MEASURED["pico_smps_efficiency"]` — the second ammeter

**What:** what the Pico draws from `VSYS` at this board's 3.3 V load.

**How:** ammeter in series with the module's VSYS pin, **with GPIO23 high** —
that is the RT6150's power-save pin and the module's default is PFM, whose
switching rate falls with load. Forced PWM is the state this design runs in
and the state its efficiency figures belong to. Expect about **70.9 mA at
4.72 V** at the worst corner.

**What it decides:** `mcu_supply().module_floor` is **45 %** with U22 at its
own pessimistic end, against a declared range starting at 86.

**And it is not a threshold on a product**, whatever three earlier documents
said. **57 % of VMOD's power is relay coil**, which passes through U22 and
never through the module's own converter, so the two stages are not in series
for most of the load. Two thresholds, weighted differently, and neither is
close.

---

## What is *not* on this list, and why

**`env_opamp_iq` is closed** — not measured, read. The row was on page 16 of
SLOS080W all along, in section 5.8 continued across a page break: *"I_Q,
quiescent current per amplifier, V_O = 0 V, no load: 1.4 typ, 2.5 max, mA"*.
Both figures the repo had been carrying, one unsourced and one called an
envelope, are the datasheet's own.

**`dcdc_node_v` and `inlet_loop_uh` are retired** — still guesses, and no
value in either range changes anything. `design.SETTLED` holds the claim and
`design.check_settled()` recomputes it on every build, so the retirement
expires if the design ever makes one load-bearing again. `inlet_loop_uh` is
the worked example in both directions: it was load-bearing until `L801` was
fitted, and would be again the day the choke came off.

They would still be *interesting* to measure. They are simply not worth a
bench trip, which is a different statement from being known.

---

## The ordering, stated once

```
noise_floor  ──► R_IN at 12k1 or 7k5      (81 µV is the trigger)
             └─► every delta.py figure
             └─► check_settled()'s margin

  [fabricate, populate]

U22 VIN  ──┐
           ├─► mcu_supply(), which already fits at both floors
Pico VSYS ─┘
```

`noise_floor` is one meter reading and it gates a component value. The other
two are confirmations of a budget that closes at every declared corner with
37 mA to spare.
