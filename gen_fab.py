"""The fabrication package: what a fabricator receives, and what it must not.

    python3 gen_fab.py            # write fab/
    python3 gen_fab.py --verify   # is the tracked package a package of the
                                  # tracked board?

**This file exists because a decision was taken, and it is worth writing down
which one.** `gen_plots.orderable()` has read the gate off `design.py` and
`verify.py` since it was written -- parts with no footprint, blocks not drawn,
connections not routed -- and it returns nothing now. That did not make a
fabrication package appear, and the previous pass was right that it should not:
what was left was not a gate but a choice, and the repository said so rather
than quietly acquiring a `fab/`. The choice has now been made.

**What a package is, and where the numbers come from.** Every argument below
comes from the file that already owns it -- the layer set from the board, the
class and the stackup from `rules.py`, the hole rules from `rules.hole_rules()`
-- and nothing here is typed a second time. Where a fabricator's convention is
involved, the convention is the sibling's, because `../summing-mixer` has
ordered boards and this repository has not:

  * **one combined drill file**, PTH and NPTH together, which is what fabs
    expect and is what `--excellon-separate-th` would undo;
  * **the layer set is copper, mask, paste, silk and outline -- and nothing
    else.** A blanket export also writes `F.Fab`, `F.CrtYd` and the user
    layers, and **`F.Fab` carries a second closed board outline**: if CAM picks
    that one up instead of `Edge.Cuts` the board comes back the wrong shape.
    That is the sibling's finding and it is the one mistake in this file that
    would not be caught by anything downstream;
  * **an empty layer is worse than a missing one**, because it is a decision a
    CAM operator has to stop and make. The sibling shipped an empty `B.SilkS`
    for the life of its design, in two zips, while its own order note said
    silkscreen was top only.

**And the empty-layer rule is enforced here rather than declared**, which is
the one place this file deliberately does not follow the sibling. There, the
layer list is written down and a separate check asserts that the back
silkscreen is empty -- two artefacts that have to agree. Here `package_layers()`
exports the candidate set, **reads each file back**, and drops the ones with no
image in them, so the answer is a measurement of this board rather than a claim
about it. If somebody puts a legend on the back tomorrow the layer returns by
itself; if the sibling's arrangement had done that, its own `B.SilkS` finding
could not have happened.

**The package is tracked as loose files and the zip is not**, which inverts the
sibling and is deliberate. There, `fab/<board>-pcbway.zip` is tracked and the
staging directory is ignored, because the archive is built by `zip`, which
*updates* rather than replaces -- a layer that stops being generated stays in
the archive for ever, which is exactly the bug that file's own comment records.
Here the archive is written by `zipfile` from a directory that is rebuilt, so
that failure is not available; what is left is which artefact deserves a
history. The gerbers are text, they diff, and `PDF_EPOCH`'s argument applies to
them unchanged -- normalised, each is a function of the board and of nothing
else, measured. A zip's bytes additionally depend on the zlib that built it, so
tracking it would put a machine into the history of a board.

**Timestamps, and the same six lines PDF_EPOCH spends.** Two exports of one
board differ in exactly four places -- `%TF.CreationDate` in every gerber, the
`G04 Created by KiCad ... date` comment, the two `date` lines in the Excellon
header, and `CreationDate` in the `.gbrjob` -- and in nothing else, measured.
Left alone, a tracked package is rewritten by every build whether or not the
board moved. `FAB_EPOCH` is that substitution. Unlike a PDF's, these are text
files with no byte offsets in them, so the replacement need not preserve
length; and unlike a PDF's, this one is *read by a person at a fabricator*, so
it is the reproducible-builds epoch rather than a fake plausible date.

**What this file will not do is decide an order.** Surface finish, mask and
silkscreen colour, electrical test, panelisation, IPC class and delivery format
are order-form choices, and not one of them is derivable from anything in this
repository. `ORDER.md` lists them as open rather than filling them in, for the
same reason `ASSUMPTIONS.md` exists: a package that looks complete and has a
guess in it is worse than one that says what it does not know.
"""

