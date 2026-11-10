"""cocotb testbench for nco.sv against the bit-exact dsplib.nco model.

just test-hdl nco            # batch (CI)
PLOT=1 just test-hdl nco     # also open time/frequency plots of the captured output
"""

import cocotb
import numpy as np
import pytest
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge
from dsplib import sim
from dsplib.nco import nco
from dsplib.plot import save_capture
from dsplib.spectral import sfdr_db

LATENCY = 5  # en -> valid cycles; must match nco.sv
N_FFT = 16384
SPUR_INC = 0x0123_4567  # nonzero low bits -> worst-case phase-truncation spurs


def model_kwargs() -> dict:
    p = sim.dut_params()
    return {
        "phase_w": p["PHASE_W"],
        "addr_w": p["ADDR_W"],
        "out_w": p["OUT_W"],
        "dither": bool(p["DITHER"]),
    }


async def run_stimulus(dut, stim):
    """Drive (en, phase_inc) one per cycle after reset. Returns the enabled cycles, and the
    cycles and (cos, sin) values of every valid output."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst.value = 1
    dut.en.value = 0
    dut.phase_inc.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst.value = 0

    out_cycles, out = [], []

    async def monitor():
        cycle = 0
        while True:
            await RisingEdge(dut.clk)
            await ReadOnly()
            cycle += 1  # outputs registered at edge k are seen in cycle k+1
            if dut.valid.value:
                out_cycles.append(cycle)
                out.append(
                    (dut.cos_out.value.to_signed(), dut.sin_out.value.to_signed())
                )

    cocotb.start_soon(monitor())
    for en, inc in stim:
        dut.en.value = en
        dut.phase_inc.value = inc
        await RisingEdge(dut.clk)
    dut.en.value = 0
    for _ in range(LATENCY + 1):
        await RisingEdge(dut.clk)

    in_cycles = [i for i, (en, _) in enumerate(stim) if en]
    return np.array(in_cycles), np.array(out_cycles), np.array(out).reshape(-1, 2)


@cocotb.test()
async def nco_bit_exact_and_latency(dut):
    """Gapped enables and frequency changes, including extremes: every output must match the
    model bit-for-bit and arrive exactly LATENCY cycles after its enable."""
    rng = np.random.default_rng(0)
    incs = [
        0,
        1,
        2**31,
        2**32 - 1,
        SPUR_INC,
        *rng.integers(0, 2**32, 5, dtype=np.uint64).tolist(),
    ]
    stim = [(int(rng.random() < 0.75), inc) for inc in incs for _ in range(300)]

    in_cycles, out_cycles, out = await run_stimulus(dut, stim)

    cos, sin = nco([inc for en, inc in stim if en], **model_kwargs())
    assert len(out) == len(cos), f"got {len(out)} outputs, expected {len(cos)}"
    np.testing.assert_array_equal(out_cycles - in_cycles, LATENCY, "output timing")
    np.testing.assert_array_equal(out[:, 0], cos, "cos")
    np.testing.assert_array_equal(out[:, 1], sin, "sin")


@cocotb.test()
async def nco_sfdr(dut):
    """Continuous tone at a spur-prone frequency: check bit-exactness and SFDR.
    Undithered SFDR is phase-truncation limited to ~6.02 dB/bit; dither must clear that by 12 dB."""
    p = sim.dut_params()
    phase_bits = p["ADDR_W"] + 2
    min_sfdr = 6.02 * phase_bits + (12 if p["DITHER"] else -1)

    _, _, out = await run_stimulus(dut, [(1, SPUR_INC)] * N_FFT)

    x = out[:, 0] + 1j * out[:, 1]
    sfdr = sfdr_db(x)
    save_capture(
        "sfdr",
        x,
        f_out=SPUR_INC / 2 ** p["PHASE_W"],
        dither=p["DITHER"],
        sfdr=round(sfdr, 1),
    )
    dut._log.info(f"SFDR {sfdr:.1f} dBc (min {min_sfdr:.1f})")
    cos, sin = nco(SPUR_INC, N_FFT, **model_kwargs())
    np.testing.assert_array_equal(x, cos + 1j * sin)
    assert sfdr >= min_sfdr


@pytest.mark.parametrize("dither", [0, 1])
def test_nco(dither):
    sim.run(
        "nco",
        parameters={"PHASE_W": 32, "ADDR_W": 10, "OUT_W": 16, "DITHER": dither},
        tag=f"dither{dither}",
    )
