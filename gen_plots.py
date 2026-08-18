"""The documents a person looks at: the schematic, the layout, and a render.

    python3 gen_plots.py

**Why this did not exist, which is the part worth writing down.** Every output
this repo produced was either a file another tool reads -- `out/` holds the
sheet KiCad opens, the board it opens, the netlist and the BOM an assembly
house parses -- or prose in `docs/`. Nothing produced a *drawing*. So the only
way to look at this schematic has been to install KiCad and open it, and the
only way to look at the board has been the same, which makes every review of
this design a review by whoever has the toolchain installed.

`../summing-mixer/build.sh` has produced all three since it had a board, and
this file is that step, kept as a `gen_*.py` because CLAUDE.md's argument
against a `build.sh` here still holds. The three `kicad-cli` invocations and
their awkward flags are lifted from it, with its reasons carried across rather
than rediscovered -- see plot_layout() in particular, where three settings that
look cosmetic are not.

**They go in `docs/` and not in a `fab/`, and that is derived rather than
copied.** The mixer keeps its equivalents in `fab/` because they travel with
gerbers to a fabricator and an assembler. Nothing here can travel anywhere:
orderable() below lists the reasons, and they are not near-misses -- three of
the board's parts have no footprint because nobody has chosen the part, and
three blocks of the circuit are not drawn. These are documents for reviewing an
unfinished design, and CLAUDE.md's rule is that the split is by audience: `out/`
is what another tool reads next, `docs/` is what a person reads at a screen. A
`fab/` appears when there is something to fabricate, and these move into it
then.

**No gerbers, and that is a gate rather than an omission.** The mixer's
build.sh refuses to write a fabrication package while a board has DRC errors.
The same argument applies harder here and orderable() states it, because a
gerber set of this board would be a complete-looking package for a board that
must not be ordered: it would silently omit three relays that have courtyards
reserved and no copper, and it would be missing the controller, the envelope
ADC and the supply entirely.
"""

import pathlib
import re
import subprocess
import sys

import design
from toolchain import kicad

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"
DOCS = HERE / "docs"
PROJECT = "cv-module"
SHEET = OUT / f"{PROJECT}.kicad_sch"
BOARD = OUT / f"{PROJECT}.kicad_pcb"


def orderable():
    """Why no fabrication package is written. Empty would mean it could be.

    Read off design.py rather than written here, so that choosing the last part
    and drawing the last block is what changes the answer -- not somebody
    remembering to delete a paragraph.
    """
    reasons = []
    # Parts with no footprint, counted off PARTS rather than off UNSPECIFIED.
    # **Not unresolved_pins(), which was tried and returns nothing**: those pins
    # resolve fine, because RELAY_PINS pins the pin map even though the part is
    # not chosen -- which is the whole point of that constant. What stops a
    # gerber being written is not an unresolved pin, it is a footprint that does
    # not exist, so that is what this counts.
    footless = sorted(ref for ref, part in design.PARTS.items()
                      if part.footprint is None)
    if footless:
        reasons.append(
            f"{len(footless)} parts have no footprint because nobody has "
            f"chosen the part ({', '.join(footless)}), so the board reserves a "
            f"courtyard where each goes and lays no copper: see "
            f"design.UNSPECIFIED")
    if design.DEFERRED:
        reasons.append(
            f"{len(design.DEFERRED)} blocks are not drawn at all "
            f"({', '.join(sorted(design.DEFERRED))}): see design.DEFERRED")
    return reasons


# What every PDF's /CreationDate is rewritten to, and why there is a rewrite.
#
# **These files are byte-reproducible apart from a clock reading, and that is
# worth spending six lines on.** Two runs over an unchanged board produce PDFs
# that differ in exactly three bytes -- the minute and second inside
# `/CreationDate (D:YYYY:MM:DD:HH:MM:SS)` -- and nothing else. Left alone, a
# tracked 600 kB binary is rewritten by every build whether or not the design
# moved, so `git log` on it says nothing and the repository grows by a megabyte
# a run. Normalised, the file changes if and only if the board does, which is
# the property that makes a tracked binary worth tracking.
#
# The mixer makes the same argument one step earlier, at `--quality basic`:
# the raytracer samples stochastically, so a higher setting "returns a
# different file byte for byte on every run even from an identical board, and
# this is a tracked binary". The PNG here is already stable for that reason;
# this is the same rule applied to the two PDFs, which KiCad stamps instead.
#
# The epoch, by the reproducible-builds convention, and the same length as what
# it replaces -- a PDF's cross-reference table is byte offsets, so a substitution
# that changed the length would corrupt the file.
PDF_EPOCH = b"D:1970:01:01:00:00:00"