import collections
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

import design
import gen_plots
import rules
import verify
from toolchain import kicad

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"
FAB = HERE / "fab"
PROJECT = "cv-module"
BOARD = OUT / f"{PROJECT}.kicad_pcb"
ZIP = FAB / f"{PROJECT}-{rules.FABRICATOR.lower()}.zip"
POS = FAB / f"{PROJECT}-pos.csv"
NOTES = FAB / "ORDER.md"

# The layers a fabricator is *never* sent, with the reason attached to each so
# that adding one back is an argument rather than an edit. This is a denial
# list and not the package: what goes in the package is derived in
# package_layers() from what the board has on it.
NEVER = {
    "F.Fab": "carries a second closed board outline -- CAM picking it up "
             "instead of Edge.Cuts returns the wrong board shape",
    "B.Fab": "as F.Fab",
    "F.CrtYd": "courtyards are a placement check, not a manufacturing layer",
    "B.CrtYd": "as F.CrtYd",
    "User.Drawings": "gen_pcb.py draws reserved courtyards here; there are "
                     "none left, and it is not a manufacturing layer either",
    "User.2": "krt.py's keep-out geometry lives here between runs",
    "User.Comments": "notes to ourselves",
}

# Every timestamp KiCad stamps into a gerber, a drill file or a job file,
# rewritten to this. The reproducible-builds epoch, in each file's own format.
#
# See the module docstring: two exports of an unchanged board differ here and
# nowhere else, measured, so this is what makes a tracked package a function of
# the board rather than of the clock.
FAB_EPOCH_ISO = "1970-01-01T00:00:00+00:00"
FAB_EPOCH_PLAIN = "1970-01-01 00:00:00"


def _run(*arguments):
    result = subprocess.run([str(kicad.KICAD_CLI), *arguments],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"kicad-cli {' '.join(arguments[:3])} failed:\n"
                         f"{result.stdout}\n{result.stderr}")
    return result.stdout


def normalise(path):
    """Replace every creation timestamp, so the file is a function of the board.

    Four shapes, and they are listed rather than pattern-matched loosely
    because a regex broad enough to catch a date is broad enough to eat a
    coordinate:

        %TF.CreationDate,2026-08-20T23:27:55+01:00*%     gerber, X2 attribute
        G04 Created by KiCad (PCBNEW 10.0.5) date ...*   gerber, comment
        ; DRILL file KiCad 10.0.5 date 2026-...          Excellon, header
        "CreationDate": "2026-08-20T23:27:55+01:00"      .gbrjob, JSON

    Returns how many substitutions were made, so that a caller can notice a
    file that has stopped carrying one -- a KiCad that changed its header is a
    thing to look at, not to silently pass through.
    """
    text = path.read_text()
    total = 0
    text, count = re.subn(r"(TF\.CreationDate,)[0-9T:+\-]+",
                          r"\g<1>" + FAB_EPOCH_ISO, text)
    total += count
    text, count = re.subn(r"(date )\d{4}-\d\d-\d\d \d\d:\d\d:\d\d",
                          r"\g<1>" + FAB_EPOCH_PLAIN, text)
    total += count
    text, count = re.subn(r"(date )\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d",
                          r"\g<1>" + FAB_EPOCH_ISO[:19], text)
    total += count
    text, count = re.subn(r'("CreationDate": ")[^"]+', r"\g<1>" + FAB_EPOCH_ISO,
                          text)
    total += count
    path.write_text(text)
    return total


def has_image(path):
    """Does this gerber draw anything at all?

    An aperture list with nothing flashed through it is a file full of header,
    and a file full of header in a fabrication package is a decision somebody
    at the fabricator has to stop and make. The test is a coordinate line or a
    flash, which is what every drawn object comes down to whatever the aperture
    macros above it say.
    """
    for line in path.read_text().splitlines():
        if re.match(r"^(X-?[\d.]+|Y-?[\d.]+|D0[123])", line):
            return True
    return False


