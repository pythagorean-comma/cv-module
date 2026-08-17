Pick up the cv-module spike. Start by reading CLAUDE.md, then README.md, then
STYLE.md. hardware-spec-v0.md is the authoritative spec and 00-current-state.md
is context for why — but note that this repo has already overturned three claims
in the latter and six in the spec, all recorded with arithmetic.

The summing-mixer repo is mounted as a sibling and is READ-ONLY: its boards are
fabricated. Read it, import from it via contract/socket.py at the pinned commit,
never write to it. Never run git from a directory containing both repos.

STATE
Everything runs and exits 0:

python3 design.py && python3 gen_netlist.py && python3 verify.py \
&& python3 test_verify.py && python3 constraints.py && python3 delta.py \
&& python3 floorplan.py && python3 gen_bom.py && python3 gen_assumptions.py \
&& python3 gen_sch.py

gen_sch.py draws all 189 parts, KiCad 10 loads the sheet, and its checker
reports 0 merges and 45 breaks.

TASK 1 — finish the schematic and close the verification loop

Not for tidiness. Today verify.py compares design.py to a netlist written from
design.py, so it cannot catch a transcription error — there is no transcription.
Once the schematic matches, point verify.py's reader at

kicad-cli sch export netlist --format kicadsexpr -o out/from-kicad.net \
out/cv-module.kicad_sch

and the comparison becomes real: geometry KiCad parsed, against design.py. That
is what CLAUDE.md's toolchain section now asks for and it makes every other
check stronger. out/from-kicad.net is regenerable — treat it as a build artefact.

**The 45 breaks are 7 bugs, not 45.** Each net family below is one geometry
error replicated across six channels:

FEN{n}  x6   front-end summing junction
RCJ{n}  x6   VCA input RC junction
IOUT{n} x6   I-V summing junction
SVN{n}  x6   servo integrator input
SRV{n}  x6   servo output
CVX{n}  x6   CV filter inner node
CVN{n}  x6   CV filter inverting input
MAGND, MDGND, RINV  x1 each, in shared_block()

37 are "not formed at all" and 8 are "wrong membership".

METHOD, and it is the only one that worked
gen_sch.py's checker prints the coordinate. Use it. Do not reason about the
geometry in the abstract — three rounds were lost moving offsets by hand and
watching a merge relocate from IOUT1 to OE to PIN1, because the report named the
nets and not the point. Run it, read the coordinate, look at the actual pin
positions with part.pin(), fix, re-run.

TRAPS ALREADY PAID FOR — expect to hit these again
1. **KiCad's Device:R and Device:C are VERTICAL at angle=0.** Use the VERT and
   HORIZ constants in gen_sch.py. Assuming angle 0 meant horizontal put every
   feedback part back in its amplifier's column and merged 34 nets into one.
2. **An op-amp's +IN and -IN are 5.08 mm apart in the same column.** A 5.08 mm
   ground drop from +IN lands its wire END on -IN. Legal junction, wrong
   circuit, invisible on the sheet.
3. **The SSI2164 puts GND (pin 8) and V- (pin 9) 2.54 mm apart on the same y.**
   Any horizontal route from one crosses the other. Use _leave_down().
4. **A part placed at exactly an amplifier's pin y** puts that pin's ground
   route along the whole component row. R{n}01 and R{n}31 both did this.
5. **A vertical Device:R spans 7.62 mm and its ground drop adds 5.08.** A 12.7
   pitch puts each ground symbol on the next resistor's top pin — a series
   chain. Use >= 20.32.
6. **A row pitch equal to a part offset** puts a part on its neighbour's row.
   C{n}42 at y-25.4 with CV_PITCH 25.4 merged all six VC nets.
7. Every coordinate must be an exact multiple of 1.27. kisch refuses otherwise,
   which is correct: an off-grid pin does not connect and the drawing does not
   say so.

RULES
- **Do not relax the checker to make it pass.** Merges are fatal for a reason:
  a merge is a different circuit that passes ERC, passes the netlist comparison,
  and looks right. If a check becomes inconvenient, that is the check working.
- test_verify.py must keep passing all 14 planted faults. If you change
  verify.py, add a planted fault for the new behaviour.
- No SKiDL and no third-party packages. Stdlib only, and the mixer's sexp.py /
  kisch.py imported read-only at the pin. CLAUDE.md's toolchain section explains
  why, and the reasoning was tested rather than inherited.
- Every value gets its derivation. If something is not in the spec and cannot be
  derived, stop and ask — §6 lists what not to invent.
- Record corrections in place, including how the mistake survived. That is the
  house convention and it is why this repo has been useful.

DONE WHEN
0 merges, 0 breaks, verify.py reading KiCad's export, test_verify.py green, and
ERC clean (kicad-cli sch erc). Then update README.md's status table.

AFTER THAT, in order
1. The pad relay: not chosen, 52% of board area and about a third of the cost.
   Its pins are pinned to IEC 60947 contact numbering, which is a constraint on
   which relay may be fitted — check candidates against that before pricing.
   Worth asking whether a 2-bit pad is worth half the board.
2. The envelope rectifier time constant — not derivable from the spec; needs an
   attack/release target or a decision to set it by ear.
3. The six shared blocks in design.DEFERRED: controller, envelope ADC, relay
   drive, fail-safe, supply.

ENVIRONMENT
KiCad 10.0.5 lives in ~/Applications, not /Applications. Don't go looking —
the mixer's kicad.py finds it, and contract/socket.py puts it on the path.