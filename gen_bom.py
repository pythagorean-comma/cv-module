"""The bill of materials, with a source and a price on every line.

Grouped by value and footprint, because parts sharing a value share a part
number -- which is how the mixer's ORDER_CODES table and a BOM line are the
same thing seen from two ends.

**Provenance is a column, and it is the most important one here.** This project's
recurring failure is a source named rather than read, and a price is the easiest
place in a document to write a plausible number nobody checked. So every line
carries a `basis`:

    read       a page was fetched in this session and states this figure
    snippet    a search result quoted a distributor's figure; the page itself
               was not opened
    band       a typical distributor band for that class of part at the stated
               quantity. Not read from anything. An estimate, said so.
    none       the part is not chosen, so it has no price by construction

Totals are therefore given as a range, and the range is honest rather than
decorative: the `band` lines are wide because nobody looked.

The distributor convention is the mixer's, inherited rather than invented. Its
`fab/SHOPPING.md` uses **Mouser UK catalogue searches keyed on the manufacturer's
part number** rather than product-page deep links, and says why: "a search
survives a part being re-listed, which a deep link does not". That warning was
worth having -- a guessed Digi-Key product URL tried during this session
resolved to a HIWIN linear rail.

    python3 gen_bom.py

writes `out/cv-module-bom.csv` and `docs/SHOPPING.md`.
"""

import collections
import csv
import pathlib

import design

HERE = pathlib.Path(__file__).resolve().parent

# Two destinations, and the split is by audience rather than by file type.
# `out/` is what a machine reads next: the CSV goes to a quoting tool or an
# assembly house. `docs/` is what a person reads: SHOPPING.md is a page you work
# from with a browser open. Both are generated and neither is source.
OUT = HERE / "out"
DOCS = HERE / "docs"

# Spares policy, inherited verbatim from the mixer's SHOPPING.md: "enough spare
# to lose a few 0805s off a pair of tweezers, and one spare of each active."
SPARE_PASSIVE = 4
SPARE_ACTIVE = 1

# What a price line carries. `low` and `high` are the same number where the
# figure was read, and a band where it was not.
Price = collections.namedtuple(
    "Price", "low high currency qty basis source note")


def read(value, currency, qty, source, note=""):
    return Price(value, value, currency, qty, "read", source, note)


def snippet(low, high, currency, qty, source, note=""):
    return Price(low, high, currency, qty, "snippet", source, note)


def band(low, high, currency, qty, note=""):
    return Price(low, high, currency, qty, "band",
                 "typical distributor band, not read this session", note)


NONE = Price(None, None, "", 0, "none", "part not chosen", "")