def candidate_layers(board=BOARD):
    """The layer set to try, before the board is asked what it actually has.

    Copper comes from gen_plots.copper_layers(), which reads the board -- the
    sibling's reason and a good one: it builds a two-layer board as well as a
    four-layer one, and a package naming In1/In2 on a two-layer board is either
    an error or two empty files.
    """
    copper = gen_plots.copper_layers(board).split(",")
    return [*copper, "F.Mask", "B.Mask", "F.Paste", "B.Paste",
            "F.SilkS", "B.SilkS", "Edge.Cuts"]


def package_layers(board=BOARD, scratch=None):
    """Which layers go, decided by exporting them and reading them back.

    Returns (layers, dropped), where dropped maps a layer name to the reason it
    is not in the package. The only reason available here is "the board draws
    nothing on it", because everything that is excluded on principle is in
    NEVER and never becomes a candidate.

    **This is a measurement and not a list**, which is the whole point. The
    sibling keeps its layer list in build.sh and asserts separately that the
    back silkscreen is empty; that arrangement is what let an empty B.SilkS
    ship for the life of the design, because the list and the check are two
    artefacts and only one of them was consulted when the list was written.
    """
    with tempfile.TemporaryDirectory() as default:
        scratch = pathlib.Path(scratch or default)
        candidates = candidate_layers(board)
        _run("pcb", "export", "gerbers", "--layers", ",".join(candidates),
             "-o", str(scratch) + "/", str(board))
        layers, dropped = [], {}
        for layer in candidates:
            plotted = _plotted_file(scratch, layer)
            if plotted is None:
                dropped[layer] = "KiCad plotted no file for it at all"
            elif has_image(plotted):
                layers.append(layer)
            else:
                dropped[layer] = ("the board draws nothing on it, and an empty "
                                  "layer in a package is a question for a CAM "
                                  "operator")
        return layers, dropped


# KiCad's own file name for each layer, which is not the layer name and is not
# derivable from it -- "F.SilkS" plots as "F_Silkscreen". Read off the export
# rather than tabulated: the directory is the authority on what it wrote.
def _plotted_file(directory, layer):
    stem = layer.replace(".", "_")
    for path in sorted(directory.iterdir()):
        if path.stem.endswith(f"-{stem}"):
            return path
    alias = {"F.SilkS": "F_Silkscreen", "B.SilkS": "B_Silkscreen"}.get(layer)
    if alias:
        for path in sorted(directory.iterdir()):
            if path.stem.endswith(f"-{alias}"):
                return path
    return None


def export(destination, board=BOARD, layers=None):
    """Write the whole package into a directory and normalise every timestamp.

    Returns the layer decision, so that main() and check_package() report the
    same thing without asking twice.
    """
    destination.mkdir(parents=True, exist_ok=True)
    if layers is None:
        layers, dropped = package_layers(board)
    else:
        dropped = {}
    _run("pcb", "export", "gerbers", "--layers", ",".join(layers),
         "-o", str(destination) + "/", str(board))
    # One combined file, PTH and NPTH together: --excellon-separate-th is what
    # would split them and fabs expect them joined. The file declares which is
    # which through its own X2 attributes -- TA.AperFunction, Plated/NonPlated
    # -- so nothing is lost by combining them, which is why the convention is
    # the convention.
    _run("pcb", "export", "drill", "--format", "excellon",
         "--drill-origin", "absolute", "--excellon-units", "mm",
         "--excellon-zeros-format", "decimal",
         "-o", str(destination) + "/", str(board))
    # The placement list is written here rather than in main() so that
    # --verify covers it. It carries no timestamp -- checked -- so it is a
    # function of the board already; what it needs is somebody comparing it,
    # and a file left out of the comparison is a file that can go stale
    # silently. --exclude-dnp is the sibling's load-bearing flag: there it
    # keeps seven 0R links off the list an assembler works from. Here it
    # excludes nothing today, counted, and it is passed anyway because the day
    # it starts excluding something is not a day anybody will remember this.
    _run("pcb", "export", "pos", "--format", "csv", "--units", "mm",
         "--exclude-dnp", "-o", str(destination / POS.name), str(board))
    for path in sorted(destination.iterdir()):
        if path.suffix.lower() in (".zip", ".md", ".csv"):
            continue
        normalise(path)
    summary = drill_summary(destination / f"{PROJECT}.drl")
    (destination / NOTES.name).write_text(
        order_notes(layers, dropped, summary, board, destination))
    return layers, dropped


