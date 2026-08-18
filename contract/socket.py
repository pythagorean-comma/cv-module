"""The only place the summing mixer's contract is adapted.

The mixer repo is the single source of truth for this interface and it is
read-only: its boards are fabricated. Everything this module knows about them
comes through here, from one named commit, so there is one copy, one place and
one reason.

    ../summing-mixer @ contract/PINNED.md
        design.py  ------> constants, models, the RV{n}01 netlist
        fab/mechanical-summing-mixer.json ------> outline, mounting, envelope

Three rules, and the second is the one that makes this file worth having.

**Read the commit, not the disk.** The mixer's working tree is dirty (see
PINNED.md), so `import design` would read a file no board was made from. Every
byte here comes through `git show <pin>:<path>`.

That sentence was true of `design.py` and false of everything else for most of
this file's life: it put the mixer's root on `sys.path` so the pinned design.py's
own `import source` and `import kisim` would resolve, and four more modules came
along with it -- `sexp`, `kisch`, `symlib`, `kicad` -- read off disk by the
generators here with nothing asserted about them. Those five are copies in
`toolchain/` now and the path entry is gone; `source` and `kisim` are executed
from the commit under their own names, which is what removed the need for it.
`check_pin()` refuses the path entry and `check_no_mixer_imports()` refuses any
module loaded from a file under the mixer, so the sentence is now checkable and
checked. See `toolchain/PROVENANCE.md` for where the line falls and why.

**Derive, do not transcribe.** Where the upstream fact lives in a symbol it is
imported. Where it lives in a *check* -- the RV{n}01 pin order is a literal
dict inside `check_attenuators()` and cannot be imported -- it is recovered
from the pinned netlist instead, so an upstream change moves it here too. The
only things retyped are the four in ADAPTED below, each carrying the upstream
text it came from.

**Never write.** Nothing in this file opens the mixer repo for anything but
reading, and `git show` cannot mutate a tree.
"""

import json
import os
import pathlib
import re
import subprocess
import sys
import types

from toolchain import kisim

HERE = pathlib.Path(__file__).resolve().parent
PINNED_MD = HERE / "PINNED.md"


# ---------------------------------------------------------------------------
# Finding the mixer
# ---------------------------------------------------------------------------

# CLAUDE.md says "../summing-mixer (or wherever it is mounted)", so this
# searches rather than assumes -- the same shape as the mixer's own kicad.py,
# which checks $KICAD_APP, then two well-known directories, then PATH.
#
# Siblings, never nested. CLAUDE.md forbids running git from a directory
# containing both repos, and a nested checkout would make every invocation
# below do exactly that.
SEARCH = ("$SUMMING_MIXER", "../summing-mixer", "~/code/summing-mixer")


def find_mixer():
    """The mixer repo's root, or a SystemExit saying where it was looked for."""
    if os.environ.get("SUMMING_MIXER"):
        candidates = [pathlib.Path(os.environ["SUMMING_MIXER"])]
    else:
        candidates = [HERE.parent.parent / "summing-mixer",
                      pathlib.Path("~/code/summing-mixer").expanduser()]
    for path in candidates:
        if (path / "design.py").is_file() and (path / ".git").exists():
            resolved = path.resolve()
            if resolved == HERE.parent or resolved in HERE.parents:
                raise SystemExit(
                    f"{resolved} contains this repo -- keep the two as "
                    f"siblings, never nested. See CLAUDE.md.")
            return resolved
    raise SystemExit(
        "cannot find the summing-mixer repo. Looked in "
        + ", ".join(SEARCH) + ". Set $SUMMING_MIXER to its root.")


MIXER = find_mixer()


def pinned_commit():
    """The fabricated revision, parsed out of PINNED.md.

    The hash lives in the document rather than in this file so there is exactly
    one copy of it. That makes PINNED.md load-bearing: it is checked, not read.
    """
    match = re.search(r"^```\n([0-9a-f]{40})\n```$",
                      PINNED_MD.read_text(), re.MULTILINE)
    if not match:
        raise SystemExit(
            f"{PINNED_MD} has no 40-character commit hash in a fenced block")
    return match.group(1)


PIN = pinned_commit()


