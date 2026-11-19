# dsp-lib

Library of DSP blocks for rapid FPGA and SDR use. A set of performant FPGA and SW primitives, along with associated modeling and algorithmic verification code, for allowing AI tools to quickly create, modify, and deploy real-time waveforms and SDR systems for applications like: novel communication links that adapt to their environment, hybrid RF sensing modalities, etc.

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
│   ├── src/dsplib/          # models (fir.py, nco.py), fixed-point utils, sim/synth runners, plotting
│   └── tests/               # pure-Python model tests (no HDL)
├── hdl/
│   ├── common/              # shared packages, primitives, utility modules
│   └── <block>/
│       ├── <block>.sv
│       ├── files.f          # filelist, shared by Verilator, cocotb and Vivado
│       ├── test_<block>.py  # cocotb test, imports dsplib
│       ├── synth.toml       # Vivado target clock, parameter sets, expected primitive counts
│       └── README.md        # algorithm (math), dataflow (mermaid), interface, synth results
├── rust/                    # one crate per kernel (rust/fir/, rust/nco/, ...)
├── scripts/vivado/          # synth.tcl: non-project, out-of-context synth + place & route
├── examples/                # OTA demos with PLUTO
├── docs/
└── build/                   # gitignored: sim and synth outputs
```

In this way:
- `uv sync`, `cargo build` and `just` all work from the repo root with no extra config. The Cargo workspace and `rust-toolchain.toml` pin Rust, and `uv` pins Python.
- HDL tests live beside the HDL as the SV, `files.f`, cocotb test and `synth.toml` sit in one directory. The Python model stays in `dsplib` because the testbench, notebooks and `examples/` all reuse it.
- One Vivado entry point as `just synth <block>` reads `hdl/<block>/synth.toml`, runs the shared Tcl once per parameter set and writes the results into the block's README, so every block has the same calling convention (also what Claude Code uses). Note Vivado is local only, CI runs the Verilator/cocotb, pytest and cargo jobs. `just synth` is a manual step, run when a block's HDL changes; `just synth-check` (no Vivado) catches READMEs whose results are older than the HDL.
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

> [!IMPORTANT]
> `just synth` needs Vivado on your `PATH`. In each shell you run it from, first source the settings script from **your** install, e.g.
> `source /tools/Xilinx/2025.1/Vivado/settings64.sh` (the path and version depend on where and what you installed).
> Synthesis targets the ADALM PLUTO's Zynq-7010 (`xc7z010clg225-1`) and was developed with Vivado 2025.1. `just doctor` lists Vivado as optional.

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
- `hdl/<block>/synth.toml` lists the Vivado parameter sets and the primitives each should map to (see [Synthesis](#synthesis)).
- `hdl/<block>/README.md` documents the block: the algorithm in GitHub math (`` $`...`$ `` inline, ```` ```math ```` blocks), a ```` ```mermaid ```` dataflow diagram, the parameter/port interface, what the tests check, and the intended FPGA mapping, followed by the generated synthesis results. [`hdl/nco/README.md`](hdl/nco/README.md) is the reference.

## Synthesis

Vivado checks that a block maps to the intended primitives (DSP48s fully pipelined, ROMs in BRAM with output registers, ...), how much of the PLUTO's Zynq-7010 it uses, and whether it closes timing. This is local only, and needs Vivado sourced (see [Prerequisites](#prerequisites)).

```
just synth <block>                  # every config in hdl/<block>/synth.toml; updates hdl/<block>/README.md
just synth <block> --tag <tag>      # one config (README not updated)
just synth <block> --synth-only     # skip place & route: faster, optimistic timing (README not updated)
just synth-check                    # no Vivado: list blocks whose README results are older than their HDL
```

- For each `[[config]]`, [`scripts/vivado/synth.tcl`](scripts/vivado/synth.tcl) runs a non-project, out-of-context synth + place & route of `hdl/<block>/files.f` with that config's parameters into `build/<block>/synth/<tag>/`. That directory gets utilization/timing/DRC reports, `vivado.log`, a `result.json` and `post_route.dcp`; open the checkpoint with `vivado build/<block>/synth/<tag>/post_route.dcp` to inspect the netlist or placement.
- [`dsplib.synth`](python/src/dsplib/synth.py) checks each result:
  - every `expect` entry: an uppercase primitive (`DSP48E1 = 2`, `RAMB18E1 = 1`) or a utilization group (`lut`, `lutram`, `ff`, `bram`, `dsp`), given as an exact count or `{ min, max }`
  - timing met at `period_ns`
  - no critical warnings
  - no DSP48 pipelining DRCs (`DPIP-1`, `DPOP-1`, `DPOP-2`)

  By convention, hard primitives get exact counts and LUT/FF get a ceiling about 20% above the baseline, to absorb Vivado version drift.
- When a full run passes, the generated section between the `synth:begin`/`synth:end` markers of the block README is rewritten: a resource and timing table per config, the hard-block configuration (e.g. BRAM `DOA_REG=1`), and the worst path. The marker records a hash of the block's sources and `synth.toml`; `just synth-check` compares it to the current files, so stale results are visible without Vivado.

## ToDo

- [ ] Make sure blocks and algorithms from [rfproto](https://github.com/JohnnyGOX17/rfproto) and [hdl-lib](https://github.com/JohnnyGOX17/hdl-lib) are covered here
- [ ] Show working demos Over The Air (OTA) with [ADI ADALM PLUTO SDR](https://github.com/JohnnyGOX17/PLUTO-SDR) using FPGA and SW kernels