def drill_summary(path):
    """The tools and hits in the Excellon file, read back out of it.

    A drill file is the one artefact in the package whose content can be
    checked against the board by counting rather than by comparing bytes, and
    check_holes() is that check. This returns what it needs: each tool's
    diameter, whether it is plated, and how many hits it takes.
    """
    tools, order, plated = {}, [], {}
    current, function = None, None
    for line in path.read_text().splitlines():
        attribute = re.match(r"; #@! TA\.AperFunction,(\w+)", line)
        if attribute:
            function = attribute.group(1)
            continue
        definition = re.match(r"^T(\d+)C([\d.]+)$", line)
        if definition:
            index = definition.group(1)
            tools[index] = float(definition.group(2))
            plated[index] = function != "NonPlated"
            order.append(index)
            continue
        selection = re.match(r"^T(\d+)$", line)
        if selection:
            current = selection.group(1)
            continue
        if current and re.match(r"^X-?[\d.]+", line):
            order.append(current)
    hits = collections.Counter(index for index in order if index in tools)
    for index in tools:
        hits[index] -= 1                      # its own definition line
    return [{"tool": f"T{index}", "diameter": tools[index],
             "plated": plated[index], "hits": hits[index]}
            for index in sorted(tools, key=int)]


def board_holes(board=BOARD):
    """Every hole the board has, counted off the board itself.

    Vias, plated through-hole pads and unplated ones -- the three things that
    become a drill hit. Counted here so that check_holes() compares two
    independent readings rather than one reading against itself.
    """
    text = board.read_text()
    return {
        "vias": len(re.findall(r"^\t\(via$", text, re.M)),
        "thru_hole": len(re.findall(r'\(pad "[^"]*" thru_hole', text)),
        "np_thru_hole": len(re.findall(r'\(pad "[^"]*" np_thru_hole', text)),
    }


def check_holes(board=BOARD, drill=None):
    """Does the drill file drill this board's holes? A count, not a hash.

    **The one check here that is not a byte comparison**, and it is worth the
    lines for that reason: `--verify` proves the package was made from the
    tracked board, and this proves the package is *right about* it. They fail
    differently -- a wrong export option that dropped every unplated hole would
    pass a byte comparison against itself for ever.

    A slot would break this arithmetic, deliberately: KiCad emits an oval as a
    routed path rather than a hit, so a board that grows one arrives here as a
    mismatch with a name on it rather than as a silently short drill file.
    """
    holes = board_holes(board)
    expected = holes["vias"] + holes["thru_hole"] + holes["np_thru_hole"]
    summary = drill_summary(drill)
    counted = sum(tool["hits"] for tool in summary)
    problems = []
    if counted != expected:
        problems.append(
            f"{drill.name} takes {counted} hits and the board has "
            f"{holes['vias']} vias, {holes['thru_hole']} plated and "
            f"{holes['np_thru_hole']} unplated through-hole pads = {expected}")
    unplated = sum(tool["hits"] for tool in summary if not tool["plated"])
    if unplated != holes["np_thru_hole"]:
        problems.append(
            f"{drill.name} marks {unplated} hits unplated and the board has "
            f"{holes['np_thru_hole']} unplated pads -- a mounting hole plated "
            f"by mistake is a short to whatever pours around it")
    smallest = min(tool["diameter"] for tool in summary)
    if smallest < rules.VIA_DRILL_MM - 1e-9:
        problems.append(
            f"{drill.name} asks for a {smallest:.3f} mm hole against "
            f"rules.VIA_DRILL_MM = {rules.VIA_DRILL_MM}")
    return problems