def _git(*args):
    result = subprocess.run(["git", "-C", str(MIXER), *args],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} in {MIXER} failed:\n"
                         f"{result.stderr.strip()}")
    return result.stdout


def show(path):
    """One file's contents at the pinned commit."""
    return _git("show", f"{PIN}:{path}")


# The mixer files that are read at all, and every one of them through `show()`.
#
# `design.py` is the interface. `source.py` is the model of what feeds it -- the
# capsule and the Nexus-GK -- and the pinned design.py imports it inside
# system_budget(); `kisim.py` likewise, inside check_dielectrics().
# `fab/mechanical-*.json` is read separately by mechanical(). Nothing else.
#
# **`kisim` is served here even though toolchain/kisim.py is a copy of it, and
# that is deliberate rather than an oversight.** The pinned design.py must run
# against the code it shipped with: `toolchain/kisim.py` is this repo's now and
# modifying it is sanctioned, so letting it answer an `import kisim` inside the
# mixer's own module would mean an edit here changed what the fabricated design
# computes about itself. Two independent module objects, no shared state, and the
# separation is what "read-only" means at the level of behaviour rather than of
# file permissions.
#
# **This list used to be longer and the extra entries were the problem.** The
# mixer's `kisim`, `sexp`, `kisch`, `symlib` and `kicad` were ordinary imports
# resolved off `sys.path`, which meant off *disk*, at whatever the mixer's
# working tree happened to say -- while `design.py` came from the commit. The
# guard was to assert those files were clean and equal to the pin, and the guard
# had to grow every time a generator here imported one more of them. They are
# copies in `toolchain/` now, and the guard is gone because the exposure is.
#
# What is left is a stronger claim than the guard ever made: **every byte this
# repo reads from the mixer comes out of one commit**, through the one function
# below. The mixer's working tree can be as dirty as it likes -- DESIGN.md,
# design.py and fab/ all are -- and it cannot reach this module.
PINNED_MODULES = ("design.py", "source.py", "kisim.py")


def check_pin():
    """The pinned commit exists, and nothing upstream is read off disk.

    Raises rather than warns. A module built against a mixer that has moved is
    a module that mates with hardware nobody has.

    The second half is the one that replaced a clean-tree assertion. Rather than
    police which working-tree files are allowed to answer for the pin, this
    refuses the mechanism: the mixer's root must not be on `sys.path` at all, so
    an `import sexp` added here in future cannot silently resolve upstream. It
    fails loudly instead, which is the correct outcome -- `toolchain/` is where
    that import goes.
    """
    if _git("cat-file", "-t", PIN).strip() != "commit":
        raise SystemExit(f"{PIN} is not a commit in {MIXER}")

    on_path = [entry for entry in sys.path
               if entry and pathlib.Path(entry).resolve() == MIXER]
    if on_path:
        raise SystemExit(
            f"{MIXER} is on sys.path -- nothing here may import the mixer's "
            f"modules from disk. The KiCad plumbing lives in toolchain/; the "
            f"interface comes through this file at {PIN[:7]}. See "
            f"toolchain/PROVENANCE.md.")


def _pinned_module(name, path):
    """One mixer module, executed from the pinned commit under a private name.

    Executed rather than imported, so `import design` elsewhere cannot return
    the mixer's copy by accident -- the mixer's root is not on `sys.path` and
    check_pin() refuses to let it be.

    `source` and `kisim` are registered under their own names, because the pinned
    `design.py` says `import source` and `import kisim` and those have to resolve
    to *these* objects rather than to files. Registering them first is what lets
    the mixer's root stay off `sys.path` entirely; before this,
    `sys.path.append(MIXER)` was there for exactly those two imports, and it
    brought four more modules with it that nothing had asked for.

    `__pinned__` marks the module as having come from a commit rather than from
    the tree, which is what check_no_mixer_imports() tests against.
    """
    module = types.ModuleType(name)
    module.__file__ = str(MIXER / path)
    module.__pinned__ = PIN
    sys.modules[name] = module
    exec(compile(show(path), module.__file__, "exec"), module.__dict__)
    return module


