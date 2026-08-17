"""Find the KiCad installation.

Everything else in here needs three things from KiCad: the `kicad-cli`
binary, the stock symbol and footprint libraries, and (for gen_pcb.py) the
bundled Python that carries `pcbnew`. None of it is pip installable, so the
location has to be discovered rather than declared in requirements.txt.

Stdlib only, deliberately: this is imported both by the project venv and by
KiCad's own interpreter.
"""

import os
import pathlib
import shutil
import subprocess

# The formats written by kisch.py and gen_pcb.py are version specific -- a
# schematic is stamped 20250610, which KiCad 9 will not open.
REQUIRED_MAJOR = 10

_CANDIDATES = (
    pathlib.Path("/Applications/KiCad/KiCad.app"),
    pathlib.Path.home() / "Applications/KiCad/KiCad.app",
)


class NotFound(Exception):
    """Raised with instructions rather than a bare path error."""


def _from_bundle(app):
    """Paths inside a macOS KiCad.app, or None if it is not one."""
    cli = app / "Contents/MacOS/kicad-cli"
    share = app / "Contents/SharedSupport"
    if cli.exists() and share.is_dir():
        interpreter = app / ("Contents/Frameworks/Python.framework/Versions/"
                             "3.9/bin/python3")
        return {
            "cli": cli,
            "symbols": share / "symbols",
            "footprints": share / "footprints",
            "python": interpreter if interpreter.exists() else None,
        }
    return None


def _from_path():
    """kicad-cli on PATH -- covers Linux packages and Homebrew."""
    found = shutil.which("kicad-cli")
    if not found:
        return None
    cli = pathlib.Path(found).resolve()
    # …/bin/kicad-cli next to …/share/kicad/{symbols,footprints}
    for share in (cli.parent.parent / "share/kicad",
                  pathlib.Path("/usr/share/kicad")):
        if (share / "symbols").is_dir():
            return {"cli": cli, "symbols": share / "symbols",
                    "footprints": share / "footprints", "python": None}
    return None


def _locate():
    searched = []

    # An explicit override is authoritative: falling through to a default
    # would quietly build against a different KiCad than the one asked for,
    # and hide a typo in the variable.
    override = os.environ.get("KICAD_APP")
    if override:
        found = _from_bundle(pathlib.Path(override))
        if found:
            return found
        raise NotFound(
            f"$KICAD_APP is set to {override}, which does not look like a "
            "KiCad installation.\nExpected to find "
            "Contents/MacOS/kicad-cli and Contents/SharedSupport beneath it.\n"
            "Unset KICAD_APP to search the usual locations instead.")

    for app in _CANDIDATES:
        found = _from_bundle(app)
        if found:
            return found
        searched.append(str(app))

    found = _from_path()
    if found:
        return found
    searched.append("kicad-cli on PATH")

    raise NotFound(
        f"KiCad {REQUIRED_MAJOR}.x is required and was not found.\n"
        "Looked in:\n  " + "\n  ".join(searched) + "\n\n"
        "Install it from https://www.kicad.org/download/ (macOS: "
        "`brew install --cask kicad`), or if it lives somewhere unusual set\n"
        "  export KICAD_APP=/path/to/KiCad.app\n"
        "KiCad is not a pip package, so requirements.txt cannot supply it.")


_cache = {}

_ATTRIBUTES = {
    "KICAD_CLI": "cli",
    "SYMBOL_DIR": "symbols",
    "FOOTPRINT_DIR": "footprints",
    "BUNDLED_PYTHON": "python",      # None outside a macOS .app bundle
}


def _info():
    if not _cache:
        _cache.update(_locate())
    return _cache


def __getattr__(name):
    """Locate KiCad on first use rather than at import.

    Importing this module must not explode: that way a missing install is
    reported by whoever asks for a path, and the command-line entry point
    below can turn it into a plain message instead of a traceback.
    """
    if name in _ATTRIBUTES:
        return _info()[_ATTRIBUTES[name]]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def version():
    """The installed version string, e.g. "10.0.5"."""
    result = subprocess.run([str(_info()["cli"]), "version"],
                            capture_output=True, text=True)
    return result.stdout.strip()


def check_version():
    """Warn if the major version is not the one these generators target."""
    installed = version()
    major = installed.split(".", 1)[0]
    if major != str(REQUIRED_MAJOR):
        return (f"warning: KiCad {installed} found, but these generators "
                f"target {REQUIRED_MAJOR}.x. The file formats they write may "
                f"not open.")
    return None


if __name__ == "__main__":
    import sys

    try:
        found = _info()
        if len(sys.argv) > 1:
            print(found[sys.argv[1]] or "")
        else:
            print(f"KiCad {version()}")
            for label in ("cli", "symbols", "footprints", "python"):
                print(f"  {label:11s}{found[label] or '(not a macOS bundle)'}")
            warning = check_version()
            if warning:
                print(warning)
    except NotFound as problem:
        # A missing prerequisite deserves an explanation, not a stack trace.
        sys.exit(str(problem))