def write_zip(directory, destination):
    """The archive a fabricator is uploaded, built so its bytes are the board's.

    Fixed member order, fixed timestamps, fixed permissions and fixed
    compression -- everything a zip records about *when* and *where* it was
    built rather than about what is in it. The sibling shells out to `zip` and
    tracks the result; the note against it there is that `zip` updates an
    archive in place, so a file that stops being generated never leaves the
    package. Rebuilding from a directory that was itself rebuilt is the fix,
    and it is why this one can be thrown away rather than tracked.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for path in sorted(directory.iterdir()):
            # The archive is what a *fabricator* is given: copper, mask,
            # paste, silk, outline, drill and the order note. The placement
            # list is an assembly upload and goes separately -- a CPL inside a
            # gerber zip is one more file for a CAM operator to have an
            # opinion about, which is the same argument the empty-layer rule
            # makes one artefact along.
            if path.is_dir() or path.suffix.lower() in (".zip", ".csv"):
                continue
            info = zipfile.ZipInfo(path.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return destination


def placement_sides(board=BOARD):
    """Which side each footprint is on, and how many are marked DNP.

    Both are counted off the board rather than asserted in the order note. The
    sidedness decides whether B.Paste can be absent honestly; the DNP count
    decides whether --exclude-dnp is doing anything, and a flag whose effect
    nobody has measured is a flag somebody will delete.
    """
    text = board.read_text()
    sides = collections.Counter(
        re.findall(r'\t\(footprint "[^"]+"\n\t\t\(layer "([^"]+)"\)', text))
    return {"sides": dict(sides),
            "dnp": len(re.findall(r"\(dnp yes\)", text))}


def board_thickness(board=BOARD):
    """What the board file tells a fabricator it is, which is a third number.

    `rules.FAB_STACKUP` sums to the bare construction, `rules.FAB_FINISHED_MM`
    is what the fabricator publishes for it, and `(general (thickness ...))` is
    what KiCad writes into the job file's `BoardThickness` -- the one of the
    three a CAM operator reads. It is KiCad's default here rather than either
    of ours, and ORDER.md says so rather than this file silently editing a
    board nothing else is allowed to edit.
    """
    found = re.search(r"\(thickness ([\d.]+)\)", board.read_text())
    return float(found.group(1)) if found else None


def order_notes(layers, dropped, summary, board=BOARD, directory=None):
    """fab/ORDER.md -- what to order, and what this repository has not decided.

    Generated, because every number in it is owned somewhere else and a
    transcribed table is a table that goes stale. The open list at the end is
    the point of the document: those are order-form fields, none of them is
    derivable from anything here, and a package that filled them in with
    something plausible would be exactly the failure ASSUMPTIONS.md exists to
    prevent.
    """
    holes = rules.hole_rules()
    hole_to_hole = holes["min_hole_to_hole"]
    hole_to_copper = holes["min_hole_clearance"]
    stackup = "".join(
        f"| {name} | {kind} | {thickness:.4f} | "
        f"{'—' if dk is None else f'{dk:.2f}'} |\n"
        for name, kind, thickness, dk in rules.FAB_STACKUP)
    files = "".join(f"| `{path.name}` | {what} |\n" for path, what in
                    _file_roles(layers, directory or FAB))
    holes = "".join(
        f"| {tool['tool']} | {tool['diameter']:.3f} | "
        f"{'plated' if tool['plated'] else '**unplated**'} | {tool['hits']} |\n"
        for tool in summary)
    left_out = "".join(f"* **{layer}** — {why}\n"
                       for layer, why in sorted(dropped.items()))
    never = "".join(f"* **{layer}** — {why}\n"
                    for layer, why in sorted(NEVER.items()))
    thickness = board_thickness(board)
    placed = placement_sides(board)
    dnp = placed["dnp"]
    holes_pth = board_holes(board)["thru_hole"]
    sides = ", ".join(
        f"**{count} of {sum(placed['sides'].values())} parts on "
        f"{'the top' if layer == 'F.Cu' else 'the bottom'}**"
        for layer, count in sorted(placed["sides"].items()))
    return f"""# Ordering this board

