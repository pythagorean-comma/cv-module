"""Write the KiCad project scaffolding around the generated schematic.

Produces `out/cv-module.kicad_pro`, the symbol and footprint library tables, and
`out/cv.kicad_sym` -- the project library holding the five symbols this design
borrows under the `cv` nickname.

**Why this file exists, and it is not tidiness.** Without the two library tables
`kicad-cli sch erc` reports 516 violations on a sheet that has nothing wrong
with it: one `lib_symbol_issues` per symbol instance and one
`footprint_link_issues` per footprint, both saying "the current configuration
does not include" a library that KiCad ships with. That is 516 true statements
about a missing project file and zero statements about the circuit, and a report
in that state cannot be read -- the three real errors this pass fixed were found
by grepping past the noise. A check whose output nobody reads is not a check,
which is the same failure this repository keeps naming about itself.

Library paths go through KiCad's own ${KICAD10_*_DIR} variables rather than
absolute paths, so the project opens on any machine with KiCad 10 installed. The
mixer's gen_project.py does the same and for the same reason.

**The design rules, and this paragraph used to say the opposite.** It said:
*"No board design rules ... inventing clearances for a board nobody has laid
out would be six plausible numbers that DRC would then enforce ... the block is
left as KiCad's own defaults and gen_pcb.py, when it exists, is where the rules
go."* The argument was right and the description of the file was not, twice
over. There *is* a board now. And even while there was not, net_classes() below
was already writing a track width, a clearance, a via diameter and a via drill
as literals -- the six plausible numbers, in the file whose docstring said it
had declined to write them -- which then matched gen_pcb.py's own copies by
nobody's arithmetic at all.

They come from rules.py now, which is where the mixer keeps its own and where
this docstring already said the mixer keeps them. `design_settings` is still
KiCad's defaults, because gen_pcb.py sets the board's rules through pcbnew
directly and SaveBoard() would overwrite anything written here anyway -- which
is why gen_pcb.py re-runs this file afterwards, and why verify.check_rules()
reads all three off disk instead of taking any of their words for it.
"""

import json
import pathlib

import design as circuit
import rules
from toolchain import symlib
from toolchain.kisch import Schematic
from toolchain.sexp import Sym, dumps

PROJECT = "cv-module"
OUT = pathlib.Path(__file__).resolve().parent / "out"

# The project library's nickname. Anything in circuit.LIBS filed under it is
# written out here rather than pointed at a stock library.
NICK = "cv"


def net_classes():
    """One class, plus a wider one for the rails and both grounds.

    Every fabrication number here comes from rules.py; what this function
    contributes is the *grouping*, which is a design statement rather than a
    fabrication one -- the two grounds are separate classes' worth of copper
    because floorplan.py keeps them separate domains, and MDGND is in the wide
    class for the reason design.py gives at R902.

    The four that used to be literals were `clearance`, `track_width`,
    `via_diameter` and `via_drill`, and they were the same four gen_pcb.py
    declared. They agreed. Nothing made them agree.
    """
    default = {
        "bus_width": 12, "clearance": rules.CLEARANCE_MM,
        "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
        "diff_pair_width": 0.2, "line_style": 0,
        "microvia_diameter": 0.3, "microvia_drill": 0.1, "name": "Default",
        "pcb_color": "rgba(0, 0, 0, 0.000)", "priority": 2147483647,
        "schematic_color": "rgba(0, 0, 0, 0.000)",
        "track_width": rules.TRACK_MM,
        "via_diameter": rules.VIA_DIAMETER_MM,
        "via_drill": rules.VIA_DRILL_MM, "wire_width": 6,
    }
    power = dict(default, name="Power", track_width=rules.POWER_TRACK_MM,
                 priority=1, pcb_color="rgba(200, 52, 52, 0.800)")
    return [default, power]


