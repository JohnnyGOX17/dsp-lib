# dsp-lib

Library of DSP blocks for rapid FPGA and SDR use.

## Repo Layout

- Python is used to create floating-point, and sometimes fixed-point, algorithms that model the intended behavior, as well as operate as reusable methods, and bit-exact comparisons, in [cocotb](https://www.cocotb.org/) HDL testbenches- `cocotb` testbenches allow us to drive DSP kernel DUTs with complex numeric algorithms while operating with fast, open-source simulators like [Verilator](https://www.veripool.org/verilator/). The Python library is also used for reusable/common methods in testbenches, DSP algorithms, numerical analysis and plotting.
- Rust is used for host-side SW DSP kernels, mainly optimized for resource constrained edge compute like SDRs attached to a Raspberry Pi, or the small ARM cores in an FPGA SoC. In cases where SIMD exploitation is necessary, it is better to have the code statically compiled, optimized and then profiled for a specific CPU architecture, rather than trying to be overly generic or support dynamic runtime dispatch.
- SystemVerilog is used for FPGA HDL and each module has similar checks for: numeric/algorithmic correctness (e.g. aforementioned Python `cocotb` testbenches) and synthesis mapping (e.g. common scripting to Xilinx Vivado to check a block maps to the proper DSP48 blocks, estimates resource utilization and even timing closure estimate for a given architecture like UltraScale+).
- Top-level [justfile](./justfile) for local, and CI/CD, processes of running all HDL testbenches, and SW tests, as well as any builds.
- The top level is split by language, since each toolchain wants its own root. Within each language, a block (ideally) uses the same name everywhere (`fir`, `nco`, `cic`, ...) so it is easy to find across Python, HDL and Rust.

```
dsp-lib/
├── justfile                 # test-py, test-hdl, test-rust, synth, ci
├── pyproject.toml           # uv project; python/ is the one package
├── Cargo.toml               # workspace root: members = ["rust/*"]
├── rust-toolchain.toml
├── .github/workflows/
├── python/
│   ├── src/dsplib/          # models (fir.py, nco.py), fixed-point utils, cocotb helpers, plotting
│   └── tests/               # pure-Python model tests (no HDL)
├── hdl/
│   ├── common/              # shared packages, primitives, utility modules
│   └── <block>/
│       ├── <block>.sv
│       ├── files.f          # filelist, shared by Verilator, cocotb and Vivado
│       ├── test_<block>.py  # cocotb test, imports dsplib
│       └── synth.toml       # expectations: DSP48 count, max LUTs, target part, Fmax
├── rust/                    # one crate per kernel (rust/fir/, rust/nco/, ...)
├── scripts/vivado/          # one synth.tcl and one report parser, called per block
├── examples/                # OTA demos with PLUTO
├── docs/
└── build/                   # gitignored: sim and synth outputs
```

In this way:
- `uv sync`, `cargo build` and `just` all work from the repo root with no extra config. The Cargo workspace and `rust-toolchain.toml` pin Rust, and `uv` pins Python.
- HDL tests live beside the HDL as the SV, `files.f`, cocotb test and `synth.toml` sit in one directory. The Python model stays in `dsplib` because the testbench, notebooks and `examples/` all reuse it.
- One Vivado entry point as `just synth <block>` reads `hdl/<block>/synth.toml` and runs the shared Tcl, so every block has the same calling convention (also what Claude Code uses). Note Vivado is local only, CI runs the Verilator/cocotb, pytest and cargo jobs. `just synth` is a manual or self-hosted step.
- Block discovery via `just test-hdl` globbing `hdl/*/files.f`, so adding a block needs no registration.

## Prerequisites

System tools, installed once per machine ([Vivado](https://www.amd.com/en/products/software/adaptive-socs-and-fpgas/vivado.html) is optional and only needed for `just synth`; it is a manual install and not supported on macOS):

| Tool | Used for | macOS | Linux |
| --- | --- | --- | --- |
| [just](https://just.systems) | task runner | `brew install just` | `apt install just` / `cargo install just` |
| [uv](https://docs.astral.sh/uv/) | Python + deps | `brew install uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| [rustup](https://rustup.rs) | Rust toolchain | `brew install rustup` or the rustup.rs script | rustup.rs script |
| [Verilator](https://www.veripool.org/verilator/) (5.x) | HDL simulation | `brew install verilator` | build from source if the distro package is older than 5.x |
| [Verible](https://github.com/chipsalliance/verible) | SV lint/format | [release binaries](https://github.com/chipsalliance/verible/releases) | [release binaries](https://github.com/chipsalliance/verible/releases) |

`just doctor` checks that these are on your `PATH`.

**NOTE:** Verilator calls `python3` while building cocotb sims, so always run simulations through `uv run` (or `just`) so the project's Python is first on `PATH`.

## Setup

```
just setup
```

Runs `just doctor`, then `uv sync` (**NOTE:** Python 3.13 venv pinned in `.python-version` because `cocotb` does not yet support Python 3.15+) and installs the `clippy` and `rustfmt` Rust components. It is safe to rerun.

## Develop & Test

```
just test-py                  # Python model tests (python/tests)
just test-hdl                 # every HDL testbench; `just test-hdl <block>` for one block
PLOT=1 just test-hdl <block>  # ...and open time/frequency plots of what the testbench captured
just plot <block>             # replay the last run's plots without re-simulating
```

Each DSP block follows the pattern:
- `python/src/dsplib/<block>.py` is a bit-exact model; `python/tests/test_<block>_model.py` checks it against ideal math (the `_model` suffix keeps it from clashing with the `cocotb` test module name).
- `hdl/<block>/test_<block>.py` holds the `@cocotb.test()` coroutines (not named `test_*`, so pytest skips them) and one pytest function that calls `dsplib.sim.run(block, parameters, tag)` per parameter set. Each set builds into `build/<block>/<tag>/`, and the cocotb tests read the parameters back with `sim.dut_params()`.
- Testbenches compare DUT output bit-exactly against the model, check timing (latency, gaps), and check quality metrics (e.g. SFDR via `dsplib.spectral`) against limits from theory.
- Call `dsplib.plot.save_capture(name, x, **meta)` *before* asserting, so a failing run still leaves something to plot. With `PLOT=1` the plots open after the sim, including on failure, though they never open when `CI` is set.

## ToDo

- [ ] Have Xilinx Vivado toolchain accessible/scriptable by Claude Code to verify synthesis, mapping (e.g. proper DSP48 inference) and resource utilization using a common calling convention per block.
- [ ] Make sure blocks and algorithms from [rfproto](https://github.com/JohnnyGOX17/rfproto) and [hdl-lib](https://github.com/JohnnyGOX17/hdl-lib) are covered here
- [ ] Show working demos Over The Air (OTA) with [ADI ADALM PLUTO SDR](https://github.com/JohnnyGOX17/PLUTO-SDR) using FPGA and SW kernels