def load_design():
    """design.py and its own imports, all as of the pinned commit."""
    check_pin()
    # These two first: the pinned design.py imports them by name, and if they are
    # not in sys.modules already Python goes looking on the path for them.
    source_module = _pinned_module("source", "source.py")
    _pinned_module("kisim", "kisim.py")
    design_module = _pinned_module("mixer_design", "design.py")
    return design_module, source_module


MIXER_DESIGN, source = load_design()


def check_no_mixer_imports():
    """No module in this process was loaded from a file in the mixer repo.

    **This replaced a narrower check and the widening is the point.** What was
    here before named three modules -- design, verify, gen_netlist -- and
    asserted each resolved to a file in *this* repo, because the mixer's root was
    on `sys.path` and both repos have a design.py and a verify.py. It was a
    correct check of a list, and the list was the problem: it could only ever
    name the collisions somebody had already thought of, and `sexp`, `kisch`,
    `symlib`, `kicad` and `kisim` were never on it while being imported from
    upstream on every run.

    So this asks the question from the other end. Walk everything actually
    loaded, and fail on anything whose file is under the mixer path. No list to
    keep current, and a module nobody anticipated is caught by the same sentence
    as one that was.

    The pinned modules are exempt *by a marker they carry*, not by name: `design`
    and `source` are executed out of `git show` and their `__file__` points at the
    mixer for the sake of readable tracebacks, so `__pinned__` is what
    distinguishes "came from the commit" from "came from the tree". Exempting
    them by name would have re-created the list this check exists to replace.
    """
    wrong = []
    for name, module in sorted(sys.modules.items()):
        if module is None or getattr(module, "__pinned__", None):
            continue
        origin = getattr(module, "__file__", None)
        if not origin:
            continue
        try:
            resolved = pathlib.Path(origin).resolve()
        except OSError:
            continue
        if resolved == MIXER or MIXER in resolved.parents:
            wrong.append(f"{name} was loaded from {origin}")
    if wrong:
        raise SystemExit(
            "; ".join(wrong) + f" -- nothing in this repo may import a module "
            f"from {MIXER}. The KiCad plumbing is copied into toolchain/; the "
            f"hardware interface comes through this file at {PIN[:7]}. See "
            f"toolchain/PROVENANCE.md.")


# ---------------------------------------------------------------------------
# Imported: values
# ---------------------------------------------------------------------------
# Named here so this module reads as a list of what the contract contains, and
# so a symbol that disappears upstream fails at import rather than at use.

CHANNELS = MIXER_DESIGN.CHANNELS                       # design.CHANNELS

RIN = MIXER_DESIGN.RIN                                 # design.RIN
RIN_OHMS = MIXER_DESIGN.RIN_OHMS                       # design.RIN_OHMS

# The summer's feedback, so this module can compute what its own residual DC
# does at SUM_OUT rather than assuming the mixer is unity per channel. It is
# unity today -- RF == RIN -- and RF_TABLE exists precisely because
# MEASURED["channel_peak"] can move it, so reading it is not pedantry.
RF = MIXER_DESIGN.RF                                   # design.RF
RF_OHMS = MIXER_DESIGN.RF_OHMS                         # design.RF_OHMS
RF_TABLE = MIXER_DESIGN.RF_TABLE                       # design.RF_TABLE
recommended_rf = MIXER_DESIGN.recommended_rf

# The output DC reference, which is what turns residual DC at SUM_OUT into a
# current through the master pot's wiper rather than a voltage across it.
#
# design.R_OUT_BLEED is the value *string* "1M", because upstream it is a BOM
# line and nothing there needs it as a number. Parsed with kisim.magnitude() --
# the same parser design.check_dielectrics() uses -- rather than retyped, so the
# *value* stays a reading and not a copy.
#
# The parser itself is now toolchain/kisim.py, a copy. That is the right way
# round: what must not be retyped is the string "1M", which is a fact about a
# fabricated board. How a suffix becomes a float is arithmetic, and arithmetic
# does not have to be borrowed to be correct.
R_OUT_BLEED = MIXER_DESIGN.R_OUT_BLEED                 # design.R_OUT_BLEED
OUT_BLEED_OHMS = kisim.magnitude(R_OUT_BLEED)