def design_rules():
    """The constraints DRC enforces, and **they were being deleted every build.**

    This is where KiCad 10 keeps the numbers `kicad-cli pcb drc` checks against;
    the board file's own `(setup ...)` block does not carry them. gen_pcb.py
    sets them through pcbnew, SaveBoard() writes them here, and then this file
    re-runs -- because SaveBoard() also flattens everything else -- and until
    now wrote `"rules": {}` straight over the top of them.

    **So the mixer's hard-won lesson was applied in the right shape and the
    wrong direction.** build.sh upstream re-runs its project generator after
    saving precisely so the design rules survive; this repo copied the re-run
    and not the rules, and the re-run was what destroyed them. Every DRC report
    this project has produced ran with `min_track_width`, `min_via_diameter`
    and `min_copper_edge_clearance` at KiCad's defaults, which are zero.

    What was *not* wrong is the clearance, and that is worth being exact about
    rather than claiming a bigger catch than there was: DRC takes clearance
    from the net class, not from here, and net_classes() has always written
    0.2 mm. So the copper this repo has already reported as DRC-clean is
    genuinely 0.2 mm clear. What went unchecked is every rule that is not a
    clearance.

    Keys absent from this dict fall back to KiCad's defaults, so the four that
    matter are named and the rest are left alone deliberately.
    """
    return {
        "min_clearance": rules.CLEARANCE_MM,
        "min_track_width": rules.TRACK_MM,
        "min_via_diameter": rules.VIA_DIAMETER_MM,
        "min_copper_edge_clearance": rules.EDGE_CLEARANCE_MM,
    }


def project_document(root_uuid):
    """The .kicad_pro as a dict.

    Separated from writing it the way the mixer separates its own, so that a
    check can read the file on disk back and compare. Worth keeping that seam:
    the mixer records that opening a project in the GUI rewrites the whole file
    in KiCad's expanded form and drops `netclass_patterns` on the way.
    """
    return {
        "board": {"design_settings": {"drc_exclusions": [],
                                      "rules": design_rules()}},
        "boards": [],
        "cvpcb": {"equivalence_files": []},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": f"{PROJECT}.kicad_pro", "version": 3},
        "net_settings": {
            "classes": net_classes(),
            "meta": {"version": 4},
            "netclass_patterns": [
                {"netclass": "Power", "pattern": pattern}
                for pattern in ("VA+", "VA-", "V5", "VREF", "VREFN",
                                "MAGND", "MDGND", "AGND")
            ],
        },
        "pcbnew": {"last_paths": {}, "page_layout_descr_file": ""},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [[root_uuid, "Root"]],
        "text_variables": {},
    }


def library_tables(directory):
    """Point at KiCad's stock libraries plus the project's own.

    Both tables are driven off design.py -- the symbol one off LIBS, the
    footprint one off the footprints the parts actually name -- so a borrowed
    part or a new footprint library cannot be added without the table following.
    """
    used = sorted({nick for nick, _, _, _ in circuit.LIBS.values()
                   if nick != NICK})
    rows = [f'  (lib (name "{nick}")(type "KiCad")(uri '
            f'"${{KICAD10_SYMBOL_DIR}}/{nick}.kicad_sym")(options "")(descr ""))'
            for nick in used]
    rows.append(f'  (lib (name "{NICK}")(type "KiCad")(uri '
                f'"${{KIPRJMOD}}/{NICK}.kicad_sym")(options "")(descr '
                f'"Parts borrowed or not in the stock libraries"))')
    (directory / "sym-lib-table").write_text(
        "(sym_lib_table\n  (version 7)\n" + "\n".join(rows) + "\n)\n")

    footprint_libs = sorted({part.footprint.split(":", 1)[0]
                             for part in circuit.PARTS.values()
                             if part.footprint})
    rows = [f'  (lib (name "{nick}")(type "KiCad")(uri '
            f'"${{KICAD10_FOOTPRINT_DIR}}/{nick}.pretty")(options "")(descr ""))'
            if nick != NICK else
            f'  (lib (name "{NICK}")(type "KiCad")(uri '
            f'"${{KIPRJMOD}}/{NICK}.pretty")(options "")(descr '
            f'"Footprints KiCad does not ship -- see gen_project.TMR6WI"))'
            for nick in footprint_libs]
    (directory / "fp-lib-table").write_text(
        "(fp_lib_table\n  (version 7)\n" + "\n".join(rows) + "\n)\n")


