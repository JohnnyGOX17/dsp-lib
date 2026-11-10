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

## ToDo

- [ ] Have Xilinx Vivado toolchain accessible/scriptable by Claude Code to verify synthesis, mapping (e.g. proper DSP48 inference) and resource utilization using a common calling convention per block.
- [ ] Make sure blocks and algorithms from [rfproto](https://github.com/JohnnyGOX17/rfproto) and [hdl-lib](https://github.com/JohnnyGOX17/hdl-lib) are covered here
- [ ] Show working demos Over The Air (OTA) with [ADI ADALM PLUTO SDR](https://github.com/JohnnyGOX17/PLUTO-SDR) using FPGA and SW kernels
