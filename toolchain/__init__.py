"""KiCad plumbing, vendored from ../summing-mixer. Ours now, not borrowed.

Five files that write and read KiCad's file formats and find KiCad itself. They
carry no hardware content: no value, no net, no dimension, nothing that has to
agree with a fabricated board. That is the whole reason they are copies and
`contract/socket.py` is not.

**The rule this package exists to enforce.** Nothing in `cv-module` imports a
module from the mixer's working tree. The mixer repo is a fabricated hardware
interface that this module references, and referencing an interface does not mean
importing a project's Python. Everything upstream that *is* hardware -- the
constants, the models, `source.py`, the mechanical envelope -- still comes from
`contract/socket.py` at the pinned commit, and comes through `git show`, so it
cannot be a copy that drifted.

See PROVENANCE.md for where each file came from and what was changed. What was
changed is two lines: `kisch` and `symlib` import their siblings relatively, as
a package must.

**What this replaced, and why the old arrangement looked fine.** CLAUDE.md used
to say to import the mixer's `sexp.py` read-only at the pinned commit rather than
writing another one, and that instruction was followed literally and did not
work: `contract/socket.py` appended the mixer's root to `sys.path` and the
imports resolved off *disk*, at whatever the working tree happened to say. The
pin covered `design.py`, which is read with `git show`, and nothing else.
`socket.check_pin()` asserted that two of the tree-read files were clean and
identical to the pin; the other four -- `sexp`, `kisch`, `symlib`, `kicad` --
were asserted nothing about at all, and the set of files grew every time a
generator was added. A schematic written by a modified `kisch` would still have
been compared to `design.py` by a comparison running through the same modified
code.

Copies remove the class of problem rather than widening the guard. The cost is
that upstream fixes have to be brought over deliberately, and that is a cost
worth paying in a repo whose siblings are on a different release cadence.
"""