def _normalise_pdf(path):
    """Replace the creation timestamp so the file is a function of the board."""
    data = path.read_bytes()
    stamped = re.search(rb"/CreationDate \((D:[\d:]+)\)", data)
    if stamped is None:
        return 0
    original = stamped.group(1)
    if len(original) != len(PDF_EPOCH):
        raise SystemExit(
            f"{path.name} stamps its creation date as {original!r}, which is "
            f"{len(original)} bytes against PDF_EPOCH's {len(PDF_EPOCH)}. A "
            f"different-length substitution would move every byte after it and "
            f"a PDF's xref table is byte offsets, so this stops rather than "
            f"writing a corrupt file")
    path.write_bytes(data.replace(original, PDF_EPOCH))
    return data.count(original)


def _run(*arguments):
    result = subprocess.run([str(kicad.KICAD_CLI), *arguments],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"kicad-cli {' '.join(arguments[:3])} failed:\n"
                         f"{result.stdout}\n{result.stderr}")


def copper_layers(board=BOARD):
    """Which copper layers this board has, read off it rather than declared.

    The mixer's build.sh does the same and says why: it builds a two-layer
    board as well as a four-layer one, and a plot naming In1/In2 on a two-layer
    board is either an error or, worse, two empty pages a reviewer has to stop
    and make a decision about. This board is four layers today and the question
    is still better asked than assumed.
    """
    text = board.read_text()
    inner = [name for name in ("In1.Cu", "In2.Cu") if f'"{name}"' in text]
    return ",".join(["F.Cu", *inner, "B.Cu"])


def plot_schematic(destination, source=None):
    """The sheet as a PDF. The one document that needs no argument at all."""
    _run("sch", "export", "pdf", "-o", str(destination),
         str(SHEET if source is None else source))


def plot_layout(destination, source=None):
    """One page per copper layer, each readable on its own.

    **Three of these settings look cosmetic and are load-bearing**, and all
    three are the mixer's findings rather than this repo's:

      * without `--bg-color` KiCad paints no page background, so the PDF renders
        on whatever the reader puts behind it -- white in one, black in another,
        which makes the two plane layers invisible in the second;
      * without `--theme` the colours come from whatever the local PCB editor
        happens to be set to, so the same board plots differently on another
        machine. "KiCad Classic" ships with KiCad and plots silk dark enough to
        read on white;
      * and **not** `--black-and-white`, which looks like the safe choice and is
        the worst one: designators become the same ink as the pads under them.

    `--common-layers` puts the outline and the silk on every page, so each page
    is a drawing rather than a layer. User.Drawings joins them here and does not
    in the mixer, for a reason particular to this board: it is where gen_pcb.py
    draws the reserved courtyard of every relay nobody has chosen, and a layout
    plot that omits them shows three empty rectangles of board with no
    indication that anything is meant to be there.
    """
    source = BOARD if source is None else source
    _run("pcb", "export", "pdf", "--mode-multipage",
         "--theme", "KiCad Classic", "--bg-color", "#FFFFFF",
         "--layers", copper_layers(source),
         "--common-layers", "Edge.Cuts,F.SilkS,User.Drawings",
         "--scale", "0", "-o", str(destination), str(source))


def render_top(destination, source=None):
    """The one artefact that reads at a glance to somebody who has not opened a CAD tool.

    Deliberately `--quality basic`: the raytracer samples stochastically, so a
    higher setting returns a different file byte for byte on every run from an
    identical board. That is the mixer's reason and it is a stronger one here,
    because this file is regenerated by every build.
    """
    _run("pcb", "render", "--side", "top", "--quality", "basic",
         "--background", "opaque", "--width", "2400", "--height", "2400",
         "-o", str(destination), str(BOARD if source is None else source))


