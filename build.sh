#!/bin/sh
# Regenerate everything generated, then verify the board on disk.
# Never writes the board: gen_pcb.py, krt.py and returns.py do that, by hand.

set -eu
cd "$(dirname "$0")"

printf '=== prerequisites\n'
python3 -m toolchain.kicad          # locates KiCad, checks the major, exits 1 if absent

for stage in \
    design gen_netlist gen_sch gen_project placement \
    verify test_verify \
    constraints delta floorplan \
    gen_bom gen_assumptions rules \
    gen_plots gen_fab
do
    printf '\n=== %s.py\n' "$stage"
    if ! python3 "$stage.py"; then
        printf '\n*** %s.py failed\n' "$stage" >&2
        exit 1
    fi
done

printf '\n=== all stages passed\n'