def symbol_library(path):
    """The project library: every part borrowed under the `cv` nickname.

    Through design.patch_symbol, which is the whole reason that function moved
    out of gen_sch.py. The schematic embeds its own copy of every symbol in
    `lib_symbols`, so a project library patched differently from the sheet
    passes ERC, passes verify.py, and appears only as a mismatch warning when
    somebody opens the project -- the mixer's own note, and the OPA1644's
    corrected description plus the SSI2164's repinned outputs are exactly the
    kind of difference that would hide there.
    """
    library = [Sym("kicad_symbol_lib"),
               [Sym("version"), 20251024],
               [Sym("generator"), PROJECT],
               [Sym("generator_version"), "10.0"]]
    for lib_id, (nick, libname, symname, rename) in sorted(circuit.LIBS.items()):
        if nick != NICK:
            continue
        symbol = symlib.flatten(libname, symname, rename=rename)
        library.append(circuit.patch_symbol(lib_id, symbol))
    path.write_text(dumps(library) + "\n")


# ---------------------------------------------------------------------------
# The project footprint library
# ---------------------------------------------------------------------------
# **One footprint, and the argument for generating it is the argument the
# symbol library already makes one paragraph up.** KiCad ships no land pattern
# for the TMR 6WI. It ships two that look like one -- the TMR 4WI's and the
# TMR 8WI's, both with exactly the right pad pattern, 1-2-3 then the 5.08 mm
# gap where pin 4 is not, then 5-6-7-8 -- and both with a different body: the
# TMR 4WI's is 9.3 mm deep with its pin row 2.575 mm from the front edge,
# against this part's 9.1 and 3.5.
#
# Using one of those and calling it approximate is what placement.SIZE's own
# comment is about: "a rounded number is approximate, a number on the wrong
# axis is wrong", written after every multi-pin courtyard in that table turned
# out to be transposed and to have survived three passes because every
# consumer was transposed too. A silkscreen and a courtyard a millimetre out
# in one direction is the same class of thing, and the only instrument that
# would ever report it is gen_pcb.check_courtyards(), which compares this
# footprint against placement.SIZE -- both of which would be wrong together.
#
# So it is written from the outline drawing on page 4 of the datasheet, with
# every dimension a named constant carrying the number it came from.

TMR6WI = {
    "name": "TRACO_TMR-6-xxxxWI_Dual_THT",
    # Datasheet page 4, Outline Dimensions, in millimetres.
    "body": (21.8, 9.1),
    # Distance from the left body edge to pin 1, then the gaps between pins.
    # "2.0 / 2 x 2.54 / 5.08 / 3 x 2.54", which totals 21.8 with 2.02 left
    # over at the other end -- the drawing is symmetric to within its own
    # rounding and the pin string is what is dimensioned.
    "pin1_inset": 2.0,
    "pitch": 2.54,
    # The pin row's distance from the near long edge: "3.5 (0.14)".
    "pin_row_inset": 3.5,
    # Pin numbers in order along the row. There is no 4: that position is the
    # creepage gap between primary and secondary, which is why the design's
    # isolation keep-out is placed off this footprint rather than guessed.
    "pins": (1, 2, 3, None, 5, 6, 7, 8),
    # Pin cross-section is 0.50 x 0.25 mm. The hole is KiCad's own figure for
    # this family of Traco SIPs rather than a tighter one computed from the
    # pin: these are wave-soldered parts and the two stock footprints use
    # 1.0 mm and 1.1 mm.
    "drill": 1.0,
    "pad": 1.6,
}

# How far the courtyard stands off the body. KiCad's own Traco footprints use
# 0.25 mm, which is what placement.SIZE has to be told.
COURTYARD_CLEARANCE = 0.25


