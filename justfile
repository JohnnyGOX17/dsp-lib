# Check system tools are installed (see README Prerequisites)
doctor:
    #!/usr/bin/env bash
    rc=0
    for t in just uv rustup cargo verilator verible-verilog-lint; do
        command -v $t >/dev/null || { echo "MISSING: $t"; rc=1; }
    done
    exit $rc

# Install project dependencies (Python env, Rust components)
setup: doctor
    uv sync
    rustup component add clippy rustfmt
