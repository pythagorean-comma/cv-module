"""Minimal s-expression reader/writer for KiCad files.

KiCad's native formats are all s-expressions. We only need enough to pull
symbol geometry out of the stock libraries and to emit a schematic, so this
stays deliberately small: a tokeniser, a recursive parser, and a pretty
printer that matches KiCad's own tab-indented style closely enough that the
files diff cleanly after KiCad rewrites them.
"""


class Sym(str):
    """A bare token, as distinct from a quoted string.

    Parsing has to remember which atoms were quoted, because re-emitting
    `version` as `"version"` produces a file KiCad will not load.
    """


def parse(text):
    """Parse one s-expression into nested lists of Sym/str/int/float."""
    pos = 0

    def skip_ws():
        nonlocal pos
        while pos < len(text) and text[pos] in " \t\r\n":
            pos += 1

    def read():
        nonlocal pos
        skip_ws()
        if text[pos] == "(":
            pos += 1
            items = []
            while True:
                skip_ws()
                if text[pos] == ")":
                    pos += 1
                    return items
                items.append(read())
        if text[pos] == '"':
            pos += 1
            out = []
            while text[pos] != '"':
                if text[pos] == "\\":
                    pos += 1
                out.append(text[pos])
                pos += 1
            pos += 1
            return "".join(out)
        start = pos
        while pos < len(text) and text[pos] not in " \t\r\n()":
            pos += 1
        return Sym(text[start:pos])

    return read()


def _atom(value):
    if isinstance(value, Sym):
        return str(value)
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        # KiCad writes trailing zeros off; keep it tidy and deterministic.
        return f"{value:.6f}".rstrip("0").rstrip(".") or "0"
    if isinstance(value, int):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def dumps(node, indent=0):
    """Render a nested list back to KiCad's tab-indented s-expression text."""
    if not isinstance(node, list):
        return _atom(node)

    pad = "\t" * indent
    # Short all-atom forms stay on one line, the way KiCad writes (at 1 2 0).
    if all(not isinstance(item, list) for item in node):
        return pad + "(" + " ".join(_atom(item) for item in node) + ")"

    parts = [pad + "(" + _atom(node[0])]
    rest = node[1:]
    # Leading atoms sit on the opening line: (symbol "R" (pin ...) ...)
    lead = 0
    while lead < len(rest) and not isinstance(rest[lead], list):
        parts[0] += " " + _atom(rest[lead])
        lead += 1
    for item in rest[lead:]:
        parts.append(dumps(item, indent + 1))
    parts.append(pad + ")")
    return "\n".join(parts)


def find_all(node, tag):
    """Direct children of `node` whose head token is `tag`."""
    return [x for x in node if isinstance(x, list) and x and str(x[0]) == tag]


def find(node, tag):
    """First direct child with head token `tag`, or None."""
    hits = find_all(node, tag)
    return hits[0] if hits else None
