# Check system tools are installed (see README Prerequisites)
doctor:
    #!/usr/bin/env bash
    rc=0
    for t in just uv rustup cargo verilator verible-verilog-lint; do
        command -v $t >/dev/null || { echo "MISSING: $t"; rc=1; }
    done
    command -v vivado >/dev/null || echo "optional: vivado not on PATH (only needed for just synth; source Vivado's settings64.sh)"
    exit $rc

# Install project dependencies (Python env, Rust components)
setup: doctor
    uv sync
    rustup component add clippy rustfmt

# Format SystemVerilog in place (4-space indent); `just fmt --verify` to only check
fmt *args:
    find hdl -name '*.sv' -o -name '*.svh' | xargs -r verible-verilog-format --indentation_spaces=4 --wrap_spaces=4 --inplace {{ if args == "--verify" { "--verify" } else { "" } }}

# Lint SystemVerilog; rules come from .rules.verible_lint if present
lint:
    find hdl -name '*.sv' -o -name '*.svh' | xargs -r verible-verilog-lint --rules_config_search

# Run Python model tests
test-py *args:
    uv run pytest python/tests {{ args }}

# Run HDL testbenches, all or one block (`just test-hdl nco`); PLOT=1 opens capture plots
test-hdl *args:
    #!/usr/bin/env bash
    set -eu -- {{ args }}
    dir=hdl; if [[ $# -gt 0 && $1 != -* ]]; then dir=hdl/$1; shift; fi
    uv run pytest "$dir" "$@"

# Replay a block's saved captures without re-simulating
plot block:
    uv run python -m dsplib.plot build/{{ block }}

# Vivado synth + place & route of one block vs hdl/<block>/synth.toml (local; source Vivado's settings64.sh first)
synth block *args:
    uv run python -m dsplib.synth {{ block }} {{ args }}

# Check each block's README synthesis results match its current sources (no Vivado needed)
synth-check:
    uv run python -m dsplib.synth --check