PLOTS = ((f"{PROJECT}-schematic.pdf", plot_schematic, "sheet"),
         (f"{PROJECT}-layout.pdf", plot_layout, "board"),
         (f"{PROJECT}-top.png", render_top, "board"))


def check_plots(sheet=SHEET, board=BOARD, docs=DOCS):
    """Do the tracked plots correspond to the tracked board? A real check.

    **The hazard is committing part-way through a build, and nothing here could
    see it.** These three files are tracked binaries, and PDF_EPOCH exists so
    that each is a *function of the board* -- which it is: two plots of one board
    are byte-identical, measured. What no instrument covered is the other half of
    that property: whether the plots on disk are a function of **this** board.
    They are not, if a commit is taken after gen_pcb.py has written the board and
    before gen_plots.py has replotted it. Commit 789c4ba is exactly that, by
    534 bytes, and its layout PDF was plotted from the previous board.

    **This check cannot be a step in the build and be worth anything**, which is
    the awkward part and is stated rather than worked around. Run after
    gen_plots.py it compares files that were just written against themselves and
    passes for free -- a check that passes trivially where it runs is this repo's
    own named failure mode. Run *before* it, on a board that has legitimately
    changed, it fails for the expected reason and would be switched off inside a
    week.

    So it is a mode rather than a stage: `python3 gen_plots.py --verify`, whose
    place is a clean checkout, before a commit, or in CI. It plots the tracked
    board into a temporary directory and compares bytes. It was validated the way
    test_verify.py validates its own cases -- by running it against 789c4ba,
    where it fails on cv-module-layout.pdf and passes on the other two.
    """
    import tempfile
    problems = []
    with tempfile.TemporaryDirectory() as scratch:
        scratch = pathlib.Path(scratch)
        for name, plot, wants in PLOTS:
            tracked = docs / name
            if not tracked.exists():
                problems.append(f"{name} is not in {docs.name}/ at all")
                continue
            fresh = scratch / name
            plot(fresh, sheet if wants == "sheet" else board)
            if fresh.suffix == ".pdf":
                _normalise_pdf(fresh)
            if tracked.read_bytes() != fresh.read_bytes():
                problems.append(
                    f"{name} is {tracked.stat().st_size} bytes and replotting "
                    f"{(sheet if wants == 'sheet' else board).name} gives "
                    f"{fresh.stat().st_size} -- the tracked plot is not a plot "
                    f"of the tracked {wants}")
    return problems


def main():
    for path, what in ((SHEET, "gen_sch.py"), (BOARD, "gen_pcb.py")):
        if not path.exists():
            raise SystemExit(f"{path} does not exist -- run {what}")
    DOCS.mkdir(exist_ok=True)

    written = []
    for name, plot, _ in PLOTS:
        destination = DOCS / name
        plot(destination)
        if destination.suffix == ".pdf":
            _normalise_pdf(destination)
        written.append(destination)

    for destination in written:
        print(f"docs/{destination.name}: "
              f"{destination.stat().st_size / 1024:.0f} kB")
    print(f"  layout plotted over {copper_layers()}, "
          f"plus Edge.Cuts, F.SilkS and the reserved courtyards")

    reasons = orderable()
    if reasons:
        print("  no gerbers, and that is a gate rather than an omission:")
        for reason in reasons:
            print(f"      {reason}")
    else:
        print("  nothing left unresolved -- a fab package is writable now, "
              "and gen_plots.py is where it goes")


if __name__ == "__main__":
    if "--verify" in sys.argv[1:]:
        stale = check_plots()
        for problem in stale:
            print(f"stale: {problem}")
        if stale:
            raise SystemExit(
                f"{len(stale)} tracked plot(s) do not correspond to the "
                f"tracked board -- run python3 gen_plots.py")
        print(f"all {len(PLOTS)} tracked plots are plots of the tracked board")
    else:
        main()