DC_BLOCK_VALUE = MIXER_DESIGN.DC_BLOCK_VALUE           # design.DC_BLOCK_VALUE
DC_BLOCK_FARADS = MIXER_DESIGN.DC_BLOCK_FARADS         # design.DC_BLOCK_FARADS

NEGATIVE_RAIL_DROP = MIXER_DESIGN.NEGATIVE_RAIL_DROP   # design.NEGATIVE_RAIL_DROP
SUPPLY_RAIL = MIXER_DESIGN.SUPPLY_RAIL                 # design.SUPPLY_RAIL
VREG_VOLTS = MIXER_DESIGN.VREG_VOLTS                   # design.VREG_VOLTS
PUMP_FREQUENCY = MIXER_DESIGN.PUMP_FREQUENCY           # design.PUMP_FREQUENCY

# The shared DC inlet, and it is an interface rather than a rail. The module's
# converter hangs off the *same barrel jack* as the mixer's own J8, so what the
# brick is asked for is a system-level fact that both boards depend on and only
# one of them records. Both strings, because SUPPLY_RANGE carries a current
# figure -- "25mA" -- which design.inlet_budget() is about to make wrong for
# the box as a whole, and SUPPLY_INTENT carries the polarity, which the mixer's
# own J8 comment records as having been written backwards for the whole life of
# that design.
SUPPLY_RANGE = MIXER_DESIGN.SUPPLY_RANGE               # design.SUPPLY_RANGE
SUPPLY_INTENT = MIXER_DESIGN.SUPPLY_INTENT             # design.SUPPLY_INTENT

CHANNEL_POT = MIXER_DESIGN.CHANNEL_POT                 # design.CHANNEL_POT
CHANNEL_POT_OHMS = MIXER_DESIGN.CHANNEL_POT_OHMS       # design.CHANNEL_POT_OHMS
CHANNEL_POT_FP = MIXER_DESIGN.CHANNEL_POT_FP           # design.CHANNEL_POT_FP
CONN_FP = MIXER_DESIGN.CONN_FP                         # design.CONN_FP
CONN_MPN = MIXER_DESIGN.CONN_MPN                       # design.CONN_MPN

MEASURED = MIXER_DESIGN.MEASURED                       # design.MEASURED
NOISE_FLOOR = MEASURED["noise_floor"]                  # design.MEASURED[...]

BANDWIDTH = MIXER_DESIGN.BANDWIDTH                     # design.BANDWIDTH
BOLTZMANN = MIXER_DESIGN.BOLTZMANN                     # design.BOLTZMANN
TEMPERATURE = MIXER_DESIGN.TEMPERATURE                 # design.TEMPERATURE

NETS = MIXER_DESIGN.NETS                               # design.NETS
PARTS = MIXER_DESIGN.PARTS                             # design.PARTS


# ---------------------------------------------------------------------------
# Imported: models
# ---------------------------------------------------------------------------
# Called rather than reimplemented, so this module's effect on the mixer can be
# shown as a delta against the mixer's own numbers instead of a fresh set that
# happens to disagree.

thermal = MIXER_DESIGN.thermal
summing_stage_noise = MIXER_DESIGN.summing_stage_noise
attenuator = MIXER_DESIGN.attenuator
attenuator_input_impedance = MIXER_DESIGN.attenuator_input_impedance
coupling_burden = MIXER_DESIGN.coupling_burden
noise_budget = MIXER_DESIGN.noise_budget
system_budget = MIXER_DESIGN.system_budget
output_swing = MIXER_DESIGN.output_swing
clipping_peak = MIXER_DESIGN.clipping_peak


# ---------------------------------------------------------------------------
# Derived: the socket
# ---------------------------------------------------------------------------

# The nets this module must not draw a single microamp from. Constraint 1.
#
# Named rather than derived because "which rails are forbidden" is a decision
# in the parent document, not a fact in the netlist -- design.py has no notion
# of a rail being off limits to somebody else. The names are checked against
# NET_DC at import below, so a rename upstream fails here.
FORBIDDEN_RAILS = ("VREG", "V+", "V-")
AGND = "AGND"

assert set(FORBIDDEN_RAILS) | {AGND} <= set(MIXER_DESIGN.NET_DC), (
    "a forbidden rail or AGND has been renamed upstream -- see design.NET_DC")


