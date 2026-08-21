# toolchain/PROVENANCE.md

Where these five files came from, and what was changed.

Taken with `git show <pin>:<file>` from `../summing-mixer`, at the commit
`contract/PINNED.md` names — the revision the mixer's boards were fabricated
from — **not** from its working tree, which carries uncommitted changes to
`DESIGN.md`, `design.py` and `fab/`.

```
4bc7ddbae461667370aa7728d3eded31774be4ab
```

| file | lines | upstream sha256 | ours | change |
|---|---|---|---|---|
| `sexp.py` | 103 | `363ebed907ab` | `363ebed907ab` | identical |
| `kisch.py` | 389 | `f6765ae7f516` | `2bf3df310403` | relative imports |
| `symlib.py` | 125 | `f84f91bf6cd5` | `82ec29b29ca8` | relative imports, **and flatten() deep-copies** |
| `kicad.py` | 161 | `2351e8a51f2a` | `2351e8a51f2a` | identical |
| `kisim.py` | 181 | `5c01d9835762` | `5c01d9835762` | identical |

The two changes are the same change. As a package, `kisch` and `symlib` reach
their siblings relatively:

```python
from . import symlib          # was: import symlib
from .sexp import Sym, dumps  # was: from sexp import Sym, dumps
```

Nothing else was touched. The hashes are recorded so that a future divergence can
be seen to be deliberate, and **not so that it can be forbidden** — these files
are this repo's now, and modifying them is expected. There is no check that they
still match upstream, because a check like that would put the dependency back.

## Why these five and not the other two

| vendored here | referenced at the pin, through `contract/socket.py` |
|---|---|
| `sexp.py`, `kisch.py`, `symlib.py`, `kicad.py`, `kisim.py` | `design.py`, `source.py`, `fab/mechanical-*.json` |

The left column carries no hardware content — no value, no net, no dimension,
nothing that has to agree with a board that exists. `kisim.py` states the case
for its own column in its docstring: *"it is copied between repositories
unchanged, like kicad.py, sexp.py and symlib.py."* `cv-module` uses exactly one
function from it, `magnitude()`, which parses `"10k 0.1%"` into a float.

The right column is the interface, and copying it would be the mistake this whole
arrangement exists to avoid. `design.py` holds the constants and the models that
this module has to mate with. `source.py` models the capsule and the Nexus-GK
that feed the mixer — `delta.py`'s entire value is expressing this module's
effect as a delta against *the mixer's own* model, and a fork of that model would
turn the deltas into a comparison against a copy of themselves, silently.

That is the line: **the toolchain is infrastructure and gets copied; the
interface is hardware and gets referenced.**

## The one change that is ours rather than cosmetic

**`symlib.flatten()` takes a deep copy, and upstream's does not.** Its
docstring in both repositories promises *"a self-contained copy of a symbol"*
and the code builds shallow lists: the outer list is new and every unit body --
which is where the pins live -- is the one inside `_library_cache`. So a caller
that renumbers a pin on a flattened symbol renumbers it in the cache, and the
next flatten of that source returns the mutated symbol.

Nothing showed while each borrowed symbol had exactly one borrower, which was
true upstream and true here for four passes. It surfaced the day `Device:D` was
borrowed twice -- as itself, and as `cv:BAT54` with its pins renumbered onto the
SOT-23 package -- and six envelope diodes drawn with the generic symbol failed
on a missing pin 2. **That is the loud version of this bug.** The quiet version
is `_repin()` or `_set_property()`, which mutate the cache just as thoroughly
and change a symbol somebody else is still using.

Worth carrying upstream if the mixer ever borrows one symbol twice. It has no
symptom there today.

## Bringing an upstream fix over

Deliberately, with the arithmetic. The one to expect is the KiCad file-format
version in `kisch.SCH_VERSION` and `symlib`, which moves with KiCad releases —
and CLAUDE.md's note about the deprecated `pcbnew` bindings applies to both repos
at once and should be solved in both at once.

```bash
git -C ../summing-mixer show <commit>:kisch.py | diff - toolchain/kisch.py
```

Re-apply the relative imports afterwards and update the table above.
