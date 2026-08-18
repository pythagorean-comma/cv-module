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


def main():
    OUT.mkdir(exist_ok=True)
    root_uuid = Schematic(PROJECT).uuid
    (OUT / f"{PROJECT}.kicad_pro").write_text(
        json.dumps(project_document(root_uuid), indent=2) + "\n")
    library_tables(OUT)
    symbol_library(OUT / f"{NICK}.kicad_sym")
    print(f"out/{PROJECT}.kicad_pro, sym-lib-table, fp-lib-table, "
          f"out/{NICK}.kicad_sym")


if __name__ == "__main__":
    main()