# Per value string. Everything in design.ORDER_CODES needs an entry here or
# check() below complains -- a part number without a price is half a BOM line.
PRICES = {
    # -- actives -----------------------------------------------------------
    design.VCA: read(
        3.80, "GBP", 1, "https://www.thonk.co.uk/shop/ssi2164/",
        "page fetched; states \"£3.80 (Excl. VAT)\". A UK synth-DIY "
        "distributor rather than a catalogue house, which is where this part "
        "actually lives."),

    design.OPAMP: snippet(
        2.40, 4.98, "USD", 1,
        "https://octopart.com/opa1644aid-texas+instruments-18186989",
        "**Out of stock at TI itself** -- ti.com/product/OPA1644 shows "
        "'Out of stock' for both OPA1644AIDR and OPA1644AID and displays no "
        "price at all. Eight of these is the largest line on the board, so "
        "the stock position matters more than the price. See ASSUMPTIONS."),

    design.VREF_PART: snippet(
        8.76, 9.96, "USD", 1,
        "Digi-Key, via search; MAX6126B25+ at $8.76/1 and MAX6126AASA50+ at "
        "$9.96/1",
        "The exact A-grade 2.5 V part (MAX6126AASA25+) was not priced "
        "directly; this brackets it with the B grade at the same voltage and "
        "the A grade at a different one. ADR4525C/D is the second source "
        "spec section 4.2 names and is not priced here at all."),

    design.LOGIC: band(
        0.40, 0.90, "GBP", 10,
        "SN74AHC541DWR, SOIC-20W. An ordinary logic part from any of the four "
        "UK catalogue houses."),

    # -- passives ----------------------------------------------------------
    # Three classes, and the first is the one that costs something.
    "10k 0.1%": band(0.10, 0.30, "GBP", 100,
                     "Panasonic ERA-6A thin film, 0.1 %, 25 ppm. Thin film is "
                     "the specification and not the tolerance -- see FRONT_R."),
    "12k1 0.1%": band(0.10, 0.30, "GBP", 25, "ERA-6A thin film"),
    "24k3 0.1%": band(0.10, 0.30, "GBP", 25, "ERA-6A thin film"),
    "48k7 0.1%": band(0.10, 0.30, "GBP", 25, "ERA-6A thin film"),
    "97k6 0.1%": band(0.10, 0.30, "GBP", 25, "ERA-6A thin film"),

    "22k 1%": band(0.01, 0.03, "GBP", 100, "0805 thick film"),
    "17k8 1%": band(0.01, 0.03, "GBP", 100, "0805 thick film, E96"),
    "220R 1%": band(0.01, 0.03, "GBP", 100, "0805 thick film"),
    "1M 1%": band(0.01, 0.03, "GBP", 100, "0805 thick film"),
    "100k 1%": band(0.01, 0.03, "GBP", 100, "0805 thick film"),
    "0R": band(0.01, 0.03, "GBP", 100, "0805 jumper"),

    "100p/50V C0G": band(0.02, 0.08, "GBP", 100, "0805 C0G"),
    "1200p/50V C0G": band(0.02, 0.08, "GBP", 100, "0805 C0G"),
    "100n/50V C0G": band(0.15, 0.45, "GBP", 10,
                         "0805 C0G at 100 nF is a large part for the class "
                         "and priced accordingly. It is the reference's NR "
                         "capacitor, which is worth C0G."),
    "22n/50V X7R": band(0.02, 0.08, "GBP", 100, "0805 X7R"),
    "56n/50V X7R": band(0.02, 0.08, "GBP", 100, "0805 X7R"),
    "150n/50V X7R": band(0.02, 0.08, "GBP", 100, "0805 X7R"),
    "100n/50V X7R": band(0.01, 0.05, "GBP", 100, "0805 X7R"),
    "10u/16V X7R": band(0.08, 0.25, "GBP", 25, "1210 X7R"),

    # -- not chosen --------------------------------------------------------
    None: NONE,
}

# Connectors are priced by part number rather than by value, because the value
# is what the silkscreen says. The mixer does the same thing -- its J11/J13/J15
# read "TO JACKS 1/2", "3/4", "5/6" -- and a builder reading CH1..CH6 off six
# identical headers is the point of them. One part, one price, six labels.
PRICES_BY_MPN = {
    "61300211121": band(0.25, 0.60, "GBP", 10,
                        "Wurth WR-PHD 1x02 vertical, gold-plated: CONN_MPN[2]. "
                        "Two ways because the loom is a shielded pair -- the "
                        "shield lands at the mixer end only, so it has no pin "
                        "here. See design.FRONT_R."),
    "61300311121": band(0.30, 0.70, "GBP", 10,
                        "Wurth WR-PHD 1x03 vertical, gold-plated: the mixer's "
                        "own CONN_MPN[3], so the same part is at both ends of "
                        "the loom. Gold because these are signal contacts in a "
                        "box that will be opened."),
    "61300511121": band(0.40, 0.90, "GBP", 10,
                        "Wurth WR-PHD 1x05 vertical, gold-plated: CONN_MPN[5]."),
}


def price_for(value, mpn):
    """Value first, then part number. A connector's value is its label."""
    if value in PRICES:
        return PRICES[value]
    return PRICES_BY_MPN.get(mpn)

# A named representative for the one line that cannot be priced, so the board
# can be budgeted without the part being chosen. This is an envelope, not a
# selection: design.PAD_RELAY is still None and design.UNSPECIFIED still says
# why.
RELAY_ENVELOPE = Price(
    2.50, 5.00, "GBP", 12, "band",
    "envelope from a representative signal DPDT latching relay",
    "e.g. Panasonic TQ2-L2-5V class: 2-pole changeover, dual coil, 14 x 9 mm. "
    "**Not a choice.** Twelve of them is the largest single cost on the board "
    "and 49 % of its area -- see floorplan.py.")

