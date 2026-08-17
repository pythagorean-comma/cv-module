Pick up the cv-module spike. Read CLAUDE.md, then README.md, then docs/STYLE.md.
docs/hardware-spec-v0.md is the authoritative spec — it carries an index of its
own overturned claims at the top, read that first. docs/00-current-state.md is
context; three of its claims lose to delta.py, marked at its top.

The summing-mixer repo is a sibling and READ-ONLY: its boards are fabricated. It
is a hardware interface, not a code dependency — design.py, source.py and
fab/mechanical-*.json come through contract/socket.py at commit 4bc7ddb via
`git show`, and the KiCad plumbing is copied into toolchain/. The mixer's root is
never on sys.path and socket.check_no_mixer_imports() enforces it. Never write
anything under that path, and never run git from a directory containing both.

STATE — everything runs and exits 0, in this order:

python3 design.py && python3 gen_netlist.py && python3 gen_sch.py \
&& python3 gen_project.py && python3 placement.py && python3 gen_pcb.py \
&& python3 verify.py && python3 test_verify.py \
&& python3 constraints.py && python3 delta.py && python3 floorplan.py \
&& python3 gen_bom.py && python3 gen_assumptions.py

225 parts, 144 nets, 644 pin connections. Schematic: 0 merges, 0 breaks, 0
stranded pins. ERC: 0 errors and 0 warnings — verify.ERC_ALLOWED is empty, and
emptying it is recorded there as the check earning its keep. verify.py runs
fifteen checks against KiCad's own netlist and its own DRC report; all green.
test_verify.py plants 50 faults and catches all 50.

Board: placed, poured and 86% routed. 222 footprints and 3 reserved courtyards
(the bypass relays are UNSPECIFIED), 101.4 x 187.8 mm, four layers, ground split
at y = 157.4 with MAGND north and MDGND south. 104 ground pads stitched to the
planes, 1031 track runs, 293 vias. DRC: 0 violations, 67 unconnected items,
pinned in verify.UNROUTED_ITEMS.

gen_pcb.py runs under the ordinary interpreter and relaunches itself under
KiCad's bundled Python (pcbnew is SWIG and lives nowhere else), then re-runs
gen_project.py because SaveBoard() rewrites the project with KiCad's defaults.
It takes about 30 s; kicad-cli pcb drc takes another 10.

TASK — finish the routing.

23 nets are unrouted and gen_pcb.py names them on every run: CVN1 CVN4 ENVN2
ENVN4 ENVN6 FEN1 FEN6 HW2 HW3 HWN1 HWN4 IOUT1 IOUT4 IOUT5 SVN1 SVN4 SVN5 VA+
VA- VC2 VC3 VC5 VREF. They are not scattered — they are the op-amp summing
junctions and the two rails, which is where a grid router runs out of room.

The mechanism is in route.py's own comments: a SOIC pin has a neighbour 1.27 mm
away on each side, so on the 0.5 mm grid there is no cell between them and every
route has to escape outward through the same corridor. Two ways out, and the
first is a decision rather than a technique:

* a finer grid with thinner track. The pitch is derived from the design rules in
  gen_pcb.py (TRACK_MM 0.25, CLEARANCE_MM 0.2), not chosen, so this is a
  fab-capability question — read a real fabricator's published process spec
  rather than assuming what it allows, and say which one. Cost per class matters
  as much as the minimum;
* rip-up and retry in route.py, which it does not do and says so.

Derive which, then do it. If the answer is the finer grid, the design rules move
and gen_project.py must move with them — check_rules() is what holds the two
together.

RULES
- Do not invent values. Section 6 of the spec lists what not to invent. A
  fabricator's minimum track width is a reading, not a guess.
- Every computed value carries its derivation, in a function, not in prose.
- Record corrections in place, including how the mistake survived. That is the
  house convention and it is why this repo has been useful.
- Do not relax a check to make it pass. verify.UNROUTED_ITEMS goes DOWN or the
  build fails; DRC violations stay at zero throughout. A router that trades
  shorts for finished connections is worse than one that gives up and says so.
- If you change verify.py, add a planted fault for the new behaviour.
- Stdlib only. placement.py and route.py import no KiCad and must not start —
  arithmetic that only runs inside KiCad's interpreter is arithmetic nobody can
  check.
- Prose that records a decision belongs in docs/. Prose that records an
  instruction does not belong in the repo at all.
- The four files marked [generated] in CLAUDE.md's layout are never hand-edited.

DONE WHEN
verify.UNROUTED_ITEMS is 0 with DRC still at 0, the pipeline is green end to
end, and README.md's status table says where it landed. If some connections
genuinely cannot be routed at the chosen rules, say which and why with the
arithmetic, and leave the count declared rather than hidden.

AFTER, in order
1. The three deferred blocks in design.DEFERRED: controller (RP2040), envelope
   ADC (ADS131M08 or MCP3564 — its sample rate is already derived at 2 kHz, and
   1 kHz fails), and the supply. The supply now has a hard number to meet:
   design.coil_budget() says the bypass relays draw 75-120 mA continuously on
   V5, against 78 mA for every amplifier and VCA on the board.
2. The two UNSPECIFIED parts, each declared by the property that filters it
   rather than by a guess: the bypass relay (non-latching signal DPDT, 5 V coil,
   IEC 60947 contact numbering) and its MOSFET (Vgs(th) <= 1.0 V, which
   pump_timing() computes rather than prefers). Choosing them empties
   design.UNSPECIFIED and releases the three reserved courtyards on the board.
3. MEASURED["noise_floor"] — the mixer's own unmeasured figure and still this
   module's most load-bearing unknown. It decides whether the module costs
   0.11 dB or 0.85 dB quiescent, and 0.51 dB or 2.95 dB while the lead feature
   is running.
4. The one assumption with the least slack behind it: the Schottky forward drop,
   assumed at 0.3 V and read from nothing. clamp_gain() gives +7.4 dB against
   the mixer's 7.84 dB of headroom, so 0.4 V clips the summer on the fault the
   clamp exists to prevent. One curve, at 10 uA and 25 C.