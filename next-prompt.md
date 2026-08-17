Pick up the cv-module spike. Read CLAUDE.md, then README.md, then docs/STYLE.md.
docs/hardware-spec-v0.md is the authoritative spec — it carries an index of its
own overturned claims at the top, read that first. docs/00-current-state.md is
context for why, and two of its claims lose to delta.py, marked at its top.

The summing-mixer repo is a sibling and READ-ONLY: its boards are fabricated. It
is a hardware interface, not a code dependency — design.py, source.py and
fab/mechanical-*.json come through contract/socket.py at commit 4bc7ddb via
`git show`, and the KiCad plumbing is copied into toolchain/. The mixer's root is
never on sys.path and socket.check_no_mixer_imports() enforces it. Never write
anything under that path, and never run git from a directory containing both.

STATE — everything runs and exits 0, in this order:

python3 design.py && python3 gen_netlist.py && python3 gen_sch.py \
&& python3 gen_project.py && python3 verify.py && python3 test_verify.py \
&& python3 constraints.py && python3 delta.py && python3 floorplan.py \
&& python3 gen_bom.py && python3 gen_assumptions.py

188 parts, 138 nets. Schematic: 0 merges, 0 breaks, 0 stranded pins. verify.py
reads KiCad's own exported netlist and compares it to design.py by name and pin —
ten checks, all green. ERC: 0 errors, 6 warnings, each declared with its exact
count in verify.ERC_ALLOWED (they are the six op-amp sections reserved for the
DEFERRED envelope rectifier). test_verify.py plants 31 faults and catches all 31.
Board: not started.

TASK — is the 2-bit coarse pad worth 52% of the board?

Answer it with arithmetic, then act on the answer. It is the largest uncosted
commitment in the design: 40 of 188 parts, 52% of the placed courtyard, about a
third of the BOM cost, plus 24 coil drives and a coil supply rail that
design.RAILS does not have.

What it buys has never been computed, and ASSUMPTIONS.md says so: the SSI2164's
noise table is specified at R_IN = R_OUT, which is true only at the 0 dB step, so
the figures at -6, -12 and -18 dB do not exist anywhere in this repo.

Start here. vca_noise(rin) already varies with R_IN and moves the wrong way:
62 nV/rtHz at 12.1k rising to 123 nV/rtHz at 48.7k, where it appears to clamp at
-93 dBu. So the cells get ~6 dB noisier while the signal into them gets 18 dB
larger — about 12 dB of SNR at the -18 dB step, if that clamp is real rather than
an artefact of how vca_noise() interpolates the datasheet's four points. Check
that first; the whole decision rests on it.

Then express the benefit as system noise through delta.py's own budget, not as a
cell figure, because the answer has to be referred to one string the way every
other result in this repo is. Note it interacts with MEASURED["noise_floor"],
which is still unmeasured, so give the answer across that range rather than at
its guessed value.

If the pad stays, the relay is still not chosen and there are two constraints on
which one may be fitted, not one:
* its pins are pinned to IEC 60947 contact numbering — 11/12/14, 21/22/24,
  A1/A2/B1/B2 — see design.RELAY_PINS;
* spec 4.5's coil arithmetic does not close. It says "12 coils (six 2-bit
  pads)" driven by "2 x TPIC6B595" = 16 outputs. Twelve coils means single-coil
  latching relays, which latch by reversing coil polarity, which an open-drain
  sink cannot do. Dual-coil, as 4.1 asks, is 24 coils and 3 x TPIC6B595
  exactly. Recorded in docs/ASSUMPTIONS.md, not acted on.
  Check candidates against both before pricing, and read a datasheet rather than
  citing one.

If the pad goes, it goes properly: design.py, gen_sch.py, DEFERRED_PINS,
floorplan.py's zones, the BOM, and test_verify.py's planted faults. The pipeline
must be green again at the end, not "green except".

RULES
- Do not invent values. Section 6 of the spec lists what not to invent, and the
  relay's coil voltage is squarely in it. If it cannot be derived, stop and ask.
- Every computed value carries its derivation, in a function, not in prose.
- Record corrections in place, including how the mistake survived. That is the
  house convention and it is why this repo has been useful.
- Do not relax a check to make it pass. If a check becomes inconvenient, that is
  the check working.
- If you change verify.py, add a planted fault for the new behaviour.
- Stdlib only. No SKiDL, no third-party packages. toolchain/ is vendored and
  yours to modify; record any change in toolchain/PROVENANCE.md.
- Prose that records a decision belongs in docs/. Prose that records an
  instruction does not belong in the repo at all — two spent prompt files were
  deleted for exactly that reason, so do not add another.
- The four files marked [generated] in CLAUDE.md's layout are never hand-edited.

DONE WHEN
The pad question is answered with arithmetic that survives the noise_floor range,
the design reflects the answer, the pipeline is green end to end, and README.md's
status table and open list say where it landed.

AFTER, in order
1. The envelope rectifier time constant — not derivable from the spec. Needs an
   attack/release target from Tim, or a decision to set it by ear.
2. The fail-safe, which now has a number to wait for: design.VREF_TURN_ON_S is
   20 ms of reference turn-on, during which the '541's Vcc is ramping and zero CV
   is unity gain. Spec 4.5's fail-loud hazard, arriving by the reference.
3. The remaining shared blocks in design.DEFERRED.
4. The board — gen_pcb.py via the deprecated pcbnew bindings, as the mixer does.