def channel_socket(n):
    """What RV{n}01's three pins are wired to, read off the pinned netlist.

    The upstream fact lives in design.check_attenuators(), as a literal dict
    inside a method:

        expected = {"1": f"PIN{n}", "2": f"SIN{n}", "3": "AGND"}

    which cannot be imported. Transcribing it would put a second copy of the
    pinout in a repo whose whole discipline is that there is one -- and it is
    exactly the copy that would go stale silently, because nothing downstream
    of a wrong pin number looks wrong.

    So it is recovered instead, from design.NETS, which is what
    check_attenuators() is asserting *about*. If the mixer ever moves the wiper
    to pin 1, this follows without an edit and verify.py here fails on the
    consequences rather than on the transcription.

    Returns {"1": "PIN1", "2": "SIN1", "3": "AGND"} for n = 1.
    """
    ref = f"RV{n}01"
    if ref not in PARTS:
        raise KeyError(f"{ref} is not in the mixer at {PIN[:7]} -- the level "
                       f"control this module hangs off has moved or gone")
    wiring = {pin: net for net, entries in NETS.items()
              for part, pin in entries if part == ref}
    if len(wiring) != 3:
        raise AssertionError(f"{ref} has {len(wiring)} pins on nets, expected 3")
    return wiring


def socket_pin(n, net_prefix):
    """Which pin of RV{n}01 carries PIN{n}, SIN{n} or AGND."""
    wanted = AGND if net_prefix == AGND else f"{net_prefix}{n}"
    for pin, net in channel_socket(n).items():
        if net == wanted:
            return pin
    raise KeyError(f"no pin of RV{n}01 carries {wanted}")


# The three roles, derived once at import so a rename or a re-pin is loud.
#
# PIN{n} is the top of the track: post-DC-block, pre-Rin, and what this module
# takes as its input. SIN{n} is the wiper: it feeds R{n}01 into the summing
# node, and is what this module drives. Pin 3 is the grounded end of the track
# and is this channel's return.
PIN_TOP = socket_pin(1, "PIN")
PIN_WIPER = socket_pin(1, "SIN")
PIN_RETURN = socket_pin(1, AGND)

assert all(socket_pin(n, "PIN") == PIN_TOP
           and socket_pin(n, "SIN") == PIN_WIPER
           and socket_pin(n, AGND) == PIN_RETURN
           for n in range(1, CHANNELS + 1)), (
    "the six level controls are not wired alike upstream")


def socket_nets(n):
    """(input, output, return) net names at channel n's socket."""
    return f"PIN{n}", f"SIN{n}", AGND


# ---------------------------------------------------------------------------
# Imported: mechanical
# ---------------------------------------------------------------------------

def mechanical(board="summing-mixer"):
    """One board's mechanical contract, at the pinned commit.

    The same JSON the comma-enclosure repo consumes. This module is the third
    consumer and reads it the same way rather than measuring a PCB file --
    README.md is explicit that the contract exists so a consumer needs no
    knowledge of KiCad internals it would silently outgrow.
    """
    return json.loads(show(f"fab/mechanical-{board}.json"))


def socket_positions():
    """Where the six RV{n}01 bodies sit on the main board, mm.

    Read out of the mechanical contract's tall-parts list, which carries them
    because a 3299W stands 11.75 mm. This is the geometry the module's loom has
    to reach: one column, 7.5 mm pitch. See FINDINGS.md on what is fitted there
    now and what has to come off.
    """
    tall = {part["ref"]: part for part in mechanical()["tall_parts"]}
    return [(tall[f"RV{n}01"]["x"], tall[f"RV{n}01"]["y"])
            for n in range(1, CHANNELS + 1)]


# ---------------------------------------------------------------------------
# Adapted: facts that live in upstream prose
# ---------------------------------------------------------------------------
# Four things this module needs that are stated in the mixer's comments rather
# than in its symbols, so they cannot be imported at all. Each carries the
# upstream text verbatim, because an adapted constant whose provenance is a
# paraphrase is a constant nobody can check.

ADAPTED = {}


def _adapt(name, value, upstream, quote):
    ADAPTED[name] = (value, upstream, quote)
    return value


