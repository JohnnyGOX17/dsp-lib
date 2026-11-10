"""Build and run a block's cocotb tests on Verilator. Shared by every hdl/<block>/test_<block>.py:

    @pytest.mark.parametrize("dither", [0, 1])
    def test_nco(dither):
        sim.run("nco", parameters=dict(DITHER=dither), tag=f"dither{dither}")

Sources come from hdl/<block>/files.f (paths relative to the repo root). Each parameter set
builds into build/<block>/<tag>/, which also holds that run's results and plot captures.
"""

import json
import os
from pathlib import Path

from cocotb_tools.runner import get_runner

from dsplib import plot

REPO = Path(__file__).resolve().parents[3]


def run(
    block: str,
    parameters: dict | None = None,
    tag: str = "default",
    toplevel: str | None = None,
) -> None:
    parameters = parameters or {}
    files_f = REPO / "hdl" / block / "files.f"
    sources = [REPO / s for s in files_f.read_text().split() if not s.startswith("#")]
    build_dir = REPO / "build" / block / tag
    for old in build_dir.glob("*.npz"):
        old.unlink()

    runner = get_runner("verilator")
    runner.build(
        sources=sources,
        hdl_toplevel=toplevel or block,
        parameters=parameters,
        build_dir=build_dir,
    )
    try:
        runner.test(
            test_module=f"test_{block}",
            hdl_toplevel=toplevel or block,
            build_dir=build_dir,
            extra_env={
                "DUT_PARAMS": json.dumps(parameters),
                "CAPTURE_DIR": str(build_dir),
            },
        )
    finally:  # plot on failure too: that is when it is most useful
        if plot.plot_enabled():
            plot.show(sorted(build_dir.glob("*.npz")))


def dut_params() -> dict:
    """Inside a sim: the HDL parameters this build was elaborated with."""
    return json.loads(os.environ["DUT_PARAMS"])