# USD to GBP, for the total only, and stated rather than folded in silently.
# Two lines are quoted in dollars because that is the currency the figures were
# found in; converting them would hide that.
USD_GBP = None          # deliberately not set: see totals()


def lines():
    """BOM lines, grouped by value and footprint, in reference order."""
    groups = collections.defaultdict(list)
    for ref, part in design.PARTS.items():
        if not part.in_bom:
            continue
        groups[(part.value, part.footprint, part.mpn)].append(ref)

    def sort_key(ref):
        head = "".join(c for c in ref if c.isalpha())
        tail = "".join(c for c in ref if c.isdigit())
        return head, int(tail or 0)

    out = []
    for (value, footprint, mpn), refs in groups.items():
        refs.sort(key=sort_key)
        active = footprint is None or "SO" in (footprint or "")
        price = RELAY_ENVELOPE if value is None else price_for(value, mpn)
        out.append({
            "refs": refs,
            "value": value,
            "footprint": footprint,
            "mpn": mpn,
            "fitted": len(refs),
            "order": len(refs) + (SPARE_ACTIVE if active else SPARE_PASSIVE),
            "price": price,
            "unspecified": value in design.UNSPECIFIED,
        })
    return sorted(out, key=lambda row: sort_key(row["refs"][0]))


def totals(rows):
    """Extended cost, per currency, as a range.

    Kept per currency rather than converted. Two lines were priced in dollars
    because that is the currency they were found in, and folding them into a
    sterling total at a rate nobody looked up would turn two honest figures
    into one invented one.
    """
    out = collections.defaultdict(lambda: [0.0, 0.0])
    unpriced = []
    for row in rows:
        price = row["price"]
        if price is None or price.low is None:
            unpriced.append(row)
            continue
        out[price.currency][0] += price.low * row["fitted"]
        out[price.currency][1] += price.high * row["fitted"]
    return dict(out), unpriced


def check(rows):
    """Every line has a part number and a price, or says why it has neither."""
    problems = []
    for row in rows:
        if not row["mpn"] and not row["unspecified"] and row["value"] is not None:
            problems.append(f"{row['refs'][0]}: no MPN and not in UNSPECIFIED")
        if row["price"] is None:
            problems.append(
                f"{row['refs'][0]} ({row['value']!r}): no entry in PRICES -- "
                f"a part number without a price is half a BOM line")
    stale = sorted(set(PRICES) - {r["value"] for r in rows} - {None})
    stale += sorted(set(PRICES_BY_MPN) - {r["mpn"] for r in rows})
    if stale:
        problems.append(f"PRICES has entries for nothing on the board: {stale}")
    return problems


def write_csv(rows):
    path = OUT / "cv-module-bom.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Reference", "Value", "Footprint", "MPN", "Fitted",
                         "Order", "Unit low", "Unit high", "Currency",
                         "Qty break", "Basis", "Source"])
        for row in rows:
            price = row["price"]
            writer.writerow([
                ",".join(row["refs"]), row["value"] or "NOT CHOSEN",
                row["footprint"] or "", row["mpn"],
                row["fitted"], row["order"],
                "" if price.low is None else f"{price.low:.2f}",
                "" if price.high is None else f"{price.high:.2f}",
                price.currency, price.qty or "", price.basis, price.source,
            ])
    return path