# What temperature range the design is allowed to assume. Needed here because
# the SSI2164's gain constant is proportional to absolute temperature at
# -3300 ppm/degC, and whether that wants compensating is decided by the span.
AMBIENT_C = _adapt(
    "AMBIENT_C", (0.0, 50.0), "design.DIELECTRICS (comment)",
    "X5R and X7R differ only in temperature range and both are class II, so "
    "both are accepted; a pedal never leaves 0-50 C.")

# The one bridge between the two grounds, by reference. Needed because this
# module's own bond is the second half of the same rule and verify.py has to
# name what it is not allowed to duplicate.
GROUND_STAR = _adapt(
    "GROUND_STAR", "R901", "design._GROUND_RULE",
    "AGND and PGND meet at exactly one component, R901, and nowhere else.")

# What the pot's wiper presents to Rin, worst case, and where. Imported as a
# model via attenuator() -- this is the headline figure the docstring states,
# kept because the noise delta in design.py quotes it directly.
WIPER_WORST_OHMS = _adapt(
    "WIPER_WORST_OHMS", CHANNEL_POT_OHMS / 4, "design.summing_stage_noise",
    "It peaks at pot/4 = 2500 ohms at half rotation and is zero at both ends.")

# Why the mounting holes are non-plated, which constrains how this module may
# be mechanically fixed: anything conductive through those holes is another
# AGND/PGND bridge in parallel with R901.
MOUNTING_IS_ISOLATED = _adapt(
    "MOUNTING_IS_ISOLATED", True, "design.mounting",
    "Four plated holes would therefore be four more bridges between AGND and "
    "PGND running in parallel with R901.")


def _report():
    """What the contract actually says. Run this file to see it."""
    print(f"summing-mixer at {PIN[:7]}  ({MIXER})")
    print()
    print("values")
    print(f"  RIN                 {RIN:>24}  ({RIN_OHMS:.0f} ohm)")
    print(f"  DC_BLOCK_VALUE      {DC_BLOCK_VALUE:>24}  "
          f"({DC_BLOCK_FARADS * 1e6:.1f} uF)")
    print(f"  CHANNEL_POT         {CHANNEL_POT:>24}  "
          f"({CHANNEL_POT_OHMS:.0f} ohm)")
    print(f"  CHANNEL_POT_FP      {CHANNEL_POT_FP.split(':')[-1]:>24}")
    print(f"  NEGATIVE_RAIL_DROP  {NEGATIVE_RAIL_DROP:>24.2f}  V")
    print(f"  rails               {VREG_VOLTS:>+18.2f} / {-SUPPLY_RAIL:+.2f}  V")
    print(f"  output_swing()      {output_swing():>24.2f}  V pk")
    print(f"  clipping_peak()     {clipping_peak():>24.2f}  V pk per channel")
    print(f"  noise_floor         {NOISE_FLOOR.value * 1e6:>24.0f}  uV rms "
          f"(assumed, {NOISE_FLOOR.low * 1e6:.0f}-{NOISE_FLOOR.high * 1e6:.0f})")
    print()
    print(f"socket, derived from the pinned netlist")
    print(f"  pin {PIN_TOP} = PIN{{n}}   input to this module")
    print(f"  pin {PIN_WIPER} = SIN{{n}}   output from this module, into "
          f"R{{n}}01 -> SUM")
    print(f"  pin {PIN_RETURN} = AGND     channel return")
    for n in range(1, CHANNELS + 1):
        x, y = socket_positions()[n - 1]
        print(f"  RV{n}01  {channel_socket(n)}  at ({x:.1f}, {y:.1f}) mm")
    print()
    board = mechanical()
    print(f"mechanical  {board['outline']['width']} x "
          f"{board['outline']['height']} x {board['outline']['thickness']} mm, "
          f"{len(board['mounting']['holes'])} x M3 "
          f"{'plated' if board['mounting']['plated'] else 'non-plated'}, "
          f"assembled {board['stack']['total']} mm")
    print()
    print("adapted from upstream prose")
    for name, (value, upstream, quote) in ADAPTED.items():
        print(f"  {name} = {value!r}")
        print(f"    {upstream}: \"{quote}\"")


if __name__ == "__main__":
    _report()