**Generated by `gen_fab.py`. Every number here is owned by the file named
beside it** — edit that file, not this one.

Upload `{ZIP.name}`. It is **not** tracked — the loose files beside it are, and
the archive is built from exactly them, so `python3 gen_fab.py` is what puts it
back in a fresh checkout. Uploading the loose files instead is the same set.

## The board

| | |
|---|---|
| fabricator this is dimensioned for | **{rules.FABRICATOR}** — `rules.FABRICATOR` |
| size | **{_extent(board)}** |
| layers | **{len([l for l in layers if l.endswith('.Cu')])} copper** |
| outer copper | **{rules.COPPER_OZ} oz** — `rules.COPPER_OZ` |
| track / clearance | **{rules.TRACK_MM:.2f} / {rules.CLEARANCE_MM:.2f} mm** — `rules.TRACK_MM`, `rules.CLEARANCE_MM` |
| smallest via | **{rules.VIA_DIAMETER_MM:.1f} / {rules.VIA_DRILL_MM:.1f} mm** — `rules.VIA_DIAMETER_MM` |
| hole to hole / hole to copper | **{hole_to_hole:.3f} / {hole_to_copper:.3f} mm** — `rules.hole_rules()` |
| finished thickness | **{rules.FAB_FINISHED_MM} mm** — `rules.FAB_FINISHED_MM` |

**The thickness is stated here because the package states a different one.**
`{PROJECT}-job.gbrjob` carries `BoardThickness: {thickness}`, which is KiCad's own
`(general (thickness ...))` field. It is neither `rules.FAB_FINISHED_MM` = {rules.FAB_FINISHED_MM},
what {rules.FABRICATOR} publishes for this construction, nor the {rules.stackup_thickness():.3f} mm the
stackup rows sum to, which is the same construction without solder mask. It is
KiCad's own default, and nothing in this repository owned it until this file
read it.
**Order to the figure in the table above.**

## The stackup

`rules.FAB_STACKUP`, and `verify.check_stackup()` holds the board to it.

| layer | kind | thickness mm | Dk |
|---|---|---|---|
{stackup}
## What is in the package

| file | what it is |
|---|---|
{files}
### Left out because the board draws nothing on them

{left_out or "* nothing — every candidate layer had an image on it\n"}
### Left out on principle

{never}
## The drilling

One combined file, plated and unplated together, each tool carrying its own
`TA.AperFunction` attribute. `gen_fab.check_holes()` counts these against the
board: {sum(t['hits'] for t in summary)} hits against {board_holes(board)['vias']} vias, {board_holes(board)['thru_hole']} plated and {board_holes(board)['np_thru_hole']} unplated through-hole pads.

| tool | diameter mm | plating | hits |
|---|---|---|---|
{holes}
## Assembly, if it is ordered

{sides}, and {holes_pth} plated through-hole pads are hand work whoever does
them.

* bill of materials: `out/{PROJECT}-bom.csv` — `gen_bom.py`, with MPNs
* placements: `fab/{POS.name}` — `kicad-cli pcb export pos`, `--exclude-dnp`,
  which excludes **{dnp}** parts on this board: counted, not assumed, so the
  CPL and the BOM agree for a reason
* what to buy and from where: `docs/SHOPPING.md`

## What this repository has **not** decided

None of these is derivable from anything in this project, so none of them is
filled in. They are order-form fields and they are a person's to choose:

* **surface finish** — the job file says `Finish: None`, which is KiCad
  reporting that nobody set one, not a specification of bare copper;
* **solder mask colour** and **silkscreen colour**;
* **electrical test** — worth pricing at {sum(t['hits'] for t in summary)} holes
  and {len(design.NETS)} nets;
* **panelisation or single boards**, and whether the fabricator may add rails;
* **IPC class**, and any impedance control — there is none on this board:
  `constraints.board_coupling()` is the only figure that reads the stackup and
  it has 60 dB of margin;