def _tmr6wi():
    """The TMR 6WI land pattern, as an s-expression, from its own drawing.

    Anchored on pad 1 at the origin, which is the convention every
    Converter_DCDC footprint in KiCad's library uses and therefore the one
    placement.py's ANCHOR table is already written around.
    """
    spec = TMR6WI
    length, depth = spec["body"]
    left = -spec["pin1_inset"]
    right = left + length
    top = -spec["pin_row_inset"]
    bottom = top + depth
    clear = COURTYARD_CLEARANCE
    silk = 0.11

    out = [Sym("footprint"), spec["name"],
           [Sym("version"), 20240108], [Sym("generator"), PROJECT],
           [Sym("generator_version"), "10.0"],
           [Sym("layer"), "F.Cu"],
           [Sym("descr"),
            "Traco TMR 6WI, isolated 6 W DC/DC, dual output, SIP-8 with the "
            "pin 4 position omitted. Generated from the outline drawing on "
            "page 4 of the datasheet of 7 November 2023 -- see "
            "design.SUPPLY_DATASHEET"],
           [Sym("tags"), "traco tmr6wi dcdc isolated dual sip8"],
           [Sym("attr"), Sym("through_hole")]]

    def text(kind, value, x, y, layer, hide=False):
        item = [Sym("property"), kind, value,
                [Sym("at"), x, y, 0], [Sym("layer"), layer],
                [Sym("effects"), [Sym("font"), [Sym("size"), 1, 1],
                                  [Sym("thickness"), 0.15]]]]
        if hide:
            item.insert(4, [Sym("hide"), Sym("yes")])
        return item

    out.append(text("Reference", "${REFERENCE}", (left + right) / 2,
                    top - 1.2, "F.SilkS"))
    out.append(text("Value", spec["name"], (left + right) / 2,
                    bottom + 1.2, "F.Fab"))
    out.append(text("Datasheet", "", 0, 0, "F.Fab", hide=True))
    out.append(text("Description", "", 0, 0, "F.Fab", hide=True))

    def line(x1, y1, x2, y2, layer, width):
        return [Sym("fp_line"), [Sym("start"), x1, y1], [Sym("end"), x2, y2],
                [Sym("stroke"), [Sym("width"), width], [Sym("type"),
                                                        Sym("solid")]],
                [Sym("layer"), layer]]

    def rect(x1, y1, x2, y2, layer, width):
        return [Sym("fp_rect"), [Sym("start"), x1, y1], [Sym("end"), x2, y2],
                [Sym("stroke"), [Sym("width"), width], [Sym("type"),
                                                        Sym("solid")]],
                [Sym("fill"), Sym("no")], [Sym("layer"), layer]]

    # The body on fabrication, the same body on silkscreen but broken either
    # side of the pin row so that no silk lands on a pad, and the courtyard
    # 0.25 mm outside it.
    out.append(rect(left, top, right, bottom, "F.Fab", 0.1))
    out.append(rect(left - clear, top - clear, right + clear, bottom + clear,
                    "F.CrtYd", 0.05))
    out.append(line(left, top, right, top, "F.SilkS", silk))
    out.append(line(left, bottom, right, bottom, "F.SilkS", silk))
    out.append(line(left, top, left, bottom, "F.SilkS", silk))
    out.append(line(right, top, right, bottom, "F.SilkS", silk))
    # Pin 1, marked on both layers a human reads.
    out.append(line(left - 0.6, top - 0.6, left - 0.6, top - 0.6 + 1.0,
                    "F.SilkS", silk))

    for index, number in enumerate(spec["pins"]):
        if number is None:
            continue
        x = index * spec["pitch"]
        shape = Sym("rect") if number == 1 else Sym("circle")
        out.append([Sym("pad"), str(number), Sym("thru_hole"), shape,
                    [Sym("at"), x, 0.0],
                    [Sym("size"), spec["pad"], spec["pad"]],
                    [Sym("drill"), spec["drill"]],
                    [Sym("layers"), "*.Cu", "*.Mask"],
                    [Sym("remove_unused_layers"), Sym("no")]])
    return out


def footprint_library(directory):
    """Write out/cv.pretty, the project's own footprints."""
    directory.mkdir(exist_ok=True)
    (directory / f"{TMR6WI['name']}.kicad_mod").write_text(
        dumps(_tmr6wi()) + "\n")


def main():
    OUT.mkdir(exist_ok=True)
    root_uuid = Schematic(PROJECT).uuid
    (OUT / f"{PROJECT}.kicad_pro").write_text(
        json.dumps(project_document(root_uuid), indent=2) + "\n")
    library_tables(OUT)
    symbol_library(OUT / f"{NICK}.kicad_sym")
    footprint_library(OUT / f"{NICK}.pretty")
    print(f"out/{PROJECT}.kicad_pro, sym-lib-table, fp-lib-table, "
          f"out/{NICK}.kicad_sym, out/{NICK}.pretty")


if __name__ == "__main__":
    main()
