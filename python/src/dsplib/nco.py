"""Numerically Controlled Oscillator (NCO) model, bit-exact with hdl/nco/nco.sv.

A phase accumulator drives a quarter-wave sine table: the top 2 bits of the truncated
phase select the quadrant, which mirrors the table address and/or negates its output.
The table is sampled at half-LSB offsets, sin(pi/2 * (k + 0.5) / N), so mirroring is
an exact bitwise invert of the address and no entry is ever 0 (negation is symmetric).

Optional dither adds uniform LFSR noise below the truncation point before the phase is
truncated, trading phase-truncation spurs for a raised noise floor.
"""

import math

import numpy as np

from dsplib.lfsr import lfsr


def quarter_sine_table(addr_w: int, out_w: int) -> np.ndarray:
    n = 1 << addr_w
    amp = (1 << (out_w - 1)) - 1
    # math.sin is libm sin(), the same call Verilator's $sin makes; np.sin may differ by an ULP.
    return np.array(
        [
            math.floor(amp * math.sin(math.pi / 2 * (k + 0.5) / n) + 0.5)
            for k in range(n)
        ]
    )


def nco(
    phase_inc,
    n: int | None = None,
    phase_w: int = 32,
    addr_w: int = 10,
    out_w: int = 16,
    dither: bool = False,
    lfsr_seed: int = 1,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (cos, sin) integer outputs for `n` samples.

    `phase_inc` is a scalar (needs `n`) or a per-sample array, so frequency changes are
    modeled at the sample they take effect. The first sample has phase 0.
    """
    inc = np.broadcast_to(
        np.asarray(phase_inc, dtype=np.uint64), (n,) if n else np.shape(phase_inc)
    )
    mask = np.uint64((1 << phase_w) - 1)
    # uint64 wraparound is a multiple of 2**phase_w, so masking after cumsum is exact.
    acc = (
        np.concatenate(([0], np.cumsum(inc[:-1], dtype=np.uint64))).astype(np.uint64)
        & mask
    )

    trunc_w = phase_w - (addr_w + 2)
    if dither:
        acc = (
            acc + (lfsr(len(acc), seed=lfsr_seed) & np.uint64((1 << trunc_w) - 1))
        ) & mask
    phase = (acc >> np.uint64(trunc_w)).astype(np.int64)

    addr = phase & ((1 << addr_w) - 1)
    q0 = (phase >> addr_w) & 1
    q1 = (phase >> (addr_w + 1)) & 1
    table = quarter_sine_table(addr_w, out_w)
    inv = (1 << addr_w) - 1
    sin_mag = table[np.where(q0 == 1, inv - addr, addr)]
    cos_mag = table[np.where(q0 == 1, addr, inv - addr)]
    sin = np.where(q1 == 1, -sin_mag, sin_mag)
    cos = np.where((q1 ^ q0) == 1, -cos_mag, cos_mag)
    return cos, sin