* **quantity, lead time and shipping**.

## Before ordering

`verify.py` must pass on the board this package was made from. It is the only
thing that says the copper is legal, the netlist is the design's, the ground
split is intact and both isolation barriers hold. `gen_fab.py --verify` says
the package is a package of *that* board and not of an older one.
"""


def _file_roles(layers, directory=FAB):
    """Each file in the package, with a sentence about what it is for."""
    roles = {
        "F.Cu": "top copper", "B.Cu": "bottom copper",
        "In1.Cu": "inner layer 1 — MAGND/MDGND plane",
        "In2.Cu": "inner layer 2 — MAGND/MDGND plane",
        "F.Mask": "top solder mask", "B.Mask": "bottom solder mask",
        "F.Paste": "top stencil", "B.Paste": "bottom stencil",
        "F.SilkS": "top legend", "B.SilkS": "bottom legend",
        "Edge.Cuts": "board outline — **the only outline in the package**",
    }
    listed = []
    for layer in layers:
        path = _plotted_file(directory, layer)
        if path is not None:
            listed.append((path, roles.get(layer, layer)))
    for name, what in ((f"{PROJECT}.drl", "drill, plated and unplated combined"),
                       (f"{PROJECT}-job.gbrjob", "job file — KiCad's own "
                                                 "summary of the set"),
                       ("ORDER.md", "this document")):
        path = directory / name
        if path.exists():
            listed.append((path, what))
    return listed


def _extent(board=BOARD):
    """The board's size, from the same function placement.py and gen_pcb.py use.

    Not measured off the gerber: placement.outline() is where this number is
    decided, and a second reading of it would be a second opinion.
    """
    import placement
    left, top, right, bottom = placement.outline()
    return f"{right - left:.1f} × {bottom - top:.1f} mm"


def check_package(board=BOARD, fab=FAB):
    """Is the tracked package a package of the tracked board?

    The same argument as gen_plots.check_plots(), one artefact along, and the
    same shape: export into a temporary directory, normalise, compare bytes.
    It is a mode rather than a stage for the same reason -- run straight after
    gen_fab.py it compares files just written against themselves.

    What it adds over that one is check_holes(), which is not a comparison
    against a copy of the same export. A package can be a faithful export of
    the tracked board and still be the wrong export.
    """
    problems = []
    if not fab.exists():
        return [f"{fab.name}/ does not exist at all -- run gen_fab.py"]
    with tempfile.TemporaryDirectory() as scratch:
        scratch = pathlib.Path(scratch)
        layers, _ = export(scratch, board)
        fresh = {path.name: path.read_bytes() for path in scratch.iterdir()}
        tracked = {path.name: path.read_bytes() for path in fab.iterdir()
                   if path.suffix.lower() != ".zip"}
        for name in sorted(set(fresh) | set(tracked)):
            if name not in tracked:
                problems.append(f"{name} is missing from {fab.name}/")
            elif name not in fresh:
                problems.append(
                    f"{name} is in {fab.name}/ and this board does not "
                    f"produce it -- a layer that left the package")
            elif fresh[name] != tracked[name]:
                problems.append(
                    f"{name} is {len(tracked[name])} bytes and re-exporting "
                    f"{board.name} gives {len(fresh[name])} -- the tracked "
                    f"package is not a package of the tracked board")
        problems += check_holes(board, scratch / f"{PROJECT}.drl")
    return problems


def refusals(board=BOARD):
    """Everything that must be true before a package is written at all.

    gen_plots.orderable() is the design's half and is imported rather than
    restated. The other half is the board, and it is asked here rather than
    taken from whatever verify.py last wrote: a fabrication package must not be
    written on the strength of a report somebody ran at some other time, over
    some other board. That is the sibling's rule too -- its build.sh deletes
    the zip when DRC is not clean rather than leaving the last good one lying
    beside a broken board.
    """
    reasons = list(gen_plots.orderable())
    with tempfile.TemporaryDirectory() as scratch:
        report = verify.read_drc(board, pathlib.Path(scratch) / "drc.json")
    problems = verify.check_board(report)
    if problems:
        reasons.append(f"the board does not pass DRC: {problems[0]}"
                       + (f" (and {len(problems) - 1} more)"
                          if len(problems) > 1 else ""))
    # **And the board has to be the design's board**, which DRC cannot say:
    # it reports against the board's own embedded netlist, so a board three
    # netlist revisions old agrees with itself perfectly. check_board_is_the_design()
    # compares refs and land patterns against design.py, and its own docstring
    # names this exact moment -- "the only things standing between a stale
    # board and a fabrication package". A package is the one artefact here
    # that leaves the repository, so it is the one place that sentence has to
    # be executable rather than true.
    stale = verify.check_board_is_the_design(board)
    if stale:
        reasons.append(f"the board is not the design's board: {stale[0]}")
    return reasons


def main():
    if not BOARD.exists():
        raise SystemExit(f"{BOARD} does not exist -- run gen_pcb.py")

    reasons = refusals()
    if reasons:
        # **The whole package goes, not just the archive.** The sibling deletes
        # its zip for this reason -- "no fabrication package is written while a
        # board has known errors" -- and here the loose files are the package
        # and the archive is a wrapper, so deleting only the wrapper would
        # leave the thing somebody actually uploads sitting on disk, correct in
        # every respect except which board it is of. A tracked artefact
        # disappearing is a loud signal; a stale one is a silent hazard.
        removed = 0
        if FAB.exists():
            for path in sorted(FAB.iterdir()):
                if path.is_file():
                    path.unlink()
                    removed += 1
        if removed:
            print(f"removed {removed} files from fab/ -- a package that is not "
                  f"this board's must not be sitting where somebody uploads it")
        print("no fabrication package written, and each of these is a gate:")
        for reason in reasons:
            print(f"    {reason}")
        raise SystemExit(1)

    if FAB.exists():
        # Rebuilt rather than written over, so a layer that stops being
        # generated leaves the package. That is the failure the sibling records
        # against `zip` updating an archive in place, one directory earlier.
        for path in sorted(FAB.iterdir()):
            if path.is_file():
                path.unlink()

    layers, dropped = export(FAB)
    summary = drill_summary(FAB / f"{PROJECT}.drl")
    write_zip(FAB, ZIP)

    print(f"fab: {len(layers)} layers, "
          f"{sum(tool['hits'] for tool in summary)} drill hits, "
          f"{len(list(FAB.glob('*')))} files")
    print(f"  layers   {','.join(layers)}")
    for layer, why in sorted(dropped.items()):
        print(f"  dropped  {layer} -- {why}")
    for tool in summary:
        print(f"  {tool['tool']}  {tool['diameter']:.3f} mm  "
              f"{'plated  ' if tool['plated'] else 'unplated'}  "
              f"{tool['hits']:4d} hits")
    problems = check_holes(BOARD, FAB / f"{PROJECT}.drl")
    for problem in problems:
        print(f"  ** {problem}")
    if problems:
        raise SystemExit(
            f"{len(problems)} drill problem(s) -- the package drills a "
            f"different board from the one it was made from")
    print(f"  wrote fab/{ZIP.name} "
          f"({ZIP.stat().st_size / 1024:.0f} kB), sha256 "
          f"{hashlib.sha256(ZIP.read_bytes()).hexdigest()[:16]}")
    print(f"  and fab/{NOTES.name}, which lists what is *not* decided -- "
          f"finish, colours, test, panelisation")


if __name__ == "__main__":
    if "--verify" in sys.argv[1:]:
        stale = check_package()
        for problem in stale:
            print(f"stale: {problem}")
        if stale:
            raise SystemExit(
                f"{len(stale)} problem(s) -- the tracked fabrication package "
                f"is not a package of the tracked board. Run python3 gen_fab.py")
        print("the tracked fabrication package is a package of the tracked "
              "board, and it drills its holes")
    else:
        main()
