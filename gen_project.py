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

**No board design rules.** The mixer's version of this file carries a full
`design_settings` block from its rules.py, because it has a board. This module
does not have one yet, and inventing clearances for a board nobody has laid out
would be six plausible numbers that DRC would then enforce -- section 6's rule,
applied to a file format instead of a resistor. The block is left as KiCad's own
defaults and gen_pcb.py, when it exists, is where the rules go.
"""

import json
import pathlib

import design as circuit
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

    Track widths are absent for the same reason the design rules are: there is
    no board. What the classes do carry is the *grouping*, which is a design
    statement rather than a fabrication one -- the two grounds are separate
    classes' worth of copper because floorplan.py keeps them separate domains,
    and MDGND is in the wide class for the reason design.py gives at R902.
    """
    default = {
        "bus_width": 12, "clearance": 0.2, "diff_pair_gap": 0.25,
        "diff_pair_via_gap": 0.25, "diff_pair_width": 0.2, "line_style": 0,
        "microvia_diameter": 0.3, "microvia_drill": 0.1, "name": "Default",
        "pcb_color": "rgba(0, 0, 0, 0.000)", "priority": 2147483647,
        "schematic_color": "rgba(0, 0, 0, 0.000)", "track_width": 0.25,
        "via_diameter": 0.6, "via_drill": 0.3, "wire_width": 6,
    }
    power = dict(default, name="Power", track_width=0.5, priority=1,
                 pcb_color="rgba(200, 52, 52, 0.800)")
    return [default, power]


def project_document(root_uuid):
    """The .kicad_pro as a dict.

    Separated from writing it the way the mixer separates its own, so that a
    check can read the file on disk back and compare. Worth keeping that seam:
    the mixer records that opening a project in the GUI rewrites the whole file
    in KiCad's expanded form and drops `netclass_patterns` on the way.
    """
    return {
        "board": {"design_settings": {"drc_exclusions": [], "rules": {}}},
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