def write_shopping(rows):
    path = DOCS / "SHOPPING.md"
    lines_out = [
        "# cv-module: what to buy, and from where",
        "",
        "Generated by `gen_bom.py`. Quantities are for **one board**.",
        "",
        "The convention is the mixer's, inherited rather than invented: "
        "**Mouser UK catalogue searches keyed on the manufacturer's part "
        "number**, not product-page deep links, because \"a search survives a "
        "part being re-listed, which a deep link does not\". **These links "
        "have not been opened.** A guessed Digi-Key product URL tried while "
        "writing this file resolved to a HIWIN linear rail, which is the "
        "failure that warning describes.",
        "",
        "The `order` column carries spares on the mixer's rule: "
        f"{SPARE_PASSIVE} spare of each passive, {SPARE_ACTIVE} of each active.",
        "",
        "## The basis column, and why the totals are a range",
        "",
        "| basis | meaning |",
        "|---|---|",
        "| `read` | a page was fetched in this session and states this figure |",
        "| `snippet` | a search result quoted a distributor's figure; the page itself was not opened |",
        "| `band` | a typical band for the class at the stated quantity. **Not read from anything.** |",
        "| `none` | the part is not chosen, so it has no price by construction |",
        "",
        "Only one line on this board is `read`. That is worth stating plainly "
        "rather than letting a tidy table imply otherwise.",
        "",
        "## Lines",
        "",
        "| Ref | Value | MPN | Fitted | Order | Unit | Basis | Mouser UK |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        price = row["price"]
        refs = row["refs"]
        span = (f"{refs[0]}–{refs[-1]}" if len(refs) > 2
                else ", ".join(refs))
        if price.low is None:
            unit = "—"
        elif price.low == price.high:
            unit = f"{price.currency} {price.low:.2f}"
        else:
            unit = f"{price.currency} {price.low:.2f}–{price.high:.2f}"
        mpn = row["mpn"] or "**not chosen**"
        link = (f"[search](https://www.mouser.co.uk/c/?q={row['mpn']})"
                if row["mpn"] else "—")
        lines_out.append(
            f"| {span} | {row['value'] or 'NOT CHOSEN'} | `{mpn}` | "
            f"{row['fitted']} | {row['order']} | {unit} | {price.basis} | "
            f"{link} |")

    sums, unpriced = totals(rows)
    lines_out += ["", "## Totals, per currency, fitted quantities", ""]
    for currency, (low, high) in sorted(sums.items()):
        lines_out.append(f"- **{currency} {low:.2f} – {high:.2f}**")
    lines_out += [
        "",
        "Kept per currency rather than converted: two lines were priced in "
        "dollars because that is the currency the figures were found in, and "
        "folding them into a sterling total at a rate nobody looked up would "
        "turn two honest figures into one invented one.",
        "",
        "## Notes per line",
        "",
    ]
    for row in rows:
        if row["price"].note:
            refs = row["refs"]
            span = (f"{refs[0]}–{refs[-1]}" if len(refs) > 2
                    else ", ".join(refs))
            lines_out.append(f"**{span}** — {row['price'].note}")
            lines_out.append("")

    lines_out += ["## Not on this BOM", ""]
    lines_out.append("The deferred blocks, each with its reason. None of them "
                     "is costed here, so the totals above are a floor for the "
                     "module and not its price.")
    lines_out.append("")
    for block, reason in sorted(design.DEFERRED.items()):
        lines_out.append(f"- **{block}** — {reason}")
    path.write_text("\n".join(lines_out) + "\n")
    return path


def main():
    OUT.mkdir(exist_ok=True)
    DOCS.mkdir(exist_ok=True)
    rows = lines()
    problems = check(rows)
    print(f"bom: {len(rows)} order lines, "
          f"{sum(r['fitted'] for r in rows)} placements")
    for problem in problems:
        print(f"  {problem}")

    sums, unpriced = totals(rows)
    bases = collections.Counter(
        r["price"].basis if r["price"] else "MISSING" for r in rows)
    print(f"  provenance: " + ", ".join(f"{k} {v}" for k, v in sorted(bases.items())))
    for currency, (low, high) in sorted(sums.items()):
        print(f"  total {currency} {low:.2f} - {high:.2f}")
    if unpriced:
        print(f"  unpriced: {[r['refs'][0] for r in unpriced]}")

    # Both paths named relative to the repo, not by .name, because this file now
    # writes into two directories and "wrote SHOPPING.md" no longer says where.
    for path in (write_csv(rows), write_shopping(rows)):
        print(f"  wrote {path.relative_to(HERE)}")
    if problems:
        raise SystemExit(f"{len(problems)} problems")


if __name__ == "__main__":
    main()
